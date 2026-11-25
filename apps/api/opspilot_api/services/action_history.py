"""Read persisted authorization without inferring it from mutable execution status."""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api.schemas import ActionOut, AuthorizationOut
from opspilot_shared.db.models import OpsActionRequest, OpsWorkflowCommand


def authorization_for(row: OpsActionRequest, command: OpsWorkflowCommand | None) -> AuthorizationOut | None:
    if command is None or command.kind != "approval_decision":
        return None
    payload = command.payload
    if (
        not isinstance(payload, dict)
        or command.action_id != row.id
        or command.investigation_id != row.investigation_id
        or payload.get("action_id") != str(row.id)
        or payload.get("params_hash") != row.params_hash
        or not isinstance(payload.get("decided_at"), str)
        or not isinstance(payload.get("decided_by"), str)
        or not payload["decided_by"].strip()
    ):
        return None
    try:
        datetime.fromisoformat(payload["decided_at"])
        return AuthorizationOut.model_validate(
            {key: payload.get(key) for key in ("decision", "decided_by", "decided_at")}
        )
    except (ValidationError, ValueError):
        return None


async def action_outputs(sf: async_sessionmaker[AsyncSession], rows: list[OpsActionRequest]) -> list[ActionOut]:
    if not rows:
        return []
    async with sf() as session:
        commands = {
            c.action_id: c
            for c in (
                await session.execute(
                    select(OpsWorkflowCommand).where(OpsWorkflowCommand.action_id.in_([r.id for r in rows]))
                )
            ).scalars()
        }
    outputs = []
    for row in rows:
        history = authorization_for(row, commands.get(row.id))
        outputs.append(
            ActionOut.model_validate(row).model_copy(update={"authorization": history, "decision_history": history})
        )
    return outputs
