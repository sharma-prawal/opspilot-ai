"""Data access for the ``ops`` schema. Route handlers never touch the ORM directly."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot_shared.db.models import (
    OpsActionRequest,
    OpsAuditLog,
    OpsEvidence,
    OpsIncident,
    OpsInvestigation,
    OpsToolInvocation,
    OpsWorkflowCommand,
    OpsWorkflowEvent,
)
from opspilot_shared.domain.investigation import can_transition
from opspilot_shared.logging import get_logger
from opspilot_shared.redaction import redact

_log = get_logger(__name__)


async def next_incident_reference(s: AsyncSession, day: datetime) -> str:
    prefix = f"INC-{day:%Y%m%d}-"
    count = (
        await s.execute(select(func.count()).select_from(OpsIncident).where(OpsIncident.reference.like(prefix + "%")))
    ).scalar_one()
    return f"{prefix}{count + 1:04d}"


async def add_event(
    s: AsyncSession,
    investigation_id: uuid.UUID,
    event_type: str,
    node: str | None,
    payload: dict[str, Any] | None = None,
) -> None:
    s.add(
        OpsWorkflowEvent(
            investigation_id=investigation_id, event_type=event_type, node=node, payload=redact(payload or {})
        )
    )


async def audit(
    s: AsyncSession, *, actor: str, action: str, entity_type: str, entity_id: str, details: dict[str, Any] | None = None
) -> None:
    s.add(OpsAuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}))


async def upsert_evidence(s: AsyncSession, investigation_id: uuid.UUID, items: dict[str, dict[str, Any]]) -> None:
    if not items:
        return
    rows = [
        {
            "investigation_id": investigation_id,
            "evidence_id": eid,
            "kind": e["kind"],
            "source_tool": e["source_tool"],
            "collected_by": e["collected_by"],
            "service": e.get("service"),
            "summary": e["summary"],
            "data": e.get("data", {}),
            "citation": e.get("citation"),
            "relevance": e.get("relevance", 0.5),
            "observed_at": datetime.fromisoformat(e["observed_at"]) if e.get("observed_at") else None,
        }
        for eid, e in items.items()
    ]
    stmt = pg_insert(OpsEvidence).values(rows)
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["investigation_id", "evidence_id"],
            set_={"summary": stmt.excluded.summary, "data": stmt.excluded.data, "relevance": stmt.excluded.relevance},
        )
    )


async def insert_tool_calls(s: AsyncSession, investigation_id: uuid.UUID, calls: list[dict[str, Any]]) -> None:
    if not calls:
        return
    rows = [
        {
            "id": c["id"],
            "investigation_id": investigation_id,
            "tool": c["tool"],
            "server": c["server"],
            "agent": c["agent"],
            "arguments": redact(c["arguments"]),
            "status": c["status"],
            "latency_ms": c["latency_ms"],
            "result_summary": c.get("result_summary"),
            "error": c.get("error"),
            "started_at": datetime.fromisoformat(c["started_at"]),
        }
        for c in calls
    ]
    await s.execute(pg_insert(OpsToolInvocation).values(rows).on_conflict_do_nothing(index_elements=["id"]))


async def set_investigation(s: AsyncSession, investigation_id: uuid.UUID, **values: Any) -> None:
    """Non-status columns only; status changes go through ``transition_investigation`` (C0-G2)."""
    if "status" in values:
        raise ValueError("investigation status must change through transition_investigation")
    await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == investigation_id).values(**values))


async def transition_investigation(
    s: AsyncSession,
    investigation_id: uuid.UUID,
    target: str,
    *,
    operator: bool = False,
    reason: str = "",
    **values: Any,
) -> str | None:
    """C0-G2: the only way to change an investigation's status. Locks the row, checks the transition policy
    (``domain.investigation.can_transition``) against the *committed* status, and writes only if it is legal.
    Returns the previous status, or None when the transition was refused (nothing is written; a refusal is logged).
    Must run inside the caller's transaction so dependent writes commit or roll back with it.

    The row lock is ``FOR NO KEY UPDATE``: it serialises status writers but does not block foreign-key checks
    (``FOR KEY SHARE``) of concurrent inserts referencing the investigation (events, commands), so the lock order
    "investigation, then its actions" cannot deadlock with a decision that holds its action row."""
    current = (
        await s.execute(
            select(OpsInvestigation.status)
            .where(OpsInvestigation.id == investigation_id)
            .with_for_update(key_share=True)
        )
    ).scalar_one_or_none()
    if current is None or not can_transition(current, target, operator=operator):
        _log.warning(
            "investigation_transition_refused",
            investigation_id=str(investigation_id),
            current=current,
            target=target,
            reason=reason,
        )
        return None
    await s.execute(
        update(OpsInvestigation).where(OpsInvestigation.id == investigation_id).values(status=target, **values)
    )
    return str(current)


async def locked_status(s: AsyncSession, investigation_id: uuid.UUID) -> str | None:
    """The committed status, with the row locked for the rest of the caller's transaction."""
    return (
        await s.execute(
            select(OpsInvestigation.status)
            .where(OpsInvestigation.id == investigation_id)
            .with_for_update(key_share=True)
        )
    ).scalar_one_or_none()


async def revoke_commands(s: AsyncSession, investigation_id: uuid.UUID, *, reason: str) -> int:
    """Invalidate every undelivered decision command of an investigation (C0-G2: cancellation). A revoked command
    is never claimed or delivered again; its claim release is conditional on ``delivering`` (commands.py)."""
    res = await s.execute(
        update(OpsWorkflowCommand)
        .where(
            OpsWorkflowCommand.investigation_id == investigation_id,
            OpsWorkflowCommand.status.in_(["pending", "delivering"]),
        )
        .values(status="cancelled", last_error=reason[:2000])
        .returning(OpsWorkflowCommand.id)
    )
    return len(res.all())


async def set_incident_status(s: AsyncSession, incident_id: uuid.UUID, status: str) -> None:
    await s.execute(update(OpsIncident).where(OpsIncident.id == incident_id).values(status=status))


async def transition_action(s: AsyncSession, action_id: uuid.UUID, expected: tuple[str, ...], **values: Any) -> bool:
    """Compare-and-set status transition; returns False if the action was not in an expected state."""
    res = await s.execute(
        update(OpsActionRequest)
        .where(OpsActionRequest.id == action_id, OpsActionRequest.status.in_(expected))
        .values(**values)
        .returning(OpsActionRequest.id)
    )
    return res.scalar_one_or_none() is not None
