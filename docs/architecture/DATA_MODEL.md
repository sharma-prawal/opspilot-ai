# Data Model

One PostgreSQL 17 database (`opspilot`) with four schemas. ORM models:
`packages/shared/opspilot_shared/db/models.py`. Migrations: `infra/db/migrations` (Alembic),
except `langgraph.*`, which is owned and migrated by `langgraph-checkpoint-postgres`'s `setup()`
(invoked by `make migrate`, never on application start-up).

| Schema | Owner (single writer) | Purpose |
|---|---|---|
| `ops` | API (one exception: the action server writes `action_requests.status` for the execution claim, C0 H) | incidents, investigations, evidence, workflow events, action requests, outbox, audit log, uploaded datasets (v0.5) |
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

## Uploaded evidence (v0.5, migration 0009)

- `ops.incidents.evidence_source`: `simulator` (has `environment_id`) or `upload` (no environment); a check
  constraint keeps them consistent.
- `ops.uploaded_datasets` (one per uploaded incident, `ON DELETE CASCADE`): `files` (per-file reports: sanitized
  name, size, SHA-256, format, record counts, rejected rows, issues), `summary` (counts, services, time range,
  samples, warnings), `records` (normalized logs, metrics, spans and events with `source`, `ts_original`, `tz`,
  `service_source`), `affected_services`, `timezone`, `storage_dir` (raw copies under `UPLOAD_DIR`). Only the
  application role can read it; the MCP roles have no grant.

## Connected telemetry snapshots (v0.6, migration 0011)

- `ops.incidents.evidence_source` also accepts `connector` (no environment, like `upload`).
- A connected incident has one `ops.uploaded_datasets` row:
  - `files` is empty;
  - `queries` (new JSONB column, `[]` for uploads) holds the provenance of each Loki/Prometheus query;
  - `records` holds the normalized logs and metrics (`source` = `<connector>/<template>/<service>:entry|point N`,
    `ts_original` as returned, `tz` = `epoch`, `service_source` `record` or `query`, metric `unit` and `labels`) and
    `collected` (services per signal whose queries succeeded);
  - `summary` adds `window`, `connectors`, `redactions` and `collected`.
- v0.9 Datadog snapshots use the same row and columns (no migration):
  - each query adds `signal`, `site`, `link` and `pages`;
  - `records.spans` holds `SpanRecord`s (`source` = `datadog/<template>/<service>:span N`, trace/span/parent IDs,
    `parent_missing` for partial traces);
  - `collected` gains a `span` entry when a span-capable connector was selected.
- Deleted with the incident, like uploads.

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
- `uq_ops_investigations_one_active_per_incident`: a partial **unique** index on `ops.investigations (incident_id)`
  where the status is queued, running, awaiting_approval or interrupted. At most one active investigation per
  incident (migration 0005, C0 G).
- `ops.workflow_commands`: unique `action_id`, plus `(status, claimed_at)` for the outbox dispatcher (migration
  0004, C0 H3).
- `trg_ops_investigations_terminal_guard` (migration 0006, C0-G2): a `BEFORE UPDATE OF status` trigger that refuses
  any status change out of `completed` or `cancelled`.
- `uq_kb_documents_revision` (id, version), `fk_kb_chunks_document_revision` chunks(document_id, document_version) →
  documents(id, version) DEFERRABLE INITIALLY DEFERRED, and `trg_kb_documents_revision_guard` (content change requires a
  higher version; versions never decrease) — migration 0007, C0-H1.
- `ops.execution_owner` (single row: `epoch`, `owner`, `owner_pid`, `acquired_at`), `ops.execution_fence(epoch, pid)` and
  `ops.fence_checkpoint_write()` (migration 0008, C0-H2); statement triggers `trg_fence_checkpoints`,
  `trg_fence_checkpoint_blobs`, `trg_fence_checkpoint_writes` on the LangGraph tables (installed by `opspilot migrate`).

## Execution ownership and outbox (Phase C0)

- `ops.investigations.run_owner` / `run_lease_until`: the API process currently running a graph segment and its
  lease expiry, claimed by compare-and-set and renewed while running.
- `ops.workflow_commands`: the durable decision-delivery outbox (`pending → delivering → delivered | failed`, and
  `pending | delivering → cancelled` in a cancellation's transaction, C0-G2), written in the decision's transaction.
  Approval tokens are never stored.
- Investigation status changes only through `repositories.transition_investigation` (locked compare-and-set against
  `domain.investigation.LEGAL_TRANSITIONS`, C0-G2).
- Execution owner (C0-G4, C0-H2): a session-level advisory lock `(0x4F505350, 1)` per database, held by the one runtime
  that may execute investigations (visible in `pg_locks` with the owner's `application_name`), plus the owner's epoch and
  lock-session PID in `ops.execution_owner`. Checkpoint writes, runner state writes and the action server's execution
  claim are fenced on that `(epoch, pid)` in their own transaction.

## Database roles

| Role | Used by | Rights |
|---|---|---|
| `opspilot_app` | API, migrations, ingestion | owner of all application schemas |
| `opspilot_mcp_read` | MCP read server | SELECT on `sim.*`, `kb.*`, `ops.incidents`; INSERT on `kb.retrieval_queries` |
| `opspilot_mcp_actions` | MCP action server | SELECT/INSERT/UPDATE on `sim.*` (no DELETE); SELECT on `ops.action_requests`; UPDATE of `ops.action_requests.status` only (the execution claim) |

Provisioned by `scripts/db-roles.sh` (`make db-roles`, also run by bootstrap); idempotent and additive. Without
role passwords in `.env`, the MCP children fall back to `opspilot_app`.

## Ground truth isolation

Scenario answer keys are **not** stored in the database. `sim.environments` stores only the scenario
key and seed needed to regenerate data. Ground truth lives in
`datasets/evaluation/ground_truth/*.json` and is read only by the evaluation package.
