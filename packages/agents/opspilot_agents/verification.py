"""Recovery verification (audit findings H4 and C0-F1).

Invariant: an incident is never reported as recovered while a known required recovery condition is failed,
unknown or unverified. Every required condition is checked or explicitly reported as not checked; nothing is
silently truncated, and "recovered" requires every required condition to pass.

Recovery scope (C0-F1). The services whose health must be re-established are derived from the *observed*
investigation, not from the model's citations:
- the alerting service;
- every service targeted by an executed remediation step (rollback, pool change, consumer actions, and the
  consumer of a quarantined queue);
- every dependency observed unhealthy/degraded on a call path from a service already in scope;
- the services the top hypothesis cites (citations can only *add* services, never remove one).
Every observed unrecovered anomaly outside that scope is listed in ``excluded`` with a machine-readable
reason, so the scope decision itself is auditable.

Required conditions:
- each unrecovered metric anomaly in scope that moved in that metric's *unhealthy* direction, or whose
  metric has no known health semantics;
- a health condition for each in-scope service observed unhealthy/degraded before the action (it must be
  observed ``healthy`` again, after the action);
- an action postcondition for each executed step (the change took effect / the system is in the state the
  plan intended, e.g. a paused consumer is running again).

Metric checks use metric-specific health semantics and acceptable ranges: a higher-is-bad metric must return
to within a band above its baseline (dropping below baseline is healthy); a lower-is-bad metric must return
to within a band below it (draining a backlog above baseline is healthy); metrics with unknown semantics must
return inside a two-sided band, so an opposite-direction excursion fails. The band is a quarter of the
original excursion, but never wider than the metric's own residual limit (``RESIDUAL_LIMITS``): a 5xx ratio
that fell from 40% to 8% has *improved*, it has not *recovered*. Load and configuration metrics are
informational and never block recovery.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

HIGHER_IS_BAD = frozenset(
    {
        "http_5xx_ratio",
        "p95_latency_ms",
        "validation_failures_per_min",
        "consumer_retries_per_min",
        "dlq_depth",
        "queue_depth",
        "db_pool_in_use",
        "db_pool_wait_ms",
    }
)
LOWER_IS_BAD = frozenset({"events_processed_per_min"})
INFORMATIONAL = frozenset({"http_requests_per_min", "db_pool_max"})  # load / configuration signals
BAND_FRACTION = 0.25
MIN_POST_POINTS = 3
UNHEALTHY_STATUSES = frozenset({"unhealthy", "degraded"})

# Largest residual deviation (in the unhealthy direction, from baseline) that still counts as *recovered*,
# as a function of the baseline. Independent of how large the original excursion was.
RESIDUAL_LIMITS: dict[str, Callable[[float], float]] = {
    "http_5xx_ratio": lambda b: 0.01,  # at most one percentage point above the normal error ratio
    "p95_latency_ms": lambda b: max(100.0, 0.5 * b),
    "db_pool_wait_ms": lambda b: max(50.0, 0.5 * b),
    "db_pool_in_use": lambda b: max(2.0, 0.5 * b),
    "queue_depth": lambda b: max(10.0, 0.5 * b),
    "dlq_depth": lambda b: max(10.0, 0.5 * b),
    "validation_failures_per_min": lambda b: max(2.0, 0.5 * b),
    "consumer_retries_per_min": lambda b: max(2.0, 0.5 * b),
    "events_processed_per_min": lambda b: max(2.0, 0.25 * b),
}


@dataclass(frozen=True, slots=True)
class Condition:
    kind: str  # metric | health | postcondition
    service: str | None
    name: str  # metric name, "health", or postcondition id
    evidence_id: str | None  # anomaly/health evidence or executed step it derives from
    spec: dict[str, Any]


def semantics(metric: str) -> str:
    if metric in HIGHER_IS_BAD:
        return "higher_is_bad"
    if metric in LOWER_IS_BAD:
        return "lower_is_bad"
    if metric in INFORMATIONAL:
        return "informational"
    return "two_sided"


def _tolerance(unit: str, baseline: float) -> float:
    return {"ratio": 0.005, "ms": 50.0}.get(unit, max(2.0, 0.1 * abs(baseline)))


# ----------------------------------------------------------------------------- scope
def _step_targets(step: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> set[str]:
    p = step.get("parameters") or {}
    out = {p["service"]} if p.get("service") else set()
    if step.get("action_type") == "quarantine_messages" and p.get("queue"):
        for e in evidence.values():
            if e["kind"] == "queue" and e["data"].get("queue") == p["queue"]:
                consumer = (e["data"].get("consumer") or {}).get("service")
                if consumer:
                    out.add(consumer)
    return out


def _dependency_edges(evidence: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """(caller, dependency, observed status) for every dependency observation."""
    edges = []
    for e in evidence.values():
        if e["kind"] != "dependency":
            continue
        edge = e["data"].get("edge") or {}
        status = (e["data"].get("health") or {}).get("status") or "unknown"
        if edge.get("service") and edge.get("depends_on"):
            edges.append((edge["service"], edge["depends_on"], status))
    return edges


def recovery_scope(state: dict[str, Any]) -> dict[str, list[str]]:
    """Services whose recovery is required, each with the reasons it is in scope."""
    evidence: dict[str, dict[str, Any]] = state.get("evidence") or {}
    scope: dict[str, list[str]] = {}

    def add(svc: str | None, reason: str) -> None:
        if svc and reason not in scope.setdefault(svc, []):
            scope[svc].append(reason)

    add(state["incident"]["service"], "alerting_service")
    by_step = {p.get("step"): p for p in state.get("remediation_plan") or []}
    for x in state.get("executions") or []:
        step = by_step.get(x.get("step"))
        if x.get("status") == "succeeded" and step is not None:
            for svc in sorted(_step_targets(step, evidence)):
                add(svc, "action_target")
    top = ((state.get("rca") or {}).get("hypotheses") or [{}])[0]
    for i in top.get("supporting_evidence_ids", []):
        add((evidence.get(i) or {}).get("service"), "cited_by_top_hypothesis")
    edges = _dependency_edges(evidence)
    changed = True
    while changed:  # transitive: an unhealthy dependency of anything in scope is on the affected path
        changed = False
        for caller, dep, status in edges:
            if caller in scope and status in UNHEALTHY_STATUSES and "affected_dependency" not in scope.get(dep, []):
                add(dep, "affected_dependency")
                changed = True
    return scope


def unrecovered_anomalies(evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e
        for e in evidence.values()
        if e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) and not e["data"].get("recovered")
    ]


def split_by_scope(
    anomalies: list[dict[str, Any]], scope: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """In-scope anomalies, and an exclusion record (with reason) for every other one."""
    inside, excluded = [], []
    for a in anomalies:
        if a.get("service") in scope:
            inside.append(a)
        else:
            excluded.append(
                {
                    "service": a.get("service"),
                    "metric": a["data"].get("metric"),
                    "evidence_id": a["id"],
                    "reason": "service_outside_recovery_scope",
                    "detail": (
                        f"{a.get('service')} is not the alerting service, an action target, an unhealthy "
                        "dependency on an affected call path, or cited by the top hypothesis"
                    ),
                }
            )
    return inside, excluded


# ----------------------------------------------------------------------------- metrics
def metric_conditions(anomalies: list[dict[str, Any]]) -> tuple[list[Condition], list[dict[str, Any]]]:
    """Split unrecovered anomalies into required conditions and informational notes."""
    required: list[Condition] = []
    informational: list[dict[str, Any]] = []
    for a in anomalies:
        d = a["data"]
        sem = semantics(d["metric"])
        unhealthy_direction = (sem == "higher_is_bad" and d.get("direction", "up") == "up") or (
            sem == "lower_is_bad" and d.get("direction") == "down"
        )
        if sem == "two_sided" or unhealthy_direction:
            required.append(Condition("metric", a.get("service"), d["metric"], a["id"], {**d, "semantics": sem}))
        else:
            informational.append(
                {
                    "service": a.get("service"),
                    "metric": d["metric"],
                    "evidence_id": a["id"],
                    "note": f"{d.get('direction')} shift on a {sem} metric is not a recovery condition",
                }
            )
    return required, informational


def acceptable_band(metric: str, unit: str, baseline: float, extreme: float) -> float:
    """Allowed deviation from baseline: a quarter of the excursion, capped by the metric's residual limit."""
    relative = BAND_FRACTION * abs(extreme - baseline)
    limit = RESIDUAL_LIMITS.get(metric)
    if limit is not None:
        relative = min(relative, limit(baseline))
    return max(relative, _tolerance(unit, baseline))


