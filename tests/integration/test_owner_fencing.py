"""C0-H2 regression: ownership is established before work, its loss stops execution, and stale owners cannot write.

Real PostgreSQL throughout and an independent OS process for the delayed-stale-owner case. Interleavings are driven
by explicit barriers (gated gateways, gated model calls, a held transaction) rather than sleeps; the only waits are
bounded polls for an asynchronous event that the test has already caused.

Instrumentation: every stale write attempt is made through the same fenced connections the runtime uses, and the
checkpoint tables are counted per thread before and after, so an accepted stale write would be visible.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from mcp import Client
from psycopg import AsyncConnection
from sqlalchemy import update

from opspilot_api.checkpointing import checkpointer_pool, fenced_kwargs
from opspilot_api.ownership import (
    LOCK_EXECUTION_OWNER,
    LOCK_NAMESPACE,
    ExecutionOwnership,
    OwnershipError,
    RuntimeLifecycle,
    RuntimeState,
)
from opspilot_api.runtime import AppRuntime
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_mcp.action_server import build_action_server
from opspilot_shared.config import Settings
from opspilot_shared.db.models import OpsActionRequest, OpsInvestigation, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import backend, inprocess_gateways, make_action, make_incident, owner_token

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def fast(settings: Settings, **kw: float) -> Settings:
    """Fast acquisition; a *slow* watchdog unless asked, so these tests prove the database fence, not detection."""
    return settings.model_copy(
        update={"execution_owner_acquire_timeout_seconds": 5, "execution_owner_check_seconds": 60, **kw}
    )


async def lock_pid(settings: Settings) -> int:
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        rows = await (
            await c.execute(
                "SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=%s AND objid=%s AND objsubid=2 "
                "AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())",
                (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
            )
        ).fetchall()
    [(pid,)] = rows
    return int(pid)


async def terminate_lock_session(settings: Settings) -> None:
    """The owner's lock session dies (database restart, network loss, admin action); the process does not."""
    pid = await lock_pid(settings)
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        await c.execute("SELECT pg_terminate_backend(%s)", (pid,))


async def checkpoint_rows(settings: Settings, thread: str) -> int:
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        row = await (
            await c.execute(
                "SELECT (SELECT count(*) FROM langgraph.checkpoints WHERE thread_id=%s) + "
                "(SELECT count(*) FROM langgraph.checkpoint_writes WHERE thread_id=%s)",
                (thread, thread),
            )
        ).fetchone()
    assert row is not None
    return int(row[0])


async def put_checkpoint(saver: Any, thread: str) -> dict[str, Any]:
    cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    return await saver.aput(cfg, empty_checkpoint(), {"source": "test", "step": 0}, {})  # type: ignore[no-any-return]


async def until(pred: Any, seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.05)):
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


@pytest.fixture
async def free(settings: Settings) -> AsyncIterator[None]:
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        n = await (
            await c.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=%s AND objid=%s AND objsubid=2 "
                "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())",
                (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
            )
        ).fetchone()
    assert n is not None and n[0] == 0, "another runtime owns the test database"
    yield


# ----------------------------------------------------------------------------- lifecycle
def test_lifecycle_is_sticky_and_only_ready_admits() -> None:
    lc = RuntimeLifecycle()
    seen: list[str] = []
    lc.on_change(lambda st, _r: seen.append(st.value))
    with pytest.raises(OwnershipError):
        lc.require_ready()
    assert lc.transition(RuntimeState.ACQUIRING_OWNERSHIP)
    assert lc.transition(RuntimeState.OWNERSHIP_LOST, "probe failed")
    assert lc.transition(RuntimeState.READY) is False and lc.lost  # never READY after a loss
    assert lc.transition(RuntimeState.STOPPING) and lc.transition(RuntimeState.STOPPED)
    assert seen == ["acquiring_ownership", "ownership_lost", "stopping", "stopped"]
    with pytest.raises(OwnershipError, match="stopped"):
        lc.require_ready()


