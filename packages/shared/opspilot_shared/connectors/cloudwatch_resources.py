"""AWS CloudWatch resource mapping and approved templates (v0.11).

CloudWatch has no universal "service" field: log events belong to log groups and metrics to resource dimensions
(a Lambda function, a load balancer target group, an ECS service). OpsPilot therefore never infers which resources
belong to a service. The operator states it in ``CLOUDWATCH_RESOURCES_FILE`` (YAML)::

    services:
      inventory-service:                     # OpsPilot service name ([a-z][a-z0-9._-]{1,62}), kept exactly
        log_groups:                          # the approved log groups of this service (≤ 10); nothing else is queried
          - /ecs/shop-prod/inventory-service
        service_field: service               # optional: structured field that names the service when a log group is
                                             # shared by several services (queries add  | filter `service` = "<name>")
        metrics:                             # optional resource identities (exact CloudWatch dimension values)
          ecs: {cluster: shop-prod, service: inventory-service}
          alb: {load_balancer: app/shop-prod-alb/50dc6c495c0c9188, target_group: targetgroup/inventory/943f017f100becff}
          lambda: {function_name: inventory-reconciler}
          custom:                            # ≤ 10 explicitly configured custom metrics
            - {id: db_pool_wait_ms, namespace: Shop/Inventory, metric_name: DbPoolWaitTime, stat: p95,
               unit: Milliseconds, dimensions: {Service: inventory-service}}

That file is the allowlist: every log group named in it is approved and no other log group, namespace or dimension can
be reached. The built-in templates below are the only queries: Logs Insights QL text with fixed regular expressions
(``$limit``, ``$bin`` and the optional service filter are the only substitutions, from validated values) and
GetMetricData metric definitions whose dimension values come from the mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from opspilot_shared.connectors.contract import ConnectorError, QueryTemplate
from opspilot_shared.connectors.templates import DD_SERVICE

MAX_SERVICES = 25
MAX_LOG_GROUPS_PER_SERVICE = 10  # StartQuery accepts 50; OpsPilot keeps scans narrow
MAX_LOG_GROUPS = 50
MAX_CUSTOM_METRICS = 10
MAX_DIMENSIONS = 10

LOG_GROUP = re.compile(r"^[\.\-_/#A-Za-z0-9]{1,512}$")  # botocore LogGroupName pattern
_FIELD = re.compile(r"^[A-Za-z_@][A-Za-z0-9_.@-]{0,63}$")
_ECS_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:-]{0,254}$")
_LAMBDA_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALB = re.compile(r"^app/[A-Za-z0-9-]{1,32}/[0-9a-f]{16}$")
_TARGET_GROUP = re.compile(r"^targetgroup/[A-Za-z0-9-]{1,32}/[0-9a-f]{16}$")
_NAMESPACE = re.compile(r"^[A-Za-z0-9._/#:-]{1,255}$")
_METRIC_NAME = re.compile(r"^[A-Za-z0-9._/#:@ -]{1,255}$")
_DIM_NAME = re.compile(r"^[A-Za-z0-9._/#:@ -]{1,255}$")
_DIM_VALUE = re.compile(r"^[^\x00-\x1f\x7f]{1,1024}$")
_METRIC_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
STAT = re.compile(r"^(Sum|Average|Minimum|Maximum|SampleCount|p\d{1,2}(\.\d{1,2})?)$")
_SIZES = ("Bytes", "Kilobytes", "Megabytes", "Gigabytes", "Terabytes", "Bits", "Kilobits", "Megabits", "Gigabits",
          "Terabits")  # fmt: skip
UNITS = frozenset(
    ["Seconds", "Microseconds", "Milliseconds", "Percent", "Count", "Count/Second", "None", *_SIZES]
    + [f"{u}/Second" for u in _SIZES]
)

ResourceKind = Literal["logs", "lambda", "alb", "ecs", "custom"]


@dataclass(frozen=True)
class MetricDef:
    """One GetMetricData metric: namespace, name, statistic, the unit AWS documents for it, and how the dimensions
    are taken from a service's mapping."""

    template: str
    kind: ResourceKind
    namespace: str
    metric_name: str
    stat: str
    unit: str
    record: str  # OpsPilot metric record name
    dimensions: tuple[tuple[str, str], ...]  # (CloudWatch dimension name, mapping key)


