"""H4 regression: verification checks every required condition and never silently skips one."""

from datetime import UTC, datetime, timedelta
from typing import Any

from opspilot_agents.nodes import AgentDeps, AgentPolicy, InvestigationNodes
from opspilot_agents.report import determine_outcome
from tests.fakes.gateway import ScriptedGateway

T = datetime(2026, 11, 3, 14, tzinfo=UTC)


def anomaly(
    i: int,
    metric: str,
    *,
    baseline: float = 0.0,
    extreme: float = 1.0,
    direction: str = "up",
    unit: str = "ratio",
    service: str = "svc",
) -> dict[str, Any]:
    return {
        "id": f"ev-m{i}",
        "kind": "metric_anomaly",
        "service": service,
        "relevance": 0.9,
        "summary": "",
        "data": {
            "metric": metric,
            "unit": unit,
            "baseline": baseline,
            "extreme": extreme,
            "direction": direction,
            "recovered": False,
        },
    }


def series(value: float) -> dict[str, Any]:
    return {"points": [{"ts": (T + timedelta(minutes=i)).isoformat(), "value": value} for i in range(6)]}


def make_state(
    evidence: list[dict[str, Any]],
    plan: list[dict[str, Any]] | None = None,
    executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    window = {"executed_at_sim": T.isoformat(), "sim_now_after": (T + timedelta(minutes=10)).isoformat()}
    return {
        "incident": {"service": "svc", "environment_id": "env"},
        "tool_calls": [],
        "evidence": {e["id"]: e for e in evidence},
        "rca": {"hypotheses": [{"supporting_evidence_ids": []}]},
        "remediation_plan": plan or [],
        "executions": executions or [{"status": "succeeded", "step": 99, "details": window}],
    }


async def run(state: dict[str, Any], gw: ScriptedGateway, **policy: Any) -> dict[str, Any]:
    nodes = InvestigationNodes(
        AgentDeps(
            chat=None,
            tools=gw,
            actions=None,  # type: ignore[arg-type]
            policy=AgentPolicy(**policy),
        )
    )
    return (await nodes.verify(state))["verification"]  # type: ignore[arg-type]


def metrics(values: dict[str, float | None]) -> ScriptedGateway:
    return ScriptedGateway(
        {"query_metrics": lambda a: None if values.get(a["metric"]) is None else series(values[a["metric"]])}
    )  # type: ignore[arg-type]


async def test_audit_reproduction_fifth_anomaly_is_checked() -> None:
    """Audit H4: five unrecovered anomalies, only the fifth still broken."""
    ev = [anomaly(i, f"m{i}") for i in range(5)]
    gw = metrics({f"m{i}": (0.9 if i == 4 else 0.0) for i in range(5)})
    v = await run(make_state(ev), gw)
    assert [a["metric"] for _, a in gw.calls] == ["m0", "m1", "m2", "m3", "m4"]
    assert v["status"] == "not_recovered" and v["recovered"] is False
    assert [c["name"] for c in v["checks"] if c["status"] == "failed"] == ["m4"]


async def test_missing_verification_metric_is_incomplete_not_recovered() -> None:
    v = await run(make_state([anomaly(0, "m0"), anomaly(1, "m1")]), metrics({"m0": 0.0, "m1": None}))
    assert v["status"] == "incomplete" and v["recovered"] is False
    st = {"status": "completed", "executions": [{"status": "succeeded"}], "verification": v, "rca": {}}
    assert determine_outcome(st)["code"] == "verification_incomplete"


async def test_opposite_direction_excursion_on_unknown_semantics_fails() -> None:
    # m0 rose 0->1 (unknown semantics: two-sided band) and now sits far below baseline.
    v = await run(make_state([anomaly(0, "m0", baseline=10.0, extreme=20.0, unit="widgets")]), metrics({"m0": -30.0}))
    assert v["status"] == "not_recovered" and "opposite-direction" in v["checks"][0]["detail"]


async def test_healthy_side_excursions_pass_for_known_semantics() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.003, extreme=0.4),
        anomaly(1, "events_processed_per_min", baseline=120, extreme=5, direction="down", unit="events/min"),
    ]
    v = await run(make_state(ev), metrics({"http_5xx_ratio": 0.0, "events_processed_per_min": 600.0}))
    assert v["status"] == "recovered"  # 5xx below baseline and backlog drain above baseline are both healthy


