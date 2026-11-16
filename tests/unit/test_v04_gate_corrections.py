"""v0.4 safety-gate corrections (D100, D101). Generic evidence only; no scenario IDs.

Fix A: a resume is admitted only for a consumer that is paused, or paused by an earlier validated step of the same
plan. A running consumer is refused, and missing consumer state is unknown (refused).
Fix B: no state-changing step may bypass a rejected resolution step or unresolved change ambiguity; a restart that
is independently justified by its own evidence is still admitted.
"""

from typing import Any
from unittest.mock import patch

import pytest

from opspilot_agents.nodes import AgentDeps, InvestigationNodes, route_after_propose
from opspilot_agents.remediation import validate_step
from opspilot_shared.errors import ApprovalError

nodes = InvestigationNodes(AgentDeps(chat=None, tools=None, actions=None))  # type: ignore[arg-type]


def ev(eid: str, kind: str, service: str | None, data: dict[str, Any]) -> dict[str, Any]:
    return {"id": eid, "kind": kind, "service": service, "relevance": 0.8, "summary": eid, "data": data}


def queue(state: str | None) -> dict[str, Any]:
    consumer = {"service": "worker"} | ({"state": state} if state else {})
    return ev(
        "ev-queue",
        "queue",
        "worker",
        {
            "queue": "events",
            "consumer": consumer,
            "failures": [{"error_code": "BAD_SCHEMA", "count": 10}],
            "dead_lettered": 10,
            "producers": ["api"],
        },
    )


def change(eid: str, cid: str, service: str, corr: float, kind: str = "deployment") -> dict[str, Any]:
    return ev(
        eid,
        kind,
        service,
        {"id": cid, "service": service, "kind": "application", "status": "succeeded", "correlation": corr},
    )


ANOM_WORKER = ev("ev-m-w", "metric_anomaly", "worker", {"metric": "events_processed_per_min", "recovered": False})
ANOM_API = ev("ev-m-a", "metric_anomaly", "api", {"metric": "http_5xx_ratio", "recovered": False})
UNHEALTHY_LEDGER = ev("ev-h-l", "service_health", "ledger", {"service": "ledger", "status": "degraded"})


def st(incident: str, plan: list[dict[str, Any]], *items: dict[str, Any]) -> dict[str, Any]:
    return {
        "investigation_id": "00000000-0000-0000-0000-0000000000a4",
        "incident": {"service": incident},
        "evidence": {i["id"]: i for i in items},
        "rca": {"remediation_plan": plan, "hypotheses": [{"confidence": 0.9}]},
    }


# 1. resume of an already-running consumer is rejected (and unknown state is not treated as paused)
@pytest.mark.parametrize(("state", "category"), [("running", "invalid"), (None, "insufficient_evidence")])
async def test_resume_of_running_or_unknown_consumer_is_rejected(state: str | None, category: str) -> None:
    chk = validate_step({"action_type": "resume_consumer", "service": "worker"}, {"q": queue(state)}, "worker")
    assert not chk.ok and chk.category == category
    out = await nodes.propose(
        st("worker", [{"action_type": "resume_consumer", "service": "worker"}], queue(state), ANOM_WORKER)
    )
    assert out["remediation_plan"] == [] and out["proposed_action"] is None


# 2. resume of a legitimately paused consumer remains permitted
async def test_resume_of_paused_consumer_is_permitted() -> None:
    chk = validate_step({"action_type": "resume_consumer", "service": "worker"}, {"q": queue("paused")}, "worker")
    assert chk.ok and chk.params == {"service": "worker"}
    # ...and a resume the model lists before its pause is still accepted, ordered after the pause
    plan = [
        {"action_type": "resume_consumer", "service": "worker"},
        {"action_type": "pause_consumer", "service": "worker"},
    ]
    out = await nodes.propose(st("worker", plan, queue("running"), ANOM_WORKER))
    assert [p["action_type"] for p in out["remediation_plan"]] == ["pause_consumer", "resume_consumer"]


