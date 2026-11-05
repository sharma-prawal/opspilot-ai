"""Test-state isolation for the shared ``opspilot_test`` database (C0-F4).

Every application stack started by a test runs start-up reconciliation over *all* unfinished investigations in
the database. Unfinished workflows left by earlier tests (deliberate crash simulations, timeouts, failed tests,
earlier sessions) were therefore re-delivered and re-dispatched inside later tests, filling the bounded admission
queue and making results depend on test order and history.

Ownership rule: a test owns the work it creates. Before the session, unfinished work from earlier sessions is
retired; after each test, unfinished work created during that test is retired. "Retired" means moved to a
terminal state with an explicit reason -- nothing is deleted, and the guard refuses any database whose name does
not end in ``_test``. A runner task that is somehow still alive after retirement cannot write over it: the
retirement clears the execution lease, and every runner write is fenced on owning that lease.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_shared.db.models import (
    ACTIVE_INVESTIGATION_STATUSES,
    OpsActionRequest,
    OpsInvestigation,
    OpsWorkflowCommand,
)

RETIRED_CLASS = "test_isolation"


async def db_now(sf: async_sessionmaker[AsyncSession]) -> datetime:
    async with sf() as s:
        return (await s.execute(text("select now()"))).scalar_one()  # type: ignore[no-any-return]


async def retire_unfinished(
    sf: async_sessionmaker[AsyncSession],
    *,
    created_since: datetime | None,
    created_before: datetime | None,
    reason: str,
) -> dict[str, int]:
    async with sf() as s, s.begin():
        db = (await s.execute(text("select current_database()"))).scalar_one()
        assert str(db).endswith("_test"), f"refusing to retire workflows in non-test database {db!r}"
        cond: list[Any] = [OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES)]
        if created_since is not None:
            cond.append(OpsInvestigation.created_at >= created_since)
        if created_before is not None:
            cond.append(OpsInvestigation.created_at < created_before)
        ids = list((await s.execute(select(OpsInvestigation.id).where(*cond).with_for_update())).scalars())
        if not ids:
            return {}
        commands = await s.execute(
            update(OpsWorkflowCommand)
            .where(
                OpsWorkflowCommand.investigation_id.in_(ids),
                OpsWorkflowCommand.status.in_(["pending", "delivering"]),
            )
            .values(status="failed", last_error=reason)
        )
        actions = await s.execute(
            update(OpsActionRequest)
            .where(OpsActionRequest.investigation_id.in_(ids), OpsActionRequest.status.in_(["pending", "approved"]))
            .values(status="cancelled", decided_by="test-harness", decided_at=text("now()"))
        )
        await s.execute(
            update(OpsInvestigation)
            .where(OpsInvestigation.id.in_(ids))
            .values(
                status="cancelled",
                completed_at=text("now()"),
                error=reason,
                error_class=RETIRED_CLASS,
                run_owner=None,
                run_lease_until=None,
            )
        )
    return {"investigations": len(ids), "commands": commands.rowcount, "actions": actions.rowcount}  # type: ignore[attr-defined]
