"""Evidence-based validation of model-proposed remediation steps.

The model proposes; this module decides whether a step is admissible. Every rule is generic and
uses only evidence collected in this investigation — never scenario knowledge. Rejections are
classified as ``invalid`` (malformed / unsupported by evidence) or ``unsafe`` (would risk making
things worse, e.g. exceeding datastore capacity, or safety cannot be verified).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opspilot_shared.domain.actions import REMEDIATION_CATALOG, ActionType

CAPACITY_HEADROOM = 0.9  # projected connections must stay within 90% of usable capacity
MAX_POOL_GROWTH = 2.0  # never more than double a pool in one step


@dataclass(frozen=True, slots=True)
class StepCheck:
    ok: bool
    action_type: str
    params: dict[str, Any] | None = None
    reason: str = ""
    category: str | None = None  # invalid | unsafe
    details: dict[str, Any] | None = None


def _by_kind(evidence: dict[str, dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in evidence.values() if e["kind"] == kind]


def observed_services(evidence: dict[str, dict[str, Any]], incident_service: str) -> set[str]:
    return {e["service"] for e in evidence.values() if e.get("service")} | {incident_service}


def shows_abnormality(service: str, evidence: dict[str, dict[str, Any]]) -> bool:
    """True if evidence shows the service itself misbehaving (unrecovered anomaly, unhealthy, or queue failures)."""
    for e in evidence.values():
        if e.get("service") != service:
            continue
        d = e.get("data") or {}
        if e["kind"] == "metric_anomaly" and d.get("anomaly", True) and not d.get("recovered"):
            return True
        if e["kind"] == "service_health" and d.get("status") in ("unhealthy", "degraded"):
            return True
        if e["kind"] == "dependency" and ((d.get("health") or {}).get("status") in ("unhealthy", "degraded")):
            return True
        if e["kind"] == "queue" and (d.get("failures") or d.get("dead_lettered")):
            return True
    return False


MIN_ROLLBACK_CORRELATION = 0.3
AMBIGUITY_MARGIN = 0.15
STRONG_CHANGE_CORRELATION = 0.5  # a rival change at or above this blocks a rollback (see rollback_gates)


def consumer_state(service: str, evidence: dict[str, dict[str, Any]]) -> str:
    """'running', 'paused' or 'unknown' from queue evidence; missing or unrecognised state is unknown (v0.4 Fix A)."""
    states = [
        (e["data"].get("consumer") or {}).get("state")
        for e in _by_kind(evidence, "queue")
        if (e["data"].get("consumer") or {}).get("service") == service
    ]
    if not states or any(s not in ("running", "paused") for s in states):
        return "unknown"
    if "running" in states:
        return "running"
    return "paused"


def unresolved_change_ambiguity(evidence: dict[str, dict[str, Any]]) -> str | None:
    """Describe two strongly and similarly correlated changes, or None (v0.4 Fix B).

    Same definition as the rollback rival rule, but evaluated on the evidence alone, so it applies whatever the model
    proposed: a plan cannot avoid the ambiguity gate by proposing a restart instead of the ambiguous rollback.
    """
    changes = sorted(
        (e["data"] for e in evidence.values() if e["kind"] in ("deployment", "config_change")),
        key=lambda d: -float(d.get("correlation") or 0.0),
    )
    strong = [d for d in changes if float(d.get("correlation") or 0.0) >= STRONG_CHANGE_CORRELATION]
    if len(strong) >= 2:
        a, b = strong[0], strong[1]
        ca, cb = float(a.get("correlation") or 0.0), float(b.get("correlation") or 0.0)
        if ca - cb < AMBIGUITY_MARGIN:
            return f"{a.get('id')} ({ca:.2f}) and {b.get('id')} ({cb:.2f}) are similarly correlated with the onset"
    return None


def rollback_gates(dep: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> StepCheck | None:
    """Generic causal checks before reverting a change. Returns a rejection or None."""
    corr = float(dep.get("correlation") or 0.0)
    if corr < MIN_ROLLBACK_CORRELATION:
        return StepCheck(
            False,
            "rollback_deployment",
            reason=f"{dep['id']} does not correlate with the anomaly "
            f"onset (correlation {corr:.2f} < {MIN_ROLLBACK_CORRELATION})",
            category="invalid",
        )
    rivals = [
        e["data"]
        for e in evidence.values()
        if e["kind"] in ("deployment", "config_change")
        and e["data"].get("id") != dep["id"]
        and float(e["data"].get("correlation") or 0) >= 0.5
        and corr - float(e["data"].get("correlation") or 0) < AMBIGUITY_MARGIN
    ]
    if rivals:
        names = ", ".join(f"{r['id']} ({float(r['correlation']):.2f})" for r in rivals)
        return StepCheck(
            False,
            "rollback_deployment",
            reason=f"ambiguous: {dep['id']} ({corr:.2f}) is not clearly "
            f"more correlated than {names}; evidence must discriminate before reverting",
            category="insufficient_evidence",
        )
    # Causal consistency: if the target's own errors are attributed to a different, unhealthy dependency that
    # did not change, reverting the target does not address the failure.
    target = dep["service"]
    changed = {
        e["data"].get("service")
        for e in evidence.values()
        if e["kind"] in ("deployment", "config_change")
        and float(e["data"].get("correlation") or 0) >= MIN_ROLLBACK_CORRELATION
    }
    unhealthy = {
        e["service"]
        for e in evidence.values()
        if e["kind"] == "dependency" and ((e["data"].get("health") or {}).get("status") in ("unhealthy", "degraded"))
    }
    blamed: dict[str, int] = {}
    total_errors = 0
    for e in evidence.values():
        if e["kind"] == "log_pattern" and e.get("service") == target and e["data"]["level"] == "ERROR":
            total_errors += int(e["data"]["count"])
            up = (e["data"].get("attributes") or {}).get("upstream")
            if up and up != target:
                blamed[up] = blamed.get(up, 0) + int(e["data"]["count"])
    for up, n in blamed.items():
        if total_errors and n / total_errors >= 0.8 and up in unhealthy and up not in changed:
            return StepCheck(
                False,
                "rollback_deployment",
                reason=f"{target}'s errors are attributed to unhealthy "
                f"dependency {up} ({n}/{total_errors}), which did not change; reverting {target} "
                "does not address it",
                category="invalid",
            )
    return None


def capacity_check(service: str, new_pool: int, evidence: dict[str, dict[str, Any]]) -> StepCheck:
    """Projected connections after a pool change must fit the datastore's capacity (from evidence)."""
    cfg = next((e["data"] for e in _by_kind(evidence, "service_config") if e["data"].get("service") == service), None)
    if not cfg:
        return StepCheck(
            False,
            "scale_connection_pool",
            reason=f"no configuration evidence for {service}; pool capacity cannot be verified",
            category="unsafe",
        )
    datastore = (cfg.get("config") or {}).get("db.datastore")
    current = int((cfg.get("config") or {}).get("db.pool.max") or 0)
    replicas = int(cfg.get("replicas") or 0)
    ds = next((e["data"] for e in _by_kind(evidence, "datastore") if e["data"].get("datastore") == datastore), None)
    if not ds or not datastore or not replicas:
        return StepCheck(
            False,
            "scale_connection_pool",
            reason=f"no capacity evidence for datastore {datastore!r}; refusing to change the pool without it",
            category="unsafe",
        )
    usable = int(ds["max_connections"]) - int(ds.get("reserved_superuser_connections", 0))
    current_client = int((ds.get("connections_by_client") or {}).get(service, current * replicas))
    projected = int(ds["connections_active"]) - current_client + new_pool * replicas
    limit = int(usable * CAPACITY_HEADROOM)
    details = {
        "datastore": datastore,
        "current_pool": current,
        "new_pool": new_pool,
        "replicas": replicas,
        "projected_connections": projected,
        "limit": limit,
        "max_connections": ds["max_connections"],
    }
    if current and new_pool > current * MAX_POOL_GROWTH:
        return StepCheck(
            False,
            "scale_connection_pool",
            reason=f"pool increase {current}->{new_pool} exceeds the {MAX_POOL_GROWTH:g}x per-step limit",
            category="unsafe",
            details=details,
        )
    if projected > limit:
        return StepCheck(
            False,
            "scale_connection_pool",
            reason=f"projected {projected} connections on {datastore} exceeds {limit} "
            f"({CAPACITY_HEADROOM:.0%} of usable {usable})",
            category="unsafe",
            details=details,
        )
    return StepCheck(True, "scale_connection_pool", {"service": service, "max_connections": new_pool}, details=details)