# 3. a restart cannot bypass a rejected ambiguous rollback (nor avoid the ambiguity by omitting the rollback)
@pytest.mark.parametrize("with_rollback", [True, False])
async def test_restart_cannot_bypass_unresolved_ambiguity(with_rollback: bool) -> None:
    plan = [{"action_type": "restart_service", "service": "ledger"}]
    if with_rollback:
        plan.insert(0, {"action_type": "rollback_deployment", "deployment_id": "dep-1"})
    out = await nodes.propose(
        st(
            "api",
            plan,
            change("ev-d", "dep-1", "ledger", 0.90),
            change("ev-c", "cfg-1", "ledger", 0.88, "config_change"),
            ANOM_API,
            UNHEALTHY_LEDGER,
        )
    )
    assert out["remediation_plan"] == [] and out["proposed_action"] is None
    restart = next(r for r in out["rejected_proposals"] if r["proposal"]["action_type"] == "restart_service")
    assert "ambiguity" in restart["reason"] and restart["category"] == "insufficient_evidence"


async def test_containment_cannot_outlive_a_rejected_resolution() -> None:
    # rollback rejected for a different reason (no correlation); the pause/quarantine meant to accompany it go too
    plan = [
        {"action_type": "pause_consumer", "service": "worker"},
        {"action_type": "rollback_deployment", "deployment_id": "dep-old"},
        {"action_type": "quarantine_messages", "queue": "events", "error_code": "BAD_SCHEMA"},
    ]
    out = await nodes.propose(st("worker", plan, change("ev-d", "dep-old", "api", 0.0), queue("running"), ANOM_WORKER))
    assert out["remediation_plan"] == []
    reasons = [r["reason"] for r in out["rejected_proposals"]]
    assert any("resolution step was rejected" in r for r in reasons)


# 4. a separately justified restart remains permitted
async def test_independently_justified_restart_is_permitted() -> None:
    out = await nodes.propose(
        st(
            "api",
            [{"action_type": "restart_service", "service": "ledger"}],
            change("ev-d", "dep-1", "ledger", 0.9),
            ANOM_API,
            UNHEALTHY_LEDGER,
        )
    )
    assert [p["action_type"] for p in out["remediation_plan"]] == ["restart_service"]
    assert out["proposed_action"]["parameters"] == {"service": "ledger"}


# 5. a valid multi-step remediation continues to work (pause -> rollback -> quarantine -> policy resume)
async def test_valid_multi_step_plan_is_unchanged() -> None:
    plan = [
        {"action_type": "pause_consumer", "service": "worker"},
        {"action_type": "rollback_deployment", "deployment_id": "dep-1"},
        {"action_type": "quarantine_messages", "queue": "events", "error_code": "BAD_SCHEMA"},
    ]
    out = await nodes.propose(st("worker", plan, change("ev-d", "dep-1", "api", 0.95), queue("running"), ANOM_WORKER))
    steps = out["remediation_plan"]
    assert [s["action_type"] for s in steps] == [
        "pause_consumer",
        "rollback_deployment",
        "quarantine_messages",
        "resume_consumer",
    ]
    assert steps[-1]["added_by"] == "policy"
    assert not [r for r in out["rejected_proposals"]]


# 6. an admitted action still requires normal human authorization
async def test_admitted_plan_still_requires_signed_human_approval() -> None:
    plan = [
        {"action_type": "pause_consumer", "service": "worker"},
        {"action_type": "rollback_deployment", "deployment_id": "dep-1"},
    ]
    state = st("worker", plan, change("ev-d", "dep-1", "api", 0.95), queue("running"), ANOM_WORKER)
    out = await nodes.propose(state)
    assert route_after_propose({**state, **out}) == "await_approval"
    action = out["proposed_action"]
    pending = {**state, **out}
    # approval without the HMAC approval token is refused before anything can execute
    with (
        patch(
            "opspilot_agents.nodes.interrupt",
            return_value={
                "action_id": action["action_id"],
                "params_hash": action["params_hash"],
                "decision": "approve",
            },
        ),
        pytest.raises(ApprovalError, match="token"),
    ):
        await nodes.await_approval(pending)
