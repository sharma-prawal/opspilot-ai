"""v0.11 AWS CloudWatch connector: authentication, scope, Logs Insights lifecycle, metrics, limits and read-only use.

Two kinds of tests, neither needing an AWS account:
- botocore ``Stubber`` tests validate every request against the official service model (parameter names, types and
  the exact values sent) and every canned response against its output shape;
- fixture tests run the loopback protocol fixture (``scripts/cloudwatch_fixture.py``) behind the real SDK.
"""

# ruff: noqa: E501 - parametrized resource-mapping cases are kept one per line
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from opspilot_shared.connectors.base import Limits
from opspilot_shared.connectors.cloudwatch import (
    CONCURRENCY,
    MAX_POLLS,
    CloudWatchConnector,
    aws_error,
    bin_expr,
    build_session,
    check_region,
    metric_period,
    parse_insights_ts,
)
from opspilot_shared.connectors.cloudwatch_resources import (
    ResourceMap,
    logs_string,
    parse_resources,
)
from opspilot_shared.connectors.contract import ConnectorError, FetchWindow
from opspilot_shared.connectors.templates import load_templates
from tests.fakes.cloudwatch import SCENARIOS, STORY, W, connector, cw, fixture_server, no_sleep

SECRET_KEY = "sentinel-secret-key-DO-NOT-LEAK-0000000"
SESSION_TOKEN = "sentinel-session-token-DO-NOT-LEAK"
ACCESS_KEY = "AKIASENTINEL00000000"
RES = parse_resources(
    {
        "services": {
            "inventory-service": {
                "log_groups": ["/ecs/shop-prod/inventory-service"],
                "metrics": {
                    "alb": {
                        "load_balancer": "app/shop-prod-internal/2b8d4f6a1c3e5a79",
                        "target_group": "targetgroup/inventory-service/8e2c4a6b1d3f5a97",
                    },
                    "custom": [
                        {
                            "id": "db_pool_wait_ms",
                            "namespace": "Shop/Inventory",
                            "metric_name": "DbConnectionWaitTime",
                            "stat": "p95",
                            "unit": "Milliseconds",
                            "dimensions": {"Service": "inventory-service"},
                        }
                    ],
                },
            },
            "shared-a": {"log_groups": ["/ecs/shared"], "service_field": "service.name"},
            "shared-b": {"log_groups": ["/ecs/shared"], "service_field": "service.name"},
        }
    }
)


def stubbed(resources: ResourceMap = RES, **kw: Any) -> tuple[CloudWatchConnector, dict[str, Stubber]]:
    clients = {
        name: boto3.client(name, region_name="us-east-1", aws_access_key_id="AKIATEST", aws_secret_access_key="x")
        for name in ("logs", "cloudwatch", "sts")
    }
    stubs = {name: Stubber(c) for name, c in clients.items()}
    for s in stubs.values():
        s.activate()
    kw.setdefault("sleep", no_sleep)
    c = CloudWatchConnector(region="us-east-1", resources=resources, limits=Limits(), clients=clients, **kw)
    return c, stubs


def identity(stubs: dict[str, Stubber], account: str = "111122223333") -> None:
    stubs["sts"].add_response(
        "get_caller_identity",
        {"Account": account, "Arn": f"arn:aws:sts::{account}:assumed-role/ReadOnly/someone@example.com", "UserId": "x"},
    )


def row(ts: str, msg: str, **fields: str) -> list[dict[str, str]]:
    cells = [{"field": "@timestamp", "value": ts}, {"field": "@message", "value": msg}]
    cells += [{"field": k, "value": v} for k, v in fields.items()]
    return [*cells, {"field": "@ptr", "value": "ptr-" + ts}]


def results(status: str, rows: list[Any] | None = None, **stats: float) -> dict[str, Any]:
    return {"status": status, "results": rows or [], "statistics": {"recordsScanned": 10.0, **stats}}


# ------------------------------------------------------------------------------------------------ configuration
@pytest.mark.parametrize(
    ("region", "problem"),
    [
        ("", "set CLOUDWATCH_REGION"),
        ("us-gov-west-1", "commercial partition"),
        ("cn-north-1", "commercial partition"),
        ("us-iso-east-1", "commercial partition"),
        ("https://logs.evil.example", "not an AWS region"),
        ("us-east-1; rm -rf", "not an AWS region"),
        ("xx-nowhere-9", "not a commercial-partition region"),
    ],
)
def test_regions_outside_the_commercial_partition_are_refused(region: str, problem: str) -> None:
    with pytest.raises(ConnectorError, match=problem) as exc:
        check_region(region)
    assert exc.value.kind == "not_configured"


