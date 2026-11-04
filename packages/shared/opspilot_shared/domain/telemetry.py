"""Contracts for observability / change data returned by ops tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from opspilot_shared.domain.common import Contract, ServiceName, UtcDatetime


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class LogEntry(Contract):
    ts: UtcDatetime
    service: ServiceName
    level: LogLevel
    message: str
    logger: str | None = None
    trace_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class LogSearchResult(Contract):
    entries: list[LogEntry]
    total_matched: int
    truncated: bool


class MetricPoint(Contract):
    ts: UtcDatetime
    value: float


class MetricSeries(Contract):
    service: ServiceName
    metric: str
    unit: str
    points: list[MetricPoint]


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ServiceHealth(Contract):
    service: ServiceName
    status: HealthStatus
    as_of: UtcDatetime
    error_ratio: float
    p95_latency_ms: float
    version: str
    notes: list[str] = Field(default_factory=list)


class DeploymentKind(StrEnum):
    APPLICATION = "application"
    SCHEMA_MIGRATION = "schema_migration"
    ROLLBACK = "rollback"


class Deployment(Contract):
    id: str
    service: ServiceName
    kind: DeploymentKind
    version: str
    previous_version: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    status: str
    author: str
    change_summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigChange(Contract):
    id: str
    service: ServiceName
    key: str
    old_value: str | None
    new_value: str | None
    changed_at: UtcDatetime
    author: str


class ServiceDependency(Contract):
    service: ServiceName
    depends_on: ServiceName
    kind: str = Field(description="sync_http | async_queue | database")
    critical: bool


class DependencyGraph(Contract):
    service: ServiceName
    downstream: list[ServiceDependency]
    upstream: list[ServiceDependency]