@dataclass(frozen=True)
class CustomMetric:
    id: str
    namespace: str
    metric_name: str
    stat: str
    unit: str
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ServiceResources:
    name: str
    log_groups: tuple[str, ...] = ()
    service_field: str | None = None
    lambda_function: str | None = None
    alb: tuple[str, str] | None = None  # (LoadBalancer, TargetGroup)
    ecs: tuple[str, str] | None = None  # (ClusterName, ServiceName)
    custom: tuple[CustomMetric, ...] = ()

    def has(self, kind: ResourceKind) -> bool:
        return bool(
            {
                "logs": self.log_groups,
                "lambda": self.lambda_function,
                "alb": self.alb,
                "ecs": self.ecs,
                "custom": self.custom,
            }[kind]
        )

    def dimension_value(self, key: str) -> str | None:
        return {
            "function_name": self.lambda_function,
            "load_balancer": self.alb[0] if self.alb else None,
            "target_group": self.alb[1] if self.alb else None,
            "cluster": self.ecs[0] if self.ecs else None,
            "ecs_service": self.ecs[1] if self.ecs else None,
        }.get(key)


@dataclass
class ResourceMap:
    services: dict[str, ServiceResources] = field(default_factory=dict)

    @property
    def log_groups(self) -> list[str]:
        return sorted({g for s in self.services.values() for g in s.log_groups})

    def get(self, service: str) -> ServiceResources | None:
        return self.services.get(service)

    def kinds(self) -> set[ResourceKind]:
        return {k for s in self.services.values() for k in ("logs", "lambda", "alb", "ecs", "custom") if s.has(k)}  # type: ignore[misc]


# ------------------------------------------------------------------------------------------------ templates
LOG_FIELDS = (
    "fields @timestamp, @message, @logStream, @log, @requestId, requestId, request_id, traceId, trace_id, "
    "correlationId, correlation_id"
)
_LOG_TAIL = "| sort @timestamp desc\n| limit $limit"


def _logs(tid: str, label: str, description: str, pattern: str, *, default: bool, extra: str = "") -> QueryTemplate:
    query = f"{LOG_FIELDS}\n$service_filter\n| filter @message like /{pattern}/\n{extra}{_LOG_TAIL}"
    return QueryTemplate(
        id=tid, connector="cloudwatch", label=label, description=description, query=query, signal="log",
        default=default,
    )  # fmt: skip


ERROR_PATTERN = r"(?i)(error|exception|fatal|panic|traceback|critical)"
LOG_TEMPLATES: tuple[QueryTemplate, ...] = (
    _logs(
        "cw_errors",
        "Recent errors and exceptions",
        "Most recent log events whose message mentions an error, exception, fatal, panic, traceback or critical.",
        ERROR_PATTERN,
        default=True,
    ),
    _logs(
        "cw_warnings",
        "Warning and error chronology",
        "Most recent warning, error and timeout events (wider than errors only; scans the same groups).",
        r"(?i)(warn|error|exception|fatal|critical|timeout|timed out)",
        default=False,
    ),
    _logs(
        "cw_timeouts",
        "Timeouts and dependency failures",
        "Timeouts, refused or reset connections, exhausted pools and unavailable dependencies.",
        r"(?i)(timeout|timed out|deadline exceeded|connection refused|connection reset|econnrefused|etimedout|"
        r"pool exhausted|too many connections|unable to acquire|could not connect|unavailable|circuit breaker)",
        default=True,
    ),
    _logs(
        "cw_lifecycle",
        "Start-up, version and configuration indicators",
        "Start-up, version, build, deployment and configuration lines: observed log indicators, not a verified "
        "change history.",
        r"(?i)(starting|started|startup|start-up|listening on|version|build|commit|deploy|release|config|"
        r"reload|feature flag|migration|shutting down|sigterm)",
        default=True,
    ),
    _logs(
        "cw_correlation",
        "Request correlation evidence",
        "Error, timeout and failure events that carry a request, trace or correlation ID.",
        r"(?i)(error|exception|timeout|fail)",
        default=False,
        extra="| filter ispresent(@requestId) or ispresent(requestId) or ispresent(request_id) or ispresent(traceId) "
        "or ispresent(trace_id) or ispresent(correlationId) or ispresent(correlation_id)\n",
    ),
)
LOG_METRIC_TEMPLATE = QueryTemplate(
    id="cw_log_error_count",
    connector="cloudwatch",
    label="Log-based error count",
    description="Error-like log events per time bin (Logs Insights stats). Bins without matching events are absent, "
    "not zero.",
    query=f"filter @message like /{ERROR_PATTERN}/\n$service_filter\n| stats count(*) as value by bin($bin) as @t",
    metric="log_error_count",
    unit="Count",
    signal="metric",
    default=True,
)

