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
    SimInspection,
    SimLog,
    SimMetric,
    SimQueueMessage,
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
from opspilot_shared.errors import NotFoundError, ToolTransientError, ValidationFailure
from opspilot_simulator.scenarios import DEFAULT_SEED, get_scenario
from opspilot_simulator.scenarios.base import DeploymentRow, ScenarioData, Telemetry
from opspilot_simulator.topology import DEPENDENCIES, METRIC_UNITS, QUEUES, SERVICE_CONFIG, SERVICES

DEFAULT_ANCHOR = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
POST_ACTION_WINDOW = timedelta(minutes=10)
MAX_WINDOW = timedelta(hours=24)
_LEVEL_ORDER = ["DEBUG", "INFO", "WARN", "ERROR"]
QUEUE_SAMPLE = 5


class BackendUnavailableError(ToolTransientError):
    """An observability backend for this environment is unavailable (simulated outage)."""

    error_class = "backend_unavailable"


def _check_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValidationFailure("end must be after start")
    if end - start > MAX_WINDOW:
        raise ValidationFailure("time window may not exceed 24h")


def _dep_contract(d: SimDeployment) -> Deployment:
    return Deployment(
        id=d.id,
        service=d.service,
        kind=d.kind,  # type: ignore[arg-type]
        version=d.version,
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
        configs = data.service_configs or {k: dict(v) for k, v in SERVICE_CONFIG.items()}
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
                        "config": configs.get(d.name, {}),
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
            if data.config_changes:
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
        if t.inspections:
            await s.execute(
                insert(SimInspection),
                [
                    {"environment_id": env_id, "kind": i.kind, "target": i.target, "ts": i.ts, "payload": i.payload}
                    for i in t.inspections
                ],
            )
        if t.queue_messages:
            await s.execute(
                insert(SimQueueMessage),
                [
                    {
                        "environment_id": env_id,
                        "queue": q.queue,
                        "message_id": q.message_id,
                        "producer_service": q.producer_service,
                        "producer_version": q.producer_version,
                        "schema_version": q.schema_version,
                        "payload": q.payload,
                        "status": q.status,
                        "attempts": q.attempts,
                        "error_code": q.error_code,
                        "last_error": q.last_error,
                        "enqueued_at": q.enqueued_at,
                        "updated_at": q.enqueued_at,
                    }
                    for q in t.queue_messages
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

    async def _tool_fault(self, env_id: uuid.UUID, key: str) -> None:
        env = await self.environment(env_id)
        message = (env.state.get("tool_faults") or {}).get(key)
        if message:
            raise BackendUnavailableError(message)

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
        await self._tool_fault(env_id, f"search_logs:{service}")
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

    async def list_metrics(self, env_id: uuid.UUID, service: str) -> list[dict[str, str]]:
        await self._require_service(env_id, service)
        async with self._sf() as s:
            names = (
                (
                    await s.execute(
                        select(SimMetric.name)
                        .distinct()
                        .where(SimMetric.environment_id == env_id, SimMetric.service == service)
                    )
                )
                .scalars()
                .all()
            )
        return [{"metric": n, "unit": METRIC_UNITS.get(n, "")} for n in sorted(names)]

    async def query_metrics(
        self, env_id: uuid.UUID, *, service: str, metric: str, start: datetime, end: datetime
    ) -> MetricSeries:
        _check_window(start, end)
        await self._require_service(env_id, service)
        available = {m["metric"] for m in await self.list_metrics(env_id, service)}
        if metric not in available:
            raise ValidationFailure(f"metric {metric!r} not available for {service}; available: {sorted(available)}")
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
            unit=METRIC_UNITS.get(metric, ""),
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
        if not by:
            return ServiceHealth(
                service=service,
                status=HealthStatus.UNKNOWN,
                as_of=env.sim_now,
                error_ratio=0.0,
                p95_latency_ms=0.0,
                version=svc.current_version,
                notes=["no recent metrics"],
            )
        err = fmean(by["http_5xx_ratio"]) if by.get("http_5xx_ratio") else 0.0
        p95 = fmean(by["p95_latency_ms"]) if by.get("p95_latency_ms") else 0.0
        status = HealthStatus.UNHEALTHY if err > 0.05 else HealthStatus.DEGRADED if err > 0.01 else HealthStatus.HEALTHY
        notes = [f"5xx ratio (5m avg) {err:.2%}"] + ([f"p95 latency {p95:.0f} ms"] if p95 else [])
        if svc.tier == "external":
            notes.append(f"external dependency owned by {svc.owner}")
        return ServiceHealth(
            service=service,
            status=status,
            as_of=env.sim_now,
            error_ratio=round(err, 5),
            p95_latency_ms=round(p95, 1),
            version=svc.current_version,
            notes=notes,
        )

    async def service_config(self, env_id: uuid.UUID, service: str) -> dict[str, Any]:
        svc = await self._require_service(env_id, service)
        return {
            "service": service,
            "tier": svc.tier,
            "owner": svc.owner,
            "version": svc.current_version,
            "replicas": svc.replicas,
            "config": svc.config,
        }

    async def datastore_status(self, env_id: uuid.UUID, datastore: str) -> dict[str, Any]:
        env = await self.environment(env_id)
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(SimInspection)
                    .where(
                        SimInspection.environment_id == env_id,
                        SimInspection.kind == "datastore",
                        SimInspection.target == datastore,
                        SimInspection.ts <= env.sim_now,
                    )
                    .order_by(SimInspection.ts.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"no status available for datastore {datastore!r}")
        return dict(row.payload)

    async def inspect_queue(self, env_id: uuid.UUID, queue: str) -> dict[str, Any]:
        if queue not in QUEUES:
            raise NotFoundError(f"unknown queue {queue!r}; known: {sorted(QUEUES)}")
        env = await self.environment(env_id)
        spec = QUEUES[queue]
        cond = [SimQueueMessage.environment_id == env_id, SimQueueMessage.queue == queue]
        async with self._sf() as s:
            counts = dict(
                (
                    await s.execute(
                        select(SimQueueMessage.status, func.count()).where(*cond).group_by(SimQueueMessage.status)
                    )
                ).all()
            )
            failures = (
                await s.execute(
                    select(
                        SimQueueMessage.error_code,
                        SimQueueMessage.last_error,
                        SimQueueMessage.producer_version,
                        SimQueueMessage.schema_version,
                        func.count(),
                    )
                    .where(*cond, SimQueueMessage.error_code.is_not(None), SimQueueMessage.status != "quarantined")
                    .group_by(
                        SimQueueMessage.error_code,
                        SimQueueMessage.last_error,
                        SimQueueMessage.producer_version,
                        SimQueueMessage.schema_version,
                    )
                )
            ).all()
            by_producer = (
                await s.execute(
                    select(SimQueueMessage.producer_version, SimQueueMessage.schema_version, func.count())
                    .where(*cond, SimQueueMessage.status.in_(["pending", "dead_lettered"]))
                    .group_by(SimQueueMessage.producer_version, SimQueueMessage.schema_version)
                )
            ).all()
            samples = (
                (
                    await s.execute(
                        select(SimQueueMessage)
                        .where(*cond, SimQueueMessage.status.in_(["dead_lettered", "pending"]))
                        .order_by(SimQueueMessage.enqueued_at.desc())
                        .limit(QUEUE_SAMPLE)
                    )
                )
                .scalars()
                .all()
            )
            oldest = (
                await s.execute(
                    select(func.min(SimQueueMessage.enqueued_at)).where(*cond, SimQueueMessage.status == "pending")
                )
            ).scalar()
        consumer = (env.state.get("consumers") or {}).get(queue) or {"service": spec["consumer"], "state": "running"}
        return {
            "queue": queue,
            "dead_letter_queue": spec["dead_letter_queue"],
            "expected_schema": spec["schema"],
            "producers": spec["producers"],
            "consumer": consumer,
            "as_of": env.sim_now.isoformat(),
            "pending": counts.get("pending", 0),
            "dead_lettered": counts.get("dead_lettered", 0),
            "quarantined": counts.get("quarantined", 0),
            "oldest_pending_age_s": int((env.sim_now - oldest).total_seconds()) if oldest else 0,
            "failures": [
                {"error_code": c, "error": e, "producer_version": pv, "schema_version": sv, "count": n}
                for c, e, pv, sv, n in failures
            ],
            "pending_or_dead_by_producer": [
                {"producer_version": pv, "schema_version": sv, "count": n} for pv, sv, n in by_producer
            ],
            "samples": [
                {
                    "message_id": m.message_id,
                    "status": m.status,
                    "attempts": m.attempts,
                    "producer_version": m.producer_version,
                    "schema_version": m.schema_version,
                    "payload_fields": sorted(m.payload),
                    "error": m.last_error,
                }
                for m in samples
            ],
        }

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
            if "service" in parameters and await s.get(SimService, (env_id, parameters["service"])) is None:
                raise ValidationFailure(f"unknown service {parameters['service']!r}")
            if "queue" in parameters and parameters["queue"] not in QUEUES:
                raise ValidationFailure(f"unknown queue {parameters['queue']!r}")
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
            state = dict(env.state)
            effect = scenario.apply_action(action_type, parameters, state=state, deployments=deployments, now=now)
            if effect.succeeded:
                state.update(effect.state_updates)
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
                for name, changes in effect.config_updates.items():
                    svc = await s.get(SimService, (env_id, name))
                    if svc is not None:
                        svc.config = {**svc.config, **changes}
                for qu in effect.queue_updates:
                    rows = (
                        (
                            await s.execute(
                                select(SimQueueMessage).where(
                                    SimQueueMessage.environment_id == env_id,
                                    SimQueueMessage.queue == qu.queue,
                                    SimQueueMessage.status.in_(qu.from_statuses),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for r in rows:
                        if qu.predicate(r.payload, r.error_code):
                            r.status, r.updated_at = qu.to_status, now
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
            # Time passes in the sandbox: generate the post-action window with the resulting state.
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
