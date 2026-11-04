# Data Model

One PostgreSQL 17 database (`opspilot`) with four schemas. ORM models:
`packages/shared/opspilot_shared/db/models.py`. Migrations: `infra/db/migrations` (Alembic),
except `langgraph.*`, which is owned and migrated by `langgraph-checkpoint-postgres`'s `setup()`
(invoked by `make migrate`, never on application start-up).

| Schema | Owner (single writer) | Purpose |
|---|---|---|
| `ops` | API | incidents, investigations, evidence, workflow events, action requests, audit log |
| `kb` | RAG ingestion | documents, chunks (+ embeddings, tsvector), ingestion runs, retrieval traces |
| `sim` | Simulator (+ action server via simulator API) | synthetic environment: services, dependencies, deployments, config changes, logs, metrics |
| `langgraph` | LangGraph checkpointer | checkpoints, blobs, writes, checkpointer migrations |

```mermaid
erDiagram
  INCIDENTS ||--o{ INVESTIGATIONS : has
  INVESTIGATIONS ||--o{ WORKFLOW_EVENTS : emits
  INVESTIGATIONS ||--o{ EVIDENCE : collects
  INVESTIGATIONS ||--o{ ACTION_REQUESTS : proposes
  ACTION_REQUESTS ||--o{ AUDIT_LOG : "audited by"
  SIM_ENVIRONMENTS ||--o{ INCIDENTS : "raised in"
  SIM_ENVIRONMENTS ||--o{ SIM_DEPLOYMENTS : contains
  SIM_ENVIRONMENTS ||--o{ SIM_LOGS : contains
  SIM_ENVIRONMENTS ||--o{ SIM_METRICS : contains
  KB_DOCUMENTS ||--o{ KB_CHUNKS : "split into"

  INCIDENTS {
    uuid id PK
    text reference UK "INC-YYYYMMDD-NNNN"
    text title
    text severity "SEV1..SEV4"
    text status
    text service
    uuid environment_id FK
    timestamptz detected_at
  }
  INVESTIGATIONS {
    uuid id PK "= LangGraph thread_id"
    uuid incident_id FK
    text status
    text current_step
    jsonb result "structured RCA"
    text report_markdown
    text error
  }
  EVIDENCE {
    uuid investigation_id PK
    text evidence_id PK "stable, content-derived"
    text kind
    text source_tool
    text summary
    jsonb data
    jsonb citation "document_id, chunk_id"
  }
  ACTION_REQUESTS {
    uuid id PK "uuid5(thread, params_hash)"
    uuid investigation_id FK
    text action_type
    jsonb parameters
    text params_hash
    text status
    text decided_by
    jsonb execution_result
    jsonb verification
  }
  KB_DOCUMENTS {
    uuid id PK "uuid5(source_uri)"
    text source_uri UK
    text doc_type
    text content_hash
    int version
    uuid duplicate_of
  }
  KB_CHUNKS {
    uuid id PK
    uuid document_id FK
    int ordinal
    text heading_path
    text content
    vector embedding "dim = EMBEDDING_DIMENSIONS (1024 verified)"
    tsvector tsv "generated, GIN"
  }
```

## Status enumerations

- Incident: `open → investigating → awaiting_approval → mitigated | resolved`, or `open` again on failure.
- Investigation: `queued → running → awaiting_approval → running → completed | failed | cancelled`.
- Action request: `pending → approved → executing → succeeded | failed`, or `pending → rejected | cancelled`.
  Transitions are guarded by conditional `UPDATE … WHERE status = :expected RETURNING`,
  which makes approval and execution idempotent and race-safe.

## Indexes

- `kb.chunks.embedding` — HNSW (`vector_cosine_ops`).
- `kb.chunks.tsv` — GIN; `tsv` is a generated column over title + heading path + content.
- `sim.logs (environment_id, service, ts)`, `sim.logs.tsv` GIN, `sim.metrics (environment_id, service, name, ts)`.
- `ops.workflow_events (investigation_id, id)`, `ops.action_requests (status)`.

## Ground truth isolation

Scenario answer keys are **not** stored in the database. `sim.environments` stores only the scenario
key and seed needed to regenerate data. Ground truth lives in
`datasets/evaluation/ground_truth/*.json` and is read only by the evaluation package.
