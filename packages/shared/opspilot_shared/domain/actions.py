"""Remediation catalogue, action requests and approval contracts.

The catalogue is the *only* set of state-changing operations the system can perform.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field

from opspilot_shared.domain.common import Contract, UtcDatetime


class ActionType(StrEnum):
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RESTART_SERVICE = "restart_service"
    SCALE_CONNECTION_POOL = "scale_connection_pool"
    PAUSE_CONSUMER = "pause_consumer"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionSpec(Contract):
    action_type: ActionType
    description: str
    required_params: tuple[str, ...]
    risk: RiskLevel
    implemented: bool


REMEDIATION_CATALOG: dict[ActionType, ActionSpec] = {
    ActionType.ROLLBACK_DEPLOYMENT: ActionSpec(
        action_type=ActionType.ROLLBACK_DEPLOYMENT,
        description="Revert a specific deployment (application or schema migration) to its previous version.",
        required_params=("service", "deployment_id"),
        risk=RiskLevel.MEDIUM,
        implemented=True,
    ),
    ActionType.RESTART_SERVICE: ActionSpec(
        action_type=ActionType.RESTART_SERVICE,
        description="Rolling restart of all instances of a service.",
        required_params=("service",),
        risk=RiskLevel.LOW,
        implemented=True,
    ),
    ActionType.SCALE_CONNECTION_POOL: ActionSpec(
        action_type=ActionType.SCALE_CONNECTION_POOL,
        description="Change a service's database connection pool size (bounded 5..200).",
        required_params=("service", "max_connections"),
        risk=RiskLevel.MEDIUM,
        implemented=False,
    ),
    ActionType.PAUSE_CONSUMER: ActionSpec(
        action_type=ActionType.PAUSE_CONSUMER,
        description="Pause a queue consumer to stop processing poison messages.",
        required_params=("service",),
        risk=RiskLevel.MEDIUM,
        implemented=False,
    ),
}


class ActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProposedAction(Contract):
    action_id: uuid.UUID
    action_type: ActionType
    parameters: dict[str, Any]
    params_hash: str
    rationale: str
    risk: RiskLevel
    hypothesis_rank: int


class ApprovalDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalDecision(Contract):
    action_id: uuid.UUID
    params_hash: str
    decision: ApprovalDecisionKind
    decided_by: str = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)
    decided_at: UtcDatetime


class ExecutionResult(Contract):
    action_id: uuid.UUID
    status: ActionStatus
    executed_at: UtcDatetime
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(Contract):
    recovered: bool
    service: str
    metric: str
    threshold: float
    observed_before: float
    observed_after: float
    window_start: UtcDatetime
    window_end: UtcDatetime
    notes: str
