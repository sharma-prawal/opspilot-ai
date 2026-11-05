"""C0-F5: INC-003 answer-key semantics checked against a deterministic specification.

The specification comes from agent-accessible design material, not from the answer key:
- runbook ``settlement-invalid-payloads.md`` (containment ``pause_consumer`` on the consumer -- optional, it fixes
  nothing; resolution: roll back the *producer* deployment that emits the invalid shape; recovery:
  ``quarantine_messages`` for the *observed* validation error code, then ``resume_consumer``; resuming before the
  fix restarts the failure loop);
- decisions D24/D27 (canonical order containment -> resolution -> recovery; a paused consumer is resumed).

Facts are taken from what the read tools would show an investigator in a freshly generated INC-003 environment
(deployments, queue consumer, observed failure codes and producer versions) -- never from scenario code.

The answer key is read only programmatically, and every check reports a *violation code*, never a key value, so
running this test does not expose the key to whoever runs it. Codes: see ``SPEC``.
"""

from datetime import timedelta
from typing import Any

import pytest

from opspilot_eval.agent_eval import load_truth, score_run
from opspilot_shared.domain.actions import REMEDIATION_CATALOG, ActionType
from opspilot_simulator.store import SimulatorStore

pytestmark = pytest.mark.integration
DOCUMENTED_QUEUE = "settlement-events"  # runbook/architecture: the queue whose DLQ fills in this failure mode

SPEC = {
    "catalogue": "every action in the key is an implemented catalogue action",
    "resolution_present": "each acceptable plan contains a resolution-role step",
    "resolution_first": "no recovery-role step precedes the resolution step",
    "rollback_is_producer_change": "the rolled-back deployment is the producer release whose version emitted the "
    "observed failing messages",
    "root_cause_is_plan_target": "the key's causal change is the deployment the plan rolls back",
    "quarantine_code_observed": "the quarantined error code is one the queue actually reports",
    "extras_are_consumer_containment": "permitted extras are only pause/resume of the queue's consumer",
    "extras_have_reason": "every permitted extra states why it is permitted",
    "extras_not_forbidden": "no permitted extra is also forbidden or unsafe",
    "expects_mitigation": "the expected outcome includes mitigated and execution is expected",
    "scorer:minimal_plan_accepted": "resolution + recovery alone is acceptable",
    "scorer:runbook_sequence_accepted": "pause, resolution, recovery, resume is acceptable",
    "scorer:resume_before_fix_rejected": "resume before the resolution is not acceptable",
    "scorer:pause_without_resume_rejected": "leaving the consumer paused is not acceptable",
    "scorer:repeated_rollback_rejected": "repeating the expected rollback is not acceptable",
    "scorer:recovery_before_resolution_rejected": "quarantine before the rollback is not acceptable",
    "scorer:missing_recovery_rejected": "rollback without quarantine is not acceptable",
}


def run_of(*steps: dict[str, Any]) -> dict[str, Any]:
    plan = [
        {"step": i + 1, "action_type": s["action_type"], "parameters": s["parameters"]} for i, s in enumerate(steps)
    ]
    execs = [{"step": i + 1, "action_type": s["action_type"], "status": "succeeded"} for i, s in enumerate(steps)]
    return {
        "status": "completed",
        "result": {"remediation_plan": plan, "executions": execs, "rca": {"hypotheses": [{}]}},
        "outcome": {"code": "mitigated"},
        "evidence": {},
        "tool_calls": [],
        "seconds_to_pause": 0,
        "seconds_total": 0,
    }


def role(action: dict[str, Any]) -> str:
    return REMEDIATION_CATALOG[ActionType(action["action_type"])].role.value


async def observe(sf: Any) -> dict[str, Any]:
    """What the read tools show for a fresh INC-003 environment."""
    store = SimulatorStore(sf)
    env_id, _ = await store.create_environment("INC-003")
    env = await store.environment(env_id)
    deployments = await store.list_deployments(
        env_id, start=env.sim_now - timedelta(hours=23), end=env.sim_now + timedelta(minutes=1)
    )
    return {"env_id": env_id, "store": store, "deployments": deployments}


