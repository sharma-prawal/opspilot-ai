"""C0-F4 regression: no test inherits another test's unfinished workflows.

The independent audit saw ``test_crash_before_decision_commit_leaves_decision_retryable`` fail in a full run
(start-up reconciliation re-dispatched earlier tests' unfinished work and filled the admission queue) and pass
in isolation. These two tests hold in either order: one deliberately leaves unfinished work behind, the other
asserts that a fresh application process finds nothing to reconcile.
"""

import pytest
from sqlalchemy import func, select

from opspilot_api.services.commands import enqueue_decision
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_shared.db.models import ACTIVE_INVESTIGATION_STATUSES, OpsActionRequest, OpsInvestigation
from tests.integration.helpers import make_action
from tests.integration.test_concurrency import StubGraph

pytestmark = pytest.mark.integration


async def test_a_test_that_leaves_unfinished_work(session_factory) -> None:  # type: ignore[no-untyped-def]
    act_id, _, _ = await make_action(session_factory, status="pending")
    async with session_factory() as s, s.begin():
        action = await s.get(OpsActionRequest, act_id)
        assert action is not None
        await enqueue_decision(
            s, investigation_id=action.investigation_id, action_id=act_id, payload={"decision": "reject"}
        )
    # Deliberately not finished: awaiting_approval investigation, pending action, pending delivery command.


async def test_fresh_process_finds_no_foreign_unfinished_work(session_factory) -> None:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        active = (
            await s.execute(
                select(func.count())
                .select_from(OpsInvestigation)
                .where(OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES))
            )
        ).scalar_one()
    assert active == 0
    graph = StubGraph()
    svc = InvestigationService(session_factory, InvestigationRunner(session_factory, graph, 1), graph, "m")
    assert await svc.reconcile() == {}  # start-up reconciliation has nothing to restore
    assert graph.runs == 0
