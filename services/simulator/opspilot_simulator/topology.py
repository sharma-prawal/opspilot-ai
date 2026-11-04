"""Static topology of the synthetic payment platform (shared by all scenarios)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceDef:
    name: str
    tier: str
    owner: str
    version: str
    replicas: int


@dataclass(frozen=True, slots=True)
class DependencyDef:
    service: str
    depends_on: str
    kind: str
    critical: bool


SERVICES: tuple[ServiceDef, ...] = (
    ServiceDef("transaction-api", "edge", "payments-api-team", "3.17.2", 6),
    ServiceDef("ledger-service", "core", "ledger-team", "2.8.4", 4),
    ServiceDef("settlement-worker", "batch", "settlement-team", "2.3.1", 3),
)

DEPENDENCIES: tuple[DependencyDef, ...] = (
    DependencyDef("transaction-api", "ledger-service", "sync_http", True),
    DependencyDef("transaction-api", "fx-rates-provider", "sync_http", False),
    DependencyDef("transaction-api", "settlement-events", "async_queue", False),
    DependencyDef("ledger-service", "ledger-db", "database", True),
    DependencyDef("settlement-worker", "settlement-events", "async_queue", True),
    DependencyDef("settlement-worker", "ledger-service", "sync_http", True),
)

METRIC_UNITS: dict[str, str] = {
    "http_requests_per_min": "requests/min",
    "http_5xx_ratio": "ratio",
    "p95_latency_ms": "ms",
    "db_pool_in_use": "connections",
    "queue_depth": "messages",
    "events_processed_per_min": "events/min",
}

SERVICE_METRICS: dict[str, tuple[str, ...]] = {
    "transaction-api": ("http_requests_per_min", "http_5xx_ratio", "p95_latency_ms"),
    "ledger-service": ("http_requests_per_min", "http_5xx_ratio", "p95_latency_ms", "db_pool_in_use"),
    "settlement-worker": ("queue_depth", "events_processed_per_min", "http_5xx_ratio"),
}
