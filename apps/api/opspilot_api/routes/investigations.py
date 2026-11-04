from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status

from opspilot_api.deps import Operator, Runtime
from opspilot_api.schemas import (
    ActionOut,
    CancelRequest,
    EventOut,
    EvidenceOut,
    InvestigationDetail,
    InvestigationOut,
    OperationAccepted,
    ReportOut,
    ToolCallOut,
)
from opspilot_shared.errors import NotFoundError

router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])


@router.get("/{investigation_id}")
async def get_investigation(rt: Runtime, investigation_id: uuid.UUID) -> InvestigationDetail:
    inv = await rt.investigations.get(investigation_id)
    out = InvestigationDetail.model_validate(inv)
    out.executing_in_process = rt.runner.is_active(investigation_id)
    return out


@router.get("/{investigation_id}/events")
async def events(rt: Runtime, investigation_id: uuid.UUID, after: int = 0) -> list[EventOut]:
    await rt.investigations.get(investigation_id)
    return [EventOut.model_validate(e) for e in await rt.investigations.events(investigation_id, after)]


@router.get("/{investigation_id}/tool-calls")
async def tool_calls(rt: Runtime, investigation_id: uuid.UUID) -> list[ToolCallOut]:
    await rt.investigations.get(investigation_id)
    return [ToolCallOut.model_validate(t) for t in await rt.investigations.tool_calls(investigation_id)]


@router.get("/{investigation_id}/evidence")
async def evidence(rt: Runtime, investigation_id: uuid.UUID) -> list[EvidenceOut]:
    await rt.investigations.get(investigation_id)
    return [EvidenceOut.model_validate(e) for e in await rt.investigations.evidence(investigation_id)]


@router.get("/{investigation_id}/actions")
async def actions(rt: Runtime, investigation_id: uuid.UUID) -> list[ActionOut]:
    await rt.investigations.get(investigation_id)
    return [ActionOut.model_validate(a) for a in await rt.investigations.actions(investigation_id)]


@router.get("/{investigation_id}/report")
async def report(rt: Runtime, investigation_id: uuid.UUID) -> ReportOut:
    inv = await rt.investigations.get(investigation_id)
    if not inv.report_markdown:
        raise NotFoundError("report not available yet (investigation not finished)")
    return ReportOut(investigation_id=inv.id, status=inv.status, markdown=inv.report_markdown, result=inv.result)


@router.get("/{investigation_id}/workflow")
async def workflow(rt: Runtime, investigation_id: uuid.UUID) -> dict[str, Any]:
    return await rt.investigations.workflow_state(investigation_id)


@router.post("/{investigation_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume(rt: Runtime, investigation_id: uuid.UUID) -> OperationAccepted:
    inv = await rt.investigations.resume(investigation_id)
    return OperationAccepted(investigation_id=inv.id, status="running", status_url=f"/api/v1/investigations/{inv.id}")


@router.post("/{investigation_id}/cancel", dependencies=[Operator])
async def cancel(rt: Runtime, investigation_id: uuid.UUID, body: CancelRequest | None = None) -> InvestigationOut:
    return InvestigationOut.model_validate(
        await rt.investigations.cancel(investigation_id, (body or CancelRequest()).actor)
    )