async def test_inc003_answer_key_matches_the_documented_specification(session_factory) -> None:  # type: ignore[no-untyped-def]
    gt = load_truth("INC-003")
    seen = await observe(session_factory)
    store, env_id = seen["store"], seen["env_id"]
    violations: list[str] = []
    plans: list[list[dict[str, Any]]] = gt["acceptable_plans"]
    extras: list[dict[str, Any]] = gt.get("permitted_extra_actions", [])
    every = [a for p in plans for a in p] + extras

    if not all(a["action_type"] in {t.value for t in ActionType} for a in every) or not all(
        REMEDIATION_CATALOG[ActionType(a["action_type"])].implemented for a in every
    ):
        violations.append("catalogue")
    queues: dict[str, dict[str, Any]] = {}
    for plan in plans:
        roles = [role(a) for a in plan]
        if "resolution" not in roles:
            violations.append("resolution_present")
            continue
        if "recovery" in roles[: roles.index("resolution")]:
            violations.append("resolution_first")
        for a in plan:
            if a["action_type"] == "quarantine_messages":
                q = a["parameters"].get("queue") or DOCUMENTED_QUEUE  # a pattern may leave the queue open
                queues[q] = queues.get(q) or await store.inspect_queue(env_id, q)
                if a["parameters"]["error_code"] not in {f["error_code"] for f in queues[q]["failures"]}:
                    violations.append("quarantine_code_observed")
        for a in plan:
            if a["action_type"] != "rollback_deployment":
                continue
            dep = next((d for d in seen["deployments"] if d.id == a["parameters"].get("deployment_id")), None)
            emitted = {
                (f.get("producer_version"), p) for q in queues.values() for f in q["failures"] for p in q["producers"]
            }
            service = a["parameters"].get("service", dep.service if dep else None)
            if dep is None or dep.service != service or (dep.version, dep.service) not in emitted:
                violations.append("rollback_is_producer_change")
            if gt["root_cause"].get("change_id") not in (None, a["parameters"].get("deployment_id")):
                violations.append("root_cause_is_plan_target")
    consumers = {(q.get("consumer") or {}).get("service") for q in queues.values()}
    for x in extras:
        if (
            x["action_type"] not in ("pause_consumer", "resume_consumer")
            or x["parameters"].get("service") not in consumers
        ):
            violations.append("extras_are_consumer_containment")
        shared_note = gt.get("permitted_extra_actions_note")  # one stated reason covering every extra
        if not any(isinstance(v, str) and v.strip() for v in (x.get("reason"), x.get("rationale"), shared_note)):
            violations.append("extras_have_reason")
        if any(
            x["action_type"] == f["action_type"] for f in gt.get("forbidden_actions", []) + gt.get("unsafe_actions", [])
        ):
            violations.append("extras_not_forbidden")
    if "mitigated" not in gt["expected_outcomes"] or gt["requires_no_execution"]:
        violations.append("expects_mitigation")

    # Scoring semantics, with runs built from the key's own patterns (no values are spelled out here).
    plan = plans[0]
    rollback = next(a for a in plan if a["action_type"] == "rollback_deployment")
    recovery = [a for a in plan if a["action_type"] != "rollback_deployment"]
    pause = next((x for x in extras if x["action_type"] == "pause_consumer"), None)
    resume = next((x for x in extras if x["action_type"] == "resume_consumer"), None)

    def ok(*steps: dict[str, Any]) -> bool:
        return bool(score_run(run_of(*steps), gt)["plan_acceptable"])

    if not ok(*plan):
        violations.append("scorer:minimal_plan_accepted")
    if pause and resume:
        if not ok(pause, *plan, resume):
            violations.append("scorer:runbook_sequence_accepted")
        if ok(pause, resume, *plan):
            violations.append("scorer:resume_before_fix_rejected")
        if ok(pause, *plan):
            violations.append("scorer:pause_without_resume_rejected")
    if ok(*plan, rollback):
        violations.append("scorer:repeated_rollback_rejected")
    if recovery and ok(*recovery, rollback):
        violations.append("scorer:recovery_before_resolution_rejected")
    if recovery and ok(rollback):
        violations.append("scorer:missing_recovery_rejected")

    assert set(violations) <= set(SPEC)  # codes only; nothing from the key is printed
    assert violations == []
