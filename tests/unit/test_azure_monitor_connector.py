"""v0.10: read-only Azure Monitor connector — configuration, Entra authentication, read-only surface, KQL safety,
limits, errors, normalization.

All against the synthetic Logs API fixture (``scripts/azure_monitor_fixture.py``), which answers with the request and
response structures documented for the Log Analytics Query API. This is contract testing, not a live Azure test.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from opspilot_shared.config import Settings
from opspilot_shared.connectors.azure_monitor import (
    FIXTURE_TOKEN,
    PUBLIC_API,
    SCOPE,
    AccessToken,
    AzureMonitorConnector,
    TokenProvider,
    build_credential,
    credential_error,
    parse_ts,
)
from opspilot_shared.connectors.contract import ConnectorError, FetchWindow, QueryTemplate
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from opspilot_shared.connectors.templates import BUILT_IN, check_template, kql_string, load_templates
from opspilot_shared.web_env import build_web_env, is_backend_only
from tests.fakes.azure_monitor import WINDOW, WORKSPACE, WS, FakeAzureMonitor, az

W = FetchWindow(start=datetime.fromisoformat(WINDOW["start"]), end=datetime.fromisoformat(WINDOW["end"]))
SERVICES = ["orders-api", "payment-service", "inventory-service"]
SECRET = "AzureClientSecret-DO-NOT-LEAK-0123456789"


def conn(fake: FakeAzureMonitor, **over: object) -> AzureMonitorConnector:
    c = fake.registry(**over).get("azure_monitor")
    assert isinstance(c, AzureMonitorConnector)
    return c


def tpl(c: AzureMonitorConnector, tid: str) -> QueryTemplate:
    return next(t for t in c.templates() if t.id == tid)


def defaults(c: AzureMonitorConnector) -> tuple[str, ...]:
    return tuple(t.id for t in c.templates() if t.default)


class Cred:
    """A token credential double: returns tokens in order, or raises."""

    def __init__(self, *tokens: str, expires_in: int = 3600, error: BaseException | None = None) -> None:
        self.tokens = list(tokens) or [FIXTURE_TOKEN]
        self.expires_in = expires_in
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        self.calls.append(scopes)
        if self.error:
            raise self.error
        token = self.tokens.pop(0) if len(self.tokens) > 1 else self.tokens[0]
        return AccessToken(token, int(datetime.now(UTC).timestamp()) + self.expires_in)


# ----------------------------------------------------------------------------------------- configuration
def test_disabled_by_default_and_settings_are_backend_only() -> None:
    reg = ConnectorRegistry.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    with pytest.raises(ConnectorError) as exc:
        reg.get("azure_monitor")
    assert exc.value.kind == "not_configured" and "AZURE_MONITOR_ENABLED" in exc.value.message
    entry = next(c for c in reg.describe()["connectors"] if c["id"] == "azure_monitor")
    assert entry["configured"] is False and entry["signals"] == ["log", "metric", "span"]
    for key in (
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_MONITOR_WORKSPACE_ID",
        "AZURE_MONITOR_LOCAL_API_URL",
        "IDENTITY_ENDPOINT",
        "MSAL_TOKEN_CACHE",
    ):
        assert is_backend_only(key), key
    env = build_web_env({"AZURE_CLIENT_SECRET": SECRET, "OPSPILOT_API_URL": "http://127.0.0.1:8000", "PATH": "/bin"})
    assert SECRET not in json.dumps(env) and "AZURE_CLIENT_SECRET" not in env
    assert not any(k.upper().startswith("NEXT_PUBLIC_AZURE") for k in Settings.model_fields)


@pytest.mark.parametrize(
    ("over", "problem"),
    [
        ({"azure_monitor_workspace_id": ""}, "AZURE_MONITOR_WORKSPACE_ID"),
        ({"azure_monitor_workspace_id": "my-workspace"}, "GUID"),
        (
            {
                "azure_monitor_workspace_id": "/subscriptions/x/resourceGroups/y/providers/"
                "Microsoft.OperationalInsights/workspaces/z"
            },
            "GUID",
        ),
        ({"azure_monitor_workspace_id": "https://api.loganalytics.azure.com/v1/workspaces/x"}, "GUID"),
        ({"azure_monitor_auth_mode": "interactive_browser"}, "AZURE_MONITOR_AUTH_MODE"),
        ({"azure_monitor_auth_mode": "default"}, "AZURE_MONITOR_AUTH_MODE"),
        ({"azure_monitor_local_api_url": "http://evil.example:8128"}, "loopback"),
        ({"azure_monitor_local_api_url": "http://169.254.169.254"}, "loopback"),
        ({"azure_monitor_local_api_url": ""}, "AZURE_MONITOR_LOCAL_API_URL"),  # fixture mode needs the fixture
        (
            {"azure_monitor_auth_mode": "service_principal"},  # local URL kept: only the fixture may use it
            "only for the synthetic fixture",
        ),
    ],
)
def test_invalid_configuration_is_reported_not_raised(over: dict[str, str], problem: str) -> None:
    fake = FakeAzureMonitor()
    reg = fake.registry(**over)
    with pytest.raises(ConnectorError) as exc:
        reg.get("azure_monitor")
    assert exc.value.kind == "not_configured" and problem in exc.value.message
    desc = next(c for c in reg.describe()["connectors"] if c["id"] == "azure_monitor")
    assert desc["configured"] is False and problem in (desc["problem"] or "")


def test_service_principal_needs_all_three_values_and_valid_ids() -> None:
    with pytest.raises(ConnectorError, match="AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET"):
        build_credential("service_principal", tenant_id="", client_id="x", client_secret="y")
    with pytest.raises(ConnectorError, match="AZURE_CLIENT_ID must be a GUID"):
        build_credential("service_principal", tenant_id="contoso.onmicrosoft.com", client_id="app", client_secret="s")
    with pytest.raises(ConnectorError, match="AZURE_TENANT_ID must be"):
        build_credential(
            "service_principal",
            tenant_id="https://login.evil.test/x",
            client_id="11111111-2222-4333-8444-555555555555",
            client_secret="s",
        )
    cred = build_credential(
        "service_principal",
        tenant_id="contoso.onmicrosoft.com",
        client_id="11111111-2222-4333-8444-555555555555",
        client_secret=SECRET,
    )
    assert type(cred).__name__ == "ClientSecretCredential"
    assert getattr(cred, "_client_id", "") == "11111111-2222-4333-8444-555555555555"  # constructed, no network call


def test_managed_identity_and_cli_are_explicit_and_never_take_a_secret() -> None:
    mi = build_credential("managed_identity", tenant_id="", client_id="", client_secret="")
    assert type(mi).__name__ == "ManagedIdentityCredential"
    uami = build_credential(
        "managed_identity", tenant_id="", client_id="11111111-2222-4333-8444-555555555555", client_secret=""
    )
    assert type(uami).__name__ == "ManagedIdentityCredential"
    cli = build_credential("azure_cli", tenant_id="", client_id="", client_secret="")
    assert type(cli).__name__ == "AzureCliCredential"
    with pytest.raises(ConnectorError, match="only used by service_principal"):
        build_credential("managed_identity", tenant_id="", client_id="", client_secret=SECRET)
    # no unrestricted chain and no interactive browser credential is ever built
    for mode in ("default", "interactive", "device_code", "environment"):
        fake = FakeAzureMonitor()
        with pytest.raises(ConnectorError):
            fake.registry(azure_monitor_auth_mode=mode, azure_monitor_local_api_url="").get("azure_monitor")


def test_destination_is_fixed_and_info_holds_no_secret() -> None:
    fake = FakeAzureMonitor()
    reg = ConnectorRegistry.from_settings(
        fake.settings(
            azure_monitor_auth_mode="service_principal",
            azure_monitor_local_api_url="",
            azure_tenant_id="contoso.onmicrosoft.com",
            azure_client_id="11111111-2222-4333-8444-555555555555",
            azure_client_secret=SECRET,
        )
    )
    c = reg.get("azure_monitor")
    assert isinstance(c, AzureMonitorConnector)
    assert c.base_url == PUBLIC_API == "https://api.loganalytics.azure.com"
    info = c.info()
    text = json.dumps(reg.describe())
    assert SECRET not in text and "AZURE_CLIENT_SECRET" not in text
    assert info["workspace_id"] == WORKSPACE and info["auth_mode"] == "service_principal" and not info["fixture"]
    assert info["read_only_endpoints"] == [f"POST /v1/workspaces/{WORKSPACE}/query"]
    assert "Log Analytics Data Reader" in info["permissions"]["role"]
    assert info["signals"] == ["log", "metric", "span"]


# ----------------------------------------------------------------------------------------- authentication
async def test_tokens_are_cached_refreshed_before_expiry_and_requested_for_the_logs_scope() -> None:
    now = [1_000_000.0]

    class Clocked:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []
            self.tokens = ["t1", "t2"]

        def get_token(self, *scopes: str, **_: Any) -> AccessToken:
            self.calls.append(scopes)
            return AccessToken(self.tokens.pop(0), int(now[0]) + 3600)

    cred = Clocked()
    tp = TokenProvider(cred, clock=lambda: now[0])
    assert await tp.get() == "t1" and await tp.get() == "t1" and tp.acquired == 1
    now[0] += 3600 - 200  # inside the 5-minute refresh margin
    assert await tp.get() == "t2" and tp.acquired == 2
    assert cred.calls == [(SCOPE,), (SCOPE,)] and SCOPE == "https://api.loganalytics.azure.com/.default"


async def test_expired_token_answered_401_is_refreshed_once_and_the_query_succeeds() -> None:
    fake = FakeAzureMonitor()
    cred = Cred(az.EXPIRED_TOKEN, FIXTURE_TOKEN)
    c = conn(fake)
    c.tokens._credential = cred
    res = await c.query("print opspilot_probe = 1", "PT5M")
    assert res.rows == [{"opspilot_probe": 1}]
    assert c.entra.refreshed == 1 and len(cred.calls) == 2
    auths = [r["headers"]["authorization"] for r in fake.requests]
    assert auths == [f"Bearer {az.EXPIRED_TOKEN}", f"Bearer {FIXTURE_TOKEN}"]


async def test_a_token_still_rejected_after_refresh_is_an_auth_error_without_the_token() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    c.tokens._credential = Cred(az.EXPIRED_TOKEN)
    with pytest.raises(ConnectorError) as exc:
        await c.query("print opspilot_probe = 1", "PT5M")
    assert exc.value.kind == "auth_error" and "even after a refresh" in exc.value.message
    assert az.EXPIRED_TOKEN not in exc.value.message
    st = await c.test()
    assert st.status == "auth_error" and az.EXPIRED_TOKEN not in st.model_dump_json()


async def test_credential_failures_keep_only_aadsts_codes() -> None:
    from azure.core.exceptions import ClientAuthenticationError
    from azure.identity import CredentialUnavailableError

    leaky = ClientAuthenticationError(
        message=f"AADSTS7000215: Invalid client secret provided. secret={SECRET} tenant 1234 app 5678 Trace ID: x"
    )
    err = credential_error(leaky)
    assert err.kind == "auth_error" and "AADSTS7000215" in err.message and "invalid client secret" in err.message
    assert SECRET not in err.message and "1234" not in err.message
    un = credential_error(CredentialUnavailableError(message="ManagedIdentityCredential unavailable: no IMDS"))
    assert un.kind == "auth_error" and "not available here" in un.message
    fake = FakeAzureMonitor()
    c = conn(fake)
    c.tokens._credential = Cred(error=leaky)
    st = await c.test()
    assert st.status == "auth_error" and st.message.startswith("Microsoft Entra ID:") and SECRET not in st.message
    assert fake.requests == []  # no query without a token
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.status == "error" and r.provenance.error and r.provenance.error["kind"] == "auth_error"


async def test_token_acquisition_timeout_is_bounded() -> None:
    class Slow:
        def get_token(self, *s: str, **k: Any) -> AccessToken:
            import time

            time.sleep(0.3)
            return AccessToken("late", 0)

    tp = TokenProvider(Slow(), timeout=0.05)
    with pytest.raises(ConnectorError) as exc:
        await tp.get()
    assert exc.value.kind == "timeout"


async def test_bearer_tokens_are_scrubbed_from_backend_echoes() -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        auth = request.headers["authorization"]
        body = {"error": {"code": "BadArgumentError", "message": f"bad request with header {auth}"}}
        return httpx.Response(400, json=body)

    c = conn(FakeAzureMonitor())
    c.http._transport = httpx.MockTransport(echo)
    with pytest.raises(ConnectorError) as exc:
        await c.query("print opspilot_probe = 1", "PT5M")
    assert FIXTURE_TOKEN not in exc.value.message and "[REDACTED]" in exc.value.message


# ----------------------------------------------------------------------------------------- read-only surface
async def test_only_the_workspace_query_path_is_reachable() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    for path in ("/v1/workspaces/other/query", "/v1/apps/x/query", "/subscriptions/x/providers/Microsoft.Insights"):
        with pytest.raises(ConnectorError, match="not an approved"):
            await c.http.post_json(path, {"query": "print 1"})
    with pytest.raises(ConnectorError, match="not allowed"):
        await c.http.get_json(c.query_path)
    for name in ("put", "patch", "delete", "put_json", "delete_json"):
        assert not hasattr(c.http, name)
    assert fake.requests == []
    tids = defaults(c)
    await collect(fake.registry(), [SourceSelection("azure_monitor", tids)], SERVICES[:1], W)
    assert {(r["method"], r["path"]) for r in fake.requests} == {("POST", f"/v1/workspaces/{WORKSPACE}/query")}
    assert all(r["headers"]["prefer"] == "wait=10" for r in fake.requests)  # server-side time bound


async def test_redirects_are_refused() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, azure_monitor_workspace_id=WS["redirect"])
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.status == "error" and r.provenance.error and r.provenance.error["kind"] == "redirect_refused"
    assert len(fake.requests) == 1 and all(req["host"] == "127.0.0.1" for req in fake.requests)


# ----------------------------------------------------------------------------------------- KQL safety
@pytest.mark.parametrize(
    "evil",
    [
        'orders-api" or 1==1 or AppRoleName =~ "x',
        "orders-api | union AppTraces",
        "orders-api\n| take 100000",
        "Orders API",
        "orders-api;drop",
        "orders\\api",
        "x",
        "a" * 70,
        "orders-api)",
        "*",
    ],
)
async def test_service_names_cannot_change_kql_structure(evil: str) -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    with pytest.raises(ConnectorError) as exc:
        await c.fetch(tpl(c, "trace_warnings"), evil, W)
    assert exc.value.kind == "invalid_request"
    assert fake.requests == []


def test_rendered_queries_quote_the_validated_service_and_bound_rows() -> None:
    c = conn(FakeAzureMonitor())
    q = c.render(tpl(c, "trace_warnings"), "billing.worker_v2", limit=2000)
    assert 'where AppRoleName =~ "billing.worker_v2"' in q and q.endswith("| take 2001")
    m = c.render(tpl(c, "p95_latency_ms"), "orders-api", step=90)
    assert "bin(TimeGenerated, 90s)" in m and "$" not in m
    rate = c.render(tpl(c, "http_requests_per_min"), "orders-api", step=60)
    assert "* 60.0 / 60.0" in rate
    assert kql_string('a"b\\c') == '"a\\"b\\\\c"'
    with pytest.raises(ValueError, match="control characters"):
        kql_string("a\nb")


@pytest.mark.parametrize(
    ("query", "problem"),
    [
        ("AppTraces | where $selector | union AppRequests | take $limit", "union"),
        ('AppTraces | where $selector | join (workspace("other").AppTraces) on OperationId | take $limit', "join"),
        ("let x = 1; AppTraces | where $selector | take $limit", "must start with"),
        ("SigninLogs | where $selector | take $limit", "must start with"),
        ("AppTraces | take 5 | where $selector | take $limit", "must start with"),
        ("AppTraces | where $selector | evaluate bag_unpack(Properties) | take $limit", "evaluate"),
        ('AppTraces | where $selector | extend x = externaldata(a:string)["https://x"] | take $limit', "externaldata"),
        ("AppTraces | where $selector | where app('x').requests | take $limit", "app"),
        ("AppTraces | where $selector | where Message has 'x' // comment\n| take $limit", "//"),
        ("AppTraces | where $selector | take $limit | where $other", "placeholder"),
        ("AppTraces | where $selector | project Message", r"take \$limit"),
        ("AppTraces | where $selector | where AppRoleName == $selector | take $limit", "exactly once"),
        ("AppTraces | where $selector and 1 == 1 | take $limit", "must start with"),
    ],
)
def test_template_files_cannot_widen_the_query_surface(query: str, problem: str) -> None:
    t = QueryTemplate(id="custom", connector="azure_monitor", signal="log", label="x", query=query, source="file")
    with pytest.raises(ValueError, match=problem):
        check_template(t)


def test_metric_templates_need_bins_and_a_metric_name(tmp_path: Any) -> None:
    bad = QueryTemplate(
        id="m_bad",
        connector="azure_monitor",
        signal="metric",
        label="m",
        metric="m_x",
        query="AppRequests | where $selector | summarize value = count()",
    )
    with pytest.raises(ValueError, match=r"bin\(TimeGenerated, \$bin\)"):
        check_template(bad)
    f = tmp_path / "t.json"
    good = {
        "id": "server_errors_per_min",
        "connector": "azure_monitor",
        "signal": "metric",
        "label": "Server errors",
        "metric": "server_errors_per_min",
        "unit": "req/min",
        "query": "AppRequests\n| where $selector\n| where Success == false\n"
        "| summarize value = todouble(sum(ItemCount)) * 60.0 / $bin_seconds by bin(TimeGenerated, $bin)",
    }
    f.write_text(json.dumps({"templates": [good, {**good, "id": "evil", "query": "union *"}]}))
    templates, problems = load_templates(f)
    assert any(t.id == "server_errors_per_min" and t.connector == "azure_monitor" for t in templates)
    assert (len(problems) == 1 and "evil" in problems[0]) or "template 2" in problems[0]
    for t in BUILT_IN:
        if t.connector == "azure_monitor":
            check_template(t)


# ----------------------------------------------------------------------------------------- limits
async def test_window_and_query_count_limits() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    with pytest.raises(ConnectorError, match="longer than"):
        await c.fetch(
            tpl(c, "trace_warnings"), "orders-api", FetchWindow(start=W.start - timedelta(hours=6), end=W.end)
        )
    with pytest.raises(ConnectorError, match="future"):
        now = datetime.now(UTC)
        await c.fetch(tpl(c, "trace_warnings"), "orders-api", FetchWindow(start=now, end=now + timedelta(hours=1)))
    with pytest.raises(ConnectorError, match="at most 40"):
        all_ids = tuple(t.id for t in c.templates())
        await collect(fake.registry(), [SourceSelection("azure_monitor", all_ids)], [*SERVICES, "billing.worker"], W)
    assert fake.requests == []


async def test_row_limit_is_enforced_after_retrieval_too() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, telemetry_max_log_lines=10, azure_monitor_max_records=10)
    r = await c.fetch(tpl(c, "trace_warnings"), "payment-service", W)
    assert r.provenance.status == "ok" and len(r.logs) == 10 and r.provenance.truncated
    assert "take 11" in r.provenance.query and any("10-record limit" in i for i in r.provenance.issues)

    def flood(request: httpx.Request) -> httpx.Response:  # a server that ignores `take`
        cols = [{"name": "TimeGenerated", "type": "datetime"}, {"name": "Message", "type": "string"}]
        rows = [["2026-11-16T10:00:00Z", f"line {i}"] for i in range(50)]
        return httpx.Response(200, json={"tables": [{"name": "PrimaryResult", "columns": cols, "rows": rows}]})

    c.http._transport = httpx.MockTransport(flood)
    r = await c.fetch(tpl(c, "trace_warnings"), "payment-service", W)
    assert len(r.logs) == 10 and r.provenance.truncated


async def test_concurrency_is_bounded() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    active = peak = 0
    real = c.http.post_json

    async def counting(path: str, body: dict[str, Any]) -> Any:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        try:
            return await real(path, body)
        finally:
            active -= 1

    c.http.post_json = counting  # type: ignore[method-assign]
    await asyncio.gather(*(c.fetch(tpl(c, t), "orders-api", W) for t in defaults(c)))
    assert peak == 2


async def test_response_size_is_capped() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, telemetry_max_response_bytes=64 * 1024)
    r = await c.fetch(tpl(c, "exceptions"), "payment-service", W)
    assert r.provenance.status == "error" and r.provenance.error
    assert r.provenance.error["kind"] == "response_too_large"


# ----------------------------------------------------------------------------------------- errors
@pytest.mark.parametrize(
    ("scenario", "kind", "words"),
    [
        ("forbidden", "permission_denied", "Log Analytics Data Reader"),
        ("throttled", "rate_limited", "Retry"),
        ("gateway_timeout", "timeout", "did not finish"),
        ("unavailable", "unavailable", "HTTP 503"),
        ("malformed", "invalid_response", "columns/rows"),
    ],
)
async def test_provider_failures_are_typed_per_query(scenario: str, kind: str, words: str) -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, azure_monitor_workspace_id=WS[scenario])
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.status == "error" and r.provenance.error and r.provenance.error["kind"] == kind, r.provenance
    assert words.lower() in r.provenance.error["message"].lower() or kind == "rate_limited"
    assert not r.logs


async def test_throttling_retries_only_short_waits_and_never_permission_failures() -> None:
    fake = FakeAzureMonitor()
    fake.fixture.retry_after = "0"
    c = conn(fake, azure_monitor_workspace_id=WS["throttled"])
    c.http._sleep = lambda s: asyncio.sleep(0)
    await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert len(fake.requests) == 3 and c.http.retries == 2  # one try + at most two retries
    fake2 = FakeAzureMonitor()  # Retry-After 30 s: beyond the 10 s bound, so no retry
    c2 = conn(fake2, azure_monitor_workspace_id=WS["throttled"])
    r = await c2.fetch(tpl(c2, "trace_warnings"), "orders-api", W)
    assert len(fake2.requests) == 1 and r.provenance.error and "30" in r.provenance.error["message"]
    fake3 = FakeAzureMonitor()
    c3 = conn(fake3, azure_monitor_workspace_id=WS["forbidden"])
    await c3.fetch(tpl(c3, "trace_warnings"), "orders-api", W)
    assert len(fake3.requests) == 1  # 403 is never retried


async def test_unknown_workspace_and_missing_tables_and_columns() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, azure_monitor_workspace_id="00000000-0000-4000-8000-000000000000")
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.error and r.provenance.error["kind"] == "not_found"
    assert "AZURE_MONITOR_WORKSPACE_ID" in r.provenance.error["message"]
    c = conn(fake, azure_monitor_workspace_id=WS["no_exceptions_table"])
    r = await c.fetch(tpl(c, "exceptions"), "payment-service", W)
    assert r.provenance.error and r.provenance.error["kind"] == "unsupported"
    assert "table AppExceptions does not exist" in r.provenance.error["message"]
    ok = await c.fetch(tpl(c, "trace_warnings"), "payment-service", W)
    assert ok.provenance.status == "ok"  # other tables still answer
    bad_col = QueryTemplate(
        id="bad_col",
        connector="azure_monitor",
        signal="log",
        label="x",
        query="AppTraces\n| where $selector\n| project TimeGenerated, NoSuchColumn\n| take $limit",
    )
    r = await conn(fake).fetch(bad_col, "orders-api", W)
    assert r.provenance.error and r.provenance.error["kind"] == "query_error"
    assert "column NoSuchColumn does not exist" in r.provenance.error["message"]


async def test_partial_results_are_kept_but_marked_incomplete() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, azure_monitor_workspace_id=WS["partial"])
    r = await c.fetch(tpl(c, "trace_warnings"), "payment-service", W)
    assert r.provenance.status == "ok" and r.logs and r.provenance.truncated
    assert any("partial result (PartialError" in i and "incomplete" in i for i in r.provenance.issues)


async def test_no_content_and_empty_results_are_empty_not_healthy() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake, azure_monitor_workspace_id=WS["no_content"])
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.status == "empty" and any("HTTP 204" in i for i in r.provenance.issues)
    c = conn(fake)
    r = await c.fetch(tpl(c, "trace_warnings"), "no-such-service", W)
    assert r.provenance.status == "empty" and not r.logs


async def test_missing_required_and_extra_columns() -> None:
    def answer(cols: list[str], row: list[Any]) -> httpx.MockTransport:
        def h(request: httpx.Request) -> httpx.Response:
            table = {"name": "PrimaryResult", "columns": [{"name": n, "type": "string"} for n in cols], "rows": [row]}
            return httpx.Response(200, json={"tables": [table]})

        return httpx.MockTransport(h)

    c = conn(FakeAzureMonitor())
    c.http._transport = answer(["Message"], ["no time"])
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.error and r.provenance.error["kind"] == "invalid_response"
    assert "TimeGenerated" in r.provenance.error["message"]
    c.http._transport = answer(
        ["TimeGenerated", "Message", "Unexpected", "SeverityLevel"], ["2026-11-16T10:00:00.1234567Z", "hi", "x", 3]
    )
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.status == "ok" and r.logs[0].level == "ERROR" and "Unexpected" not in r.logs[0].attributes
    assert r.logs[0].ts == datetime(2026, 11, 16, 10, 0, 0, 123456, tzinfo=UTC)
    c.http._transport = answer(["TimeGenerated", "Message"], ["2026-11-16T10:00:00Z"])
    r = await c.fetch(tpl(c, "trace_warnings"), "orders-api", W)
    assert r.provenance.rejected == 1 and any("did not match the column list" in i for i in r.provenance.issues)


def test_log_analytics_timestamps() -> None:
    assert parse_ts("2026-11-16T10:31:00.1234567Z") == datetime(2026, 11, 16, 10, 31, 0, 123456, tzinfo=UTC)
    assert parse_ts("2026-11-16T10:31:00Z") == datetime(2026, 11, 16, 10, 31, tzinfo=UTC)
    assert parse_ts("2026-11-16T12:31:00+02:00") == datetime(2026, 11, 16, 10, 31, tzinfo=UTC)
    for bad in ("2026-11-16T10:31:00", "yesterday", None, 17):
        assert parse_ts(bad) is None


# ----------------------------------------------------------------------------------------- connection test, discovery
async def test_connection_test_reports_token_workspace_and_tables() -> None:
    fake = FakeAzureMonitor()
    st = await conn(fake).test()
    assert (
        st.status == "ok"
        and st.tables
        and set(st.tables)
        == {
            "AppTraces",
            "AppExceptions",
            "AppRequests",
            "AppDependencies",
        }
    )
    assert st.signals and {s: v.status for s, v in st.signals.items()} == {"log": "ok", "metric": "ok", "span": "ok"}
    st = await conn(fake, azure_monitor_workspace_id=WS["no_exceptions_table"]).test()
    assert st.status == "partial" and st.tables
    assert st.tables["AppExceptions"].status == "unsupported" and st.tables["AppTraces"].status == "ok"
    assert st.signals and st.signals["log"].status == "ok"  # AppTraces still serves logs
    st = await conn(fake, azure_monitor_workspace_id=WS["forbidden"]).test()
    assert st.status == "permission_denied" and "Log Analytics Data Reader" in st.message
    st = await conn(fake, azure_monitor_workspace_id=WS["unavailable"]).test()
    assert st.status == "unavailable"


async def test_discovery_is_bounded_scoped_and_reports_what_it_left_out() -> None:
    fake = FakeAzureMonitor()
    services, notes = await conn(fake).discover(W)
    assert services == ["billing.worker", "inventory-service", "orders-api", "payment-service"]
    text = " ".join(notes)
    assert "have no AppRoleName" in text and "Notification Worker" in text
    assert "Billing.Worker is listed as 'billing.worker' and queried case-insensitively" in text
    q = fake.requests[-1]["body"]["query"]
    assert q.startswith("union isfuzzy=true AppRequests, AppDependencies, AppExceptions, AppTraces")
    assert "top 51 by records" in q and fake.requests[-1]["body"]["timespan"].startswith("2026-11-16T09:30:00")


# ----------------------------------------------------------------------------------------- normalization
async def test_snapshot_normalizes_every_signal_with_provenance() -> None:
    fake = FakeAzureMonitor()
    reg = fake.registry()
    c = reg.get("azure_monitor")
    assert isinstance(c, AzureMonitorConnector)
    snap = await collect(reg, [SourceSelection("azure_monitor", defaults(c))], SERVICES, W)
    d = snap.dataset
    assert d.collected == {"log": SERVICES_SORTED, "metric": SERVICES_SORTED, "span": SERVICES_SORTED}
    for q in snap.queries:
        assert q.workspace == WORKSPACE and q.tables and q.connector == "azure_monitor"
        assert q.endpoint == f"/v1/workspaces/{WORKSPACE}/query"

    trace = next(r for r in d.logs if "db.pool.max_size=5" in r.message)
    assert (
        trace.service == "payment-service"
        and trace.level == "INFO"
        and trace.source.startswith("azure_monitor/trace_lifecycle/payment-service:entry ")
    )
    assert trace.attributes["azure.table"] == "AppTraces" and trace.attributes["prop.config_revision"] == "r-1842"
    assert trace.ts_original.endswith("0Z") and trace.tz == "Z"

    exc = next(r for r in d.logs if r.attributes.get("exception.type") == "Npgsql.NpgsqlException")
    assert exc.level == "ERROR" and exc.message.startswith("Npgsql.NpgsqlException: The connection pool")
    assert exc.attributes["exception.stack_truncated"] is True and exc.attributes["exception.stack_frames"] == 14
    assert exc.trace_id and exc.span_id
    no_stack = next(r for r in d.logs if r.attributes.get("exception.type") == "System.Net.Http.HttpRequestException")
    assert no_stack.attributes["exception.stack"] == "not recorded"

    redacted = next(r for r in d.logs if "Password=" in r.message)
    assert az.FAKE_SECRET not in redacted.message and snap.redactions() >= 1

    req = next(s for s in d.spans if s.kind == "request" and s.service == "payment-service" and s.status == "error")
    assert req.status_message == "request failed with result code 503" and req.attributes["http.status_code"] == 503
    dep = next(s for s in d.spans if s.kind == "dependency:sql" and s.status == "error")
    assert dep.attributes["dependency.target"] == "orders-db" and dep.attributes["peer.service"] == "orders-db"
    assert "orders-db" in (dep.status_message or "")
    slow = await c.fetch(tpl(c, "slow_requests"), "inventory-service", W)
    assert slow.spans and all(sp.status == "ok" for sp in slow.spans)  # Success == true is recorded as ok
    sampled = next(s for s in d.spans if s.service == "orders-api")
    assert sampled.attributes["azure.item_count"] == 2
    sampled_q = [
        q for q in snap.queries if any("record(s) are sampled telemetry (ItemCount > 1" in i for i in q.issues)
    ]
    assert sampled_q and {q.signal for q in sampled_q} <= {"log", "span"}  # record queries say they hold samples
    assert "orders-api" in {q.service for q in sampled_q}
    # only orders-api is sampled: a payment-service query is flagged only when its expanded operations hold
    # orders-api records, and a payment-service-only query (its exceptions) never is
    assert not any(q.id == "azure_monitor/exceptions/payment-service" for q in sampled_q)
    assert any(s.attributes.get("parent_missing") for s in d.spans)

    p95 = sorted(
        (m for m in d.metrics if m.service == "payment-service" and m.metric == "p95_latency_ms"), key=lambda m: m.ts
    )
    before = [m.value for m in p95 if m.ts < datetime(2026, 11, 16, 10, 31, tzinfo=UTC)]
    during = [
        m.value
        for m in p95
        if datetime(2026, 11, 16, 10, 40, tzinfo=UTC) <= m.ts < datetime(2026, 11, 16, 11, 10, tzinfo=UTC)
    ]
    assert max(before) < 100 and min(during) > 1000 and p95[0].unit == "ms"
    fail = [m for m in d.metrics if m.service == "orders-api" and m.metric == "request_failure_ratio"]
    assert all(0 <= m.value <= 1 for m in fail) and max(m.value for m in fail) > 0.5
    rate = next(q for q in snap.queries if q.id == "azure_monitor/http_requests_per_min/orders-api")
    assert any("ItemCount-weighted estimates" in i for i in rate.issues)
    assert not any(m.metric == "dependency_failure_ratio" and m.service == "inventory-service" for m in d.metrics)
    assert not any(e.event_type for e in d.events)  # no change history is ever collected


SERVICES_SORTED = sorted(SERVICES)


async def test_metric_gaps_are_absent_never_zero() -> None:
    def sparse(request: httpx.Request) -> httpx.Response:
        cols = [
            {"name": "TimeGenerated", "type": "datetime"},
            {"name": "value", "type": "real"},
            {"name": "records", "type": "long"},
            {"name": "items", "type": "long"},
        ]
        rows = [
            ["2026-11-16T10:00:00Z", 0.1, 5, 5],
            ["2026-11-16T10:05:00Z", 0.4, 5, 5],  # four 60 s bins missing between them
            ["2026-11-16T10:06:00Z", None, 0, 0],
        ]
        return httpx.Response(200, json={"tables": [{"name": "PrimaryResult", "columns": cols, "rows": rows}]})

    c = conn(FakeAzureMonitor())
    c.http._transport = httpx.MockTransport(sparse)
    w = FetchWindow(start=datetime(2026, 11, 16, 10, tzinfo=UTC), end=datetime(2026, 11, 16, 10, 10, tzinfo=UTC))
    r = await c.fetch(tpl(c, "request_failure_ratio"), "orders-api", w)
    assert [m.value for m in r.metrics] == [0.1, 0.4]
    assert any("had no records; they are absent, never filled with zero" in i for i in r.provenance.issues)
    assert any("1 bin(s) had no value (null)" in i for i in r.provenance.issues)


async def test_expansion_fetches_operations_by_validated_ids_only() -> None:
    fake = FakeAzureMonitor()
    c = conn(fake)
    r = await c.fetch(tpl(c, "failed_requests"), "payment-service", W)
    bodies = [q["body"]["query"] for q in fake.requests]
    assert len(bodies) == 3 and bodies[1].startswith("AppRequests\n| where OperationId in (")
    assert bodies[2].startswith("AppDependencies\n| where OperationId in (")
    assert r.provenance.tables == ["AppRequests", "AppDependencies"] and r.provenance.pages == 3
    services = {s.service for s in r.spans}
    assert {"payment-service", "orders-api"} <= services  # other services of the same operations
    orders_dep = {s.span_id for s in r.spans if s.service == "orders-api" and s.kind == "dependency:http"}
    assert any(s.parent_span_id in orders_dep for s in r.spans if s.service == "payment-service")


async def test_secrets_never_reach_snapshots_or_errors() -> None:
    fake = FakeAzureMonitor()
    reg = fake.registry()
    c = reg.get("azure_monitor")
    snap = await collect(reg, [SourceSelection("azure_monitor", defaults(c))], ["payment-service"], W)  # type: ignore[arg-type]
    dump = snap.dataset.model_dump_json() + json.dumps([q.model_dump(mode="json") for q in snap.queries])
    assert FIXTURE_TOKEN not in dump and "Bearer" not in dump and az.FAKE_SECRET not in dump
