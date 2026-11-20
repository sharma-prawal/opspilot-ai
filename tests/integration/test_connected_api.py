"""v0.6 HTTP contract: connectors, preview, connected incident, read-only investigation, deletion.

Real app, database and MCP servers; Loki and Prometheus are the in-process fakes of ``tests.fakes.telemetry``.
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
from opspilot_shared.db.models import OpsActionRequest, OpsIncident, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.fakes.telemetry import INCIDENT_TIME, SECRET_TOKEN, WINDOW, FakeTelemetry
from tests.integration.helpers import inprocess_gateways
from tests.integration.test_api import poll
from tests.unit.test_connected_investigation import pool_rca
from tests.unit.test_upload_investigation import plan

pytestmark = pytest.mark.integration
SOURCES = [
    {"connector": "loki", "templates": ["errors_warnings", "lifecycle"]},
    {"connector": "prometheus", "templates": ["http_5xx_ratio", "p95_latency_ms", "db_pool_in_use", "db_pool_max"]},
]


def body(**over: Any) -> dict[str, Any]:
    return {
        "title": "Checkout payments failing",
        "description": "Checkout error-rate alert fired (synthetic telemetry).",
        "service": "checkout-api",
        "affected_services": ["payment-service"],
        "severity": "SEV2",
        "incident_time": INCIDENT_TIME,
        "sources": SOURCES,
        **WINDOW,
        **over,
    }


def preview(**over: Any) -> dict[str, Any]:
    b = body(**over)
    for k in ("title", "description", "severity"):
        b.pop(k)
    return b


@pytest.fixture
async def fake() -> FakeTelemetry:
    return FakeTelemetry(prom_token=SECRET_TOKEN)


@pytest.fixture
async def client(settings, session_factory, embedder, ingested, fake) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    registry = fake.registry(prometheus_url="https://prometheus.test", prometheus_bearer_token=SECRET_TOKEN)
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


async def test_connectors_are_listed_without_secrets_and_tested(client: httpx.AsyncClient, fake: FakeTelemetry) -> None:
    r = await client.get("/api/v1/connectors")
    assert r.status_code == 200 and SECRET_TOKEN not in r.text
    by_id = {c["id"]: c for c in r.json()["connectors"]}
    assert by_id["loki"]["configured"] and by_id["prometheus"]["auth"] == "bearer token"
    assert {t["id"] for t in by_id["prometheus"]["templates"]} >= {"http_5xx_ratio", "db_pool_in_use"}
    assert "Azure Monitor" not in r.json()["planned"]  # v0.10: implemented

    assert (await client.post("/api/v1/connectors/loki/test")).json()["status"] == "ok"
    fake.prom_token = "rotated-token-9999"  # the configured token is now wrong
    t = await client.post("/api/v1/connectors/prometheus/test")
    assert t.status_code == 200 and t.json()["status"] == "auth_error"  # never an HTTP 401 for the operator
    assert SECRET_TOKEN not in t.text
    dd = await client.post("/api/v1/connectors/datadog/test")  # v0.9: known connector, not configured here
    assert (
        dd.status_code == 200 and dd.json()["status"] == "not_configured" and "DATADOG_ENABLED" in dd.json()["message"]
    )
    assert (await client.post("/api/v1/connectors/splunk/test")).status_code == 422
    svc = await client.post("/api/v1/connectors/loki/services", json=WINDOW)
    assert svc.json()["services"] == ["checkout-api", "payment-service", "search-api"]
    anon = await client.post("/api/v1/connectors/loki/test", headers={"Authorization": ""})
    assert anon.status_code == 401


async def test_preview_returns_evidence_and_stores_nothing(client: httpx.AsyncClient, session_factory) -> None:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        before = (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one()
    r = await client.post("/api/v1/incidents/connected/preview", json=preview())
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["usable"] and p["summary"]["records"]["log"] > 0 and p["summary"]["records"]["metric"] > 0
    assert p["summary"]["redactions"] == 1 and "sk_test_EXAMPLE" not in r.text
    q = {x["id"]: x for x in p["queries"]}
    assert q["prometheus/http_5xx_ratio/checkout-api"]["status"] == "ok"
    assert q["prometheus/db_pool_in_use/checkout-api"]["status"] == "empty"
    assert p["samples"]["log"][0]["source"].startswith("loki/") and p["samples"]["metric"][0]["unit"]
    async with session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(OpsIncident))).scalar_one() == before


async def test_request_validation(client: httpx.AsyncClient) -> None:
    long = preview(start="2026-11-12T00:00:00Z", end="2026-11-12T09:45:00Z")
    r = await client.post("/api/v1/incidents/connected/preview", json=long)
    assert r.status_code == 422 and "limit" in r.json()["error"]["message"]
    r = await client.post(
        "/api/v1/incidents/connected/preview", json=preview(sources=[{"connector": "loki", "templates": ["nope_x"]}])
    )
    assert r.status_code == 422 and "unknown loki template" in r.json()["error"]["message"]
    free_form = preview(sources=[{"connector": "prometheus", "templates": ["http_5xx_ratio"], "query": "up"}])
    assert (await client.post("/api/v1/incidents/connected/preview", json=free_form)).status_code == 422
    url = preview(url="http://169.254.169.254/")
    assert (await client.post("/api/v1/incidents/connected/preview", json=url)).status_code == 422
    naive = preview(start="2026-11-12T07:30:00")
    assert (await client.post("/api/v1/incidents/connected/preview", json=naive)).status_code == 422
    r = await client.post("/api/v1/incidents/connected", json=body(service="inventory-api", affected_services=[]))
    assert r.status_code == 422 and "no usable records" in r.json()["error"]["message"]


async def test_connected_incident_is_investigated_read_only_and_deleted(
    client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    fake: FakeTelemetry,
) -> None:
    async with session_factory() as s:
        executions_before = (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one()
    r = await client.post("/api/v1/incidents/connected", json=body())
    assert r.status_code == 201, r.text
    inc = r.json()
    assert inc["evidence_source"] == "connector" and inc["environment_id"] is None
    ds = (await client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    assert ds["files"] == [] and len(ds["queries"]) == 12
    assert ds["summary"]["window"] == {"start": "2026-11-12T07:30:00+00:00", "end": "2026-11-12T09:45:00+00:00"}

    requests_before = len(fake.requests)
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert len(fake.requests) == requests_before  # investigated from the stored snapshot only
    outcome = done["result"]["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] is True
    assert (await client.get(f"/api/v1/investigations/{inv}/actions")).json() == []
    tools = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    servers = {t["tool"]: t["server"] for t in tools}
    assert servers["search_logs"] == "opspilot-connected-telemetry" == servers["query_metrics"]
    assert servers["search_runbooks"] == "opspilot-ops-read"  # runbook RAG stays separate
    report = (await client.get(f"/api/v1/investigations/{inv}/report")).json()["markdown"]
    assert "Connected telemetry — read-only analysis" in report and "Telemetry queries (provenance)" in report
    assert "uncalibrated" in outcome["reason"] and "not calibrated probabilities" in report  # confidence labelled
    # the connector credential never reaches a browser-facing response or the downloadable report
    for path in (f"/api/v1/incidents/{inc['id']}/dataset", f"/api/v1/investigations/{inv}"):
        assert SECRET_TOKEN not in (await client.get(path)).text, path
    for path in ("tool-calls", "evidence", "events", "report"):
        assert SECRET_TOKEN not in (await client.get(f"/api/v1/investigations/{inv}/{path}")).text, path
    assert SECRET_TOKEN not in report
    assert (await client.get(f"/api/v1/incidents/{inc['id']}")).json()["status"] == "open"
    async with session_factory() as s:
        assert (
            await s.execute(
                select(func.count()).select_from(OpsActionRequest).where(OpsActionRequest.incident_id == inc["id"])
            )
        ).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one() == executions_before

    gone = await client.post(f"/api/v1/incidents/{inc['id']}/discard")
    assert gone.status_code == 200 and gone.json()["files_removed"] is False
    assert (await client.get(f"/api/v1/incidents/{inc['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/investigations/{inv}")).status_code == 404
    assert {r.method for r in fake.requests} == {"GET"}


async def test_backend_auth_failure_is_a_per_query_error(client: httpx.AsyncClient, fake: FakeTelemetry) -> None:
    fake.prom_token = "rotated-token-9999"
    r = await client.post("/api/v1/incidents/connected/preview", json=preview())
    assert r.status_code == 200
    p = r.json()
    prom = [q for q in p["queries"] if q["connector"] == "prometheus"]
    assert prom and all(q["status"] == "error" and q["error"]["kind"] == "auth_error" for q in prom)
    assert p["collected"]["metric"] == [] and any("stay unknown" in w for w in p["warnings"])
    assert SECRET_TOKEN not in r.text
