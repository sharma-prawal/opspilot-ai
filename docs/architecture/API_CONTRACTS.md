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
| POST 🔒 | `/api/v1/incidents/upload/preview` | v0.5. `{"files": [{"name", "content", "service"?}], "timezone", "incident_time"?, "service"?, "affected_services"}` → per-file reports (format, records by signal, rejected, issues), summary, coverage warnings, sample records. Stores nothing. `422` for unsupported types or exceeded limits |
| POST 🔒 | `/api/v1/incidents/upload` | v0.5. Preview body plus `title`, `description`, `service`, `severity`, `incident_time` → `201` incident with `evidence_source: "upload"` and `environment_id: null`. `422` if no file is usable or no log/metric/trace belongs to `service` |
| POST 🔒 | `/api/v1/incidents/connected/preview` | v0.6 (Datadog v0.9, Azure Monitor v0.10, AWS CloudWatch v0.11). `{"sources": [{"connector": "loki"\|"prometheus"\|"datadog"\|"azure_monitor"\|"cloudwatch", "templates": [ids]}] (≤ 4 sources, each once), "service", "affected_services" (≤ 3), "start", "end" (timezone-aware, ≤ 6 h), "incident_time"?}` → `usable`, `summary` (records, services, time range, redactions), `queries` (provenance per query: id, connector, endpoint, rendered query, window, step/limit, status `ok`/`empty`/`error`, error kind, counts, truncated; v0.9: `signal`, `site`, `link`, `pages`; v0.10: `workspace`, `tables`; v0.11: `aws` (region, account, log groups, Logs Insights query ID, final status, polls, scan statistics, stopped/stop error, partial, `not_queried`, or metric definitions, period and status codes)), `collected` (`log`, `metric`, and `span` when a span-capable connector is selected), `warnings`, `samples` (incl. `span`), `series` (v0.9: returned metric points per service/metric, never resampled). Stores nothing. Unknown fields → `422`; unknown template, window over the limit or in the future → `422`; connector not configured → `409`. Backend failures are per-query errors, never an HTTP 401 |
| POST 🔒 | `/api/v1/incidents/connected` | v0.6. Preview body plus `title`, `description`, `severity`, `incident_time` (required) → `201` incident with `evidence_source: "connector"`, `environment_id: null`; the queries run again and their results are stored as the snapshot. `422` if nothing usable or nothing for `service` |
| GET | `/api/v1/incidents/{id}/dataset` | v0.5/v0.6. Files (uploads) or `queries` (connector snapshot), summary, samples and warnings of a read-only incident (`404` for simulator incidents) |
| POST 🔒 | `/api/v1/incidents/{id}/discard` | v0.5/v0.6. Deletes an uploaded or connected incident with its files, records, investigations and checkpoints; `409` for simulator incidents or while an investigation is active |
| GET | `/api/v1/incidents/{id}` | incident (v0.5: includes `evidence_source`; `environment_id` is null for uploads) |
| GET | `/api/v1/incidents/{id}/investigations` | investigations for the incident |
| POST 🔒 | `/api/v1/incidents/{id}/investigations` | start → `202 {"investigation_id", "status", "status_url"}`; `409` if one is already active (DB-enforced; concurrent duplicates answer 409 even at the admission limit); `429` at the admission limit, with nothing written. A `202` row is durable: if dispatch fails it is re-dispatched by the maintenance sweep |

## Connectors (v0.6; Datadog v0.9; Azure Monitor v0.10; AWS CloudWatch v0.11)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/connectors` | `connectors` (Loki, Prometheus, Datadog: `configured`, `signal`, `signals`, `endpoint` without credentials, `auth` mode, `tenant`, `service_label`, `templates` (with `signal`), `limits`; Datadog adds `site`, `fixture`, `env`, `log_indexes`, `permissions`, `read_only_endpoints`, `limits_extra`; Azure Monitor adds `workspace_id`, `auth_mode`, `cloud`, `fixture`, `tables`, `permissions`, `read_only_endpoints`, `limits_extra`; AWS CloudWatch adds `region`, `partition`, `auth_mode`, `profile` (name only), `role_arn`, `expected_account`, `fixture`, `log_groups`, `services` (mapping summary), `permissions.actions`, `read_only_endpoints`, `limits_extra` — never a key or token; or `problem`/`hint` when not configured), `template_problems`, `planned` (not implemented), `max_queries`. No secrets |
| POST 🔒 | `/api/v1/connectors/{id}/test` | one build-info + auth probe → `{"status": "ok"\|"partial"\|"auth_error"\|"rate_limited"\|"unavailable"\|"error"\|"not_configured", "message", "version", "latency_ms", "signals"}`. Datadog (v0.9): API-key validation, then one minimal read per product; `signals.{log,metric,span}.status` is `ok`/`permission_denied`/`unsupported`/`rate_limited`/`unavailable`/`error`. Azure Monitor (v0.10): token, one `print` probe, then one `take 1` per table; status may also be `permission_denied`, and `tables.{AppTraces,AppExceptions,AppRequests,AppDependencies}` reports each table. AWS CloudWatch (v0.11): `sts:GetCallerIdentity` → `identity` (account, principal kind, role name, region; never the ARN), `DescribeLogGroups` on the configured groups, one 1-minute `fields @timestamp \| limit 1` Logs Insights query per existing group (≤ 10) and one `GetMetricData` probe → `log_groups.{<name>}` (`ok`/`unsupported` = not found/`permission_denied`/…) and `signals.{log,metric}`. `422` for an unknown connector |
| POST 🔒 | `/api/v1/connectors/{id}/services` | `{"start", "end"}` → `{"services": [values of the service label in the window], "error", "notes"}`. Datadog: one log aggregate over the `service` facet (top 50); `notes` report untagged logs and names that are not valid service slugs. Azure Monitor: one fixed `union isfuzzy=true` count by `AppRoleName` (top 50); `notes` report records without a role, mixed-case and unusable role names. AWS CloudWatch: the services of `CLOUDWATCH_RESOURCES_FILE` (never inferred); `notes` report log groups not found or not checkable and services without logs or metrics; no log or metric data is read |

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

Approval tokens (C0-H2) also carry the minting execution owner's epoch and lock-session PID; the action server's claim
transaction refuses a token whose owner is no longer current, and tokens without an owner binding.

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
