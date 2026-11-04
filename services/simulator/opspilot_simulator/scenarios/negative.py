"""Negative and ambiguous scenarios. The correct outcome is *not* an automated remediation.

NEG-001  False positive: a short 5xx blip during a routine pod reschedule, already recovered.
NEG-002  External dependency degradation with an unrelated (tempting) deployment on the alerting service.
NEG-003  Ambiguous + incomplete: two simultaneous changes, and the log backend is unavailable for the
         service that would discriminate them (tool error).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from opspilot_simulator.scenarios.base import AlertSpec, ConfigChangeRow, DeploymentRow
from opspilot_simulator.scenarios.platform import Minute, PlatformScenario, common_history


class TransientBlipScenario(PlatformScenario):
    key = "NEG-001"
    title = "short-lived 5xx blip during a pod reschedule (already recovered)"
    detect_after = timedelta(minutes=5)
    now_after = timedelta(minutes=25)

    def alert(self, onset: datetime) -> AlertSpec:
        return AlertSpec(
            title="Elevated HTTP 5xx ratio on transaction-api",
            description=(
                "Alert TransactionApi5xxRatioHigh fired: 5xx ratio above 2% on transaction-api. "
                "No customer reports yet."
            ),
            severity="SEV3",
            service="transaction-api",
            detected_at=onset + self.detect_after,
        )

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        onset = datetime.fromisoformat(state["onset"])
        m = Minute()
        if onset <= t < onset + timedelta(minutes=4):
            m.overrides[("transaction-api", "http_5xx_ratio")] = rng.uniform(0.03, 0.05)
            m.overrides[("ledger-service", "http_5xx_ratio")] = rng.uniform(0.02, 0.04)
            for _ in range(rng.randint(2, 4)):
                m.logs.append(
                    (
                        "transaction-api",
                        "ERROR",
                        "POST /v1/payments failed: upstream ledger-service connection reset (retry exhausted)",
                        "api.payments",
                        {"upstream": "ledger-service", "status": 502},
                    )
                )
            if t == onset:
                m.logs.append(
                    (
                        "ledger-service",
                        "INFO",
                        "Pod ledger-service-7c9f4 terminating: node drain for scheduled kernel patch; "
                        "replacement pod ledger-service-2b81d ready in 41s",
                        "k8s.lifecycle",
                        {"reason": "node-maintenance"},
                    )
                )
        return m


class ExternalDependencyScenario(PlatformScenario):
    key = "NEG-002"
    title = "payment timeouts from FX provider degradation (with an unrelated deployment)"
    detect_after = timedelta(minutes=8)

    def deployments(self, onset: datetime) -> list[DeploymentRow]:
        return [
            *common_history(onset),
            DeploymentRow(
                "dep-ta-3173",
                "transaction-api",
                "application",
                "3.17.3",
                "3.17.2",
                onset - timedelta(minutes=12),
                onset - timedelta(minutes=7),
                "succeeded",
                "a.rivera",
                "Update OpenAPI docs and request logging format",
                {},
            ),
        ]

    def alert(self, onset: datetime) -> AlertSpec:
        return AlertSpec(
            title="Elevated HTTP 5xx ratio on transaction-api",
            description=(
                "Alert TransactionApi5xxRatioHigh: 5xx ratio above 2% for 5 minutes on transaction-api. "
                "Some checkouts are failing."
            ),
            severity="SEV2",
            service="transaction-api",
            detected_at=onset + self.detect_after,
        )

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        m = Minute()
        if t < datetime.fromisoformat(state["onset"]):
            return m
        m.overrides.update(
            {
                ("fx-rates-provider", "p95_latency_ms"): rng.gauss(5200, 600),
                ("fx-rates-provider", "http_5xx_ratio"): rng.uniform(0.15, 0.25),
                ("transaction-api", "http_5xx_ratio"): rng.uniform(0.05, 0.07),
                ("transaction-api", "p95_latency_ms"): rng.gauss(2050, 100),
            }
        )
        for _ in range(rng.randint(3, 5)):
            m.logs.append(
                (
                    "transaction-api",
                    "ERROR",
                    "POST /v1/payments failed: upstream fx-rates-provider timed out after 2000ms "
                    "code=PAYMENT_TIMEOUT (cross-currency)",
                    "api.payments",
                    {"upstream": "fx-rates-provider", "status": 504, "code": "PAYMENT_TIMEOUT"},
                )
            )
        if rng.random() < 0.4:
            m.logs.append(
                (
                    "transaction-api",
                    "WARN",
                    "fx-rates circuit breaker half-open; cache expired for EUR/GBP",
                    "api.fx",
                    {"upstream": "fx-rates-provider"},
                )
            )
        return m


class AmbiguousIncompleteScenario(PlatformScenario):
    key = "NEG-003"
    title = "ledger errors after two simultaneous changes, with ledger logs unavailable"
    detect_after = timedelta(minutes=8)

    def deployments(self, onset: datetime) -> list[DeploymentRow]:
        return [
            *common_history(onset),
            DeploymentRow(
                "dep-ls-0292",
                "ledger-service",
                "application",
                "2.9.2",
                "2.8.4",
                onset - timedelta(minutes=9),
                onset - timedelta(minutes=3),
                "succeeded",
                "j.okafor",
                "Dependency upgrades (database driver and HTTP client)",
                {},
            ),
        ]

    def config_changes(self, onset: datetime) -> list[ConfigChangeRow]:
        return [
            *super().config_changes(onset),
            ConfigChangeRow(
                "cfg-ls-0144",
                "ledger-service",
                "db.statement_timeout_ms",
                "30000",
                "800",
                onset - timedelta(minutes=4),
                "ops-automation",
            ),
        ]

    def initial_state(self, onset: datetime) -> dict[str, Any]:
        # Observable environment behaviour, not an answer key: the log backend is down for ledger-service.
        return {
            **super().initial_state(onset),
            "tool_faults": {"search_logs:ledger-service": "log backend unavailable: ingestion lag exceeds 45 minutes"},
        }

    def alert(self, onset: datetime) -> AlertSpec:
        return AlertSpec(
            title="Elevated HTTP 5xx ratio on transaction-api",
            description="Alert TransactionApi5xxRatioHigh: 5xx ratio above 2% for 5 minutes on transaction-api.",
            severity="SEV2",
            service="transaction-api",
            detected_at=onset + self.detect_after,
        )

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        m = Minute()
        if t < datetime.fromisoformat(state["onset"]):
            return m
        m.overrides.update(
            {
                ("ledger-service", "http_5xx_ratio"): rng.uniform(0.04, 0.06),
                ("ledger-service", "p95_latency_ms"): rng.gauss(520, 60),
                ("transaction-api", "http_5xx_ratio"): rng.uniform(0.03, 0.05),
            }
        )
        for _ in range(rng.randint(2, 3)):
            m.logs.append(
                (
                    "transaction-api",
                    "ERROR",
                    "POST /v1/payments failed: upstream ledger-service returned 500 code=LEDGER_WRITE_FAILED",
                    "api.payments",
                    {"upstream": "ledger-service", "status": 500, "code": "LEDGER_WRITE_FAILED"},
                )
            )
        return m
