# Progress

Resumable record of the build. Update at the end of every working session.

## Status — 2026-11-04, end of session 1

**Current milestone:** Priority A complete and verified. Partially into Priority B (HITL + sandbox
remediation, dashboard, retrieval benchmark, agent evaluation, security tests and CI are done for INC-001).

### Acceptance criteria (Phase A)

| Criterion | Status | Evidence |
|---|---|---|
| Existing directory preserved | ✅ | only `.claude/settings.local.json` existed; untouched (git-ignored) |
| Git repository initialised safely | ✅ | `git init -b main`; **nothing committed yet** (awaiting owner) |
| Architecture documentation | ✅ | `docs/architecture/*` (8 docs), `docs/adr/ADR-001…007` |
| Ollama available locally | ✅ | 0.40.14, brew service, 127.0.0.1 only |
| Qwen3 8B downloaded and responds | ✅ | structured JSON, ~44 tok/s, 100% GPU |
| Embedding model downloaded and responds | ✅ | `qwen3-embedding:0.6b` |
| Embedding dimensions verified | ✅ | 1024 from live API; checked by `make doctor` and a live test |
| PostgreSQL container healthy | ✅ | `pgvector/pgvector:0.8.7-pg17`, 127.0.0.1:5433 |
| pgvector enabled | ✅ | 0.8.7 in `opspilot` and `opspilot_test` |
| Migrations succeed | ✅ | Alembic `0001` up/down/up round-trip; `alembic check` clean |
| FastAPI starts | ✅ | `/health/ready` 200 with all checks |
| Next.js starts | ✅ | dev + production build succeed |
| Synthetic documents ingested | ✅ | 19 docs + 1 duplicate detected; re-ingest fully incremental |
| Hybrid search returns relevant sources | ✅ | integration tests + benchmark (Recall@5 0.967) |
| Incident can be created | ✅ | `POST /incidents/simulate`, UI button, CLI |
| Investigation workflow executes | ✅ | CLI, HTTP, UI, eval runs |
| ≥1 MCP tool call works | ✅ | 15 calls per run over stdio; protocol tests |
| Investigation evidence persisted | ✅ | `ops.evidence`, `ops.tool_invocations`, `ops.workflow_events` |
| Workflow state persists through restart | ✅ | killed API at approval pause, restarted, approved → completed (HTTP); test `test_checkpoint_resume.py` |
| RCA references actual retrieved evidence | ✅ | citations validated against evidence; 0 violations in eval; API test asserts cited ⊆ persisted |
| Backend tests run | ✅ | 72 passed, 3 live skipped by default (3/3 pass with `--run-live`) |
| Local dev commands documented | ✅ | README, `make help`, `docs/development/DEVELOPMENT.md` |
| No paid API key required | ✅ | none configured anywhere |
| No unrelated data destroyed | ✅ | see "Side effects" below |

### Verified results (this session)

- `make doctor`: all checks pass. `make bootstrap`: idempotent re-run (no changes).
- `make lint`: ruff clean, mypy `--strict` clean (76 files), import-linter 4/4 contracts kept, ESLint + tsc clean.
- `make test`: 72 Python tests + 6 web unit tests pass. `make test-live`: 3/3. `make e2e`: 1/1 (≈31 s, real model).
- `make evaluate` (see `docs/evaluation/BASELINE.md`): INC-001 3/3 trials — root cause, category, remediation correct;
  0 citation violations; 0 unauthorized executions; 0 executions after reject; injection not followed; recovery verified;
  mean 25 s to approval pause. Retrieval: vector nDCG@10 0.932, hybrid 0.901, keyword 0.820.

### Side effects on the machine

- Installed via Homebrew: ollama, colima, docker (CLI), docker-compose. Homebrew's automatic cleanup removed old
  download caches and an outdated `xz` keg during that install (not requested; scripts now set `HOMEBREW_NO_INSTALL_CLEANUP=1`).
- Docker context switched to `colima` by `colima start` (Docker Desktop context unchanged; `docker context use desktop-linux` to revert).
- Models pulled: `qwen3:8b`, `qwen3-embedding:0.6b` (5.5 GB). No other models.
- Disk: 223 → 204 GiB free. Project footprint ≈ 8.7 GB.

### Commands executed (key)

`brew install ollama colima docker docker-compose` · `brew services start ollama` · `ollama pull qwen3:8b` ·
`ollama pull qwen3-embedding:0.6b` · `colima start --cpus 4 --memory 4 --disk 30 --vm-type vz` · `git init -b main` ·
`uv sync` · `pnpm install` · `scripts/infra-up.sh` · `alembic upgrade head` · `opspilot migrate|ingest|investigate` ·
`opspilot-eval retrieval|agent` · `pytest` · `playwright test`.

### Known failures / limitations

- Only INC-001 is implemented; INC-002…005 are designed (runbooks and postmortems exist in the corpus) but not simulated.
- CI workflow (`.github/workflows/ci.yml`) is written but has **not run** (no remote yet).
- Hybrid retrieval does not beat vector-only on the current benchmark; labels are self-authored (bias).
- Agent evaluation uses temperature 0 → near-deterministic trials; only one scenario, so rates are not generalisable.
- Operator identity is a shared token + free-text name; no per-user auth.
- MCP stdio sessions are opened once per API process; if a child dies, readiness reports it but there is no automatic reconnect.
- `next dev` overlay (Next.js dev indicator) can overlap UI in screenshots; not present in production builds.

## Next implementation tasks (in order)

