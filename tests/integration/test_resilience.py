"""Resilience: MCP process failure/restart, bounded reconnection, tool timeouts, duplicate requests,
verification failure. No duplicate side effects are allowed anywhere."""

import asyncio
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from mcp import Client, StdioServerParameters
from mcp.server import MCPServer
from sqlalchemy import func, select

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps
from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_api.checkpointing import checkpointer_pool
from opspilot_api.main import create_app
from opspilot_mcp.gateway import McpToolGateway, SupervisedMcpGateway, stdio_params
from opspilot_mcp.read_server import READ_TOOLS
from opspilot_shared.db.models import OpsInvestigation, SimActionExecution
from tests.fakes.models import ScriptedChatModel, _evidence_from
from tests.integration.helpers import inprocess_gateways, make_incident

pytestmark = pytest.mark.integration


def mcp_children(profile: str) -> list[int]:
    out = subprocess.run(
        ["pgrep", "-P", str(os.getpid()), "-f", f"opspilot_mcp.cli serve --profile {profile}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    return [int(p) for p in out]


async def test_mcp_child_crash_is_recovered_transparently(session_factory) -> None:  # type: ignore[no-untyped-def]
    _, env = await make_incident(session_factory)
    gw = SupervisedMcpGateway(
        lambda: stdio_params("read"), profile="read", expected_tools=READ_TOOLS, timeout_seconds=10, backoff_base=0.2
    )
    await gw.start()
    try:
        assert (await gw.call("get_service_health", {"environment_id": env, "service": "ledger-service"}, agent="t")).ok
        [pid] = mcp_children("read")
        os.kill(pid, signal.SIGKILL)  # simulate the MCP server process dying
        await asyncio.sleep(0.3)
        res = await gw.call("get_service_health", {"environment_id": env, "service": "ledger-service"}, agent="t")
        assert res.ok, res.error
        assert gw.reconnects >= 1 and gw.connected
        assert mcp_children("read") and mcp_children("read")[0] != pid  # a new process serves the session
    finally:
        await gw.aclose()
    assert mcp_children("read") == []  # no orphaned child processes


async def test_reconnection_is_bounded_and_fails_fast() -> None:
    broken = StdioServerParameters(command=sys.executable, args=["-c", "import sys; sys.exit(3)"])
    gw = SupervisedMcpGateway(
        lambda: broken,
        profile="read",
        expected_tools=READ_TOOLS,
        timeout_seconds=2,
        max_reconnects=2,
        backoff_base=0.05,
        connect_timeout=20,
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await gw.start()
    assert gw.exhausted and gw.reconnects == 2
    res = await gw.call("get_service_health", {"environment_id": str(uuid.uuid4()), "service": "x"}, agent="t")
    assert not res.ok and "session unavailable" in (res.error or "")
    await gw.aclose()


async def test_tool_timeout_is_reported_not_hung() -> None:
    slow = MCPServer("slow")

    @slow.tool()
    async def sleepy(seconds: float) -> dict[str, float]:
        await asyncio.sleep(seconds)
        return {"slept": seconds}

    async with Client(slow) as c:
        gw = McpToolGateway(c, server_name="slow", tools=frozenset({"sleepy"}), timeout_seconds=0.3)
        res = await gw.call("sleepy", {"seconds": 5}, agent="t")
        assert not res.ok and res.record.status.value == "timeout" and res.record.latency_ms < 2000
        assert (await gw.call("sleepy", {"seconds": 0.01}, agent="t")).ok


# ----------------------------------------------------------------------------- API-level duplicates
@pytest.fixture
async def client(settings, session_factory, embedder, ingested) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    app = create_app(
        settings,
        chat=ScriptedChatModel(),
        embedder=embedder,
        gateways=inprocess_gateways(settings, session_factory, embedder),
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
            headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},  # BFF-equivalent caller
        ) as c:
            yield c
    finally:
        stop.set()
        await task


async def poll(c: httpx.AsyncClient, inv: str, until: set[str]) -> dict[str, Any]:
    for _ in range(300):
        b = (await c.get(f"/api/v1/investigations/{inv}")).json()
        if b["status"] in until and not b["executing_in_process"]:
            return b  # type: ignore[no-any-return]
        await asyncio.sleep(0.2)
    raise AssertionError(f"timeout waiting for {until}")


async def test_duplicate_resume_and_concurrent_approvals_have_single_effect(client, settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    await poll(client, inv, {"awaiting_approval"})
    assert (await client.post(f"/api/v1/investigations/{inv}/resume")).status_code == 409  # must use approvals
    [action] = (await client.get(f"/api/v1/investigations/{inv}/actions")).json()
    auth = {"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"}
    body = {"decision": "approve", "params_hash": action["params_hash"], "decided_by": "sre"}
    url = f"/api/v1/approvals/{action['id']}/decision"
    r1, r2 = await asyncio.gather(client.post(url, json=body, headers=auth), client.post(url, json=body, headers=auth))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    await poll(client, inv, {"completed", "failed"})
    assert (await client.post(f"/api/v1/investigations/{inv}/resume")).status_code == 409  # finished
    async with session_factory() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(SimActionExecution)
                .where(SimActionExecution.action_id == uuid.UUID(action["id"]))
            )
        ).scalar_one()
    assert n == 1


async def test_verification_failure_is_reported_accurately(
    settings, session_factory, embedder, ingested, owner
) -> None:  # type: ignore[no-untyped-def]
    """An executed action that does not fix the incident must end as not_recovered + escalate, not success."""

    def restart_only(messages):  # type: ignore[no-untyped-def]
        ev = _evidence_from(messages)
        cite = [e["id"] for e in ev if e["kind"] in ("log_pattern", "metric_anomaly")][:2]
        return {
            "summary": "restart it",
            "hypotheses": [
                {
                    "title": "ledger-service is stuck",
                    "category": "unknown",
                    "description": "x",
                    "confidence": 0.7,
                    "supporting_evidence_ids": cite,
                }
            ],
            "impact_ongoing": True,
            "escalation": {"required": False},
            "remediation_plan": [{"action_type": "restart_service", "service": "ledger-service", "rationale": "x"}],
        }

    chat = ScriptedChatModel(
        {
            PlanOutput: lambda _m: {
                "category": "unknown",
                "category_confidence": 0.3,
                "rationale": "x",
                "capabilities": ["telemetry", "changes"],
            },
            RcaOutput: restart_only,
        }
    )
    inc_id, env_id = await make_incident(session_factory)
    inv = uuid.uuid4()
    async with session_factory() as s, s.begin():
        s.add(OpsInvestigation(id=inv, incident_id=inc_id, status="running", model="x"))
    cfg = {"configurable": {"thread_id": str(inv)}}
    gw = inprocess_gateways(settings, session_factory, embedder)
    from langgraph.types import Command

    from opspilot_shared.approvals import issue_token

    async with gw("read") as r, gw("actions") as a, checkpointer_pool(settings, fence=owner.fence) as saver:
        g = build_graph(AgentDeps(chat=chat, tools=r, actions=a), saver)
        await g.ainvoke({"investigation_id": str(inv), "incident_id": str(inc_id)}, cfg)
        act = (await g.aget_state(cfg)).tasks[0].interrupts[0].value["action"]
        assert act["action_type"] == "restart_service"
        from opspilot_shared.db.models import OpsActionRequest

        async with session_factory() as s, s.begin():
            s.add(
                OpsActionRequest(
                    id=uuid.UUID(act["action_id"]),
                    investigation_id=inv,
                    incident_id=inc_id,
                    environment_id=env_id,
                    action_type=act["action_type"],
                    parameters=act["parameters"],
                    params_hash=act["params_hash"],
                    rationale="r",
                    risk="low",
                    status="approved",
                )
            )
        tok = issue_token(
            settings.action_signing_key.get_secret_value(),
            action_id=uuid.UUID(act["action_id"]),
            params_hash=act["params_hash"],
            approved_by="t",
            ttl_seconds=60,
            epoch=owner.fence[0],
            owner_pid=owner.fence[1],
        )
        await g.ainvoke(
            Command(
                resume={
                    "action_id": act["action_id"],
                    "params_hash": act["params_hash"],
                    "decision": "approve",
                    "decided_by": "t",
                    "approval_token": tok,
                }
            ),
            cfg,
        )
        final = (await g.aget_state(cfg)).values
    assert final["status"] == "completed" and final["executions"][0]["status"] == "succeeded"
    assert final["verification"]["recovered"] is False
    assert final["outcome"]["code"] == "not_recovered" and final["outcome"]["escalate"] is True
    assert "NOT recovered" in final["report"]["markdown"]
