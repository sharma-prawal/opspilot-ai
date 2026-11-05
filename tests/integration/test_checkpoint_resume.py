"""Durable execution: pause at approval, throw away graph + DB pool, resume from Postgres."""

import uuid

import pytest
from langgraph.types import Command
from sqlalchemy import select

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps
from opspilot_api.checkpointing import checkpointer_pool
from opspilot_shared.approvals import issue_token
from opspilot_shared.db.models import OpsActionRequest, OpsInvestigation, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways, make_incident

pytestmark = pytest.mark.integration


async def test_resume_after_restart_executes_approved_action(
    settings, session_factory, embedder, ingested, owner
) -> None:  # type: ignore[no-untyped-def]
    inc_id, env = await make_incident(session_factory)
    inv_id = uuid.uuid4()
    async with session_factory() as s, s.begin():
        s.add(OpsInvestigation(id=inv_id, incident_id=inc_id, status="running", model="scripted"))
    cfg = {"configurable": {"thread_id": str(inv_id)}}
    gw = inprocess_gateways(settings, session_factory, embedder)

    # --- process 1: run until the approval interrupt -------------------------------------
    async with gw("read") as read, gw("actions") as act, checkpointer_pool(settings, fence=owner.fence) as saver:
        g1 = build_graph(AgentDeps(chat=ScriptedChatModel(), tools=read, actions=act), saver)
        await g1.ainvoke({"investigation_id": str(inv_id), "incident_id": str(inc_id)}, cfg)
        snap = await g1.aget_state(cfg)
        assert snap.next == ("await_approval",)
        action = snap.tasks[0].interrupts[0].value["action"]
        assert action["parameters"] == {"service": "ledger-service", "deployment_id": "dep-ls-0042"}
        # Evidence-driven routing happened (alerting service → dependency → ledger telemetry)
        assert "telemetry:ledger-service" in snap.values["completed_tasks"]
    del g1, saver  # pool closed by the context manager: nothing in memory survives

    async with session_factory() as s:  # nothing executed while waiting for approval
        assert (
            await s.execute(select(SimActionExecution).where(SimActionExecution.environment_id == env))
        ).first() is None
        # approval recorded out-of-band, as ApprovalService would
        s.add(
            OpsActionRequest(
                id=uuid.UUID(action["action_id"]),
                investigation_id=inv_id,
                incident_id=inc_id,
                environment_id=env,
                action_type=action["action_type"],
                parameters=action["parameters"],
                params_hash=action["params_hash"],
                rationale="r",
                risk="medium",
                status="approved",
            )
        )
        await s.commit()

    # --- process 2: fresh pool + fresh graph, resume from the checkpoint ------------------
    async with gw("read") as read, gw("actions") as act, checkpointer_pool(settings, fence=owner.fence) as saver2:
        g2 = build_graph(AgentDeps(chat=ScriptedChatModel(), tools=read, actions=act), saver2)
        assert (await g2.aget_state(cfg)).next == ("await_approval",)
        tok = issue_token(
            settings.action_signing_key.get_secret_value(),
            action_id=uuid.UUID(action["action_id"]),
            params_hash=action["params_hash"],
            approved_by="tester",
            ttl_seconds=60,
            epoch=owner.fence[0],
            owner_pid=owner.fence[1],
        )
        await g2.ainvoke(
            Command(
                resume={
                    "action_id": action["action_id"],
                    "params_hash": action["params_hash"],
                    "decision": "approve",
                    "decided_by": "tester",
                    "approval_token": tok,
                }
            ),
            cfg,
        )
        snap2 = await g2.aget_state(cfg)
        final = snap2.values
    assert final["status"] == "completed" and not snap2.next
    assert final["remediation"]["status"] == "succeeded"
    assert final["verification"]["recovered"] is True
    assert "## Ranked hypotheses" in final["report"]["markdown"]


async def test_rejection_path_never_executes(settings, session_factory, embedder, ingested, owner) -> None:  # type: ignore[no-untyped-def]
    inc_id, env = await make_incident(session_factory)
    inv_id = uuid.uuid4()
    async with session_factory() as s, s.begin():
        s.add(OpsInvestigation(id=inv_id, incident_id=inc_id, status="running", model="scripted"))
    cfg = {"configurable": {"thread_id": str(inv_id)}}
    gw = inprocess_gateways(settings, session_factory, embedder)
    async with gw("read") as read, gw("actions") as act, checkpointer_pool(settings, fence=owner.fence) as saver:
        g = build_graph(AgentDeps(chat=ScriptedChatModel(), tools=read, actions=act), saver)
        await g.ainvoke({"investigation_id": str(inv_id), "incident_id": str(inc_id)}, cfg)
        a = (await g.aget_state(cfg)).tasks[0].interrupts[0].value["action"]
        await g.ainvoke(
            Command(
                resume={
                    "action_id": a["action_id"],
                    "params_hash": a["params_hash"],
                    "decision": "reject",
                    "decided_by": "tester",
                    "comment": "not now",
                }
            ),
            cfg,
        )
        final = (await g.aget_state(cfg)).values
    assert final["status"] == "completed" and final.get("remediation") is None
    assert final["outcome"]["code"] == "remediation_rejected" and final["outcome"]["escalate"] is True
    assert "Last decision:** reject" in final["report"]["markdown"]
    async with session_factory() as s:
        assert (
            await s.execute(select(SimActionExecution).where(SimActionExecution.environment_id == env))
        ).first() is None
