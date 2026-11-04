from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter

from opspilot_api.deps import Operator, Runtime
from opspilot_api.schemas import ActionOut, DecisionRequest

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
StatusFilter = Literal["pending", "approved", "rejected", "cancelled", "succeeded", "failed", "all"]


@router.get("")
async def list_approvals(rt: Runtime, status: StatusFilter = "pending") -> list[ActionOut]:
    return [ActionOut.model_validate(a) for a in await rt.approvals.list(None if status == "all" else status)]


@router.get("/{action_id}")
async def get_approval(rt: Runtime, action_id: uuid.UUID) -> ActionOut:
    return ActionOut.model_validate(await rt.approvals.get(action_id))


@router.post("/{action_id}/decision", dependencies=[Operator])
async def decide(rt: Runtime, action_id: uuid.UUID, body: DecisionRequest) -> ActionOut:
    row = await rt.approvals.decide(
        action_id,
        decision=body.decision,
        params_hash=body.params_hash,
        decided_by=body.decided_by,
        comment=body.comment,
    )
    return ActionOut.model_validate(row)
