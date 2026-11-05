"""C0-G2 regression: terminal workflow states are monotonic (real PostgreSQL).

Once an investigation is cancelled (or completed), no background path — reconciliation of any branch, checkpoint
restoration, outbox delivery, approval expiry, restart, repeated sweeps — may move it back to an active or
approval-pending state, and no new remediation request can be created or executed for it. The independent audit
reproduced the first of these (cancel committed while reconciliation was restoring an interrupt) at ``5079b72``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from opspilot_api import repositories as repo
from opspilot_api.services.approvals import ApprovalService
from opspilot_api.services.commands import CommandDispatcher, enqueue_decision
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_shared.db.models import (
    OpsActionRequest,
    OpsIncident,
    OpsInvestigation,
    OpsWorkflowCommand,
    OpsWorkflowEvent,
    SimActionExecution,
)
from opspilot_shared.domain.actions import ApprovalDecisionKind
from opspilot_shared.domain.common import utcnow
from opspilot_shared.errors import ConflictError
from tests.integration.helpers import make_action

pytestmark = pytest.mark.integration


class SnapGraph:
    """A checkpoint view: ``values``/``next``/pending interrupt, optionally held at a barrier inside ``aget_state``
    so a cancellation can commit between the reconciler's read and its write."""

    def __init__(
        self,
        *,
        values: dict[str, Any] | None = None,
        next_: tuple[str, ...] = (),
        action: dict[str, Any] | None = None,
        barrier: bool = False,
    ) -> None:
        self.values, self.next, self.action = values or {}, next_, action
        self.entered, self.go = asyncio.Event(), asyncio.Event()
        self.barrier = barrier
        self.runs = 0

    async def aget_state(self, _config: Any) -> Any:
        if self.barrier:
            self.entered.set()
            await self.go.wait()
        interrupts = [SimpleNamespace(value={"action": self.action})] if self.action else []
        return SimpleNamespace(values=self.values, next=self.next, tasks=[SimpleNamespace(interrupts=interrupts)])

    async def astream(self, *_a: Any, **_k: Any) -> Any:
        self.runs += 1
        await asyncio.sleep(0)
        return
        yield  # pragma: no cover


async def workflow(sf, *, status: str = "running", action_status: str = "pending") -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """An investigation (no live owner) with one action request; returns ids and the interrupt payload."""
    aid, _, _ = await make_action(sf, status=action_status)
    async with sf() as s, s.begin():
        act = await s.get(OpsActionRequest, aid)
        inv = await s.get(OpsInvestigation, act.investigation_id)
        await s.execute(
            update(OpsInvestigation)
            .where(OpsInvestigation.id == inv.id)
            .values(status=status, run_owner=None, run_lease_until=None)
        )
        payload = {
            "action_id": str(aid),
            "action_type": act.action_type,
            "parameters": act.parameters,
            "params_hash": act.params_hash,
            "rationale": act.rationale,
            "risk": act.risk,
        }
    return {"inv": inv.id, "incident": inv.incident_id, "aid": aid, "action": payload}


def service(sf, graph, settings=None) -> tuple[InvestigationService, InvestigationRunner]:  # type: ignore[no-untyped-def]
    runner = InvestigationRunner(sf, graph, 1)
    svc = InvestigationService(sf, runner, graph, "test")
    if settings is not None:
        svc.dispatcher = CommandDispatcher(sf, runner, graph, settings)
    return svc, runner


async def drain(runner: InvestigationRunner) -> None:
    for t in list(runner._tasks.values()):
        await asyncio.gather(t, return_exceptions=True)


async def state(sf, inv: uuid.UUID) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    async with sf() as s:
        row = await s.get(OpsInvestigation, inv)
        incident = await s.get(OpsIncident, row.incident_id)
        actions = list(
            (await s.execute(select(OpsActionRequest).where(OpsActionRequest.investigation_id == inv))).scalars()
        )
        executed = (
            await s.execute(
                select(func.count())
                .select_from(SimActionExecution)
                .where(SimActionExecution.action_id.in_([a.id for a in actions] or [uuid.uuid4()]))
            )
        ).scalar_one()
        events = [
            e.event_type
            for e in (
                await s.execute(
                    select(OpsWorkflowEvent)
                    .where(OpsWorkflowEvent.investigation_id == inv)
                    .order_by(OpsWorkflowEvent.id)
                )
            ).scalars()
        ]
    return {
        "status": row.status,
        "incident": incident.status,
        "actions": {str(a.id): a.status for a in actions},
        "executed": executed,
        "events": events,
        "result": row.result,
    }