def evaluate_metric(cond: Condition, points: list[float] | None) -> dict[str, Any]:
    d = cond.spec
    base = {
        "kind": "metric",
        "service": cond.service,
        "name": cond.name,
        "evidence_id": cond.evidence_id,
        "semantics": d["semantics"],
        "baseline": round(float(d["baseline"]), 5),
        "anomalous": round(float(d.get("extreme", d.get("peak", d["baseline"]))), 5),
    }
    if not points or len(points) < MIN_POST_POINTS:
        return {**base, "status": "unknown", "detail": "insufficient post-remediation data"}
    after = sum(points[-MIN_POST_POINTS:]) / MIN_POST_POINTS
    b = float(d["baseline"])
    extreme = float(d.get("extreme", b))
    band = acceptable_band(cond.name, str(d.get("unit", "")), b, extreme)
    sem = d["semantics"]
    if sem == "higher_is_bad":
        ok, bound = after <= b + band, f"<= {b + band:.4g}"
    elif sem == "lower_is_bad":
        ok, bound = after >= b - band, f">= {b - band:.4g}"
    else:
        ok, bound = abs(after - b) <= band, f"within {b - band:.4g}..{b + band:.4g}"
    detail = f"after {after:.4g} (acceptable {bound})"
    if not ok and sem == "two_sided" and (after - b) * (extreme - b) < 0:
        detail += "; opposite-direction excursion beyond the healthy band"
    elif not ok and abs(after - b) < 0.5 * abs(extreme - b):
        detail += "; improved but not recovered"
    return {
        **base,
        "status": "passed" if ok else "failed",
        "after": round(after, 5),
        "acceptable": bound,
        "detail": detail,
    }