def validate_step(
    step: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    incident_service: str,
    *,
    paused_in_plan: frozenset[str] = frozenset(),
) -> StepCheck:
    """Admit one step. ``paused_in_plan``: consumers paused by an already validated earlier step of this plan."""
    raw_type = str(step.get("action_type"))
    try:
        action = ActionType(raw_type)
    except ValueError:
        return StepCheck(
            False, raw_type, reason=f"action type {raw_type!r} is not in the remediation catalogue", category="invalid"
        )
    if not REMEDIATION_CATALOG[action].implemented:
        return StepCheck(False, raw_type, reason=f"{raw_type} is not available in the sandbox", category="invalid")
    services = observed_services(evidence, incident_service)
    queues = {e["data"]["queue"]: e["data"] for e in _by_kind(evidence, "queue")}

    if action is ActionType.ROLLBACK_DEPLOYMENT:
        deployments = {e["data"]["id"]: e["data"] for e in _by_kind(evidence, "deployment")}
        dep = deployments.get(step.get("deployment_id") or "")
        if dep is None:
            return StepCheck(
                False,
                raw_type,
                reason=f"deployment {step.get('deployment_id')!r} does not appear in collected evidence",
                category="invalid",
            )
        if dep["kind"] == "rollback" or dep["status"] == "rolled_back":
            return StepCheck(
                False, raw_type, reason="deployment is already a rollback / rolled back", category="invalid"
            )
        gate = rollback_gates(dep, evidence)
        if gate is not None:
            return gate
        return StepCheck(True, raw_type, {"service": dep["service"], "deployment_id": dep["id"]})

    if action is ActionType.RESTART_SERVICE:
        if step.get("service") not in services:
            return StepCheck(
                False,
                raw_type,
                reason=f"service {step.get('service')!r} not observed in this investigation",
                category="invalid",
            )
        if not shows_abnormality(str(step["service"]), evidence):
            return StepCheck(
                False,
                raw_type,
                reason=f"no evidence shows {step['service']!r} itself is abnormal; "
                "restarting a healthy service is unwarranted",
                category="invalid",
            )
        return StepCheck(True, raw_type, {"service": step["service"]})

    if action is ActionType.SCALE_CONNECTION_POOL:
        if step.get("service") not in services or not step.get("max_connections"):
            return StepCheck(
                False,
                raw_type,
                reason="scale_connection_pool needs an observed service and max_connections",
                category="invalid",
            )
        return capacity_check(str(step["service"]), int(step["max_connections"]), evidence)

    if action in (ActionType.PAUSE_CONSUMER, ActionType.RESUME_CONSUMER):
        consumer_of = [q for q, d in queues.items() if (d.get("consumer") or {}).get("service") == step.get("service")]
        if not consumer_of:
            return StepCheck(
                False,
                raw_type,
                reason=f"no queue evidence shows {step.get('service')!r} as a consumer",
                category="invalid",
            )
        if action is ActionType.PAUSE_CONSUMER and not shows_abnormality(str(step["service"]), evidence):
            return StepCheck(
                False,
                raw_type,
                reason=f"no failures observed on queues consumed by {step['service']!r}",
                category="invalid",
            )
        if action is ActionType.RESUME_CONSUMER:
            # v0.4 Fix A: resuming is only meaningful for a paused consumer. Missing state is unknown, not paused.
            svc = str(step["service"])
            if svc in paused_in_plan:
                return StepCheck(True, raw_type, {"service": svc}, details={"resume_justified_by": "pause_in_plan"})
            observed = consumer_state(svc, evidence)
            if observed == "paused":
                return StepCheck(True, raw_type, {"service": svc}, details={"resume_justified_by": "observed_paused"})
            if observed == "running":
                return StepCheck(
                    False,
                    raw_type,
                    reason=f"consumer {svc!r} is already running and is not paused earlier in this plan",
                    category="invalid",
                )
            return StepCheck(
                False,
                raw_type,
                reason=f"state of consumer {svc!r} is unknown; a resume needs evidence that it is paused",
                category="insufficient_evidence",
            )
        return StepCheck(True, raw_type, {"service": step["service"]})

    if action is ActionType.QUARANTINE_MESSAGES:
        requested = step.get("queue") or ""
        if not requested and step.get("service"):
            consumed = [qn for qn, d in queues.items() if (d.get("consumer") or {}).get("service") == step["service"]]
            requested = consumed[0] if len(consumed) == 1 else ""
        # A DLQ name refers to its primary queue (quarantine covers the queue and its dead-letter queue).
        q = queues.get(requested) or next((d for d in queues.values() if d.get("dead_letter_queue") == requested), None)
        if q is None:
            return StepCheck(
                False,
                raw_type,
                reason=f"queue {step.get('queue')!r} not inspected in this investigation",
                category="invalid",
            )
        codes = {f.get("error_code") for f in q.get("failures", [])}
        if not step.get("error_code") or step["error_code"] not in codes:
            return StepCheck(
                False,
                raw_type,
                reason=f"error code {step.get('error_code')!r} not observed on "
                f"{q['queue']} (observed: {sorted(c for c in codes if c)})",
                category="invalid",
            )
        return StepCheck(True, raw_type, {"queue": q["queue"], "error_code": step["error_code"]})

    return StepCheck(False, raw_type, reason="unsupported action", category="invalid")  # pragma: no cover