# ----------------------------------------------------------------------------- cancel versus reconcile
async def test_codex_r3_cancel_during_reconcile_restoration_is_not_resurrected(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Independent audit R3: reconcile selected a running abandoned row, ``cancel()`` committed, then reconcile
    restored ``awaiting_approval``. The cancellation must win."""
    w = await workflow(session_factory)
    graph = SnapGraph(
        values={"status": "awaiting_approval"}, next_=("await_approval",), action=w["action"], barrier=True
    )
    svc, _ = service(session_factory, graph)
    sweep = asyncio.create_task(svc.reconcile(expired_leases_only=True))
    await asyncio.wait_for(graph.entered.wait(), 10)
    assert (await svc.cancel(w["inv"], "sre")).status == "cancelled"
    graph.go.set()
    counts = await asyncio.wait_for(sweep, 10)
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled" and st["incident"] == "open"
    assert st["actions"] == {str(w["aid"]): "cancelled"} and st["executed"] == 0
    assert counts == {"skipped_terminal": 1} and "stale_interrupt_ignored" in st["events"]


@pytest.mark.parametrize("branch", ["finished", "interrupted", "queued_dispatch", "pending_command"])
async def test_cancel_during_every_reconcile_branch_is_final(settings, session_factory, branch: str) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="queued" if branch == "queued_dispatch" else "running")
    graph = SnapGraph(
        values={
            "finished": {"status": "completed", "outcome": {"code": "mitigated"}},
            "interrupted": {"status": "running"},
            "queued_dispatch": {},
            "pending_command": {"status": "running"},
        }[branch],
        next_=() if branch in ("finished", "queued_dispatch") else ("rca",),
        barrier=True,
    )
    svc, runner = service(session_factory, graph, settings)
    if branch == "pending_command":
        async with session_factory() as s, s.begin():
            await enqueue_decision(
                s,
                investigation_id=w["inv"],
                action_id=w["aid"],
                payload={"decision": "approve", "action_id": str(w["aid"])},
            )
    sweep = asyncio.create_task(svc.reconcile(expired_leases_only=True))
    await asyncio.wait_for(graph.entered.wait(), 10)
    await svc.cancel(w["inv"], "sre")
    graph.go.set()
    await asyncio.wait_for(sweep, 10)
    await drain(runner)
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled", branch
    assert st["incident"] == "open"  # never "mitigated"/"investigating" from a stale checkpoint
    assert graph.runs == 0 and st["executed"] == 0
    assert set(st["actions"].values()) == {"cancelled"}


# ----------------------------------------------------------------------------- restart / repeated sweeps
async def test_cancel_then_restart_and_repeated_reconciliation(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval")
    first, _ = service(session_factory, SnapGraph())
    await first.cancel(w["inv"], "sre")
    # "Restart": a new runner/service against the same database, the checkpoint still paused on the action.
    graph = SnapGraph(values={"status": "awaiting_approval"}, next_=("await_approval",), action=w["action"])
    svc, runner = service(session_factory, graph, settings)
    for _ in range(3):
        await svc.reconcile()
        await svc.reconcile(expired_leases_only=True)
    await drain(runner)
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled" and graph.runs == 0
    assert st["events"].count("run_cancelled") == 1 and "approval_requested" not in st["events"]


async def test_crash_between_cancel_commit_and_checkpoint_reconciliation(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    """The owner died holding a lease; the operator's cancellation committed; the checkpoint (written by the dead
    owner after the cancel) is paused on a *new* action. Recovery must not create that request or reopen the run."""
    w = await workflow(session_factory)
    async with session_factory() as s, s.begin():
        await s.execute(
            update(OpsInvestigation)
            .where(OpsInvestigation.id == w["inv"])
            .values(run_owner="dead-process", run_lease_until=utcnow())
        )
    svc0, _ = service(session_factory, SnapGraph())
    await svc0.cancel(w["inv"], "sre")
    new_action = {**w["action"], "action_id": str(uuid.uuid4())}
    graph = SnapGraph(values={"status": "awaiting_approval"}, next_=("await_approval",), action=new_action)
    svc, runner = service(session_factory, graph, settings)
    await svc.reconcile(expired_leases_only=True)
    await svc.reconcile()
    # Even a direct restoration attempt (the path reconcile uses) is refused for the terminal row.
    async with session_factory() as s, s.begin():
        await runner._on_interrupt(s, w["inv"], w["incident"], {"action": new_action})
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled" and new_action["action_id"] not in st["actions"]


# ----------------------------------------------------------------------------- cancel variants
async def test_cancel_while_awaiting_approval_then_stale_checkpoint_is_ignored(session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval")
    svc, _runner = service(session_factory, SnapGraph())
    await svc.cancel(w["inv"], "sre")
    before = (await state(session_factory, w["inv"]))["result"]
    # stale checkpoints: still paused (result refresh) and finished as mitigated (final persistence)
    for graph in (
        SnapGraph(values={"rca": {"x": 1}}, next_=("await_approval",), action=w["action"]),
        SnapGraph(values={"status": "completed", "outcome": {"code": "mitigated"}}),
    ):
        stale = InvestigationRunner(session_factory, graph, 1)
        assert await stale.finalize(w["inv"]) is False
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled" and st["incident"] == "open" and st["result"] == before


async def test_duplicate_and_concurrent_cancellation_is_idempotent(session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval")
    svc, _ = service(session_factory, SnapGraph())
    results = await asyncio.gather(svc.cancel(w["inv"], "a"), svc.cancel(w["inv"], "b"), return_exceptions=True)
    assert sorted(type(r).__name__ for r in results) == ["ConflictError", "OpsInvestigation"]
    with pytest.raises(ConflictError, match="already cancelled"):
        await svc.cancel(w["inv"], "c")
    st = await state(session_factory, w["inv"])
    assert st["status"] == "cancelled" and st["events"].count("run_cancelled") == 1


async def test_approval_and_cancellation_race_never_executes_or_reopens(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    for _ in range(4):
        w = await workflow(session_factory, status="awaiting_approval")
        graph = SnapGraph(values={"status": "awaiting_approval"}, next_=("await_approval",), action=w["action"])
        svc, runner = service(session_factory, graph, settings)
        approvals = ApprovalService(session_factory, runner, graph, settings, svc.dispatcher)
        decided, cancelled = await asyncio.gather(
            approvals.decide(
                w["aid"],
                decision=ApprovalDecisionKind.APPROVE,
                params_hash=w["action"]["params_hash"],
                decided_by="sre",
                comment=None,
            ),
            svc.cancel(w["inv"], "other-sre"),
            return_exceptions=True,
        )
        await drain(runner)
        assert not isinstance(cancelled, Exception), cancelled  # nothing was claimed for execution
        assert not isinstance(decided, Exception) or isinstance(decided, ConflictError)
        st = await state(session_factory, w["inv"])
        assert st["status"] == "cancelled" and st["executed"] == 0
        assert st["actions"] == {str(w["aid"]): "cancelled"}
        async with session_factory() as s:
            cmd = (
                await s.execute(select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id == w["aid"]))
            ).scalar_one_or_none()
        assert cmd is None or cmd.status in ("cancelled", "delivered", "failed")


async def test_outbox_delivery_after_cancellation_is_inert(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval", action_status="approved")
    async with session_factory() as s, s.begin():
        await enqueue_decision(
            s,
            investigation_id=w["inv"],
            action_id=w["aid"],
            payload={"decision": "approve", "action_id": str(w["aid"])},
        )
    graph = SnapGraph(values={"status": "awaiting_approval"}, next_=("await_approval",), action=w["action"])
    svc, runner = service(session_factory, graph, settings)
    await svc.cancel(w["inv"], "sre")
    assert svc.dispatcher is not None
    for _ in range(2):
        await svc.dispatcher.dispatch_due()
    await drain(runner)
    async with session_factory() as s:
        cmd = (await s.execute(select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id == w["aid"]))).scalar_one()
    assert cmd.status == "cancelled" and graph.runs == 0
    assert (await state(session_factory, w["inv"]))["status"] == "cancelled"


async def test_expired_approval_after_cancellation_does_nothing(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval")
    graph = SnapGraph(values={"status": "awaiting_approval"}, next_=("await_approval",), action=w["action"])
    svc, runner = service(session_factory, graph, settings)
    await svc.cancel(w["inv"], "sre")
    approvals = ApprovalService(
        session_factory, runner, graph, settings.model_copy(update={"approval_request_ttl_seconds": 0})
    )
    async with session_factory() as s:
        row = await s.get(OpsActionRequest, w["aid"])
    assert await approvals.expire(row, reason="ttl") is False
    assert await approvals.expire_stale() == 0 or (await state(session_factory, w["inv"]))["status"] == "cancelled"
    async with session_factory() as s:
        cmd = (
            await s.execute(select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id == w["aid"]))
        ).scalar_one_or_none()
    st = await state(session_factory, w["inv"])
    assert cmd is None and st["status"] == "cancelled" and st["actions"] == {str(w["aid"]): "cancelled"}


# ----------------------------------------------------------------------------- no new remediation after terminal
async def test_terminal_investigation_cannot_request_or_run_new_remediation(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory, status="awaiting_approval")
    svc, runner = service(session_factory, SnapGraph(), settings)
    await svc.cancel(w["inv"], "sre")
    new_action = {**w["action"], "action_id": str(uuid.uuid4())}
    async with session_factory() as s, s.begin():
        await runner._on_interrupt(s, w["inv"], w["incident"], {"action": new_action})
    graph = SnapGraph(values={"status": "running"}, next_=("execute",))
    runner2 = InvestigationRunner(session_factory, graph, 1)
    runner2.submit(w["inv"], None)
    await drain(runner2)
    st = await state(session_factory, w["inv"])
    assert new_action["action_id"] not in st["actions"] and graph.runs == 0 and st["status"] == "cancelled"
    with pytest.raises(ConflictError):
        await svc.resume(w["inv"])


async def test_database_refuses_status_changes_out_of_absorbing_states(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Backstop independent of application code: a raw UPDATE cannot reopen a completed or cancelled row."""
    for terminal, target in (("cancelled", "running"), ("completed", "awaiting_approval"), ("cancelled", "completed")):
        w = await workflow(session_factory)
        async with session_factory() as s, s.begin():
            await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == w["inv"]).values(status=terminal))
        with pytest.raises(DBAPIError, match="terminal"):
            async with session_factory() as s, s.begin():
                await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == w["inv"]).values(status=target))
        assert (await state(session_factory, w["inv"]))["status"] == terminal


async def test_failed_is_reopened_only_by_explicit_operator_resume(session_factory) -> None:  # type: ignore[no-untyped-def]
    w = await workflow(session_factory)
    async with session_factory() as s, s.begin():
        assert await repo.transition_investigation(s, w["inv"], "failed", reason="test") == "running"
    graph = SnapGraph(values={"status": "running"}, next_=("rca",), action=None)
    svc, runner = service(session_factory, graph)
    async with session_factory() as s, s.begin():  # background restoration: refused
        await runner._on_interrupt(s, w["inv"], w["incident"], {"action": w["action"]})
        assert await repo.transition_investigation(s, w["inv"], "running", reason="background") is None
    assert (await state(session_factory, w["inv"]))["status"] == "failed"
    await svc.resume(w["inv"])  # operator: failed -> interrupted -> running
    await drain(runner)
    st = await state(session_factory, w["inv"])
    assert graph.runs == 1 and "resume_requested" in st["events"] and st["status"] == "running"
