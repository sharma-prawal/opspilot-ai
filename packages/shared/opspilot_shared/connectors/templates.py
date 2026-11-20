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

Datadog templates (v0.9) name their ``signal`` (``log``, ``metric`` or ``span``). ``$selector`` becomes
``service:<service>`` (plus ``env:<DATADOG_ENV>`` when set), written with a space in log/span search syntax and a
comma inside a metric scope. A Datadog metric template is either one metrics query (``avg:system.cpu.user{$selector}``)
or named queries and a formula, separated by semicolons::

    a = sum:trace.http.request.errors{$selector}.as_count(); b = sum:trace.http.request.hits{$selector}.as_count();
    a / b

which becomes the ``queries`` and ``formulas`` of one ``POST /api/v2/query/timeseries`` request.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from opspilot_shared.connectors.contract import ConnectorError, ConnectorKind, QueryTemplate

_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")  # Loki/Prometheus: no quote, backslash or brace can reach a query
# v0.9 Datadog service tag values: lower-case letters, digits, '.', '_' and '-' (Datadog lowercases span and metric
# tags;
# ':' and '/' are allowed by Datadog but excluded here because they would break source references). Search values are
# additionally escaped with ``dd_escape``.
DD_SERVICE = re.compile(r"^[a-z][a-z0-9._-]{1,62}$")
# Characters Datadog's search syntax treats as special (docs: logs/explorer/search_syntax), escaped with a backslash.
_DD_SPECIAL = set('+-=&|><!(){}[]^"\u201c\u201d~*?:\\/ ')


def dd_escape(value: str) -> str:
    """A value as a literal term in Datadog log/span search syntax: every documented special character escaped."""
    return "".join(f"\\{c}" if c in _DD_SPECIAL else c for c in value)


