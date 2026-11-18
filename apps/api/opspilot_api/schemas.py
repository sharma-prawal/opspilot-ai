"""HTTP DTOs (request/response models). Kept separate from domain contracts and ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from opspilot_shared.domain.actions import ApprovalDecisionKind
from opspilot_shared.domain.common import ServiceName, Severity
from opspilot_shared.domain.knowledge import RetrievalFilters, RetrievalMode
from opspilot_shared.redaction import redact
from opspilot_shared.uploads.model import MAX_FILE_BYTES, MAX_FILES

# Every free-form JSON field that leaves the API passes the central redaction policy (audit finding E).
RedactedJson = Annotated[dict[str, Any], AfterValidator(redact)]


class Dto(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SimulateRequest(BaseModel):
    scenario: str = Field(default="INC-001", pattern=r"^(INC|NEG)-\d{3}$")


class UploadFileIn(BaseModel):
    """One uploaded file, read as text by the browser. Only the base name is used; content is untrusted data."""

    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=MAX_FILE_BYTES)
    service: str | None = Field(default=None, max_length=63, description="service for records that name none")


class UploadPreviewRequest(BaseModel):
    files: list[UploadFileIn] = Field(min_length=1, max_length=MAX_FILES)
    timezone: str = Field(default="UTC", max_length=64, description="IANA zone for timestamps without an offset")
    incident_time: str | None = Field(default=None, max_length=64)
    service: ServiceName | None = None
    affected_services: list[ServiceName] = Field(default_factory=list, max_length=6)


class UploadIncidentRequest(UploadPreviewRequest):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)
    service: ServiceName
    severity: Severity = Severity.SEV2
    incident_time: str = Field(min_length=10, max_length=64)


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
    result: RedactedJson | None
    executing_in_process: bool = False


class OperationAccepted(BaseModel):
    investigation_id: uuid.UUID
    status: str
    status_url: str


class EventOut(Dto):
    id: int
    event_type: str
    node: str | None
    payload: RedactedJson
    created_at: datetime


class ToolCallOut(Dto):
    id: str
    tool: str
    server: str
    agent: str
    arguments: RedactedJson
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
    parameters: RedactedJson
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
