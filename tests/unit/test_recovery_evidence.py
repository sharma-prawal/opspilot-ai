"""C0-G1 regression: recovery needs complete, affirmative, fresh evidence for every required condition.

Covers the two independent-audit counterexamples (unknown initial health; a known-unhealthy dependency hidden by a
missing edge snapshot) and the generic cases the invariant must hold for. No incident identifiers are involved.
"""

import json
from datetime import timedelta
from typing import Any

from opspilot_agents.report import determine_outcome, verified_recovered
from opspilot_agents.verification import initial_health, required_conditions
from tests.fakes.gateway import ScriptedGateway
from tests.unit.test_verification import T, anomaly, deployment, fresh_health, make_state, rollback_state, run, series


def health_ev(svc: str, status: str, eid: str | None = None) -> dict[str, Any]:
    return {
        "id": eid or f"ev-health-{svc}",
        "kind": "service_health",
        "service": svc,
        "relevance": 0.6,
        "summary": "",
        "data": {"service": svc, "status": status, "as_of": T.isoformat()},
    }


def edge(caller: str, dep: str, snapshot: str | None) -> dict[str, Any]:
    return {
        "id": f"ev-dep-{caller}-{dep}",
        "kind": "dependency",
        "service": dep,
        "relevance": 0.3,
        "summary": "",
        "data": {
            "edge": {"service": caller, "depends_on": dep, "kind": "sync_http", "critical": True},
            "health": None if snapshot is None else {"service": dep, "status": snapshot, "as_of": T.isoformat()},
        },
    }


def outcome(state: dict[str, Any], v: dict[str, Any]) -> str:
    rca = {"hypotheses": [{**state["rca"]["hypotheses"][0], "confidence": 0.9}]}  # schema-shaped RCA
    return determine_outcome({**state, "rca": rca, "verification": v, "status": "completed"})["code"]


def gateway(metric_values: dict[str, float], health: dict[str, str], rolled: bool = True) -> ScriptedGateway:
    return ScriptedGateway(
        {
            "query_metrics": lambda a: series(metric_values[a["service"]]),
            "get_service_health": lambda a: (
                None
                if health.get(a["service"]) is None
                else {
                    "service": a["service"],
                    "status": health[a["service"]],
                    "as_of": (T + timedelta(minutes=9)).isoformat(),
                }
            ),
            "list_recent_deployments": lambda a: {
                "deployments": [{"id": "dep-x", "status": "rolled_back" if rolled else "succeeded"}]
            },
        }
    )


# ----------------------------------------------------------------------------- the audit counterexamples
async def test_codex_r1_unknown_initial_health_is_never_mitigated() -> None:
    """Independent C0-F audit R1: alerting/action-target service with *unknown* initial health and an ongoing
    anomaly; the metric recovers and the rollback took effect, but health still reads unknown. Before C0-G1 no health
    condition was generated and the outcome was ``mitigated``."""
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        deployment("svc", "dep-x"),
        health_ev("svc", "unknown"),
    ]
    st = rollback_state(ev, service="svc")
    gw = gateway({"svc": 0.002}, {"svc": "unknown"})
    v = await run(st, gw)
    assert ("get_service_health", "svc") in {(t, a.get("service")) for t, a in gw.calls}
    assert v["status"] == "incomplete" and v["verdict"] == "INCOMPLETE"
    assert outcome(st, v) == "verification_incomplete"


async def test_codex_r2_unhealthy_dependency_with_missing_edge_snapshot_stays_required() -> None:
    """Independent C0-F audit R2: the svc -> downstream edge carries no health snapshot (its read failed), but
    separate evidence shows downstream unhealthy with an unrecovered anomaly. Before C0-G1 downstream was excluded as
    "outside the affected path" and the run ended ``mitigated``."""
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        deployment("svc", "dep-x"),
        health_ev("svc", "unhealthy"),
        edge("svc", "downstream", None),
        health_ev("downstream", "unhealthy"),
        anomaly(1, "http_5xx_ratio", baseline=0.002, extreme=0.4, service="downstream"),
    ]
    st = rollback_state(ev, service="svc")
    gw = gateway({"svc": 0.002, "downstream": 0.4}, {"svc": "healthy", "downstream": "unhealthy"})
    v = await run(st, gw)
    assert v["scope"]["downstream"] == ["affected_dependency"] and v["excluded"] == []
    assert {(c["service"], c["kind"]) for c in v["checks"] if c["status"] == "failed"} == {
        ("downstream", "metric"),
        ("downstream", "health"),
    }
    assert v["status"] == "not_recovered" and outcome(st, v) == "not_recovered"


# ----------------------------------------------------------------------------- initial evidence
async def test_initial_health_unknown_with_no_health_read_at_all_requires_positive_health() -> None:
    st = rollback_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")], "svc")
    v = await run(st, gateway({"svc": 0.002}, {}))  # health unavailable after the action
    health = [c for c in v["checks"] if c["kind"] == "health"]
    assert [(c["service"], c["status"]) for c in health] == [("svc", "unknown")]
    assert v["status"] == "incomplete" and outcome(st, v) == "verification_incomplete"