METRIC_DEFS: tuple[MetricDef, ...] = (
    MetricDef("lambda_errors", "lambda", "AWS/Lambda", "Errors", "Sum", "Count", "lambda_errors",
              (("FunctionName", "function_name"),)),
    MetricDef("lambda_invocations", "lambda", "AWS/Lambda", "Invocations", "Sum", "Count", "lambda_invocations",
              (("FunctionName", "function_name"),)),
    MetricDef("lambda_duration_p95", "lambda", "AWS/Lambda", "Duration", "p95", "Milliseconds",
              "lambda_duration_p95_ms", (("FunctionName", "function_name"),)),
    MetricDef("lambda_throttles", "lambda", "AWS/Lambda", "Throttles", "Sum", "Count", "lambda_throttles",
              (("FunctionName", "function_name"),)),
    MetricDef("alb_target_5xx", "alb", "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "Sum", "Count",
              "alb_target_5xx_count", (("LoadBalancer", "load_balancer"), ("TargetGroup", "target_group"))),
    MetricDef("alb_requests", "alb", "AWS/ApplicationELB", "RequestCount", "Sum", "Count", "alb_request_count",
              (("LoadBalancer", "load_balancer"), ("TargetGroup", "target_group"))),
    MetricDef("alb_target_response_p95", "alb", "AWS/ApplicationELB", "TargetResponseTime", "p95", "Seconds",
              "alb_target_response_p95_s", (("LoadBalancer", "load_balancer"), ("TargetGroup", "target_group"))),
    MetricDef("alb_unhealthy_hosts", "alb", "AWS/ApplicationELB", "UnHealthyHostCount", "Maximum", "Count",
              "alb_unhealthy_hosts_max", (("LoadBalancer", "load_balancer"), ("TargetGroup", "target_group"))),
    MetricDef("ecs_cpu", "ecs", "AWS/ECS", "CPUUtilization", "Average", "Percent", "ecs_cpu_utilization_pct",
              (("ClusterName", "cluster"), ("ServiceName", "ecs_service"))),
    MetricDef("ecs_memory", "ecs", "AWS/ECS", "MemoryUtilization", "Average", "Percent",
              "ecs_memory_utilization_pct", (("ClusterName", "cluster"), ("ServiceName", "ecs_service"))),
)  # fmt: skip
_METRIC_LABELS = {
    "lambda_errors": ("Lambda errors (Sum)", True),
    "lambda_invocations": ("Lambda invocations (Sum)", False),
    "lambda_duration_p95": ("Lambda duration p95", True),
    "lambda_throttles": ("Lambda throttles (Sum)", False),
    "alb_target_5xx": ("ALB target 5xx responses (Sum)", True),
    "alb_requests": ("ALB request count (Sum)", False),
    "alb_target_response_p95": ("ALB target response time p95", True),
    "alb_unhealthy_hosts": ("ALB unhealthy targets (Maximum)", False),
    "ecs_cpu": ("ECS service CPU utilization (Average)", True),
    "ecs_memory": ("ECS service memory utilization (Average)", True),
}
METRIC_BY_TEMPLATE = {m.template: m for m in METRIC_DEFS}


def _describe(m: MetricDef) -> str:
    dims = ", ".join(f"{name}=<{key}>" for name, key in m.dimensions)
    return f"{m.namespace} {m.metric_name} {m.stat} by {dims}"


