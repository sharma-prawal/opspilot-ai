"""MCP **read** server: observability, change and knowledge tools. No tool here changes state."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AwareDatetime, Field

from opspilot_mcp.backend import OpsBackend
from opspilot_mcp.schemas import (
    ConfigChangeList,
    DatastoreStatus,
    DeploymentList,
    IncidentView,
    KnowledgeHits,
    MetricCatalog,
    MetricInfo,
    QueueStatus,
    ServiceConfigView,
)
from opspilot_shared.db.models import OpsIncident
from opspilot_shared.domain.knowledge import DocType, RetrievalFilters
from opspilot_shared.domain.telemetry import (
    DependencyGraph,
    LogLevel,
    LogSearchResult,
    MetricSeries,
    ServiceHealth,
)
from opspilot_shared.errors import OpsPilotError

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
READ_TOOLS = frozenset(
    {
        "list_service_metrics",
        "get_service_config",
        "get_datastore_status",
        "inspect_queue",
        "get_incident",
        "search_logs",
        "query_metrics",
        "get_service_health",
        "list_recent_deployments",
        "get_config_changes",
        "get_service_dependencies",
        "search_runbooks",
        "get_historical_incidents",
    }
)

Service = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$", description="Service name, e.g. transaction-api")]
EnvId = Annotated[uuid.UUID, Field(description="Environment ID from the incident record")]
Query = Annotated[str, Field(min_length=3, max_length=500)]
TopK = Annotated[int, Field(ge=1, le=10)]
ExpandSections = Annotated[int, Field(ge=0, le=4, description="extra sections of the top current runbook (0-4)")]


async def _guard[T](fn: Callable[[], Awaitable[T]]) -> T:
    """Map domain errors to MCP tool errors (is_error=True with a readable message)."""
    try:
        return await fn()
    except OpsPilotError as exc:
        raise ToolError(f"{exc.error_class}: {exc}") from exc


def build_read_server(backend: OpsBackend) -> MCPServer:
    mcp = MCPServer(
        "opspilot-ops-read",
        version="0.1.0",
        instructions=(
            "Read-only operational tools for the OpsPilot sandbox environment. Times are ISO-8601 with "
            "timezone. Windows are limited to 24h."
        ),
    )
    store = backend.store

    @mcp.tool(title="Get incident", annotations=READ_ONLY)
    async def get_incident(incident_id: uuid.UUID) -> IncidentView:
        """Fetch an incident record (title, severity, affected service, environment, detection time)."""

        async def run() -> IncidentView:
            async with backend.session_factory() as s:
                row = await s.get(OpsIncident, incident_id)
            if row is None:
                raise ToolError(f"not_found: incident {incident_id}")
            return IncidentView(
                id=row.id,
                reference=row.reference,
                title=row.title,
                description=row.description,
                severity=row.severity,
                status=row.status,
                service=row.service,
                environment_id=row.environment_id,
                detected_at=row.detected_at,
            )

        return await _guard(run)

    @mcp.tool(title="Search logs", annotations=READ_ONLY)
    async def search_logs(
        environment_id: EnvId,
        service: Service,
        start: AwareDatetime,
        end: AwareDatetime,
        min_level: LogLevel = LogLevel.WARN,
        contains: Annotated[str | None, Field(max_length=200)] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> LogSearchResult:
        """Search a service's logs in a time window, newest first, filtered by minimum level and terms."""
        return await _guard(
            lambda: store.search_logs(
                environment_id,
                service=service,
                start=start,
                end=end,
                min_level=min_level,
                contains=contains,
                limit=limit,
            )
        )

    @mcp.tool(title="Query metrics", annotations=READ_ONLY)
    async def query_metrics(
        environment_id: EnvId,
        service: Service,
        metric: Annotated[str, Field(pattern=r"^[a-z0-9_]{2,63}$")],
        start: AwareDatetime,
        end: AwareDatetime,
    ) -> MetricSeries:
        """Per-minute metric series, e.g. http_5xx_ratio, p95_latency_ms, http_requests_per_min,
        db_pool_in_use, queue_depth, events_processed_per_min."""
        return await _guard(
            lambda: store.query_metrics(environment_id, service=service, metric=metric, start=start, end=end)
        )

    @mcp.tool(title="Service health", annotations=READ_ONLY)
    async def get_service_health(environment_id: EnvId, service: Service) -> ServiceHealth:
        """Current health of a service, from the last 5 minutes of metrics."""
        return await _guard(lambda: store.service_health(environment_id, service))

    @mcp.tool(title="List service metrics", annotations=READ_ONLY)
    async def list_service_metrics(environment_id: EnvId, service: Service) -> MetricCatalog:
        """Metric names (and units) available for a service in this environment."""

        async def run() -> MetricCatalog:
            rows = await store.list_metrics(environment_id, service)
            return MetricCatalog(service=service, metrics=[MetricInfo(**r) for r in rows])

        return await _guard(run)

    @mcp.tool(title="Service configuration", annotations=READ_ONLY)
    async def get_service_config(environment_id: EnvId, service: Service) -> ServiceConfigView:
        """Current runtime configuration of a service: replicas, pool sizes, timeouts, consumer settings."""

        async def run() -> ServiceConfigView:
            return ServiceConfigView(**await store.service_config(environment_id, service))

        return await _guard(run)

    @mcp.tool(title="Datastore status", annotations=READ_ONLY)
    async def get_datastore_status(environment_id: EnvId, datastore: Service) -> DatastoreStatus:
        """Connection capacity and usage of a datastore (max/active connections by client, long-running queries)."""

        async def run() -> DatastoreStatus:
            return DatastoreStatus(**await store.datastore_status(environment_id, datastore))

        return await _guard(run)

    @mcp.tool(title="Inspect queue", annotations=READ_ONLY)
    async def inspect_queue(environment_id: EnvId, queue: Service) -> QueueStatus:
        """Queue state: pending/dead-lettered/quarantined counts, consumer state, validation failures by producer."""

        async def run() -> QueueStatus:
            return QueueStatus(**await store.inspect_queue(environment_id, queue))

        return await _guard(run)

    @mcp.tool(title="Recent deployments", annotations=READ_ONLY)
    async def list_recent_deployments(
        environment_id: EnvId, start: AwareDatetime, end: AwareDatetime, service: Service | None = None
    ) -> DeploymentList:
        """Deployments (application, schema_migration, rollback) started within the window."""

        async def run() -> DeploymentList:
            return DeploymentList(
                deployments=await store.list_deployments(environment_id, start=start, end=end, service=service)
            )

        return await _guard(run)

    @mcp.tool(title="Configuration changes", annotations=READ_ONLY)
    async def get_config_changes(
        environment_id: EnvId, start: AwareDatetime, end: AwareDatetime, service: Service | None = None
    ) -> ConfigChangeList:
        """Runtime configuration changes within the window."""

        async def run() -> ConfigChangeList:
            return ConfigChangeList(
                changes=await store.config_changes(environment_id, start=start, end=end, service=service)
            )

        return await _guard(run)

    @mcp.tool(title="Service dependencies", annotations=READ_ONLY)
    async def get_service_dependencies(environment_id: EnvId, service: Service) -> DependencyGraph:
        """Upstream and downstream dependencies of a service, with criticality."""
        return await _guard(lambda: store.dependencies(environment_id, service))

    async def _search(
        query: str, top_k: int, filters: RetrievalFilters, caller: str, expand_sections: int = 0
    ) -> KnowledgeHits:
        # C0-G3: agent-facing search is normal incident investigation, never historical analysis: superseded or
        # withdrawn documents are not candidates, and the response is lifecycle-validated before it is returned.
        resp = await backend.retriever.search(
            query,
            top_k=top_k,
            filters=filters,
            caller=caller,
            expand_sections=expand_sections,
            exclude_obsolete=True,
        )
        return KnowledgeHits(
            query_id=resp.query_id,
            query=resp.query,
            results=resp.results,
            mode=resp.mode.value,
            effective_mode=(resp.effective_mode or resp.mode).value,
            warnings=resp.warnings,
            context=resp.context,
        )

    @mcp.tool(title="Search runbooks and docs", annotations=READ_ONLY)
    async def search_runbooks(
        query: Query,
        top_k: TopK = 5,
        doc_types: list[DocType] | None = None,
        services: list[Service] | None = None,
        expand_sections: ExpandSections = 0,
    ) -> KnowledgeHits:
        """Hybrid (vector + keyword) search over runbooks, architecture, policies and error codes.

        ``expand_sections`` (0-4) also returns up to that many further sections of the top-ranked current runbook
        or troubleshooting document (same version) in ``context``."""
        types = doc_types or [d for d in DocType if d is not DocType.INCIDENT_REPORT]
        return await _guard(
            lambda: _search(
                query,
                top_k,
                RetrievalFilters(doc_types=types, services=services),
                "mcp.search_runbooks",
                expand_sections,
            )
        )

    @mcp.tool(title="Historical incidents", annotations=READ_ONLY)
    async def get_historical_incidents(query: Query, top_k: TopK = 3) -> KnowledgeHits:
        """Hybrid search over past incident postmortems."""
        return await _guard(
            lambda: _search(
                query, top_k, RetrievalFilters(doc_types=[DocType.INCIDENT_REPORT]), "mcp.get_historical_incidents"
            )
        )

    _ = datetime  # keep import for type evaluation of annotations
    return mcp
