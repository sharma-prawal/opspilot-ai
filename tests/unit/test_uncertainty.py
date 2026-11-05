"""Audit finding F: an uncertain diagnosis must never yield an approvable remediation proposal."""

from typing import Any

from opspilot_agents.nodes import AgentDeps, AgentPolicy, InvestigationNodes, make_route_after_rca
from opspilot_agents.report import determine_outcome
from tests.unit.test_nodes_policy import ANOM, DEP

ROLLBACK = {"action_type": "rollback_deployment", "deployment_id": "dep-ls-0042", "rationale": "correlated deploy"}
OTHER = {
    "id": "ev-log-9",
    "kind": "log_pattern",
    "service": "transaction-api",
    "relevance": 0.5,
    "summary": "s",
    "data": {},
}
nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]


def state(hypotheses: list[dict[str, Any]], escalation: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "investigation_id": "00000000-0000-0000-0000-000000000002",
        "incident": {"service": "transaction-api"},
        "evidence": {DEP["id"]: DEP, ANOM["id"]: ANOM, OTHER["id"]: OTHER},
        "rca": {
            "hypotheses": hypotheses,
            "remediation_plan": [ROLLBACK],
            "escalation": escalation or {"required": False},
            "impact": {"state": "ongoing", "reasons": [], "evidence_ids": [ANOM["id"]]},
        },
        "rounds": 1,
        "llm_calls": [],
        **extra,
    }


def hyp(conf: float, *ids: str) -> dict[str, Any]:
    return {"confidence": conf, "supporting_evidence_ids": list(ids)}


async def run(s: dict[str, Any]) -> dict[str, Any]:
    out = await nodes.propose(s)
    return {**s, **out, "rejected_proposals": out["rejected_proposals"]}


async def test_audit_reproduction_low_confidence_and_escalation_withholds_proposal() -> None:
    s = state([hyp(0.1, DEP["id"], ANOM["id"])], {"required": True, "to": "ledger-team", "reason": "unclear"})
    assert make_route_after_rca(AgentPolicy())(s) == "propose"  # no follow-ups left: reaches propose
    after = await run(s)
    assert after["proposed_action"] is None and after["remediation_plan"] == []
    [withheld] = after["rejected_proposals"]
    assert withheld["category"] == "withheld_uncertain"
    assert any("below the threshold" in r for r in withheld["uncertainty"])
    assert any("requested escalation" in r for r in withheld["uncertainty"])
    outcome = determine_outcome(after)
    assert outcome["code"] == "escalated" and outcome["escalate"] and outcome["escalate_to"] == "ledger-team"


async def test_low_confidence_alone_withholds_and_is_inconclusive() -> None:
    after = await run(state([hyp(0.4, DEP["id"])]))
    assert after["proposed_action"] is None
    outcome = determine_outcome(after)
    assert outcome["code"] == "inconclusive" and outcome["escalate"]
    assert outcome["reason"].startswith("proposal withheld:")


async def test_explicit_escalation_at_high_confidence_withholds() -> None:
    after = await run(state([hyp(0.95, DEP["id"])], {"required": True, "to": "fx-team"}))
    assert after["proposed_action"] is None and determine_outcome(after)["code"] == "escalated"


async def test_competing_hypotheses_with_disjoint_evidence_withhold() -> None:
    after = await run(state([hyp(0.85, DEP["id"]), hyp(0.8, OTHER["id"])]))
    assert after["proposed_action"] is None
    assert "competing hypotheses" in after["rejected_proposals"][0]["reason"]
    assert determine_outcome(after)["code"] == "inconclusive"


async def test_close_hypotheses_sharing_evidence_do_not_withhold() -> None:
    # Two readings of the same evidence (e.g. "migration" vs "deploy of the migration") are not a conflict.
    after = await run(state([hyp(0.95, DEP["id"], ANOM["id"]), hyp(0.85, DEP["id"])]))
    assert after["proposed_action"] is not None


async def test_margin_boundary_is_not_a_float_artifact() -> None:
    after = await run(state([hyp(0.95, DEP["id"]), hyp(0.85, OTHER["id"])]))  # gap exactly 0.1: not competing
    assert after["proposed_action"] is not None


async def test_exhausted_budget_withholds() -> None:
    err = {"node": "dispatch", "error_class": "budget_exceeded", "message": "tool budget exhausted", "at": "t"}
    after = await run(state([hyp(0.95, DEP["id"])], errors=[err]))
    assert after["proposed_action"] is None
    assert "budget exhausted" in after["rejected_proposals"][0]["reason"]


async def test_confident_unambiguous_diagnosis_still_proposes() -> None:
    after = await run(state([hyp(0.95, DEP["id"], ANOM["id"]), hyp(0.6, OTHER["id"])]))
    assert after["proposed_action"]["action_type"] == "rollback_deployment"
    assert not after["rejected_proposals"]
