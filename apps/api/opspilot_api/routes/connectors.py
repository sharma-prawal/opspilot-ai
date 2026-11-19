"""Read-only telemetry connectors (v0.6): what is configured, connection tests and service discovery."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, ConfigDict

from opspilot_api.deps import Operator, Runtime

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


class WindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime


@router.get("")
async def list_connectors(rt: Runtime) -> dict[str, Any]:
    """Configured connectors with their endpoint, auth mode, service label, templates and limits. No secrets."""
    return rt.connected.describe()


@router.post("/{connector_id}/test", dependencies=[Operator])
async def test_connector(rt: Runtime, connector_id: str) -> dict[str, Any]:
    """One cheap read against the backend: ok, auth_error, unavailable, error or not_configured."""
    return await rt.connected.test(connector_id)


@router.post("/{connector_id}/services", dependencies=[Operator])
async def connector_services(rt: Runtime, connector_id: str, body: WindowIn) -> dict[str, Any]:
    """Values of the configured service label seen in the window (contacts the backend, so operator-only)."""
    return await rt.connected.services(connector_id, body.start, body.end)
