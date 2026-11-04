"""HTTP contract tests: real app + lifespan, real DB/checkpointer/MCP protocol, scripted model."""

import asyncio
import re
from collections.abc import AsyncIterator

import httpx
import pytest

from opspilot_api.main import create_app
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(settings, session_factory, embedder, ingested) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    app = create_app(
        settings,
        chat=ScriptedChatModel(),
        gateways=inprocess_gateways(settings, session_factory, embedder),
        embedder=embedder,
    )
    started, stop = asyncio.Event(), asyncio.Event()

    async def host() -> None:  # lifespan (incl. MCP sessions' cancel scopes) lives in one task
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(host())
    await asyncio.wait_for(started.wait(), 30)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},  # BFF-equivalent caller
        ) as c:
            yield c
    finally:
        stop.set()
        await task


def auth(settings) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"}


async def poll(c: httpx.AsyncClient, inv: str, until: set[str], timeout: float = 60) -> dict:  # type: ignore[type-arg]
    for _ in range(int(timeout / 0.2)):
        body = (await c.get(f"/api/v1/investigations/{inv}")).json()
        if body["status"] in until and not body["executing_in_process"]:
            return body
        await asyncio.sleep(0.2)
    raise AssertionError(f"timeout waiting for {until}")


async def test_health_and_validation(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    r = await client.get("/api/v1/incidents/not-a-uuid")
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["path", "incident_id"]
    assert (await client.get("/api/v1/incidents/00000000-0000-0000-0000-000000000000")).status_code == 404
    assert (await client.post("/api/v1/incidents/simulate", json={"scenario": "DROP"})).status_code == 422
    r = await client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    openapi = (await client.get("/openapi.json")).json()
    assert "/api/v1/approvals/{action_id}/decision" in openapi["paths"]


async def test_full_investigation_lifecycle(client: httpx.AsyncClient, settings) -> None:  # type: ignore[no-untyped-def]
    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    assert inc["status"] == "open" and inc["reference"].startswith("INC-")
    r = await client.post(f"/api/v1/incidents/{inc['id']}/investigations")
    assert r.status_code == 202
    inv = r.json()["investigation_id"]
    assert (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).status_code == 409  # one at a time

    await poll(client, inv, {"awaiting_approval"})
    assert (await client.get(f"/api/v1/incidents/{inc['id']}")).json()["status"] == "awaiting_approval"
    [action] = [a for a in (await client.get("/api/v1/approvals")).json() if a["investigation_id"] == inv]
    assert action["status"] == "pending" and action["parameters"]["deployment_id"] == "dep-ls-0042"
    wf = (await client.get(f"/api/v1/investigations/{inv}/workflow")).json()
    assert wf["next"] == ["await_approval"] and wf["pending_interrupts"][0]["action"]["action_id"] == action["id"]

    url = f"/api/v1/approvals/{action['id']}/decision"
    body = {"decision": "approve", "params_hash": action["params_hash"], "decided_by": "sre"}
    assert (await client.post(url, json=body, headers={"Authorization": ""})).status_code == 401
    assert (await client.post(url, json=body, headers={"Authorization": "Bearer wrong-token-value"})).status_code == 401
    bad = await client.post(url, json={**body, "params_hash": "f" * 64}, headers=auth(settings))
    assert bad.status_code == 409 and bad.json()["error"]["class"] == "approval"
    ok = await client.post(url, json=body, headers=auth(settings))
    assert ok.status_code == 200 and ok.json()["status"] == "approved"

    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert (await client.post(url, json=body, headers=auth(settings))).status_code == 409  # replay
    final_action = (await client.get(f"/api/v1/approvals/{action['id']}")).json()
    assert final_action["status"] == "succeeded" and final_action["verification"]["recovered"] is True
    assert (await client.get(f"/api/v1/incidents/{inc['id']}")).json()["status"] == "mitigated"

    evidence = (await client.get(f"/api/v1/investigations/{inv}/evidence")).json()
    ids = {e["evidence_id"] for e in evidence}
    assert any(e["citation"] for e in evidence)  # knowledge evidence carries document/chunk citations
    report = (await client.get(f"/api/v1/investigations/{inv}/report")).json()
    cited = report["result"]["rca"]["hypotheses"][0]["supporting_evidence_ids"]
    assert cited and set(cited) <= ids  # RCA cites only persisted evidence
    assert all(c in report["markdown"] for c in cited)
    # The spent approval token is cleared from state after execution and never leaves the backend.
    assert report["result"]["approval"]["approval_token"] in (None, "[REDACTED]")
    tools = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    assert {"get_incident", "search_logs", "list_recent_deployments", "search_runbooks", "execute_remediation"} <= {
        t["tool"] for t in tools
    }
    events = [e["event_type"] for e in (await client.get(f"/api/v1/investigations/{inv}/events")).json()]
    assert events[0] == "queued" and "approval_requested" in events and events[-1] == "run_completed"


async def test_cancel_pending_investigation(client: httpx.AsyncClient, settings) -> None:  # type: ignore[no-untyped-def]
    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    await poll(client, inv, {"awaiting_approval"})
    assert (await client.post(f"/api/v1/investigations/{inv}/cancel", headers={"Authorization": ""})).status_code == 401
    r = await client.post(f"/api/v1/investigations/{inv}/cancel", headers=auth(settings), json={"actor": "sre"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    actions = (await client.get(f"/api/v1/investigations/{inv}/actions")).json()
    assert [a["status"] for a in actions] == ["cancelled"]
    a = actions[0]
    late = await client.post(
        f"/api/v1/approvals/{a['id']}/decision",
        headers=auth(settings),
        json={"decision": "approve", "params_hash": a["params_hash"], "decided_by": "sre"},
    )
    assert late.status_code == 409


async def test_knowledge_endpoints(client: httpx.AsyncClient) -> None:
    docs = (await client.get("/api/v1/knowledge/documents")).json()
    active = [d for d in docs if d["status"] == "active"]
    assert len(active) >= 19 and {"runbooks/high-5xx-error-rate.md"} <= {d["source_uri"] for d in active}
    res = (await client.post("/api/v1/knowledge/search", json={"query": "LEDGER_WRITE_FAILED", "top_k": 3})).json()
    assert res["results"] and res["results"][0]["source_uri"]
    trace = (await client.get(f"/api/v1/knowledge/queries/{res['query_id']}")).json()
    assert trace["caller"] == "api.knowledge.search" and len(trace["results"]) == len(res["results"])


async def test_direct_backend_access_requires_operator_token_for_every_mutation(client: httpx.AsyncClient) -> None:
    """H1 defence in depth: bypassing the BFF does not bypass authorization. Every POST route rejects
    a caller without the operator token, before any side effect (enumerated from the live route table)."""
    openapi = (await client.get("/openapi.json")).json()
    zero = "00000000-0000-0000-0000-000000000000"
    posts = [p for p, ops in openapi["paths"].items() if "post" in ops]
    assert len(posts) >= 7
    before = (await client.get("/api/v1/incidents")).json()
    for path in posts:
        url = re.sub(r"\{[^}]+\}", zero, path)
        for headers in ({"Authorization": ""}, {"Authorization": "Bearer not-the-operator-token"}):
            r = await client.post(url, json={"scenario": "INC-001", "query": "x"}, headers=headers)
            assert r.status_code == 401, (path, r.status_code)
    assert (await client.get("/api/v1/incidents")).json() == before  # nothing was created
