"""H3 regression: operator decisions survive crashes at every boundary; no duplicate side effects.

A "crash" raises a BaseException subclass, which bypasses ``except Exception`` handlers exactly like
process death would (no further writes). A "restart" is a new application instance on the same DB whose
start-up reconciliation must repair the state. Delivery is at-least-once; effects are exactly-once via
idempotency (asserted by counting sandbox executions per action).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from opspilot_api.main import create_app
from opspilot_shared.db.models import OpsWorkflowCommand, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration


class SimulatedCrash(BaseException):
    pass


@asynccontextmanager
async def crashes() -> AsyncIterator[None]:
    """Expect a SimulatedCrash, possibly wrapped in exception groups by Starlette's middleware."""

    def contains(exc: BaseException) -> bool:
        if isinstance(exc, SimulatedCrash):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return any(contains(e) for e in exc.exceptions)
        return exc.__cause__ is not None and contains(exc.__cause__)

    try:
        yield
    except BaseException as exc:
        if not contains(exc):
            raise
    else:
        raise AssertionError("expected a simulated crash")


@asynccontextmanager
async def stack(settings, session_factory, embedder) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:  # type: ignore[no-untyped-def]
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
            yield c, app.state.runtime
    finally:
        stop.set()
        await task


@pytest.fixture
def fast(settings):  # type: ignore[no-untyped-def]
    return settings.model_copy(update={"command_lease_seconds": 0.3})


def auth(settings) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"}


async def poll(c: httpx.AsyncClient, inv: str, until: set[str], timeout: float = 60) -> dict[str, Any]:
    for _ in range(int(timeout / 0.2)):
        b = (await c.get(f"/api/v1/investigations/{inv}")).json()
        if b["status"] in until and not b["executing_in_process"]:
            return b  # type: ignore[no-any-return]
        await asyncio.sleep(0.2)
    raise AssertionError(f"timeout waiting for {until}; last={b['status']}")


async def paused(c: httpx.AsyncClient, settings) -> tuple[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    inc = (await c.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"}, headers=auth(settings))).json()
    inv = (await c.post(f"/api/v1/incidents/{inc['id']}/investigations", headers=auth(settings))).json()[
        "investigation_id"
    ]
    await poll(c, inv, {"awaiting_approval"})
    [action] = (await c.get(f"/api/v1/investigations/{inv}/actions")).json()
    return inv, action


def decision(action: dict[str, Any]) -> dict[str, str]:
    return {"decision": "approve", "params_hash": action["params_hash"], "decided_by": "sre"}


async def executions(sf, action_id: str) -> int:  # type: ignore[no-untyped-def]
    async with sf() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(SimActionExecution)
                    .where(SimActionExecution.action_id == uuid.UUID(action_id))
                )
            ).scalar_one()
        )


async def command(sf, action_id: str) -> OpsWorkflowCommand | None:  # type: ignore[no-untyped-def]
    async with sf() as s:
        return (
            await s.execute(select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id == uuid.UUID(action_id)))
        ).scalar_one_or_none()


