"""Recovery verification (audit finding H4).

Every required recovery condition is checked or explicitly reported as not checked. Nothing is
silently truncated, and "recovered" requires every required condition to pass.

Required conditions:
- each unrecovered metric anomaly (on the alerting service and the services the top hypothesis cites)
  that moved in that metric's *unhealthy* direction, or whose metric has no known health semantics;
- an action postcondition for each executed step (the change took effect / the system is in the state the
  plan intended, e.g. a paused consumer is running again).

Metric checks use metric-specific health semantics: a higher-is-bad metric must return to within a band
above its baseline (dropping below baseline is healthy); a lower-is-bad metric must return to within a
band below it (draining a backlog above baseline is healthy); metrics with unknown semantics must return
inside a two-sided band, so an opposite-direction excursion fails. Load and configuration metrics are
informational and never block recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Condition:
    kind: str  # metric | postcondition
    service: str | None
    name: str  # metric name or postcondition id
    evidence_id: str | None  # anomaly evidence or executed step it derives from
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
    excursion = abs(float(d.get("extreme", b)) - b)
    band = max(BAND_FRACTION * excursion, _tolerance(str(d.get("unit", "")), b))
    sem = d["semantics"]
    if sem == "higher_is_bad":
        ok, bound = after <= b + band, f"<= {b + band:.4g}"
    elif sem == "lower_is_bad":
        ok, bound = after >= b - band, f">= {b - band:.4g}"
    else:
        ok, bound = abs(after - b) <= band, f"within {b - band:.4g}..{b + band:.4g}"
    detail = f"after {after:.4g} (acceptable {bound})"
    if not ok and sem == "two_sided" and (after - b) * (float(d.get("extreme", b)) - b) < 0:
        detail += "; opposite-direction excursion beyond the healthy band"
    return {
        **base,
        "status": "passed" if ok else "failed",
        "after": round(after, 5),
        "acceptable": bound,
        "detail": detail,
    }


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


def overall(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "incomplete"
    if any(c["status"] == "failed" for c in checks):
        return "not_recovered"
    if all(c["status"] == "passed" for c in checks):
        return "recovered"
    return "incomplete"