METRIC_TEMPLATES: tuple[QueryTemplate, ...] = tuple(
    QueryTemplate(
        id=m.template,
        connector="cloudwatch",
        label=_METRIC_LABELS[m.template][0],
        description=f"GetMetricData: {_describe(m)} (unit as documented by AWS: {m.unit}).",
        query=f"GetMetricData {_describe(m)}",
        metric=m.record,
        unit=m.unit,
        signal="metric",
        default=_METRIC_LABELS[m.template][1],
    )
    for m in METRIC_DEFS
)
CUSTOM_TEMPLATE = QueryTemplate(
    id="custom_metrics",
    connector="cloudwatch",
    label="Configured custom metrics",
    description="The custom metrics configured for the service in CLOUDWATCH_RESOURCES_FILE (namespace, name, "
    "statistic and exact dimensions).",
    query="GetMetricData <configured custom metrics of the service>",
    signal="metric",
    default=True,
)
TEMPLATE_KIND: dict[str, ResourceKind] = {
    **{t.id: "logs" for t in LOG_TEMPLATES},
    LOG_METRIC_TEMPLATE.id: "logs",
    **{m.template: m.kind for m in METRIC_DEFS},
    CUSTOM_TEMPLATE.id: "custom",
}
ALL_TEMPLATES: tuple[QueryTemplate, ...] = (*LOG_TEMPLATES, LOG_METRIC_TEMPLATE, *METRIC_TEMPLATES, CUSTOM_TEMPLATE)
KIND_LABEL = {
    "logs": "approved log group",
    "lambda": "Lambda function",
    "alb": "load balancer target group",
    "ecs": "ECS service",
    "custom": "custom metric",
}


def logs_string(value: str) -> str:
    """``value`` as a Logs Insights double-quoted string literal (callers validate first; quote and backslash are
    escaped anyway, control characters refused)."""
    if any(ord(c) < 32 for c in value):
        raise ConnectorError("invalid_request", "control characters are not allowed in a Logs Insights literal")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ------------------------------------------------------------------------------------------------ loading
def _str(raw: Any, pattern: re.Pattern[str], what: str) -> str:
    if not isinstance(raw, str) or not pattern.match(raw):
        raise ValueError(f"invalid {what}: {str(raw)[:80]!r}")
    return raw


def _custom(raw: Any, svc: str) -> CustomMetric:
    if not isinstance(raw, dict):
        raise ValueError(f"{svc}: each custom metric must be a mapping")
    unknown = set(raw) - {"id", "namespace", "metric_name", "stat", "unit", "dimensions"}
    if unknown:
        raise ValueError(f"{svc}: unknown custom metric key(s) {', '.join(sorted(unknown))}")
    ns = _str(raw.get("namespace"), _NAMESPACE, f"{svc} custom metric namespace")
    if ns.upper().startswith("AWS/"):
        raise ValueError(f"{svc}: custom metrics cannot use an AWS/ namespace (use the built-in templates)")
    unit = str(raw.get("unit") or "None")
    if unit not in UNITS:
        raise ValueError(f"{svc}: unit {unit!r} is not a CloudWatch standard unit")
    dims_raw = raw.get("dimensions") or {}
    if not isinstance(dims_raw, dict) or not dims_raw or len(dims_raw) > MAX_DIMENSIONS:
        raise ValueError(f"{svc}: a custom metric needs 1-{MAX_DIMENSIONS} exact dimensions")
    dims = tuple(
        (_str(k, _DIM_NAME, f"{svc} dimension name"), _str(str(v), _DIM_VALUE, f"{svc} dimension value"))
        for k, v in sorted(dims_raw.items())
    )
    return CustomMetric(
        id=_str(raw.get("id"), _METRIC_ID, f"{svc} custom metric id"),
        namespace=ns,
        metric_name=_str(raw.get("metric_name"), _METRIC_NAME, f"{svc} custom metric name"),
        stat=_str(raw.get("stat") or "Average", STAT, f"{svc} custom metric statistic"),
        unit=unit,
        dimensions=dims,
    )


