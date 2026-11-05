"""C0-F2 regression: atomic investigation admission, durable dispatch and execution-lease fencing.

Real PostgreSQL (``opspilot_test``) with stub graphs: no model inference runs. A "crash" is a BaseException,
which bypasses ``except Exception`` handlers like process death; a second runner/service on its own engine
stands in for a second process.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_shared.db.models import OpsAuditLog, OpsInvestigation, OpsWorkflowEvent
from opspilot_shared.db.session import create_engine, create_session_factory
from opspilot_shared.domain.common import utcnow
from opspilot_shared.errors import CapacityError, ConflictError
from tests.integration.helpers import make_incident
from tests.integration.test_concurrency import BlockingGraph, StubGraph

pytestmark = pytest.mark.integration


class SimulatedCrash(BaseException):
    pass


@pytest.fixture
async def second_sf(migrated) -> AsyncIterator[async_sessionmaker[AsyncSession]]:  # type: ignore[no-untyped-def]
    engine = create_engine(migrated)
    yield create_session_factory(engine)
    await engine.dispose()


async def rows_for(sf: async_sessionmaker[AsyncSession], incident_id: uuid.UUID) -> list[OpsInvestigation]:
    async with sf() as s:
        return list(
            (await s.execute(select(OpsInvestigation).where(OpsInvestigation.incident_id == incident_id))).scalars()
        )


async def side_effects(sf: async_sessionmaker[AsyncSession], investigation_ids: list[uuid.UUID]) -> int:
    ids = [str(i) for i in investigation_ids]
    async with sf() as s:
        events = (
            await s.execute(
                select(func.count())
                .select_from(OpsWorkflowEvent)
                .where(OpsWorkflowEvent.investigation_id.in_(investigation_ids))
            )
        ).scalar_one()
        audits = (
            await s.execute(select(func.count()).select_from(OpsAuditLog).where(OpsAuditLog.entity_id.in_(ids)))
        ).scalar_one()
    return int(events) + int(audits)


async def drain(runner: InvestigationRunner, graph: BlockingGraph) -> None:
    graph.release.set()
    await asyncio.gather(*list(runner._tasks.values()), return_exceptions=True)


async def test_codex_f2_reproduction_rejected_start_commits_nothing(session_factory) -> None:  # type: ignore[no-untyped-def]
    """The audit's race on real PostgreSQL: capacity one, two distinct incidents, the first start's transaction
    held open (uncommitted) while the second runs. Before C0-F2 both rows were committed and one was then refused,
    leaving a queued row with a NULL lease. Now the second is refused before writing anything."""
    graph = BlockingGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    inc_a, inc_b = (await make_incident(session_factory))[0], (await make_incident(session_factory))[0]
    entered, gate = asyncio.Event(), asyncio.Event()
    real_started = svc._started

    async def held_open(s: AsyncSession, inv: OpsInvestigation) -> None:
        entered.set()
        await gate.wait()  # the first start's transaction stays open across the second start
        await real_started(s, inv)

    svc._started = held_open  # type: ignore[method-assign]
    first = asyncio.create_task(svc.start(inc_a))
    await asyncio.wait_for(entered.wait(), 10)
    with pytest.raises(CapacityError):
        await svc.start(inc_b)
    gate.set()
    accepted = await first
    try:
        assert await rows_for(session_factory, inc_b) == []  # no row, so no lease/approval/checkpoint/job either
        [row] = await rows_for(session_factory, inc_a)
        assert row.id == accepted.id and row.run_owner == runner.owner and row.run_lease_until is not None
        assert runner.pending == 1
    finally:
        await drain(runner, graph)
    assert runner.pending == 0


async def test_concurrent_distinct_starts_never_exceed_capacity(session_factory) -> None:  # type: ignore[no-untyped-def]
    for capacity in (1, 2, 3):
        graph = BlockingGraph()
        runner = InvestigationRunner(session_factory, graph, 1, max_pending=capacity)
        svc = InvestigationService(session_factory, runner, graph, "m")
        incidents = [(await make_incident(session_factory))[0] for _ in range(capacity + 3)]
        results = await asyncio.gather(*(svc.start(i) for i in incidents), return_exceptions=True)
        accepted = [r for r in results if isinstance(r, OpsInvestigation)]
        refused = [i for i, r in zip(incidents, results, strict=True) if isinstance(r, CapacityError)]
        try:
            assert len(accepted) == capacity and len(refused) == 3, results
            assert runner.pending == capacity
            for inc in refused:
                assert await rows_for(session_factory, inc) == []
            for inv in accepted:
                assert inv.run_owner == runner.owner and inv.run_lease_until is not None
        finally:
            await drain(runner, graph)


async def test_concurrent_duplicate_starts_answer_conflict_not_capacity(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Duplicate HTTP requests for one incident: one row, every other request 409 -- even at capacity one."""
    graph = BlockingGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    inc, _ = await make_incident(session_factory)
    results = await asyncio.gather(*(svc.start(inc) for _ in range(5)), return_exceptions=True)
    try:
        assert sum(isinstance(r, OpsInvestigation) for r in results) == 1
        assert sum(isinstance(r, ConflictError) for r in results) == 4, results
        assert len(await rows_for(session_factory, inc)) == 1
    finally:
        await drain(runner, graph)


