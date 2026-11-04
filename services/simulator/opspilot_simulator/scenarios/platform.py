"""Shared baseline for scenarios built after INC-001.

A scenario supplies its change history, alert, initial state and a per-minute ``effects`` hook; the
base generates realistic baseline telemetry for every service and applies the overrides. INC-001
predates this base and keeps its own generator so its published dataset stays byte-identical.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from opspilot_simulator.scenarios.base import (
    ActionEffect,
    AlertSpec,
    ConfigChangeRow,
    DeploymentRow,
    InspectionRow,
    LogRow,
    MetricRow,
    QueueMessageRow,
    ScenarioData,
    Telemetry,
    minutes,
    trace_id,
)
from opspilot_simulator.topology import DATASTORES, SERVICE_CONFIG


@dataclass(slots=True)
class Minute:
    """Scenario output for one simulated minute."""

    overrides: dict[tuple[str, str], float] = field(default_factory=dict)
    logs: list[tuple[str, str, str, str, dict[str, Any]]] = field(
        default_factory=list
    )  # service, level, msg, logger, attrs
    suppress_baseline_logs: set[str] = field(default_factory=set)
    queue_messages: list[QueueMessageRow] = field(default_factory=list)


def common_history(onset: datetime) -> list[DeploymentRow]:
    """Older, unrelated changes present in every environment (realistic background noise)."""
    return [
        DeploymentRow(
            "dep-ta-3172",
            "transaction-api",
            "application",
            "3.17.2",
            "3.17.1",
            onset - timedelta(hours=26),
            onset - timedelta(hours=26) + timedelta(minutes=7),
            "succeeded",
            "a.rivera",
            "Refund validation fix for partial captures",
        ),
        DeploymentRow(
            "dep-ls-0284",
            "ledger-service",
            "application",
            "2.8.4",
            "2.8.3",
            onset - timedelta(days=3),
            onset - timedelta(days=3) + timedelta(minutes=9),
            "succeeded",
            "j.okafor",
            "Ledger posting metrics; no schema changes",
        ),
        DeploymentRow(
            "dep-sw-2311",
            "settlement-worker",
            "application",
            "2.3.1",
            "2.3.0",
            onset - timedelta(hours=5, minutes=10),
            onset - timedelta(hours=5, minutes=4),
            "succeeded",
            "p.singh",
            "Batch size tuning for EU merchants",
        ),
    ]


class PlatformScenario:
    key = "BASE"
    title = "platform scenario"
    history = timedelta(hours=4)
    detect_after = timedelta(minutes=9)
    now_after = timedelta(minutes=30)
    settlement_rate = 1150.0  # events/min at baseline

    # ---- hooks ---------------------------------------------------------------------------
    def deployments(self, onset: datetime) -> list[DeploymentRow]:
        return common_history(onset)

    def config_changes(self, onset: datetime) -> list[ConfigChangeRow]:
        return [
            ConfigChangeRow(
                "cfg-sw-0077",
                "settlement-worker",
                "batch.max_size",
                "500",
                "800",
                onset - timedelta(hours=5),
                "p.singh",
            )
        ]

    def alert(self, onset: datetime) -> AlertSpec:  # pragma: no cover - abstract
        raise NotImplementedError

    def initial_state(self, onset: datetime) -> dict[str, Any]:
        return {"fault_active": True, "onset": onset.isoformat(), "actions": []}

    def service_configs(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in SERVICE_CONFIG.items()}

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        return Minute()

    def datastore_snapshot(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> dict[str, Any] | None:
        pool = int(state.get("pool_max", 40))
        ledger = round(rng.gauss(13, 3)) * 4
        others = {"reporting-etl": 18, "admin": 2, "migrations": 0}
        active = ledger + sum(others.values())
        return {
            "datastore": "ledger-db",
            **DATASTORES["ledger-db"],
            "connections_active": active,
            "connections_by_client": {"ledger-service": ledger, **others},
            "client_pool_limits": {"ledger-service": {"pool_max_per_replica": pool, "replicas": 4}},
            "long_running_queries": [],
            "as_of": t.isoformat(),
        }

    def extra_logs(self, onset: datetime) -> list[LogRow]:
        return []

    def apply_action(
        self,
        action_type: str,
        parameters: dict[str, Any],
        *,
        state: dict[str, Any],
        deployments: list[DeploymentRow],
        now: datetime,
    ) -> ActionEffect:
        if action_type == "restart_service":
            return ActionEffect(
                True,
                f"rolling restart of {parameters['service']} completed",
                fault_cleared=False,
                details={"service": parameters["service"]},
            )
        if action_type == "rollback_deployment":
            target = next((d for d in deployments if d.id == parameters["deployment_id"]), None)
            if target is None or target.kind == "rollback" or target.status == "rolled_back":
                return ActionEffect(
                    False, f"deployment {parameters['deployment_id']} is not eligible for rollback", fault_cleared=False
                )
            return self.rollback_effect(target, now, cleared=self.is_culprit(target.id))
        return ActionEffect(False, f"action {action_type} has no effect in this environment", fault_cleared=False)

    def is_culprit(self, deployment_id: str) -> bool:
        return False

    @staticmethod
    def rollback_effect(
        target: DeploymentRow, now: datetime, *, cleared: bool, state_updates: dict[str, Any] | None = None
    ) -> ActionEffect:
        rb = DeploymentRow(
            f"dep-rb-{target.id.removeprefix('dep-')}",
            target.service,
            "rollback",
            target.previous_version or "unknown",
            target.version,
            now,
            now + timedelta(minutes=1),
            "succeeded",
            "opspilot-sandbox",
            f"Rollback of {target.id}",
            {"rolled_back_deployment_id": target.id},
        )
        versions = {} if target.kind == "schema_migration" else {target.service: target.previous_version or ""}
        return ActionEffect(
            True,
            f"rolled back {target.id} on {target.service}",
            cleared,
            [rb],
            versions,
            {"rollback_deployment_id": rb.id, "service": target.service},
            state_updates=state_updates or {},
        )

    # ---- generation ------------------------------------------------------------------------
    def generate(self, seed: int, anchor: datetime) -> ScenarioData:
        rng = random.Random(seed)
        onset = anchor
        state = self.initial_state(onset)
        sim_now = onset + self.now_after
        telemetry = self.telemetry_window(rng, onset - self.history, sim_now, fault_active=True, state=state)
        telemetry.logs.extend(self.extra_logs(onset))
        deployments = self.deployments(onset)
        versions = {
            "transaction-api": "3.17.2",
            "ledger-service": "2.8.4",
            "settlement-worker": "2.3.1",
            "fx-rates-provider": "saas",
        }
        for d in sorted(deployments, key=lambda d: d.started_at):
            if d.kind == "application" and d.status == "succeeded":
                versions[d.service] = d.version
        return ScenarioData(
            sim_now,
            deployments,
            self.config_changes(onset),
            telemetry,
            self.alert(onset),
            versions,
            state,
            self.service_configs(),
        )

    def telemetry_window(
        self, rng: random.Random, start: datetime, end: datetime, *, fault_active: bool, state: dict[str, Any]
    ) -> Telemetry:
        out = Telemetry()
        for t in minutes(start, end):
            m = self.effects(rng, t, state) if fault_active or state.get("always_effects") else Minute()
            self._baseline(rng, t, out, m)
            out.queue_messages.extend(m.queue_messages)
            if t.minute % 5 == 0 or t == minutes(start, end)[-1]:
                snap = self.datastore_snapshot(rng, t, state)
                if snap:
                    out.inspections.append(InspectionRow(t, "datastore", snap["datastore"], snap))
        return out

    def _baseline(self, rng: random.Random, t: datetime, out: Telemetry, m: Minute) -> None:
        o = m.overrides

        def metric(service: str, name: str, value: float) -> None:
            out.metrics.append(MetricRow(t, service, name, round(max(o.get((service, name), value), 0.0), 5)))

        rpm = rng.gauss(1200, 60)
        metric("transaction-api", "http_requests_per_min", rpm)
        metric("transaction-api", "http_5xx_ratio", rng.uniform(0.001, 0.004))
        metric("transaction-api", "p95_latency_ms", rng.gauss(180, 12))
        metric("ledger-service", "http_requests_per_min", rpm * 2.1 + rng.gauss(0, 40))
        metric("ledger-service", "http_5xx_ratio", rng.uniform(0.0005, 0.002))
        metric("ledger-service", "p95_latency_ms", rng.gauss(45, 4))
        metric("ledger-service", "db_pool_in_use", rng.gauss(13, 3))
        metric("ledger-service", "db_pool_max", 40)
        metric("ledger-service", "db_pool_wait_ms", abs(rng.gauss(2, 1)))
        metric("settlement-worker", "queue_depth", rng.gauss(310, 45))
        metric("settlement-worker", "events_processed_per_min", rng.gauss(self.settlement_rate, 50))
        metric("settlement-worker", "validation_failures_per_min", rng.choice([0, 0, 0, 1]))
        metric("settlement-worker", "consumer_retries_per_min", rng.choice([0, 0, 1, 2]))
        metric("settlement-worker", "dlq_depth", 12)
        metric("fx-rates-provider", "p95_latency_ms", rng.gauss(140, 15))
        metric("fx-rates-provider", "http_5xx_ratio", rng.uniform(0.0, 0.002))

        def log(service: str, level: str, msg: str, logger: str, **attrs: Any) -> None:
            ts = t + timedelta(seconds=rng.randint(0, 59), milliseconds=rng.randint(0, 999))
            out.logs.append(LogRow(ts, service, level, msg, logger, trace_id(rng), attrs))

        if "transaction-api" not in m.suppress_baseline_logs:
            log(
                "transaction-api",
                "INFO",
                f"POST /v1/payments 201 in {rng.randint(90, 210)}ms",
                "api.access",
                endpoint="POST /v1/payments",
                status=201,
            )
        if "ledger-service" not in m.suppress_baseline_logs:
            log(
                "ledger-service",
                "INFO",
                f"POST /v1/entries 201 in {rng.randint(20, 60)}ms",
                "ledger.access",
                endpoint="POST /v1/entries",
                status=201,
            )
        if "settlement-worker" not in m.suppress_baseline_logs:
            log(
                "settlement-worker",
                "INFO",
                f"Submitted settlement batch with {rng.randint(80, 240)} payments",
                "settlement.batch",
            )
        if rng.random() < 0.08:
            log(
                "transaction-api",
                "WARN",
                "Idempotency-Key reused with different payload (IDEMPOTENCY_CONFLICT)",
                "api.idempotency",
                code="IDEMPOTENCY_CONFLICT",
                status=409,
            )
        if rng.random() < 0.04:
            log("ledger-service", "WARN", f"Slow query on ledger_entries ({rng.randint(300, 700)}ms)", "ledger.db")
        if rng.random() < 0.03:
            log(
                "settlement-worker",
                "ERROR",
                "Bank SFTP upload retry 1/3: connection reset by peer",
                "settlement.sftp",
                upstream="bank-sftp",
            )
        for service, level, msg, logger, attrs in m.logs:
            log(service, level, msg, logger, **attrs)
