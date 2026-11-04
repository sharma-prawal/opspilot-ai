"""Scenario framework. A scenario generates deterministic telemetry for a time window given
whether its fault is active, and decides how sandbox actions change the fault state.

Scenario modules know the injected fault. They are *never* exposed to agents: agents only see
the generated telemetry through MCP tools. Answer keys live in datasets/evaluation/ground_truth.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol


@dataclass(slots=True)
class LogRow:
    ts: datetime
    service: str
    level: str
    message: str
    logger: str
    trace_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetricRow:
    ts: datetime
    service: str
    name: str
    value: float


@dataclass(slots=True)
class DeploymentRow:
    id: str
    service: str
    kind: str
    version: str
    previous_version: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    author: str
    change_summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConfigChangeRow:
    id: str
    service: str
    key: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime
    author: str


@dataclass(slots=True)
class AlertSpec:
    title: str
    description: str
    severity: str
    service: str
    detected_at: datetime


@dataclass(slots=True)
class InspectionRow:
    ts: datetime
    kind: str  # datastore | queue
    target: str
    payload: dict[str, Any]


@dataclass(slots=True)
class QueueMessageRow:
    queue: str
    message_id: str
    producer_service: str
    producer_version: str
    schema_version: str
    payload: dict[str, Any]
    status: str
    attempts: int
    error_code: str | None
    last_error: str | None
    enqueued_at: datetime


@dataclass(slots=True)
class Telemetry:
    logs: list[LogRow] = field(default_factory=list)
    metrics: list[MetricRow] = field(default_factory=list)
    inspections: list[InspectionRow] = field(default_factory=list)
    queue_messages: list[QueueMessageRow] = field(default_factory=list)

    def extend(self, other: Telemetry) -> None:
        self.logs.extend(other.logs)
        self.metrics.extend(other.metrics)
        self.inspections.extend(other.inspections)
        self.queue_messages.extend(other.queue_messages)


@dataclass(slots=True)
class ScenarioData:
    sim_now: datetime
    deployments: list[DeploymentRow]
    config_changes: list[ConfigChangeRow]
    telemetry: Telemetry
    alert: AlertSpec
    service_versions: dict[str, str]
    state: dict[str, Any]
    service_configs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class QueueUpdate:
    """Status transition applied to matching queue records (e.g. quarantine). Records are never deleted."""

    queue: str
    from_statuses: tuple[str, ...]
    to_status: str
    predicate: Callable[[dict[str, Any], str | None], bool]
    attempts: int | None = None
    error_code: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class ActionEffect:
    """What a sandbox action did to the environment."""

    succeeded: bool
    message: str
    fault_cleared: bool
    deployments: list[DeploymentRow] = field(default_factory=list)
    service_versions: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    state_updates: dict[str, Any] = field(default_factory=dict)
    config_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue_updates: list[QueueUpdate] = field(default_factory=list)


class Scenario(Protocol):
    key: str
    title: str

    def generate(self, seed: int, anchor: datetime) -> ScenarioData: ...

    def telemetry_window(
        self, rng: random.Random, start: datetime, end: datetime, *, fault_active: bool, state: dict[str, Any]
    ) -> Telemetry: ...

    def apply_action(
        self,
        action_type: str,
        parameters: dict[str, Any],
        *,
        state: dict[str, Any],
        deployments: list[DeploymentRow],
        now: datetime,
    ) -> ActionEffect: ...


def minutes(start: datetime, end: datetime) -> list[datetime]:
    out, t = [], start.replace(second=0, microsecond=0)
    while t < end:
        out.append(t)
        t += timedelta(minutes=1)
    return out


def trace_id(rng: random.Random) -> str:
    return f"{rng.getrandbits(128):032x}"
