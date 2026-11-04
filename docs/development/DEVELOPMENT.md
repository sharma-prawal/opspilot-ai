# Development Guide

## Environment variables

All configuration is in `.env` (created by `make bootstrap` from `.env.example` with random local
secrets) and read through `opspilot_shared.config.Settings`. `.env.example` documents every variable.
The secrets that matter:

| Variable | Used by | Notes |
|---|---|---|
| `POSTGRES_SUPERUSER_PASSWORD` | container init + `scripts/db-ensure.sh` only | the app never uses the superuser |
| `DB_PASSWORD` | API, MCP servers, migrations | non-superuser role `opspilot_app` |
| `OPERATOR_TOKEN` | API (approval/cancel/ingest), web BFF (server side) | operator endpoints are disabled if shorter than 16 chars |
| `ACTION_SIGNING_KEY` | API (issues) + MCP action server (verifies) | HMAC key for approval tokens |

## Workflow

```bash
make dev                 # API :8000 (logs .run/api.log), web :3000 (logs .run/web.log)
make test                # 72 deterministic Python tests + web unit tests; needs only Postgres
make lint                # ruff, mypy --strict, import-linter, eslint, tsc
make test-live           # real-model tests (Ollama)
make e2e                 # Playwright against the running stack
make evaluate            # measured benchmark → docs/evaluation/BASELINE.md
```

Tests run against the separate `opspilot_test` database (the conftest refuses any database whose name
does not end in `_test`). Deterministic tests use a feature-hashing embedder and a scripted chat model,
but real PostgreSQL, the real LangGraph checkpointer and the real MCP protocol (in-process and stdio).

## Test map

| Concern | Tests |
|---|---|
| Parsing, normalisation, chunking, RRF, tsquery sanitisation | `tests/unit/test_chunking_parsing.py`, `test_retrieval_logic.py` |
| Onset detection, log clustering, change correlation | `tests/unit/test_analysis.py` |
| Remediation validation, routing, budgets, plan policy, approval payload checks | `tests/unit/test_nodes_policy.py` |
| Approval token crypto | `tests/unit/test_approval_tokens.py` |
| Schema inlining regression, simulator determinism, answer-key isolation | `tests/unit/test_schema_and_simulator.py` |
| Ingestion (dedup, incremental, versioning, failures, dim guard), retrieval modes/filters/traces | `tests/integration/test_ingestion_retrieval.py` |
| MCP protocol (listing, schemas, structured results, errors, stdio transport) | `tests/integration/test_mcp_protocol.py` |
| Checkpoint persistence across "restart", rejection path | `tests/integration/test_checkpoint_resume.py` |
| HTTP contract incl. 401/409 approval cases, cancel, report citations, token redaction | `tests/integration/test_api.py` |
| Action-server enforcement (pending, forged/expired/mismatched tokens, idempotent replay) | `tests/security/test_action_enforcement.py` |
| Prompt injection (fencing, fabricated citations, out-of-scope targets, human gate) | `tests/security/test_prompt_injection.py` |
| Live model: embedding dim, structured output, full real-model investigation | `tests/integration/test_live_llm.py` |
| UI critical path | `apps/web/e2e/investigation.spec.ts` |

## Adding things

- **A tool**: add a typed function to `packages/mcp/opspilot_mcp/read_server.py` (pydantic return type,
  bounded `Annotated` inputs), add it to `READ_TOOLS`, call it from a node via `_Calls`.
- **A scenario**: implement the `Scenario` protocol in `services/simulator/opspilot_simulator/scenarios/`,
  register it, add ground truth in `datasets/evaluation/ground_truth/`.
- **A document format**: implement `Parser` in `packages/rag/opspilot_rag/parsing.py`.
- **A model**: change `LLM_MODEL`/`EMBEDDING_MODEL`; a different embedding dimension needs a migration + `make ingest ARGS=--reindex`.

## Observability

- Logs: structured JSON on stderr with `correlation_id`, `incident_id`, `investigation_id`, `node`,
  `tool_call_id`, latency and token counts.
- Traces: OpenTelemetry spans (`http …`, `investigation.run`, `agent.node/*`, `mcp.tool/*`, `llm.*`, `rag.*`).
  `OTEL_EXPORTER=console` prints them; for a UI: `make infra-up PROFILES=observability`, `uv sync --extra otlp`,
  `OTEL_EXPORTER=otlp`, then open Jaeger at <http://127.0.0.1:16686>.
- Built-in: `ops.workflow_events`, `ops.tool_invocations`, `kb.retrieval_queries` (all exposed via the API/UI).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose` uses an old plugin | scripts use `docker-compose` (v5) automatically |
| `make dev` says port in use | `make stop`, or another process owns the port (`lsof -iTCP:8000 -sTCP:LISTEN`) |
| investigation shows `interrupted` after a restart | press *Resume from checkpoint* or `POST /investigations/{id}/resume` |
| slow first investigation | model cold load (~4 s) + embedding load; later runs ~25 s to approval |
