from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from opspilot_api.deps import Runtime
from opspilot_api.schemas import InvestigationOut, OperationAccepted, SimulateRequest
from opspilot_shared.domain.incidents import Incident, IncidentStatus

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("/scenarios")
async def scenarios(rt: Runtime) -> list[dict[str, str]]:
    return rt.incidents.scenarios()


@router.get("")
async def list_incidents(rt: Runtime, status: IncidentStatus | None = None, limit: int = 50) -> list[Incident]:
    return await rt.incidents.list(status=status, limit=min(limit, 200))


@router.post("/simulate", status_code=status.HTTP_201_CREATED)
async def simulate(rt: Runtime, body: SimulateRequest) -> Incident:
    return await rt.incidents.simulate(body.scenario)


@router.get("/{incident_id}")
async def get_incident(rt: Runtime, incident_id: uuid.UUID) -> Incident:
    return await rt.incidents.get(incident_id)


@router.get("/{incident_id}/investigations")
async def incident_investigations(rt: Runtime, incident_id: uuid.UUID) -> list[InvestigationOut]:
    await rt.incidents.get(incident_id)
    return [InvestigationOut.model_validate(i) for i in await rt.investigations.list_for_incident(incident_id)]


@router.post("/{incident_id}/investigations", status_code=status.HTTP_202_ACCEPTED)
async def start_investigation(rt: Runtime, incident_id: uuid.UUID) -> OperationAccepted:
    inv = await rt.investigations.start(incident_id)
    return OperationAccepted(investigation_id=inv.id, status=inv.status, status_url=f"/api/v1/investigations/{inv.id}")
