"""INC-003: settlement processing failure from invalid message payloads (poison messages).

Fault: transaction-api 3.18.0 publishes ``payment.authorized`` events with ``currency`` renamed to
``currency_code`` (a draft v4 schema). settlement-worker validates against settlement-event.v3, retries
each invalid message 3 times, then dead-letters it. Retrying head-of-line poison messages stalls
partitions, so valid messages queue up behind them and settlement throughput collapses.

Misleading clues: a settlement-worker config change lowering ``consumer.max_retries`` 50 minutes before
onset, and routine bank SFTP retry noise.

Remediation semantics (enforced by the sandbox state machine):
- pause_consumer: containment only — stops retry churn, nothing is processed, backlog grows.
- rollback_deployment(dep-ta-3180): stops new invalid messages; existing poison remains.
- quarantine_messages(queue, error_code): moves schema-invalid records (pending or dead-lettered) to
  quarantine, preserved for replay. While the producer is still bad, new poison keeps arriving.
- resume_consumer: processing restarts; recovers only when the producer is fixed and poison is gone.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from opspilot_simulator.scenarios.base import (
    ActionEffect,
    AlertSpec,
    ConfigChangeRow,
    DeploymentRow,
    QueueMessageRow,
    QueueUpdate,
)
from opspilot_simulator.scenarios.platform import Minute, PlatformScenario, common_history

CULPRIT = "dep-ta-3180"
QUEUE = "settlement-events"
ERROR_CODE = "SETTLEMENT_SCHEMA_INVALID"
REQUIRED_V3 = ("payment_id", "merchant_id", "amount_minor", "currency", "authorized_at")
RATE = 120.0  # events/min in this environment
DRAIN_RATE = 600  # events/min when draining a clean backlog
POISONED_THROUGHPUT = 5  # valid events/min processed while partitions retry poison


def schema_invalid(payload: dict[str, Any], error_code: str | None) -> bool:
    """The sandbox's own validation against settlement-event.v3 (independent of the agent)."""
    return error_code == ERROR_CODE or any(k not in payload for k in REQUIRED_V3)