def test_known_regions_are_accepted() -> None:
    assert check_region(" EU-West-1 ") == "eu-west-1"
    assert check_region("ap-southeast-2") == "ap-southeast-2"


@pytest.mark.parametrize(
    ("kw", "problem"),
    [
        ({"auth_mode": "default_chain"}, "CLOUDWATCH_AUTH_MODE must be one of"),
        ({"auth_mode": "access_keys", "local_endpoint_url": "http://127.0.0.1:9"}, "only for the synthetic fixture"),
        ({"auth_mode": "fixture", "local_endpoint_url": ""}, "needs CLOUDWATCH_LOCAL_ENDPOINT_URL"),
        ({"auth_mode": "fixture", "local_endpoint_url": "https://logs.us-east-1.amazonaws.com"}, "loopback"),
        ({"auth_mode": "fixture", "local_endpoint_url": "http://10.0.0.5:8131"}, "loopback"),
        ({"auth_mode": "profile"}, "needs CLOUDWATCH_AWS_PROFILE"),
        ({"auth_mode": "access_keys"}, "needs CLOUDWATCH_ACCESS_KEY_ID"),
        ({"auth_mode": "instance_role", "access_key_id": "AKIAX"}, "only used by access_keys"),
        ({"auth_mode": "access_keys", "access_key_id": "A", "secret_access_key": "B", "role_arn": "arn:aws-us-gov:iam::123456789012:role/x"}, "commercial partition"),
        ({"auth_mode": "access_keys", "access_key_id": "A", "secret_access_key": "B", "account_id": "12345"}, "12-digit"),
    ],
)  # fmt: skip
def test_invalid_auth_configuration_is_refused(kw: dict[str, Any], problem: str) -> None:
    with pytest.raises(ConnectorError, match=problem) as exc:
        CloudWatchConnector(region="us-east-1", resources=RES, limits=Limits(), **kw)
    assert exc.value.kind == "not_configured"


def _aws_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config").write_text("[profile ro]\nregion = us-east-1\n[profile empty]\nregion = us-east-1\n")
    (tmp_path / "credentials").write_text("[ro]\naws_access_key_id = AKIAPROFILE000000000\naws_secret_access_key = p\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAENVIRONMENT00000")  # an unrelated identity in the environment
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret")
    monkeypatch.setenv("AWS_PROFILE", "unrelated-developer-profile")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")  # never reach instance metadata from a test


def test_profile_mode_uses_only_the_named_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _aws_files(tmp_path, monkeypatch)
    creds = build_session("profile", profile="ro", region="us-east-1").get_credentials()
    assert creds.access_key == "AKIAPROFILE000000000"
    methods = {p.METHOD for p in build_session("profile", profile="ro", region="us-east-1")
               .get_component("credential_provider").providers}  # fmt: skip
    assert "env" not in methods and "iam-role" not in methods and "container-role" not in methods
    # a profile without credentials does not silently fall back to the environment or instance metadata
    assert build_session("profile", profile="empty", region="us-east-1").get_credentials() is None
    with pytest.raises(ConnectorError, match="not defined"):
        build_session("profile", profile="missing", region="us-east-1")


def test_instance_role_mode_uses_only_workload_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _aws_files(tmp_path, monkeypatch)
    resolver = build_session("instance_role", region="us-east-1").get_component("credential_provider")
    assert {p.METHOD for p in resolver.providers} == {"container-role", "iam-role", "assume-role-with-web-identity"}


def test_access_keys_mode_ignores_environment_profile_and_endpoint_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _aws_files(tmp_path, monkeypatch)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://evil.example")
    monkeypatch.setenv("AWS_ENDPOINT_URL_CLOUDWATCH_LOGS", "https://evil.example")
    c = CloudWatchConnector(
        region="eu-west-1",
        resources=RES,
        limits=Limits(),
        auth_mode="access_keys",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        session_token=SESSION_TOKEN,
    )
    assert c._clients == {}  # constructing the connector created no client and resolved no credential
    logs = c._make_client("logs")
    assert logs.meta.endpoint_url == "https://logs.eu-west-1.amazonaws.com"
    assert c._make_client("cloudwatch").meta.endpoint_url == "https://monitoring.eu-west-1.amazonaws.com"
    assert c._session.get_credentials().access_key == ACCESS_KEY
    text = json.dumps(c.info())
    assert SECRET_KEY not in text and SESSION_TOKEN not in text and ACCESS_KEY not in text


