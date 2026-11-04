"""Incident application service."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_shared.db.models import OpsIncident, SimEnvironment
from opspilot_shared.domain.common import Severity, utcnow
from opspilot_shared.domain.incidents import Incident, IncidentStatus
from opspilot_shared.errors import NotFoundError
from opspilot_simulator.scenarios import SCENARIOS
from opspilot_simulator.store import SimulatorStore


def to_contract(row: OpsIncident) -> Incident:
    return Incident(
        id=row.id,
        reference=row.reference,
        title=row.title,
        description=row.description,
        severity=Severity(row.severity),
        status=IncidentStatus(row.status),
        service=row.service,
        environment_id=row.environment_id,
        detected_at=row.detected_at,
        created_at=row.created_at,
    )


class IncidentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._sim = SimulatorStore(session_factory)

    @staticmethod
    def scenarios() -> list[dict[str, str]]:
        return [{"key": s.key, "title": s.title} for s in SCENARIOS.values()]

    async def simulate(self, scenario_key: str) -> Incident:
        env_id, data = await self._sim.create_environment(scenario_key)
        async with self._sf() as s, s.begin():
            row = OpsIncident(
                id=uuid.uuid4(),
                reference=await repo.next_incident_reference(s, utcnow()),
                title=data.alert.title,
                description=data.alert.description,
                severity=data.alert.severity,
                status=IncidentStatus.OPEN.value,
                service=data.alert.service,
                environment_id=env_id,
                detected_at=data.alert.detected_at,
            )
            s.add(row)
            await repo.audit(
                s,
                actor="system",
                action="incident.simulated",
                entity_type="incident",
                entity_id=str(row.id),
                details={"scenario": scenario_key, "environment_id": str(env_id)},
            )
            await s.flush()
            await s.refresh(row)
        return to_contract(row)

    async def list(self, *, status: IncidentStatus | None = None, limit: int = 50) -> list[Incident]:
        stmt = select(OpsIncident).order_by(OpsIncident.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(OpsIncident.status == status.value)
        async with self._sf() as s:
            return [to_contract(r) for r in (await s.execute(stmt)).scalars()]

    async def get(self, incident_id: uuid.UUID) -> Incident:
        async with self._sf() as s:
            row = await s.get(OpsIncident, incident_id)
        if row is None:
            raise NotFoundError(f"incident {incident_id} not found")
        return to_contract(row)

    async def open_for_scenario(self, scenario_key: str) -> Incident | None:
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(OpsIncident)
                    .join(SimEnvironment, SimEnvironment.id == OpsIncident.environment_id)
                    .where(SimEnvironment.scenario_key == scenario_key, OpsIncident.status == IncidentStatus.OPEN.value)
                    .limit(1)
                )
            ).scalar_one_or_none()
        return to_contract(row) if row else None


async def simulate_incident_cli(infra: Any, scenario: str, *, if_none: bool) -> None:
    svc = IncidentService(infra.session_factory)
    if if_none and (existing := await svc.open_for_scenario(scenario)):
        print(json.dumps({"skipped": True, "existing": existing.reference, "id": str(existing.id)}))
        return
    inc = await svc.simulate(scenario)
    print(json.dumps({"created": inc.reference, "id": str(inc.id), "environment_id": str(inc.environment_id)}))