def dd_service_value(raw: object) -> str | None:
    """A Datadog service name exactly as returned (never rewritten into another name), or None if not usable."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value if DD_SERVICE.match(value) else None


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
    # ---- Datadog (v0.9). APM trace metrics use the span name of the service's integration; ``trace.http.request``
    # is the generic web-server name. Override these in TELEMETRY_TEMPLATES_FILE for other span names
    # (trace.flask.request, trace.express.request, trace.servlet.request, ...).
    QueryTemplate(
        id="errors_warnings",
        connector="datadog",
        signal="log",
        label="Error and warning logs",
        description="Logs with status error, warn, critical, alert or emergency",
        query="$selector status:(error OR warn OR critical OR alert OR emergency)",
    ),
    QueryTemplate(
        id="lifecycle",
        connector="datadog",
        signal="log",
        label="Start-up, shutdown and config logs",
        description="Logs mentioning starting, stopping, versions, deployments or configuration (to spot changes)",
        query="$selector (starting OR started OR shutdown OR version OR deploy OR rollout OR config OR restart)",
    ),
    QueryTemplate(
        id="all_logs",
        connector="datadog",
        signal="log",
        label="All logs",
        description="Every indexed log of the service (most recent first, up to the line limit)",
        query="$selector",
        default=False,
    ),
    QueryTemplate(
        id="http_5xx_ratio",
        connector="datadog",
        signal="metric",
        label="HTTP 5xx ratio (APM)",
        description="Share of trace.http.request hits answered with a 5xx status (trace metrics by http.status_class)",
        query="a = sum:trace.http.request.hits.by_http_status{$selector,http.status_class:5xx}.as_count(); "
        "b = sum:trace.http.request.hits{$selector}.as_count(); a / b",
        metric="http_5xx_ratio",
        unit="ratio",
    ),
    QueryTemplate(
        id="trace_error_ratio",
        connector="datadog",
        signal="metric",
        label="Trace error ratio (APM)",
        description="Share of trace.http.request hits flagged as errors by the tracer",
        query="a = sum:trace.http.request.errors{$selector}.as_count(); "
        "b = sum:trace.http.request.hits{$selector}.as_count(); a / b",
        metric="trace_error_ratio",
        unit="ratio",
    ),
    QueryTemplate(
        id="p95_latency_ms",
        connector="datadog",
        signal="metric",
        label="p95 latency (APM)",
        description="95th percentile of the trace.http.request distribution (seconds) in milliseconds",
        query="a = p95:trace.http.request{$selector}; a * 1000",
        metric="p95_latency_ms",
        unit="ms",
    ),
    QueryTemplate(
        id="http_requests_per_min",
        connector="datadog",
        signal="metric",
        label="Request rate (APM)",
        description="trace.http.request hits per minute",
        query="a = sum:trace.http.request.hits{$selector}.as_rate(); a * 60",
        metric="http_requests_per_min",
        unit="req/min",
    ),
    QueryTemplate(
        id="cpu_user_pct",
        connector="datadog",
        signal="metric",
        label="CPU user time (host)",
        description="avg system.cpu.user of hosts tagged with the service (needs unified service tagging on hosts)",
        query="avg:system.cpu.user{$selector}",
        metric="cpu_user_pct",
        unit="percent",
        default=False,
    ),
    QueryTemplate(
        id="error_spans",
        connector="datadog",
        signal="span",
        label="Error spans and their traces (APM)",
        description="Indexed spans of the service with status:error, plus the other indexed spans of up to 10 of "
        "those traces (to see which dependency failed)",
        query="$selector status:error",
        expand_traces=10,
    ),
    QueryTemplate(
        id="service_spans",
        connector="datadog",
        signal="span",
        label="All indexed spans (APM)",
        description="Most recent indexed spans of the service, errors or not (a sample: retention filters apply)",
        query="$selector",
        default=False,
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


_DD_NAME = re.compile(r"^[a-z]$")
_DD_FORMULA = re.compile(r"^[a-z0-9 .()+\-*/]{1,200}$")
_DD_SCOPED = re.compile(r"\{\$selector[,}]")


def datadog_metric_parts(query: str) -> tuple[list[tuple[str, str]], str]:
    """Named metrics queries and the formula of a Datadog metric template (see the module docstring)."""
    parts = [p.strip() for p in query.split(";") if p.strip()]
    if len(parts) == 1:
        return [("a", parts[0])], "a"
    *named, formula = parts
    queries: list[tuple[str, str]] = []
    for item in named:
        name, sep, q = item.partition("=")
        name, q = name.strip(), q.strip()
        if not sep or not _DD_NAME.match(name) or not q:
            raise ValueError(f"expected '<letter> = <metrics query>', got {item[:40]!r}")
        queries.append((name, q))
    names = [n for n, _ in queries]
    if len(set(names)) != len(names) or len(queries) > 4:
        raise ValueError("query names must be unique (at most 4 queries)")
    if not _DD_FORMULA.match(formula) or "=" in formula:
        raise ValueError(f"invalid formula {formula[:40]!r}: use query names, numbers and + - * / ( )")
    used = set(re.findall(r"\b[a-z]\b", formula))
    if not used or not used <= set(names):
        raise ValueError(f"the formula {formula[:40]!r} must use only the named queries {names}")
    return queries, formula


def _check_datadog(t: QueryTemplate) -> None:
    if t.signal is None:
        raise ValueError(f"{t.id}: a Datadog template must name its signal (log, metric or span)")
    if "$rate" in t.query:
        raise ValueError(f"{t.id}: $rate is only for PromQL templates")
    if t.expand_traces and t.signal != "span":
        raise ValueError(f"{t.id}: expand_traces is only for span templates")
    if t.signal in ("log", "span"):
        if not t.query.lstrip().startswith("$selector"):
            raise ValueError(f"{t.id}: a Datadog log/span template must start with $selector")
        if ";" in t.query or "{" in t.query:
            raise ValueError(f"{t.id}: a Datadog log/span template is one search query")
        return
    if not t.metric:
        raise ValueError(f"{t.id}: a Datadog metric template needs a metric name for its records")
    queries, _ = datadog_metric_parts(t.query)
    for name, q in queries:
        if not _DD_SCOPED.search(q):
            raise ValueError(f"{t.id}: query {name} must be scoped with {{$selector...}}")


def check_template(t: QueryTemplate) -> None:
    if "$selector" not in t.query:
        raise ValueError(f"{t.id}: the query must contain $selector so it is scoped to one service")
    if t.connector == "datadog":
        _check_datadog(t)
        return
    native = "log" if t.connector == "loki" else "metric"
    if t.expand_traces or (t.signal is not None and t.signal != native):
        raise ValueError(f"{t.id}: a {t.connector} template returns only {native}s")
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