def test_role_arn_wraps_the_base_credentials() -> None:
    session = build_session(
        "access_keys",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        role_arn="arn:aws:iam::123456789012:role/OpsPilotReadOnly",
        region="us-east-1",
    )
    methods = [p.METHOD for p in session.get_component("credential_provider").providers]
    assert methods == ["opspilot-assume-role"]


def _client_error(code: str, message: str = "m", status: int = 400) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Op"
    )


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("ExpiredTokenException", "auth_error"),
        ("ExpiredToken", "auth_error"),
        ("UnrecognizedClientException", "auth_error"),
        ("InvalidSignatureException", "auth_error"),
        ("AccessDeniedException", "permission_denied"),
        ("ThrottlingException", "rate_limited"),
        ("LimitExceededException", "rate_limited"),
        ("ResourceNotFoundException", "not_found"),
        ("MalformedQueryException", "query_error"),
        ("ServiceUnavailableException", "unavailable"),
    ],
)
def test_aws_errors_are_typed(code: str, kind: str) -> None:
    assert aws_error(_client_error(code), "logs:StartQuery").kind == kind


def test_aws_error_messages_never_carry_principal_names() -> None:
    msg = (
        "User: arn:aws:sts::111122223333:assumed-role/AWSReservedSSO_ReadOnly_ab12/jane.doe@example.com is not "
        "authorized to perform: logs:StartQuery on resource: arn:aws:logs:us-east-1:111122223333:log-group:/x"
    )
    err = aws_error(_client_error("AccessDeniedException", msg), "logs:StartQuery")
    assert err.kind == "permission_denied" and "logs:StartQuery" in err.message
    assert "jane.doe" not in err.message and "AWSReservedSSO" not in err.message


def test_sso_and_credential_failures_are_actionable() -> None:
    from botocore.exceptions import NoCredentialsError, SSOTokenLoadError

    err = aws_error(SSOTokenLoadError(error_msg="token expired for jane@example.com"), "client", profile="ro")
    assert err.kind == "auth_error" and "aws sso login --profile ro" in err.message and "jane" not in err.message
    assert aws_error(NoCredentialsError(), "client").kind == "auth_error"


# ------------------------------------------------------------------------------------------------ resource mapping
@pytest.mark.parametrize(
    ("doc", "problem"),
    [
        ({"services": {"Orders API": {"log_groups": ["/x"]}}}, "invalid service name"),
        ({"services": {"orders": {"log_groups": ["/x y"]}}}, "log group name"),
        ({"services": {"orders": {"log_groups": ['/x"; fields *']}}}, "log group name"),
        ({"services": {"orders": {"log_groups": [f"/g{i}" for i in range(11)]}}}, "at most 10"),
        ({"services": {"svc-a": {"log_groups": ["/s"]}, "svc-b": {"log_groups": ["/s"]}}}, "set service_field"),
        ({"services": {"orders": {"log_groups": ["/x"], "service_field": "a b"}}}, "service_field"),
        ({"services": {"orders": {"metrics": {"alb": {"load_balancer": "my-lb", "target_group": "tg"}}}}}, "load_balancer"),
        ({"services": {"orders": {"metrics": {"custom": [{"id": "m", "namespace": "App", "metric_name": "CPU", "dimensions": {"a": "b"}}]}}}}, "custom metric id"),
        ({"services": {"orders": {"metrics": {"custom": [{"id": "cpu_x", "namespace": "AWS/EC2", "metric_name": "CPU", "dimensions": {"a": "b"}}]}}}}, "AWS/ namespace"),
        ({"services": {"orders": {"metrics": {"custom": [{"id": "cpu_x", "namespace": "App", "metric_name": "CPU", "unit": "Furlongs", "dimensions": {"a": "b"}}]}}}}, "standard unit"),
        ({"services": {"orders": {"metrics": {"custom": [{"id": "cpu_x", "namespace": "App", "metric_name": "CPU", "stat": "median", "dimensions": {"a": "b"}}]}}}}, "statistic"),
        ({"services": {"orders": {}}}, "map at least one"),
        ({"services": {"orders": {"log_groups": ["/x"], "endpoint": "https://x"}}}, "unknown key"),
        ({"services": {}, "region": "us-east-1"}, "unknown top-level"),
    ],
)  # fmt: skip
def test_resource_mapping_is_validated(doc: dict[str, Any], problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        parse_resources(doc)


def test_fixture_and_example_mappings_load() -> None:
    from opspilot_shared.connectors.cloudwatch_resources import load_resources

    assert "inventory-service" in load_resources(STORY).services
    assert load_resources(Path(__file__).parents[2] / "infra/cloudwatch/resources.example.yaml").log_groups
    with pytest.raises(ConnectorError, match="CLOUDWATCH_RESOURCES_FILE") as exc:
        load_resources(None)
    assert exc.value.kind == "not_configured"


def test_templates_file_cannot_add_cloudwatch_queries(tmp_path: Path) -> None:
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"templates": [{"id": "all_logs", "connector": "cloudwatch", "label": "x",
                                            "query": "fields * | limit 10000", "signal": "log"}]}))  # fmt: skip
    templates, problems = load_templates(f)
    assert not any(t.connector == "cloudwatch" for t in templates)
    assert problems and "built in" in problems[0]


