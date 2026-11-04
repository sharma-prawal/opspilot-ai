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
