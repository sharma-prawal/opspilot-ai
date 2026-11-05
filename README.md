# OpsPilot AI

**Local-first, agentic incident investigation.** OpsPilot correlates telemetry, change history,
service dependencies and operational knowledge to produce evidence-cited root-cause hypotheses,
proposes a remediation from a fixed catalogue, **waits for a human to approve it**, executes it in
a sandbox, verifies recovery and writes an RCA report.

Everything runs on one laptop: open-weight models via native Ollama, one PostgreSQL (with
pgvector), no paid APIs, no cloud services, no production access.

> **Status: v0.2.1, experimental, local-first.** Remediation acts only on a deterministic simulator. Run one API
> worker per database. Not intended for multi-user or network-exposed use. See [Limitations](#limitations).

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
| PostgreSQL 17 + pgvector 0.8.7 in Colima, Alembic migrations (0001–0008), LangGraph Postgres checkpoints | ✅ |
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

**Planned** (see [ROADMAP](docs/ROADMAP.md)): an independently sealed unseen scenario set to test the gates out of
sample, planner robustness, per-server OS isolation for MCP, INC-004/005, OIDC operator identity, SSE.

## Limitations

v0.2.1 received a **conditional** sign-off from the final independent verification
([report](docs/audits/PHASE_C0_H_INDEPENDENT_VERIFICATION.md)). These limits apply:

1. **Experimental, local-first only.** One machine, local models, services bound to `127.0.0.1`.
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

| INC-003: step 1 of a 4-step plan awaiting approval | INC-003: all steps executed, recovery verified |
|---|---|
| ![INC-003 approval](docs/images/inc003-approval.png) | ![INC-003 mitigated](docs/images/inc003-mitigated.png) |
| **NEG-002: wrong top hypothesis, rollback blocked, escalated** | **Overview** |
| ![NEG-002 escalated](docs/images/neg002-escalated.png) | ![Overview](docs/images/overview.png) |

## Quick start

Prerequisites: macOS on Apple Silicon (tested: M5 Pro, 24 GB), Homebrew, `uv`, Node 24 + pnpm.

```bash
make bootstrap ARGS=--install   # installs missing tools (brew), pulls models, .env with random secrets,
                                # starts Postgres, migrates, creates MCP DB roles, ingests the knowledge base, seeds INC-001
make doctor                     # verify everything (models, embedding dim, pgvector, migrations, ports)
make dev                        # API on :8000, web on :3000
```

Open <http://127.0.0.1:3000> and sign in with the operator passphrase (`OPSPILOT_WEB_OPERATOR_PASSPHRASE` in `.env`) → **Incidents** → pick a scenario → **Simulate** → **Start investigation** → review
the hypotheses, evidence and plan → approve or reject each step → watch verification, the outcome and the RCA report.

Headless: `uv run opspilot investigate --scenario INC-003 --decision approve`. Walkthroughs for every scenario:
[docs/DEMO.md](docs/DEMO.md).

## Commands

| Command | Purpose |
|---|---|
| `make bootstrap` / `make doctor` | provision / diagnose (idempotent, read-only respectively) |
| `make infra-up` / `make infra-down` | start / stop containers (volumes are never deleted) |
| `make migrate` / `make ingest` | schema + checkpointer setup / incremental knowledge ingestion |
| `make dev` / `make stop` | start / stop API + web |
| `make test` | deterministic Python + web unit tests (no model needed) |
| `make test-live` / `make e2e` | live-model tests / Playwright UI tests on an isolated stack (API :8100 on `opspilot_test`, web :3100; safe beside `make dev`) |
| `make db-roles` | create/refresh least-privilege DB roles for the MCP servers |
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

- Architecture: [system design](docs/architecture/SYSTEM_DESIGN.md) · [components](docs/architecture/COMPONENT_DIAGRAM.md) ·
  [agent workflows](docs/architecture/AGENT_WORKFLOWS.md) · [RAG](docs/architecture/RAG_PIPELINE.md) ·
  [data model](docs/architecture/DATA_MODEL.md) · [API](docs/architecture/API_CONTRACTS.md) ·
  [security](docs/architecture/SECURITY.md) · [deployment](docs/architecture/DEPLOYMENT.md)
- Decisions: [ADRs](docs/adr/) · [decision log](docs/DECISIONS.md)
- Setup: [environment audit](docs/setup/ENVIRONMENT_AUDIT.md) · [development guide](docs/development/DEVELOPMENT.md)
- Status: [progress](docs/PROGRESS.md) · [evaluation baseline](docs/evaluation/BASELINE.md)
- Release: [v0.2.1 release notes](docs/releases/V0.2.1_NOTES.md)
- Audit and hardening: [Codex audit of v0.2.0](docs/audits/CODEX_AUDIT_9ec857c.md) · remediation records
  [C0](docs/audits/PHASE_C0_REMEDIATION.md) · [C0-F](docs/audits/PHASE_C0_F_REMEDIATION.md) ·
  [C0-G](docs/audits/PHASE_C0_G_REMEDIATION.md) · [C0-H](docs/audits/PHASE_C0_H_REMEDIATION.md) ·
  [final independent verification](docs/audits/PHASE_C0_H_INDEPENDENT_VERIFICATION.md)
- Licensing and data provenance: [THIRD_PARTY.md](docs/THIRD_PARTY.md)

## License

Apache-2.0 (see [LICENSE](LICENSE)). All data in this repository is synthetic.