async def test_initial_metrics_missing_is_incomplete_even_when_everything_read_now_is_healthy() -> None:
    st = rollback_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")], "svc")
    st["telemetry_coverage"] = {
        "svc": {"metrics_failed": {"p95_latency_ms": "timeout"}, "metrics_insufficient": [], "catalog_failed": False}
    }
    v = await run(st, gateway({"svc": 0.002}, {"svc": "healthy"}))
    baseline = [c for c in v["checks"] if c["kind"] == "baseline"]
    assert [(c["name"], c["status"]) for c in baseline] == [("initial:p95_latency_ms", "unknown")]
    assert v["status"] == "incomplete" and outcome(st, v) == "verification_incomplete"


async def test_missing_metric_catalogue_and_insufficient_points_are_gaps() -> None:
    st = make_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4)])
    st["telemetry_coverage"] = {
        "svc": {
            "metrics_failed": {},
            "metrics_insufficient": ["queue_depth", "http_requests_per_min"],
            "catalog_failed": True,
        }
    }
    v = await run(st, gateway({"svc": 0.002}, {"svc": "healthy"}))
    names = sorted(c["name"] for c in v["checks"] if c["kind"] == "baseline")
    assert names == ["initial:metric_catalogue", "initial:queue_depth"]  # load metric stays informational
    assert v["status"] == "incomplete"


async def test_healthy_snapshot_without_any_failure_evidence_is_not_confirmed_recovery() -> None:
    st = rollback_state([deployment("svc", "dep-x"), health_ev("svc", "healthy")], "svc")
    v = await run(st, gateway({}, {"svc": "healthy"}))
    assert [c["name"] for c in v["checks"] if c["kind"] == "baseline"] == ["failure_evidence"]
    assert all(c["status"] == "passed" for c in v["checks"] if c["kind"] != "baseline")
    assert v["status"] == "incomplete" and outcome(st, v) == "verification_incomplete"


# ----------------------------------------------------------------------------- scope
async def test_healthy_action_target_with_unhealthy_dependency_is_not_recovered() -> None:
    ev = [
        anomaly(0, "p95_latency_ms", baseline=50, extreme=900, unit="ms"),
        deployment("svc", "dep-x"),
        edge("svc", "db-proxy", "healthy"),  # stale edge snapshot says healthy ...
        health_ev("db-proxy", "degraded"),  # ... an independent read says degraded
    ]
    st = rollback_state(ev, service="svc")
    v = await run(st, gateway({"svc": 50}, {"svc": "healthy", "db-proxy": "degraded"}))
    assert initial_health(st)["db-proxy"]["conflict"] is True
    assert v["services"]["db-proxy"] == {
        "reasons": ["affected_dependency"],
        "initial": "UNHEALTHY",
        "initial_conflict": True,
        "current": "UNHEALTHY",
    }
    assert v["status"] == "not_recovered"


async def test_known_anomaly_outside_target_selection_and_citations_stays_required() -> None:
    """Only svc is cited and targeted; `billing` has a persistent anomaly but no observed edge to the scope. It is no
    longer excluded: a known failure cannot disappear because ranking/selection left it out."""
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "http_5xx_ratio", baseline=0.002, extreme=0.3, service="billing"),
        deployment("svc", "dep-x"),
    ]
    st = rollback_state(ev, service="svc")
    st["rca"]["hypotheses"][0]["supporting_evidence_ids"] = ["ev-m0"]
    v = await run(st, gateway({"svc": 0.002, "billing": 0.3}, {"svc": "healthy", "billing": "unhealthy"}))
    assert v["scope"]["billing"] == ["known_unhealthy"] and v["excluded"] == []
    assert v["status"] == "not_recovered"


async def test_multiple_unhealthy_dependencies_transitively_are_all_required() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        deployment("svc", "dep-x"),
        edge("svc", "a", None),
        edge("a", "b", None),
        edge("svc", "c", "healthy"),
        health_ev("a", "degraded"),
        anomaly(1, "p95_latency_ms", baseline=40, extreme=800, unit="ms", service="b"),
        health_ev("c", "healthy"),
    ]
    st = rollback_state(ev, service="svc")
    all_ok = {"svc": "healthy", "a": "healthy", "b": "healthy"}
    v = await run(st, gateway({"svc": 0.002, "b": 41}, all_ok))
    assert v["scope"]["a"] == ["affected_dependency"] and v["scope"]["b"] == ["affected_dependency"]
    assert "c" not in v["scope"]
    assert v["status"] == "recovered" and outcome(st, v) == "mitigated"
    v = await run(st, gateway({"svc": 0.002, "b": 41}, {**all_ok, "b": "unhealthy"}))
    assert v["status"] == "not_recovered"