async def test_partial_remediation_is_not_recovered() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.003, extreme=0.4),
        anomaly(1, "p95_latency_ms", baseline=180, extreme=2400, unit="ms"),
    ]
    v = await run(make_state(ev), metrics({"http_5xx_ratio": 0.002, "p95_latency_ms": 2300.0}))
    assert v["status"] == "not_recovered"


async def test_insufficient_budget_reports_omitted_checks() -> None:
    ev = [anomaly(i, f"m{i}") for i in range(6)]
    v = await run(make_state(ev), metrics({f"m{i}": 0.0 for i in range(6)}), max_verification_checks=4)
    assert v["status"] == "incomplete" and v["omitted"] == 2 and v["budget"] == 4
    assert [c["status"] for c in v["checks"]].count("not_checked") == 2


async def test_failed_postconditions_block_recovery() -> None:
    queue = {
        "id": "ev-q",
        "kind": "queue",
        "service": "worker",
        "relevance": 0.8,
        "summary": "",
        "data": {"queue": "events", "consumer": {"service": "worker", "state": "running"}, "failures": []},
    }
    plan = [
        {"step": 1, "action_type": "pause_consumer", "parameters": {"service": "worker"}},
        {"step": 2, "action_type": "quarantine_messages", "parameters": {"queue": "events", "error_code": "BAD"}},
    ]
    window = {"executed_at_sim": T.isoformat(), "sim_now_after": (T + timedelta(minutes=10)).isoformat()}
    execs = [
        {"status": "succeeded", "step": 1, "details": window},
        {"status": "succeeded", "step": 2, "details": window},
    ]
    gw = ScriptedGateway(
        {"inspect_queue": lambda a: {"consumer": {"state": "paused"}, "failures": [{"error_code": "BAD", "count": 7}]}}
    )
    v = await run(make_state([queue], plan, execs), gw)
    names = {c["name"]: c["status"] for c in v["checks"]}
    assert names == {"no_unquarantined:events:BAD": "failed", "consumer_running:events": "failed"}
    assert v["status"] == "not_recovered"
    assert len(gw.calls) == 1  # one shared inspect_queue read serves both postconditions


async def test_genuine_full_recovery_with_postconditions() -> None:
    dep = {
        "id": "ev-d",
        "kind": "deployment",
        "service": "svc",
        "relevance": 0.9,
        "summary": "",
        "data": {"id": "dep-1", "service": "svc", "started_at": T.isoformat()},
    }
    plan = [
        {"step": 1, "action_type": "rollback_deployment", "parameters": {"service": "svc", "deployment_id": "dep-1"}}
    ]
    window = {"executed_at_sim": T.isoformat(), "sim_now_after": (T + timedelta(minutes=10)).isoformat()}
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002),
            "list_recent_deployments": lambda a: {"deployments": [{"id": "dep-1", "status": "rolled_back"}]},
        }
    )
    v = await run(
        make_state(
            [anomaly(0, "http_5xx_ratio", baseline=0.003, extreme=0.4), dep],
            plan,
            [{"status": "succeeded", "step": 1, "details": window}],
        ),
        gw,
    )
    assert v["status"] == "recovered" and all(c["status"] == "passed" for c in v["checks"])
    assert {c["kind"] for c in v["checks"]} == {"metric", "postcondition"}
    assert all(c.get("evidence_id") and c.get("tool_call_id") for c in v["checks"])  # evidence-linked


async def test_load_metrics_are_informational_not_required() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.003, extreme=0.4),
        anomaly(1, "http_requests_per_min", baseline=1200, extreme=1500, unit="requests/min"),
    ]
    v = await run(make_state(ev), metrics({"http_5xx_ratio": 0.002}))
    assert v["status"] == "recovered" and v["informational"][0]["metric"] == "http_requests_per_min"


# ----------------------------------------------------------------------------- C0-F1 regression tests
def deployment(service: str, dep_id: str) -> dict[str, Any]:
    return {
        "id": f"ev-deploy-{dep_id}",
        "kind": "deployment",
        "service": service,
        "relevance": 0.9,
        "summary": f"{service} release",
        "data": {"id": dep_id, "service": service, "started_at": T.isoformat()},
    }


