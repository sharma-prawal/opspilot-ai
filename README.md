# OpsPilot AI

**Local-first, agentic incident investigation.** OpsPilot correlates telemetry, change history,
service dependencies and operational knowledge to produce evidence-cited root-cause hypotheses,
proposes a remediation from a fixed catalogue, **waits for a human to approve it**, executes it in
a sandbox, verifies recovery and writes an RCA report.

Everything runs on one laptop: open-weight models via native Ollama, one PostgreSQL (with
pgvector), no paid APIs, no cloud services, no production access.

```
Alert ─► LangGraph investigation ──► MCP tools ──► simulated payment platform
            │  supervisor plan            (logs, metrics, deploys, deps, health)
            │  telemetry / dependencies / changes / knowledge (hybrid RAG)
            │  RCA (Qwen3 8B, schema-constrained, citations validated)
            ▼
         proposal ─► interrupt ─► operator approves (signed, hash-bound) ─► sandbox action ─► verify ─► report
```

## What is implemented (and verified)

| Area | State |
|---|---|
| Native Ollama (`qwen3:8b`, `qwen3-embedding:0.6b`), embedding dim verified = 1024 | ✅ |
| PostgreSQL 17 + pgvector 0.8.7 in Colima, Alembic migrations, LangGraph Postgres checkpoints | ✅ |
| Incremental RAG ingestion (hashing, versioning, dedup, heading-aware chunking) | ✅ |
| Hybrid retrieval (pgvector HNSW + full-text, RRF) with traces and a measured benchmark | ✅ |
| Deterministic simulator — INC-001 (schema-migration regression) incl. red herrings and a prompt-injection log line | ✅ (INC-002…005 planned) |
| Two MCP servers (read / action) over stdio, typed + bounded tool contracts | ✅ |
| LangGraph workflow: supervisor plan, evidence-driven routing, bounded follow-ups, RCA, HITL interrupt, execute, verify, report | ✅ |
| Backend-enforced approvals: operator token, params-hash binding, CAS transitions, HMAC token re-verified by the executor, idempotent execution | ✅ |
| Workflow survives API restart (verified over HTTP and in tests) | ✅ |
| FastAPI (26 endpoints, OpenAPI), Next.js 16 operator UI via same-origin BFF | ✅ |
| Tests: 72 deterministic + 3 live-model + Playwright e2e; ruff, mypy `--strict`, import-linter | ✅ |

Measured results live in [`docs/evaluation/BASELINE.md`](docs/evaluation/BASELINE.md) (generated, not hand-written).
At the time of writing: INC-001 root cause, category and remediation correct in 3/3 real-model trials,
0 fabricated citations, 0 unauthorized executions, injected instruction not followed, ~25 s to the
approval pause. Hybrid retrieval did **not** beat vector-only on nDCG@10 for this small corpus — see the
baseline for the numbers and caveats.

## Quick start

Prerequisites: macOS on Apple Silicon (tested: M5 Pro, 24 GB), Homebrew, `uv`, Node 24 + pnpm.

```bash
make bootstrap ARGS=--install   # installs missing tools (brew), pulls models, .env with random secrets,
                                # starts Postgres, migrates, ingests the knowledge base, seeds INC-001
make doctor                     # verify everything (models, embedding dim, pgvector, migrations, ports)
make dev                        # API on :8000, web on :3000
```

Open <http://127.0.0.1:3000> → **Incidents** → open the incident → **Start investigation** → review the
ranked hypotheses and evidence → **Approve & execute in sandbox** → watch verification and the RCA report.

Headless alternative: `make investigate` runs the same flow in-process and prints the report.

## Commands

| Command | Purpose |
|---|---|
| `make bootstrap` / `make doctor` | provision / diagnose (idempotent, read-only respectively) |
| `make infra-up` / `make infra-down` | start / stop containers (volumes are never deleted) |
| `make migrate` / `make ingest` | schema + checkpointer setup / incremental knowledge ingestion |
| `make dev` / `make stop` | start / stop API + web |
| `make test` | deterministic Python + web unit tests (no model needed) |
| `make test-live` / `make e2e` | live-model tests / Playwright UI test against the running stack |
| `make lint` | ruff, mypy --strict, import-linter, ESLint, tsc |
| `make evaluate` | retrieval benchmark + agent evaluation → `docs/evaluation/BASELINE.md` |

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

- Architecture: [system design](docs/architecture/SYSTEM_DESIGN.md) · [components](docs/architecture/COMPONENT_DIAGRAM.md) ·
  [agent workflows](docs/architecture/AGENT_WORKFLOWS.md) · [RAG](docs/architecture/RAG_PIPELINE.md) ·
  [data model](docs/architecture/DATA_MODEL.md) · [API](docs/architecture/API_CONTRACTS.md) ·
  [security](docs/architecture/SECURITY.md) · [deployment](docs/architecture/DEPLOYMENT.md)
- Decisions: [ADRs](docs/adr/) · [decision log](docs/DECISIONS.md)
- Setup: [environment audit](docs/setup/ENVIRONMENT_AUDIT.md) · [development guide](docs/development/DEVELOPMENT.md)
- Status: [progress](docs/PROGRESS.md) · [evaluation baseline](docs/evaluation/BASELINE.md)
- Licensing and data provenance: [THIRD_PARTY.md](docs/THIRD_PARTY.md)

## License

Apache-2.0 (see [LICENSE](LICENSE)). All data in this repository is synthetic.
