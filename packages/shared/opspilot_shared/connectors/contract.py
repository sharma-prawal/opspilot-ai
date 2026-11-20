"""The contract every telemetry connector implements (v0.6; multi-signal providers since v0.9).

A connector turns one *approved query template* for one *service* and one bounded *time window* into normalized
evidence records (``LogRecord`` / ``MetricRecord`` / ``SpanRecord`` from ``opspilot_shared.uploads.model``) plus a
provenance entry
describing exactly what was asked and what came back. That is the whole surface: connectors never accept a free-form
query, URL or path from a caller, never write to the backend, and report failures as typed ``ConnectorError``s.

A connector serves one signal (Loki: logs, Prometheus: metrics) or several (Datadog: logs, metrics and APM spans);
each template names the signal it returns. To add a provider (Azure Monitor, CloudWatch, a custom store), implement
``TelemetryConnector`` and register
it in ``opspilot_shared.connectors.registry``; see docs/integrations/CONNECTORS.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from opspilot_shared.uploads.model import LogRecord, MetricRecord, SpanRecord

ConnectorKind = Literal["loki", "prometheus", "datadog"]
Signal = Literal["log", "metric", "span"]
ErrorKind = Literal[
    "not_configured",  # the connector is not set up (no URL) or its configuration is invalid
    "auth_error",  # 401/403 or a missing tenant: check the read-only credentials
    "permission_denied",  # v0.9: credentials accepted but not allowed to read this product (Datadog 403)
    "unsupported",  # v0.9: the product/API is not available for this account or site
    "unavailable",  # connection refused, DNS failure or a 5xx answer
    "timeout",  # no answer within TELEMETRY_TIMEOUT_SECONDS
    "redirect_refused",  # the backend answered with a redirect; OpsPilot never follows one
    "rate_limited",  # 429
    "not_found",  # 404: wrong base URL or path prefix
    "query_error",  # the backend rejected the query (400/422), e.g. a template that does not fit its schema
    "response_too_large",  # the answer exceeded TELEMETRY_MAX_RESPONSE_BYTES
    "invalid_response",  # not the JSON shape the official API documents
    "invalid_request",  # window, service or template outside the allowed limits
]


class ConnectorError(Exception):
    """A typed, credential-free connector failure."""

    def __init__(self, kind: ErrorKind, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message
        self.status = status  # HTTP status that caused it, when there was one

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


class QueryTemplate(BaseModel):
    """An operator-approved query. ``$selector`` becomes ``<service label>="<service>"`` (Datadog:
    ``service:<service>``)
    and ``$rate`` a PromQL range such as ``5m``; nothing else from a request ever reaches the query text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    connector: ConnectorKind
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    query: str = Field(min_length=3, max_length=2000)
    metric: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,63}$", description="record name (metric templates)")
    unit: str = Field(default="", max_length=20, description="unit of the query result (metric templates)")
    signal: Signal | None = Field(default=None, description="v0.9: what the template returns (required for Datadog)")
    expand_traces: int = Field(
        default=0, ge=0, le=20, description="v0.9 span templates: also fetch the other spans of up to N matched traces"
    )
    default: bool = True
    source: Literal["built-in", "file"] = "built-in"

    @property
    def returns(self) -> Signal:
        """The signal of the records this template produces."""
        if self.signal is not None:
            return self.signal
        return "log" if self.connector == "loki" else "metric"


class FetchWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: datetime
    end: datetime


class QueryProvenance(BaseModel):
    """What was asked, of whom, and what came back. Stored with the snapshot and shown in previews and reports."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(description="<connector>/<template>/<service>; prefix of every record's source reference")
    connector: ConnectorKind
    connector_name: str
    signal: Signal | None = Field(default=None, description="v0.9: signal of the records (None in v0.6 snapshots)")
    endpoint: str = Field(description="API path that was called, e.g. /api/v1/query_range")
    template: str
    template_label: str
    service: str
    query: str
    start: datetime
    end: datetime
    step_seconds: int | None = None
    limit: int | None = None
    status: Literal["ok", "empty", "error"]
    error: dict[str, str] | None = None
    returned: int = 0
    rejected: int = 0
    redactions: int = 0
    truncated: bool = False
    series: int | None = None
    unit: str = ""
    fetched_at: datetime
    duration_ms: float = 0.0
    issues: list[str] = Field(default_factory=list)
    site: str | None = Field(default=None, description="v0.9: provider site/region, e.g. datadoghq.eu")
    link: str | None = Field(default=None, description="v0.9: credential-free link to the query in the provider UI")
    pages: int | None = Field(default=None, description="v0.9: result pages fetched (paginated APIs)")

    @property
    def returns(self) -> Signal:
        if self.signal is not None:
            return self.signal
        return "log" if self.connector == "loki" else "metric"


class FetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: QueryProvenance
    logs: list[LogRecord] = Field(default_factory=list)
    metrics: list[MetricRecord] = Field(default_factory=list)
    spans: list[SpanRecord] = Field(default_factory=list)


class SignalStatus(BaseModel):
    """v0.9: whether one product of a multi-signal provider can be read with the configured credentials."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "permission_denied", "unsupported", "rate_limited", "unavailable", "error"]
    message: str


class ConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector: str
    status: Literal["ok", "partial", "not_configured", "auth_error", "rate_limited", "unavailable", "error"]
    message: str
    version: str | None = None
    latency_ms: float | None = None
    checked_at: datetime
    signals: dict[str, SignalStatus] | None = None  # v0.9 multi-signal providers: per-product read probe


@runtime_checkable
class TelemetryConnector(Protocol):
    """Read-only access to one configured observability backend."""

    @property
    def id(self) -> str: ...  # stable identifier used in requests: "loki", "prometheus", "datadog"

    @property
    def kind(self) -> ConnectorKind: ...

    @property
    def signal(self) -> Signal: ...  # primary signal (the only one for Loki and Prometheus)

    @property
    def signals(self) -> tuple[Signal, ...]: ...  # every signal its templates can return

    def info(self) -> dict[str, Any]:
        """Display-safe description: name, kind, signal, endpoint without credentials, auth mode, service label,
        templates and limits. Never contains a secret."""
        ...

    def templates(self) -> list[QueryTemplate]: ...

    async def test(self) -> ConnectionStatus:
        """One cheap read (build info / readiness) that distinguishes ok, auth error and unavailable; multi-signal
        providers also probe each product (``ConnectionStatus.signals``)."""
        ...

    async def services(self, window: FetchWindow) -> list[str]:
        """Values of the configured service label (Datadog: ``service`` facet) seen in the window, bounded."""
        ...

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        """Run one template for one service and window; never raises for backend failures (they are recorded in
        ``provenance.status``/``error``), only for an invalid request (``ConnectorError('invalid_request')``)."""
        ...
