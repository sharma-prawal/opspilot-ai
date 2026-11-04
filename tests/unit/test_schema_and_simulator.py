from opspilot_agents.prompts import RcaOutput
from opspilot_shared.llm.schema import inline_schema
from opspilot_simulator.scenarios import DEFAULT_SEED, get_scenario
from opspilot_simulator.store import DEFAULT_ANCHOR


def test_inline_schema_keeps_title_property() -> None:
    """Regression: stripping every 'title' key removed the hypothesis.title property from the grammar."""
    s = inline_schema(RcaOutput)
    item = s["properties"]["hypotheses"]["items"]
    assert "title" in item["properties"] and "title" in item["required"]
    assert "$ref" not in str(s) and "$defs" not in s


def test_simulator_is_deterministic() -> None:
    sc = get_scenario("INC-001")
    a, b = sc.generate(DEFAULT_SEED, DEFAULT_ANCHOR), sc.generate(DEFAULT_SEED, DEFAULT_ANCHOR)
    assert [(m.ts, m.service, m.name, m.value) for m in a.telemetry.metrics] == [
        (m.ts, m.service, m.name, m.value) for m in b.telemetry.metrics
    ]
    assert [(lg.ts, lg.message) for lg in a.telemetry.logs] == [(lg.ts, lg.message) for lg in b.telemetry.logs]


def test_simulator_state_contains_no_answer_key() -> None:
    data = get_scenario("INC-001").generate(DEFAULT_SEED, DEFAULT_ANCHOR)
    assert set(data.state) == {"fault_active", "onset", "actions"}
    assert "root_cause" not in str(data.state).lower()


def test_correct_and_wrong_remediation_effects() -> None:
    sc = get_scenario("INC-001")
    data = sc.generate(DEFAULT_SEED, DEFAULT_ANCHOR)
    ok = sc.apply_action(
        "rollback_deployment",
        {"service": "ledger-service", "deployment_id": "dep-ls-0042"},
        state=data.state,
        deployments=data.deployments,
        now=data.sim_now,
    )
    wrong = sc.apply_action(
        "rollback_deployment",
        {"service": "settlement-worker", "deployment_id": "dep-sw-2311"},
        state=data.state,
        deployments=data.deployments,
        now=data.sim_now,
    )
    restart = sc.apply_action(
        "restart_service",
        {"service": "transaction-api"},
        state=data.state,
        deployments=data.deployments,
        now=data.sim_now,
    )
    assert ok.succeeded and ok.fault_cleared
    assert wrong.succeeded and not wrong.fault_cleared
    assert restart.succeeded and not restart.fault_cleared
