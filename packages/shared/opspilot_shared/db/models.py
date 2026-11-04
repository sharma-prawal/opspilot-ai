"""ORM models for the ``ops``, ``kb`` and ``sim`` schemas.

Each schema has a single writer (see docs/architecture/DATA_MODEL.md). JSONB is used for
open-ended structured payloads that are validated by pydantic contracts at the boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opspilot_shared.config import get_settings
from opspilot_shared.db.base import Base

EMBEDDING_DIM = get_settings().embedding_dimensions
TZ = DateTime(timezone=True)


def _now() -> Any:
    return mapped_column(TZ, server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------------------- sim
class SimEnvironment(Base):
    __tablename__ = "environments"
    __table_args__ = {"schema": "sim"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scenario_key: Mapped[str] = mapped_column(String(32))
    seed: Mapped[int] = mapped_column(Integer)
    sim_now: Mapped[datetime] = mapped_column(TZ)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class SimService(Base):
    __tablename__ = "services"
    __table_args__ = {"schema": "sim"}
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sim.environments.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    tier: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(63))
    current_version: Mapped[str] = mapped_column(String(32))
    replicas: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class SimDependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = {"schema": "sim"}
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sim.environments.id", ondelete="CASCADE"), primary_key=True
    )
    service: Mapped[str] = mapped_column(String(63), primary_key=True)
    depends_on: Mapped[str] = mapped_column(String(63), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    critical: Mapped[bool] = mapped_column(Boolean)


class SimDeployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_sim_deployments_env_started", "environment_id", "started_at"),
        {"schema": "sim"},
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sim.environments.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service: Mapped[str] = mapped_column(String(63))
    kind: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    previous_version: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(String(32))
    author: Mapped[str] = mapped_column(String(63))
    change_summary: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class SimConfigChange(Base):
    __tablename__ = "config_changes"
    __table_args__ = {"schema": "sim"}
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sim.environments.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service: Mapped[str] = mapped_column(String(63))
    key: Mapped[str] = mapped_column(String(200))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(TZ)
    author: Mapped[str] = mapped_column(String(63))


class SimLog(Base):
    __tablename__ = "logs"
    __table_args__ = (
        Index("ix_sim_logs_env_service_ts", "environment_id", "service", "ts"),
        Index("ix_sim_logs_tsv", "tsv", postgresql_using="gin"),
        {"schema": "sim"},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim.environments.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TZ)
    service: Mapped[str] = mapped_column(String(63))
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    logger: Mapped[str | None] = mapped_column(String(200))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', message)", persisted=True))


class SimMetric(Base):
    __tablename__ = "metrics"
    __table_args__ = {"schema": "sim"}
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sim.environments.id", ondelete="CASCADE"), primary_key=True
    )
    service: Mapped[str] = mapped_column(String(63), primary_key=True)
    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class SimInspection(Base):
    """Point-in-time structured observations (datastore status, queue status) as an ops tool would return."""

    __tablename__ = "inspections"
    __table_args__ = (Index("ix_sim_inspections_lookup", "environment_id", "kind", "target", "ts"), {"schema": "sim"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim.environments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(63))
    ts: Mapped[datetime] = mapped_column(TZ)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class SimQueueMessage(Base):
    """Structured queue records. Status transitions model retries, dead-lettering and quarantine (never deletion)."""

    __tablename__ = "queue_messages"
    __table_args__ = (Index("ix_sim_queue_messages_lookup", "environment_id", "queue", "status"), {"schema": "sim"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim.environments.id", ondelete="CASCADE"))
    queue: Mapped[str] = mapped_column(String(63))
    message_id: Mapped[str] = mapped_column(String(64))
    producer_service: Mapped[str] = mapped_column(String(63))
    producer_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))  # pending | dead_lettered | quarantined | processed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ)


class SimActionExecution(Base):
    """Idempotency ledger for sandbox actions: one row per executed action_id."""

    __tablename__ = "action_executions"
    __table_args__ = {"schema": "sim"}
    action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim.environments.id", ondelete="CASCADE"))
    action_type: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    params_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    executed_at: Mapped[datetime] = _now()


# ---------------------------------------------------------------------------------------- kb
class KbDocument(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": "kb"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_uri: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    ingested_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())
    chunks: Mapped[list[KbChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KbChunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": "kb"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.documents.id", ondelete="CASCADE"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    heading_path: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(heading_path, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(content, '')), 'C')",
            persisted=True,
        ),
    )
    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class KbIngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = {"schema": "kb"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(String(16))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class KbRetrievalQuery(Base):
    __tablename__ = "retrieval_queries"
    __table_args__ = {"schema": "kb"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    top_k: Mapped[int] = mapped_column(Integer)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[float] = mapped_column(Float)
    caller: Mapped[str | None] = mapped_column(String(100))
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = _now()


# --------------------------------------------------------------------------------------- ops
class OpsIncident(Base):
    __tablename__ = "incidents"
    __table_args__ = {"schema": "ops"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), index=True)
    service: Mapped[str] = mapped_column(String(63))
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim.environments.id"))
    detected_at: Mapped[datetime] = mapped_column(TZ)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())


ACTIVE_INVESTIGATION_STATUSES = ("queued", "running", "awaiting_approval", "interrupted")


class OpsInvestigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        # At most one active (non-terminal) investigation per incident (audit finding G, migration 0005).
        Index(
            "uq_ops_investigations_one_active_per_incident",
            "incident_id",
            unique=True,
            postgresql_where=text("status IN (" + ", ".join(f"'{x}'" for x in ACTIVE_INVESTIGATION_STATUSES) + ")"),
        ),
        {"schema": "ops"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.incidents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_step: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_markdown: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(64))
    # Execution ownership lease: which API process is running a graph segment, and until when (finding G).
    run_owner: Mapped[str | None] = mapped_column(String(128))
    run_lease_until: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())


class OpsWorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (Index("ix_ops_workflow_events_inv_id", "investigation_id", "id"), {"schema": "ops"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.investigations.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(32))
    node: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class OpsToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = {"schema": "ops"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ops.investigations.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(64))
    server: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[float] = mapped_column(Float)
    result_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ)


class OpsEvidence(Base):
    __tablename__ = "evidence"
    __table_args__ = {"schema": "ops"}
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ops.investigations.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    source_tool: Mapped[str] = mapped_column(String(64))
    collected_by: Mapped[str] = mapped_column(String(64))
    service: Mapped[str | None] = mapped_column(String(63))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    citation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    relevance: Mapped[float] = mapped_column(Float, default=0.5)
    observed_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _now()


class OpsActionRequest(Base):
    __tablename__ = "action_requests"
    __table_args__ = {"schema": "ops"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ops.investigations.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.incidents.id", ondelete="CASCADE"))
    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    action_type: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    params_hash: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    requested_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(TZ)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class OpsWorkflowCommand(Base):
    """Transactional outbox for workflow commands (audit H3).

    Written in the same transaction as the decision it carries, then delivered at least once to the
    LangGraph workflow by a claim-based dispatcher. ``action_id`` is the idempotency key: one command per
    decided action. The approval token is minted at delivery time and never stored here.
    """

    __tablename__ = "workflow_commands"
    __table_args__ = (Index("ix_ops_workflow_commands_status", "status", "claimed_at"), {"schema": "ops"})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ops.investigations.id", ondelete="CASCADE"), index=True
    )
    action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))  # pending | delivering | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    claimed_at: Mapped[datetime | None] = mapped_column(TZ)
    delivered_at: Mapped[datetime | None] = mapped_column(TZ)


class OpsAuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "ops"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = _now()
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
