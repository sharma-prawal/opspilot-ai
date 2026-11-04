"""Shared builders for integration tests (real DB, real MCP protocol, deterministic models)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_mcp.backend import OpsBackend
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.config import Settings
from opspilot_shared.db.models import OpsActionRequest, OpsIncident, OpsInvestigation
from opspilot_shared.domain.common import utcnow
from opspilot_simulator.store import SimulatorStore


def backend(settings: Settings, sf: async_sessionmaker[AsyncSession], embedder: Any) -> OpsBackend:
    return OpsBackend(
        settings=settings,
        engine=None,
        session_factory=sf,
        store=SimulatorStore(sf),  # type: ignore[arg-type]
        retriever=HybridRetriever(sf, embedder, settings),
    )


async def make_incident(sf: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    """Fresh INC-001 environment + incident row. Returns (incident_id, environment_id)."""
    store = SimulatorStore(sf)
    env_id, data = await store.create_environment("INC-001")
    inc_id = uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(
            OpsIncident(
                id=inc_id,
                reference=f"T-{inc_id.hex[:12]}",
                title=data.alert.title,
                description=data.alert.description,
                severity=data.alert.severity,
                status="open",
                service=data.alert.service,
                environment_id=env_id,
                detected_at=data.alert.detected_at,
            )
        )
    return inc_id, env_id


async def make_action(
    sf: async_sessionmaker[AsyncSession],
    *,
    status: str,
    action_type: str = "rollback_deployment",
    parameters: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, str, uuid.UUID]:
    from opspilot_shared.approvals import action_params_hash

    inc_id, env_id = await make_incident(sf)
    params = parameters or {"service": "ledger-service", "deployment_id": "dep-ls-0042"}
    ph = action_params_hash(action_type, params)
    inv_id, act_id = uuid.uuid4(), uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(OpsInvestigation(id=inv_id, incident_id=inc_id, status="awaiting_approval", model="t"))
        await s.flush()
        s.add(
            OpsActionRequest(
                id=act_id,
                investigation_id=inv_id,
                incident_id=inc_id,
                environment_id=env_id,
                action_type=action_type,
                parameters=params,
                params_hash=ph,
                rationale="r",
                risk="medium",
                status=status,
                decided_at=utcnow(),
            )
        )
    return act_id, ph, env_id


def inprocess_gateways(settings: Settings, sf: async_sessionmaker[AsyncSession], embedder: Any):  # type: ignore[no-untyped-def]
    """Gateway factory speaking real MCP to in-process servers (deterministic embedder)."""
    from contextlib import asynccontextmanager

    from mcp import Client

    from opspilot_mcp.action_server import ACTION_TOOLS, build_action_server
    from opspilot_mcp.gateway import McpToolGateway
    from opspilot_mcp.read_server import READ_TOOLS, build_read_server

    b = backend(settings, sf, embedder)

    @asynccontextmanager
    async def factory(profile: str):  # type: ignore[no-untyped-def]
        server = build_read_server(b) if profile == "read" else build_action_server(b)
        async with Client(server) as client:
            yield McpToolGateway(
                client,
                server_name=f"opspilot-ops-{profile}",
                tools=READ_TOOLS if profile == "read" else ACTION_TOOLS,
                timeout_seconds=10,
            )

    return factory