# ----------------------------------------------------------------------------- start-up
async def test_codex_n1_ownership_lost_during_startup_refuses_the_runtime(
    settings, session_factory, embedder, ingested, free
) -> None:  # type: ignore[no-untyped-def]
    """Independent C0-G audit N1, default CLI/evaluation path (no exit hook): the owner session dies while the
    gateways start; a replacement acquires. The first runtime must never open, so it cannot admit, run or checkpoint."""
    s = fast(settings, execution_owner_check_seconds=0.1)
    factory = inprocess_gateways(s, session_factory, embedder)
    entered, go = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def slow_gateway(profile: str) -> AsyncIterator[Any]:
        if profile == "read":
            entered.set()
            await go.wait()
        async with factory(profile) as gw:
            yield gw

    async def old() -> None:
        async with AppRuntime.open(
            s, chat=ScriptedChatModel(), embedder=embedder, gateways=slow_gateway, on_owner_lost=None
        ):
            raise AssertionError("a runtime that lost ownership during start-up must not open")  # pragma: no cover

    task = asyncio.create_task(old())
    await asyncio.wait_for(entered.wait(), 10)
    await terminate_lock_session(s)
    async with AppRuntime.open(s, chat=ScriptedChatModel(), embedder=embedder, gateways=factory) as new:
        assert new.ownership.lifecycle.ready
        go.set()
        # Refused either by the sticky loss or, if the watchdog had not fired yet, by the affirmative fence check
        # (the replacement's epoch is newer). The MCP task group may wrap the OwnershipError.
        with pytest.raises(BaseException) as refused:
            await asyncio.wait_for(task, 20)
        assert "OwnershipError" in repr(refused.value)
        # The replacement is the only executor: it runs an investigation and checkpoints it.
        inc, _ = await make_incident(session_factory)
        inv = await new.investigations.start(inc)
        await asyncio.wait_for(new.runner.wait(inv.id), 30)
        assert (await new.investigations.get(inv.id)).status == "awaiting_approval"
        assert await checkpoint_rows(s, str(inv.id)) > 0
        await new.investigations.cancel(inv.id, "test-cleanup")


async def test_owner_is_established_before_any_work_and_ready_is_last(
    settings, session_factory, embedder, ingested, free
) -> None:  # type: ignore[no-untyped-def]
    s = fast(settings)
    states: list[str] = []
    async with AppRuntime.open(
        s, chat=ScriptedChatModel(), embedder=embedder, gateways=inprocess_gateways(s, session_factory, embedder)
    ) as rt:
        lc = rt.ownership.lifecycle
        lc.on_change(lambda st, _r: states.append(st.value))
        assert lc.ready and rt.ownership.fence is not None and rt.runner.fence == rt.ownership.fence
        epoch = rt.ownership.fence[0]
    assert states == ["stopping", "stopped"] and lc.state is RuntimeState.STOPPED
    async with AppRuntime.open(  # normal shutdown and restart: a fresh, higher epoch
        s, chat=ScriptedChatModel(), embedder=embedder, gateways=inprocess_gateways(s, session_factory, embedder)
    ) as rt2:
        assert rt2.ownership.fence is not None and rt2.ownership.fence[0] == epoch + 1