def test_query_text_takes_only_validated_values() -> None:
    c, _ = stubbed()
    shared = RES.get("shared-a")
    assert shared is not None
    q = c.render_logs(c.template("cw_errors"), shared, limit=10, bin_s=None)
    assert '| filter `service.name` = "shared-a"' in q and "| limit 11" in q and "$" not in q
    assert logs_string('a"b\\c') == '"a\\"b\\\\c"'
    with pytest.raises(ConnectorError):
        logs_string("a\nb")
    metric = c.render_logs(c.template("cw_log_error_count"), RES.services["inventory-service"], limit=None, bin_s=120)
    assert "bin(2m) as @t" in metric and "$service_filter" not in metric
    assert bin_expr(60) == "1m" and bin_expr(90) == "2m" and bin_expr(7200) == "2h"


@pytest.mark.parametrize("evil", ['inventory-service" or 1=1', "inventory-service | fields *", "Inventory", "*"])
async def test_service_names_are_validated(evil: str) -> None:
    c, _ = stubbed()
    with pytest.raises(ConnectorError) as exc:
        await c.fetch(c.template("cw_errors"), evil, W)
    assert exc.value.kind == "invalid_request"


async def test_time_window_limits() -> None:
    c, _ = stubbed()
    long = FetchWindow(start=W.start - timedelta(hours=10), end=W.end)
    future = FetchWindow(start=datetime.now(UTC), end=datetime.now(UTC) + timedelta(hours=1))
    for w in (long, future, FetchWindow(start=W.end, end=W.start)):
        with pytest.raises(ConnectorError) as exc:
            await c.fetch(c.template("cw_errors"), "inventory-service", w)
        assert exc.value.kind == "invalid_request"


def test_metric_period_respects_resolution_retention() -> None:
    now = datetime(2026, 11, 20, tzinfo=UTC)
    recent = FetchWindow(start=now - timedelta(hours=2), end=now - timedelta(hours=1))
    assert metric_period(recent, now) == 60
    old = FetchWindow(start=now - timedelta(days=20), end=now - timedelta(days=20) + timedelta(hours=1))
    assert metric_period(old, now) == 300
    older = FetchWindow(start=now - timedelta(days=70), end=now - timedelta(days=70) + timedelta(hours=1))
    assert metric_period(older, now) == 3600


def test_insights_timestamps_are_utc() -> None:
    assert parse_insights_ts("2026-11-18 14:05:01.123") == datetime(2026, 11, 18, 14, 5, 1, 123000, tzinfo=UTC)
    assert parse_insights_ts("yesterday") is None and parse_insights_ts(None) is None


# ------------------------------------------------------------------------------------------------ Logs Insights (Stubber)
async def test_logs_insights_lifecycle_is_bounded_and_exact() -> None:
    c, stubs = stubbed()
    identity(stubs)
    stubs["logs"].add_response(
        "start_query",
        {"queryId": "q-1"},
        {
            "queryLanguage": "CWLI",
            "logGroupNames": ["/ecs/shop-prod/inventory-service"],
            "startTime": int(W.start.timestamp()),
            "endTime": int(W.end.timestamp()),
            "queryString": c.render_logs(c.template("cw_errors"), RES.services["inventory-service"], limit=500,
                                         bin_s=None),
            "limit": 501,
        },
    )  # fmt: skip
    stubs["logs"].add_response("get_query_results", results("Scheduled"), {"queryId": "q-1"})
    stubs["logs"].add_response("get_query_results", results("Running"), {"queryId": "q-1"})
    stubs["logs"].add_response(
        "get_query_results",
        results(
            "Complete",
            [row("2026-11-18 14:06:00.000", '{"level":"ERROR","msg":"pool timeout","traceId":"t-1"}', traceId="t-1"),
             row("2026-11-18 14:05:00.000", "plain error line", requestId="r-9")],
            bytesScanned=2048.0, recordsMatched=2.0, logGroupsScanned=1.0,
        ),
        {"queryId": "q-1"},
    )  # fmt: skip
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    for s in stubs.values():
        s.assert_no_pending_responses()  # no StopQuery: the query completed
    p = res.provenance
    assert p.status == "ok" and p.returned == 2 and not p.truncated
    assert p.aws and p.aws["query_id"] == "q-1" and p.aws["polls"] == 3 and p.aws["query_status"] == "Complete"
    assert p.aws["account"] == "111122223333" and p.aws["statistics"]["bytesScanned"] == 2048.0
    first, second = res.logs
    assert first.ts < second.ts and first.level == "ERROR" and first.level_inferred and not second.level_inferred
    assert second.trace_id == "t-1" and second.service_source == "query" and second.attributes["aws.ptr"]
    assert (
        first.attributes["correlation.requestId"] == "r-9"
        and first.source == "cloudwatch/cw_errors/inventory-service:entry 1"
    )
    assert any("billed by scanned volume" in i for i in p.issues)
    assert any("log group is mapped" in i for i in p.issues)


