"""Investigation artefacts: evidence, observations, hypotheses, tool and LLM call records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from opspilot_shared.domain.common import Contract, UtcDatetime
from opspilot_shared.domain.incidents import IncidentCategory


class EvidenceKind(StrEnum):
    METRIC_ANOMALY = "metric_anomaly"
    LOG_PATTERN = "log_pattern"
    SERVICE_HEALTH = "service_health"
    DEPLOYMENT = "deployment"
    CONFIG_CHANGE = "config_change"
    DEPENDENCY = "dependency"
    KNOWLEDGE = "knowledge"
    HISTORICAL_INCIDENT = "historical_incident"
    SERVICE_CONFIG = "service_config"
    DATASTORE = "datastore"
    QUEUE = "queue"
    TOOL_ERROR = "tool_error"


class Citation(Contract):
    """A citation is a self-contained snapshot (audit finding 13): re-ingestion replaces chunks, so the cited
    passage, its document version, a content hash, the lifecycle status and the retrieval time are recorded
    with the evidence itself. Optional for compatibility with citations recorded before Phase C0."""

    document_id: str
    chunk_id: str
    source_uri: str
    title: str
    heading_path: str
    document_version: int | None = None
    passage: str | None = Field(default=None, description="complete cited chunk text at retrieval time")
    passage_sha256: str | None = None
    lifecycle_status: str | None = None
    retrieved_at: UtcDatetime | None = None


class Evidence(Contract):
    id: str = Field(description="Stable, content-derived ID, e.g. ev-log-3f2a9c1b7d0e")
    kind: EvidenceKind
    source_tool: str
    collected_by: str
    service: str | None = None
    summary: str = Field(max_length=1200)
    data: dict[str, Any] = Field(default_factory=dict)
    citation: Citation | None = None
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_at: UtcDatetime | None = None


class Observation(Contract):
    agent: str
    finding: str
    evidence_ids: list[str]


class Hypothesis(Contract):
    rank: int = Field(ge=1)
    title: str = Field(max_length=200)
    category: IncidentCategory
    description: str = Field(max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class ToolCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class ToolCallRecord(Contract):
    id: str
    tool: str
    server: str
    agent: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    latency_ms: float
    started_at: UtcDatetime
    result_summary: str | None = None
    error: str | None = None


class LLMCallRecord(Contract):
    id: str
    purpose: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1
    status: str = "ok"
    error: str | None = None
    started_at: UtcDatetime