def rollback_state(evidence: list[dict[str, Any]], service: str = "worker", dep_id: str = "dep-x") -> dict[str, Any]:
    plan = [
        {"step": 1, "action_type": "rollback_deployment", "parameters": {"service": service, "deployment_id": dep_id}}
    ]
    window = {"executed_at_sim": T.isoformat(), "sim_now_after": (T + timedelta(minutes=10)).isoformat()}
    return make_state(evidence, plan, [{"status": "succeeded", "step": 1, "details": window}])


def rolled_back(dep_id: str = "dep-x") -> Any:
    return lambda a: {"deployments": [{"id": dep_id, "status": "rolled_back"}]}


async def test_codex_f1_reproduction_action_target_anomaly_is_required() -> None:
    """Independent audit reproduction: rollback on ``worker``, a known unrecovered ``worker`` 5xx anomaly, and the
    top hypothesis citing only the alerting service. Before C0-F1 this returned ``recovered`` without querying
    the worker metric."""
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "http_5xx_ratio", baseline=0.002, extreme=0.4, service="worker"),
        deployment("worker", "dep-x"),
    ]
    st = rollback_state(ev)
    st["rca"]["hypotheses"][0]["supporting_evidence_ids"] = ["ev-m0"]
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002 if a["service"] == "svc" else 0.4),
            "list_recent_deployments": rolled_back(),
        }
    )
    v = await run(st, gw)
    assert ("query_metrics", "worker") in {(t, a.get("service")) for t, a in gw.calls}
    assert v["status"] == "not_recovered" and v["recovered"] is False
    assert {(c["service"], c["name"], c["status"]) for c in v["checks"] if c["kind"] == "metric"} == {
        ("svc", "http_5xx_ratio", "passed"),
        ("worker", "http_5xx_ratio", "failed"),
    }
    assert v["scope"]["worker"] == ["action_target"] and v["excluded"] == []
    st = {"status": "completed", "executions": [{"status": "succeeded"}], "verification": v, "rca": {}}
    assert determine_outcome(st)["code"] == "not_recovered"


async def test_scope_does_not_shrink_when_citations_are_removed_or_reordered() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "p95_latency_ms", baseline=50, extreme=900, unit="ms", service="worker"),
        deployment("worker", "dep-x"),
    ]
    results = []
    for cited in ([], ["ev-m0"], ["ev-deploy-dep-x", "ev-m1"], ["ev-m1", "ev-m0"]):
        st = rollback_state(ev)
        st["rca"]["hypotheses"][0]["supporting_evidence_ids"] = cited
        gw = ScriptedGateway(
            {
                "query_metrics": lambda a: series(0.002 if a["service"] == "svc" else 50),
                "list_recent_deployments": rolled_back(),
            }
        )
        v = await run(st, gw)
        results.append(sorted((c["service"], c["name"]) for c in v["checks"]))
    assert all(r == results[0] for r in results)
    assert ("worker", "p95_latency_ms") in results[0]


async def test_multiple_anomalies_on_one_service_are_all_required() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "p95_latency_ms", baseline=180, extreme=2400, unit="ms"),
        anomaly(2, "queue_depth", baseline=40, extreme=900, unit="msgs"),
    ]
    v = await run(make_state(ev), metrics({"http_5xx_ratio": 0.002, "p95_latency_ms": 190, "queue_depth": 600}))
    assert v["required"] == 3 and len(v["checks"]) == 3
    assert v["status"] == "not_recovered"
    assert [c["name"] for c in v["checks"] if c["status"] == "failed"] == ["queue_depth"]


async def test_more_conditions_than_budget_is_incomplete_even_when_all_checked_pass() -> None:
    ev = [anomaly(i, f"m{i}") for i in range(5)] + [anomaly(9, "m9", service="worker"), deployment("worker", "dep-x")]
    gw = ScriptedGateway({"query_metrics": lambda a: series(0.0), "list_recent_deployments": rolled_back()})
    v = await run(rollback_state(ev), gw, max_verification_checks=3)
    assert v["required"] == 7 and v["budget"] == 3 and v["omitted"] == 4
    assert v["status"] == "incomplete" and v["recovered"] is False
    assert all(c["status"] in ("passed", "not_checked") for c in v["checks"])
    st = {"status": "completed", "executions": [{"status": "succeeded"}], "verification": v, "rca": {}}
    assert determine_outcome(st)["code"] == "verification_incomplete"