@pytest.mark.parametrize(
    ("status", "kind"), [("Failed", "query_error"), ("Timeout", "timeout"), ("Cancelled", "unavailable")]
)
async def test_terminal_failures_are_errors_without_stop(status: str, kind: str) -> None:
    c, stubs = stubbed()
    identity(stubs)
    stubs["logs"].add_response("start_query", {"queryId": "q-2"})
    stubs["logs"].add_response("get_query_results", results(status))
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    stubs["logs"].assert_no_pending_responses()
    assert res.provenance.status == "error" and (res.provenance.error or {})["kind"] == kind


async def test_polling_ceiling_stops_only_its_own_query_and_keeps_partial_rows() -> None:
    c, stubs = stubbed()
    identity(stubs)
    stubs["logs"].add_response("start_query", {"queryId": "q-own"})
    for _ in range(MAX_POLLS - 1):
        stubs["logs"].add_response("get_query_results", results("Running"))
    stubs["logs"].add_response("get_query_results", results("Running", [row("2026-11-18 14:06:00.000", "error x")]))
    stubs["logs"].add_response("stop_query", {"success": True}, {"queryId": "q-own"})
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    stubs["logs"].assert_no_pending_responses()
    p = res.provenance
    assert p.status == "ok" and p.truncated and p.aws and p.aws["stopped"] is True and p.aws["polls"] == MAX_POLLS
    assert any("partial" in i for i in p.issues)


async def test_query_timeout_without_rows_is_a_timeout_and_stop_failure_is_recorded() -> None:
    clock = iter(range(0, 10_000, 30))
    c, stubs = stubbed(query_timeout=60, monotonic=lambda: float(next(clock)))
    identity(stubs)
    stubs["logs"].add_response("start_query", {"queryId": "q-3"})
    stubs["logs"].add_response("get_query_results", results("Running"))
    stubs["logs"].add_response("get_query_results", results("Running"))
    stubs["logs"].add_client_error("stop_query", "ServiceUnavailableException", http_status_code=500)
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    p = res.provenance
    assert p.status == "error" and (p.error or {})["kind"] == "timeout"
    assert p.aws and p.aws["stopped"] is False and "60-minute" in p.aws["stop_error"]


async def test_truncation_is_detected_with_one_extra_row() -> None:
    c, stubs = stubbed(max_records=10)
    identity(stubs)
    stubs["logs"].add_response("start_query", {"queryId": "q-4"})
    rows = [row(f"2026-11-18 14:{m:02d}:00.000", f"error {m}") for m in range(11)]
    stubs["logs"].add_response("get_query_results", results("Complete", rows))
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    assert res.provenance.returned == 10 and res.provenance.truncated
    assert any("10 most recent" in i and "earlier occurrences may exist" in i for i in res.provenance.issues)


async def test_unmapped_resources_are_not_queried() -> None:
    c, stubs = stubbed()
    res = await c.fetch(c.template("cw_errors"), "unknown-svc", W)
    assert res.provenance.status == "error" and "not mapped" in (res.provenance.error or {})["message"]
    assert res.provenance.aws and res.provenance.aws["not_queried"]
    res = await c.fetch(c.template("alb_target_5xx"), "shared-a", W)
    assert (res.provenance.error or {})["kind"] == "not_configured"
    for s in stubs.values():
        s.assert_no_pending_responses()  # nothing was sent to AWS


async def test_expected_account_mismatch_blocks_queries() -> None:
    c, stubs = stubbed(account_id="999999999999")
    identity(stubs)
    res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
    assert res.provenance.status == "error" and "999999999999" in (res.provenance.error or {})["message"]
    stubs["logs"].assert_no_pending_responses()


