# API Contracts

FastAPI serves interactive docs at `http://127.0.0.1:8000/docs` and the schema at `/openapi.json`
(the authoritative contract; this page summarises it). All bodies are JSON.

## Conventions

- **Long-running work** returns `202 Accepted` with an operation ID (`investigation_id`) and a
  `status_url` to poll. Investigations run in a bounded background runner.
- **Errors** from domain logic: `{"error": {"class": "<error_class>", "message": "..."}}`.
  Request validation errors use FastAPI's standard `422` `{"detail": [...]}` with locations.
- **Status codes**:
  - `200/201/202` success;
  - `401` missing or invalid operator token;
  - `404` not found;
  - `409` state conflict: wrong status, params-hash mismatch, an active investigation already exists for the
    incident, already running, replay, or cancel refused after the execution claim;
  - `422` validation;
  - `429` admission limit reached (retry later; nothing was written);
  - `503` not ready, or `execution_owner_unavailable`: this process does not (or no longer) own execution for its
    database (C0-G4; another runtime holds the single-owner lock or the lock was lost).
- **Correlation**: send `X-Request-ID` (optional); it is echoed back and bound to every log line.
- **Auth**:
  - **Every POST** requires `Authorization: Bearer <OPERATOR_TOKEN>` (C0 H1); 🔒 marks them below.
  - GETs are unauthenticated on localhost.
  - The web UI never holds the token. Its BFF (`/api/ops/*`) requires a signed-in session for every call and,
    for mutations, also same-origin, a CSRF header (`x-opspilot-csrf`), `application/json` and the right role.
    It then injects the token server-side and takes decision/cancel identity from the session.
  - Session endpoints: `POST /api/session` (sign in), `GET /api/session`, `DELETE /api/session`.
- **Redaction**: free-form JSON in responses (tool-call arguments, event payloads, results, action parameters)
  passes the central credential redaction policy; credentials appear as `[REDACTED]`.
- **CORS**: allowlist from `CORS_ALLOWED_ORIGINS` (default: localhost:3000), methods GET/POST only.

## Health

| Method | Path | Description |
|---|---|---|
| GET | `/health/live` | process is up |
| GET | `/health/ready` | `200` when Postgres, Ollama (+ models), both MCP sessions and the execution-owner lock (C0-G4) are OK, else `503` |
| GET | `/health/dependencies` | detailed checks (pgvector version, migration head, KB size, missing models, MCP tool lists) + config |

## System

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/system/overview` | counts by status (incidents, investigations, actions), KB size, model + budget config |
| GET | `/api/v1/system/identity` | `{"database", "test_database", "instance"}`; E2E refuses to mutate unless `*_test` + `e2e` |

## Knowledge

| Method | Path | Description |
|---|---|---|
| POST 🔒 | `/api/v1/knowledge/ingest` | `{"reindex": false}` → ingestion report (per-file outcome: created/updated/metadata_updated/unchanged/duplicate/failed) |
| GET | `/api/v1/knowledge/documents` | documents with version, status, duplicate_of, chunk count, hash |
| GET | `/api/v1/knowledge/ingestion-runs` | recent runs with stats |
| POST 🔒 | `/api/v1/knowledge/search` | `{"query", "mode": "hybrid"\|"vector"\|"keyword", "top_k", "filters": {"doc_types", "services", "tags"}}` → `SearchResponse`; explicitly authorised historical search: obsolete documents included, labelled and ranked last (the agent's MCP tools exclude them, C0-G3) |
| GET | `/api/v1/knowledge/queries/{query_id}` | retrieval trace: filters, ranked chunk IDs with vector/keyword ranks, latency, caller |

`RetrievedChunk`: `chunk_id, document_id, document_version, source_uri, title, doc_type, heading_path, snippet, score, vector_rank, keyword_rank, metadata`.

## Incidents

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/incidents?status=` | list |
| GET | `/api/v1/incidents/scenarios` | available simulator scenarios |
| POST 🔒 | `/api/v1/incidents/simulate` | `{"scenario": "INC-001"}` → `201` new environment + incident |
| GET | `/api/v1/incidents/{id}` | incident |
| GET | `/api/v1/incidents/{id}/investigations` | investigations for the incident |
| POST 🔒 | `/api/v1/incidents/{id}/investigations` | start → `202 {"investigation_id", "status", "status_url"}`; `409` if one is already active (DB-enforced; concurrent duplicates answer 409 even at the admission limit); `429` at the admission limit, with nothing written. A `202` row is durable: if dispatch fails it is re-dispatched by the maintenance sweep |