async def test_failure_inside_admission_transaction_releases_the_slot(session_factory) -> None:  # type: ignore[no-untyped-def]
    graph = BlockingGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    inc, _ = await make_incident(session_factory)

    async def broken(*_a: Any) -> None:
        raise RuntimeError("audit insert failed")

    real = svc._started
    svc._started = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await svc.start(inc)
    assert await rows_for(session_factory, inc) == [] and runner.pending == 0
    svc._started = real  # type: ignore[method-assign]
    inv = await svc.start(inc)  # capacity was released
    await drain(runner, graph)
    assert (await rows_for(session_factory, inc))[0].id == inv.id


async def test_commit_failure_releases_the_slot(session_factory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.orm.session import SessionTransaction

    graph = BlockingGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    inc, _ = await make_incident(session_factory)
    real_commit = SessionTransaction.commit

    def failing_commit(self: SessionTransaction, _to_root: bool = False) -> None:
        raise ConnectionError("connection lost during COMMIT")  # the context manager then rolls back

    monkeypatch.setattr(SessionTransaction, "commit", failing_commit)
    with pytest.raises(ConnectionError):
        await svc.start(inc)
    monkeypatch.setattr(SessionTransaction, "commit", real_commit)
    assert await rows_for(session_factory, inc) == [] and runner.pending == 0
    await svc.start(inc)
    await drain(runner, graph)


async def test_dispatch_failure_leaves_a_recoverable_queued_row(session_factory) -> None:  # type: ignore[no-untyped-def]
    graph = StubGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    inc, _ = await make_incident(session_factory)
    real_submit = runner.submit

    def broken_submit(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("event loop refused the task")

    runner.submit = broken_submit  # type: ignore[method-assign]
    inv = await svc.start(inc)  # accepted: the row is durable
    runner.submit = real_submit  # type: ignore[method-assign]
    [row] = await rows_for(session_factory, inc)
    assert row.status == "queued" and row.run_owner is None and row.run_lease_until is None
    assert runner.pending == 0  # the slot was released
    counts = await svc.reconcile(expired_leases_only=True)  # the periodic sweep now finds NULL-lease rows
    assert counts.get("dispatched") == 1
    await runner.wait(inv.id)
    assert graph.runs == 1


async def test_crash_before_dispatch_is_recovered_by_another_process(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    a = InvestigationRunner(session_factory, StubGraph(), 1, lease_seconds=0.3, owner="proc-a")
    svc_a = InvestigationService(session_factory, a, None, "m")
    inc, _ = await make_incident(session_factory)

    def crash(*_a: Any, **_k: Any) -> None:
        raise SimulatedCrash

    a.submit = crash  # type: ignore[method-assign]
    with pytest.raises(SimulatedCrash):
        await svc_a.start(inc)
    [row] = await rows_for(session_factory, inc)
    assert row.status == "queued" and row.run_owner == "proc-a"  # accepted, owned, never dispatched

    b_graph = StubGraph()
    b = InvestigationRunner(second_sf, b_graph, 1, owner="proc-b")
    svc_b = InvestigationService(second_sf, b, b_graph, "m")
    assert "dispatched" not in await svc_b.reconcile()  # A's lease is still live: B must not take the row
    await asyncio.sleep(0.4)  # A's lease expires
    assert (await svc_b.reconcile(expired_leases_only=True)).get("dispatched") == 1
    await b.wait(row.id)
    assert b_graph.runs == 1
    [after] = await rows_for(session_factory, inc)
    assert after.run_owner is None  # B released its lease after the segment


async def test_dispatch_is_deferred_not_dropped_when_capacity_is_full(session_factory) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    stale = OpsInvestigation(id=uuid.uuid4(), incident_id=inc, status="queued", model="m")
    async with session_factory() as s, s.begin():
        s.add(stale)
    graph = BlockingGraph()
    runner = InvestigationRunner(session_factory, graph, 1, max_pending=1)
    svc = InvestigationService(session_factory, runner, graph, "m")
    other, _ = await make_incident(session_factory)
    await svc.start(other)  # fills capacity
    try:
        counts = await svc.reconcile(expired_leases_only=True)
        assert counts.get("deferred", 0) >= 1 and runner.pending == 1
        [row] = await rows_for(session_factory, inc)
        assert row.status == "queued"  # still accepted work, retried by the next sweep
    finally:
        await drain(runner, graph)
    graph.release = asyncio.Event()
    graph.release.set()
    counts = await svc.reconcile(expired_leases_only=True)
    assert counts.get("dispatched", 0) >= 1


class CheckpointedGraph(StubGraph):
    """A graph that had started before the crash (a checkpoint exists): it must not be re-run silently."""

    async def aget_state(self, _config: Any) -> Any:
        return SimpleNamespace(tasks=[], values={"status": "running"}, next=("telemetry",))


async def test_crash_after_dispatch_mid_run_becomes_interrupted_not_rerun(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    row = OpsInvestigation(
        id=uuid.uuid4(),
        incident_id=inc,
        status="running",
        model="m",
        run_owner="proc-dead",
        run_lease_until=utcnow() - timedelta(seconds=1),
    )
    async with session_factory() as s, s.begin():
        s.add(row)
    graph = CheckpointedGraph()
    b = InvestigationRunner(second_sf, graph, 1, owner="proc-b")
    counts = await InvestigationService(second_sf, b, graph, "m").reconcile(expired_leases_only=True)
    assert counts.get("interrupted") == 1 and graph.runs == 0
    [after] = await rows_for(session_factory, inc)
    assert after.status == "interrupted" and after.run_owner is None  # visible; operator resumes explicitly


class SteppingGraph(StubGraph):
    """Emits one update, waits, then emits another; used to observe writes around a takeover."""

    def __init__(self) -> None:
        super().__init__()
        self.first_done = asyncio.Event()
        self.proceed = asyncio.Event()
        self.cancelled = False

    async def astream(self, *_a: Any, **_k: Any) -> AsyncIterator[Any]:
        self.runs += 1
        yield "custom", {"event": "node_started", "node": "telemetry"}
        self.first_done.set()
        try:
            await self.proceed.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield "custom", {"event": "node_started", "node": "rca"}


async def take_over(sf: async_sessionmaker[AsyncSession], investigation_id: uuid.UUID, owner: str) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            update(OpsInvestigation)
            .where(OpsInvestigation.id == investigation_id)
            .values(run_owner=owner, run_lease_until=utcnow() + timedelta(seconds=60), status="running")
        )


async def test_lost_lease_stops_the_stale_owner_without_writes(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    """Owner A stalls past its lease; B takes over. A's heartbeat sees the loss and stops A's segment, and A
    records nothing (no cancelled/failed status, no further events) over B's ownership."""
    inc, _ = await make_incident(session_factory)
    row = OpsInvestigation(id=uuid.uuid4(), incident_id=inc, status="queued", model="m")
    async with session_factory() as s, s.begin():
        s.add(row)
    graph = SteppingGraph()
    a = InvestigationRunner(session_factory, graph, 1, lease_seconds=0.3, owner="proc-a")
    a.submit(row.id, None)
    await asyncio.wait_for(graph.first_done.wait(), 10)
    await take_over(second_sf, row.id, "proc-b")  # A's lease is overwritten as if it had expired and been taken
    await asyncio.wait_for(a.wait(row.id), 10)
    assert graph.cancelled and graph.runs == 1
    [after] = await rows_for(session_factory, inc)
    assert after.run_owner == "proc-b" and after.status == "running"  # untouched by A
    assert after.current_step == "telemetry"  # A's write after the takeover never happened
    async with session_factory() as s:
        kinds = list(
            (
                await s.execute(select(OpsWorkflowEvent.event_type).where(OpsWorkflowEvent.investigation_id == row.id))
            ).scalars()
        )
    assert "run_cancelled" not in kinds and "run_failed" not in kinds


async def test_stale_owner_write_is_fenced_even_before_its_heartbeat_notices(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    row = OpsInvestigation(id=uuid.uuid4(), incident_id=inc, status="queued", model="m")
    async with session_factory() as s, s.begin():
        s.add(row)
    graph = SteppingGraph()
    a = InvestigationRunner(session_factory, graph, 1, lease_seconds=600, owner="proc-a")  # heartbeat won't fire
    a.submit(row.id, None)
    await asyncio.wait_for(graph.first_done.wait(), 10)
    await take_over(second_sf, row.id, "proc-b")
    graph.proceed.set()  # A resumes and tries to persist its next update
    await asyncio.wait_for(a.wait(row.id), 10)
    [after] = await rows_for(session_factory, inc)
    assert after.run_owner == "proc-b" and after.current_step == "telemetry" and after.status == "running"
    assert await side_effects(session_factory, [row.id]) == 2  # run_started + first node_started only