# ----------------------------------------------------------------------------- reconciliation
def graph_paused_on(action: dict[str, Any], barrier: tuple[asyncio.Event, asyncio.Event] | None = None) -> Any:
    class G:
        async def aget_state(self, _cfg: Any) -> Any:
            if barrier is not None:
                barrier[0].set()
                await barrier[1].wait()
            return SimpleNamespace(
                values={"status": "awaiting_approval"},
                next=("await_approval",),
                tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={"action": action})])],
            )

        async def astream(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover - never reached
            raise AssertionError("no segment may run")
            yield

    return G()


async def abandoned_running(sf: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    aid, _, _ = await make_action(sf, status="pending")
    async with sf() as s, s.begin():
        act = await s.get(OpsActionRequest, aid)
        await s.execute(
            update(OpsInvestigation)
            .where(OpsInvestigation.id == act.investigation_id)
            .values(status="running", run_owner=None, run_lease_until=None)
        )
        action = {
            "action_id": str(aid),
            "action_type": act.action_type,
            "parameters": act.parameters,
            "params_hash": act.params_hash,
            "rationale": act.rationale,
            "risk": act.risk,
        }
    return act.investigation_id, action


async def owned_service(settings: Settings, sf: Any, graph: Any) -> tuple[ExecutionOwnership, InvestigationService]:
    own = ExecutionOwnership(fast(settings))
    await own.acquire()
    own.lifecycle.transition(RuntimeState.READY)
    runner = InvestigationRunner(
        sf, graph, 1, lifecycle=own.lifecycle, fence=own.fence, on_fence_violation=own.lose_now
    )
    return own, InvestigationService(sf, runner, graph, "test")


async def status_of(sf: Any, inv: uuid.UUID) -> str:
    async with sf() as s:
        row = await s.get(OpsInvestigation, inv)
    assert row is not None
    return row.status


async def test_loss_before_reconciliation_begins_writes_nothing(settings, session_factory, free) -> None:  # type: ignore[no-untyped-def]
    inv, action = await abandoned_running(session_factory)
    own, svc = await owned_service(settings, session_factory, graph_paused_on(action))
    try:
        await terminate_lock_session(settings)
        own.lose_now("test: watchdog detected the loss")
        assert await svc.reconcile() == {"skipped_not_owner": 1}
        assert await status_of(session_factory, inv) == "running"
    finally:
        await own.release()
        async with session_factory() as s, s.begin():
            await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == inv).values(status="cancelled"))


async def test_undetected_loss_during_reconciliation_is_refused_by_the_database(
    settings, session_factory, free
) -> None:  # type: ignore[no-untyped-def]
    """The watchdog has not noticed (60 s interval): the restoration write itself is refused by the fence, and the
    refusal moves the runtime to OWNERSHIP_LOST synchronously."""
    inv, action = await abandoned_running(session_factory)
    entered, go = asyncio.Event(), asyncio.Event()
    own, svc = await owned_service(settings, session_factory, graph_paused_on(action, (entered, go)))
    try:
        sweep = asyncio.create_task(svc.reconcile(expired_leases_only=True))
        await asyncio.wait_for(entered.wait(), 10)
        await terminate_lock_session(settings)
        assert own.lifecycle.ready  # not yet detected
        go.set()
        counts = await asyncio.wait_for(sweep, 10)
        assert counts.get("stopped_not_owner") == 1
        assert own.lifecycle.state is RuntimeState.OWNERSHIP_LOST and svc.runner.suspended
        assert await status_of(session_factory, inv) == "running"  # not restored to awaiting_approval
    finally:
        await own.release()
        async with session_factory() as s, s.begin():
            await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == inv).values(status="cancelled"))


# ----------------------------------------------------------------------------- agent execution and checkpoints
class GatedChat(ScriptedChatModel):
    def __init__(self) -> None:
        super().__init__()
        self.entered, self.go = asyncio.Event(), asyncio.Event()

    async def generate_structured(self, **kw: Any) -> Any:  # type: ignore[override]
        self.entered.set()
        await self.go.wait()
        return await super().generate_structured(**kw)


async def test_undetected_loss_during_agent_execution_writes_no_further_checkpoint(
    settings, session_factory, embedder, ingested, free
) -> None:  # type: ignore[no-untyped-def]
    s = fast(settings)
    chat = GatedChat()
    async with AppRuntime.open(
        s, chat=chat, embedder=embedder, gateways=inprocess_gateways(s, session_factory, embedder)
    ) as rt:
        inc, _ = await make_incident(session_factory)
        inv = await rt.investigations.start(inc)
        await asyncio.wait_for(chat.entered.wait(), 20)  # the graph is inside a model call
        await terminate_lock_session(s)
        await asyncio.sleep(0.3)  # let any write that passed the fence before the termination commit
        before = await checkpoint_rows(s, str(inv.id))
        assert rt.ownership.lifecycle.ready  # watchdog interval is 60 s: nothing noticed yet
        chat.go.set()
        await until(lambda: not rt.runner.is_active(inv.id), 30)  # cancelled by the synchronous suspension
        assert await checkpoint_rows(s, str(inv.id)) == before  # every later checkpoint write was refused
        assert rt.ownership.lifecycle.state is RuntimeState.OWNERSHIP_LOST and rt.runner.suspended
        assert (await rt.investigations.get(inv.id)).status == "running"  # nothing advanced it
        with pytest.raises(OwnershipError):
            rt.runner.reserve()
    async with session_factory() as db, db.begin():
        await db.execute(update(OpsInvestigation).where(OpsInvestigation.id == inv.id).values(status="cancelled"))


