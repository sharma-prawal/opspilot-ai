"""v0.11 HTTP contract for AWS CloudWatch: listing, connection test, discovery, preview, connected incident, read-only
investigation, report, deletion — next to Azure Monitor, Datadog and Loki/Prometheus.

Real app, database and MCP servers; CloudWatch is the synthetic protocol fixture on loopback, reached through the
real AWS SDK. Contract testing only: no AWS account, credential or endpoint is contacted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_api.main import create_app
from opspilot_shared.connectors.cloudwatch import FIXTURE_SECRET_KEY
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.db.models import OpsActionRequest, OpsIncident, OpsUploadedDataset, SimActionExecution
from tests.fakes.azure_monitor import LOCAL as AZ_LOCAL
from tests.fakes.azure_monitor import WORKSPACE, FakeAzureMonitor
from tests.fakes.cloudwatch import INCIDENT_TIME, WINDOW, FixtureServer, cw, fixture_server, settings
from tests.fakes.datadog import API_KEY, APP_KEY, FakeDatadog
from tests.fakes.models import ScriptedChatModel
from tests.fakes.telemetry import FakeTelemetry
from tests.integration.helpers import inprocess_gateways
from tests.integration.test_api import poll
from tests.unit.test_cloudwatch_investigation import pool_rca
from tests.unit.test_upload_investigation import plan

pytestmark = pytest.mark.integration
CW_SOURCES = [
    {
        "connector": "cloudwatch",
        "templates": ["cw_errors", "cw_lifecycle", "cw_log_error_count", "alb_target_5xx", "custom_metrics"],
    }
]


def body(**over: Any) -> dict[str, Any]:
    return {
        "title": "Checkout failing: inventory timeouts",
        "description": "api-gateway 5xx alarm (synthetic CloudWatch fixture).",
        "service": "inventory-service",
        "affected_services": ["checkout-service"],
        "severity": "SEV2",
        "incident_time": INCIDENT_TIME,
        "sources": CW_SOURCES,
        **WINDOW,
        **over,
    }


def preview(**over: Any) -> dict[str, Any]:
    b = body(**over)
    for k in ("title", "description", "severity"):
        b.pop(k)
    return b


def no_secrets(text: str) -> bool:
    return FIXTURE_SECRET_KEY not in text and "AKIA" not in text and cw.FAKE_SECRET not in text


@pytest.fixture
def cwsrv() -> Iterator[FixtureServer]:
    with fixture_server() as s:
        yield s


@pytest.fixture
async def client(settings_, session_factory, embedder, ingested, cwsrv) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    telemetry, dd, azm = FakeTelemetry(), FakeDatadog(), FakeAzureMonitor()
    cfg = settings(
        cwsrv.url,
        loki_url="http://loki.test",
        loki_tenant_id="opspilot-demo",
        prometheus_url="http://prometheus.test",
        datadog_enabled=True,
        datadog_api_key=API_KEY,
        datadog_app_key=APP_KEY,
        azure_monitor_enabled=True,
        azure_monitor_auth_mode="fixture",
        azure_monitor_local_api_url=AZ_LOCAL,
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
        settings_,
        chat=chat,
        gateways=inprocess_gateways(settings_, session_factory, embedder),
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
            headers={"Authorization": f"Bearer {settings_.operator_token.get_secret_value()}"},
            timeout=120,
        ) as c:
            yield c
    finally:
        stop.set()
        await task


@pytest.fixture
def settings_(settings):  # type: ignore[no-untyped-def]
    return settings


async def test_cloudwatch_is_listed_tested_and_discovered_without_secrets(
    client: httpx.AsyncClient, cwsrv: FixtureServer
) -> None:
    r = await client.get("/api/v1/connectors")
    assert r.status_code == 200 and no_secrets(r.text)
    by_id = {c["id"]: c for c in r.json()["connectors"]}
    assert set(by_id) == {"loki", "prometheus", "datadog", "azure_monitor", "cloudwatch"}
    c = by_id["cloudwatch"]
    assert c["configured"] and c["fixture"] is True and c["region"] == "us-east-1" and c["auth_mode"] == "fixture"
    assert c["signals"] == ["log", "metric"] and "/ecs/shop-prod/inventory-service" in c["log_groups"]
    assert "logs:StopQuery" in c["permissions"]["actions"]
    assert "CloudWatch" not in " ".join(r.json()["planned"])

    t = await client.post("/api/v1/connectors/cloudwatch/test")
    assert t.status_code == 200 and t.json()["status"] == "partial" and no_secrets(t.text)
    doc = t.json()
    assert doc["identity"]["account"] == cw.ACCOUNT and "fixture-operator" not in t.text
    assert doc["log_groups"]["/ecs/shop-prod/audit-worker"]["status"] == "permission_denied"
    assert doc["log_groups"]["/ecs/shop-prod/pricing-service"]["status"] == "unsupported"

    s = await client.post("/api/v1/connectors/cloudwatch/services", json=WINDOW)
    assert s.status_code == 200
    assert s.json()["services"] == [
        "api-gateway", "audit-worker", "checkout-service", "inventory-service", "pricing-service",
    ]  # fmt: skip
    assert any("never inferred" in n for n in s.json()["notes"])
    anon = await client.post("/api/v1/connectors/cloudwatch/test", headers={"Authorization": ""})
    assert anon.status_code == 401
    assert set(cwsrv.state()["calls"]) <= {"StartQuery", "GetQueryResults", "DescribeLogGroups", "GetMetricData"}


async def test_request_validation_accepts_ids_only(client: httpx.AsyncClient, cwsrv: FixtureServer) -> None:
    for extra in (
        {"log_groups": ["/aws/lambda/everything"]},
        {"region": "us-gov-west-1"},
        {"endpoint_url": "https://logs.evil.example"},
        {"query": "fields * | limit 10000"},
        {"role_arn": "arn:aws:iam::123456789012:role/Admin"},
    ):
        assert (await client.post("/api/v1/incidents/connected/preview", json=preview(**extra))).status_code == 422
    raw = preview(sources=[{"connector": "cloudwatch", "templates": ["cw_errors"], "queryString": "fields *"}])
    assert (await client.post("/api/v1/incidents/connected/preview", json=raw)).status_code == 422
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(sources=[{"connector": "cloudwatch", "templates": ["delete_log_group"]}]),
    )
    assert r.status_code == 422 and "unknown cloudwatch template" in r.json()["error"]["message"]
    for evil in ('inventory-service" | fields *', "inventory-service | stats", "Inventory Service", "*"):
        assert (await client.post("/api/v1/incidents/connected/preview", json=preview(service=evil))).status_code == 422
    long = preview(start="2026-11-18T05:00:00Z", end="2026-11-18T15:30:00Z")
    assert (await client.post("/api/v1/incidents/connected/preview", json=long)).status_code == 422
    assert cwsrv.state()["started"] == []  # nothing invalid ever reached AWS


async def test_preview_create_investigate_report_and_delete(
    client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    cwsrv: FixtureServer,
) -> None:
    async with session_factory() as s:
        incidents_before = (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one()
        executions_before = (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one()
    p = await client.post("/api/v1/incidents/connected/preview", json=preview())
    assert p.status_code == 200, p.text
    view = p.json()
    recs = view["summary"]["records"]
    assert view["usable"] and recs["log"] > 0 and recs["metric"] > 0
    assert view["collected"] == {"log": ["checkout-service", "inventory-service"], "metric": ["checkout-service",
                                 "inventory-service"]}  # fmt: skip
    assert no_secrets(p.text)
    q = {x["id"]: x for x in view["queries"]}
    assert q["cloudwatch/alb_target_5xx/checkout-service"]["error"]["kind"] == "not_configured"  # never sent
    assert q["cloudwatch/cw_errors/inventory-service"]["aws"]["query_status"] == "Complete"
    series = {(x["service"], x["metric"]): x for x in view["series"]}
    wait = series[("inventory-service", "db_pool_wait_ms")]
    assert wait["unit"] == "Milliseconds" and len(wait["points"]) == wait["count"] > 100
    async with session_factory() as s:  # a preview stores nothing
        assert (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one() == incidents_before

    r = await client.post("/api/v1/incidents/connected", json=body())
    assert r.status_code == 201, r.text
    inc = r.json()
    ds = (await client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    assert ds["summary"]["connectors"] == ["cloudwatch"]
    assert {x["aws"]["region"] for x in ds["queries"]} == {"us-east-1"}
    async with session_factory() as s:  # the frozen snapshot holds no credential
        row = (
            await s.execute(select(OpsUploadedDataset).where(OpsUploadedDataset.incident_id == inc["id"]))
        ).scalar_one()
        assert no_secrets(str(row.records) + str(row.queries) + str(row.summary))

    calls_before = len(cwsrv.state()["calls"])
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert len(cwsrv.state()["calls"]) == calls_before  # investigated from the frozen snapshot only
    assert done["result"]["outcome"]["code"] == "analysis_complete" and done["result"]["outcome"]["read_only"]
    assert (await client.get(f"/api/v1/investigations/{inv}/actions")).json() == []
    tools = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    assert {t["server"] for t in tools if t["tool"] == "search_logs"} == {"opspilot-connected-telemetry"}
    evidence = (await client.get(f"/api/v1/investigations/{inv}/evidence")).json()
    report = (await client.get(f"/api/v1/investigations/{inv}/report")).json()["markdown"]
    assert "snapshot of AWS CloudWatch telemetry" in report and "_(source: cloudwatch/" in report
    assert "AWS CloudWatch (us-east-1, log, /ecs/shop-prod/inventory-service, query " in report
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
    assert set(cwsrv.state()["calls"]) <= {"StartQuery", "GetQueryResults", "GetMetricData", "DescribeLogGroups"}


async def test_cloudwatch_with_every_other_provider(client: httpx.AsyncClient) -> None:
    sources = [
        {"connector": "loki", "templates": ["errors_warnings"]},
        {"connector": "datadog", "templates": ["errors_warnings"]},
        {"connector": "azure_monitor", "templates": ["trace_warnings"]},
        {"connector": "cloudwatch", "templates": ["cw_errors"]},
    ]
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(
            sources=sources,
            service="checkout-api",
            affected_services=["inventory-service"],
            start="2026-11-12T07:30:00Z",
            end="2026-11-12T09:45:00Z",
            incident_time="2026-11-12T09:16:00Z",
        ),
    )
    assert r.status_code == 200, r.text
    q = {x["id"]: x for x in r.json()["queries"]}
    assert q["loki/errors_warnings/checkout-api"]["status"] == "ok"
    assert q["cloudwatch/cw_errors/checkout-api"]["aws"]["not_queried"]  # not mapped: never sent to AWS
    assert q["cloudwatch/cw_errors/inventory-service"]["status"] == "empty"  # the fixture holds 2026-11-18 only


async def test_a_denied_log_group_does_not_affect_other_evidence(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/incidents/connected/preview",
        json=preview(affected_services=["audit-worker", "pricing-service"], sources=[
            {"connector": "cloudwatch", "templates": ["cw_errors", "lambda_errors"]}]),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    q = {x["id"]: x for x in r.json()["queries"]}
    assert q["cloudwatch/cw_errors/inventory-service"]["status"] == "ok"
    assert q["cloudwatch/cw_errors/audit-worker"]["error"]["kind"] == "permission_denied"
    assert q["cloudwatch/cw_errors/pricing-service"]["error"]["kind"] == "not_found"
    assert q["cloudwatch/lambda_errors/pricing-service"]["status"] == "empty"
    warnings = r.json()["warnings"]
    assert any(w.startswith("cloudwatch/cw_errors/audit-worker failed (permission_denied)") for w in warnings)
    assert any("no logs could be collected for audit-worker, pricing-service" in w for w in warnings)
