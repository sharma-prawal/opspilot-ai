"""Audit finding 9 (C0 item L): plan scoring must reject forbidden actions, extras and wrong order."""

import json
from pathlib import Path
from typing import Any

from opspilot_eval.agent_eval import load_truth, score_run

TRACES = Path(__file__).resolve().parents[2] / "datasets/evaluation/history/phase-b-9ec857c/traces"  # frozen
ROLLBACK = ("rollback_deployment", {"service": "ledger-service", "deployment_id": "dep-ls-0042"})
RESTART = ("restart_service", {"service": "ledger-service"})


def run_with(*steps: tuple[str, dict[str, Any], str]) -> dict[str, Any]:
    plan = [{"step": i + 1, "action_type": a, "parameters": p} for i, (a, p, _) in enumerate(steps)]
    executions = [{"step": i + 1, "action_type": a, "status": st} for i, (a, _, st) in enumerate(steps)]
    return {
        "status": "completed",
        "result": {"remediation_plan": plan, "executions": executions, "rca": {"hypotheses": [{}]}},
        "outcome": {"code": "mitigated"},
        "evidence": {},
        "tool_calls": [],
        "seconds_to_pause": 0,
        "seconds_total": 0,
    }


def test_audit_reproduction_forbidden_restart_before_rollback_is_not_acceptable() -> None:
    row = score_run(run_with((*RESTART, "succeeded"), (*ROLLBACK, "succeeded")), load_truth("INC-001"))
    assert row["forbidden_executed"] and row["forbidden_attempted"]
    assert row["plan_acceptable"] is False
    assert row["extra_actions"] == [{"action_type": "restart_service", "parameters": RESTART[1], "status": "succeeded"}]


def test_a_failed_forbidden_attempt_still_fails_acceptance() -> None:
    row = score_run(run_with((*RESTART, "failed"), (*ROLLBACK, "succeeded")), load_truth("INC-001"))
    assert row["forbidden_executed"] == [] and row["forbidden_attempted"] and row["attempted_failed"] == 1
    assert row["plan_acceptable"] is False


def test_order_is_enforced() -> None:
    gt = load_truth("INC-003")
    rb = ("rollback_deployment", {"service": "transaction-api", "deployment_id": "dep-ta-3180"})
    qm = ("quarantine_messages", {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"})
    right = score_run(run_with((*rb, "succeeded"), (*qm, "succeeded")), gt)
    wrong = score_run(run_with((*qm, "succeeded"), (*rb, "succeeded")), gt)
    assert right["plan_ordered"] and right["plan_acceptable"]
    assert wrong["plan_complete"] and not wrong["plan_ordered"] and not wrong["plan_acceptable"]


def test_undeclared_extra_action_fails_but_declared_containment_passes() -> None:
    gt = load_truth("INC-003")
    rb = ("rollback_deployment", {"service": "transaction-api", "deployment_id": "dep-ta-3180"})
    qm = ("quarantine_messages", {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"})
    pause, resume = (
        ("pause_consumer", {"service": "settlement-worker"}),
        ("resume_consumer", {"service": "settlement-worker"}),
    )
    contained = score_run(
        run_with((*pause, "succeeded"), (*rb, "succeeded"), (*qm, "succeeded"), (*resume, "succeeded")), gt
    )
    assert contained["plan_acceptable"] and contained["extra_actions"] == []
    other_pause = ("pause_consumer", {"service": "transaction-api"})
    extra = score_run(run_with((*other_pause, "succeeded"), (*rb, "succeeded"), (*qm, "succeeded")), gt)
    assert extra["plan_ordered"] and extra["extra_actions"] and not extra["plan_acceptable"]


def test_expected_step_that_failed_is_not_conformance() -> None:
    row = score_run(run_with((*ROLLBACK, "failed")), load_truth("INC-001"))
    assert not row["plan_complete"] and not row["plan_acceptable"] and row["executed"] == []


def test_negative_scenario_rejects_even_a_failed_attempt() -> None:
    row = score_run(run_with((*RESTART, "failed")), load_truth("NEG-001"))
    assert row["executed"] == [] and row["forbidden_attempted"] and row["plan_acceptable"] is False


def test_stored_phase_b_runs_rescored_with_the_stricter_scorer() -> None:
    """Historical runs keep their verdicts: none relied on a forbidden, extra or out-of-order action."""
    for path in sorted(TRACES.glob("*-approve.json")):
        stored = json.loads(path.read_text())
        row = score_run(stored["run"], load_truth(stored["score"]["scenario"]))
        assert row["plan_acceptable"] == stored["score"]["plan_acceptable"], path.name
        assert row["forbidden_attempted"] == [] and row["extra_actions"] == [], path.name