ROLE_ORDER = {"containment": 0, "resolution": 1, "recovery": 2}


REDUNDANT_WITH_RESOLUTION = {"restart_service", "scale_connection_pool"}


def role_of(action_type: str) -> str | None:
    try:
        return REMEDIATION_CATALOG[ActionType(action_type)].role.value
    except ValueError:
        return None


def enforce_causal_prerequisites(
    plan: list[dict[str, Any]], rejected: list[dict[str, Any]], evidence: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """v0.4 Fix B: no state-changing step may bypass a rejected resolution or unresolved causal ambiguity.

    1. Unresolved change ambiguity in the evidence withholds every step (the cause is not established, so neither a
       revert nor a restart is justified by it).
    2. When the model's plan had a resolution step and every resolution step was rejected, the containment and
       recovery steps that were meant to accompany it are dropped. A restart or other containment proposed on its
       own (no rejected resolution) is still judged by its own gates.
    3. A resume justified only by a pause in this plan is dropped if that pause is no longer in the plan.
    Returns (kept, dropped-with-reason).
    """
    dropped: list[dict[str, Any]] = []

    def drop(step: dict[str, Any], reason: str, category: str = "insufficient_evidence") -> None:
        dropped.append(
            {"proposal": {k: step[k] for k in ("action_type", "parameters")}, "category": category, "reason": reason}
        )

    ambiguity = unresolved_change_ambiguity(evidence)
    if ambiguity:
        for step in plan:
            drop(step, f"unresolved causal ambiguity: {ambiguity}; no state-changing step may bypass it")
        return [], dropped
    rejected_resolution = [
        r for r in rejected if role_of(str((r.get("proposal") or {}).get("action_type"))) == "resolution"
    ]
    kept = list(plan)
    if rejected_resolution and not any(s.get("role") == "resolution" for s in kept):
        why = "; ".join(str(r.get("reason", ""))[:160] for r in rejected_resolution)
        for step in kept:
            drop(step, f"the plan's resolution step was rejected ({why}); {step['action_type']} would act without it")
        kept = []
    paused = {s["parameters"].get("service") for s in kept if s["action_type"] == "pause_consumer"}
    final: list[dict[str, Any]] = []
    for step in kept:
        justified = (step.get("validation") or {}).get("resume_justified_by")
        if (
            step["action_type"] == "resume_consumer"
            and justified == "pause_in_plan"
            and step["parameters"].get("service") not in paused
        ):
            drop(step, "resume depended on a pause that is no longer in the plan", "invalid")
            continue
        final.append(step)
    return final, dropped


def enforce_plan_shape(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical order containment -> resolution -> recovery (stable), minus redundant containment.

    Restarts and capacity changes are redundant once a resolution step reverts the cause, and only add risk.
    Returns (kept, dropped-with-reason).
    """
    ordered = sorted(steps, key=lambda s: ROLE_ORDER.get(s.get("role", ""), 1))
    has_resolution = any(s.get("role") == "resolution" for s in ordered)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for step in ordered:
        if has_resolution and step["action_type"] in REDUNDANT_WITH_RESOLUTION:
            dropped.append(
                {
                    "proposal": {k: step[k] for k in ("action_type", "parameters")},
                    "category": "invalid",
                    "reason": f"{step['action_type']} is redundant when the plan reverts the cause",
                }
            )
            continue
        kept.append(step)
    return kept, dropped
