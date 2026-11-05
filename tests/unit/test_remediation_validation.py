"""Evidence-based safety rules for remediation steps (no scenario knowledge involved)."""

from typing import Any

from opspilot_agents.nodes import AgentDeps, InvestigationNodes
from opspilot_agents.remediation import validate_step


def ev(eid: str, kind: str, service: str | None, data: dict[str, Any]) -> dict[str, Any]:
    return {"id": eid, "kind": kind, "service": service, "relevance": 0.8, "summary": eid, "data": data}


CFG = ev(
    "ev-config-1",
    "service_config",
    "ledger-service",
    {"service": "ledger-service", "replicas": 4, "config": {"db.datastore": "ledger-db", "db.pool.max": 40}},
)
DS = ev(
    "ev-ds-1",
    "datastore",
    "ledger-db",
    {
        "datastore": "ledger-db",
        "max_connections": 200,
        "reserved_superuser_connections": 3,
        "connections_active": 186,
        "connections_by_client": {"ledger-service": 160, "reporting-etl": 18},
    },
)
QUEUE = ev(
    "ev-queue-1",
    "queue",
    "settlement-worker",
    {
        "queue": "settlement-events",
        "consumer": {"service": "settlement-worker", "state": "running"},
        "failures": [{"error_code": "SETTLEMENT_SCHEMA_INVALID", "count": 10}],
        "producers": ["transaction-api"],
    },
)


def evidence(*items: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in items}


def test_any_pool_increase_is_unsafe_when_datastore_already_near_capacity() -> None:
    chk = validate_step(
        {"action_type": "scale_connection_pool", "service": "ledger-service", "max_connections": 42},
        evidence(CFG, DS),
        "transaction-api",
    )
    assert not chk.ok and chk.category == "unsafe"  # 186/197 usable already exceeds the 90% headroom


def test_pool_increase_beyond_datastore_capacity_is_unsafe() -> None:
    chk = validate_step(
        {"action_type": "scale_connection_pool", "service": "ledger-service", "max_connections": 60},
        evidence(CFG, DS),
        "transaction-api",
    )
    assert not chk.ok and chk.category == "unsafe" and chk.details
    assert chk.details["projected_connections"] == 186 - 160 + 240  # 266 > 90% of 197


def test_pool_increase_within_capacity_is_allowed_but_bounded() -> None:
    roomy = ev("ev-ds-3", "datastore", "ledger-db", {**DS["data"], "max_connections": 300})
    ok = validate_step(
        {"action_type": "scale_connection_pool", "service": "ledger-service", "max_connections": 42},
        evidence(CFG, roomy),
        "transaction-api",
    )
    assert ok.ok and ok.params == {"service": "ledger-service", "max_connections": 42}
    small_ds = ev(
        "ev-ds-2", "datastore", "ledger-db", {**DS["data"], "max_connections": 2000, "connections_active": 186}
    )
    doubled = validate_step(
        {"action_type": "scale_connection_pool", "service": "ledger-service", "max_connections": 120},
        evidence(CFG, small_ds),
        "transaction-api",
    )
    assert not doubled.ok and "per-step limit" in doubled.reason


def test_pool_change_without_capacity_evidence_is_refused() -> None:
    chk = validate_step(
        {"action_type": "scale_connection_pool", "service": "ledger-service", "max_connections": 42},
        evidence(CFG),
        "transaction-api",
    )
    assert not chk.ok and chk.category == "unsafe" and "capacity" in chk.reason


def test_queue_actions_require_queue_evidence() -> None:
    e = evidence(QUEUE)
    assert validate_step({"action_type": "pause_consumer", "service": "settlement-worker"}, e, "settlement-worker").ok
    assert validate_step({"action_type": "resume_consumer", "service": "settlement-worker"}, e, "settlement-worker").ok
    q = validate_step(
        {"action_type": "quarantine_messages", "queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"},
        e,
        "settlement-worker",
    )
    assert q.ok and q.params == {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"}
    wildcard = validate_step(
        {"action_type": "quarantine_messages", "queue": "settlement-events", "error_code": "*"}, e, "settlement-worker"
    )
    assert not wildcard.ok and "not observed" in wildcard.reason
    assert not validate_step(
        {"action_type": "quarantine_messages", "queue": "other-queue", "error_code": "X"}, e, "settlement-worker"
    ).ok


async def test_multi_step_plan_gets_ordered_stable_action_ids() -> None:
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]
    dep = ev(
        "ev-deploy-1",
        "deployment",
        "transaction-api",
        {
            "id": "dep-ta-3180",
            "service": "transaction-api",
            "kind": "application",
            "status": "succeeded",
            "correlation": 1.0,
        },
    )
    anom = ev(
        "ev-metric-1",
        "metric_anomaly",
        "settlement-worker",
        {"metric": "events_processed_per_min", "recovered": False, "baseline": 120, "extreme": 5},
    )
    plan = [
        {"action_type": "pause_consumer", "service": "settlement-worker"},
        {"action_type": "rollback_deployment", "deployment_id": "dep-ta-3180"},
        {"action_type": "quarantine_messages", "queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"},
        {"action_type": "pause_consumer", "service": "settlement-worker"},  # duplicate: dropped
        {"action_type": "resume_consumer", "service": "settlement-worker"},
    ]
    st = {
        "investigation_id": "00000000-0000-0000-0000-000000000009",
        "incident": {"service": "settlement-worker"},
        "evidence": evidence(QUEUE, dep, anom),
        "rca": {"remediation_plan": plan, "hypotheses": [{"confidence": 0.9}]},  # confident diagnosis
    }
    out = await nodes.propose(st)
    steps = out["remediation_plan"]
    assert [s["action_type"] for s in steps] == [
        "pause_consumer",
        "rollback_deployment",
        "quarantine_messages",
        "resume_consumer",
    ]
    assert [s["role"] for s in steps] == ["containment", "resolution", "recovery", "recovery"]
    assert out["proposed_action"] == steps[0] and len({s["action_id"] for s in steps}) == 4
    assert (await nodes.propose(st))["remediation_plan"][2]["action_id"] == steps[2]["action_id"]