# ----------------------------------------------------------------------------- health
def health_conditions(scope: dict[str, list[str]], evidence: dict[str, dict[str, Any]]) -> list[Condition]:
    """A health condition for each in-scope service observed unhealthy/degraded before the action."""
    observed: dict[str, tuple[str, str]] = {}  # service -> (status, evidence id); unhealthy observations win
    for e in sorted(evidence.values(), key=lambda e: e["id"]):
        if e["kind"] == "service_health":
            svc, status = e.get("service"), e["data"].get("status")
        elif e["kind"] == "dependency":
            svc, status = e.get("service"), (e["data"].get("health") or {}).get("status")
        else:
            continue
        if svc in scope and status in UNHEALTHY_STATUSES:
            observed.setdefault(svc, (status, e["id"]))
    return [
        Condition("health", svc, "health", eid, {"before": status}) for svc, (status, eid) in sorted(observed.items())
    ]


def evaluate_health(cond: Condition, data: dict[str, Any] | None, executed_at: str | None) -> dict[str, Any]:
    base = {"kind": "health", "service": cond.service, "name": "health", "evidence_id": cond.evidence_id}
    if data is None:
        return {**base, "status": "unknown", "detail": "post-remediation health could not be observed"}
    status, as_of = data.get("status"), data.get("as_of")
    if executed_at and as_of and datetime.fromisoformat(str(as_of)) < datetime.fromisoformat(executed_at):
        return {**base, "status": "unknown", "observed": status, "detail": f"stale health observation ({as_of})"}
    if status == "healthy":
        return {**base, "status": "passed", "observed": status, "detail": f"was {cond.spec['before']}, now healthy"}
    if status in UNHEALTHY_STATUSES:
        return {**base, "status": "failed", "observed": status, "detail": f"still {status} after remediation"}
    return {**base, "status": "unknown", "observed": status, "detail": f"health status {status or 'missing'}"}


