"""Audit finding G: one active investigation per incident, enforced by PostgreSQL, and DB-backed
execution ownership across API processes (two engines stand in for two processes)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api.services.commands import CommandDispatcher, enqueue_decision
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_shared.db.models import OpsInvestigation
from opspilot_shared.db.session import create_engine, create_session_factory
from opspilot_shared.errors import ConflictError
from tests.integration.helpers import make_incident
from tests.integration.test_api import client  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration


class StubGraph:
    """Records whether a segment actually ran; never paused unless told to."""

    def __init__(self, waiting_on: str | None = None) -> None:
        self.runs = 0
        self.waiting_on = waiting_on

    async def aget_state(self, _config: Any) -> Any:
        interrupts = [SimpleNamespace(value={"action": {"action_id": self.waiting_on}})] if self.waiting_on else []
        return SimpleNamespace(tasks=[SimpleNamespace(interrupts=interrupts)], values={}, next=())

    async def astream(self, *_a: Any, **_k: Any) -> AsyncIterator[Any]:
        self.runs += 1
        await asyncio.sleep(0)
        return
        yield  # pragma: no cover


class NoopRunner:
    submitted: list[uuid.UUID]

    def __init__(self) -> None:
        self.submitted = []

    def submit(self, investigation_id: uuid.UUID, *_a: Any, **_k: Any) -> None:
        self.submitted.append(investigation_id)


@pytest.fixture
async def second_sf(migrated) -> AsyncIterator[async_sessionmaker[AsyncSession]]:  # type: ignore[no-untyped-def]
    engine = create_engine(migrated)  # an independent pool: a second "process"
    yield create_session_factory(engine)
    await engine.dispose()


async def active_count(sf: async_sessionmaker[AsyncSession], incident_id: uuid.UUID) -> int:
    async with sf() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(OpsInvestigation)
                .where(
                    OpsInvestigation.incident_id == incident_id,
                    OpsInvestigation.status.in_(["queued", "running", "awaiting_approval", "interrupted"]),
                )
            )
        ).scalar_one()


def inv_row(incident_id: uuid.UUID, status: str) -> OpsInvestigation:
    return OpsInvestigation(id=uuid.uuid4(), incident_id=incident_id, status=status, model="t")


async def test_database_rejects_a_second_active_investigation(session_factory) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    async with session_factory() as s, s.begin():
        s.add_all([inv_row(inc, "completed"), inv_row(inc, "cancelled"), inv_row(inc, "interrupted")])
    with pytest.raises(IntegrityError, match="uq_ops_investigations_one_active_per_incident"):
        async with session_factory() as s, s.begin():
            s.add(inv_row(inc, "queued"))
    assert await active_count(session_factory, inc) == 1


async def test_concurrent_starts_across_two_engines_create_exactly_one(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    for _ in range(5):  # repeat to exercise different interleavings
        inc, _ = await make_incident(session_factory)
        a = InvestigationService(session_factory, NoopRunner(), None, "m")  # type: ignore[arg-type]
        b = InvestigationService(second_sf, NoopRunner(), None, "m")  # type: ignore[arg-type]
        results = await asyncio.gather(*(svc.start(inc) for svc in (a, b, a, b)), return_exceptions=True)
        ok = [r for r in results if isinstance(r, OpsInvestigation)]
        conflicts = [r for r in results if isinstance(r, ConflictError)]
        assert len(ok) == 1 and len(conflicts) == 3, results
        assert await active_count(session_factory, inc) == 1


async def test_start_waits_for_an_uncommitted_competing_insert(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    """A writer that skips start() inserts first (uncommitted). Its FK lock on the incident row serialises
    start(), which then sees the committed row and answers 409."""
    inc, _ = await make_incident(session_factory)
    svc = InvestigationService(second_sf, NoopRunner(), None, "m")  # type: ignore[arg-type]
    async with session_factory() as rogue:
        await rogue.begin()
        rogue.add(inv_row(inc, "running"))
        await rogue.flush()  # FK check holds KEY SHARE on the incident; start()'s FOR UPDATE must wait
        task = asyncio.create_task(svc.start(inc))
        await asyncio.sleep(0.5)
        assert not task.done()
        await rogue.commit()
    with pytest.raises(ConflictError):
        await task
    assert await active_count(session_factory, inc) == 1


async def test_unique_index_violation_maps_to_conflict_when_precheck_misses(  # type: ignore[no-untyped-def]
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index, not the application check, is the invariant: with the pre-check blinded, the insert
    itself is refused and reported as 409 (not 500)."""
    from opspilot_api.services import investigations as svc_mod

    inc, _ = await make_incident(session_factory)
    async with session_factory() as s, s.begin():
        s.add(inv_row(inc, "awaiting_approval"))
    monkeypatch.setattr(svc_mod, "ACTIVE_INVESTIGATION_STATUSES", ("no-such-status",))
    runner = NoopRunner()
    with pytest.raises(ConflictError, match="already active"):
        await InvestigationService(session_factory, runner, None, "m").start(inc)  # type: ignore[arg-type]
    assert runner.submitted == [] and await active_count(session_factory, inc) == 1