# ------------------------------------------------------------------------------------------------ metrics (Stubber)
async def test_metric_request_uses_exact_dimensions_and_keeps_units_and_gaps() -> None:
    c, stubs = stubbed()
    identity(stubs)
    t0 = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)
    stubs["cloudwatch"].add_response(
        "get_metric_data",
        {
            "MetricDataResults": [
                {"Id": "m0", "Label": "TargetResponseTime", "Timestamps": [t0, t0 + timedelta(minutes=2)],
                 "Values": [0.02, 1.9], "StatusCode": "PartialData"}
            ],
            "NextToken": "page-2",
        },
        {
            "MetricDataQueries": [{"Id": "m0", "MetricStat": {"Metric": {"Namespace": "AWS/ApplicationELB",
                "MetricName": "TargetResponseTime", "Dimensions": [
                    {"Name": "LoadBalancer", "Value": "app/shop-prod-internal/2b8d4f6a1c3e5a79"},
                    {"Name": "TargetGroup", "Value": "targetgroup/inventory-service/8e2c4a6b1d3f5a97"}]},
                "Period": 60, "Stat": "p95"}, "ReturnData": True}],
            "StartTime": W.start, "EndTime": W.end, "ScanBy": "TimestampAscending", "MaxDatapoints": 2000,
        },
    )  # fmt: skip
    stubs["cloudwatch"].add_response(
        "get_metric_data",
        {"MetricDataResults": [{"Id": "m0", "Timestamps": [t0 + timedelta(minutes=3), t0], "Values": [1.8, 0.02],
                                "StatusCode": "Complete"}]},
    )  # fmt: skip
    res = await c.fetch(c.template("alb_target_response_p95"), "inventory-service", W)
    stubs["cloudwatch"].assert_no_pending_responses()
    p = res.provenance
    assert p.status == "ok" and p.pages == 2 and p.step_seconds == 60 and not p.truncated
    values = [(m.ts, m.value) for m in res.metrics]
    assert values == [(t0, 0.02), (t0 + timedelta(minutes=2), 1.9), (t0 + timedelta(minutes=3), 1.8)]  # no fill
    m = res.metrics[0]
    assert m.metric == "alb_target_response_p95_s" and m.unit == "Seconds" and m.labels["stat"] == "p95"
    assert m.labels["dim.TargetGroup"] == "targetgroup/inventory-service/8e2c4a6b1d3f5a97"
    assert any("had no datapoint" in i and "never filled with zero" in i for i in p.issues)


async def test_custom_metrics_forbidden_and_page_ceiling() -> None:
    c, stubs = stubbed()
    identity(stubs)
    stubs["cloudwatch"].add_response(
        "get_metric_data",
        {"MetricDataResults": [{"Id": "m0", "Timestamps": [], "Values": [], "StatusCode": "Forbidden"}]},
    )
    res = await c.fetch(c.template("custom_metrics"), "inventory-service", W)
    assert res.provenance.status == "error" and (res.provenance.error or {})["kind"] == "permission_denied"
    t0 = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)
    for i in range(3):
        stubs["cloudwatch"].add_response(
            "get_metric_data",
            {"MetricDataResults": [{"Id": "m0", "Timestamps": [t0 + timedelta(minutes=i)], "Values": [5.0 + i],
                                    "StatusCode": "PartialData"}], "NextToken": f"t{i}"},
        )  # fmt: skip
    res = await c.fetch(c.template("custom_metrics"), "inventory-service", W)
    p = res.provenance
    assert p.returned == 3 and p.truncated and any("more datapoints after 3 page(s)" in i for i in p.issues)
    assert res.metrics[0].metric == "db_pool_wait_ms" and res.metrics[0].unit == "Milliseconds"


async def test_mismatched_metric_lengths_are_rejected() -> None:
    c, stubs = stubbed()
    identity(stubs)
    stubs["cloudwatch"].add_response(
        "get_metric_data",
        {"MetricDataResults": [{"Id": "m0", "Timestamps": [datetime(2026, 11, 18, 14, tzinfo=UTC)], "Values": [],
                                "StatusCode": "Complete"}]},
    )  # fmt: skip
    res = await c.fetch(c.template("alb_target_5xx"), "inventory-service", W)
    assert (res.provenance.error or {})["kind"] == "invalid_response"


