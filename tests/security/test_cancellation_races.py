"""Audit suspected risk (C0 item H): cancellation versus execution.

The action server's claim (approved -> executing, under a row lock) is the non-cancellable boundary.
Invariant checked throughout: an action is never both cancelled and executed, and an executed action is
never left looking cancelled.
"""

import asyncio
import uuid
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import func, select

from opspilot_api.services.commands import CommandDispatcher, enqueue_decision
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_mcp.action_server import build_action_server
from opspilot_shared.approvals import issue_token
from opspilot_shared.db.models import OpsActionRequest, OpsInvestigation, OpsWorkflowCommand, SimActionExecution
from opspilot_shared.errors import ConflictError
from tests.integration.helpers import backend, make_action
from tests.integration.test_concurrency import StubGraph

pytestmark = pytest.mark.integration


class Runner:
    def __init__(self) -> None:
        self.cancelled: list[uuid.UUID] = []

    def submit(self, *_a: Any, **_k: Any) -> None:  # pragma: no cover
        raise AssertionError("nothing should be submitted")

    async def cancel(self, investigation_id: uuid.UUID) -> bool:
        self.cancelled.append(investigation_id)
        return True


def token(settings, aid, ph, now=None) -> str:  # type: ignore[no-untyped-def]
    return issue_token(
        settings.action_signing_key.get_secret_value(),
        action_id=aid,
        params_hash=ph,
        approved_by="tester",
        ttl_seconds=60,
        now=now,
    )


async def facts(sf, aid) -> tuple[str, int, str]:  # type: ignore[no-untyped-def]
    async with sf() as s:
        act = await s.get(OpsActionRequest, aid)
        assert act is not None
        inv = await s.get(OpsInvestigation, act.investigation_id)
        n = (
            await s.execute(
                select(func.count()).select_from(SimActionExecution).where(SimActionExecution.action_id == aid)
            )
        ).scalar_one()
    assert inv is not None
    return act.status, n, inv.status


async def investigation_of(sf, aid) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with sf() as s:
        act = await s.get(OpsActionRequest, aid)
        assert act is not None
        return act.investigation_id


async def test_cancel_before_claim_revokes_approval_and_execution_is_refused(
    settings, session_factory, embedder
) -> None:  # type: ignore[no-untyped-def]
    aid, ph, _ = await make_action(session_factory, status="approved")
    runner = Runner()
    svc = InvestigationService(session_factory, runner, None, "m")  # type: ignore[arg-type]
    await svc.cancel(await investigation_of(session_factory, aid), actor="sre")
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        res = await c.call_tool(
            "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
        )
    assert res.is_error and "'cancelled'" in res.content[0].text
    assert await facts(session_factory, aid) == ("cancelled", 0, "cancelled")
    assert runner.cancelled  # the task is stopped only after the decisions were revoked


