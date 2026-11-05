from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field

from opspilot_shared.domain.common import Contract

# Document lifecycle (audit finding 7, C0-G3). Tier 0: current; tier 1: unreviewed / unknown status; tier 2: obsolete
# (superseded, withdrawn, ...). Ranking puts lower tiers first; normal incident investigation (the agent-facing MCP
# tools) never receives tier-2 guidance; explicitly authorised historical search (operator API) still can.
OBSOLETE_STATUSES = frozenset({"superseded", "deprecated", "retired", "withdrawn", "obsolete", "archived"})


def lifecycle_tier(status: object) -> int:
    s = str(status or "current").lower()
    if s == "current":
        return 0
    return 2 if s in OBSOLETE_STATUSES else 1


class DocType(StrEnum):
    RUNBOOK = "runbook"
    ARCHITECTURE = "architecture"
    INCIDENT_REPORT = "incident_report"
    DEPLOYMENT_PROCEDURE = "deployment_procedure"
    ERROR_CATALOG = "error_catalog"
    TROUBLESHOOTING = "troubleshooting"
    DEPENDENCY_MAP = "dependency_map"


class RetrievalMode(StrEnum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class RetrievalFilters(Contract):
    doc_types: list[DocType] | None = None
    services: list[str] | None = None
    tags: list[str] | None = None


class RetrievedChunk(Contract):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version: int
    source_uri: str
    title: str
    doc_type: DocType
    heading_path: str
    snippet: str
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str | None = Field(default=None, description="complete chunk text (citation snapshot)")
    content_sha256: str | None = None


class SearchResponse(Contract):
    query_id: uuid.UUID
    query: str
    mode: RetrievalMode
    results: list[RetrievedChunk]
    latency_ms: float
    warnings: list[str] = Field(default_factory=list, description="e.g. degraded to keyword-only")
    effective_mode: RetrievalMode | None = Field(
        default=None, description="mode actually used; differs from ``mode`` when hybrid degraded to keyword-only"
    )
    context: list[RetrievedChunk] = Field(
        default_factory=list,
        description="other sections of the top-ranked current operational document (same version), when requested "
        "with expand_sections; never from non-current documents",
    )