# ------------------------------------------------------------------------------------------------ protocol fixture
async def test_story_through_the_real_sdk_and_wire_protocol() -> None:
    with fixture_server() as srv:
        c = connector(srv.url)
        st = await c.test()
        assert st.status == "partial" and st.identity == {
            "account": cw.ACCOUNT, "principal": "assumed role", "region": "us-east-1", "role": "OpsPilotReadOnly",
        }  # fmt: skip
        assert st.signals and {k: v.status for k, v in st.signals.items()} == {"log": "ok", "metric": "ok"}
        groups = {k: v.status for k, v in (st.log_groups or {}).items()}
        assert groups["/ecs/shop-prod/audit-worker"] == "permission_denied"
        assert groups["/ecs/shop-prod/pricing-service"] == "unsupported"
        assert groups["/ecs/shop-prod/inventory-service"] == "ok"
        assert "fixture-operator" not in st.model_dump_json()  # the session name (an e-mail) is never shown

        services, notes = await c.discover(W)
        assert services == ["api-gateway", "audit-worker", "checkout-service", "inventory-service", "pricing-service"]
        assert any("never inferred" in n for n in notes) and any("pricing-service" in n for n in notes)

        logs = await c.fetch(c.template("cw_lifecycle"), "inventory-service", W)
        msgs = " ".join(r.message for r in logs.logs)
        assert "3.8.0 starting" in msgs and "max_size=8" in msgs and logs.provenance.aws
        assert logs.provenance.aws["query_status"] == "Complete" and logs.provenance.aws["polls"] == 2
        errs = await c.fetch(c.template("cw_errors"), "checkout-service", W)
        assert errs.provenance.status == "ok" and errs.provenance.redactions == 0
        warn = await c.fetch(c.template("cw_warnings"), "checkout-service", W)
        assert warn.provenance.redactions >= 1 and cw.FAKE_SECRET not in json.dumps([r.message for r in warn.logs])

        rate = await c.fetch(c.template("cw_log_error_count"), "inventory-service", W)
        assert rate.metrics and all(m.unit == "Count" for m in rate.metrics)
        assert min(m.ts for m in rate.metrics) >= cw.ONSET  # no zero bins invented before the onset
        wait = await c.fetch(c.template("custom_metrics"), "inventory-service", W)
        before = [m.value for m in wait.metrics if m.ts < cw.ONSET]
        during = [m.value for m in wait.metrics if cw.ONSET <= m.ts < cw.RESTORE]
        assert max(before) < 20 and min(during) > 1000
        lam = await c.fetch(c.template("lambda_errors"), "pricing-service", W)
        assert lam.provenance.status == "empty" and any("never read as zero" in i for i in lam.provenance.issues)
        missing = await c.fetch(c.template("cw_errors"), "pricing-service", W)
        assert (missing.provenance.error or {})["kind"] == "not_found"
        denied = await c.fetch(c.template("cw_errors"), "audit-worker", W)
        assert (denied.provenance.error or {})["kind"] == "permission_denied"
        state = srv.state()
        assert state["stopped"] == []  # every query completed: nothing to clean up
        assert set(state["calls"]) <= {"StartQuery", "GetQueryResults", "DescribeLogGroups", "GetMetricData"}


@pytest.mark.parametrize(
    ("svc", "status", "kind"),
    [
        ("empty-svc", "empty", None),
        ("delayed-svc", "ok", None),
        ("failed-svc", "error", "query_error"),
        ("timeout-svc", "error", "timeout"),
        ("cancelled-svc", "error", "unavailable"),
        ("throttled-svc", "error", "rate_limited"),
        ("limit-svc", "error", "rate_limited"),
        ("denied-svc", "error", "permission_denied"),
        ("slow-svc", "error", "timeout"),
        ("partial-svc", "ok", None),
        ("malformed-svc", "ok", None),
    ],
)
async def test_failure_scenarios(svc: str, status: str, kind: str | None) -> None:
    with fixture_server() as srv:
        c = connector(srv.url, SCENARIOS)
        res = await c.fetch(c.template("cw_errors"), svc, W)
        p = res.provenance
        assert p.status == status, (p.error, p.issues)
        assert (p.error or {}).get("kind") == kind
        state = srv.state()
        if svc in ("slow-svc", "partial-svc"):
            assert p.aws and state["stopped"] == [p.aws["query_id"]]  # its own query, stopped once
            assert p.aws["polls"] == MAX_POLLS
        else:
            assert state["stopped"] == []
        if svc == "partial-svc":
            assert p.truncated and any("partial" in i for i in p.issues)
        if svc == "malformed-svc":
            assert p.rejected == 2 and res.logs
        if svc == "delayed-svc":
            assert p.aws and p.aws["polls"] == 4
        if svc == "empty-svc":
            assert any("does not show that no such events happened" in i for i in p.issues)


