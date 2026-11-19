"""v0.6: read-only Loki and Prometheus connectors — normalization, provenance, limits, errors and safety."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from opspilot_shared.config import Settings
from opspilot_shared.connectors.base import step_for
from opspilot_shared.connectors.contract import ConnectorError, FetchWindow, QueryTemplate
from opspilot_shared.connectors.http import ReadOnlyHttp, validate_base_url
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from opspilot_shared.connectors.templates import check_template, load_templates, render
from tests.fakes.telemetry import SECRET_TOKEN, TENANT, FakeTelemetry, window_dt

W = FetchWindow(start=window_dt()[0], end=window_dt()[1])


def _all_sources() -> list[SourceSelection]:
    return [
        SourceSelection("loki", ("errors_warnings", "lifecycle")),
        SourceSelection("prometheus", ("http_5xx_ratio", "p95_latency_ms", "db_pool_in_use", "db_pool_max")),
    ]


# ----------------------------------------------------------------------------------------- configuration
@pytest.mark.parametrize(
    ("url", "creds", "problem"),
    [
        ("ftp://loki.example", False, "http"),
        ("http://user:pw@loki.example", False, "credentials"),
        ("https://loki.example/?x=1", False, "query string"),
        ("https://loki.example/#f", False, "fragment"),
        ("http://loki.example", True, "https"),
        ("not a url", False, "http"),
    ],
)
def test_invalid_destinations_are_refused(url: str, creds: bool, problem: str) -> None:
    with pytest.raises(ConnectorError, match=problem) as exc:
        validate_base_url(url, has_credentials=creds)
    assert exc.value.kind == "not_configured"


def test_valid_destinations_are_normalized() -> None:
    assert validate_base_url("http://127.0.0.1:3310/", has_credentials=True) == "http://127.0.0.1:3310"
    assert validate_base_url("http://localhost:9090", has_credentials=True) == "http://localhost:9090"
    assert validate_base_url("https://logs.example.com/loki/", has_credentials=True) == "https://logs.example.com/loki"


def test_only_configured_connectors_exist_and_describe_holds_no_secret() -> None:
    reg = ConnectorRegistry.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert reg.configured == []
    desc = reg.describe()
    assert {c["id"]: c["configured"] for c in desc["connectors"]} == {
        "loki": False,
        "prometheus": False,
        "datadog": False,  # v0.9: implemented, so listed as a connector and no longer as planned
    }
    assert "Datadog" not in " ".join(desc["planned"]) and "Azure Monitor" in " ".join(desc["planned"])
    with pytest.raises(ConnectorError) as exc:
        reg.get("loki")
    assert exc.value.kind == "not_configured" and "LOKI_URL" in exc.value.message

    fake = FakeTelemetry(prom_token=SECRET_TOKEN)
    reg = fake.registry(
        prometheus_url="https://prometheus.test",
        prometheus_bearer_token=SECRET_TOKEN,
        loki_url="https://loki.test",
        loki_password="loki-secret-pw",
        loki_username="u",
    )
    text = json.dumps(reg.describe(), default=str)
    assert SECRET_TOKEN not in text and "loki-secret-pw" not in text
    prom = next(c for c in reg.describe()["connectors"] if c["id"] == "prometheus")
    assert prom["auth"] == "bearer token" and prom["endpoint"] == "https://prometheus.test"


def test_bad_connector_configuration_is_reported_not_raised() -> None:
    s = Settings(_env_file=None, loki_url="http://admin:pw@loki.example", prometheus_url="https://p.example")  # type: ignore[call-arg]
    reg = ConnectorRegistry.from_settings(s)
    assert reg.configured == ["prometheus"]
    loki = next(c for c in reg.describe()["connectors"] if c["id"] == "loki")
    assert not loki["configured"] and "credentials" in loki["problem"] and "pw" not in loki["problem"]


# --------------------------------------------------------------------------------------------- templates
def test_templates_are_scoped_to_one_service_and_reject_injection() -> None:
    t = QueryTemplate(
        id="x_ratio", connector="prometheus", label="x", query="sum(rate(x{$selector}[$rate]))", metric="x_ratio"
    )
    assert (
        render(t, label="service", service="checkout-api", step_seconds=30)
        == 'sum(rate(x{service="checkout-api"}[5m]))'
    )
    assert (
        render(t, label="service", service="checkout-api", step_seconds=120)
        == 'sum(rate(x{service="checkout-api"}[8m]))'
    )
    for bad in ('checkout"} or vector(1) #', "Checkout", "a", "x\\y", 'svc,status!=""'):
        with pytest.raises(ConnectorError) as exc:
            render(t, label="service", service=bad)
        assert exc.value.kind == "invalid_request"
    with pytest.raises(ValueError, match=r"\$selector"):
        check_template(QueryTemplate(id="up", connector="prometheus", label="up", query="up{}", metric="up"))
    with pytest.raises(ValueError, match="stream selector"):
        check_template(
            QueryTemplate(id="lq", connector="loki", label="l", query="sum(count_over_time({$selector}[5m]))")
        )


def test_template_file_adds_and_rejects(tmp_path: Path) -> None:
    f = tmp_path / "t.json"
    f.write_text(
        json.dumps(
            {
                "templates": [
                    {
                        "id": "ok_metric",
                        "connector": "prometheus",
                        "label": "ok",
                        "query": "max(m{$selector})",
                        "metric": "ok_metric",
                    },
                    {"id": "no_selector", "connector": "prometheus", "label": "bad", "query": "max(m)", "metric": "m"},
                    {"id": "BadId", "connector": "loki", "label": "bad", "query": "{$selector}"},
                ]
            }
        )
    )
    templates, problems = load_templates(f)
    ids = {t.id for t in templates}
    assert "ok_metric" in ids and "no_selector" not in ids and "errors_warnings" in ids
    assert len(problems) == 2
    _, problems = load_templates(tmp_path / "missing.json")
    assert problems and "not used" in problems[0]


def test_window_limits_and_step() -> None:
    start = datetime(2026, 11, 12, 6, tzinfo=UTC)
    assert step_for(FetchWindow(start=start, end=start + timedelta(hours=2))) == 30
    assert step_for(FetchWindow(start=start, end=start + timedelta(minutes=10))) == 15
    assert step_for(FetchWindow(start=start, end=start + timedelta(hours=6))) == 90


@pytest.mark.parametrize(
    ("start", "end", "msg"),
    [
        (datetime(2026, 11, 12, 1, tzinfo=UTC), datetime(2026, 11, 12, 9, tzinfo=UTC), "limit"),
        (datetime(2026, 11, 12, 9, tzinfo=UTC), datetime(2026, 11, 12, 8, tzinfo=UTC), "after start"),
        (datetime.now(UTC), datetime.now(UTC) + timedelta(hours=1), "future"),
    ],
)
async def test_windows_outside_the_limits_are_refused(start: datetime, end: datetime, msg: str) -> None:
    fake = FakeTelemetry()
    reg = fake.registry()
    with pytest.raises(ConnectorError, match=msg) as exc:
        await collect(reg, _all_sources(), ["checkout-api"], FetchWindow(start=start, end=end))
    assert exc.value.kind == "invalid_request"
    assert fake.requests == []  # refused before any request


# ------------------------------------------------------------------------------------------ normalization
async def test_snapshot_preserves_timestamps_units_labels_and_provenance() -> None:
    fake = FakeTelemetry()
    snap = await collect(fake.registry(), _all_sources(), ["checkout-api", "payment-service"], W)
    d = snap.dataset
    assert d.logs and d.metrics and not d.spans and not d.events
    log = next(r for r in d.logs if r.service == "payment-service" and r.level == "ERROR")
    assert log.tz == "epoch" and log.ts_original.isdigit() and len(log.ts_original) == 19  # Loki nanoseconds as sent
    assert log.service_source == "record" and log.level_inferred is False
    assert log.source.startswith("loki/errors_warnings/payment-service:entry ")
    assert log.attributes["label.env"] == "demo" and log.attributes["pool"] == "payments-db" and log.trace_id
    ratio = next(r for r in d.metrics if r.metric == "http_5xx_ratio" and r.service == "checkout-api")
    assert ratio.unit == "ratio" and ratio.tz == "epoch" and ratio.service_source == "query"
    assert ratio.source.startswith("prometheus/http_5xx_ratio/checkout-api:point ")
    assert {r.unit for r in d.metrics if r.metric == "p95_latency_ms"} == {"ms"}
    # provenance of every query, including the exact rendered query and the step
    q = next(q for q in snap.queries if q.id == "prometheus/http_5xx_ratio/checkout-api")
    assert q.status == "ok" and q.step_seconds == 45 and q.endpoint == "/api/v1/query_range"
    assert (
        'service="checkout-api"' in q.query
        and "[5m]" in q.query
        and q.returned == len([r for r in d.metrics if r.source.startswith(q.id + ":")])
    )
    lq = next(q for q in snap.queries if q.id == "loki/lifecycle/payment-service")
    assert lq.limit == 2000 and lq.redactions == 1  # the fake credential in the config line
    redacted = next(r for r in d.logs if "loaded gateway client config" in r.message)
    assert "sk_test_EXAMPLE0000000" not in redacted.message and "[REDACTED]" in redacted.message
    assert any("version=2.14.0" in r.message for r in d.logs)  # lifecycle template finds the start-up line
    # collected signals: db pool metrics do not exist for checkout-api -> empty, but the signal was collected
    assert d.collected == {"log": ["checkout-api", "payment-service"], "metric": ["checkout-api", "payment-service"]}
    assert any("db_pool_in_use/checkout-api returned no data" in w for w in d.warnings)
    # the same line matched by two templates is stored once
    keys = [(r.service, r.ts_original, r.message) for r in d.logs]
    assert len(keys) == len(set(keys))


async def test_non_finite_points_are_skipped_not_filled() -> None:
    fake = FakeTelemetry()
    reg = fake.registry()

    def nan_payload(request: httpx.Request) -> httpx.Response:
        values = [[1794474000.0, "0.1"], [1794474030.0, "NaN"], [1794474060.0, "+Inf"], [1794474090.0, "0.2"]]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": "matrix", "result": [{"metric": {"service": "checkout-api"}, "values": values}]},
            },
        )

    prom = reg.get("prometheus")
    prom.http._transport = httpx.MockTransport(nan_payload)  # type: ignore[attr-defined]
    res = await prom.fetch(prom.templates()[0], "checkout-api", W)
    assert [m.value for m in res.metrics] == [0.1, 0.2] and res.provenance.rejected == 2
    assert res.metrics[0].service_source == "record"
    assert any("never filled in" in i for i in res.provenance.issues)


async def test_loki_line_limit_is_reported_as_truncated() -> None:
    fake = FakeTelemetry()
    reg = fake.registry(telemetry_max_log_lines=10)
    snap = await collect(reg, [SourceSelection("loki", ("all_lines",))], ["checkout-api"], W)
    q = snap.queries[0]
    assert q.truncated and q.returned == 10 and fake.requests[-1].params["limit"] == "10"
    assert fake.requests[-1].params["direction"] == "backward"
    assert any("10-line limit" in w for w in snap.dataset.warnings)


async def test_too_many_series_are_capped() -> None:
    fake = FakeTelemetry()
    reg = fake.registry(telemetry_max_series=2)

    def many(request: httpx.Request) -> httpx.Response:
        result = [{"metric": {"pod": f"p{i}"}, "values": [[1794474000.0, "1"]]} for i in range(5)]
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": result}})

    prom = reg.get("prometheus")
    prom.http._transport = httpx.MockTransport(many)  # type: ignore[attr-defined]
    res = await prom.fetch(prom.templates()[0], "checkout-api", W)
    assert res.provenance.series == 5 and res.provenance.truncated and len(res.metrics) == 2
    assert res.metrics[0].labels == {"pod": "p0"}


# ---------------------------------------------------------------------------------------- errors / states
async def test_connection_states() -> None:
    fake = FakeTelemetry()
    reg = fake.registry()
    assert (await reg.get("loki").test()).status == "ok"
    assert (await reg.get("prometheus").test()).version == "3.5.0"
    no_tenant = fake.registry(loki_tenant_id="")
    st = await no_tenant.get("loki").test()
    assert st.status == "auth_error" and "no org id" in st.message
    fake.fail["/api/v1/status/buildinfo"] = httpx.ConnectError("connection refused")
    assert (await reg.get("prometheus").test()).status == "unavailable"
    fake.fail["/api/v1/status/buildinfo"] = httpx.ReadTimeout("slow")
    st = await reg.get("prometheus").test()
    assert st.status == "unavailable" and "no answer" in st.message
    fake.fail["/api/v1/status/buildinfo"] = 404  # build info absent (some hosted APIs): the auth probe decides
    assert (await reg.get("prometheus").test()).status == "ok"
    fake.fail["/api/v1/labels"] = 503
    assert (await reg.get("prometheus").test()).status == "unavailable"


async def test_backend_failures_are_recorded_per_query_and_stay_unknown() -> None:
    fake = FakeTelemetry()
    fake.fail["/api/v1/query_range"] = 401
    snap = await collect(fake.registry(), _all_sources(), ["checkout-api"], W)
    errors = [q for q in snap.queries if q.status == "error"]
    assert errors and all(q.connector == "prometheus" and q.error and q.error["kind"] == "auth_error" for q in errors)
    assert snap.dataset.metrics == [] and snap.dataset.collected["metric"] == []  # unknown, not "healthy"
    assert any("no metrics could be collected for checkout-api" in w for w in snap.dataset.warnings)
    assert snap.dataset.logs  # the other connector still worked


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        ("redirect", "redirect_refused"),
        ("huge", "response_too_large"),
        (400, "query_error"),
        (404, "not_found"),
        (429, "rate_limited"),
        (500, "unavailable"),
        (httpx.ConnectTimeout("t"), "timeout"),
    ],
)
async def test_http_failure_kinds(failure: object, kind: str) -> None:
    fake = FakeTelemetry()
    fake.fail["/api/v1/query_range"] = failure
    reg = fake.registry()
    prom = reg.get("prometheus")
    res = await prom.fetch(prom.templates()[0], "checkout-api", W)
    assert res.provenance.status == "error" and res.provenance.error and res.provenance.error["kind"] == kind
    assert len([r for r in fake.requests if r.path == "/api/v1/query_range"]) == 1  # the redirect was not followed


async def test_errors_never_echo_credentials() -> None:
    fake = FakeTelemetry(prom_token="the-right-one-0000")
    reg = fake.registry(prometheus_url="https://prometheus.test", prometheus_bearer_token=SECRET_TOKEN)  # wrong token
    st = await reg.get("prometheus").test()
    assert st.status == "auth_error" and SECRET_TOKEN not in st.message and "[REDACTED]" in st.message
    assert fake.requests[-1].headers["authorization"] == f"Bearer {SECRET_TOKEN}"  # it was sent, only to the API


async def test_only_get_requests_to_read_endpoints_of_the_configured_hosts() -> None:
    fake = FakeTelemetry()
    reg = fake.registry()
    await reg.get("loki").test()
    await reg.get("prometheus").test()
    await reg.get("loki").services(W)
    await reg.get("prometheus").services(W)
    await collect(reg, _all_sources(), ["checkout-api", "payment-service"], W)
    assert fake.requests
    assert {r.method for r in fake.requests} == {"GET"}
    assert {r.host for r in fake.requests} == {"loki.test", "prometheus.test"}
    read_paths = {
        "/loki/api/v1/status/buildinfo",
        "/loki/api/v1/labels",
        "/loki/api/v1/label/service_name/values",
        "/loki/api/v1/query_range",
        "/api/v1/status/buildinfo",
        "/api/v1/labels",
        "/api/v1/label/service/values",
        "/api/v1/query_range",
    }
    assert {r.path for r in fake.requests} <= read_paths
    assert all(r.headers.get("x-scope-orgid") == TENANT for r in fake.requests if r.host == "loki.test")


async def test_client_refuses_paths_outside_its_allowlist() -> None:
    http = ReadOnlyHttp(
        "http://prometheus.test", allowed_paths=["/api/v1/query_range"], transport=FakeTelemetry().transport()
    )
    for path in ("/api/v1/admin/tsdb/delete_series", "/loki/api/v1/push", "/-/quit", "/api/v1/query_range/../admin"):
        with pytest.raises(ConnectorError) as exc:
            await http.get_json(path)
        assert exc.value.kind == "invalid_request"
    assert not hasattr(http, "post") and not hasattr(http, "request")


async def test_service_discovery_keeps_only_valid_service_names() -> None:
    fake = FakeTelemetry()
    fake.streams.append({"stream": {"service_name": 'evil"} or {x=~".+'}, "values": []})
    fake.streams.append({"stream": {"service_name": "Upper_Case"}, "values": []})
    services = await fake.registry().get("loki").services(W)
    assert services == ["checkout-api", "payment-service", "search-api"]


async def test_too_many_queries_are_refused() -> None:
    fake = FakeTelemetry()
    reg = fake.registry()
    big = [SourceSelection("prometheus", tuple(t.id for t in reg.get("prometheus").templates()) * 1)]
    services = [f"svc-{i}" for i in range(9)]
    with pytest.raises(ConnectorError, match="at most"):
        await collect(reg, big, services, W)
    with pytest.raises(ConnectorError, match="unknown"):
        await collect(reg, [SourceSelection("loki", ("drop_everything",))], ["checkout-api"], W)