async def test_tool_budget_exhaustion_cannot_drop_a_required_condition() -> None:
    ev = [anomaly(0, "m0"), anomaly(1, "m1")]
    st = make_state(ev)
    st["tool_calls"] = [{}] * 59  # one call left in the investigation's overall tool budget
    v = await run(st, metrics({"m0": 0.0, "m1": 0.0}))
    assert v["required"] == 2 and v["budget"] == 1
    assert [c["status"] for c in v["checks"]] == ["passed", "not_checked"] and v["status"] == "incomplete"


async def test_one_metric_recovered_another_unhealthy_is_not_recovered() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.003, extreme=0.4),
        anomaly(1, "db_pool_wait_ms", baseline=2, extreme=4000, unit="ms"),
    ]
    v = await run(make_state(ev), metrics({"http_5xx_ratio": 0.002, "db_pool_wait_ms": 3500.0}))
    assert v["status"] == "not_recovered"
    assert {c["name"]: c["status"] for c in v["checks"]} == {"http_5xx_ratio": "passed", "db_pool_wait_ms": "failed"}


def dependency(caller: str, dep: str, status: str) -> dict[str, Any]:
    return {
        "id": f"ev-dep-{caller}-{dep}",
        "kind": "dependency",
        "service": dep,
        "relevance": 0.75,
        "summary": f"{caller} -> {dep}: {status}",
        "data": {
            "edge": {"service": caller, "depends_on": dep, "kind": "sync_http", "critical": True},
            "health": {"service": dep, "status": status, "as_of": T.isoformat()},
        },
    }


async def test_downstream_dependency_still_unhealthy_blocks_recovery() -> None:
    """svc -> ledger (observed degraded) -> ledger-db path; ledger's own anomaly and health are required even though
    no citation names ledger."""
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "p95_latency_ms", baseline=45, extreme=2900, unit="ms", service="ledger"),
        dependency("svc", "ledger", "degraded"),
        dependency("svc", "fx", "healthy"),
        anomaly(2, "p95_latency_ms", baseline=80, extreme=900, unit="ms", service="unrelated"),
    ]
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002 if a["service"] == "svc" else 2500),
            "get_service_health": lambda a: {
                "service": a["service"],
                "status": "degraded",
                "as_of": (T + timedelta(minutes=9)).isoformat(),
            },
        }
    )
    v = await run(make_state(ev), gw)
    assert v["scope"]["ledger"] == ["affected_dependency"] and "fx" not in v["scope"]
    assert v["status"] == "not_recovered"
    failed = {(c["service"], c["kind"]) for c in v["checks"] if c["status"] == "failed"}
    assert failed == {("ledger", "metric"), ("ledger", "health")}
    assert [(x["service"], x["reason"]) for x in v["excluded"]] == [("unrelated", "service_outside_recovery_scope")]


async def test_missing_telemetry_is_unknown_never_recovered() -> None:
    ev = [anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), dependency("svc", "ledger", "unhealthy")]
    gw = ScriptedGateway({"query_metrics": lambda a: series(0.002)})  # get_service_health unavailable
    v = await run(make_state(ev), gw)
    health = [c for c in v["checks"] if c["kind"] == "health"]
    assert [c["status"] for c in health] == ["unknown"] and "tool error" in health[0]["detail"]
    assert v["status"] == "incomplete" and v["recovered"] is False


async def test_conflicting_evidence_metrics_quiet_but_health_unhealthy_is_not_recovered() -> None:
    health_before = {
        "id": "ev-health-svc",
        "kind": "service_health",
        "service": "svc",
        "relevance": 0.6,
        "summary": "",
        "data": {"service": "svc", "status": "unhealthy", "as_of": T.isoformat()},
    }
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002),
            "get_service_health": lambda a: {
                "service": "svc",
                "status": "unhealthy",
                "as_of": (T + timedelta(minutes=9)).isoformat(),
            },
        }
    )
    v = await run(make_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), health_before]), gw)
    assert {c["kind"]: c["status"] for c in v["checks"]} == {"metric": "passed", "health": "failed"}
    assert v["status"] == "not_recovered"


