"""INC-002: transaction latency and timeouts from exhausted ledger DB connection pools.

Fault: ledger-service 2.9.1 adds a merchant-statement export endpoint whose query sequentially scans
``ledger_entries`` (~2.9 s per call). Requests hold pooled connections for seconds, every replica's pool
(40) saturates, ledger requests wait for connections and time out, and transaction-api returns 504s.

Misleading clues: a marketing traffic increase starting 15 minutes before onset (plausible "we need a
bigger pool" story) and a superseded runbook in the knowledge base recommending a pool increase.
Capacity: ledger-db max_connections is 200 and is already ~94% used, so raising the pool enough to matter
would exceed the datastore's capacity. The sandbox refuses such a change regardless of approval.

Correct resolution: roll back dep-ls-0291 (removes the slow query). A pool increase that fits capacity is
executed but does not recover the service (connections are held by the slow query, not lacking).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from opspilot_simulator.scenarios.base import ActionEffect, AlertSpec, DeploymentRow
from opspilot_simulator.scenarios.platform import Minute, PlatformScenario, common_history
from opspilot_simulator.topology import DATASTORES

CULPRIT = "dep-ls-0291"
REPLICAS = 4
OTHER_CLIENTS = {"reporting-etl": 18, "admin": 2, "migrations": 0}
SLOW_QUERY = (
    "SELECT entry_id, amount, currency, created_at FROM ledger_entries WHERE account_id = $1 "
    "AND created_at BETWEEN $2 AND $3 ORDER BY created_at"
)


class PoolExhaustionScenario(PlatformScenario):
    key = "INC-002"
    title = "transaction-api timeouts from ledger connection pool exhaustion"
    detect_after = timedelta(minutes=8)

    def deployments(self, onset: datetime) -> list[DeploymentRow]:
        return [
            *common_history(onset),
            DeploymentRow(
                CULPRIT,
                "ledger-service",
                "application",
                "2.9.1",
                "2.8.4",
                onset - timedelta(minutes=11),
                onset - timedelta(minutes=6),
                "succeeded",
                "l.moreau",
                "Add merchant statement export endpoint GET /v1/accounts/{id}/statements",
                {"feature_flag": "statements_export", "rollout": "100%"},
            ),
        ]

    def alert(self, onset: datetime) -> AlertSpec:
        return AlertSpec(
            title="transaction-api p95 latency and 5xx above SLO",
            description=(
                "Alert TransactionApiLatencyHigh: p95 above 400 ms for 5 minutes and 5xx ratio above 2% "
                "on transaction-api. Checkout requests are slow and some time out."
            ),
            severity="SEV2",
            service="transaction-api",
            detected_at=onset + self.detect_after,
        )

    def initial_state(self, onset: datetime) -> dict[str, Any]:
        return {**super().initial_state(onset), "slow_query_active": True, "pool_max": 40}

    def _active(self, t: datetime, state: dict[str, Any]) -> bool:
        return bool(state.get("slow_query_active")) and t >= datetime.fromisoformat(state["onset"])

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        onset = datetime.fromisoformat(state["onset"])
        m = Minute()
        # Misleading clue: traffic grows ~25% from 15 minutes before onset and stays elevated.
        if t >= onset - timedelta(minutes=15):
            m.overrides[("transaction-api", "http_requests_per_min")] = rng.gauss(1500, 60)
            if rng.random() < 0.15:
                m.logs.append(
                    (
                        "transaction-api",
                        "INFO",
                        "Traffic above forecast: campaign EARLY-BIRD active",
                        "api.capacity",
                        {"campaign": "EARLY-BIRD"},
                    )
                )
        if not self._active(t, state):
            return m
        ramp = min(1.0, (t - onset).total_seconds() / 300 + 0.2)
        pool = float(state.get("pool_max", 40))
        m.overrides.update(
            {
                ("ledger-service", "p95_latency_ms"): rng.gauss(2600, 150) * ramp,
                ("ledger-service", "db_pool_in_use"): pool,
                ("ledger-service", "db_pool_max"): pool,
                ("ledger-service", "db_pool_wait_ms"): rng.gauss(3800, 400) * ramp,
                ("ledger-service", "http_5xx_ratio"): rng.uniform(0.08, 0.12) * ramp,
                ("transaction-api", "p95_latency_ms"): rng.gauss(2450, 120) * ramp,
                ("transaction-api", "http_5xx_ratio"): rng.uniform(0.10, 0.16) * ramp,
            }
        )
        for _ in range(rng.randint(3, 5)):
            m.logs.append(
                (
                    "ledger-service",
                    "WARN",
                    f"Slow query ({rng.randint(2600, 3200)}ms, Seq Scan on ledger_entries): {SLOW_QUERY}",
                    "ledger.db",
                    {"endpoint": "GET /v1/accounts/{id}/statements", "plan": "Seq Scan"},
                )
            )
        for _ in range(rng.randint(4, 7)):
            m.logs.append(
                (
                    "ledger-service",
                    "ERROR",
                    "PoolTimeout: couldn't get a connection after 5.00 sec",
                    "ledger.pool",
                    {"code": "LEDGER_POOL_TIMEOUT", "status": 503, "pool_max": int(pool)},
                )
            )
            m.logs.append(
                (
                    "transaction-api",
                    "ERROR",
                    "POST /v1/payments failed: upstream ledger-service timed out after 2500ms code=PAYMENT_TIMEOUT",
                    "api.payments",
                    {"upstream": "ledger-service", "status": 504, "code": "PAYMENT_TIMEOUT"},
                )
            )
        return m

    def datastore_snapshot(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> dict[str, Any] | None:
        pool = int(state.get("pool_max", 40))
        active_fault = self._active(t, state)
        ledger = pool * REPLICAS if active_fault else round(rng.gauss(13, 3)) * REPLICAS
        long_running = (
            [
                {
                    "fingerprint": SLOW_QUERY,
                    "sessions": rng.randint(118, 142),
                    "mean_ms": rng.randint(2700, 3000),
                    "plan": "Seq Scan on ledger_entries (rows=48M)",
                    "client": "ledger-service",
                    "first_seen": state["onset"],
                }
            ]
            if active_fault
            else []
        )
        return {
            "datastore": "ledger-db",
            **DATASTORES["ledger-db"],
            "connections_active": ledger + sum(OTHER_CLIENTS.values()) + (rng.randint(4, 8) if active_fault else 0),
            "connections_by_client": {"ledger-service": ledger, **OTHER_CLIENTS},
            "client_pool_limits": {"ledger-service": {"pool_max_per_replica": pool, "replicas": REPLICAS}},
            "long_running_queries": long_running,
            "as_of": t.isoformat(),
        }

    def is_culprit(self, deployment_id: str) -> bool:
        return deployment_id == CULPRIT

    def apply_action(
        self,
        action_type: str,
        parameters: dict[str, Any],
        *,
        state: dict[str, Any],
        deployments: list[DeploymentRow],
        now: datetime,
    ) -> ActionEffect:
        if action_type == "rollback_deployment" and parameters.get("deployment_id") == CULPRIT:
            target = next(d for d in deployments if d.id == CULPRIT)
            if target.status == "rolled_back":
                return ActionEffect(False, f"{CULPRIT} already rolled back", fault_cleared=False)
            return self.rollback_effect(
                target, now, cleared=True, state_updates={"slow_query_active": False, "fault_active": False}
            )
        if action_type == "scale_connection_pool":
            new = int(parameters["max_connections"])
            ds: dict[str, Any] = DATASTORES["ledger-db"]
            capacity = int(ds["max_connections"]) - int(ds["reserved_superuser_connections"])
            projected = new * REPLICAS + sum(OTHER_CLIENTS.values())
            if projected > capacity:
                return ActionEffect(
                    False,
                    f"refused: {REPLICAS} replicas x {new} + {sum(OTHER_CLIENTS.values())} other "
                    f"clients = {projected} connections exceeds ledger-db capacity {capacity}",
                    fault_cleared=False,
                    details={"projected_connections": projected, "capacity": capacity},
                )
            return ActionEffect(
                True,
                f"ledger-service pool max set to {new} per replica",
                fault_cleared=False,
                details={"projected_connections": projected, "capacity": capacity},
                state_updates={"pool_max": new},
                config_updates={"ledger-service": {"db.pool.max": new}},
            )
        return super().apply_action(action_type, parameters, state=state, deployments=deployments, now=now)