def _service(name: str, raw: Any) -> ServiceResources:
    if not isinstance(name, str) or not DD_SERVICE.match(name):
        raise ValueError(f"invalid service name {str(name)[:80]!r} (use [a-z][a-z0-9._-], 2-63 characters)")
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: expected a mapping")
    unknown = set(raw) - {"log_groups", "service_field", "metrics"}
    if unknown:
        raise ValueError(f"{name}: unknown key(s) {', '.join(sorted(unknown))}")
    groups_raw = raw.get("log_groups") or []
    if not isinstance(groups_raw, list) or len(groups_raw) > MAX_LOG_GROUPS_PER_SERVICE:
        raise ValueError(f"{name}: log_groups must be a list of at most {MAX_LOG_GROUPS_PER_SERVICE} names")
    groups = tuple(dict.fromkeys(_str(g, LOG_GROUP, f"{name} log group name") for g in groups_raw))
    field_raw = raw.get("service_field")
    service_field = _str(field_raw, _FIELD, f"{name} service_field") if field_raw else None
    metrics = raw.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise ValueError(f"{name}: metrics must be a mapping")
    unknown = set(metrics) - {"lambda", "alb", "ecs", "custom"}
    if unknown:
        raise ValueError(f"{name}: unknown metrics key(s) {', '.join(sorted(unknown))}")
    lam = alb = ecs = None
    if metrics.get("lambda") is not None:
        lam = _str((metrics["lambda"] or {}).get("function_name"), _LAMBDA_NAME, f"{name} Lambda function_name")
    if metrics.get("alb") is not None:
        m = metrics["alb"] or {}
        alb = (
            _str(m.get("load_balancer"), _ALB, f"{name} ALB load_balancer (app/<name>/<16 hex>)"),
            _str(m.get("target_group"), _TARGET_GROUP, f"{name} ALB target_group (targetgroup/<name>/<16 hex>)"),
        )
    if metrics.get("ecs") is not None:
        m = metrics["ecs"] or {}
        ecs = (
            _str(m.get("cluster"), _ECS_NAME, f"{name} ECS cluster"),
            _str(m.get("service"), _ECS_NAME, f"{name} ECS service"),
        )
    custom_raw = metrics.get("custom") or []
    if not isinstance(custom_raw, list) or len(custom_raw) > MAX_CUSTOM_METRICS:
        raise ValueError(f"{name}: custom must be a list of at most {MAX_CUSTOM_METRICS} metrics")
    custom = tuple(_custom(c, name) for c in custom_raw)
    if len({c.id for c in custom}) != len(custom):
        raise ValueError(f"{name}: custom metric ids must be unique")
    res = ServiceResources(name, groups, service_field, lam, alb, ecs, custom)
    if not any(res.has(k) for k in ("logs", "lambda", "alb", "ecs", "custom")):
        raise ValueError(f"{name}: map at least one log group or metric resource")
    return res


def parse_resources(doc: Any) -> ResourceMap:
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        raise ValueError("expected a mapping with a 'services' mapping")
    if set(doc) - {"services"}:
        raise ValueError(f"unknown top-level key(s) {', '.join(sorted(set(doc) - {'services'}))}")
    items = doc["services"]
    if not items or len(items) > MAX_SERVICES:
        raise ValueError(f"map 1-{MAX_SERVICES} services")
    services = {name: _service(name, raw) for name, raw in items.items()}
    owners: dict[str, list[ServiceResources]] = {}
    for s in services.values():
        for g in s.log_groups:
            owners.setdefault(g, []).append(s)
    for group, svcs in owners.items():
        if len(svcs) > 1 and any(s.service_field is None for s in svcs):
            raise ValueError(
                f"log group {group} is mapped to {', '.join(s.name for s in svcs)}: set service_field on each so "
                "events are attributed by a recorded field, never by guess"
            )
    if len(owners) > MAX_LOG_GROUPS:
        raise ValueError(f"at most {MAX_LOG_GROUPS} distinct log groups can be approved")
    return ResourceMap(services)


def load_resources(path: Path | str | None) -> ResourceMap:
    if path is None or not str(path).strip():
        raise ConnectorError(
            "not_configured", "set CLOUDWATCH_RESOURCES_FILE (the service → log group / metric mapping)"
        )
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return parse_resources(doc)
    except OSError as exc:
        raise ConnectorError("not_configured", f"CLOUDWATCH_RESOURCES_FILE cannot be read ({exc.strerror})") from None
    except (ValueError, yaml.YAMLError) as exc:
        raise ConnectorError(
            "not_configured", f"CLOUDWATCH_RESOURCES_FILE is invalid: {str(exc).splitlines()[0][:200]}"
        ) from None