# ----------------------------------------------------------------------------- verification
async def test_incomplete_budget_never_mitigates() -> None:
    ev = [anomaly(i, f"m{i}") for i in range(3)] + [deployment("svc", "dep-x")]
    st = rollback_state(ev, service="svc")
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.0),
            "get_service_health": fresh_health(),
            "list_recent_deployments": lambda a: {},
        }
    )
    v = await run(st, gw, max_verification_checks=2)
    assert v["status"] == "incomplete" and v["omitted"] >= 1 and outcome(st, v) == "verification_incomplete"


async def test_failed_postcondition_is_not_recovered() -> None:
    st = rollback_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")], "svc")
    v = await run(st, gateway({"svc": 0.002}, {"svc": "healthy"}, rolled=False))
    assert [c["status"] for c in v["checks"] if c["kind"] == "postcondition"] == ["failed"]
    assert v["verdict"] == "FAILED" and outcome(st, v) == "not_recovered"


async def test_partial_improvement_is_not_recovered() -> None:
    st = rollback_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")], "svc")
    v = await run(st, gateway({"svc": 0.08}, {"svc": "healthy"}))
    [m] = [c for c in v["checks"] if c["kind"] == "metric"]
    assert m["status"] == "failed" and "improved but not recovered" in m["detail"]
    assert outcome(st, v) == "not_recovered"


async def test_stale_or_untimestamped_post_action_health_is_unknown() -> None:
    st = rollback_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")], "svc")
    for reading in (
        {"status": "healthy", "as_of": (T - timedelta(minutes=1)).isoformat()},
        {"status": "healthy"},
    ):
        gw = ScriptedGateway(
            {
                "query_metrics": lambda a: series(0.002),
                "get_service_health": lambda a, r=reading: {"service": a["service"], **r},
                "list_recent_deployments": lambda a: {"deployments": [{"id": "dep-x", "status": "rolled_back"}]},
            }
        )
        v = await run(st, gw)
        assert [c["status"] for c in v["checks"] if c["kind"] == "health"] == ["unknown"]
        assert outcome(st, v) == "verification_incomplete"


async def test_conflicting_initial_observations_resolve_to_unhealthy() -> None:
    """A healthy health read alongside a persistent failing anomaly: the service is initially UNHEALTHY (conflict
    recorded), so a positive post-action health read *and* the metric are both required."""
    ev = [health_ev("svc", "healthy"), anomaly(0, "dlq_depth", baseline=10, extreme=3000, unit="messages")]
    st = make_state(ev)
    states = initial_health(st)
    assert states["svc"]["status"] == "unhealthy" and states["svc"]["conflict"] is True
    v = await run(st, gateway({"svc": 10}, {"svc": "healthy"}))
    assert {c["kind"] for c in v["checks"]} == {"metric", "health"} and v["status"] == "recovered"
    v = await run(st, gateway({"svc": 10}, {"svc": "degraded"}))
    assert v["status"] == "not_recovered"


async def test_genuine_full_recovery_from_unknown_initial_health() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        deployment("svc", "dep-x"),
        health_ev("svc", "unknown"),
        edge("svc", "ledger", None),
        health_ev("ledger", "unhealthy"),
    ]
    st = rollback_state(ev, service="svc")
    v = await run(st, gateway({"svc": 0.002}, {"svc": "healthy", "ledger": "healthy"}))
    assert v["status"] == "recovered" and v["verdict"] == "VERIFIED"
    assert {s: x["current"] for s, x in v["services"].items()} == {"svc": "HEALTHY", "ledger": "HEALTHY"}
    assert outcome(st, v) == "mitigated"
    # restart: JSON-compatible state round-trips and re-derives the same requirement set
    restored = json.loads(json.dumps({**st, "verification": v}))
    assert outcome(restored, restored["verification"]) == "mitigated"


# ----------------------------------------------------------------------------- outcome-time re-derivation
async def test_outcome_rederives_conditions_and_refuses_an_incomplete_record() -> None:
    """A C0-G record that claims recovery but lacks a check for a re-derived required condition (e.g. a health
    condition dropped by a generation bug, or a tampered checkpoint) is never ``mitigated``."""
    ev = [anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), deployment("svc", "dep-x")]
    st = rollback_state(ev, service="svc")
    v = await run(st, gateway({"svc": 0.002}, {"svc": "healthy"}))
    assert verified_recovered(v, st) is True
    trimmed = {**v, "checks": [c for c in v["checks"] if c["kind"] != "health"]}
    trimmed["required"] = len(trimmed["checks"])
    assert verified_recovered(trimmed, st) is False
    assert verified_recovered(v, None) is False  # cannot re-derive: fail closed
    # evidence added after verification (a newly known failure) also blocks the claim
    st2 = {**st, "evidence": {**st["evidence"], "ev-x": anomaly(7, "dlq_depth", baseline=1, extreme=900, service="q")}}
    assert verified_recovered(v, st2) is False
    assert len(required_conditions(st2).conditions) > len(required_conditions(st).conditions)
