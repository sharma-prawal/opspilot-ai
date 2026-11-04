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
    OpsWorkflowEvent,
)
from opspilot_shared.redaction import redact


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
    await s.execute(update(OpsInvestigation).where(OpsInvestigation.id == investigation_id).values(**values))


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
