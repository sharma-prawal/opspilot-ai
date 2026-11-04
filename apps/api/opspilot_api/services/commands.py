"""Durable delivery of operator decisions to interrupted workflows (audit finding H3).

Invariants
- A decision and its delivery command are committed atomically (``enqueue`` runs in the decision's
  transaction). If that transaction fails, neither exists and the decision can simply be retried.
- Delivery is at-least-once: a command stays ``pending``/``delivering`` until the workflow has demonstrably
  consumed it. Duplicate delivery is harmless because (a) a command is claimed with compare-and-set, (b) the
  graph accepts a resume only while paused on that exact action, and (c) sandbox execution is idempotent per
  action_id. Exactly-once *effects* follow from idempotency, not from exactly-once delivery.
- ``delivered`` is recorded only after the workflow segment that consumed the decision has been persisted,
  or when the checkpoint shows the decision was already consumed (crash after consumption).

State machine: pending -> delivering -> delivered | failed; a stale ``delivering`` (lease expired, no live
task) is re-claimed. The approval token is minted at delivery time and is never stored in the outbox.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from langgraph.types import Command
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_api.services.investigations import InvestigationRunner, thread_config
from opspilot_shared.approvals import issue_token
from opspilot_shared.config import Settings
from opspilot_shared.db.models import OpsInvestigation, OpsWorkflowCommand
from opspilot_shared.domain.common import utcnow
from opspilot_shared.ids import stable_uuid
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)
TERMINAL = {"completed", "failed", "cancelled"}


def command_id_for(action_id: uuid.UUID) -> uuid.UUID:
    return stable_uuid("workflow-command", action_id)


async def enqueue_decision(
    s: AsyncSession, *, investigation_id: uuid.UUID, action_id: uuid.UUID, payload: dict[str, Any]
) -> uuid.UUID:
    """Insert the delivery command inside the caller's (decision) transaction. Idempotent per action."""
    if "approval_token" in payload:
        raise ValueError("approval tokens are minted at delivery time and must not be stored in the outbox")
    cid = command_id_for(action_id)
    await s.execute(
        pg_insert(OpsWorkflowCommand)
        .values(
            id=cid,
            investigation_id=investigation_id,
            action_id=action_id,
            kind="approval_decision",
            payload=payload,
            status="pending",
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["action_id"])
    )
    return cid


class CommandDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: InvestigationRunner,
        graph: Any,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._runner = runner
        self._graph = graph
        self._s = settings

    async def _claim(self, command_id: uuid.UUID) -> OpsWorkflowCommand | None:
        stale = utcnow() - timedelta(seconds=self._s.command_lease_seconds)
        async with self._sf() as s, s.begin():
            row = (
                await s.execute(
                    update(OpsWorkflowCommand)
                    .where(
                        OpsWorkflowCommand.id == command_id,
                        or_(
                            OpsWorkflowCommand.status == "pending",
                            and_(OpsWorkflowCommand.status == "delivering", OpsWorkflowCommand.claimed_at < stale),
                        ),
                    )
                    .values(status="delivering", claimed_at=utcnow(), attempts=OpsWorkflowCommand.attempts + 1)
                    .returning(OpsWorkflowCommand)
                )
            ).scalar_one_or_none()
        return row

    async def _set(self, command_id: uuid.UUID, **values: Any) -> None:
        async with self._sf() as s, s.begin():
            await s.execute(update(OpsWorkflowCommand).where(OpsWorkflowCommand.id == command_id).values(**values))

    async def mark_delivered(self, command_id: uuid.UUID) -> None:
        async with self._sf() as s, s.begin():
            await s.execute(
                update(OpsWorkflowCommand)
                .where(OpsWorkflowCommand.id == command_id, OpsWorkflowCommand.status != "delivered")
                .values(status="delivered", delivered_at=utcnow(), last_error=None)
            )

    async def deliver(self, command_id: uuid.UUID) -> str:
        """Try to deliver one command. Returns a short outcome code (for logs/tests)."""
        cmd = await self._claim(command_id)
        if cmd is None:
            return "not_claimable"
        try:
            return await self._deliver_claimed(cmd)
        except Exception as exc:  # release the claim so a later attempt can retry
            await self._set(cmd.id, status="pending", last_error=f"{type(exc).__name__}: {exc}"[:2000])
            _log.warning("command_delivery_failed", command_id=str(cmd.id), error=str(exc))
            raise

    async def _deliver_claimed(self, cmd: OpsWorkflowCommand) -> str:
        if self._runner.is_active(cmd.investigation_id) or await self._runner.owned_elsewhere(cmd.investigation_id):
            await self._set(cmd.id, status="pending", claimed_at=None)
            return "busy"
        async with self._sf() as s:
            inv = await s.get(OpsInvestigation, cmd.investigation_id)
        snap = await self._graph.aget_state(thread_config(cmd.investigation_id))
        waiting = [i.value for t in snap.tasks for i in (t.interrupts or ())]
        if any(w.get("action", {}).get("action_id") == str(cmd.action_id) for w in waiting):
            resume = dict(cmd.payload)
            if resume.get("decision") == "approve":
                resume["approval_token"] = issue_token(
                    self._s.action_signing_key.get_secret_value(),
                    action_id=cmd.action_id,
                    params_hash=resume["params_hash"],
                    approved_by=resume.get("decided_by") or "operator",
                    ttl_seconds=self._s.approval_token_ttl_seconds,
                )
            self._runner.submit(
                cmd.investigation_id,
                Command(resume=resume),
                on_success=self.mark_delivered,
                command_id=cmd.id,
                expect_action_id=str(cmd.action_id),
            )
            _log.info("command_submitted", command_id=str(cmd.id), action_id=str(cmd.action_id))
            return "submitted"
        consumed = ((snap.values or {}).get("approval") or {}).get("action_id") == str(cmd.action_id) or any(
            x.get("action_id") == str(cmd.action_id) for x in (snap.values or {}).get("executions") or []
        )
        if consumed:  # crash after the workflow consumed the decision: record delivery, do nothing else
            await self.mark_delivered(cmd.id)
            return "already_consumed"
        if inv is None or inv.status in TERMINAL:
            await self._set(cmd.id, status="failed", last_error=f"investigation is {inv.status if inv else 'missing'}")
            return "investigation_terminal"
        await self._set(
            cmd.id, status="pending", claimed_at=None, last_error="workflow is not paused on this action yet"
        )
        return "not_waiting"

    async def deliver_for_action(self, action_id: uuid.UUID) -> str:
        return await self.deliver(command_id_for(action_id))

    async def due(self) -> list[uuid.UUID]:
        stale = utcnow() - timedelta(seconds=self._s.command_lease_seconds)
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsWorkflowCommand.id)
                        .where(
                            or_(
                                OpsWorkflowCommand.status == "pending",
                                and_(OpsWorkflowCommand.status == "delivering", OpsWorkflowCommand.claimed_at < stale),
                            )
                        )
                        .order_by(OpsWorkflowCommand.created_at)
                    )
                ).scalars()
            )

    async def dispatch_due(self) -> dict[str, int]:
        """Deliver every pending/stale command. Safe to call repeatedly and concurrently."""
        counts: dict[str, int] = {}
        for cid in await self.due():
            try:
                outcome = await self.deliver(cid)
            except Exception:
                outcome = "error"
            counts[outcome] = counts.get(outcome, 0) + 1
        if counts:
            _log.info("commands_dispatched", **counts)
        return counts

    async def pending_for(self, investigation_id: uuid.UUID) -> list[OpsWorkflowCommand]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsWorkflowCommand).where(
                            OpsWorkflowCommand.investigation_id == investigation_id,
                            OpsWorkflowCommand.status.in_(["pending", "delivering"]),
                        )
                    )
                ).scalars()
            )

    async def audit_delivery(self, s: AsyncSession, investigation_id: uuid.UUID, outcome: str) -> None:
        await repo.add_event(s, investigation_id, "command_delivery", "await_approval", {"outcome": outcome})