def dep_ev(eid: str, dep_id: str, service: str, corr: float, kind: str = "deployment") -> dict[str, Any]:
    return ev(
        eid,
        kind,
        service,
        {"id": dep_id, "service": service, "kind": "application", "status": "succeeded", "correlation": corr},
    )


def test_rollback_requires_correlation_with_onset() -> None:
    chk = validate_step(
        {"action_type": "rollback_deployment", "deployment_id": "dep-old"},
        evidence(dep_ev("e1", "dep-old", "settlement-worker", 0.0)),
        "transaction-api",
    )
    assert not chk.ok and "does not correlate" in chk.reason


def test_ambiguous_candidates_block_rollback() -> None:
    e = evidence(
        dep_ev("e1", "dep-a", "ledger-service", 0.9), dep_ev("e2", "cfg-b", "ledger-service", 0.85, "config_change")
    )
    chk = validate_step({"action_type": "rollback_deployment", "deployment_id": "dep-a"}, e, "transaction-api")
    assert not chk.ok and chk.category == "insufficient_evidence" and "cfg-b" in chk.reason
    clear = evidence(
        dep_ev("e1", "dep-a", "ledger-service", 1.0), dep_ev("e2", "cfg-b", "ledger-service", 0.6, "config_change")
    )
    assert validate_step({"action_type": "rollback_deployment", "deployment_id": "dep-a"}, clear, "transaction-api").ok


def test_rollback_blocked_when_errors_blame_an_unchanged_unhealthy_dependency() -> None:
    log = ev(
        "l1",
        "log_pattern",
        "transaction-api",
        {"level": "ERROR", "count": 90, "attributes": {"upstream": "fx-rates-provider"}},
    )
    dep_health = ev("d1", "dependency", "fx-rates-provider", {"health": {"status": "unhealthy"}})
    e = evidence(dep_ev("e1", "dep-ta", "transaction-api", 0.8), log, dep_health)
    chk = validate_step({"action_type": "rollback_deployment", "deployment_id": "dep-ta"}, e, "transaction-api")
    assert not chk.ok and "fx-rates-provider" in chk.reason
    # If the blamed dependency is the one that changed, reverting it is consistent (INC-001 shape).
    log2 = ev(
        "l2",
        "log_pattern",
        "transaction-api",
        {"level": "ERROR", "count": 90, "attributes": {"upstream": "ledger-service"}},
    )
    led = ev("d2", "dependency", "ledger-service", {"health": {"status": "unhealthy"}})
    e2 = evidence(dep_ev("e2", "dep-ls", "ledger-service", 1.0), log2, led)
    assert validate_step({"action_type": "rollback_deployment", "deployment_id": "dep-ls"}, e2, "transaction-api").ok


def test_dlq_name_is_normalised_to_primary_queue() -> None:
    q = ev("q1", "queue", "settlement-worker", {**QUEUE["data"], "dead_letter_queue": "settlement-events.dlq"})
    chk = validate_step(
        {
            "action_type": "quarantine_messages",
            "queue": "settlement-events.dlq",
            "error_code": "SETTLEMENT_SCHEMA_INVALID",
        },
        evidence(q),
        "settlement-worker",
    )
    assert chk.ok and chk.params == {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"}


async def test_no_remediation_when_impact_has_ended() -> None:
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]
    recovered = ev("m1", "metric_anomaly", "transaction-api", {"metric": "http_5xx_ratio", "recovered": True})
    st = {
        "investigation_id": "00000000-0000-0000-0000-000000000010",
        "incident": {"service": "transaction-api"},
        "evidence": evidence(recovered, dep_ev("e1", "dep-x", "transaction-api", 0.9)),
        # Genuine recovery requires complete, healthy observations (H2), not merely a recovered anomaly.
        "telemetry_coverage": {
            "transaction-api": {
                "metrics_requested": ["http_5xx_ratio", "p95_latency_ms"],
                "metrics_ok": ["http_5xx_ratio", "p95_latency_ms"],
                "metrics_failed": {},
                "metrics_insufficient": [],
                "health_status": "healthy",
                "catalog_failed": False,
            }
        },
        "rca": {"remediation_plan": [{"action_type": "rollback_deployment", "deployment_id": "dep-x"}]},
    }
    out = await nodes.propose(st)
    assert out["remediation_plan"] == [] and out["rejected_proposals"][0]["category"] == "unwarranted"


async def test_policy_appends_resume_for_paused_consumer() -> None:
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]
    anom = ev("m1", "metric_anomaly", "settlement-worker", {"metric": "events_processed_per_min", "recovered": False})
    st = {
        "investigation_id": "00000000-0000-0000-0000-000000000011",
        "incident": {"service": "settlement-worker"},
        "evidence": evidence(QUEUE, anom),
        "rca": {
            "remediation_plan": [{"action_type": "pause_consumer", "service": "settlement-worker"}],
            "hypotheses": [{"confidence": 0.9}],  # confident diagnosis (uncertainty gate is tested separately)
        },
    }
    plan = (await nodes.propose(st))["remediation_plan"]
    assert [p["action_type"] for p in plan] == ["pause_consumer", "resume_consumer"]
    assert plan[1]["added_by"] == "policy" and plan[1]["action_id"] and plan[1]["step"] == 2
