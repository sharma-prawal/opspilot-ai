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
    ServiceDef("fx-rates-provider", "external", "vendor:fx-provider", "saas", 0),
)

# Runtime configuration exposed by get_service_config (scenarios may override per environment).
SERVICE_CONFIG: dict[str, dict[str, object]] = {
    "transaction-api": {"http.client.timeout_ms": 2000, "fx.circuit_breaker.failure_ratio": 0.2},
    "ledger-service": {
        "db.datastore": "ledger-db",
        "db.pool.max": 40,
        "db.pool.timeout_ms": 5000,
        "db.statement_timeout_ms": 30000,
    },
    "settlement-worker": {
        "consumer.queue": "settlement-events",
        "consumer.max_retries": 3,
        "consumer.dead_letter_queue": "settlement-events.dlq",
        "batch.max_size": 800,
        "schema.accepted": ["settlement-event.v3"],
    },
    "fx-rates-provider": {"sla.p95_ms": 300},
}

DATASTORES: dict[str, dict[str, object]] = {
    "ledger-db": {
        "engine": "postgresql",
        "max_connections": 200,
        "reserved_superuser_connections": 3,
        "owner_service": "ledger-service",
    },
}
QUEUES: dict[str, dict[str, object]] = {
    "settlement-events": {
        "producers": ["transaction-api"],
        "consumer": "settlement-worker",
        "dead_letter_queue": "settlement-events.dlq",
        "schema": "settlement-event.v3",
    },
}

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
    "db_pool_max": "connections",
    "db_pool_wait_ms": "ms",
    "dlq_depth": "messages",
    "validation_failures_per_min": "messages/min",
    "consumer_retries_per_min": "attempts/min",
    "connections_active": "connections",
}

SERVICE_METRICS: dict[str, tuple[str, ...]] = {
    "transaction-api": ("http_requests_per_min", "http_5xx_ratio", "p95_latency_ms"),
    "ledger-service": ("http_requests_per_min", "http_5xx_ratio", "p95_latency_ms", "db_pool_in_use"),
    "settlement-worker": ("queue_depth", "events_processed_per_min", "http_5xx_ratio"),
    "fx-rates-provider": ("p95_latency_ms", "http_5xx_ratio"),
}
