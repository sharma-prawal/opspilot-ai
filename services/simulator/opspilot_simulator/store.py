"""Persistence and query API for simulated environments (``sim`` schema).

Used by the MCP servers (read + sandbox actions) and by the API to create environments.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_shared.db.models import (
    SimActionExecution,
    SimConfigChange,
    SimDependency,
    SimDeployment,
    SimEnvironment,
    SimLog,
    SimMetric,
    SimService,
)
from opspilot_shared.domain.telemetry import (
    ConfigChange,
    DependencyGraph,
    Deployment,
    HealthStatus,
    LogEntry,
    LogLevel,
    LogSearchResult,
    MetricPoint,
    MetricSeries,
    ServiceDependency,
    ServiceHealth,
)
from opspilot_shared.errors import NotFoundError, ValidationFailure
from opspilot_simulator.scenarios import DEFAULT_SEED, get_scenario
from opspilot_simulator.scenarios.base import DeploymentRow, ScenarioData, Telemetry
from opspilot_simulator.topology import DEPENDENCIES, METRIC_UNITS, SERVICE_METRICS, SERVICES

DEFAULT_ANCHOR = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
POST_ACTION_WINDOW = timedelta(minutes=10)
MAX_WINDOW = timedelta(hours=24)
_LEVEL_ORDER = ["DEBUG", "INFO", "WARN", "ERROR"]


def _check_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValidationFailure("end must be after start")
    if end - start > MAX_WINDOW:
        raise ValidationFailure("time window may not exceed 24h")


def _dep_contract(d: SimDeployment) -> Deployment:
    return Deployment(
        id=d.id,
        service=d.service,
        kind=d.kind,
        version=d.version,  # type: ignore[arg-type]
        previous_version=d.previous_version,
        started_at=d.started_at,
        finished_at=d.finished_at,
        status=d.status,
        author=d.author,
        change_summary=d.change_summary,
        metadata=d.metadata_,
    )


class SimulatorStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ---------------------------------------------------------------- environment lifecycle
    async def create_environment(
        self, scenario_key: str, *, seed: int = DEFAULT_SEED, anchor: datetime = DEFAULT_ANCHOR
    ) -> tuple[uuid.UUID, ScenarioData]:
        scenario = get_scenario(scenario_key)
        data = scenario.generate(seed, anchor)
        env_id = uuid.uuid4()
        async with self._sf() as s, s.begin():
            s.add(
                SimEnvironment(id=env_id, scenario_key=scenario_key, seed=seed, sim_now=data.sim_now, state=data.state)
            )
            await s.flush()
            await s.execute(
                insert(SimService),
                [
                    {
                        "environment_id": env_id,
                        "name": d.name,
                        "tier": d.tier,
                        "owner": d.owner,
                        "current_version": data.service_versions.get(d.name, d.version),
                        "replicas": d.replicas,
                    }
                    for d in SERVICES
                ],
            )
            await s.execute(
                insert(SimDependency),
                [
                    {
                        "environment_id": env_id,
                        "service": d.service,
                        "depends_on": d.depends_on,
                        "kind": d.kind,
                        "critical": d.critical,
                    }
                    for d in DEPENDENCIES
                ],
            )
            await self._insert_deployments(s, env_id, data.deployments)
            await s.execute(
                insert(SimConfigChange),
                [
                    {
                        "environment_id": env_id,
                        "id": c.id,
                        "service": c.service,
                        "key": c.key,
                        "old_value": c.old_value,
                        "new_value": c.new_value,
                        "changed_at": c.changed_at,
                        "author": c.author,
                    }
                    for c in data.config_changes
                ],
            )
            await self._insert_telemetry(s, env_id, data.telemetry)
        return env_id, data

    @staticmethod
    async def _insert_deployments(s: AsyncSession, env_id: uuid.UUID, rows: list[DeploymentRow]) -> None:
        if rows:
            await s.execute(
                insert(SimDeployment),
                [
                    {
                        "environment_id": env_id,
                        "id": d.id,
                        "service": d.service,
                        "kind": d.kind,
                        "version": d.version,
                        "previous_version": d.previous_version,
                        "started_at": d.started_at,
                        "finished_at": d.finished_at,
                        "status": d.status,
                        "author": d.author,
                        "change_summary": d.change_summary,
                        "metadata_": d.metadata,
                    }
                    for d in rows
                ],
            )

    @staticmethod
    async def _insert_telemetry(s: AsyncSession, env_id: uuid.UUID, t: Telemetry) -> None:
        if t.logs:
            await s.execute(
                insert(SimLog),
                [
                    {
                        "environment_id": env_id,
                        "ts": r.ts,
                        "service": r.service,
                        "level": r.level,
                        "message": r.message,
                        "logger": r.logger,
                        "trace_id": r.trace_id,
                        "attributes": r.attributes,
                    }
                    for r in t.logs
                ],
            )
        if t.metrics:
            await s.execute(
                pg_insert(SimMetric).on_conflict_do_nothing(),
                [
                    {"environment_id": env_id, "service": r.service, "name": r.name, "ts": r.ts, "value": r.value}
                    for r in t.metrics
                ],
            )

    async def environment(self, env_id: uuid.UUID) -> SimEnvironment:
        async with self._sf() as s:
            env = await s.get(SimEnvironment, env_id)
        if env is None:
            raise NotFoundError(f"environment {env_id} not found")
        return env

    async def _services(self, env_id: uuid.UUID) -> dict[str, SimService]:
        async with self._sf() as s:
            rows = (await s.execute(select(SimService).where(SimService.environment_id == env_id))).scalars()
            return {r.name: r for r in rows}

    async def _require_service(self, env_id: uuid.UUID, service: str) -> SimService:
        services = await self._services(env_id)
        if service not in services:
            raise NotFoundError(f"unknown service {service!r}; known: {sorted(services)}")
        return services[service]

    # ---------------------------------------------------------------- read API (MCP read tools)
    async def search_logs(
        self,
        env_id: uuid.UUID,
        *,
        service: str,
        start: datetime,
        end: datetime,
        min_level: LogLevel = LogLevel.INFO,
        contains: str | None = None,
        limit: int = 100,
    ) -> LogSearchResult:
        _check_window(start, end)
        await self._require_service(env_id, service)
        levels = _LEVEL_ORDER[_LEVEL_ORDER.index(min_level.value) :]
        cond = [
            SimLog.environment_id == env_id,
            SimLog.service == service,
            SimLog.ts >= start,
            SimLog.ts < end,
            SimLog.level.in_(levels),
        ]
        if contains:
            # Substring (ILIKE) semantics: full-text parsing would treat tokens such as
            # "psycopg.errors.UndefinedColumn" as one host-like lexeme and miss "UndefinedColumn".
            for term in re.findall(r"[A-Za-z0-9_.\-]{2,}", contains)[:8]:
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                cond.append(SimLog.message.ilike(f"%{escaped}%", escape="\\"))
        async with self._sf() as s:
            total = (await s.execute(select(func.count()).select_from(SimLog).where(*cond))).scalar_one()
            rows = (await s.execute(select(SimLog).where(*cond).order_by(SimLog.ts.desc()).limit(limit))).scalars()
            entries = [
                LogEntry(
                    ts=r.ts,
                    service=r.service,
                    level=LogLevel(r.level),
                    message=r.message,
                    logger=r.logger,
                    trace_id=r.trace_id,
                    attributes=r.attributes,
                )
                for r in rows
            ]
        return LogSearchResult(entries=entries, total_matched=total, truncated=total > len(entries))

    async def query_metrics(
        self, env_id: uuid.UUID, *, service: str, metric: str, start: datetime, end: datetime
    ) -> MetricSeries:
        _check_window(start, end)
        await self._require_service(env_id, service)
        if metric not in SERVICE_METRICS.get(service, ()):
            raise ValidationFailure(
                f"metric {metric!r} not available for {service}; available: {list(SERVICE_METRICS.get(service, ()))}"
            )
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(SimMetric.ts, SimMetric.value)
                    .where(
                        SimMetric.environment_id == env_id,
                        SimMetric.service == service,
                        SimMetric.name == metric,
                        SimMetric.ts >= start,
                        SimMetric.ts < end,
                    )
                    .order_by(SimMetric.ts)
                )
            ).all()
        return MetricSeries(
            service=service,
            metric=metric,
            unit=METRIC_UNITS[metric],
            points=[MetricPoint(ts=t, value=v) for t, v in rows],
        )

    async def service_health(self, env_id: uuid.UUID, service: str) -> ServiceHealth:
        svc = await self._require_service(env_id, service)
        env = await self.environment(env_id)
        start = env.sim_now - timedelta(minutes=5)
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(SimMetric.name, SimMetric.value).where(
                        SimMetric.environment_id == env_id,
                        SimMetric.service == service,
                        SimMetric.ts >= start,
                        SimMetric.ts < env.sim_now,
                    )
                )
            ).all()
        by: dict[str, list[float]] = {}
        for name, value in rows:
            by.setdefault(name, []).append(value)
        err = fmean(by["http_5xx_ratio"]) if by.get("http_5xx_ratio") else 0.0
        p95 = fmean(by["p95_latency_ms"]) if by.get("p95_latency_ms") else 0.0
        status = HealthStatus.UNHEALTHY if err > 0.05 else HealthStatus.DEGRADED if err > 0.01 else HealthStatus.HEALTHY
        notes = [f"5xx ratio (5m avg) {err:.2%}"] + ([f"p95 latency {p95:.0f} ms"] if p95 else [])
        return ServiceHealth(
            service=service,
            status=status,
            as_of=env.sim_now,
            error_ratio=round(err, 5),
            p95_latency_ms=round(p95, 1),
            version=svc.current_version,
            notes=notes,
        )

    async def list_deployments(
        self, env_id: uuid.UUID, *, start: datetime, end: datetime, service: str | None = None
    ) -> list[Deployment]:
        _check_window(start, end)
        cond = [
            SimDeployment.environment_id == env_id,
            SimDeployment.started_at >= start,
            SimDeployment.started_at < end,
        ]
        if service:
            cond.append(SimDeployment.service == service)
        async with self._sf() as s:
            rows = (await s.execute(select(SimDeployment).where(*cond).order_by(SimDeployment.started_at))).scalars()
            return [_dep_contract(d) for d in rows]

    async def config_changes(
        self, env_id: uuid.UUID, *, start: datetime, end: datetime, service: str | None = None
    ) -> list[ConfigChange]:
        _check_window(start, end)
        cond = [
            SimConfigChange.environment_id == env_id,
            SimConfigChange.changed_at >= start,
            SimConfigChange.changed_at < end,
        ]
        if service:
            cond.append(SimConfigChange.service == service)
        async with self._sf() as s:
            rows = (
                await s.execute(select(SimConfigChange).where(*cond).order_by(SimConfigChange.changed_at))
            ).scalars()
            return [
                ConfigChange(
                    id=c.id,
                    service=c.service,
                    key=c.key,
                    old_value=c.old_value,
                    new_value=c.new_value,
                    changed_at=c.changed_at,
                    author=c.author,
                )
                for c in rows
            ]

    async def dependencies(self, env_id: uuid.UUID, service: str) -> DependencyGraph:
        await self._require_service(env_id, service)
        async with self._sf() as s:
            rows = list(
                (await s.execute(select(SimDependency).where(SimDependency.environment_id == env_id))).scalars()
            )

        def c(d: SimDependency) -> ServiceDependency:
            return ServiceDependency(service=d.service, depends_on=d.depends_on, kind=d.kind, critical=d.critical)

        return DependencyGraph(
            service=service,
            downstream=[c(d) for d in rows if d.service == service],
            upstream=[c(d) for d in rows if d.depends_on == service],
        )

    # ---------------------------------------------------------------- sandbox actions
    async def execute_action(
        self, env_id: uuid.UUID, *, action_id: uuid.UUID, action_type: str, parameters: dict[str, Any], params_hash: str
    ) -> SimActionExecution:
        """Execute a sandbox action exactly once per ``action_id`` (idempotent replay)."""
        async with self._sf() as s, s.begin():
            env = (
                await s.execute(select(SimEnvironment).where(SimEnvironment.id == env_id).with_for_update())
            ).scalar_one_or_none()
            if env is None:
                raise NotFoundError(f"environment {env_id} not found")
            prior = await s.get(SimActionExecution, action_id)
            if prior is not None:
                if prior.params_hash != params_hash:
                    raise ValidationFailure("action_id already executed with different parameters")
                return prior
            if "service" in parameters:
                svc = await s.get(SimService, (env_id, parameters["service"]))
                if svc is None:
                    raise ValidationFailure(f"unknown service {parameters['service']!r}")
            scenario = get_scenario(env.scenario_key)
            deployments = [
                DeploymentRow(
                    d.id,
                    d.service,
                    d.kind,
                    d.version,
                    d.previous_version,
                    d.started_at,
                    d.finished_at,
                    d.status,
                    d.author,
                    d.change_summary,
                    d.metadata_,
                )
                for d in (
                    await s.execute(select(SimDeployment).where(SimDeployment.environment_id == env_id))
                ).scalars()
            ]
            if action_type == "rollback_deployment":
                target = next((d for d in deployments if d.id == parameters.get("deployment_id")), None)
                if target is not None and target.service != parameters.get("service"):
                    raise ValidationFailure("deployment does not belong to the given service")
            now = env.sim_now
            effect = scenario.apply_action(action_type, parameters, state=env.state, deployments=deployments, now=now)
            state = dict(env.state)
            fault_active = bool(state.get("fault_active")) and not effect.fault_cleared
            state["fault_active"] = fault_active
            state["actions"] = [
                *state.get("actions", []),
                {
                    "action_id": str(action_id),
                    "type": action_type,
                    "succeeded": effect.succeeded,
                    "at": now.isoformat(),
                },
            ]
            if effect.succeeded:
                await self._insert_deployments(s, env_id, effect.deployments)
                for d in effect.deployments:
                    rolled = d.metadata.get("rolled_back_deployment_id")
                    if rolled:
                        await s.execute(
                            update(SimDeployment)
                            .where(SimDeployment.environment_id == env_id, SimDeployment.id == rolled)
                            .values(status="rolled_back")
                        )
                for name, version in effect.service_versions.items():
                    await s.execute(
                        update(SimService)
                        .where(SimService.environment_id == env_id, SimService.name == name)
                        .values(current_version=version)
                    )
            # Time passes in the sandbox: generate the post-action window with the resulting fault state.
            rng = random.Random(env.seed ^ action_id.int)
            post = scenario.telemetry_window(rng, now, now + POST_ACTION_WINDOW, fault_active=fault_active, state=state)
            await self._insert_telemetry(s, env_id, post)
            env.state = state
            env.sim_now = now + POST_ACTION_WINDOW
            row = SimActionExecution(
                action_id=action_id,
                environment_id=env_id,
                action_type=action_type,
                parameters=parameters,
                params_hash=params_hash,
                status="succeeded" if effect.succeeded else "failed",
                message=effect.message,
                details={
                    **effect.details,
                    "executed_at_sim": now.isoformat(),
                    "sim_now_after": env.sim_now.isoformat(),
                },
            )
            s.add(row)
        return row
