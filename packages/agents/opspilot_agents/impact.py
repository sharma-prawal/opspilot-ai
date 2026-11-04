"""Tri-state impact assessment (audit finding H2).

Absence of an anomaly is only recovery evidence if the observations that could have shown one were
actually made and were sufficient. Missing metrics, failed tools, too few data points, an unknown health
status, or observations that contradict each other all yield UNKNOWN — and UNKNOWN never resolves an
incident or unlocks a remediation proposal.
"""

from __future__ import annotations

from typing import Any

from opspilot_shared.domain.incidents import ImpactAssessment, ImpactState

MIN_POINTS = 20  # a metric series shorter than this cannot establish "steady" or "recovered"
CORE_METRICS = ("http_5xx_ratio", "p95_latency_ms", "events_processed_per_min", "validation_failures_per_min")


def assess_impact(state: dict[str, Any]) -> ImpactAssessment:
    svc = state["incident"]["service"]
    evidence = state.get("evidence", {})
    coverage = (state.get("telemetry_coverage") or {}).get(svc)
    mine = [e for e in evidence.values() if e.get("service") == svc]
    unrecovered = [
        e
        for e in mine
        if e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) and not e["data"].get("recovered")
    ]
    recovered = [
        e
        for e in mine
        if e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) and e["data"].get("recovered")
    ]
    health_ids = [e["id"] for e in mine if e["kind"] == "service_health"]
    if unrecovered:
        return ImpactAssessment(
            state=ImpactState.ONGOING,
            evidence_ids=[e["id"] for e in unrecovered],
            reasons=[f"{len(unrecovered)} unrecovered anomalous metric(s) on {svc}"],
        )
    if not coverage:
        return ImpactAssessment(state=ImpactState.UNKNOWN, reasons=[f"telemetry for {svc} was not collected"])
    health = coverage.get("health_status")

    ok = set(coverage.get("metrics_ok", []))
    failed = coverage.get("metrics_failed", {})
    insufficient = coverage.get("metrics_insufficient", [])
    core_expected = [m for m in coverage.get("metrics_requested", []) if m in CORE_METRICS]
    reasons: list[str] = []
    if coverage.get("catalog_failed"):
        reasons.append(f"metric catalogue for {svc} unavailable")
    if failed:
        reasons.append(f"metric queries failed on {svc}: {sorted(failed)}")
    if insufficient:
        reasons.append(f"insufficient data points on {svc}: {sorted(insufficient)}")
    if not core_expected or not set(core_expected) <= ok:
        reasons.append(
            f"core metrics not fully observed on {svc} (observed {sorted(ok & set(core_expected))} "
            f"of {sorted(core_expected)})"
        )
    if health in ("unhealthy", "degraded"):
        if reasons:  # metrics missing, health says impact: the affirmative signal is the health check
            return ImpactAssessment(
                state=ImpactState.ONGOING, evidence_ids=health_ids, reasons=[f"{svc} health is {health}", *reasons]
            )
        return ImpactAssessment(
            state=ImpactState.UNKNOWN,
            evidence_ids=health_ids + [e["id"] for e in recovered],
            reasons=[f"conflicting observations: metrics show no ongoing anomaly but {svc} health is {health}"],
        )
    if health != "healthy":
        reasons.append(f"{svc} health status is {health or 'not observed'}")
    if reasons:
        return ImpactAssessment(state=ImpactState.UNKNOWN, reasons=reasons, evidence_ids=health_ids)
    return ImpactAssessment(
        state=ImpactState.RECOVERED,
        evidence_ids=health_ids + [e["id"] for e in recovered],
        reasons=[
            f"core metrics on {svc} observed with sufficient data and no ongoing anomaly; "
            f"health {health}" + (f"; {len(recovered)} anomaly(ies) recovered" if recovered else "")
        ],
    )
