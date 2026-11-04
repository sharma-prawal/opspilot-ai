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
    QUARANTINE_MESSAGES = "quarantine_messages"
    RESUME_CONSUMER = "resume_consumer"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionRole(StrEnum):
    CONTAINMENT = "containment"  # limits impact; does not fix the cause
    RESOLUTION = "resolution"  # removes the cause
    RECOVERY = "recovery"  # restores normal operation after resolution


class ActionSpec(Contract):
    action_type: ActionType
    description: str
    required_params: tuple[str, ...]
    risk: RiskLevel
    role: ActionRole
    implemented: bool


REMEDIATION_CATALOG: dict[ActionType, ActionSpec] = {
    ActionType.ROLLBACK_DEPLOYMENT: ActionSpec(
        action_type=ActionType.ROLLBACK_DEPLOYMENT,
        description="Revert a specific deployment (application or schema migration) to its previous version.",
        required_params=("service", "deployment_id"),
        risk=RiskLevel.MEDIUM,
        role=ActionRole.RESOLUTION,
        implemented=True,
    ),
    ActionType.RESTART_SERVICE: ActionSpec(
        action_type=ActionType.RESTART_SERVICE,
        description="Rolling restart of all instances of a service. Does not fix code, schema or data problems.",
        required_params=("service",),
        risk=RiskLevel.LOW,
        role=ActionRole.CONTAINMENT,
        implemented=True,
    ),
    ActionType.SCALE_CONNECTION_POOL: ActionSpec(
        action_type=ActionType.SCALE_CONNECTION_POOL,
        description=(
            "Set a service's database connection pool size per replica. Only safe when replicas x pool "
            "plus other clients stays within 90% of the datastore's max_connections."
        ),
        required_params=("service", "max_connections"),
        risk=RiskLevel.HIGH,
        role=ActionRole.CONTAINMENT,
        implemented=True,
    ),
    ActionType.PAUSE_CONSUMER: ActionSpec(
        action_type=ActionType.PAUSE_CONSUMER,
        description=(
            "Pause a queue consumer. Containment only: stops processing and retry churn; nothing is "
            "processed until resume_consumer."
        ),
        required_params=("service",),
        risk=RiskLevel.MEDIUM,
        role=ActionRole.CONTAINMENT,
        implemented=True,
    ),
    ActionType.QUARANTINE_MESSAGES: ActionSpec(
        action_type=ActionType.QUARANTINE_MESSAGES,
        description=(
            "Move messages that fail validation with a given error code (pending or dead-lettered) to "
            "quarantine, preserved for later replay. Never deletes messages."
        ),
        required_params=("queue", "error_code"),
        risk=RiskLevel.MEDIUM,
        role=ActionRole.RECOVERY,
        implemented=True,
    ),
    ActionType.RESUME_CONSUMER: ActionSpec(
        action_type=ActionType.RESUME_CONSUMER,
        description=(
            "Resume a paused queue consumer. Only recovers if the cause is fixed and poison messages are removed."
        ),
        required_params=("service",),
        risk=RiskLevel.MEDIUM,
        role=ActionRole.RECOVERY,
        implemented=True,
    ),
}


class ActionStatus(StrEnum):
    PENDING = "pending"
    EXPIRED = "expired"
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
