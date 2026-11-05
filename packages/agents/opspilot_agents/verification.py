"""Recovery verification (audit findings H4, C0-F1 and C0-G1).

Invariant: an incident is never reported as recovered unless every required recovery condition has
affirmative, sufficient, fresh supporting evidence. Missing, unknown, unsupported, stale or failed telemetry is
never equated with health. Every required condition is checked or explicitly reported as not checked; nothing
is silently truncated, and "recovered" requires every required condition to pass.

Initial health (C0-G1). Each service's state *before* the action is resolved across **all** observations, not
from any single snapshot: health reads, the health snapshot embedded in a dependency edge, and unrecovered
metric anomalies in the unhealthy direction (persistent-failure evidence). Any unhealthy/degraded observation
or failing anomaly makes the service ``unhealthy`` (it wins over a conflicting ``healthy`` read, and the
conflict is recorded); otherwise any ``healthy`` read makes it ``healthy``; otherwise it is ``unknown``.

Recovery scope. The services whose recovery is required are derived from the *observed* investigation, never
from the model's ranking or citations alone:
- the alerting service;
- every service targeted by an executed remediation step (rollback, pool change, consumer actions, and the
  consumer of a quarantined queue);
- every dependency whose *resolved* initial state is unhealthy, on an observed call path from a service already
  in scope (an edge whose own snapshot is missing or healthy cannot hide independent unhealthy evidence);
- every other service known to be unhealthy in this investigation (``known_unhealthy``): no known failure
  disappears because it was outside a top-K, uncited, or belongs to a dependency rather than the target;
- the services the top hypothesis cites (citations can only *add* services, never remove one).

Required conditions:
- each unrecovered metric anomaly in scope that moved in that metric's *unhealthy* direction, or whose
  metric has no known health semantics;
- a fresh, affirmative ``healthy`` health observation after the action for the alerting service, every action
  target, every affected dependency and every known-unhealthy service, whatever its initial state (an
  initially *unknown* service needs positive post-action health exactly as an unhealthy one does). A cited
  service with only healthy/unknown observations is not required;
- an action postcondition for each executed step (the change took effect / the system is in the state the
  plan intended, e.g. a paused consumer is running again);
- baseline sufficiency: an in-scope required metric whose *initial* read failed or had too few points, or a
  missing metric catalogue, is an unverifiable signal (``unknown``); and when no in-scope service had any
  observed failure before the action, a healthy-looking snapshot cannot confirm *recovery* (``unknown``).

Metric checks use metric-specific health semantics and acceptable ranges: a higher-is-bad metric must return
to within a band above its baseline (dropping below baseline is healthy); a lower-is-bad metric must return
to within a band below it (draining a backlog above baseline is healthy); metrics with unknown semantics must
return inside a two-sided band, so an opposite-direction excursion fails. The band is a quarter of the
original excursion, but never wider than the metric's own residual limit (``RESIDUAL_LIMITS``): a 5xx ratio
that fell from 40% to 8% has *improved*, it has not *recovered*. Load and configuration metrics are
informational and never block recovery.

``required_conditions`` is a pure function of the recorded state, so the outcome step re-derives it and refuses
``mitigated`` unless every one of those conditions has a passed check (``report.verified_recovered``).
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
HEALTHY, UNHEALTHY, UNKNOWN = "healthy", "unhealthy", "unknown"
VERDICTS = {"recovered": "VERIFIED", "not_recovered": "FAILED", "incomplete": "INCOMPLETE"}
CONTRACT = "c0g"  # verification records carrying this are re-derived at outcome time (report.verified_recovered)
# Scope reasons that make positive post-action health a required condition (cited-only services excluded).
HEALTH_REQUIRED_REASONS = frozenset({"alerting_service", "action_target", "affected_dependency", "known_unhealthy"})

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


def _dependency_edges(evidence: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """(caller, dependency) for every observed dependency edge. The edge's embedded health snapshot is *not*
    used here: a dependency's state comes from ``initial_health``, which considers every observation."""
    edges = []
    for e in evidence.values():
        if e["kind"] != "dependency":
            continue
        edge = e["data"].get("edge") or {}
        if edge.get("service") and edge.get("depends_on"):
            edges.append((edge["service"], edge["depends_on"]))
    return edges


def _health_label(status: Any) -> str:
    if status == HEALTHY:
        return HEALTHY
    if status in UNHEALTHY_STATUSES:
        return UNHEALTHY
    return UNKNOWN


