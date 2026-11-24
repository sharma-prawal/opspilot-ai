from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status

from opspilot_api.deps import Operator, Runtime
from opspilot_api.schemas import (
    ConnectedIncidentRequest,
    ConnectedPreviewRequest,
    InvestigationOut,
    OperationAccepted,
    SimulateRequest,
    UploadIncidentRequest,
    UploadPreviewRequest,
)
from opspilot_shared.domain.incidents import Incident, IncidentStatus

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("/scenarios")
async def scenarios(rt: Runtime) -> list[dict[str, str]]:
    return rt.incidents.scenarios()


@router.get("")
async def list_incidents(
    rt: Runtime, status: IncidentStatus | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[Incident]:
    return await rt.incidents.list(status=status, limit=limit)


@router.get("/search")
async def search_incidents(
    rt: Runtime,
    q: Annotated[str, Query(max_length=200)] = "",
    source: Literal["simulator", "upload", "connector"] | None = None,
    status: IncidentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> dict[str, Any]:
    return await rt.incidents.search(q=q, source=source, status=status, limit=limit, offset=offset)


@router.post("/simulate", status_code=status.HTTP_201_CREATED, dependencies=[Operator])
async def simulate(rt: Runtime, body: SimulateRequest) -> Incident:
    return await rt.incidents.simulate(body.scenario)


@router.post("/upload/preview", dependencies=[Operator])
async def upload_preview(rt: Runtime, body: UploadPreviewRequest) -> dict[str, Any]:
    """Validate and normalize uploaded files without storing anything (v0.5)."""
    return rt.uploads.preview(body)


@router.post("/upload", status_code=status.HTTP_201_CREATED, dependencies=[Operator])
async def upload_incident(rt: Runtime, body: UploadIncidentRequest) -> Incident:
    """Create an incident backed by uploaded files; investigate it like any other (read-only analysis)."""
    return await rt.uploads.create(body)


@router.post("/connected/preview", dependencies=[Operator])
async def connected_preview(rt: Runtime, body: ConnectedPreviewRequest) -> dict[str, Any]:
    """Run the selected connector templates for the window and return normalized evidence; stores nothing (v0.6)."""
    return await rt.connected.preview(body)


@router.post("/connected", status_code=status.HTTP_201_CREATED, dependencies=[Operator])
async def connected_incident(rt: Runtime, body: ConnectedIncidentRequest) -> Incident:
    """Create an incident backed by a read-only Loki/Prometheus snapshot; investigate it like an upload (v0.6)."""
    return await rt.connected.create(body)


@router.get("/{incident_id}/dataset")
async def incident_dataset(rt: Runtime, incident_id: uuid.UUID) -> dict[str, Any]:
    return await rt.uploads.dataset(incident_id)


@router.post("/{incident_id}/discard", dependencies=[Operator])
async def discard_upload(rt: Runtime, incident_id: uuid.UUID) -> dict[str, Any]:
    """Delete an uploaded or connected incident: its files or snapshot, records, investigations and checkpoints."""
    return await rt.uploads.discard(incident_id)


@router.get("/{incident_id}")
async def get_incident(rt: Runtime, incident_id: uuid.UUID) -> Incident:
    return await rt.incidents.get(incident_id)


@router.get("/{incident_id}/investigations")
async def incident_investigations(rt: Runtime, incident_id: uuid.UUID) -> list[InvestigationOut]:
    await rt.incidents.get(incident_id)
    return [InvestigationOut.model_validate(i) for i in await rt.investigations.list_for_incident(incident_id)]


@router.post("/{incident_id}/investigations", status_code=status.HTTP_202_ACCEPTED, dependencies=[Operator])
async def start_investigation(rt: Runtime, incident_id: uuid.UUID) -> OperationAccepted:
    inv = await rt.investigations.start(incident_id)
    return OperationAccepted(investigation_id=inv.id, status=inv.status, status_url=f"/api/v1/investigations/{inv.id}")