async def test_api_concurrent_start_requests_one_accepted(client) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    url = f"/api/v1/incidents/{inc['id']}/investigations"
    codes = sorted(r.status_code for r in await asyncio.gather(*(client.post(url) for _ in range(6))))
    assert codes == [202, 409, 409, 409, 409, 409]


async def test_execution_lease_excludes_a_second_process(session_factory, second_sf) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    row = inv_row(inc, "interrupted")
    async with session_factory() as s, s.begin():
        s.add(row)
    a = InvestigationRunner(session_factory, StubGraph(), 1, lease_seconds=0.4, owner="proc-a")
    b_graph = StubGraph()
    b = InvestigationRunner(second_sf, b_graph, 1, lease_seconds=0.4, owner="proc-b")

    assert await a.claim(row.id)
    assert not await b.claim(row.id) and await b.owned_elsewhere(row.id)
    await b.run(row.id, None)  # owned elsewhere: the segment must not run
    assert b_graph.runs == 0
    await b.release(row.id)  # releasing someone else's lease is a no-op
    assert await b.owned_elsewhere(row.id)

    await asyncio.sleep(0.5)  # proc-a "died": its lease expires
    assert not await b.owned_elsewhere(row.id)
    await b.run(row.id, None)
    assert b_graph.runs == 1
    async with session_factory() as s:
        after = await s.get(OpsInvestigation, row.id)
        assert after is not None and after.run_owner is None  # released after the segment


async def test_dispatcher_treats_a_foreign_live_lease_as_busy(session_factory, second_sf, settings) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    row, action_id = inv_row(inc, "awaiting_approval"), uuid.uuid4()
    async with session_factory() as s, s.begin():
        s.add(row)
        await s.flush()
        await enqueue_decision(s, investigation_id=row.id, action_id=action_id, payload={"decision": "reject"})
    a = InvestigationRunner(session_factory, StubGraph(), 1, owner="proc-a")
    assert await a.claim(row.id)
    graph = StubGraph(waiting_on=str(action_id))
    b = InvestigationRunner(second_sf, graph, 1, owner="proc-b")
    assert await CommandDispatcher(second_sf, b, graph, settings).deliver_for_action(action_id) == "busy"
    assert graph.runs == 0


async def test_resume_rechecks_the_pause_after_taking_the_lease(session_factory) -> None:  # type: ignore[no-untyped-def]
    inc, _ = await make_incident(session_factory)
    row = inv_row(inc, "awaiting_approval")
    async with session_factory() as s, s.begin():
        s.add(row)
    graph = StubGraph(waiting_on=str(uuid.uuid4()))  # paused on a *different* action
    runner = InvestigationRunner(session_factory, graph, 1, owner="proc-a")
    await runner.run(row.id, None, expect_action_id=str(uuid.uuid4()))
    assert graph.runs == 0
    async with session_factory() as s:
        after = await s.get(OpsInvestigation, row.id)
        assert after is not None and after.status == "awaiting_approval" and after.run_owner is None