1. Commit the initial tree (owner decision) and push to trigger CI; fix anything CI surfaces.
2. INC-002 (connection-pool exhaustion) and INC-003 (invalid payloads): scenarios, ground truth, `scale_connection_pool`
   and `pause_consumer` sandbox implementations, eval trials. Then INC-004/005.
3. Add negative scenarios (no change correlates; red-herring-only) to measure false-positive remediation proposals.
4. MCP session supervision (reconnect on child exit) and per-tool rate limits.
5. Retrieval: held-out question set, weighted RRF / cross-encoder reranker behind the `Reranker` protocol; compare.
6. SSE stream for workflow events; OIDC operator identity; audit-log viewer in the UI.
7. Optional Ragas faithfulness metrics using the local model as judge (documented as model-graded).

## Files and directories created

See `README.md` → Repository layout. Key entry points: `apps/api/opspilot_api/main.py`, `runtime.py`,
`services/investigations.py`; `packages/agents/opspilot_agents/graph.py`, `nodes.py`; `packages/mcp/opspilot_mcp/*_server.py`;
`packages/rag/opspilot_rag/ingest.py`, `retrieval.py`; `services/simulator/opspilot_simulator/scenarios/inc001_schema_migration.py`;
`apps/web/app/investigations/[id]/view.tsx`.

## Status — 2026-11-04, end of Phase B

**Milestones:** B0 ✅ · B1 ✅ · B2 ✅ · B3 ✅ · B4 ✅ · B5 ✅ (see per-milestone notes below).

- **B0:** release audit (no secrets, personal paths, dumps or client data; local machine inventory redacted);
  SHA-pinned actions, read-only token, no Ollama/paid API in CI; public repo `sharma-prawal/opspilot-ai`; CI run
  41793925142 passed; v0.1.0 released. Audit found and fixed: hybrid search failed entirely without embeddings.
- **B1:** INC-002 (pool exhaustion; capacity-bound sandbox; misleading traffic spike + superseded runbook) and INC-003
  (structured queue records, retries, DLQ, poison-head stalls, quarantine that preserves records, safe resume).
  New read tools: `list_service_metrics`, `get_service_config`, `get_datastore_status`, `inspect_queue`.
  New actions: `scale_connection_pool`, `pause_consumer`, `quarantine_messages`, `resume_consumer`, each action-bound
  and idempotent. Multi-step plans, approved step by step.
- **B2:** NEG-001 (false positive), NEG-002 (external dependency + unrelated deploy), NEG-003 (ambiguous changes +
  log-backend outage); poisoned wiki page and superseded runbook in the corpus; approval-request expiry + sweeper;
  explicit outcomes with escalation; evidence-based safety gates (D25-D28).
- **B3:** held-out retrieval set (5-gram leakage check: none); ground truth for all six scenarios; incident-level
  scoring; 13 live runs; traces retained in `datasets/evaluation/results/traces_latest/`. No reranker: failure
  analysis attributes the held-out misses to document lifecycle, not semantic ranking.
- **B4:** supervised MCP sessions with bounded reconnection; tests for killed MCP child, bounded reconnect, tool
  timeout, duplicate resume, concurrent duplicate approvals (exactly one execution), expired approvals, verification
  failure. API restart and checkpoint resume covered since Phase A.
- **B5:** UI outcome banner / plan steps / blocked proposals / scenario picker; README, architecture, security,
  DEMO.md, ROADMAP.md, decision log D24-D32; screenshots from the live app in `docs/images/`.

**Verified:** `make lint` clean; 101 deterministic tests + 3 live tests pass; Playwright e2e passes (≈33 s);
evaluation results in `docs/evaluation/BASELINE.md`.

**Known limitations:** see `docs/architecture/SECURITY.md` (known gaps) and BASELINE caveats. Most important:
the safety gates were designed after observing failures on these scenarios, so they need an unseen scenario set;
NEG-002 root cause is ranked second by the model; retrieval ignores document status; shared operator token.

**Next (Phase C):** see `docs/ROADMAP.md`.

## Earlier note — Phase B mid-session checkpoint (superseded by the status above)

Done:
- **B0:** release audit (no secrets, personal paths or client data; machine inventory redacted). CI actions are SHA-pinned with a read-only token. Public repo `sharma-prawal/opspilot-ai`; first CI run passed; **v0.1.0** tagged and released. The audit also found and fixed a real defect: hybrid retrieval now degrades to keyword-only when embeddings are down (migration 0002).
- **B1/B2 (code):** INC-002, INC-003, NEG-001/002/003 implemented; 4 new MCP read tools; multi-step approved plans; evidence-based safety gates; outcomes with escalation; approval-request expiry and a sweeper (migration 0003). Commits `9f1ee66`, `a20e8e2`, `aa184ea`.
- **Tests:** 89 deterministic tests pass; ruff, mypy --strict and import-linter are clean.
- **Live single-run check (qwen3:8b, one run each, not an evaluation):** INC-001/002/003 → mitigated (the INC-002 unsafe pool increase was blocked); NEG-001 → no_action_required; NEG-002/NEG-003 → proposal_blocked, with no action executed.

Not done (next session, in order):
1. Push-triggered CI for these commits: check the result (`gh run list`).
2. Unit/API tests for expiry/sweeper, the BackendUnavailable tool fault and INC-002/003 simulator effects; a doc update for D24–D30 (gates, plan loop, deterministic impact, onset fix).
3. B3: held-out retrieval set, multi-scenario agent eval with ground truth files (INC-002/003, NEG-*), BASELINE regeneration.
4. B4: MCP session supervision/reconnect plus resilience tests (MCP kill, duplicate resume/approval, expiry).
5. B5: UI outcome/plan display, README/architecture/security docs, screenshots, roadmap.