async def test_stale_health_observation_is_unknown() -> None:
    health_before = {
        "id": "ev-health-svc",
        "kind": "service_health",
        "service": "svc",
        "relevance": 0.6,
        "summary": "",
        "data": {"service": "svc", "status": "degraded", "as_of": T.isoformat()},
    }
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002),
            "get_service_health": lambda a: {
                "service": "svc",
                "status": "healthy",
                "as_of": (T - timedelta(minutes=5)).isoformat(),
            },
        }
    )
    v = await run(make_state([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4), health_before]), gw)
    assert [c["status"] for c in v["checks"] if c["kind"] == "health"] == ["unknown"]
    assert v["status"] == "incomplete"


def test_improved_but_unhealthy_metric_is_not_recovered() -> None:
    """Independent audit: 0.2% baseline, 40% excursion, 8% afterwards passed the old relative bound (10.15%)."""
    from opspilot_agents.verification import evaluate_metric, metric_conditions

    [c], _ = metric_conditions([anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4)])
    r = evaluate_metric(c, [0.08] * 3)
    assert r["status"] == "failed" and "improved but not recovered" in r["detail"]
    assert evaluate_metric(c, [0.004] * 3)["status"] == "passed"  # within one point of the normal error ratio


def test_metric_specific_ranges_keep_measured_recoveries() -> None:
    """Recovered values from the archived C0 traces stay inside the tightened ranges."""
    from opspilot_agents.verification import evaluate_metric, metric_conditions

    cases = [  # metric, unit, baseline, extreme, observed-after (from history traces)
        ("http_5xx_ratio", "ratio", 0.0023, 0.15951, 0.00308),
        ("p95_latency_ms", "ms", 181.25, 2709.7, 191.4),
        ("db_pool_in_use", "connections", 13.46, 40.0, 16.68),
        ("db_pool_wait_ms", "ms", 1.97, 4276.0, 2.7),
        ("dlq_depth", "messages", 12.0, 3254.0, 12.0),
        ("queue_depth", "messages", 43.7, 266.0, 40.0),
        ("validation_failures_per_min", "per_min", 0.0, 112.0, 0.0),
    ]
    for metric, unit, b, x, after in cases:
        [c], _ = metric_conditions([anomaly(0, metric, baseline=b, extreme=x, unit=unit)])
        assert evaluate_metric(c, [after] * 3)["status"] == "passed", metric


def test_outcome_refuses_a_recovered_record_with_unpassed_checks() -> None:
    """Defence in depth: a verification record that claims recovery but carries a failed/unknown/not-checked
    condition, or fewer checks than required conditions, never maps to ``mitigated``."""
    base = {"status": "completed", "executions": [{"status": "succeeded"}], "rca": {}}
    for checks, required in (
        ([{"status": "passed"}, {"status": "unknown"}], 2),
        ([{"status": "passed"}, {"status": "not_checked"}], 2),
        ([{"status": "passed"}], 2),
        ([], 0),
    ):
        v = {"status": "recovered", "recovered": True, "checks": checks, "required": required}
        assert determine_outcome({**base, "verification": v})["code"] != "mitigated"
    ok = {"status": "recovered", "recovered": True, "checks": [{"status": "passed"}], "required": 1}
    assert determine_outcome({**base, "verification": ok})["code"] == "mitigated"


async def test_genuine_complete_recovery_across_scope() -> None:
    ev = [
        anomaly(0, "http_5xx_ratio", baseline=0.002, extreme=0.4),
        anomaly(1, "p95_latency_ms", baseline=45, extreme=2900, unit="ms", service="worker"),
        dependency("svc", "worker", "degraded"),
        deployment("worker", "dep-x"),
    ]
    gw = ScriptedGateway(
        {
            "query_metrics": lambda a: series(0.002 if a["service"] == "svc" else 47),
            "get_service_health": lambda a: {
                "service": a["service"],
                "status": "healthy",
                "as_of": (T + timedelta(minutes=9)).isoformat(),
            },
            "list_recent_deployments": rolled_back(),
        }
    )
    v = await run(rollback_state(ev), gw)
    assert v["status"] == "recovered" and v["recovered"] is True
    assert {c["kind"] for c in v["checks"]} == {"metric", "health", "postcondition"}
    assert v["scope"]["worker"] == ["action_target", "affected_dependency"]
    assert all(c["status"] == "passed" and c.get("tool_call_id") for c in v["checks"])
