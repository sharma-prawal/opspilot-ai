"""v0.10 HTTP contract for Azure Monitor: listing, connection test, discovery, preview, connected incident, read-only
investigation, report, deletion — next to Datadog and Loki/Prometheus.

Real app, database and MCP servers; Azure Monitor is the synthetic Logs API fixture (``tests.fakes.azure_monitor``).
Contract testing only: no Azure subscription, tenant or workspace is contacted.
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
from opspilot_shared.connectors.azure_monitor import FIXTURE_TOKEN
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.db.models import OpsActionRequest, OpsIncident, OpsUploadedDataset, SimActionExecution
from tests.fakes.azure_monitor import INCIDENT_TIME, LOCAL, WINDOW, WORKSPACE, FakeAzureMonitor, az
from tests.fakes.datadog import API_KEY, APP_KEY, FakeDatadog
from tests.fakes.models import ScriptedChatModel
from tests.fakes.telemetry import FakeTelemetry
from tests.integration.helpers import inprocess_gateways
from tests.integration.test_api import poll
from tests.unit.test_azure_monitor_investigation import pool_rca
from tests.unit.test_upload_investigation import plan

pytestmark = pytest.mark.integration
AZ_SOURCES = [
    {
        "connector": "azure_monitor",
        "templates": [
            "trace_warnings",
            "trace_lifecycle",
            "exceptions",
            "failed_requests",
            "request_failure_ratio",
            "p95_latency_ms",
        ],
    }
]


def body(**over: Any) -> dict[str, Any]:
    return {
        "title": "Orders failing with 502s",
        "description": "orders-api failed-request alert fired (synthetic Azure Monitor fixture).",
        "service": "orders-api",
        "affected_services": ["payment-service"],
        "severity": "SEV2",
        "incident_time": INCIDENT_TIME,
        "sources": AZ_SOURCES,
        **WINDOW,
        **over,
    }


def preview(**over: Any) -> dict[str, Any]:
    b = body(**over)
    for k in ("title", "description", "severity"):
        b.pop(k)
    return b


def no_secrets(text: str) -> bool:
    return FIXTURE_TOKEN not in text and "Bearer " not in text and az.FAKE_SECRET not in text


@pytest.fixture
async def azm() -> FakeAzureMonitor:
    return FakeAzureMonitor()


@pytest.fixture
async def client(settings, session_factory, embedder, ingested, azm) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    telemetry, dd = FakeTelemetry(), FakeDatadog()
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        loki_url="http://loki.test",
        loki_tenant_id="opspilot-demo",
        prometheus_url="http://prometheus.test",
        datadog_enabled=True,
        datadog_api_key=API_KEY,
        datadog_app_key=APP_KEY,
        azure_monitor_enabled=True,
        azure_monitor_auth_mode="fixture",
        azure_monitor_local_api_url=LOCAL,
        azure_monitor_workspace_id=WORKSPACE,
    )
    registry = ConnectorRegistry.from_settings(
        cfg,
        transports={
            "loki": telemetry.transport(),
            "prometheus": telemetry.transport(),
            "datadog": dd.transport(),
            "azure_monitor": azm.transport(),
        },
    )
    chat = ScriptedChatModel({PlanOutput: plan, RcaOutput: pool_rca})
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


async def test_azure_is_listed_tested_and_discovered_without_secrets(
    client: httpx.AsyncClient, azm: FakeAzureMonitor
) -> None:
    r = await client.get("/api/v1/connectors")
    assert r.status_code == 200 and no_secrets(r.text)
    by_id = {c["id"]: c for c in r.json()["connectors"]}
    assert set(by_id) == {"loki", "prometheus", "datadog", "azure_monitor", "cloudwatch"}  # v0.11: listed, unconfigured
    a = by_id["azure_monitor"]
    assert a["configured"] and a["fixture"] is True and a["workspace_id"] == WORKSPACE
    assert a["signals"] == ["log", "metric", "span"] and {t["signal"] for t in a["templates"]} == {
        "log",
        "metric",
        "span",
    }
    assert "Azure Monitor" not in r.json()["planned"]

    t = await client.post("/api/v1/connectors/azure_monitor/test")
    assert t.status_code == 200 and t.json()["status"] == "ok" and no_secrets(t.text)
    assert set(t.json()["tables"]) == {"AppTraces", "AppExceptions", "AppRequests", "AppDependencies"}
    azm.fixture.scenario[WORKSPACE] = "forbidden"  # RBAC missing: a result, never an HTTP 401/403 for the operator
    t = await client.post("/api/v1/connectors/azure_monitor/test")
    assert t.status_code == 200 and t.json()["status"] == "permission_denied"
    azm.fixture.scenario[WORKSPACE] = "incident"

    s = await client.post("/api/v1/connectors/azure_monitor/services", json=WINDOW)
    assert s.status_code == 200
    assert s.json()["services"] == ["billing.worker", "inventory-service", "orders-api", "payment-service"]
    assert any("Notification Worker" in n for n in s.json()["notes"])
    anon = await client.post("/api/v1/connectors/azure_monitor/test", headers={"Authorization": ""})
    assert anon.status_code == 401


async def test_request_validation_accepts_ids_only(client: httpx.AsyncClient) -> None:
    for extra in (
        {"workspace_id": "00000000-0000-4000-8000-000000000000"},
        {"url": "https://api.loganalytics.azure.com"},
        {"query": "AppTraces | take 10"},
        {"resource_id": "/subscriptions/x"},
    ):
        assert (await client.post("/api/v1/incidents/connected/preview", json=preview(**extra))).status_code == 422
    raw = preview(sources=[{"connector": "azure_monitor", "templates": ["exceptions"], "kql": "union *"}])
    assert (await client.post("/api/v1/incidents/connected/preview", json=raw)).status_code == 422
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(sources=[{"connector": "azure_monitor", "templates": ["purge_table"]}]),
    )
    assert r.status_code == 422 and "unknown azure_monitor template" in r.json()["error"]["message"]
    for evil in ('orders-api" or 1==1 //', "orders-api | union *", "Orders API", "*"):
        assert (await client.post("/api/v1/incidents/connected/preview", json=preview(service=evil))).status_code == 422
    long = preview(start="2026-11-16T03:00:00Z", end="2026-11-16T11:30:00Z")
    assert (await client.post("/api/v1/incidents/connected/preview", json=long)).status_code == 422


async def test_preview_create_investigate_report_and_delete(
    client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    azm: FakeAzureMonitor,
) -> None:
    async with session_factory() as s:
        incidents_before = (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one()
        executions_before = (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one()
    p = await client.post("/api/v1/incidents/connected/preview", json=preview())
    assert p.status_code == 200, p.text
    view = p.json()
    recs = view["summary"]["records"]
    assert view["usable"] and recs["log"] > 0 and recs["metric"] > 0 and recs["span"] > 0
    assert view["collected"]["span"] == ["orders-api", "payment-service"]
    assert view["summary"]["redactions"] >= 1 and no_secrets(p.text)
    series = {(x["service"], x["metric"]): x for x in view["series"]}
    p95 = series[("payment-service", "p95_latency_ms")]
    assert p95["unit"] == "ms" and len(p95["points"]) == p95["count"] > 100  # every returned bin, none invented
    async with session_factory() as s:  # a preview stores nothing
        assert (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one() == incidents_before

    r = await client.post("/api/v1/incidents/connected", json=body())
    assert r.status_code == 201, r.text
    inc = r.json()
    ds = (await client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    assert ds["summary"]["connectors"] == ["azure_monitor"] and ds["summary"]["records"]["span"] > 0
    assert {q["workspace"] for q in ds["queries"]} == {WORKSPACE}
    async with session_factory() as s:  # the frozen snapshot holds no token
        row = (
            await s.execute(select(OpsUploadedDataset).where(OpsUploadedDataset.incident_id == inc["id"]))
        ).scalar_one()
        assert no_secrets(str(row.records) + str(row.queries) + str(row.summary))

    requests_before = len(azm.requests)
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert len(azm.requests) == requests_before  # investigated from the frozen snapshot only
    assert done["result"]["outcome"]["code"] == "analysis_complete" and done["result"]["outcome"]["read_only"]
    assert (await client.get(f"/api/v1/investigations/{inv}/actions")).json() == []
    tools = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    servers = {t["tool"]: t["server"] for t in tools}
    assert servers["search_logs"] == servers["get_service_dependencies"] == "opspilot-connected-telemetry"
    evidence = (await client.get(f"/api/v1/investigations/{inv}/evidence")).json()
    report = (await client.get(f"/api/v1/investigations/{inv}/report")).json()["markdown"]
    assert "snapshot of Azure Monitor telemetry" in report and "_(source: azure_monitor/" in report
    assert f"workspace {WORKSPACE}" in report
    cited = {i for h in done["result"]["rca"]["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited and cited <= {e["evidence_id"] for e in evidence}
    for path in (f"/api/v1/incidents/{inc['id']}/dataset", f"/api/v1/investigations/{inv}"):
        assert no_secrets((await client.get(path)).text), path
    for path in ("tool-calls", "evidence", "events", "report"):
        assert no_secrets((await client.get(f"/api/v1/investigations/{inv}/{path}")).text), path
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
    async with session_factory() as s:
        left = (
            await s.execute(
                select(func.count()).select_from(OpsUploadedDataset).where(OpsUploadedDataset.incident_id == inc["id"])
            )
        ).scalar_one()
        assert left == 0
    assert {(r["method"], r["path"]) for r in azm.requests} == {("POST", f"/v1/workspaces/{WORKSPACE}/query")}


async def test_every_provider_together(client: httpx.AsyncClient) -> None:
    sources = [
        {"connector": "loki", "templates": ["errors_warnings"]},
        {"connector": "prometheus", "templates": ["http_5xx_ratio"]},
        {"connector": "datadog", "templates": ["errors_warnings"]},
        {"connector": "azure_monitor", "templates": ["trace_warnings"]},
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
    assert q["datadog/errors_warnings/orders-api"]["status"] == "empty"
    assert q["azure_monitor/trace_warnings/orders-api"]["status"] == "empty"  # the fixture holds 2026-11-16 only


async def test_a_failing_azure_workspace_does_not_affect_other_connectors(
    client: httpx.AsyncClient, azm: FakeAzureMonitor
) -> None:
    azm.fixture.scenario[WORKSPACE] = "unavailable"
    sources = [
        {"connector": "loki", "templates": ["errors_warnings"]},
        {"connector": "azure_monitor", "templates": ["trace_warnings"]},
    ]
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(
            sources=sources,
            service="checkout-api",
            affected_services=[],
            start="2026-11-12T07:30:00Z",
            end="2026-11-12T09:45:00Z",
            incident_time="2026-11-12T09:16:00Z",
        ),
    )
    assert r.status_code == 200, r.text
    q = {x["id"]: x for x in r.json()["queries"]}
    assert q["loki/errors_warnings/checkout-api"]["status"] == "ok"
    assert q["azure_monitor/trace_warnings/checkout-api"]["error"]["kind"] == "unavailable"
    assert any(
        w.startswith("azure_monitor/trace_warnings/checkout-api failed (unavailable)") for w in r.json()["warnings"]
    )