# ----------------------------------------------------------------------------- postconditions
def postcondition_conditions(
    executions: list[dict[str, Any]], plan: list[dict[str, Any]], evidence: dict[str, dict[str, Any]]
) -> list[Condition]:
    """One postcondition per executed step; consumer state is checked once, after the last consumer action."""
    by_step = {p["step"]: p for p in plan}
    conditions: list[Condition] = []
    consumer_targets: dict[str, str] = {}
    queues = {e["data"]["queue"]: e["data"] for e in evidence.values() if e["kind"] == "queue"}
    for x in executions:
        if x.get("status") != "succeeded":
            continue
        step = by_step.get(x.get("step"))
        if step is None:
            continue
        a, p = step["action_type"], step["parameters"]
        ref = f"step-{step['step']}"
        if a == "rollback_deployment":
            dep: dict[str, Any] = next(
                (
                    e["data"]
                    for e in evidence.values()
                    if e["kind"] == "deployment" and e["data"].get("id") == p["deployment_id"]
                ),
                {},
            )
            conditions.append(
                Condition(
                    "postcondition",
                    p["service"],
                    f"rolled_back:{p['deployment_id']}",
                    ref,
                    {"deployment_id": p["deployment_id"], "started_at": dep.get("started_at")},
                )
            )
        elif a == "scale_connection_pool":
            conditions.append(
                Condition(
                    "postcondition",
                    p["service"],
                    f"pool_size:{p['max_connections']}",
                    ref,
                    {"expected": int(p["max_connections"])},
                )
            )
        elif a == "quarantine_messages":
            conditions.append(
                Condition(
                    "postcondition",
                    None,
                    f"no_unquarantined:{p['queue']}:{p['error_code']}",
                    ref,
                    {"queue": p["queue"], "error_code": p["error_code"]},
                )
            )
        elif a in ("pause_consumer", "resume_consumer"):
            for q, d in queues.items():
                if (d.get("consumer") or {}).get("service") == p["service"]:
                    consumer_targets[q] = ref
    for q, ref in consumer_targets.items():
        conditions.append(
            Condition("postcondition", queues[q]["consumer"]["service"], f"consumer_running:{q}", ref, {"queue": q})
        )
    return conditions


def evaluate_postcondition(cond: Condition, data: dict[str, Any] | None) -> dict[str, Any]:
    base = {"kind": "postcondition", "service": cond.service, "name": cond.name, "evidence_id": cond.evidence_id}
    if data is None:
        return {**base, "status": "unknown", "detail": "postcondition could not be observed"}
    name = cond.name.split(":", 1)[0]
    if name == "rolled_back":
        dep = next((d for d in data.get("deployments", []) if d["id"] == cond.spec["deployment_id"]), None)
        ok = dep is not None and dep["status"] == "rolled_back"
        observed = dep["status"] if dep else "deployment not found"
    elif name == "pool_size":
        observed = (data.get("config") or {}).get("db.pool.max")
        ok = observed == cond.spec["expected"]
    elif name == "no_unquarantined":
        remaining = sum(f["count"] for f in data.get("failures", []) if f.get("error_code") == cond.spec["error_code"])
        ok, observed = remaining == 0, f"{remaining} unquarantined failing message(s)"
    elif name == "consumer_running":
        observed = (data.get("consumer") or {}).get("state")
        ok = observed == "running"
    else:  # pragma: no cover
        return {**base, "status": "unknown", "detail": f"no evaluator for {cond.name}"}
    return {**base, "status": "passed" if ok else "failed", "observed": observed, "detail": f"observed {observed}"}


# ----------------------------------------------------------------------------- outcome
def overall(checks: list[dict[str, Any]], required: int | None = None) -> str:
    """``recovered`` only when every required condition has a check and every check passed."""
    if not checks:
        return "incomplete"
    if any(c["status"] == "failed" for c in checks):
        return "not_recovered"
    if required is not None and len(checks) < required:
        return "incomplete"  # a required condition has no recorded check: never assume it passed
    if all(c["status"] == "passed" for c in checks):
        return "recovered"
    return "incomplete"