class InvalidPayloadScenario(PlatformScenario):
    key = "INC-003"
    title = "settlement-worker failing on invalid message payloads"
    detect_after = timedelta(minutes=10)
    settlement_rate = RATE

    def deployments(self, onset: datetime) -> list[DeploymentRow]:
        return [
            *common_history(onset),
            DeploymentRow(
                CULPRIT,
                "transaction-api",
                "application",
                "3.18.0",
                "3.17.2",
                onset - timedelta(minutes=7),
                onset - timedelta(minutes=2),
                "succeeded",
                "a.rivera",
                "Payment events: rename currency to currency_code (settlement-event.v4 draft)",
                {"event_schema": "settlement-event.v4-draft"},
            ),
        ]

    def config_changes(self, onset: datetime) -> list[ConfigChangeRow]:
        return [
            *super().config_changes(onset),
            ConfigChangeRow(
                "cfg-sw-0081",
                "settlement-worker",
                "consumer.max_retries",
                "5",
                "3",
                onset - timedelta(minutes=50),
                "p.singh",
            ),
        ]

    def alert(self, onset: datetime) -> AlertSpec:
        return AlertSpec(
            title="Settlement dead-letter queue growing; throughput below SLO",
            description=(
                "Alert SettlementDLQGrowing: settlement-events.dlq grew by more than 500 messages in 10 "
                "minutes and settlement-worker throughput is below the 15-minute settlement SLO."
            ),
            severity="SEV2",
            service="settlement-worker",
            detected_at=onset + self.detect_after,
        )

    def initial_state(self, onset: datetime) -> dict[str, Any]:
        return {
            **super().initial_state(onset),
            "always_effects": True,
            "producer_bad": True,
            "consumer_paused": False,
            "pending_valid": 0,
            "pending_invalid": 0,
            "dlq": 0,
            "quarantined": 0,
            "consumers": {QUEUE: {"service": "settlement-worker", "state": "running"}},
        }

    @staticmethod
    def _msg(rng: random.Random, t: datetime, *, invalid: bool, status: str, attempts: int) -> QueueMessageRow:
        payload: dict[str, Any] = {
            "payment_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "merchant_id": f"m-{rng.randint(1000, 9999)}",
            "amount_minor": rng.randint(500, 250000),
            "authorized_at": t.isoformat(),
        }
        payload["currency_code" if invalid else "currency"] = rng.choice(["EUR", "GBP", "USD"])
        return QueueMessageRow(
            QUEUE,
            f"msg-{rng.getrandbits(48):012x}",
            "transaction-api",
            "3.18.0" if invalid else "3.17.2",
            "settlement-event.v4-draft" if invalid else "settlement-event.v3",
            payload,
            status,
            attempts,
            ERROR_CODE if invalid and attempts else None,
            "'currency' is a required property" if invalid and attempts else None,
            t + timedelta(seconds=rng.randint(0, 59)),
        )

    def effects(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> Minute:
        onset = datetime.fromisoformat(state["onset"])
        m = Minute()
        if t < onset:
            m.overrides[("settlement-worker", "queue_depth")] = 40 + abs(rng.gauss(0, 6))
            return m
        invalid = round(RATE * rng.uniform(0.86, 0.94)) if state["producer_bad"] else 0
        valid = round(RATE * rng.uniform(0.95, 1.05)) - invalid
        retries = failures = processed = 0
        if state["consumer_paused"]:
            state["pending_valid"] += valid
            state["pending_invalid"] += invalid
            m.queue_messages += [self._msg(rng, t, invalid=True, status="pending", attempts=0) for _ in range(invalid)]
            m.queue_messages += [self._msg(rng, t, invalid=False, status="pending", attempts=0) for _ in range(valid)]
            m.suppress_baseline_logs.add("settlement-worker")
            if t.minute % 3 == 0:
                m.logs.append(
                    (
                        "settlement-worker",
                        "INFO",
                        f"Consumer paused; {QUEUE} backlog "
                        f"{state['pending_valid'] + state['pending_invalid']} messages",
                        "settlement.consumer",
                        {},
                    )
                )
        else:
            poison = invalid + state["pending_invalid"]
            if poison:
                failures, retries = poison, poison * 2
                state["dlq"] += poison
                state["pending_invalid"] = 0
                m.queue_messages += [
                    self._msg(rng, t, invalid=True, status="dead_lettered", attempts=3) for _ in range(invalid)
                ]
                processed = min(state["pending_valid"] + valid, POISONED_THROUGHPUT)
                backlog_add = valid - processed
                state["pending_valid"] += backlog_add
                m.queue_messages += [
                    self._msg(rng, t, invalid=False, status="pending", attempts=0) for _ in range(max(backlog_add, 0))
                ]
                m.suppress_baseline_logs.add("settlement-worker")
                for _ in range(min(poison, rng.randint(4, 7))):
                    mid = f"msg-{rng.getrandbits(48):012x}"
                    m.logs.append(
                        (
                            "settlement-worker",
                            "ERROR",
                            f"Message {mid} failed validation against settlement-event.v3: 'currency' is a "
                            f"required property (attempt 3/3); moved to {QUEUE}.dlq",
                            "settlement.validation",
                            {
                                "code": ERROR_CODE,
                                "producer_version": "3.18.0",
                                "schema_version": "settlement-event.v4-draft",
                            },
                        )
                    )
                    m.logs.append(
                        (
                            "settlement-worker",
                            "WARN",
                            f"Retrying message {mid} (attempt 2/3)",
                            "settlement.consumer",
                            {"code": ERROR_CODE},
                        )
                    )
                if rng.random() < 0.5:
                    m.logs.append(
                        (
                            "settlement-worker",
                            "WARN",
                            f"Partition {rng.randint(0, 11)} consumer lag {rng.randint(300, 900)}s: "
                            "head-of-line message retrying",
                            "settlement.consumer",
                            {},
                        )
                    )
            else:
                processed = min(state["pending_valid"] + valid, DRAIN_RATE)
                state["pending_valid"] = max(0, state["pending_valid"] + valid - processed)
        depth = 40 + state["pending_valid"] + state["pending_invalid"]
        m.overrides.update(
            {
                ("settlement-worker", "events_processed_per_min"): float(processed) if t >= onset else RATE,
                ("settlement-worker", "validation_failures_per_min"): float(failures),
                ("settlement-worker", "consumer_retries_per_min"): float(retries),
                ("settlement-worker", "dlq_depth"): 12.0 + state["dlq"],
                ("settlement-worker", "queue_depth"): float(depth),
            }
        )
        if t == onset + timedelta(minutes=1):
            m.logs.append(
                (
                    "transaction-api",
                    "INFO",
                    "Publishing payment.authorized with schema settlement-event.v4-draft",
                    "api.events",
                    {"schema_version": "settlement-event.v4-draft"},
                )
            )
        return m

    def datastore_snapshot(self, rng: random.Random, t: datetime, state: dict[str, Any]) -> dict[str, Any] | None:
        return super().datastore_snapshot(rng, t, state)

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
        consumers = {QUEUE: {"service": "settlement-worker", "state": "running"}}
        if action_type == "pause_consumer":
            if state["consumer_paused"]:
                return ActionEffect(False, "consumer already paused", fault_cleared=False)
            consumers[QUEUE]["state"] = "paused"
            return ActionEffect(
                True,
                "settlement-worker consumer paused (containment: nothing is processed)",
                fault_cleared=False,
                state_updates={"consumer_paused": True, "consumers": consumers},
            )
        if action_type == "resume_consumer":
            if not state["consumer_paused"]:
                return ActionEffect(False, "consumer is not paused", fault_cleared=False)
            clean = not state["producer_bad"] and state["pending_invalid"] == 0
            drained = (
                [QueueUpdate(QUEUE, ("pending",), "processed", lambda p, e: not schema_invalid(p, e))] if clean else []
            )
            return ActionEffect(
                True,
                "settlement-worker consumer resumed",
                fault_cleared=clean,
                state_updates={"consumer_paused": False, "consumers": consumers, "fault_active": not clean},
                queue_updates=drained,
            )
        if action_type == "quarantine_messages":
            if parameters.get("queue") != QUEUE or parameters.get("error_code") != ERROR_CODE:
                return ActionEffect(False, "no messages match the requested queue/error code", fault_cleared=False)
            moved = state["pending_invalid"] + state["dlq"]
            update = QueueUpdate(QUEUE, ("pending", "dead_lettered"), "quarantined", schema_invalid)
            return ActionEffect(
                True,
                f"quarantined {moved} schema-invalid messages from {QUEUE} and its DLQ (preserved for replay)",
                fault_cleared=False,
                details={"quarantined": moved},
                state_updates={"pending_invalid": 0, "dlq": 0, "quarantined": state["quarantined"] + moved},
                queue_updates=[update],
            )
        if action_type == "rollback_deployment" and parameters.get("deployment_id") == CULPRIT:
            target = next(d for d in deployments if d.id == CULPRIT)
            if target.status == "rolled_back":
                return ActionEffect(False, f"{CULPRIT} already rolled back", fault_cleared=False)
            return self.rollback_effect(target, now, cleared=False, state_updates={"producer_bad": False})
        return super().apply_action(action_type, parameters, state=state, deployments=deployments, now=now)
