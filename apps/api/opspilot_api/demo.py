"""In-process end-to-end run used by ``opspilot investigate`` and the agent evaluation suite.

Uses exactly the same services, MCP servers, checkpointer and graph as the HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from opspilot_api.runtime import AppRuntime
from opspilot_shared.config import Settings
from opspilot_shared.domain.actions import ApprovalDecisionKind
from opspilot_shared.domain.common import utcnow


async def wait_for(rt: AppRuntime, inv_id: uuid.UUID, statuses: set[str], timeout_s: float = 900) -> str:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        inv = await rt.investigations.get(inv_id)
        if inv.status in statuses and not rt.runner.is_active(inv_id):
            return inv.status
        await asyncio.sleep(1.0)
    raise TimeoutError(f"investigation {inv_id} did not reach {statuses}")


async def investigate(rt: AppRuntime, scenario: str, decision: str, *, max_steps: int = 6) -> dict[str, Any]:
    """Run one scenario end to end. ``decision`` applies to every approval request of the plan
    (``approve`` | ``reject`` | ``none`` = stop at the first approval request)."""
    t0 = time.monotonic()
    incident = await rt.incidents.simulate(scenario)
    inv = await rt.investigations.start(incident.id)
    status = await wait_for(rt, inv.id, {"awaiting_approval", "completed", "failed", "cancelled"})
    t_pause = time.monotonic() - t0
    actions: list[dict[str, Any]] = []
    executions_before_first_decision = None
    while status == "awaiting_approval" and len(actions) < max_steps:
        [action] = [a for a in await rt.approvals.list("pending") if a.investigation_id == inv.id]
        actions.append(
            {"id": str(action.id), "type": action.action_type, "parameters": action.parameters, "decision": decision}
        )
        if executions_before_first_decision is None:
            executions_before_first_decision = await _executions(rt, incident.environment_id)
        if decision == "none":
            break
        await rt.approvals.decide(
            action.id,
            decision=ApprovalDecisionKind(decision),
            params_hash=action.params_hash,
            decided_by="cli-operator",
            comment=f"{decision} via opspilot investigate",
        )
        status = await wait_for(rt, inv.id, {"awaiting_approval", "completed", "failed", "cancelled"})
    final = await rt.investigations.get(inv.id)
    state = (await rt.graph.aget_state({"configurable": {"thread_id": str(inv.id)}})).values
    return {
        "scenario": scenario,
        "incident_id": str(incident.id),
        "environment_id": str(incident.environment_id),
        "reference": incident.reference,
        "investigation_id": str(inv.id),
        "status": status,
        "seconds_to_pause": round(t_pause, 1),
        "seconds_total": round(time.monotonic() - t0, 1),
        "result": final.result,
        "actions": actions,
        "action": actions[0] if actions else None,
        "executions_before_first_decision": executions_before_first_decision or 0,
        "executions_total": await _executions(rt, incident.environment_id),
        "tool_calls": [
            {k: c[k] for k in ("tool", "agent", "status", "latency_ms")} | {"error": c.get("error")}
            for c in state.get("tool_calls", [])
        ],
        "llm_calls": state.get("llm_calls", []),
        "evidence_ids": sorted(state.get("evidence", {})),
        "evidence": state.get("evidence", {}),
        "completed_tasks": state.get("completed_tasks", []),
        "rejected_proposals": state.get("rejected_proposals", []),
        "outcome": state.get("outcome"),
        "report_markdown": final.report_markdown,
        "error": final.error,
        "finished_at": utcnow().isoformat(),
    }


async def _executions(rt: AppRuntime, environment_id: Any) -> int:
    from sqlalchemy import func, select

    from opspilot_shared.db.models import SimActionExecution

    async with rt.infra.session_factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(SimActionExecution)
                    .where(SimActionExecution.environment_id == environment_id)
                )
            ).scalar_one()
        )


async def run_demo(settings: Settings, *, scenario: str, decision: str, out: str | None) -> None:
    async with AppRuntime.open(settings) as rt:
        summary = await investigate(rt, scenario, decision)
    if out:
        await asyncio.to_thread(Path(out).write_text, json.dumps(summary, indent=2, default=str))
    print(summary["report_markdown"] or "(no report)")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "reference",
                    "investigation_id",
                    "status",
                    "seconds_to_pause",
                    "seconds_total",
                    "actions",
                    "outcome",
                    "completed_tasks",
                )
            },
            indent=2,
            default=str,
        )
    )