async def test_uncorrelated_events_are_flagged() -> None:
    with fixture_server() as srv:
        c = connector(srv.url, SCENARIOS)
        res = await c.fetch(c.template("cw_errors"), "uncorrelated-svc", W)
        assert any("cannot be correlated" in i for i in res.provenance.issues)
        forbidden = await c.fetch(c.template("custom_metrics"), "forbidden-metric-svc", W)
        assert (forbidden.provenance.error or {})["kind"] == "permission_denied"


@pytest.mark.parametrize(
    ("key", "status"),
    [
        ("AKIAFIXTUREEXPIRED00", "auth_error"),
        ("AKIAFIXTUREINVALID00", "auth_error"),
        ("AKIAFIXTURENOPERMS00", "permission_denied"),
    ],
)
async def test_credential_scenarios(key: str, status: str) -> None:
    with fixture_server() as srv:
        c = connector(srv.url, access_key_id=key)
        st = await c.test()
        assert st.status == status, st.message
        res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
        assert res.provenance.status == "error"
        assert key not in st.model_dump_json() and key not in res.provenance.model_dump_json()


async def test_wrong_account_is_reported_and_blocks_collection() -> None:
    with fixture_server() as srv:
        c = connector(srv.url, access_key_id="AKIAFIXTUREOTHERACCT", account_id=cw.ACCOUNT)
        st = await c.test()
        assert st.status == "auth_error" and "444455556666" in st.message
        res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
        assert "444455556666" in (res.provenance.error or {})["message"]
        assert "StartQuery" not in srv.state()["calls"]


async def test_cancelled_collection_stops_its_running_query() -> None:
    with fixture_server() as srv:
        polled = asyncio.Event()
        calls = 0

        async def sleep(_: float) -> None:
            nonlocal calls
            calls += 1
            if calls > 1:
                polled.set()
                await asyncio.sleep(3600)

        c = connector(srv.url, SCENARIOS, sleep=sleep)
        task = asyncio.create_task(c.fetch(c.template("cw_errors"), "slow-svc", W))
        await asyncio.wait_for(polled.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(50):
            if srv.state()["stopped"]:
                break
            await asyncio.sleep(0.05)
        state = srv.state()
        assert state["stopped"] == state["started"] and len(state["stopped"]) == 1


async def test_active_queries_are_bounded() -> None:
    with fixture_server() as srv:
        active = peak = 0

        async def sleep(_: float) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

        c = connector(srv.url, SCENARIOS, sleep=sleep)
        svcs = ["empty-svc", "delayed-svc", "malformed-svc", "uncorrelated-svc", "partial-svc", "failed-svc"]
        await asyncio.gather(*(c.fetch(c.template("cw_errors"), s, W) for s in svcs))
        assert 1 < peak <= CONCURRENCY


async def test_response_size_limit() -> None:
    with fixture_server() as srv:
        c = connector(srv.url, limits=Limits(max_response_bytes=2048))
        res = await c.fetch(c.template("cw_errors"), "inventory-service", W)
        assert (res.provenance.error or {})["kind"] == "response_too_large"


# ------------------------------------------------------------------------------------------------ web process isolation
def test_aws_credentials_never_reach_the_web_process() -> None:
    from opspilot_shared.config import Settings
    from opspilot_shared.web_env import build_web_env, is_backend_only

    keys = (
        "CLOUDWATCH_ACCESS_KEY_ID",
        "CLOUDWATCH_SECRET_ACCESS_KEY",
        "CLOUDWATCH_SESSION_TOKEN",
        "CLOUDWATCH_AWS_PROFILE",
        "CLOUDWATCH_ROLE_ARN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    )
    for key in keys:
        assert is_backend_only(key), key
    source = {k: SECRET_KEY for k in keys} | {"OPSPILOT_API_URL": "http://127.0.0.1:8000", "PATH": "/bin"}
    env = build_web_env(source)
    assert SECRET_KEY not in json.dumps(env) and not any(k in env for k in keys)
    assert not any(k.upper().startswith(("NEXT_PUBLIC_AWS", "NEXT_PUBLIC_CLOUDWATCH")) for k in Settings.model_fields)


async def test_import_and_disabled_settings_make_no_aws_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import botocore.session

    from opspilot_shared.config import Settings
    from opspilot_shared.connectors.registry import ConnectorRegistry

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("an SDK client was created")

    monkeypatch.setattr(botocore.session.Session, "create_client", boom)
    reg = ConnectorRegistry.from_settings(Settings(_env_file=None, cloudwatch_region="us-east-1"))  # type: ignore[call-arg]
    assert "cloudwatch" not in reg.configured
    with pytest.raises(ConnectorError) as exc:
        reg.get("cloudwatch")
    assert exc.value.kind == "not_configured" and "CLOUDWATCH_ENABLED" in exc.value.message
