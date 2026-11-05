"""H2 regression: missing telemetry must never look like recovery (tri-state impact)."""

import json
from typing import Any

import pytest

from opspilot_agents.impact import assess_impact
from opspilot_agents.nodes import AgentDeps, InvestigationNodes
from opspilot_agents.report import determine_outcome

SVC = "transaction-api"
CORE = ["http_5xx_ratio", "p95_latency_ms"]


def ev(eid: str, kind: str, data: dict[str, Any], service: str = SVC) -> dict[str, Any]:
    return {"id": eid, "kind": kind, "service": service, "relevance": 0.8, "summary": eid, "data": data}


def cov(
    ok: list[str] | None = None,
    failed: dict[str, str] | None = None,
    insufficient: list[str] | None = None,
    health: str | None = "healthy",
    catalog_failed: bool = False,
) -> dict[str, Any]:
    return {
        "metrics_requested": CORE,
        "metrics_ok": CORE if ok is None else ok,
        "metrics_failed": failed or {},
        "metrics_insufficient": insufficient or [],
        "health_status": health,
        "catalog_failed": catalog_failed,
    }


def state(evidence: list[dict[str, Any]], coverage: dict[str, Any] | None, **rca: Any) -> dict[str, Any]:
    return {
        "incident": {"service": SVC},
        "evidence": {e["id"]: e for e in evidence},
        "telemetry_coverage": {SVC: coverage} if coverage else {},
        "status": "completed",
        "rca": {"hypotheses": [{"confidence": 0.9}], "remediation_plan": [], **rca},
    }


def outcome(st: dict[str, Any]) -> dict[str, Any]:
    st["rca"]["impact"] = assess_impact(st).model_dump(mode="json")
    return determine_outcome(st)


def test_audit_reproduction_no_longer_resolves() -> None:
    """Audit H2: unhealthy service + missing metrics + low confidence + explicit escalation."""
    st = state(
        [ev("h", "service_health", {"status": "unhealthy"}), ev("t", "tool_error", {})],
        cov(ok=[], failed={"http_5xx_ratio": "backend down", "p95_latency_ms": "backend down"}, health="unhealthy"),
        escalation={"required": True, "reason": "observability outage"},
    )
    st["rca"]["hypotheses"] = [{"confidence": 0.1}]
    o = outcome(st)
    assert st["rca"]["impact"]["state"] == "ongoing"  # the health check is affirmative evidence of impact
    assert o["code"] == "escalated" and o["escalate"] is True


def test_metrics_unavailable_is_unknown() -> None:
    st = state([], cov(ok=[], failed={m: "timeout" for m in CORE}, health=None))
    assert assess_impact(st).state.value == "unknown"
    o = outcome(st)
    assert o["code"] == "impact_unknown" and o["escalate"] is True


def test_telemetry_never_collected_is_unknown() -> None:
    assert assess_impact(state([], None)).state.value == "unknown"


def test_incomplete_telemetry_is_unknown() -> None:
    insufficient = assess_impact(state([], cov(ok=["http_5xx_ratio"], insufficient=["p95_latency_ms"])))
    assert insufficient.state.value == "unknown" and any("insufficient" in r for r in insufficient.reasons)
    catalog = assess_impact(state([], cov(ok=[], catalog_failed=True, health="healthy")))
    assert catalog.state.value == "unknown"


def test_tool_failure_on_one_core_metric_is_unknown_even_if_others_look_fine() -> None:
    st = state(
        [ev("m", "metric_anomaly", {"metric": "p95_latency_ms", "anomaly": False})],
        cov(ok=["p95_latency_ms"], failed={"http_5xx_ratio": "500 from metrics backend"}),
    )
    assert assess_impact(st).state.value == "unknown"


def test_unknown_health_is_not_recovery() -> None:
    assert assess_impact(state([], cov(health=None))).state.value == "unknown"


def test_conflicting_observations_are_unknown() -> None:
    st = state(
        [
            ev("m", "metric_anomaly", {"metric": "http_5xx_ratio", "recovered": True}),
            ev("h", "service_health", {"status": "unhealthy"}),
        ],
        cov(health="unhealthy"),
    )
    a = assess_impact(st)
    assert a.state.value == "unknown" and "conflicting" in a.reasons[0]


def test_unrecovered_anomaly_is_ongoing() -> None:
    st = state([ev("m", "metric_anomaly", {"metric": "http_5xx_ratio", "recovered": False})], cov())
    assert assess_impact(st).state.value == "ongoing"


def test_genuine_recovery_requires_complete_healthy_observations() -> None:
    st = state([ev("m", "metric_anomaly", {"metric": "http_5xx_ratio", "recovered": True})], cov())
    a = assess_impact(st)
    assert a.state.value == "recovered" and "m" in a.evidence_ids
    assert outcome(st)["code"] == "no_action_required"


def test_explicit_escalation_overrides_recovery() -> None:
    st = state(
        [ev("m", "metric_anomaly", {"metric": "http_5xx_ratio", "recovered": True})],
        cov(),
        escalation={"required": True, "reason": "customer reports continue"},
    )
    assert outcome(st)["code"] == "escalated"


def test_assessment_is_stable_across_serialisation_restart() -> None:
    """Impact is recomputed from checkpointed (JSON) state, so a restart yields the same assessment."""
    st = state(
        [ev("m", "metric_anomaly", {"metric": "http_5xx_ratio", "recovered": True})],
        cov(failed={"p95_latency_ms": "x"}),
    )
    again = json.loads(json.dumps(st))
    assert assess_impact(st) == assess_impact(again)


def test_legacy_records_without_impact_are_treated_conservatively() -> None:
    st = state([], cov())
    st["rca"]["impact_ongoing"] = False  # Phase B record shape: boolean only
    assert determine_outcome(st)["code"] == "impact_unknown"


@pytest.mark.parametrize(
    "impact_cov, category",
    [
        (cov(ok=[], failed={m: "down" for m in CORE}, health=None), "insufficient_evidence"),
    ],
)
async def test_unknown_impact_blocks_proposals(impact_cov: dict[str, Any], category: str) -> None:
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]
    dep = ev(
        "d",
        "deployment",
        {"id": "dep-x", "service": SVC, "kind": "application", "status": "succeeded", "correlation": 0.9},
    )
    st = state([dep], impact_cov)
    st["investigation_id"] = "00000000-0000-0000-0000-000000000021"
    st["rca"]["remediation_plan"] = [{"action_type": "rollback_deployment", "deployment_id": "dep-x"}]
    out = await nodes.propose(st)  # type: ignore[arg-type]
    assert out["remediation_plan"] == [] and out["rejected_proposals"][0]["category"] == category
    assert "unknown" in out["rejected_proposals"][0]["reason"]