def _failing(anomaly: dict[str, Any]) -> bool:
    """An unrecovered anomaly that is evidence of failure: unhealthy direction, or unknown semantics."""
    d = anomaly["data"]
    sem = semantics(d.get("metric", ""))
    return (
        sem == "two_sided"
        or (sem == "higher_is_bad" and d.get("direction", "up") == "up")
        or (sem == "lower_is_bad" and d.get("direction") == "down")
    )


def initial_health(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each observed service's pre-action state, resolved across every observation (see module docstring)."""
    evidence: dict[str, dict[str, Any]] = state.get("evidence") or {}
    obs: dict[str, list[dict[str, Any]]] = {}

    def note(svc: str | None, eid: str, source: str, label: str, raw: Any) -> None:
        if svc:
            obs.setdefault(svc, []).append({"evidence_id": eid, "source": source, "status": label, "raw": raw})

    for e in sorted(evidence.values(), key=lambda e: e["id"]):
        if e["kind"] == "service_health":
            raw = e["data"].get("status")
            note(e.get("service"), e["id"], "service_health", _health_label(raw), raw)
        elif e["kind"] == "dependency" and e["data"].get("health"):
            raw = e["data"]["health"].get("status")
            note(e.get("service"), e["id"], "dependency_snapshot", _health_label(raw), raw)
        elif e["kind"] == "metric_anomaly" and _unrecovered(e) and _failing(e):
            note(e.get("service"), e["id"], "unrecovered_anomaly", UNHEALTHY, e["data"].get("metric"))
    out: dict[str, dict[str, Any]] = {}
    for svc, items in sorted(obs.items()):
        labels = {i["status"] for i in items}
        status = UNHEALTHY if UNHEALTHY in labels else HEALTHY if HEALTHY in labels else UNKNOWN
        out[svc] = {"status": status, "conflict": {HEALTHY, UNHEALTHY} <= labels, "observations": items}
    return out


def recovery_scope(state: dict[str, Any], states: dict[str, dict[str, Any]] | None = None) -> dict[str, list[str]]:
    """Services whose recovery is required, each with the reasons it is in scope."""
    evidence: dict[str, dict[str, Any]] = state.get("evidence") or {}
    states = initial_health(state) if states is None else states
    scope: dict[str, list[str]] = {}

    def add(svc: str | None, reason: str) -> None:
        if svc and reason not in scope.setdefault(svc, []):
            scope[svc].append(reason)

    def unhealthy(svc: str) -> bool:
        return (states.get(svc) or {}).get("status") == UNHEALTHY

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
        for caller, dep in edges:
            if caller in scope and unhealthy(dep) and "affected_dependency" not in scope.get(dep, []):
                add(dep, "affected_dependency")
                changed = True
    for svc in sorted(states):  # every remaining known failure stays required
        if unhealthy(svc) and svc not in scope:
            add(svc, "known_unhealthy")
    return scope


def _unrecovered(e: dict[str, Any]) -> bool:
    return e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) and not e["data"].get("recovered")


def unrecovered_anomalies(evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in evidence.values() if _unrecovered(e)]


