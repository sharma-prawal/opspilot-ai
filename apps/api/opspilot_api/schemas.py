"""HTTP DTOs (request/response models). Kept separate from domain contracts and ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opspilot_shared.domain.actions import ApprovalDecisionKind
from opspilot_shared.domain.knowledge import RetrievalFilters, RetrievalMode


class Dto(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SimulateRequest(BaseModel):
    scenario: str = Field(default="INC-001", pattern=r"^(INC|NEG)-\d{3}$")


class InvestigationOut(Dto):
    id: uuid.UUID
    incident_id: uuid.UUID
    status: str
    current_step: str | None
    model: str
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    error_class: str | None
    created_at: datetime
    updated_at: datetime


class InvestigationDetail(InvestigationOut):
    result: dict[str, Any] | None
    executing_in_process: bool = False


class OperationAccepted(BaseModel):
    investigation_id: uuid.UUID
    status: str
    status_url: str


class EventOut(Dto):
    id: int
    event_type: str
    node: str | None
    payload: dict[str, Any]
    created_at: datetime


class ToolCallOut(Dto):
    id: str
    tool: str
    server: str
    agent: str
    arguments: dict[str, Any]
    status: str
    latency_ms: float
    result_summary: str | None
    error: str | None
    started_at: datetime


class EvidenceOut(Dto):
    evidence_id: str
    kind: str
    source_tool: str
    collected_by: str
    service: str | None
    summary: str
    data: dict[str, Any]
    citation: dict[str, Any] | None
    relevance: float
    observed_at: datetime | None


class ActionOut(Dto):
    id: uuid.UUID
    investigation_id: uuid.UUID
    incident_id: uuid.UUID
    action_type: str
    parameters: dict[str, Any]
    params_hash: str
    rationale: str
    risk: str
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_comment: str | None
    executed_at: datetime | None
    execution_result: dict[str, Any] | None
    verification: dict[str, Any] | None


class DecisionRequest(BaseModel):
    decision: ApprovalDecisionKind
    params_hash: str = Field(min_length=64, max_length=64, description="Hash of the exact action being approved")
    decided_by: str = Field(min_length=1, max_length=100, pattern=r"^[\w.@ -]+$")
    comment: str | None = Field(default=None, max_length=1000)


class CancelRequest(BaseModel):
    actor: str = Field(default="operator", min_length=1, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    mode: RetrievalMode = RetrievalMode.HYBRID
    top_k: int = Field(default=6, ge=1, le=20)
    filters: RetrievalFilters | None = None


class IngestRequest(BaseModel):
    reindex: bool = False


class ReportOut(BaseModel):
    investigation_id: uuid.UUID
    status: str
    markdown: str
    result: dict[str, Any] | None