async def test_checkpoint_write_immediately_after_loss_is_rejected(settings, free) -> None:  # type: ignore[no-untyped-def]
    own = ExecutionOwnership(fast(settings))
    await own.acquire()
    thread = f"fence-{uuid.uuid4()}"
    try:
        async with checkpointer_pool(settings, fence=own.fence) as saver:
            cfg = await put_checkpoint(saver, thread)
            assert await checkpoint_rows(settings, thread) == 1
            await terminate_lock_session(settings)
            with pytest.raises(Exception, match="execution fence"):
                await saver.aput_writes(cfg, [("channel", 1)], "task-1")
            with pytest.raises(Exception, match="execution fence"):
                await put_checkpoint(saver, thread)
        assert await checkpoint_rows(settings, thread) == 1
    finally:
        await own.release()


async def test_unfenced_connection_cannot_write_checkpoints(settings, free) -> None:  # type: ignore[no-untyped-def]
    thread = f"fence-{uuid.uuid4()}"
    async with checkpointer_pool(settings) as saver:  # no owner at all
        with pytest.raises(Exception, match="without execution ownership"):
            await put_checkpoint(saver, thread)
    assert await checkpoint_rows(settings, thread) == 0


async def test_in_flight_write_commits_before_the_new_owner_and_later_writes_fail(settings, free) -> None:  # type: ignore[no-untyped-def]
    """The fence's FOR SHARE makes takeover wait for an in-flight fenced write: the stale write is ordered strictly
    before the new epoch, and every write after the new epoch fails. No interleaving is possible."""
    old = ExecutionOwnership(fast(settings))
    await old.acquire()
    thread = f"fence-{uuid.uuid4()}"
    new = ExecutionOwnership(fast(settings, execution_owner_acquire_timeout_seconds=20))
    async with await AsyncConnection.connect(settings.libpq_dsn(), **fenced_kwargs(old.fence)) as conn:
        await conn.set_autocommit(False)
        # In flight: this transaction's write passes the fence (FOR SHARE on the epoch row) but is not committed.
        await conn.execute(
            "INSERT INTO langgraph.checkpoint_writes "
            "(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path) "
            "VALUES (%s, '', 'c1', 't1', 0, 'ch', 'null', '\\x00'::bytea, '')",
            (thread,),
        )
        await terminate_lock_session(settings)  # the old owner's lock session dies
        acquiring = asyncio.create_task(new.acquire())
        await asyncio.sleep(0.5)
        assert not acquiring.done()  # blocked on the epoch row until the in-flight write finishes
        await conn.commit()
        await asyncio.wait_for(acquiring, 20)
        assert new.fence is not None and old.fence is not None and new.fence[0] == old.fence[0] + 1
        with pytest.raises(Exception, match="execution fence"):
            await conn.execute(
                "INSERT INTO langgraph.checkpoint_writes "
                "(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path) "
                "VALUES (%s, '', 'c1', 't2', 0, 'ch', 'null', '\\x00'::bytea, '')",
                (thread,),
            )
        await conn.rollback()
    assert await checkpoint_rows(settings, thread) == 1  # exactly the write that committed before takeover
    await new.release()
    await old.release()