def split_by_scope(
    anomalies: list[dict[str, Any]], scope: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """In-scope anomalies, and an exclusion record (with reason) for every other one.

    Since C0-G1 every service with a failing unrecovered anomaly is in scope (``known_unhealthy``), so the only
    anomalies that can still be excluded are healthy-direction/informational ones and anomalies with no service.
    """
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
                        f"{a.get('service')} has no failing anomaly or unhealthy observation and is not the "
                        "alerting service, an action target, an affected dependency, or cited by the top hypothesis"
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
def health_conditions(scope: dict[str, list[str]], states: dict[str, dict[str, Any]]) -> list[Condition]:
    """Positive post-action health is required for every in-scope service whose reasons demand it, and for any
    in-scope service known to be unhealthy, whatever its initial state (C0-G1)."""
    out = []
    for svc, reasons in sorted(scope.items()):
        st = states.get(svc) or {"status": UNKNOWN, "observations": []}
        if not (HEALTH_REQUIRED_REASONS & set(reasons)) and st["status"] != UNHEALTHY:
            continue
        first = next((o["evidence_id"] for o in st["observations"] if o["status"] == st["status"]), None)
        out.append(Condition("health", svc, "health", first, {"before": st["status"]}))
    return out


def evaluate_health(cond: Condition, data: dict[str, Any] | None, executed_at: str | None) -> dict[str, Any]:
    base = {"kind": "health", "service": cond.service, "name": "health", "evidence_id": cond.evidence_id}
    if data is None:
        return {**base, "status": "unknown", "detail": "post-remediation health could not be observed"}
    status, as_of = data.get("status"), data.get("as_of")
    if executed_at and not as_of:
        return {**base, "status": "unknown", "observed": status, "detail": "health observation has no timestamp"}
    if executed_at and as_of and datetime.fromisoformat(str(as_of)) < datetime.fromisoformat(executed_at):
        return {**base, "status": "unknown", "observed": status, "detail": f"stale health observation ({as_of})"}
    if status == "healthy":
        return {
            **base,
            "status": "passed",
            "observed": status,
            "detail": f"initially {cond.spec['before']}, now healthy",
        }
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


# ----------------------------------------------------------------------------- baseline sufficiency
def baseline_conditions(
    state: dict[str, Any], scope: dict[str, list[str]], states: dict[str, dict[str, Any]]
) -> list[Condition]:
    """Signals whose initial state was never established, and the absence of any pre-action failure evidence.

    These conditions have no post-action read that could satisfy them, so they are always ``unknown``: recovery
    of a signal that was never observed cannot be confirmed (C0-G1)."""
    out: list[Condition] = []
    coverage: dict[str, dict[str, Any]] = state.get("telemetry_coverage") or {}
    for svc, reasons in sorted(scope.items()):
        if not HEALTH_REQUIRED_REASONS & set(reasons):
            continue
        cov = coverage.get(svc) or {}
        if cov.get("catalog_failed"):
            out.append(Condition("baseline", svc, "initial:metric_catalogue", None, {"gap": "catalogue unavailable"}))
        for metric, err in sorted((cov.get("metrics_failed") or {}).items()):
            if semantics(metric) != "informational":
                out.append(Condition("baseline", svc, f"initial:{metric}", None, {"gap": f"read failed: {err}"}))
        for metric in sorted(cov.get("metrics_insufficient") or []):
            if semantics(metric) != "informational":
                out.append(Condition("baseline", svc, f"initial:{metric}", None, {"gap": "too few data points"}))
    if not any((states.get(svc) or {}).get("status") == UNHEALTHY for svc in scope):
        alerting = state["incident"]["service"]
        out.append(
            Condition(
                "baseline",
                alerting,
                "failure_evidence",
                None,
                {"gap": "no failure was observed before the action; a healthy snapshot cannot confirm recovery"},
            )
        )
    return out


def evaluate_baseline(cond: Condition) -> dict[str, Any]:
    return {
        "kind": "baseline",
        "service": cond.service,
        "name": cond.name,
        "evidence_id": cond.evidence_id,
        "status": "unknown",
        "detail": f"initial evidence insufficient: {cond.spec['gap']}",
    }


@dataclass(frozen=True, slots=True)
class Requirements:
    states: dict[str, dict[str, Any]]
    scope: dict[str, list[str]]
    excluded: list[dict[str, Any]]
    informational: list[dict[str, Any]]
    conditions: list[Condition]


def required_conditions(state: dict[str, Any]) -> Requirements:
    """Every required recovery condition, as a pure function of the recorded state. Enumerated in full before
    any tool budget is applied, and re-derived at outcome time."""
    evidence = state.get("evidence") or {}
    states = initial_health(state)
    scope = recovery_scope(state, states)
    anomalies, excluded = split_by_scope(unrecovered_anomalies(evidence), scope)
    metric_conds, informational = metric_conditions(anomalies)
    conditions = [
        *metric_conds,
        *health_conditions(scope, states),
        *postcondition_conditions(state.get("executions") or [], state.get("remediation_plan") or [], evidence),
        *baseline_conditions(state, scope, states),
    ]
    return Requirements(states, scope, excluded, informational, conditions)


def condition_key(kind: Any, service: Any, name: Any, evidence_id: Any) -> str:
    return f"{kind}|{service or ''}|{name}|{evidence_id or ''}"


def service_summary(req: Requirements, checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Initial and current health per in-scope service (HEALTHY / UNHEALTHY / UNKNOWN)."""
    current: dict[str, str] = {}
    for c in checks:
        if c["kind"] == "health":
            current[c["service"]] = {"passed": "HEALTHY", "failed": "UNHEALTHY"}.get(c["status"], "UNKNOWN")
    out = {}
    for svc, reasons in sorted(req.scope.items()):
        st = req.states.get(svc) or {"status": UNKNOWN, "conflict": False}
        out[svc] = {
            "reasons": reasons,
            "initial": st["status"].upper(),
            "initial_conflict": bool(st.get("conflict")),
            "current": current.get(svc, "NOT_REQUIRED"),
        }
    return out


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
