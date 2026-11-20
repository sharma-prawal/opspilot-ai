"""v0.9 HTTP contract for Datadog: listing, connection test, discovery, preview, connected incident, read-only
investigation, report, deletion — and Loki/Prometheus side by side.

Real app, database and MCP servers; Datadog is the synthetic fixture (``tests.fakes.datadog``), Loki/Prometheus the
v0.6 fakes. Contract testing only: no live Datadog organization is contacted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_api.main import create_app
from opspilot_shared.config import Settings
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.db.models import OpsActionRequest, OpsIncident, SimActionExecution
from tests.fakes.datadog import API_KEY, APP_KEY, INCIDENT_TIME, WINDOW, FakeDatadog
from tests.fakes.models import ScriptedChatModel
from tests.fakes.telemetry import FakeTelemetry
from tests.integration.helpers import inprocess_gateways
from tests.integration.test_api import poll
from tests.unit.test_datadog_investigation import lock_rca
from tests.unit.test_upload_investigation import plan

pytestmark = pytest.mark.integration
DD_SOURCES = [
    {
        "connector": "datadog",
        "templates": ["errors_warnings", "lifecycle", "http_5xx_ratio", "p95_latency_ms", "error_spans"],
    }
]


def body(**over: Any) -> dict[str, Any]:
    return {
        "title": "Orders failing with 504s",
        "description": "orders-api 5xx alert fired (synthetic Datadog fixture).",
        "service": "orders-api",
        "affected_services": ["inventory-service"],
        "severity": "SEV2",
        "incident_time": INCIDENT_TIME,
        "sources": DD_SOURCES,
        **WINDOW,
        **over,
    }


def preview(**over: Any) -> dict[str, Any]:
    b = body(**over)
    for k in ("title", "description", "severity"):
        b.pop(k)
    return b


@pytest.fixture
async def dd() -> FakeDatadog:
    return FakeDatadog()


@pytest.fixture
async def client(settings, session_factory, embedder, ingested, dd) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    telemetry = FakeTelemetry()
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        loki_url="http://loki.test",
        loki_tenant_id="opspilot-demo",
        prometheus_url="http://prometheus.test",
        datadog_enabled=True,
        datadog_api_key=API_KEY,
        datadog_app_key=APP_KEY,
    )
    registry = ConnectorRegistry.from_settings(
        cfg,
        transports={"loki": telemetry.transport(), "prometheus": telemetry.transport(), "datadog": dd.transport()},
    )
    chat = ScriptedChatModel({PlanOutput: plan, RcaOutput: lock_rca})
    app = create_app(
        settings,
        chat=chat,
        gateways=inprocess_gateways(settings, session_factory, embedder),
        embedder=embedder,
        connectors=registry,
    )
    started, stop = asyncio.Event(), asyncio.Event()

    async def host() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(host())
    await asyncio.wait_for(started.wait(), 30)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},
        ) as c:
            yield c
    finally:
        stop.set()
        await task


def no_keys(text: str) -> bool:
    return API_KEY not in text and APP_KEY not in text


async def test_datadog_is_listed_tested_and_discovered_without_secrets(
    client: httpx.AsyncClient, dd: FakeDatadog
) -> None:
    r = await client.get("/api/v1/connectors")
    assert r.status_code == 200 and no_keys(r.text)
    by_id = {c["id"]: c for c in r.json()["connectors"]}
    assert {"loki", "prometheus", "datadog"} <= set(by_id)
    assert all(by_id[k]["configured"] for k in ("loki", "prometheus", "datadog"))
    d = by_id["datadog"]
    assert d["site"] == "datadoghq.com" and d["signals"] == ["log", "metric", "span"] and d["fixture"] is False
    assert {t["signal"] for t in d["templates"]} == {"log", "metric", "span"}
    assert "Datadog" not in r.json()["planned"]

    t = await client.post("/api/v1/connectors/datadog/test")
    assert t.status_code == 200 and t.json()["status"] == "ok" and no_keys(t.text)
    assert {s: v["status"] for s, v in t.json()["signals"].items()} == {"log": "ok", "metric": "ok", "span": "ok"}
    dd.fail["/api/v2/spans/events/search"] = 403
    t = await client.post("/api/v1/connectors/datadog/test")
    assert t.json()["status"] == "partial" and t.json()["signals"]["span"]["status"] == "permission_denied"
    dd.fail.clear()
    dd.fail["/api/v1/validate"] = 403  # bad API key: an auth_error result, never an HTTP 401 for the operator
    t = await client.post("/api/v1/connectors/datadog/test")
    assert t.status_code == 200 and t.json()["status"] == "auth_error"
    dd.fail.clear()

    s = await client.post("/api/v1/connectors/datadog/services", json=WINDOW)
    assert s.status_code == 200
    assert s.json()["services"] == ["billing.worker_v2", "inventory-service", "notification-worker", "orders-api"]
    assert any("no service tag" in n for n in s.json()["notes"])
    anon = await client.post("/api/v1/connectors/datadog/test", headers={"Authorization": ""})
    assert anon.status_code == 401


async def test_request_validation_accepts_ids_only(client: httpx.AsyncClient) -> None:
    for extra in ({"url": "https://api.datadoghq.com"}, {"site": "evil.test"}, {"method": "DELETE"}):
        assert (await client.post("/api/v1/incidents/connected/preview", json=preview(**extra))).status_code == 422
    raw = preview(sources=[{"connector": "datadog", "templates": ["errors_warnings"], "query": "*"}])
    assert (await client.post("/api/v1/incidents/connected/preview", json=raw)).status_code == 422
    path = preview(sources=[{"connector": "datadog", "templates": ["errors_warnings"], "path": "/api/v1/monitor"}])
    assert (await client.post("/api/v1/incidents/connected/preview", json=path)).status_code == 422
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(sources=[{"connector": "datadog", "templates": ["delete_monitor"]}]),
    )
    assert r.status_code == 422 and "unknown datadog template" in r.json()["error"]["message"]
    long = preview(start="2026-11-15T06:00:00Z", end="2026-11-15T14:30:00Z")
    assert (await client.post("/api/v1/incidents/connected/preview", json=long)).status_code == 422


async def test_preview_create_investigate_report_and_delete(
    client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    dd: FakeDatadog,
) -> None:
    async with session_factory() as s:
        incidents_before = (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one()
        executions_before = (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one()
    p = await client.post("/api/v1/incidents/connected/preview", json=preview())
    assert p.status_code == 200, p.text
    view = p.json()
    recs = view["summary"]["records"]
    assert view["usable"] and recs["log"] > 0 and recs["metric"] > 0 and recs["span"] > 0
    assert view["collected"]["span"] == ["inventory-service", "orders-api"]
    assert view["samples"]["span"][0]["source"].startswith("datadog/error_spans/")
    assert view["summary"]["redactions"] >= 1 and "sk_live_FIXTURE" not in p.text and no_keys(p.text)
    async with session_factory() as s:  # a preview stores nothing
        assert (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one() == incidents_before

    r = await client.post("/api/v1/incidents/connected", json=body())
    assert r.status_code == 201, r.text
    inc = r.json()
    ds = (await client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    assert ds["summary"]["connectors"] == ["datadog"] and ds["summary"]["records"]["span"] > 0
    assert {q["signal"] for q in ds["queries"]} == {"log", "metric", "span"}

    requests_before = len(dd.requests)
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert len(dd.requests) == requests_before  # investigated from the frozen snapshot only
    assert done["result"]["outcome"]["code"] == "analysis_complete" and done["result"]["outcome"]["read_only"]
    assert (await client.get(f"/api/v1/investigations/{inv}/actions")).json() == []
    tools = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    servers = {t["tool"]: t["server"] for t in tools}
    assert servers["search_logs"] == servers["get_service_dependencies"] == "opspilot-connected-telemetry"
    evidence = (await client.get(f"/api/v1/investigations/{inv}/evidence")).json()
    report = (await client.get(f"/api/v1/investigations/{inv}/report")).json()["markdown"]
    assert "snapshot of Datadog telemetry" in report and "_(source: datadog/" in report
    cited = {i for h in done["result"]["rca"]["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited and cited <= {e["evidence_id"] for e in evidence}
    for path in (f"/api/v1/incidents/{inc['id']}/dataset", f"/api/v1/investigations/{inv}"):
        assert no_keys((await client.get(path)).text), path
    for path in ("tool-calls", "evidence", "events", "report"):
        assert no_keys((await client.get(f"/api/v1/investigations/{inv}/{path}")).text), path
    async with session_factory() as s:
        assert (
            await s.execute(
                select(func.count()).select_from(OpsActionRequest).where(OpsActionRequest.incident_id == inc["id"])
            )
        ).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one() == executions_before

    gone = await client.post(f"/api/v1/incidents/{inc['id']}/discard")
    assert gone.status_code == 200
    assert (await client.get(f"/api/v1/incidents/{inc['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/investigations/{inv}")).status_code == 404
    methods = {(r["method"], r["path"]) for r in dd.requests}
    assert {m for m, _ in methods} <= {"GET", "POST"} and all(p.startswith("/api/v") for _, p in methods)


async def test_loki_prometheus_and_datadog_together(client: httpx.AsyncClient) -> None:
    sources = [
        {"connector": "loki", "templates": ["errors_warnings"]},
        {"connector": "prometheus", "templates": ["http_5xx_ratio"]},
        {"connector": "datadog", "templates": ["errors_warnings", "error_spans"]},
    ]
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(
            sources=sources,
            service="checkout-api",
            affected_services=["orders-api"],
            start="2026-11-12T07:30:00Z",
            end="2026-11-12T09:45:00Z",
            incident_time="2026-11-12T09:16:00Z",
        ),
    )
    assert r.status_code == 200, r.text
    q = {x["id"]: x for x in r.json()["queries"]}
    assert q["loki/errors_warnings/checkout-api"]["status"] == "ok"
    assert q["prometheus/http_5xx_ratio/checkout-api"]["status"] == "ok"
    assert q["datadog/errors_warnings/orders-api"]["status"] == "empty"  # the fixture holds 2026-11-15 only
    dup = [{"connector": "datadog", "templates": ["errors_warnings"]}] * 2
    assert (await client.post("/api/v1/incidents/connected/preview", json=preview(sources=dup))).status_code == 422


async def test_dotted_service_names_and_injection_attempts_at_the_api(client: httpx.AsyncClient) -> None:
    dotted = preview(
        service="billing.worker_v2", affected_services=[], sources=[{"connector": "datadog", "templates": ["all_logs"]}]
    )
    r = await client.post("/api/v1/incidents/connected/preview", json=dotted)
    assert r.status_code == 200, r.text
    q = r.json()["queries"][0]
    assert q["id"] == "datadog/all_logs/billing.worker_v2" and q["query"] == "service:billing.worker_v2"
    assert q["status"] == "ok" and r.json()["collected"]["log"] == ["billing.worker_v2"]
    for evil in ("orders-api OR service:*", "orders-api status:error", 'x" OR "y', "svc*", "svc:prod", "Orders"):
        bad = preview(service=evil, affected_services=[])
        assert (await client.post("/api/v1/incidents/connected/preview", json=bad)).status_code == 422, evil
    loki = preview(
        service="billing.worker_v2",
        affected_services=[],
        sources=[{"connector": "loki", "templates": ["errors_warnings"]}],
    )
    r = await client.post("/api/v1/incidents/connected/preview", json=loki)
    assert r.status_code == 422 and "lower-case slug" in r.json()["error"]["message"]  # Loki unchanged
