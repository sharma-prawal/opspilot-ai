# OpsPilot AI

**Local-first, agentic incident investigation.** OpsPilot correlates telemetry, change history,
service dependencies and operational knowledge to produce evidence-cited root-cause hypotheses,
proposes a remediation from a fixed catalogue, **waits for a human to approve it**, executes it in
a sandbox, verifies recovery and writes an RCA report.

Everything runs on one laptop: open-weight models via native Ollama, one PostgreSQL (with
pgvector), no paid APIs, no cloud services, no production access.

> **Status: v0.6.0-dev (feature/connected-observability-v06), experimental, local-first.** v0.6 adds read-only Grafana Loki and Prometheus connectors ([below](#connected-observability-v06)); v0.5 added analysis of uploaded files. v0.4 added configurable local models, agent reasoning improvements and two safety-gate fixes ([release notes](docs/releases/V0.4.0_NOTES.md)). v0.3.0: Redesigned operator console, interactive architecture explorer, source-agnostic integration catalog, and in-app developer guide. Remediation acts only on a deterministic simulator. Run one API worker per database. Not intended for multi-user or network-exposed use. See [Limitations](#limitations).

```
Alert ─► LangGraph investigation ──► MCP tools ──► simulated payment platform
            │  supervisor plan            (logs, metrics, deploys, deps, health)
            │  telemetry / dependencies / changes / knowledge (hybrid RAG)
            │  RCA (local model set by LLM_MODEL, schema-constrained, citations validated)
            ▼
         proposal ─► interrupt ─► operator approves (signed, hash-bound) ─► sandbox action ─► verify ─► report
```

## What is implemented (and verified)

| Area | State |
|---|---|
| Native Ollama; investigation model selected by `LLM_MODEL` (preferred `qwen3.5:9b-q4_K_M`, fallback `qwen3:8b`), embeddings `qwen3-embedding:0.6b` (dim verified = 1024); `opspilot models --probe` checks a model before use; models are downloaded only on explicit opt-in (`make models`) | ✅ (v0.4) |
| PostgreSQL 17 + pgvector 0.8.7 in Colima, Alembic migrations (0001–0011), LangGraph Postgres checkpoints | ✅ |
| Read-only analysis of uploaded log/metric/trace/event files (v0.5) and of Loki/Prometheus telemetry snapshots (v0.6) through the same LangGraph workflow | ✅ |
| Incremental RAG ingestion (hashing, versioning, dedup, lifecycle status) and hybrid retrieval (pgvector + full-text, RRF) that degrades to keyword-only when embeddings are down | ✅ |
| Lifecycle-aware retrieval (superseded guidance never reaches investigations), serialized per-document revision publication, version/hash-pinned passages, self-verifying citation snapshots | ✅ (v0.2.1) |
| Deterministic simulator: **INC-001** schema migration, **INC-002** pool exhaustion, **INC-003** poison messages, **NEG-001** false positive, **NEG-002** external dependency with an unrelated deploy, **NEG-003** ambiguous changes + log outage | ✅ |
| Two MCP servers over stdio (13 read tools, 2 action tools), supervised sessions with bounded reconnection | ✅ |
| LangGraph workflow: supervisor plan, evidence-driven routing, RCA, **multi-step plans approved step by step**, verification, deterministic **outcomes and escalation** | ✅ |
| Evidence-based safety gates on model proposals (impact, correlation, ambiguity, causal consistency, capacity, abnormality, plan shape) | ✅ |
| Backend-enforced approvals: operator token on every mutation, params-hash binding, CAS transitions, HMAC token re-verified by the executor, row-locked execution claim (non-cancellable boundary), idempotent execution, request expiry, **crash-safe decision delivery** (transactional outbox) | ✅ |
| Signed-in operator UI (session, CSRF, roles), central credential redaction, least-privilege MCP database roles, bounded resources | ✅ (v0.2.1) |
| Evidence-complete recovery verification (tri-state impact, observed-incident scope, `verification_incomplete`), uncertain plans withheld | ✅ (v0.2.1) |
| Monotonic terminal states, cancellation-safe execution claim, atomic admission (HTTP 429, nothing persisted) | ✅ (v0.2.1) |
| Single execution owner per database (advisory lock, runtime lifecycle) with epoch fencing of checkpoint writes, runner writes and remediation claims | ✅ (v0.2.1) |
| Workflow survives API restart; MCP child crash recovered transparently | ✅ |
| FastAPI (26 endpoints) and Next.js 16 operator UI (outcome, plan, blocked proposals, evidence, timeline, report) | ✅ |
| Tests: 304 deterministic + 30 web unit + 3 live-model + isolated Playwright e2e (own API on `opspilot_test`, identity-checked); ruff, mypy `--strict`, import-linter; CI on every push | ✅ |
| Held-out retrieval set and incident-level evaluation across all scenarios with retained traces | ✅ |

Headline measurements come from the v0.2.1 evaluation: `qwen3:8b`, temperature 0, 13 live runs over six
scenarios. Details, per-scenario tables and caveats are in BASELINE and the
[release notes](docs/releases/V0.2.1_NOTES.md#evaluation).

**What the gated system did:**
- correct final outcome in 13/13 runs (6 mitigations, 6 correct non-remediation outcomes, 1 rejection);
- recovery verified in 6/6 mitigations;
- 0 unsafe, forbidden or unauthorized actions executed, and 0 approval bypasses;
- false-positive remediation rate 0;
- citation validity 1.0.

**What the model proposed before the gates:**
- its own plan was acceptable in only 3 of 12 runs;
- root cause correct in 7 of 9 determinable cases (NEG-002 blames an unrelated deployment);
- 11 policy interventions, including 1 unsafe proposal;
- a rollback proposed in every negative scenario run.

The deterministic gates and human approval, not the model, produce the correct outcomes.

Held-out retrieval: hybrid Recall@5 0.972. On the agent's actual path, a relevant passage reached the RCA prompt for
every held-out question (MRR 0.603).

### Analyze your own incident data (v0.5)

Upload evidence exported from your own systems on **Analyze files** (`/incidents/new`), preview what OpsPilot
extracted, then run the same LangGraph investigation with your local Ollama model.

**Sanitize before uploading.** Remove customer data, personal data and secrets from the files first. OpsPilot redacts
values that look like credentials (password/token/secret/API-key fields, bearer tokens, AWS keys, private keys) as a
safety net, but it cannot recognize every kind of sensitive data.

| File | Read as |
|---|---|
| `.log`, `.txt` | one entry per line starting with a timestamp (ISO-8601, epoch, or `[18/Nov/2026:10:02:03 +0000]`); level and `key=value` pairs such as `upstream=`, `trace_id=` are recognized; stack-trace lines join the entry above; JSON lines also work |
| `.json` | an array of objects, an object holding one (`records`, `events`, `logs`, …), JSON Lines, or an OTLP/JSON trace export (`resourceSpans`). Each object becomes a log (message), metric sample (name + numeric value), trace span (trace and span IDs) or change event (deployment, rollback, migration, config change, alert) |
| `.csv` | a header with a timestamp column, then one numeric column per metric, `metric,value[,unit]` rows, or an event-type column. Units come from headers like `latency (ms)` or suffixes like `_ms`, `_ratio` |

- **Limits:** 5 files per incident, 5 MB each, 8 MB total, 50 000 records.
- **Preview first.** Before anything is stored you see records per signal, rejected rows and why, services, time
  range, timezones, redactions and sample records with `file:line` sources.
- **Nothing invented.** Records without a timestamp or service are rejected, not filled in. Timestamps without an
  offset are read in the timezone you choose and marked as assumed. A record without a service uses the service you
  declare for its file.
- **Read-only.** Uploaded incidents get evidence correlation, ranked hypotheses with citations to your files,
  uncertainty and evidence gaps, recommended next steps, suggested remediation (checked by the same evidence gates)
  and a downloadable Markdown report. No approval is requested, nothing is executed, and recovery is never claimed.
  Live health, configuration, datastore and queue state cannot come from files; the report lists them as gaps.
- **Local only.** Raw files are kept under `UPLOAD_DIR` (default `var/uploads`, git-ignored, owner-only
  permissions) and the normalized records in the local database. Inference uses your local Ollama model; nothing is
  sent to an external AI API. File content is treated as data, never as instructions.
- **Deletion.** **Delete uploaded data** on an uploaded incident removes its files, normalized records,
  investigations and their checkpoints. `make uploads-purge` (API stopped) deletes uploads older than
  `UPLOAD_RETENTION_DAYS` (default 14); `uv run opspilot uploads list` lists them.

**Example data:** synthetic files for a checkout outage after a payment-service deploy are in
[`apps/web/public/examples/uploads/`](apps/web/public/examples/uploads/) (a text log, a metrics CSV, change events and
OTLP traces; regenerate with `scripts/generate_upload_examples.py`). Download them from the upload page, or use
**Load example into the form**. Design: D103–D108 in [DECISIONS.md](docs/DECISIONS.md).

### Connected observability (v0.6)

Investigate real telemetry from **Grafana Loki** (logs) and **Prometheus** (metrics) with the same workflow: on
**Incidents → Use Loki / Prometheus** (`/incidents/new?source=connected`) pick the configured sources, test the
connection, give the affected service and an incident window, choose approved query templates, preview what came
back, then start the read-only investigation. Azure Monitor, Datadog, CloudWatch and custom adapters are **planned,
not implemented**; [CONNECTORS.md](docs/integrations/CONNECTORS.md) has the interface contract for adding one.

```bash
make telemetry-up   # local Loki (127.0.0.1:3310, tenant opspilot-demo) + Prometheus (127.0.0.1:9390), synthetic incident
# then in .env (or the API's environment) and restart the API:
LOKI_URL=http://127.0.0.1:3310
LOKI_TENANT_ID=opspilot-demo
PROMETHEUS_URL=http://127.0.0.1:9390
TELEMETRY_TEMPLATES_FILE=infra/telemetry/query-templates.json
```

- **Only configured destinations.** Requests carry template IDs, service names and a window — never a URL or query
  text. The client sends only `GET`s to the official query endpoints (`/loki/api/v1/query_range`,
  `/api/v1/query_range`, label and build-info endpoints), follows no redirects, ignores proxy/netrc settings, and
  enforces timeouts, a 6 h window, line/series limits and a response-size cap.
- **Credentials** live in the API environment only (`*_BEARER_TOKEN` or basic auth, plus `LOKI_TENANT_ID`), are never
  returned to the browser, are sent only over https or to loopback, and are scrubbed from error messages.
- **Provenance.** Every log line and metric point keeps its original timestamp, unit, labels and the query that
  returned it (`loki/errors_warnings/payment-service:entry 37`, `prometheus/http_5xx_ratio/checkout-api:point 12`).
  The report lists every query in a provenance table.
- **Snapshot, read-only.** Creating the incident stores the query results with it; the investigation reads only that
  snapshot (`opspilot-connected-telemetry`), never the backends, and runbook RAG stays separate. Nothing is approved
  or executed and recovery is never claimed from historical data. Change history, traces and live state are not part
  of Loki/Prometheus telemetry and stay **unknown**, as does any signal whose queries failed.
- **States** shown in the UI: loading, not configured, connected, authentication failed, unavailable, query rejected,
  no data, truncated.

Demonstrated on the synthetic incident through the UI (one run per model, development testing — not an accuracy
evaluation; confidences are model-estimated and uncalibrated). Both runs ended `analysis_complete`, with nothing
executed:
- **`qwen3:8b`** named payment-service database-pool exhaustion (90%). It attributed it to a slow query from the
  runbooks rather than to the pool shrinking from 50 to 10, which the telemetry shows. A deployment or config change
  came second (70%).
- **`qwen3.5:9b-q4_K_M`** cited the `db_pool_max` drop to 10 and the pool-timeout logs (95%), listed an unobserved
  change as a second hypothesis, and escalated to the database team.

Design: D109–D115 in [DECISIONS.md](docs/DECISIONS.md).

### v0.4 reasoning and model comparison

[MODEL_COMPARISON_V0.4.md](docs/evaluation/MODEL_COMPARISON_V0.4.md) diagnoses the qwen3:8b traces (rollbacks
proposed for a recovered blip and for an external-provider outage, over-confidence under ambiguity, invented queue
actions) and compares models on the six public scenarios, one trial each. The v0.4 RCA prompt opens with a
deterministic evidence digest, asks for an explicit decision before the plan, and restricts cited evidence IDs and
plan identifiers to observed values at decode time, and offers only the catalogue actions the evidence makes
applicable. Two safety-gate gaps found on the way were then fixed (resume of a running consumer; a restart
bypassing a rejected ambiguous rollback) — see §7 of the report.

Development testing on the same six scenarios the changes were tuned on (one trial each), not a generalization
benchmark:

| 6 public scenarios, one trial each | qwen3:8b v0.3 | qwen3:8b v0.4 | qwen3.5:9b-q4_K_M v0.4 |
|---|---|---|---|
| System outcome correct | 6/6 | 6/6 | 6/6 |
| Root cause correct | 3/4 | 4/4 | 4/4 |
| Model's own plan acceptable to the scenario answer key | 2/6 | 3/6 | 6/6 |
| …and admitted unchanged by the safety gates | 2/6 | 3/6 | 5/6 |
| Steps the gates had to reject | 5 | 4 | 1 |
| Model itself abstained/escalated on the 3 negative scenarios | 0/3 | 1/3 | 3/3 |

### Choosing the investigation model

| | Model | Download | Loaded (ctx 8192) | Notes |
|---|---|---|---|---|
| **Preferred** (default in `.env.example`) | `qwen3.5:9b-q4_K_M` | 6.6 GB | 4.9 GB | best raw reasoning in v0.4 tests |
| Fallback | `qwen3:8b` | 5.2 GB | 5.6 GB | v0.1–v0.3 baseline; correct end to end, relies more on the gates |
| Embeddings (both) | `qwen3-embedding:0.6b` | 0.6 GB | 1.0 GB | changing it requires `make ingest ARGS=--reindex` |

Use the explicit `-q4_K_M` tag. On Apple Silicon the plain `qwen3.5:9b` tag resolves to an MLX (nvfp4) build, and
Ollama 0.40.14 answers its structured-output requests with HTTP 501 `structured output is unavailable`; plain chat
works, but the agent needs JSON-schema output. `opspilot models --probe` detects this.

Models are never downloaded silently. Download them explicitly:

```bash
make models                      # pulls LLM_MODEL and EMBEDDING_MODEL from .env (~7.3 GB) and probes them
```

To switch, set `LLM_MODEL` in `.env`, run `make models` (or `ollama pull <tag>`) and restart the API; the UI shows the
active model. To try a model without editing `.env`:

```bash
uv run opspilot models --model qwen3:8b --probe
LLM_MODEL=qwen3:8b uv run opspilot-eval agent --trials 1 --out /tmp/qwen3-8b-check
```

**Planned** (see [ROADMAP](docs/ROADMAP.md)): an independently sealed unseen scenario set to test the gates out of
sample, planner robustness, per-server OS isolation for MCP, INC-004/005, OIDC operator identity, SSE.

## Limitations

v0.2.1 received a **conditional** sign-off from the final independent verification
([report](docs/audits/PHASE_C0_H_INDEPENDENT_VERIFICATION.md)). These limits apply:

1. **Experimental, local-first only.** One machine, local models, services bound to `127.0.0.1`. Uploaded-file
   analysis (v0.5) is read-only and understands common log, JSON and CSV shapes, not every format. The Loki and
   Prometheus connectors (v0.6) were tested only against local containers with synthetic data, and their built-in
   templates assume common metric names.
2. **No production infrastructure access** is implemented or certified. Actions affect only the simulator.
3. **One execution owner per database.** A second API worker, CLI demo or evaluation run on the same database is
   refused. Multi-worker operation is unsupported.
4. **The database-owner credential is trusted.** Ownership fencing and the revision constraints stop stale normal
   application writes and the unprivileged MCP roles, not the `opspilot_app` owner role.
5. **Physical chunk IDs are not immutable.** Revision identity is logical source content. Citation snapshots stay
   self-verifying.
6. **No independently sealed, unseen evaluation yet.** One author wrote the scenarios, labels and gates, and the
   gates were designed after observing failures on these scenarios.
7. **Raw model planning is unreliable.** Safety policies and human approval enforce the remediation boundary.
8. **Old local development token records** (expired approval tokens written by earlier versions) need
   `opspilot sanitize-secrets --apply`.
9. **Not ready for multi-user or network-exposed production use.** There are shared per-role passphrases, no
   per-user identity, and the MCP servers share one OS user.

Measured results are only in [`docs/evaluation/BASELINE.md`](docs/evaluation/BASELINE.md) (generated by
`make evaluate`, never hand-edited), including the caveats: one author wrote the scenarios and labels, and the
safety gates were designed after observing failures on these scenarios.

## Screenshots (real running app, synthetic data)

| Overview Command Center & Scenarios | Incident Command Center & Human Approval |
|---|---|
| ![Overview Dashboard](docs/images/after/overview-desktop.png) | ![Incident Command Center](docs/images/after/incident-workspace-approval-desktop.png) |
| **Interactive Architecture Explorer** | **Data Sources & Extensibility Catalog** |
| ![Architecture Explorer](docs/images/after/architecture-system-desktop.png) | ![Integrations Catalog](docs/images/after/integrations-demo-desktop.png) |

## Quick start

Prerequisites: macOS on Apple Silicon (tested: M5 Pro, 24 GB), Homebrew, `uv`, Node 24 + pnpm.

```bash
make bootstrap ARGS=--install   # installs missing tools (brew), writes .env with random secrets; stops if models are missing
make models                     # explicit opt-in: downloads LLM_MODEL + EMBEDDING_MODEL (~7.3 GB) and probes them
make bootstrap                  # starts Postgres, migrates, creates MCP DB roles, ingests the knowledge base, seeds INC-001
make doctor                     # verify everything (models, embedding dim, pgvector, migrations, ports)
make dev                        # API on :8000, web on :3000
```

Open <http://127.0.0.1:3000> and sign in with the operator passphrase (`OPSPILOT_WEB_OPERATOR_PASSPHRASE` in `.env`):
- **Command Center (`/`)**: System overview, synthetic scenario launches, and active incident metrics.
- **Incident Workspace (`/investigations/[id]`)**: Step-by-step progress, root-cause hypotheses, safety gate decisions, approval actions, and recovery verification.
- **Architecture Explorer (`/architecture`)**: Interactive ReactFlow diagrams for System Topology, Agent Workflow, Hybrid RAG, and Evidence Extensibility.
- **Integrations Catalog (`/integrations`)**: Evidence source guide across Demo, Offline/File, and Connected Observability modes.
- **Developer Guide (`/guide`)**: Interactive local setup, operational verification steps, and architectural concepts.
- **Safety Center (`/safety`)**: In-depth specification of the Seven Invariant Safety Gates and human-in-the-loop policies.

Headless: `uv run opspilot investigate --scenario INC-003 --decision approve`. Walkthroughs for every scenario:
[docs/DEMO.md](docs/DEMO.md).

## Commands

| Command | Purpose |
|---|---|
| `make bootstrap` / `make doctor` | provision / diagnose (idempotent, read-only respectively); bootstrap never downloads models unless `ARGS=--pull-models` |
| `make models` | explicit opt-in download of `LLM_MODEL` and `EMBEDDING_MODEL`, then a compatibility probe |
| `make infra-up` / `make infra-down` | start / stop containers (volumes are never deleted) |
| `make migrate` / `make ingest` | schema + checkpointer setup / incremental knowledge ingestion |
| `make dev` / `make stop` | start / stop API + web |
| `make test` | deterministic Python + web unit tests (no model needed) |
| `make test-live` / `make e2e` | live-model tests / Playwright UI tests on an isolated stack (API :8100 on `opspilot_test`, web :3100; safe beside `make dev`) |
| `make db-roles` | create/refresh least-privilege DB roles for the MCP servers |
| `make uploads-purge` / `uv run opspilot uploads list` | delete uploaded and connected incidents older than `UPLOAD_RETENTION_DAYS` (files or snapshots, records, checkpoints; stop the API first) / list uploads |
| `make telemetry-up` / `make telemetry-down` | start / remove the local Loki + Prometheus test setup with synthetic telemetry (127.0.0.1, tmpfs, no volumes) |
| `make lint` | ruff, mypy --strict, import-linter, ESLint, tsc |
| `make evaluate` | retrieval (development + held-out) and agent evaluation over all scenarios → `docs/evaluation/BASELINE.md` |

## Repository layout

```
apps/api/opspilot_api        FastAPI app, application services, runner, CLI (composition root)
apps/web                     Next.js 16 operator UI (+ BFF proxy route)
packages/shared              config, logging, tracing, domain contracts, ORM, LLM ports + Ollama adapters
packages/agents              LangGraph graph, nodes, deterministic analysis, prompts (ports only)
packages/rag                 parsing, chunking, ingestion, hybrid retrieval, reranker seam
packages/mcp                 MCP read/action servers and the ToolGateway client
packages/evaluation          retrieval + agent evaluation harness
services/simulator           deterministic synthetic environment + sandbox actions
infra/compose, infra/db      Compose file, DB init, Alembic migrations
datasets/synthetic           knowledge corpus (synthetic)
datasets/evaluation          labelled questions, ground truth (agents never see it), results
docs/                        architecture, ADRs, setup, development, evaluation, progress, decisions
```

Layering is enforced by import-linter: agents depend only on ports; nothing imports the evaluation harness.

## Documentation

- Connected observability: [connectors, configuration, security and the provider contract](docs/integrations/CONNECTORS.md)
- Architecture: [system design](docs/architecture/SYSTEM_DESIGN.md) · [components](docs/architecture/COMPONENT_DIAGRAM.md) ·
  [agent workflows](docs/architecture/AGENT_WORKFLOWS.md) · [RAG](docs/architecture/RAG_PIPELINE.md) ·
  [data model](docs/architecture/DATA_MODEL.md) · [API](docs/architecture/API_CONTRACTS.md) ·
  [security](docs/architecture/SECURITY.md) · [deployment](docs/architecture/DEPLOYMENT.md)
- Decisions: [ADRs](docs/adr/) · [decision log](docs/DECISIONS.md)
- Setup: [environment audit](docs/setup/ENVIRONMENT_AUDIT.md) · [development guide](docs/development/DEVELOPMENT.md)
- Status: [progress](docs/PROGRESS.md) · [evaluation baseline](docs/evaluation/BASELINE.md) ·
  [v0.4 model comparison](docs/evaluation/MODEL_COMPARISON_V0.4.md)
- Release: [v0.4.0 release notes](docs/releases/V0.4.0_NOTES.md) · [v0.3.0 release notes](docs/releases/V0.3.0_NOTES.md) · [v0.2.1 release notes](docs/releases/V0.2.1_NOTES.md)
- Audit and hardening: [Codex audit of v0.2.0](docs/audits/CODEX_AUDIT_9ec857c.md) · remediation records
  [C0](docs/audits/PHASE_C0_REMEDIATION.md) · [C0-F](docs/audits/PHASE_C0_F_REMEDIATION.md) ·
  [C0-G](docs/audits/PHASE_C0_G_REMEDIATION.md) · [C0-H](docs/audits/PHASE_C0_H_REMEDIATION.md) ·
  [final independent verification](docs/audits/PHASE_C0_H_INDEPENDENT_VERIFICATION.md)
- Licensing and data provenance: [THIRD_PARTY.md](docs/THIRD_PARTY.md)

## License

Apache-2.0 (see [LICENSE](LICENSE)). All data in this repository is synthetic.