async def test_cancel_after_claim_is_refused_and_the_effect_completes(  # type: ignore[no-untyped-def]
    settings, session_factory, embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid, ph, _ = await make_action(session_factory, status="approved")
    b = backend(settings, session_factory, embedder)
    entered, release = asyncio.Event(), asyncio.Event()
    real = b.store.execute_action

    async def slow(*a: Any, **k: Any) -> Any:
        entered.set()
        await release.wait()
        return await real(*a, **k)

    monkeypatch.setattr(b.store, "execute_action", slow)
    svc = InvestigationService(session_factory, Runner(), None, "m")  # type: ignore[arg-type]
    async with Client(build_action_server(b)) as c:
        call = asyncio.create_task(
            c.call_tool("execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)})
        )
        await asyncio.wait_for(entered.wait(), 10)  # claimed, effect in progress
        with pytest.raises(ConflictError, match="past the execution claim"):
            await svc.cancel(await investigation_of(session_factory, aid), actor="sre")
        release.set()
        res = await call
    assert not res.is_error and res.structured_content["status"] == "succeeded"
    assert await facts(session_factory, aid) == ("executing", 1, "awaiting_approval")  # runner records the result


async def test_concurrent_cancel_and_execute_never_both_win(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    b = backend(settings, session_factory, embedder)
    outcomes: set[str] = set()
    async with Client(build_action_server(b)) as c:
        # Two-sided sweep: negative offsets delay the execute (cancel first), positive ones delay the cancel.
        # The extremes force each order; the offsets near zero explore genuine interleavings.
        for offset in (-0.3, -0.05, -0.01, -0.002, 0, 0, 0.002, 0.01, 0.05, 0.3):
            aid, ph, _ = await make_action(session_factory, status="approved")
            svc = InvestigationService(session_factory, Runner(), None, "m")  # type: ignore[arg-type]
            inv = await investigation_of(session_factory, aid)

            async def delayed_cancel(inv: uuid.UUID = inv, svc: InvestigationService = svc, d: float = offset) -> Any:
                await asyncio.sleep(max(d, 0))
                return await svc.cancel(inv, actor="sre")

            async def delayed_execute(aid: uuid.UUID = aid, ph: str = ph, d: float = offset) -> Any:
                await asyncio.sleep(max(-d, 0))
                return await c.call_tool(
                    "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
                )

            cancel, execute = await asyncio.gather(
                delayed_cancel(),
                delayed_execute(),
                return_exceptions=True,
            )
            status, executed, inv_status = await facts(session_factory, aid)
            if isinstance(cancel, ConflictError):  # claim won
                assert not execute.is_error and executed == 1 and status == "executing"
                assert inv_status == "awaiting_approval"
                outcomes.add("claim_won")
            else:  # cancel won
                assert not isinstance(cancel, BaseException), cancel
                assert execute.is_error and executed == 0 and status == "cancelled" and inv_status == "cancelled"
                outcomes.add("cancel_won")
    assert outcomes == {"claim_won", "cancel_won"}, outcomes  # both orders exercised, invariant held in each


async def test_crash_between_claim_and_effect_is_retryable_and_not_cancellable(  # type: ignore[no-untyped-def]
    settings, session_factory, embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid, ph, _ = await make_action(session_factory, status="approved")
    b = backend(settings, session_factory, embedder)
    real = b.store.execute_action
    crashed = False

    async def crash_once(*a: Any, **k: Any) -> Any:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated crash after claim")
        return await real(*a, **k)

    monkeypatch.setattr(b.store, "execute_action", crash_once)
    svc = InvestigationService(session_factory, Runner(), None, "m")  # type: ignore[arg-type]
    args = {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
    async with Client(build_action_server(b)) as c:
        first = await c.call_tool("execute_remediation", args)
        assert first.is_error
        assert await facts(session_factory, aid) == ("executing", 0, "awaiting_approval")
        with pytest.raises(ConflictError):
            await svc.cancel(await investigation_of(session_factory, aid), actor="sre")
        retry = await c.call_tool("execute_remediation", args)  # recovery re-enters the claim
        again = await c.call_tool("execute_remediation", args)
    assert not retry.is_error and retry.structured_content["replayed"] is False
    assert again.structured_content["replayed"] is True
    assert (await facts(session_factory, aid))[1] == 1


async def test_expired_token_after_execution_replays_but_never_executes_anew(
    settings, session_factory, embedder
) -> None:  # type: ignore[no-untyped-def]
    aid, ph, _ = await make_action(session_factory, status="approved")
    fresh, (other, other_ph, _) = token(settings, aid, ph), await make_action(session_factory, status="approved")
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        assert not (await c.call_tool("execute_remediation", {"action_id": str(aid), "approval_token": fresh})).is_error
        replay = await c.call_tool(
            "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph, now=0)}
        )
        refused = await c.call_tool(
            "execute_remediation", {"action_id": str(other), "approval_token": token(settings, other, other_ph, now=0)}
        )
    assert not replay.is_error and replay.structured_content["replayed"] is True
    assert refused.is_error and "expired" in refused.content[0].text
    assert await facts(session_factory, other) == ("approved", 0, "awaiting_approval")  # not even claimed


async def test_cancel_after_completion_is_refused(session_factory) -> None:  # type: ignore[no-untyped-def]
    aid, _, _ = await make_action(session_factory, status="succeeded")
    inv = await investigation_of(session_factory, aid)
    async with session_factory() as s, s.begin():
        row = await s.get(OpsInvestigation, inv)
        assert row is not None
        row.status = "completed"
    with pytest.raises(ConflictError, match="already completed"):
        await InvestigationService(session_factory, Runner(), None, "m").cancel(inv, actor="sre")  # type: ignore[arg-type]


async def test_decision_accepted_before_cancel_is_never_delivered(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    """Approve (command enqueued, not yet delivered) -> cancel -> delivery must not resume the workflow."""
    aid, ph, _ = await make_action(session_factory, status="approved")
    inv = await investigation_of(session_factory, aid)
    async with session_factory() as s, s.begin():
        await enqueue_decision(
            s,
            investigation_id=inv,
            action_id=aid,
            payload={"decision": "approve", "params_hash": ph, "action_id": str(aid)},
        )
    await InvestigationService(session_factory, Runner(), None, "m").cancel(inv, actor="sre")  # type: ignore[arg-type]
    graph = StubGraph(waiting_on=str(aid))  # the checkpoint is still paused on the action
    runner = InvestigationRunner(session_factory, graph, 1)
    assert await CommandDispatcher(session_factory, runner, graph, settings).deliver_for_action(aid) == (
        "investigation_terminal"
    )
    assert graph.runs == 0 and not runner.is_active(inv)
    async with session_factory() as s:
        cmd = (await s.execute(select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id == aid))).scalar_one()
    assert cmd.status == "failed"
    assert await facts(session_factory, aid) == ("cancelled", 0, "cancelled")