# ----------------------------------------------------------------------------- remediation
async def test_stale_owner_token_cannot_start_a_remediation(settings, session_factory, embedder, free) -> None:  # type: ignore[no-untyped-def]
    aid, ph, _ = await make_action(session_factory, status="approved")
    old = ExecutionOwnership(fast(settings))
    await old.acquire()
    stale = owner_token(settings, old, aid, ph)
    await terminate_lock_session(settings)
    new = ExecutionOwnership(fast(settings))
    await new.acquire()
    try:
        async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
            refused = await c.call_tool("execute_remediation", {"action_id": str(aid), "approval_token": stale})
            assert refused.is_error and "no longer current" in refused.content[0].text
            async with session_factory() as s:
                assert (await s.get(OpsActionRequest, aid)).status == "approved"  # not even claimed
                assert await s.get(SimActionExecution, aid) is None
            ok = await c.call_tool(
                "execute_remediation", {"action_id": str(aid), "approval_token": owner_token(settings, new, aid, ph)}
            )
            assert not ok.is_error
    finally:
        await new.release()
        await old.release()


async def test_unbound_token_cannot_start_a_remediation(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    from opspilot_shared.approvals import issue_token

    aid, ph, _ = await make_action(session_factory, status="approved")
    tok = issue_token(
        settings.action_signing_key.get_secret_value(), action_id=aid, params_hash=ph, approved_by="t", ttl_seconds=60
    )
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        res = await c.call_tool("execute_remediation", {"action_id": str(aid), "approval_token": tok})
    assert res.is_error and "not bound to an execution owner" in res.content[0].text


# ----------------------------------------------------------------------------- independent OS process
STALE = textwrap.dedent(
    """
    import asyncio, sys
    from opspilot_api.checkpointing import checkpointer_pool
    from opspilot_api.ownership import ExecutionOwnership
    from opspilot_shared.config import get_settings
    from langgraph.checkpoint.base import empty_checkpoint
    async def main():
        s = get_settings().model_copy(update={"execution_owner_check_seconds": 600})
        o = ExecutionOwnership(s)
        await o.acquire()
        async with checkpointer_pool(s, fence=o.fence) as saver:
            cfg = {"configurable": {"thread_id": sys.argv[1], "checkpoint_ns": ""}}
            await saver.aput(cfg, empty_checkpoint(), {"source": "test", "step": 0}, {})
            print("held", o.fence[0], flush=True)
            await asyncio.to_thread(sys.stdin.readline)   # parent: lock session killed, new owner elected
            try:
                await saver.aput(cfg, empty_checkpoint(), {"source": "test", "step": 1}, {})
                print("ACCEPTED", flush=True)
            except Exception as exc:
                print("refused", "execution fence" in str(exc), o.lifecycle.state.value, flush=True)
    asyncio.run(main())
    """
)


async def test_delayed_operations_of_a_stale_owner_process_are_refused(settings, free) -> None:  # type: ignore[no-untyped-def]
    thread = f"fence-{uuid.uuid4()}"
    env = {**os.environ, "DB_NAME": settings.db_name, "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(  # an independent stale owner process
        [sys.executable, "-c", STALE, thread],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    new = ExecutionOwnership(fast(settings, execution_owner_acquire_timeout_seconds=20))
    try:
        assert proc.stdout is not None and proc.stdin is not None
        out, stdin = proc.stdout, proc.stdin

        def line(*prefixes: str) -> str:
            for raw in out:
                if raw.startswith(prefixes):
                    return raw.strip()
            return ""

        held = await asyncio.wait_for(asyncio.to_thread(line, "held"), 30)
        old_epoch = int(held.split()[1])
        await terminate_lock_session(settings)  # its process keeps running, its watchdog is asleep
        await new.acquire()
        assert new.fence is not None and new.fence[0] > old_epoch
        stdin.write("go\n")
        stdin.flush()
        verdict = await asyncio.wait_for(asyncio.to_thread(line, "refused", "ACCEPTED"), 30)
        assert verdict.startswith("refused True"), verdict
        assert await checkpoint_rows(settings, thread) == 1  # only the write made while it was the owner
    finally:
        proc.send_signal(signal.SIGKILL)
        await asyncio.to_thread(proc.wait, 10)
        await new.release()
