"""v0.9: read-only Datadog connector — configuration, destinations, read-only surface, limits, errors, normalization.

All against the synthetic Datadog fixture (``scripts/datadog_fixture.py``), which answers with the request/response
structures documented at https://docs.datadoghq.com/api/latest/. This is contract testing, not a live Datadog test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from opspilot_shared.config import Settings
from opspilot_shared.connectors.contract import ConnectorError, FetchWindow, QueryTemplate
from opspilot_shared.connectors.datadog import (
    LOGS_AGGREGATE,
    LOGS_SEARCH,
    SITES,
    SPANS_SEARCH,
    TIMESERIES,
    VALIDATE,
    DatadogConnector,
    resolve_site,
)
from opspilot_shared.connectors.http import ReadOnlyHttp
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from opspilot_shared.connectors.templates import check_template, load_templates
from opspilot_shared.web_env import is_backend_only
from tests.fakes.datadog import API_KEY, APP_KEY, WINDOW, FakeDatadog, dd

W = FetchWindow(start=datetime.fromisoformat(WINDOW["start"]), end=datetime.fromisoformat(WINDOW["end"]))
SERVICES = ["orders-api", "inventory-service", "notification-worker"]
READ_ONLY = {("GET", VALIDATE), *(("POST", p) for p in (LOGS_SEARCH, LOGS_AGGREGATE, TIMESERIES, SPANS_SEARCH))}


def dd_conn(fake: FakeDatadog, **over: object) -> DatadogConnector:
    c = fake.registry(**over).get("datadog")
    assert isinstance(c, DatadogConnector)
    return c


def defaults(c: DatadogConnector) -> tuple[str, ...]:
    return tuple(t.id for t in c.templates() if t.default)


# ----------------------------------------------------------------------------------------- configuration
def test_disabled_by_default_and_keys_are_backend_only() -> None:
    reg = ConnectorRegistry.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    with pytest.raises(ConnectorError) as exc:
        reg.get("datadog")
    assert exc.value.kind == "not_configured" and "DATADOG_ENABLED" in exc.value.message
    entry = next(c for c in reg.describe()["connectors"] if c["id"] == "datadog")
    assert entry["configured"] is False and entry["signals"] == ["log", "metric", "span"]
    for key in ("DATADOG_API_KEY", "DATADOG_APP_KEY", "DATADOG_SITE", "DATADOG_LOCAL_API_URL", "DD_API_KEY"):
        assert is_backend_only(key), key  # never passed to the web process
    assert not any(k.startswith("NEXT_PUBLIC_DATADOG") for k in Settings.model_fields)


def test_missing_keys_or_unsupported_site_are_reported_not_raised() -> None:
    no_app = ConnectorRegistry.from_settings(
        Settings(_env_file=None, datadog_enabled=True, datadog_api_key="x" * 32)  # type: ignore[call-arg]
    )
    entry = next(c for c in no_app.describe()["connectors"] if c["id"] == "datadog")
    assert not entry["configured"] and "DATADOG_APP_KEY" in entry["problem"]
    fake = FakeDatadog()
    for site in ("evil.example.com", "datadoghq.com.evil.io", "https://api.datadoghq.com", "169.254.169.254", ""):
        reg = fake.registry(datadog_site=site)
        entry = next(c for c in reg.describe()["connectors"] if c["id"] == "datadog")
        assert not entry["configured"] and "unsupported DATADOG_SITE" in entry["problem"], site


@pytest.mark.parametrize("site", sorted(SITES))
def test_every_documented_site_maps_to_its_fixed_api_host(site: str) -> None:
    key, base, app = resolve_site(site.upper())
    assert key == site and base == f"https://{SITES[site][0]}" and app == SITES[site][1]
    assert base.startswith("https://api.")


@pytest.mark.parametrize(
    "url",
    ["http://10.0.0.5:8126", "https://api.datadoghq.com.attacker.test", "http://169.254.169.254", "ftp://127.0.0.1"],
)
def test_local_fixture_url_must_be_loopback(url: str) -> None:
    with pytest.raises(ConnectorError, match="loopback") as exc:
        resolve_site("datadoghq.com", url)
    assert exc.value.kind == "not_configured"
    assert resolve_site("datadoghq.com", "http://127.0.0.1:8126")[1] == "http://127.0.0.1:8126"


def test_info_holds_no_secret_and_states_the_read_only_surface() -> None:
    c = dd_conn(FakeDatadog(), datadog_site="datadoghq.eu", datadog_env="prod")
    info = c.info()
    text = json.dumps(info, default=str)
    assert API_KEY not in text and APP_KEY not in text
    assert info["endpoint"] == "https://api.datadoghq.eu" and info["site"] == "datadoghq.eu"
    assert info["auth"] == "API key + application key" and info["signals"] == ["log", "metric", "span"]
    assert set(info["read_only_endpoints"]) == {f"{m} {p}" for m, p in READ_ONLY}
    assert info["permissions"] == {"log": "logs_read_data", "metric": "timeseries_query", "span": "apm_read"}


def test_datadog_templates_are_scoped_and_validated(tmp_path: Path) -> None:
    for t in load_templates(None)[0]:
        check_template(t)
    bad = [
        {"id": "x_logs", "connector": "datadog", "label": "x", "query": "service:other $selector", "signal": "log"},
        {"id": "x_nosig", "connector": "datadog", "label": "x", "query": "$selector"},
        {
            "id": "x_metric",
            "connector": "datadog",
            "label": "x",
            "signal": "metric",
            "metric": "x_m",
            "query": "a = avg:cpu{*}; b = avg:cpu{$selector}; a / b",
        },
        {
            "id": "x_formula",
            "connector": "datadog",
            "label": "x",
            "signal": "metric",
            "metric": "x_m",
            "query": "a = avg:cpu{$selector}; __import__('os')",
        },
        {
            "id": "x_expand",
            "connector": "datadog",
            "label": "x",
            "signal": "log",
            "expand_traces": 3,
            "query": "$selector",
        },
        {"id": "x_loki_span", "connector": "loki", "label": "x", "signal": "span", "query": "{$selector}"},
    ]
    good = {
        "id": "db_lock_waits",
        "connector": "datadog",
        "label": "Lock waits",
        "signal": "metric",
        "metric": "db_lock_waits",
        "unit": "waits",
        "query": "sum:postgresql.locks{$selector,mode:exclusive}",
    }
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"templates": [*bad, good]}))
    templates, problems = load_templates(f)
    assert len(problems) == len(bad), problems
    assert any(t.id == "db_lock_waits" and t.connector == "datadog" for t in templates)


def test_selector_cannot_carry_query_syntax() -> None:
    c = dd_conn(FakeDatadog(), datadog_env="prod")
    t = next(t for t in c.templates() if t.id == "http_5xx_ratio")
    assert "{service:orders-api,env:prod,http.status_class:5xx}" in c.render(t, "orders-api")
    logs = next(t for t in c.templates() if t.id == "errors_warnings")
    # search syntax: '-' is a documented special character, so it is escaped
    assert c.render(logs, "orders-api").startswith("service:orders\\-api env:prod status:(")
    evil_values = (
        "orders-api OR service:*",
        "a}",
        'x" OR "',
        "*",
        "svc*",
        "svc)",
        "svc:prod",
        "svc/1",
        "svc\\",
        "a.b OR c",
        "Orders-API",  # Datadog lowercases service tags; mixed case would silently match nothing
        "a" * 64,
        "-leading",
        "1numeric",
        "svc,env:dev",
        "svc\nstatus:error",
    )
    for evil in evil_values:
        for template in (logs, t):
            with pytest.raises(ConnectorError) as exc:
                c.render(template, evil)
            assert exc.value.kind == "invalid_request", evil


@pytest.mark.parametrize(
    ("service", "search", "scope"),
    [
        ("orders-api", "service:orders\\-api", "{service:orders-api}"),
        ("billing.worker_v2", "service:billing.worker_v2", "{service:billing.worker_v2}"),
        ("web_store", "service:web_store", "{service:web_store}"),
        ("api.v2-internal", "service:api.v2\\-internal", "{service:api.v2-internal}"),
    ],
)
def test_legitimate_datadog_service_names_are_escaped_not_rewritten(service: str, search: str, scope: str) -> None:
    c = dd_conn(FakeDatadog())
    logs = next(t for t in c.templates() if t.id == "errors_warnings")
    spans = next(t for t in c.templates() if t.id == "error_spans")
    metric = next(t for t in c.templates() if t.id == "p95_latency_ms")
    assert c.render(logs, service).startswith(search + " status:(")
    assert c.render(spans, service) == f"{search} status:error"
    assert scope in c.render(metric, service)


def test_escaping_covers_every_documented_special_character() -> None:
    from opspilot_shared.connectors.templates import dd_escape

    special = '+-=&|><!(){}[]^"~*?:\\/ '
    assert dd_escape(special) == "".join(f"\\{ch}" for ch in special)
    assert dd_escape("billing.worker_v2") == "billing.worker_v2"


async def test_dotted_service_is_discovered_queried_and_kept_exactly() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake)
    services, notes = await c.discover(W)  # type: ignore[attr-defined]
    assert "billing.worker_v2" in services and any("Legacy_Billing" in n for n in notes)
    t = next(t for t in c.templates() if t.id == "all_logs")
    res = await c.fetch(t, "billing.worker_v2", W)
    assert res.provenance.status == "ok" and res.provenance.id == "datadog/all_logs/billing.worker_v2"
    assert {r.service for r in res.logs} == {"billing.worker_v2"}  # never rewritten to billing-worker-v2
    assert all(r.service_source == "record" for r in res.logs)
    assert res.logs[0].source.startswith("datadog/all_logs/billing.worker_v2:entry ")


async def test_loki_and_prometheus_still_accept_slugs_only() -> None:
    from opspilot_shared.connectors.templates import render

    loki = next(t for t in load_templates(None)[0] if t.connector == "loki")
    assert render(loki, label="service_name", service="checkout-api").startswith('{service_name="checkout-api"}')
    for value in ("billing.worker_v2", "web_store"):
        with pytest.raises(ConnectorError, match="lower-case slug"):
            render(loki, label="service_name", service=value)


# ------------------------------------------------------------------------------------- read-only surface
async def test_only_documented_read_endpoints_of_the_site_host_are_called() -> None:
    fake = FakeDatadog()
    reg = fake.registry()
    c = reg.get("datadog")
    await c.test()
    await c.services(W)
    await collect(reg, [SourceSelection("datadog", defaults(c))], SERVICES, W)  # type: ignore[arg-type]
    assert fake.requests
    assert {(r["method"], r["path"]) for r in fake.requests} <= READ_ONLY
    assert {r["host"] for r in fake.requests} == {"api.datadoghq.com"}
    for r in fake.requests:
        assert r["headers"]["dd-api-key"] == API_KEY
        assert r["path"] == VALIDATE or r["headers"]["dd-application-key"] == APP_KEY
        assert "authorization" not in r["headers"]


async def test_client_refuses_unapproved_posts_and_any_other_method() -> None:
    http = ReadOnlyHttp("https://api.datadoghq.com", allowed_paths=[VALIDATE], allowed_post_paths=[LOGS_SEARCH])
    for path in ("/api/v1/monitor", "/api/v2/logs/config/indexes", "/api/v1/dashboard", VALIDATE):
        with pytest.raises(ConnectorError, match="not an approved read-only query"):
            await http.post_json(path, {})
    loki_like = ReadOnlyHttp("https://loki.test", allowed_paths=["/loki/api/v1/labels"])
    with pytest.raises(ConnectorError, match="not an approved"):
        await loki_like.post_json("/loki/api/v1/push", {})  # v0.6 connectors still cannot POST at all
    assert not any(hasattr(http, m) for m in ("put", "patch", "delete", "request", "put_json", "delete_json"))
    c = dd_conn(FakeDatadog())
    assert set(c.allowed_post_paths()) == {LOGS_SEARCH, LOGS_AGGREGATE, TIMESERIES, SPANS_SEARCH}
    assert c.allowed_paths() == [VALIDATE]


async def test_redirects_are_refused() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    reg = FakeDatadog().settings()
    c = ConnectorRegistry.from_settings(reg, transports={"datadog": httpx.MockTransport(redirect)}).get("datadog")
    st = await c.test()
    assert st.status == "error" and "redirect" in st.message


# ------------------------------------------------------------------------------------------ connection test
async def test_connection_states() -> None:
    fake = FakeDatadog()
    ok = await dd_conn(fake).test()
    assert (
        ok.status == "ok"
        and ok.signals
        and {s: v.status for s, v in ok.signals.items()}
        == {
            "log": "ok",
            "metric": "ok",
            "span": "ok",
        }
    )
    bad_key = await dd_conn(fake, datadog_api_key="wrong-api-key-0000").test()
    assert bad_key.status == "auth_error" and "API key was rejected" in bad_key.message and bad_key.signals is None
    bad_app = await dd_conn(fake, datadog_app_key="wrong-app-key-0000").test()
    assert bad_app.status == "auth_error" and "application key" in bad_app.message
    fake.fail[SPANS_SEARCH] = 403  # this application key may not read APM
    partial = await dd_conn(fake).test()
    assert partial.status == "partial" and partial.signals
    assert partial.signals["span"].status == "permission_denied" and "apm_read" in partial.signals["span"].message
    assert partial.signals["log"].status == "ok"
    fake.fail.clear()
    fake.fail[SPANS_SEARCH] = 404
    assert (await dd_conn(fake).test()).signals["span"].status == "unsupported"  # type: ignore[index]
    fake.fail.clear()
    fake.fail[VALIDATE] = "timeout"
    assert (await dd_conn(fake).test()).status == "unavailable"
    fake.fail[VALIDATE] = 500
    assert (await dd_conn(fake).test()).status == "unavailable"


async def test_rate_limits_are_retried_briefly_then_reported() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake)
    logs = next(t for t in c.templates() if t.id == "errors_warnings")
    fake.fail[LOGS_SEARCH] = 429
    fake.fixture.rate_reset = "0"  # the provider allows the next request now: up to 2 retries, then give up
    res = await c.fetch(logs, "orders-api", W)
    assert res.provenance.status == "error" and res.provenance.error["kind"] == "rate_limited"  # type: ignore[index]
    assert c.http.retries == 2 and sum(r["path"] == LOGS_SEARCH for r in fake.requests) == 3
    fake.requests.clear()
    fake.fixture.rate_reset = "45"  # longer than OpsPilot waits: no retry, no loop, and the wait is reported
    res = await c.fetch(logs, "orders-api", W)
    assert sum(r["path"] == LOGS_SEARCH for r in fake.requests) == 1
    assert "next request in 45 s" in res.provenance.error["message"]  # type: ignore[index]


async def test_transient_rate_limit_then_success() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake)
    calls = {"n": 0}
    original = fake.fixture.handle

    def flaky(method, path, headers, body):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if path == TIMESERIES and calls["n"] == 1:
            return 429, {"x-ratelimit-reset": "0"}, b'{"errors": ["Too many requests"]}'
        return original(method, path, headers, body)

    fake.fixture.handle = flaky  # type: ignore[method-assign]
    t = next(t for t in c.templates() if t.id == "p95_latency_ms")
    res = await c.fetch(t, "orders-api", W)
    assert res.provenance.status == "ok" and res.metrics and c.http.retries == 1


# -------------------------------------------------------------------------------- normalization & provenance
async def test_snapshot_normalizes_logs_metrics_and_spans_with_provenance() -> None:
    fake = FakeDatadog()
    reg = fake.registry()
    c = reg.get("datadog")
    snap = await collect(reg, [SourceSelection("datadog", defaults(c))], SERVICES, W)  # type: ignore[arg-type]
    d = snap.dataset
    assert d.logs and d.metrics and d.spans and snap.usable
    assert d.collected == {"log": SERVICES_SORTED, "metric": SERVICES_SORTED, "span": SERVICES_SORTED}
    q = {p.id: p for p in snap.queries}
    logs_q = q["datadog/errors_warnings/orders-api"]
    assert logs_q.signal == "log" and logs_q.site == "datadoghq.com" and logs_q.endpoint == LOGS_SEARCH
    assert logs_q.query.startswith("service:orders\\-api status:(") and logs_q.limit == 2000 and logs_q.pages == 1
    assert logs_q.link and logs_q.link.startswith("https://app.datadoghq.com/logs?query=service%3Aorders%5C-api")
    assert API_KEY not in logs_q.link and APP_KEY not in logs_q.link
    assert q["datadog/http_5xx_ratio/orders-api"].link is None  # no unverified URL scheme for metrics
    log = next(r for r in d.logs if r.service == "orders-api" and r.level == "ERROR" and r.trace_id)
    assert log.source.startswith("datadog/errors_warnings/orders-api:entry ") and log.tz == "Z"
    assert log.ts_original.endswith("Z") and log.attributes["datadog.log_id"].startswith("AQAAA")
    assert not log.level_inferred and log.attributes["env"] == "prod"
    secret = next(r for r in d.logs if "payment provider" in r.message)
    assert dd.FAKE_SECRET not in secret.message and snap.redactions() >= 1

    m = [r for r in d.metrics if r.service == "orders-api" and r.metric == "http_5xx_ratio"]
    assert m and m[0].unit == "ratio" and m[0].tz == "epoch" and m[0].labels == {"service": "orders-api"}
    assert m[0].source.startswith("datadog/http_5xx_ratio/orders-api:point ")
    gap_start, gap_end = datetime(2026, 11, 15, 13, 20, tzinfo=UTC), datetime(2026, 11, 15, 13, 23, tzinfo=UTC)
    assert not any(gap_start <= r.ts < gap_end for r in m)  # Datadog nulls are left out, never filled in
    assert any("had no value (null)" in i for i in q["datadog/http_5xx_ratio/orders-api"].issues)
    assert max(r.value for r in m if r.ts >= dd.ONSET) > 0.2 > max(r.value for r in m if r.ts < dd.ONSET)
    p95 = [r for r in d.metrics if r.metric == "p95_latency_ms" and r.service == "orders-api"]
    assert 50 < p95[0].value < 150  # p95 seconds * 1000 through the formula

    spans = [s for s in d.spans if s.trace_id]
    services = {s.service for s in spans}
    assert {"orders-api", "inventory-service", "inventory-db"} <= services  # expanded traces reach the dependency
    by_parent = {s.parent_span_id: s for s in spans if s.parent_span_id}
    err = next(s for s in spans if s.service == "orders-api" and s.status == "error" and s.span_id in by_parent)
    assert err.status_message and "timed out" in err.status_message and err.duration_ms and err.duration_ms > 4000
    assert err.parent_span_id is None and err.attributes["http.status_code"] == "504"
    assert by_parent[err.span_id].service == "inventory-service"  # the real parent/child relation, as returned
    db = next(s for s in spans if s.service == "inventory-db")
    assert db.status == "unset" and db.kind == "db"  # not flagged by Datadog: unset, never assumed ok
    partial = [s for s in spans if s.attributes.get("parent_missing")]
    assert partial and any("traces are partial" in i for p in snap.queries for i in p.issues)


SERVICES_SORTED = sorted(SERVICES)


async def test_pagination_has_hard_ceilings() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake, telemetry_max_log_lines=10)
    t = next(t for t in c.templates() if t.id == "errors_warnings")
    res = await c.fetch(t, "orders-api", W)
    assert len(res.logs) == 10 and res.provenance.truncated and res.provenance.pages == 1
    assert any("10-record limit" in i for i in res.provenance.issues)
    bodies = [r["body"] for r in fake.requests if r["path"] == LOGS_SEARCH]
    assert all(b["page"]["limit"] <= 1000 for b in bodies)
    assert bodies[0]["filter"]["from"] == "2026-11-15T12:00:00.000Z" and bodies[0]["sort"] == "-timestamp"

    from opspilot_shared.connectors import datadog as mod

    fake.requests.clear()
    old = mod.PAGE_LIMIT
    mod.PAGE_LIMIT = 5  # force multi-page answers
    try:
        res = await dd_conn(fake).fetch(t, "orders-api", W)
    finally:
        mod.PAGE_LIMIT = old
    assert res.provenance.pages == mod.MAX_PAGES and len(res.logs) == 5 * mod.MAX_PAGES and res.provenance.truncated
    cursors = [r["body"]["page"].get("cursor") for r in fake.requests if r["path"] == LOGS_SEARCH]
    assert cursors[0] is None and all(cursors[1:])


async def test_metric_request_matches_the_documented_shape_and_series_are_capped() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake, telemetry_max_series=1)
    t = next(t for t in c.templates() if t.id == "http_5xx_ratio")
    await c.fetch(t, "inventory-service", W)
    body = next(r["body"] for r in fake.requests if r["path"] == TIMESERIES)
    attrs = body["data"]["attributes"]
    assert body["data"]["type"] == "timeseries_request"
    assert attrs["from"] == 1794744000000 and attrs["to"] == 1794753000000 and attrs["interval"] % 15000 == 0
    assert [q["name"] for q in attrs["queries"]] == ["a", "b"] and attrs["formulas"] == [{"formula": "a / b"}]
    assert all(q["data_source"] == "metrics" for q in attrs["queries"])


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (403, "permission_denied"),
        (429, "rate_limited"),
        (500, "unavailable"),
        ("timeout", "timeout"),
        ("malformed", "invalid_response"),
        ("not_json", "invalid_response"),
        (400, "query_error"),
    ],
)
async def test_failure_kinds_per_query(failure: object, kind: str) -> None:
    fake = FakeDatadog()
    fake.fail[SPANS_SEARCH] = failure
    fake.fixture.rate_reset = "60"
    reg = fake.registry()
    c = reg.get("datadog")
    snap = await collect(reg, [SourceSelection("datadog", defaults(c))], ["orders-api"], W)  # type: ignore[arg-type]
    span_q = next(q for q in snap.queries if q.signal == "span")
    assert span_q.status == "error" and span_q.error and span_q.error["kind"] == kind
    # the other signals are kept, and spans stay unknown rather than "none found"
    assert snap.dataset.logs and snap.dataset.metrics and snap.dataset.collected["span"] == []  # type: ignore[index]
    assert any("no traces/spans could be collected for orders-api" in w for w in snap.dataset.warnings)
    if kind == "permission_denied":
        assert "apm_read" in span_q.error["message"]


async def test_errors_never_echo_credentials() -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        keys = f"{request.headers['dd-api-key']} {request.headers.get('dd-application-key', '')}"
        return httpx.Response(400, json={"errors": [f"bad request for key {keys}"]})

    c = ConnectorRegistry.from_settings(
        FakeDatadog().settings(), transports={"datadog": httpx.MockTransport(echo)}
    ).get("datadog")
    st = await c.test()
    t = next(t for t in c.templates() if t.id == "errors_warnings")
    res = await c.fetch(t, "orders-api", W)
    text = st.model_dump_json() + res.provenance.model_dump_json()
    assert API_KEY not in text and APP_KEY not in text and "[REDACTED]" in text


async def test_window_and_service_limits() -> None:
    c = dd_conn(FakeDatadog())
    t = c.templates()[0]
    now = datetime.now(UTC)
    for start, end in ((W.start, W.start + timedelta(hours=7)), (now, now + timedelta(hours=1)), (W.end, W.start)):
        with pytest.raises(ConnectorError) as exc:
            await c.fetch(t, "orders-api", FetchWindow(start=start, end=end))
        assert exc.value.kind == "invalid_request"
    with pytest.raises(ConnectorError):
        await c.fetch(t, "Orders API", W)


async def test_service_discovery_is_bounded_and_explicit_about_gaps() -> None:
    fake = FakeDatadog()
    c = dd_conn(fake)
    services, notes = await c.discover(W)  # type: ignore[attr-defined]
    assert services == sorted([*SERVICES, "billing.worker_v2"])
    assert any("no service tag" in n for n in notes) and any("Legacy_Billing" in n for n in notes)
    body = next(r["body"] for r in fake.requests if r["path"] == LOGS_AGGREGATE)
    assert body["group_by"][0]["facet"] == "service" and body["group_by"][0]["limit"] == 50
    assert body["filter"]["from"] == "2026-11-15T12:00:00.000Z"
    with pytest.raises(ConnectorError):
        await c.discover(FetchWindow(start=W.start, end=W.start + timedelta(hours=8)))  # type: ignore[attr-defined]


async def test_empty_window_is_no_data_not_an_error() -> None:
    fake = FakeDatadog()
    reg = fake.registry()
    c = reg.get("datadog")
    empty = FetchWindow(start=datetime(2026, 11, 14, 1, tzinfo=UTC), end=datetime(2026, 11, 14, 2, tzinfo=UTC))
    snap = await collect(reg, [SourceSelection("datadog", defaults(c))], ["orders-api"], empty)  # type: ignore[arg-type]
    assert not snap.usable and {q.status for q in snap.queries} == {"empty"}
    assert snap.dataset.collected == {"log": ["orders-api"], "metric": ["orders-api"], "span": ["orders-api"]}


def test_template_model_accepts_signal_only_for_known_values() -> None:
    with pytest.raises(ValueError):
        QueryTemplate(id="x_y", connector="datadog", label="x", query="$selector", signal="trace")  # type: ignore[arg-type]


async def test_span_templates_are_service_scoped_and_need_no_operation_name() -> None:
    """Span search works for any integration: no built-in span template names an operation (trace.http.request,
    operation_name, resource_name). Only APM *metric* templates depend on the span name, documented as such."""
    fake = FakeDatadog()
    c = dd_conn(fake)
    span_templates = [t for t in c.templates() if t.returns == "span"]
    assert {t.id for t in span_templates} == {"error_spans", "service_spans"}
    for t in span_templates:
        assert t.query.startswith("$selector")
        assert not any(op in t.query for op in ("trace.", "operation_name", "resource_name", "@"))
    worker = next(t for t in span_templates if t.id == "service_spans")
    res = await c.fetch(worker, "notification-worker", W)  # a worker with only non-HTTP spans (send_batch)
    assert res.provenance.status == "ok" and {s.name for s in res.spans} == {"send_batch"}
    body = next(r["body"] for r in fake.requests if r["path"] == SPANS_SEARCH)
    assert body["data"]["attributes"]["filter"]["query"] == "service:notification\\-worker"
    metric_ops = {t.id for t in c.templates() if t.returns == "metric" and "trace.http.request" in t.query}
    assert metric_ops == {"http_5xx_ratio", "trace_error_ratio", "p95_latency_ms", "http_requests_per_min"}