async def test_crash_before_decision_commit_leaves_decision_retryable(
    fast, session_factory, embedder, ingested, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import opspilot_api.services.approvals as approvals

    async with stack(fast, session_factory, embedder) as (c, _):
        inv, action = await paused(c, fast)
        real = approvals.enqueue_decision

        async def crash(*_a: Any, **_k: Any) -> None:
            raise SimulatedCrash

        monkeypatch.setattr(approvals, "enqueue_decision", crash)
        async with crashes():
            await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        monkeypatch.setattr(approvals, "enqueue_decision", real)
        # Atomicity: the decision rolled back together with its delivery intent.
        assert (await c.get(f"/api/v1/approvals/{action['id']}")).json()["status"] == "pending"
        assert await command(session_factory, action["id"]) is None
        r = await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert r.status_code == 200
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
    assert await executions(session_factory, action["id"]) == 1


async def test_crash_after_commit_before_submission_is_redelivered_on_restart(
    fast, session_factory, embedder, ingested, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)

        async def crash(*_a: Any, **_k: Any) -> str:
            raise SimulatedCrash

        monkeypatch.setattr(rt.dispatcher, "deliver_for_action", crash)
        async with crashes():
            await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert (await c.get(f"/api/v1/approvals/{action['id']}")).json()["status"] == "approved"
        cmd = await command(session_factory, action["id"])
        assert cmd is not None and cmd.status == "pending" and "approval_token" not in cmd.payload
    async with stack(fast, session_factory, embedder) as (c, _):  # restart: reconciliation delivers
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
    assert (await command(session_factory, action["id"])).status == "delivered"  # type: ignore[union-attr]
    assert await executions(session_factory, action["id"]) == 1


async def test_crash_during_submission_recovers_after_lease(
    fast, session_factory, embedder, ingested, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)

        def crash(*_a: Any, **_k: Any) -> None:
            raise SimulatedCrash

        monkeypatch.setattr(rt.runner, "submit", crash)
        async with crashes():
            await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert (await command(session_factory, action["id"])).status == "delivering"  # type: ignore[union-attr]
    await asyncio.sleep(0.5)  # let the claim's lease expire
    async with stack(fast, session_factory, embedder) as (c, _):
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
    assert await executions(session_factory, action["id"]) == 1


async def test_crash_after_graph_completion_before_final_persistence(
    fast, session_factory, embedder, ingested, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from opspilot_api.services.investigations import InvestigationRunner

    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)
        real = InvestigationRunner._finish_segment

        async def crash(self: Any, *a: Any, **k: Any) -> None:
            raise SimulatedCrash

        monkeypatch.setattr(InvestigationRunner, "_finish_segment", crash)
        r = await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert r.status_code == 200
        for _ in range(100):  # the graph runs to the end, then "dies" before persisting the final state
            if not rt.runner.is_active(uuid.UUID(inv)):
                break
            await asyncio.sleep(0.1)
        body = (await c.get(f"/api/v1/investigations/{inv}")).json()
        assert body["status"] == "running"  # final application persistence was lost
        monkeypatch.setattr(InvestigationRunner, "_finish_segment", real)
    await asyncio.sleep(0.5)
    async with stack(fast, session_factory, embedder) as (c, _):
        done = await poll(c, inv, {"completed"})
        assert done["result"]["outcome"]["code"] == "mitigated"
    assert (await command(session_factory, action["id"])).status == "delivered"  # type: ignore[union-attr]
    assert await executions(session_factory, action["id"]) == 1


async def test_crash_during_reconciliation_is_retried(fast, session_factory, embedder, ingested, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opspilot_api.services.investigations import InvestigationRunner

    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)
        real_finish = InvestigationRunner._finish_segment

        async def crash(self: Any, *a: Any, **k: Any) -> None:
            raise SimulatedCrash

        monkeypatch.setattr(InvestigationRunner, "_finish_segment", crash)
        await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        for _ in range(100):
            if not rt.runner.is_active(uuid.UUID(inv)):
                break
            await asyncio.sleep(0.1)
    # Restart #1: reconciliation itself fails part-way (finalize raises an ordinary error).
    calls = {"n": 0}

    async def flaky_finalize(self: Any, investigation_id: uuid.UUID) -> None:
        calls["n"] += 1
        raise RuntimeError("database blip during reconciliation")

    monkeypatch.setattr(InvestigationRunner, "_finish_segment", real_finish)
    monkeypatch.setattr(InvestigationRunner, "finalize", flaky_finalize)
    async with stack(fast, session_factory, embedder) as (c, rt):
        assert calls["n"] >= 1
        assert (await c.get(f"/api/v1/investigations/{inv}")).json()["status"] == "running"
        monkeypatch.undo()
        await asyncio.sleep(0.5)
        counts = await rt.investigations.reconcile()  # restart #2 equivalent: retry is idempotent
        assert counts.get("finalized") == 1
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
        assert (await rt.investigations.reconcile()).get("finalized") is None  # nothing left to repair
    assert await executions(session_factory, action["id"]) == 1


async def test_duplicate_and_concurrent_delivery_has_single_effect(
    fast, session_factory, embedder, ingested, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)
        real = rt.dispatcher.deliver_for_action

        async def deferred(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("delivery deferred")  # ordinary failure: decision stays durable, request succeeds

        monkeypatch.setattr(rt.dispatcher, "deliver_for_action", deferred)
        r = await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert r.status_code == 200 and r.json()["status"] == "approved"
        monkeypatch.setattr(rt.dispatcher, "deliver_for_action", real)
        cid = (await command(session_factory, action["id"])).id  # type: ignore[union-attr]
        results = await asyncio.gather(
            rt.dispatcher.deliver(cid), rt.dispatcher.deliver(cid), rt.dispatcher.dispatch_due(), return_exceptions=True
        )
        submitted = sum(1 for x in results if x == "submitted") + sum(
            x.get("submitted", 0) for x in results if isinstance(x, dict)
        )
        assert submitted == 1, results
        resume = await c.post(f"/api/v1/investigations/{inv}/resume", headers=auth(fast))
        assert resume.status_code in (202, 409)  # never a second effect
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
        await rt.dispatcher.dispatch_due()  # re-dispatch after completion: nothing to do
    assert await executions(session_factory, action["id"]) == 1


async def test_resume_redelivers_a_stranded_decision(fast, session_factory, embedder, ingested, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The audit's reproduction path: decision accepted, delivery lost, operator presses resume."""
    async with stack(fast, session_factory, embedder) as (c, rt):
        inv, action = await paused(c, fast)
        real = rt.dispatcher.deliver_for_action

        async def deferred(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("delivery deferred")

        monkeypatch.setattr(rt.dispatcher, "deliver_for_action", deferred)
        await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        monkeypatch.setattr(rt.dispatcher, "deliver_for_action", real)
        retry = await c.post(f"/api/v1/approvals/{action['id']}/decision", json=decision(action), headers=auth(fast))
        assert retry.status_code == 409  # the decision is already recorded; it is not re-decided
        r = await c.post(f"/api/v1/investigations/{inv}/resume", headers=auth(fast))
        assert r.status_code == 202
        assert (await poll(c, inv, {"completed"}))["result"]["outcome"]["code"] == "mitigated"
    assert await executions(session_factory, action["id"]) == 1
