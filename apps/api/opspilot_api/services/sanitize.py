"""Find and (optionally) redact credentials already stored in JSON columns (audit finding E).

Safe by construction:
- dry-run by default: only counts are reported, never values;
- ``apply`` rewrites only the sensitive *values* inside affected JSON documents (the central redaction
  policy), in one transaction; no row is deleted and no other field changes;
- LangGraph checkpoint history is counted but never modified: rewriting serialized checkpoints could corrupt
  resumable workflows. Those entries hold short-lived, action-bound approval tokens.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import LargeBinary, String, cast, column, func, literal, or_, select, text
from sqlalchemy import table as sa_table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from opspilot_shared.db.models import (
    OpsActionRequest,
    OpsAuditLog,
    OpsEvidence,
    OpsInvestigation,
    OpsToolInvocation,
    OpsWorkflowCommand,
    OpsWorkflowEvent,
    SimActionExecution,
)
from opspilot_shared.redaction import SENSITIVE_KEY_PARTS, contains_secret, redact

JSON_COLUMNS: list[InstrumentedAttribute[Any]] = [
    OpsToolInvocation.arguments,
    OpsWorkflowEvent.payload,
    OpsInvestigation.result,
    OpsEvidence.data,
    OpsEvidence.citation,
    OpsActionRequest.parameters,
    OpsActionRequest.execution_result,
    OpsActionRequest.verification,
    OpsWorkflowCommand.payload,
    OpsAuditLog.details,
    SimActionExecution.parameters,
    SimActionExecution.details,
]
CHECKPOINT_BLOB_TABLES = ("checkpoint_writes", "checkpoint_blobs")


async def sanitize_secrets(sf: async_sessionmaker[AsyncSession], *, apply: bool = False) -> dict[str, Any]:
    found: dict[str, int] = {}
    async with sf() as s:
        for col in JSON_COLUMNS:
            model = col.class_
            label = f"{model.__table__.schema}.{model.__tablename__}.{col.key}"  # type: ignore[attr-defined]
            # Cheap prefilter in SQL, exact check with the shared policy in Python.
            maybe = or_(*[cast(col, String).ilike(f"%{part}%") for part in SENSITIVE_KEY_PARTS])
            rows = (await s.execute(select(model).where(col.is_not(None), maybe))).scalars().all()
            hits = [r for r in rows if contains_secret(getattr(r, col.key))]
            found[label] = len(hits)
            if apply:
                for r in hits:
                    setattr(r, col.key, redact(getattr(r, col.key)))
        checkpoints: dict[str, int] = {}
        for table in CHECKPOINT_BLOB_TABLES:
            schema = (
                await s.execute(
                    text("select table_schema from information_schema.tables where table_name = :t limit 1"),
                    {"t": table},
                )
            ).scalar_one_or_none()
            if schema is None:
                continue
            blobs = sa_table(table, column("blob", LargeBinary), schema=schema)
            needle = literal(b"%approval_token%", LargeBinary)
            checkpoints[f"{schema}.{table}"] = (
                await s.execute(select(func.count()).select_from(blobs).where(blobs.c.blob.op("LIKE")(needle)))
            ).scalar_one()
        if apply:
            await s.commit()
        else:
            await s.rollback()
    return {
        "mode": "apply" if apply else "dry-run",
        "json_rows_with_secrets": found,
        "total": sum(found.values()),
        "redacted": sum(found.values()) if apply else 0,
        "checkpoint_entries_mentioning_approval_token": checkpoints,
        "checkpoint_note": "checkpoint history is not rewritten; entries hold short-lived, action-bound tokens",
    }
