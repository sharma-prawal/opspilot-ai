"""Remediation validation and routing decisions, exercised directly on state."""

from typing import Any

import pytest

from opspilot_agents.nodes import (
    AgentDeps,
    AgentPolicy,
    InvestigationNodes,
    make_route_after_rca,
    route_after_followup,
    route_dispatch,
)

DEP = {
    "id": "ev-deploy-1",
    "kind": "deployment",
    "service": "ledger-service",
    "relevance": 0.9,
    "summary": "s",
    "data": {"id": "dep-ls-0042", "service": "ledger-service", "kind": "schema_migration", "status": "succeeded"},
}


def state(remediation: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "investigation_id": "00000000-0000-0000-0000-000000000001",
        "incident": {"service": "transaction-api"},
        "evidence": {DEP["id"]: DEP},
        "rca": {"hypotheses": [{"confidence": 0.9}], "remediation": remediation},
        **extra,
    }


nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]


async def test_valid_rollback_uses_evidence_parameters() -> None:
    # The model named the wrong service; the deployment's own service from evidence is used.
    out = await nodes.propose(
        state(
            {
                "action_type": "rollback_deployment",
                "service": "transaction-api",
                "deployment_id": "dep-ls-0042",
                "rationale": "r",
            }
        )
    )
    act = out["proposed_action"]
    assert act["parameters"] == {"service": "ledger-service", "deployment_id": "dep-ls-0042"}
    assert len(act["params_hash"]) == 64 and act["risk"] == "medium"
    again = await nodes.propose(
        state({"action_type": "rollback_deployment", "deployment_id": "dep-ls-0042", "rationale": "different text"})
    )
    assert again["proposed_action"]["action_id"] == act["action_id"]  # stable, idempotent ID


@pytest.mark.parametrize(
    "rem, reason",
    [
        ({"action_type": "rollback_deployment", "deployment_id": "dep-fabricated", "rationale": ""}, "does not appear"),
        ({"action_type": "restart_service", "service": "settlement-worker", "rationale": ""}, "not observed"),
        ({"action_type": "scale_connection_pool", "service": "ledger-service", "rationale": ""}, "not available"),
        ({"action_type": "drop_database", "rationale": ""}, "not in the remediation catalogue"),
    ],
)
async def test_invalid_proposals_rejected(rem: dict[str, Any], reason: str) -> None:
    out = await nodes.propose(state(rem))
    assert out["proposed_action"] is None and reason in out["rejected_proposals"][0]["reason"]


def test_route_dispatch() -> None:
    assert route_dispatch({"active_task": {"capability": "changes", "service": None, "reason": ""}}) == "changes"
    assert route_dispatch({"active_task": None}) == "rca"


async def test_dispatch_defers_knowledge_until_evidence_tasks_done() -> None:
    out = await nodes.dispatch(
        {
            "task_queue": [
                {"capability": "knowledge", "service": None, "reason": ""},
                {"capability": "telemetry", "service": "a", "reason": ""},
            ],
            "completed_tasks": [],
            "tool_calls": [],
        }
    )
    assert out["active_task"]["capability"] == "telemetry"


async def test_dispatch_stops_when_budget_exhausted() -> None:
    n = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None, policy=AgentPolicy(max_tool_calls=2)))  # type: ignore[arg-type]
    out = await n.dispatch(
        {
            "task_queue": [{"capability": "telemetry", "service": "a", "reason": ""}],
            "completed_tasks": [],
            "tool_calls": [{}, {}],
        }
    )
    assert out["active_task"] is None and out["errors"][0]["error_class"] == "budget_exceeded"


def test_low_confidence_triggers_bounded_followup() -> None:
    route = make_route_after_rca(AgentPolicy(confidence_threshold=0.6, max_rounds=2))
    low = {
        "rca": {
            "hypotheses": [{"confidence": 0.4}],
            "followups": ["knowledge"],
            "remediation": {"action_type": "none"},
        },
        "rounds": 0,
        "llm_calls": [],
    }
    assert route(low) == "followup"
    assert route({**low, "rounds": 1}) == "report"  # rounds exhausted
    assert route({**low, "rca": {**low["rca"], "followups": []}}) == "report"
    high = {
        **low,
        "rca": {
            **low["rca"],
            "hypotheses": [{"confidence": 0.9}],
            "remediation": {"action_type": "rollback_deployment"},
        },
    }
    assert route(high) == "propose"
    assert route({"status": "failed"}) == "failed"


def test_followup_with_nothing_new_skips_to_decision() -> None:
    assert route_after_followup({"task_queue": [], "rca": {"remediation": {"action_type": "none"}}}) == "report"


async def test_approval_payload_must_match_pending_action() -> None:
    from unittest.mock import patch

    from opspilot_shared.errors import ApprovalError

    st = state({}, proposed_action={"action_id": "a1", "params_hash": "h1"})
    with (
        patch(
            "opspilot_agents.nodes.interrupt",
            return_value={"action_id": "a1", "params_hash": "OTHER", "decision": "approve", "approval_token": "t"},
        ),
        pytest.raises(ApprovalError),
    ):
        await nodes.await_approval(st)
    with (
        patch(
            "opspilot_agents.nodes.interrupt",
            return_value={"action_id": "a1", "params_hash": "h1", "decision": "approve"},
        ),
        pytest.raises(ApprovalError, match="token"),
    ):
        await nodes.await_approval(st)


async def test_plan_policy_adds_mandatory_capabilities() -> None:
    from opspilot_agents.prompts import PlanOutput
    from tests.fakes.models import ScriptedChatModel

    chat = ScriptedChatModel(
        {
            PlanOutput: lambda _m: {
                "category": "unknown",
                "category_confidence": 0.2,
                "rationale": "x",
                "capabilities": ["changes"],
            }
        }
    )
    n = InvestigationNodes(AgentDeps(chat=chat, tools=None, actions=None))  # type: ignore[arg-type]
    out = await n.plan({"incident": {"service": "transaction-api", "title": "t"}, "llm_calls": []})
    assert out["plan"]["capabilities"] == ["telemetry", "changes", "knowledge"]
    assert len(out["plan"]["notes"]) == 2 and out["classification"]["source"] == "llm"


async def test_dispatch_schedules_by_data_dependency() -> None:
    q = [{"capability": c, "service": "a", "reason": ""} for c in ("knowledge", "changes", "dependencies", "telemetry")]
    order = []
    st: dict[str, Any] = {"task_queue": q, "completed_tasks": [], "tool_calls": []}
    while True:
        out = await nodes.dispatch(st)
        if not out["active_task"]:
            break
        order.append(out["active_task"]["capability"])
        st = {**st, "task_queue": out["task_queue"]}
    assert order == ["telemetry", "dependencies", "changes", "knowledge"]
