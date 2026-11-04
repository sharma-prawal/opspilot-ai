"""LangGraph state. JSON-compatible values only, so checkpoints deserialize in strict mode."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_evidence(
    left: dict[str, dict[str, Any]] | None, right: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """Evidence is keyed by stable ID; re-collecting the same item is idempotent."""
    return {**(left or {}), **(right or {})}


class Task(TypedDict):
    capability: str  # telemetry | changes | dependencies | knowledge
    service: str | None
    reason: str


class InvestigationState(TypedDict, total=False):
    investigation_id: str
    incident_id: str
    incident: dict[str, Any]
    window: dict[str, str]  # start, end, detected_at, onset
    classification: dict[str, Any]
    plan: dict[str, Any]
    task_queue: list[Task]
    active_task: Task | None
    completed_tasks: list[str]
    evidence: Annotated[dict[str, dict[str, Any]], merge_evidence]
    observations: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    llm_calls: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    rejected_proposals: Annotated[list[dict[str, Any]], operator.add]
    rounds: int
    rca: dict[str, Any] | None
    proposed_action: dict[str, Any] | None
    remediation_plan: list[dict[str, Any]]
    plan_index: int
    executions: list[dict[str, Any]]
    outcome: dict[str, Any] | None
    approval: dict[str, Any] | None
    remediation: dict[str, Any] | None
    verification: dict[str, Any] | None
    report: dict[str, Any] | None
    status: str
    current_step: str


CAPABILITIES = ("telemetry", "dependencies", "changes", "knowledge")


def task_key(task: Task) -> str:
    return f"{task['capability']}:{task.get('service') or '*'}"