## Investigations

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/investigations/{id}` | status, current step, result (classification, plan, rca, proposed_action, …), `executing_in_process` |
| GET | `/api/v1/investigations/{id}/events?after=` | ordered workflow events (node started/completed with tool + LLM call summaries, approvals, run lifecycle) |
| GET | `/api/v1/investigations/{id}/tool-calls` | every MCP tool invocation: arguments, status, latency, summary/error |
| GET | `/api/v1/investigations/{id}/evidence` | evidence items (kind, source tool, summary, data, citation, relevance) |
| GET | `/api/v1/investigations/{id}/actions` | action requests for this investigation |
| GET | `/api/v1/investigations/{id}/report` | `{"markdown", "status", "result"}`; `404` until finished |
| GET | `/api/v1/investigations/{id}/workflow` | live checkpoint view: `next` nodes, pending interrupts, queue, counts |
| POST 🔒 | `/api/v1/investigations/{id}/resume` | continue an `interrupted`/stalled run from its last checkpoint (`409` while awaiting approval — use approvals) |
| POST 🔒 | `/api/v1/investigations/{id}/cancel` | `{"actor"}`; revokes `pending`/`approved` actions and undelivered decision commands, then stops the run; `409` once an action is claimed for execution, or if already terminal |

Investigation status: `queued → running → awaiting_approval → running → completed | failed | cancelled`;
`interrupted` marks runs whose process died (resumable). C0-G2: `completed` and `cancelled` are absorbing (also
enforced by a database trigger); `failed` is reopened only by an explicit `/resume` (→ `interrupted` → `running`);
no background work (reconciliation, delivery, expiry, restart) ever leaves a terminal state.

## Approvals

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/approvals?status=pending\|approved\|rejected\|cancelled\|succeeded\|failed\|all` | action requests |
| GET | `/api/v1/approvals/{action_id}` | one action request incl. execution result and verification |
| POST 🔒 | `/api/v1/approvals/{action_id}/decision` | `{"decision": "approve"\|"reject", "params_hash": "<64 hex>", "decided_by", "comment"}` |

Decision validation (all server-side): action is `pending`; `params_hash` equals the stored hash and the
hash recomputed from stored parameters; the workflow is paused on this action; not currently executing;
compare-and-set `pending → approved|rejected`. The decision and its delivery command are committed
together (outbox). At delivery an HMAC token (TTL `APPROVAL_TOKEN_TTL_SECONDS`) bound to
`(action_id, params_hash)` is minted; the MCP action server verifies it, then claims the action
(`approved → executing`) under a row lock before executing. Action status adds `executing`.

## MCP tools (internal contract)

Read server `opspilot-ops-read` (all `readOnlyHint=true`): `get_incident`, `search_logs`, `query_metrics`,
`get_service_health`, `list_recent_deployments`, `get_config_changes`, `get_service_dependencies`,
`search_runbooks`, `get_historical_incidents`.
Action server `opspilot-ops-actions`: `execute_remediation(action_id, approval_token)` (`destructiveHint=true`;
no parameter arguments — parameters come from the persisted request), `get_action_execution(action_id)`.
Bounds: service names `^[a-z][a-z0-9-]{1,62}$`, windows ≤ 24 h, `limit ≤ 500`, `top_k ≤ 10`, query ≤ 500 chars,
`search_runbooks.expand_sections ≤ 4` (default 0: further sections of the top current runbook, returned in `context`;
C0-F3). Both knowledge tools exclude superseded/withdrawn documents and return lifecycle-validated passages (C0-G3).
