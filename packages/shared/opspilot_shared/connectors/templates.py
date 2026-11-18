"""Approved query templates (v0.6).

Users choose templates by ID; they never type LogQL or PromQL. Built-in templates follow common conventions
(``http_requests_total`` with a ``status`` label, ``http_request_duration_seconds`` histograms). An operator can add
or override templates in a JSON file named by ``TELEMETRY_TEMPLATES_FILE``::

    {"templates": [{"id": "db_pool_in_use", "connector": "prometheus", "label": "DB pool in use",
                    "query": "max(db_pool_connections_in_use{$selector})", "metric": "db_pool_in_use",
                    "unit": "connections"}]}

Placeholders: ``$selector`` (required) becomes ``<service label>="<service>"``; ``$rate`` (PromQL only) becomes a
range at least four steps long, e.g. ``5m``. Metric names that match the agent's known names (``http_5xx_ratio``,
``p95_latency_ms``, ``db_pool_in_use``, …) are examined first by the investigation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from opspilot_shared.connectors.contract import ConnectorError, ConnectorKind, QueryTemplate

_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")  # ServiceName: no quote, backslash or brace can reach a query

BUILT_IN: tuple[QueryTemplate, ...] = (
    QueryTemplate(
        id="errors_warnings",
        connector="loki",
        label="Errors and warnings",
        description="Lines mentioning errors, warnings, exceptions, timeouts or failures",
        query='{$selector} |~ "(?i)(error|warn|exception|fail|timeout|refused|unavailable|panic|fatal)"',
    ),
    QueryTemplate(
        id="lifecycle",
        connector="loki",
        label="Start-up, shutdown and config lines",
        description="Lines about starting, stopping, versions, deployments and configuration (to spot changes)",
        query='{$selector} |~ "(?i)(starting|started|shutting down|shutdown|version|deploy|rollout|config|restart)"',
    ),
    QueryTemplate(
        id="all_lines",
        connector="loki",
        label="All log lines",
        description="Every line of the service (most recent first, up to the line limit)",
        query="{$selector}",
        default=False,
    ),
    QueryTemplate(
        id="http_5xx_ratio",
        connector="prometheus",
        label="HTTP 5xx ratio",
        description="Share of requests answered with a 5xx status (http_requests_total by status)",
        query='sum(rate(http_requests_total{$selector,status=~"5.."}[$rate]))'
        " / sum(rate(http_requests_total{$selector}[$rate]))",
        metric="http_5xx_ratio",
        unit="ratio",
    ),
    QueryTemplate(
        id="p95_latency_ms",
        connector="prometheus",
        label="p95 latency",
        description="95th percentile request latency from http_request_duration_seconds buckets",
        query="histogram_quantile(0.95, sum by (le) "
        "(rate(http_request_duration_seconds_bucket{$selector}[$rate]))) * 1000",
        metric="p95_latency_ms",
        unit="ms",
    ),
    QueryTemplate(
        id="http_requests_per_min",
        connector="prometheus",
        label="Request rate",
        description="Requests per minute (http_requests_total)",
        query="sum(rate(http_requests_total{$selector}[$rate])) * 60",
        metric="http_requests_per_min",
        unit="req/min",
    ),
)


def load_templates(path: Path | None) -> tuple[list[QueryTemplate], list[str]]:
    """Built-in templates with the file's additions/overrides applied, and problems found in the file."""
    by_key: dict[tuple[ConnectorKind, str], QueryTemplate] = {(t.connector, t.id): t for t in BUILT_IN}
    problems: list[str] = []
    if path is not None:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            items = doc.get("templates") if isinstance(doc, dict) else None
            if not isinstance(items, list):
                raise ValueError('expected {"templates": [...]}')
        except (OSError, ValueError) as exc:
            problems.append(f"templates file not used: {exc}")
            items = []
        for i, raw in enumerate(items[:50]):
            try:
                t = QueryTemplate.model_validate({**raw, "source": "file"}) if isinstance(raw, dict) else None
                if t is None:
                    raise ValueError("not an object")
                check_template(t)
            except (ValidationError, ValueError) as exc:
                problems.append(f"template {i + 1} ignored: {str(exc).splitlines()[0][:160]}")
                continue
            by_key[(t.connector, t.id)] = t
    return list(by_key.values()), problems


def check_template(t: QueryTemplate) -> None:
    if "$selector" not in t.query:
        raise ValueError(f"{t.id}: the query must contain $selector so it is scoped to one service")
    if t.connector == "loki":
        if not t.query.lstrip().startswith("{$selector"):
            raise ValueError(f"{t.id}: a LogQL template must start with the stream selector {{$selector...}}")
        if "$rate" in t.query:
            raise ValueError(f"{t.id}: $rate is only for PromQL templates")
    elif not t.metric:
        raise ValueError(f"{t.id}: a Prometheus template needs a metric name for its records")


def selector(label: str, service: str) -> str:
    if not _LABEL.match(label):
        raise ConnectorError("not_configured", f"invalid service label name {label!r}")
    if not _SERVICE.match(service):
        raise ConnectorError("invalid_request", "service must be a lower-case slug such as checkout-api")
    return f'{label}="{service}"'


def promql_range(step_seconds: int) -> str:
    seconds = max(300, step_seconds * 4)
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"


def render(t: QueryTemplate, *, label: str, service: str, step_seconds: int | None = None) -> str:
    query = t.query.replace("$selector", selector(label, service))
    if "$rate" in query:
        query = query.replace("$rate", promql_range(step_seconds or 60))
    return query
