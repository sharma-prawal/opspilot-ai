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

## Status — 2026-11-04, end of Phase C0 (hardening) — CONDITIONAL

**Branch:** `hardening/phase-c0` (from `9ec857c` = v0.2.0); not merged, pushed, tagged or released.
**Scope:** remediation of the Codex audit (`docs/audits/CODEX_AUDIT_9ec857c.md`, preserved verbatim). Per-finding
evidence and the verification matrix: `docs/audits/PHASE_C0_REMEDIATION.md`. Draft release notes:
`docs/releases/V0.2.1_NOTES.md`.

**Milestones:** C0-A (H1–H4) ✅ · C0-B (E–H) ✅ · C0-C (I–M) ✅ · C0-D (N–P) ✅ · C0-E (regression, evaluation,
docs) ✅ with one open measured regression.

**Verified by execution:**
- `make lint` clean;
- `make test`: 180 passed, 3 live skipped, and 30 web tests;
- `make test-live`: 3 passed;
- `make e2e`: 4 passed, 3 screenshot specs skipped, with dev-DB row counts unchanged; pointing it at the dev
  ports aborts before any test;
- `make doctor` passes;
- `make evaluate` (`TRIALS=2`, 13 runs, `cc275d7`) — results in `docs/evaluation/BASELINE.md`, frozen under
  `datasets/evaluation/history/phase-c0-cc275d7/`:
  - outcome accuracy 12/13;
  - 0 unsafe, forbidden or unauthorized actions executed;
  - citation validity 1.0;
- live smoke through the BFF on the restarted dev stack: sign-in, CSRF, investigation, approval, execution,
  verified recovery, RCA, and no credentials in 31 responses.

**Open (see the remediation record):**
1. **INC-002 regression.**
   - Official run 1/2 mitigated; supplementary run 1/5; Phase B 2/2.
   - A controlled ablation (Phase B ranking): 5/5.
   - Cause: the lifecycle-ranking fix (I) changes the model's context. The failure is safe — the gates blocked
     everything and the incident escalated.
   - Not tuned away, by policy.
2. **58 legacy dev-DB rows with expired approval tokens.** They need the owner's authorization for
   `sanitize-secrets --apply`; a backup and rollback procedure is documented.
3. **MCP OS-user separation** is not done (DB roles and environment are).

**Machine state changes this phase (additive only):**
- migrations 0004 and 0005 on `opspilot` and `opspilot_test`;
- roles `opspilot_mcp_read` and `opspilot_mcp_actions`, with grants;
- `.env` gained the web session/passphrase and MCP role passwords;
- dev API and web restarted on the C0 code.

Nothing was deleted.

**Next:** independent Codex verification of the branch. Then, only with authorization: merge, tag `v0.2.1`, and
publish. Phase C1 is not started.

## Status — 2026-11-05, end of Phase C0-F (independent audit remediation)

**Input:** independent Codex verification of `29d019c` (verdict FAIL), preserved verbatim in `docs/audits/`
(`PHASE_C0_INDEPENDENT_*`). Record: `docs/audits/PHASE_C0_F_REMEDIATION.md`. Decisions D49–D54.

**Commits:** `c33d28f` F1 recovery scope/health/ranges · `9ada7d7` F2 atomic admission, durable dispatch, lease
fencing · `1d67597` F3 current-runbook section coverage · `7ead2af` F4 test-workflow ownership · `62a9e21` F5 INC-003
specification check, occurrence/order-aware scoring, separated metrics · docs/results commit.

**Verified by execution (code at `62a9e21`):** `make doctor` ✓; `make lint` clean; `make test` 229 passed + 3 live
skipped, web 30; integration+security stable in 4 orders (91 passed each); `make test-live` 3 passed; `make e2e`
4 passed / 3 skipped with dev-DB counts unchanged; audit reproducer: all four defects gone.

**Evaluation** (`history/phase-c0f-62a9e21/`): official 13/13 correct outcomes, 0 unsafe/forbidden/unauthorised
executions; INC-002 12/12 mitigated (2 official + 10 supplementary; C0 was 2/7); negatives 15/15 correct with no
execution, but the raw model still proposes a rollback in every negative run (as in Phase B and C0). Model-plan
acceptability (before gates) 3/12 in the official run.

**Open:** no sealed unseen scenario set (novel cases not evaluated); multi-worker deployment unsupported
(per-process admission, unfenced checkpointer writes); INC-003 key verified by a same-author specification, so an
independent human review is recommended; 58 expired legacy tokens await the owner's `sanitize-secrets --apply`
decision; MCP OS-user separation.

**Machine state changes this phase:** test DB: 755 stale unfinished test workflows retired (terminal, nothing
deleted); dev API/web restarted on the new code; evaluation rows added to the dev DB (additive).

**Next:** independent re-verification of the branch. Merge, tag `v0.2.1` and publish only with authorisation.
Phase C1 is not started.

## Status — 2026-11-05, end of Phase C0-H (third independent audit remediation)

**Input:** third independent Codex verification of `b2a76d5` (FAIL: N1 start-up ownership loss, N2 revision reuse),
preserved verbatim (`PHASE_C0_G_INDEPENDENT_*`, committed `2116ef1`). Record: `docs/audits/PHASE_C0_H_REMEDIATION.md`.
Decisions D60–D63.

**Commits:** `1e28076` H1 immutable serialized document revisions (migration 0007) · `5729dbb` H2 runtime lifecycle +
epoch-based database fencing of checkpoints, runner writes and remediation claims (migration 0008) · `1635170` H3
concurrency/fault-injection suites · `2116ef1` audit artifacts · docs/results commit.

**Verified by execution:** both new reproducers reproduced on `b2a76d5` and no longer succeed; audit process checks pass;
earlier R1/R2/R3/R5 still corrected. `make lint` clean; `make test` 304 passed + 3 live skipped, web 30; shuffled
integration/security 153 passed in each of 3 orders; `make doctor` ✓ (head 0008); `make test-live` 3; `make e2e` 4 passed /
3 skipped, dev-DB counts unchanged; `make evaluate` 13/13 correct outcomes, 0 unsafe executions, identical quality metrics
to C0-G (`history/phase-c0h-2116ef1/`).

**Open:** as C0-G (no unseen scenario set; multi-worker unsupported; R6 partial plan metric; default residual limits;
58 expired legacy tokens awaiting the owner's decision; MCP OS-user separation; terminal-row growth) plus: old document
revisions are not archived (citation snapshots are the record); unfenced operator API writes from a process in the
instant between ownership loss and exit (CAS-protected, not execution).

**Machine state changes this phase:** migrations 0007 and 0008 applied to the dev and test DBs (additive; dev API
stopped first) and `make db-roles` re-run (fence EXECUTE for the action role); evaluation rows added to the dev DB; dev
API/web restarted on the new code.

**Next:** final independent verification. Merge, tag `v0.2.1` and publish only with authorisation. Phase C1 not started.

## Status — 2026-11-05, v0.2.1 release preparation (Phase C0 closure)

**Input:** final independent Codex verification of `de879a2`. Verdict **CONDITIONAL**: H1/H2 verified closed, no
supported-path release blocker. Two claim qualifications apply: physical chunk IDs are not immutable (revision
identity is logical), and the `opspilot_app` owner credential is trusted. Artifacts are preserved verbatim in
`docs/audits/PHASE_C0_H_INDEPENDENT_*`. Decision D64.

**Release documentation:**
- `docs/releases/V0.2.1_NOTES.md` finalized with the nine disclosed limitations;
- README brought in line with it (capabilities, v0.2.1 numbers, Limitations section);
- the RAG, deployment and security pages scoped to the audit's qualifications;
- ROADMAP: v0.2.1 row and the Phase C1 starting point.

**Verified by execution (code unchanged since `2116ef1`; documentation-only commits since):**
- `make lint` clean;
- `make test`: 304 passed + 3 live skipped, and 30 web tests;
- `make doctor` ✓, migrations at head `0008` on the dev and test DBs;
- secret scan of every commit since `main` and the new audit artifacts: no `.env` value, approval token, key or
  home path found.

The full LLM evaluation was not re-run, because no code changed. The official results are `history/phase-c0h-2116ef1/`.

**Publication plan:** push `hardening/phase-c0`, open a PR to `main`, and wait for CI and the owner's approval.
Then merge with a merge commit, tag `v0.2.1` on the verified `main` commit and publish the GitHub release. The
closure record is added after publication.

## Status — 2026-11-05, end of Phase C0-G (second independent audit remediation)

**Input:** second independent Codex verification of `5079b72` (verdict FAIL), preserved verbatim in `docs/audits/`
(`PHASE_C0_F_INDEPENDENT_*`, committed `2d18d46`). Record: `docs/audits/PHASE_C0_G_REMEDIATION.md`. Decisions D55–D59.

**Commits:** `d6d1901` G1 evidence-complete recovery verification · `7305815` G2 monotonic terminal states (transition
policy, locked CAS, migration 0006 trigger, command revocation) · `37610db` G3 lifecycle-validated retrieval, no obsolete
guidance in investigations · `95e79b9` G4 single execution owner per database (advisory lock, watchdog, launchers pinned
to one worker) · `748c069` G3 fixture cleanup · `2d18d46` audit artifacts · docs/results commit.

**Verified by execution:** all four audit reproducers reproduced the defects on `5079b72` and no longer do (R4 by
real-process validation; the audit's static Uvicorn-config probe is unchanged by design). `make lint` clean; `make test`
283 passed + 3 live skipped, web 30; integration+security stable under shuffle seeds 11/22/137 (132 passed each);
`make doctor` ✓; `make test-live` 3 passed; `make e2e` 4 passed / 3 skipped with dev-DB counts unchanged.

**Evaluation** (`history/phase-c0g-2d18d46/`): official 13/13 correct outcomes; 0 unsafe/forbidden/unauthorised
executions; verified recovery 6/6 under the stricter conditions; model-plan acceptability 3/12, root cause 7/9 (both
unchanged from C0-F); the raw model still proposes a rollback in every negative run; INC-002 still receives the current
runbook's sections.

**Deployment restriction (now enforced):** one execution owner per database. Stop the dev API before `make evaluate`
or the CLI demo; Python tests and E2E cannot run at the same time.

**Open:** no sealed unseen scenario set; multi-worker execution unsupported (C1); raw model-plan metric is partial
pattern conformance (audit R6); residual limits are defaults, not SLOs; 58 expired legacy tokens await the owner's
`sanitize-secrets --apply` decision; MCP OS-user separation; terminal rows/checkpoints accumulate.

**Machine state changes this phase:** migration 0006 applied to the dev and test DBs (additive trigger); dev API/web
stopped for the evaluation and restarted on the new code (now holding the dev DB's owner lock); evaluation rows added to
the dev DB (additive); test DB: audit-reproducer and test rows left terminal, test-owned KB fixtures removed.

**Next:** independent re-verification of the branch. Merge, tag `v0.2.1` and publish only with authorisation.
Phase C1 is not started.

## Status — 2026-11-16, v0.4.0 reasoning and model flexibility (`feature/ai-reasoning-v04`, not pushed)

- **Diagnosis** of the published qwen3:8b traces and a fresh re-run (identical raw plans): system outcomes 13/13 correct
  only because of the gates; raw model plan acceptable 4/13; the decisive evidence was present but ignored. Write-up:
  `docs/evaluation/MODEL_COMPARISON_V0.4.md` §1.
- **Model selection** (D97): `opspilot models [--model] [--probe]`; health/overview expose the active model; UI renders
  configured names; fail-fast on 501/4xx. `qwen3.5:9b` default tag = MLX build without structured output on Ollama
  0.40.14; `qwen3.5:9b-q4_K_M` (GGUF) works.
- **Agent changes** (D98): evidence digest (`synthesis.py`), explicit `decision`, observed-value enums for citations and
  plan identifiers. No gate, uncertainty or approval rule changed.
- **Comparison** (six public scenarios, 1 trial, supplementary `--out` runs in
  `datasets/evaluation/history/v0.4-model-comparison/`; BASELINE.md untouched): qwen3.5:9b-q4_K_M after — system 6/6,
  raw plan 6/6, 0 gate rejections, 3/3 negatives self-handled, repeat identical; qwen3:8b after — system 6/6, raw plan
  1/6, 8 rejections. Recommendation D99 (default left at qwen3:8b pending owner).
- **Verified**: `make lint` clean; `uv run pytest` 317 passed / 3 skipped; web 38 passed; live-model tests 3/3 with both
  models.
- **Open for the owner**: switch the default model? Two pre-existing gate gaps (resume of a running consumer;
  containment admitted when its resolution is rejected) — report §5. `make evaluate` (official baseline) not re-run.
- Models on disk added this session: `qwen3.5:9b-q4_K_M` (6.6 GB) and the unusable MLX `qwen3.5:9b` (7.6 GB, can be
  removed with `ollama rm qwen3.5:9b`).

## Status — 2026-11-16, v0.4.0 safety-gate corrections (`feature/ai-reasoning-v04`, not pushed)

- **Fix A (D100)** resume only for paused consumers; **Fix B (D101)** no step bypasses a rejected resolution or
  unresolved change ambiguity. 9 regression cases in `tests/unit/test_v04_gate_corrections.py`; recorded NEG-002 /
  NEG-003 failure traces replayed through the fixed `propose`: nothing proposed.
- **Prompt/schema (D102)**: evidence-applicable actions only, pause→resume guidance restored, changed-dependency fact.
  Six scenarios: qwen3:8b raw plan 3/6 (was 1/6), qwen3.5:9b-q4_K_M 6/6; both 6/6 system outcomes; NEG-003 executed
  nothing; INC-003 recovered with both. Report §7.
- **Defaults**: `.env.example` → `qwen3.5:9b-q4_K_M` (fallback `qwen3:8b`); models download only via `make models`
  or `bootstrap --pull-models`. This machine's `.env` still says `qwen3:8b` (not edited).
- **Verified**: `make lint` clean; `uv run pytest` 328 passed / 3 skipped; web 38 passed; live-model tests 3/3 with
  qwen3.5:9b-q4_K_M. Not re-run: official `make evaluate`, Playwright e2e.

## Status — 2026-11-17, v0.4.0 release-readiness pass (`feature/ai-reasoning-v04`, not pushed)

- Onboarding aligned: `.env.example` (qwen3.5:9b-q4_K_M, fallback qwen3:8b), bootstrap (no silent download),
  `make models`, `make doctor` (now checks structured output, catches the MLX 501), `opspilot models --probe`,
  README, guide, DEPLOYMENT.md, ADR-001 note, DEMO/CONTRIBUTING.
- UI smoke test on an isolated stack (API :8200 with `LLM_MODEL=qwen3.5:9b-q4_K_M` in the process environment, web
  :3200, throwaway passphrase; `.env` untouched): INC-001 → evidence → RCA (dep-ls-0042, 98%) → UI approval →
  sandbox rollback → recovered 5/5 → mitigated; model shown correctly on overview, runtime panel and investigation.
- Report: "plan acceptable" (answer key) vs "admitted unchanged by gates" now reported separately (qwen3.5 6/6 vs
  5/6); labelled development testing on reused scenarios.
- Checks: lint clean; pytest 328 passed / 3 skipped; web 38 passed; `make build-web` OK.
- Branch: based on published v0.3.0 (`1305d1e` = origin/main), 7 commits ahead, 0 behind, merges cleanly.
  `docs/releases/V0.4.0_NOTES.md` prepared. Not pushed, merged or tagged. `phase-c1` branch untouched.

## Status — 2026-11-18, v0.5.0 bring-your-own incident data (`feature/incident-file-analysis-v05`, not pushed)

- Base: published v0.4.0 (`origin/main` = `e8d5363`). Migration `0009` (incident `evidence_source`, nullable
  `environment_id`, `ops.uploaded_datasets`), applied to the app and test DBs.
- Parsing/normalization: `opspilot_shared/uploads` (.log/.txt text and JSON lines, JSON arrays/objects, OTLP/JSON
  traces, CSV long/wide metrics and events); provenance per record; credential redaction; limits (D104, D106).
- File-backed provider + `EvidenceRouter` (`opspilot_mcp/file_evidence.py`, D103); read-only path through
  propose/approval/execute/API and new outcomes (D105); upload-only agent tweaks (D107); report sections
  "Suggested remediation (not executed)" and "Recommended next investigation steps" with file citations.
- API: upload preview/create, dataset, discard; `opspilot uploads list|purge`, `make uploads-purge`.
- Web: Analyze files page (form, drag-and-drop, validation, preview, samples, examples), Demo vs Uploaded labels,
  dataset card + delete, read-only investigation view, Markdown download, file source on evidence; guide,
  integrations and architecture pages updated. Example files: `apps/web/public/examples/uploads/`
  (`scripts/generate_upload_examples.py`).
- Live browser-to-backend run (API :8010 with the configured `qwen3:8b`, web :3010, throwaway passphrase; `.env`
  untouched): example upload → preview (129 log, 456 metric, 24 span, 3 event records; 1 credential redacted) →
  investigation completed in 32 s → `analysis_complete`, top hypothesis deploy-7731 (payment-service 2.14.0, 90%),
  suggested rollback; the model's two extra restarts were dropped by the gates; nothing executed.
- Not done: Playwright e2e for the upload flow; official `make evaluate` not re-run (simulator path unchanged).

## Status — 2026-11-18, v0.5.0 correctness and release-readiness pass (same branch, not pushed)

- Incident references: durable per-day counter (`ops.incident_reference_counters`, migration `0010`, D108), atomic
  upsert in the incident transaction; tests for concurrent allocation and no reuse after deleting the highest number.
- Privacy: 422 responses no longer echo the request body; parse issues are scrubbed; tests that previews, oversized
  uploads and failed creates do not return a credential from the file; deletion test now also checks evidence, tool
  calls, events, dataset and checkpoints are gone and that an unrelated upload and a simulator incident remain.
  Sanitization instructions added to the upload page, guide, README and release notes.
- Real browser upload: `apps/web/e2e/upload.spec.ts` (Playwright `setInputFiles` from disk, invalid file rejected,
  preview counts and sources, investigation, cited report, Markdown download, deletion with files removed from disk)
  passed on the isolated e2e stack with `E2E_LLM_MODEL=qwen3.5:9b-q4_K_M` (process-level; `.env` untouched): RCA
  24 s, `analysis_complete`, top hypothesis deploy-7731 (model-estimated 100%, uncalibrated), unrelated search-api deploy ranked 10%, suggested
  rollback, nothing executed.
- `docs/releases/V0.5.0_NOTES.md` prepared.
- Release maintenance: simulator Playwright spec updated to the current UI (heading "RCA Postmortem Report", exact
  "mcp read" status, visible scenario select, header "Start investigation" button; assertions unchanged); both
  `investigation.spec.ts` and `upload.spec.ts` pass on the isolated e2e stack with the configured `qwen3:8b`.
  Report and UI label hypothesis confidence as model-estimated and uncalibrated. Migration 0010 verified on a clean
  database and on a v0.4.0-schema database with existing incidents (throwaway databases, dropped afterwards).

## Status — 2026-11-18, v0.6.0 connected observability (`feature/connected-observability-v06`, not pushed)

- Base: published v0.5.0 (`origin/main` = `7677360`). Migration `0011` (`evidence_source='connector'`,
  `ops.uploaded_datasets.queries`), applied to the test DB (downgrade/upgrade round trip checked). The main DB is
  not migrated yet: run `make migrate`. It is additive.
- Connectors (`opspilot_shared/connectors`):
  - `TelemetryConnector` contract, `ReadOnlyHttp` (GET-only allowlisted paths, no redirects, `trust_env=False`,
    timeouts, size cap, secret scrubbing), approved templates (+ `TELEMETRY_TEMPLATES_FILE`);
  - Loki and Prometheus connectors and snapshot collection with `collected` signals (D109–D112).
  - API formats verified against the real `grafana/loki:3.5.0` and `prom/prometheus:v3.5.0`.
- API:
  - `GET /connectors`, `POST /connectors/{id}/test|services`, `POST /incidents/connected/preview` and
    `/incidents/connected`;
  - the dataset endpoint, deletion and purge cover connector incidents.
- Agents:
  - read-only gating covers connector incidents, with a connected prompt note and report sections (D113);
  - the digest says change history is unknown when it could not be read (D115, prompted by the first qwen3.5 run).
- Web:
  - **Connected telemetry** mode on `/incidents/new?source=connected`: connector cards with Test connection and
    template choice, demo incident, service discovery, preview (per-query status, counts, warnings, samples), create
    and start;
  - connector status panel on Integrations (Loki/Prometheus implemented; Datadog, CloudWatch, Azure, tracing,
    CI/CD and custom marked planned);
  - source badge and banners; snapshot card with queries and delete;
  - guide section 12 and architecture nodes.
- Local test setup: `make telemetry-up` / `make telemetry-down` (compose profile `telemetry`, 127.0.0.1, tmpfs, no
  volumes; synthetic incident from `scripts/generate_telemetry.py`) (D114). Docs:
  `docs/integrations/CONNECTORS.md` (config, security, provider contract), README, SECURITY, API_CONTRACTS,
  DATA_MODEL, AGENT_WORKFLOWS; `docs/releases/V0.6.0_NOTES.md` prepared.
- Verified:
  - `make lint` clean;
  - `uv run pytest` 388 passed / 3 skipped, including 33 connector unit tests, 4 graph tests, 5 API tests and 2
    live tests against the local Loki/Prometheus;
  - web 50 passed; `make build-web` OK;
  - Playwright with `E2E_TELEMETRY=1`: auth, simulator INC-001 (approve → verified recovery), upload and connected
    specs all pass.
- Demonstrated investigations (isolated e2e stack, `.env` untouched; models via process-level `E2E_LLM_MODEL`):
  - `qwen3:8b`: RCA 25 s, `analysis_complete`, pool exhaustion 90%, attributed to a slow query (runbook
    pattern), not to the pool-size drop the telemetry shows;
  - `qwen3.5:9b-q4_K_M`: RCA 25 s, pool exhaustion 95% citing the `db_pool_max` drop and timeout logs, an
    unobserved change as hypothesis 2, escalated to the database team;
  - in both, nothing was proposed for approval or executed, search_logs went to `opspilot-connected-telemetry`, and
    the cited Markdown report with the provenance table was downloaded.
- Not done / open:
  - official `make evaluate` not re-run (simulator path unchanged apart from D115, which only fires when change
    tools fail);
  - connectors tested only against local containers with synthetic data;
  - `alembic check` reports the pre-existing `ops.execution_owner` table (migration-managed, no ORM model).

## Status — 2026-11-19, v0.6.0 release-readiness pass (same branch)

- First-time documentation aligned in README, `CONNECTORS.md`, Integrations (setup panel) and the guide (section 12):
  - `make migrate` (0011);
  - `make telemetry-up`;
  - `.env` URLs and credentials;
  - `make stop && make dev`;
  - test → templates → preview → investigate;
  - adapting service labels, metric names and templates;
  - `make telemetry-down`;
  - tested (local Loki/Prometheus 3.5.0 containers) vs not verified (remote and cloud endpoints, auth other than
    bearer or basic).
- Consistency assertions added:
  - the connected report and outcome label confidence as uncalibrated (API test, Playwright);
  - the connector credential appears in none of the dataset, investigation, tool-call, evidence, event or report
    responses.
- Verified:
  - `make lint` clean;
  - pytest 388 passed / 3 skipped; web 50 passed; `make build-web` OK;
  - Playwright with `E2E_TELEMETRY=1`: 6 passed (auth ×3, connected, simulator INC-001 with verified recovery,
    upload).
- Migration 0011 on a full copy of the main database (throwaway database, dropped afterwards): 0010 → 0011
  cleanly, with 277 incidents, 275 investigations, 7,464 evidence rows, 23 documents and the uploaded dataset unchanged.
  The main database itself was not migrated (it is still at 0010); run `make migrate`.

## Status — 2026-11-19, v0.7.0 Incident Forensics Lab Visual Identity Redesign

- **Redesign Implementation (Concept A — Incident Forensics Lab):**
  - Replaced generic AI SaaS dashboard styling with an archival, editorial scientific investigation workspace (warm ivory `#FBFBF8`, serif headings, crisp mono metrics, stamped exhibits).
  - Implemented synchronized horizontal incident time ribbon with horizontal scrolling and right padding preventing event clipping.
  - Interactive causal graph: selecting hypotheses highlights connected supporting/contradicting evidence; clicking evidence jumps to citations.
  - Responsive layout verified across desktop (1440px) and mobile (390px).
- **Truth-in-UI Corrections:**
  - Clear presentation-layer distinction between external telemetry status (`External: {status} (unverified)`), analysis completion (`Analysis complete (read-only)`), and verified recovery.
  - Dynamic runtime model attribution (`qwen3.5:9b-q4_K_M` and `qwen3-embedding:0.6b`) with explicit uncalibrated confidence labeling.
  - INC-002 screenshot fixtures aligned with documented scenario (Safety Gate D25 capacity ceiling blocking connection pool expansion; rollback of `dep-ls-0291` executed and recovery verified).
  - Automated smoke test (`e2e/overview-smoke.spec.ts`) asserting zero error boundaries and verifying 3 operating modes.
- **Verification:**
  - `pnpm lint`, `pnpm typecheck`, `pnpm test` (50 unit tests), `pnpm build` (27 routes).
  - Playwright E2E: `auth.spec.ts` (3/3), `overview-smoke.spec.ts` (1/1), `investigation.spec.ts` (1/1), `upload.spec.ts` (1/1), `connected.spec.ts` (1/1).
  - All 10 screenshots refreshed in `docs/images/redesign/`.

## Status — 2026-11-19, v0.7.0 maintenance (`fix/v0.7.0-maintenance`, not pushed)

- Web process environment (D116): `make dev` / `scripts/start.sh` start `next dev` detached with an allowlisted
  environment from `opspilot_shared.web_env`; backend-only credentials and settings are excluded
  (`tests/security/test_web_process_env.py`).
- Unavailable states: model names show `unavailable` (`…` while loading) and overview counts `—` when the backend
  did not answer, instead of setting names and zeros. Launcher-only startup documented in `apps/web/README.md`
  and `docs/development/DEVELOPMENT.md`.

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


## Status — 2026-11-19, Visual Experience 2 (local review)

- Baseline verified remotely: v0.7.1 published 2026-11-19; `origin/main` at `1ee1b70`,
  CI run 44548721335 passed. Work is isolated on `codex/visual-experience-2` in the
  managed `visual-experience-2` worktree. No push, merge, tag or release.
- Original evidence-convergence identity: three vector concepts, selected symbol,
  light/dark wordmarks, square icon, SVG/PNG exports and favicon. Usage guide:
  `docs/design/BRAND.md`. Implementation direction and before/after comparison:
  `docs/design/VISUAL_EXPERIENCE_2.md`.
- Home: three-source intake, single scenario picker, real runtime status strip,
  recent cases and incident-source distribution; removed hardcoded connector status.
  Roster: search, source/state filters, exact timestamps and linked case titles.
- Workbench: leading conclusion and structured facts, ranked selectable hypotheses,
  source-backed metric summary bars, evidence composition/filtering, observed service
  links, model association map and source chronology. Workflow chronology, reasoning,
  technical context and report are available on demand. Simulator-only approval controls;
  uploads/connected telemetry remain read-only. Keyboard focus follows evidence and
  review-action links across tabs; workspace selection is announced.
- Integrations: capability matrix separates implementation, configuration and tested
  connectivity. Datadog, Azure Monitor and CloudWatch remain planned. Architecture
  selections emphasize adjacent edges; safety uses an approval-boundary sequence;
  guide adds a task walkthrough while keeping all technical sections.
- Verification executed:
  - `make lint`: Ruff, formatting, strict mypy, four import contracts, ESLint and
    TypeScript passed; frontend lint/tests and production build rechecked after fixes.
  - `make test`: 396 Python passed, 3 opt-in live-model tests skipped; 68 web tests passed.
  - Existing Playwright: 7 passed (auth x3, connected, simulator approval/recovery,
    overview and upload). Dedicated `opspilot_test`, ports 3100/8100; a temporary test
    launcher filtered the web environment through the existing `build_web_env` allowlist.
  - `pnpm smoke:mock` (also `pnpm test:visual2`): 15 production-browser checks passed,
    no page errors. Tests cover normal/running/failure, approval, blocked-only,
    verified simulator recovery, both read-only sources, empty/loading/unavailable,
    evidence links, filtering, keyboard focus, downloads and mobile overflow.
  - Actual implementation screenshots in `docs/images/visual-experience-2/`, explicitly
    labeled synthetic. See its `verification.json` and `README.md`.
  - Independent visual reviewer requested two P2 interaction fixes; both implemented
    and browser-verified. Scoped verdict pass: **ship**, both findings resolved.
- No backend/agent/schema/security/startup changes, no credentials or `.env` edited,
  no paid inference, no main-database tests, no services on 3000/8000 stopped.
  `make evaluate` not rerun: inference/workflow behavior is unchanged; no new model
  quality or recovery-rate claims. Private Phase C1 work was not accessed.
- Limits: metric evidence stores summaries rather than historical series, so charts
  compare baseline/extreme/current instead of fabricating trends. Confidence remains
  uncalibrated; graph edges distinguish observed dependency and model association.
  Screenshots use synthetic fixtures, not production telemetry. No operator usability
  study or measured text-reduction percentage is claimed. Light UI is primary; dark
  brand assets are supplied, with no new theme toggle.

## Status — 2026-11-19, Visual Experience 2 final focused UX refinement

- Refined the approved `0a734f3` design on the same `codex/visual-experience-2`
  branch/worktree. Original logo geometry and exports are unchanged.
- Investigation: pending simulator decision controls precede forensic detail; review
  links reveal Analysis and focus the relevant approval button (or review form for
  viewers), waiting for action data if necessary. Navigation never submits approval.
  Parameters/rationale stay visible; plan steps and blocked-proposal reasons expand.
  Metric labels, units and captions are larger; source-linked map nodes are more
  readable, with explicit mobile scrolling guidance and verified keyboard access.
- Integrations: compact implemented-source rows, separate planned adapters, and
  per-provider configuration/test controls. Capability comparison and the original
  complete technical catalog are secondary disclosures. Loki/Prometheus behavior is
  retained; no adapter added. Technical catalog selectors now use keyboard buttons.
- Safety: five-stage boundary retained; seven short summaries expand to all original
  technical criteria. Full authorization/recovery explanations remain available.
- Homepage: reduced intake padding, column gap and selector height within the same
  layout. Existing symbol inspected at native 16/24/32 px on light and dark backgrounds.
- Verification executed:
  - `make lint` passed (Ruff, formatting, strict mypy, four import contracts, ESLint,
    TypeScript); production build passed. Frontend lint/build/tests were rechecked
    after the final small mobile-readability changes.
  - `make test`: 396 Python passed, 3 opt-in live-model tests skipped; 68 web passed.
  - Existing affected Playwright journeys: 7 passed (auth x3, connected telemetry,
    simulator approval/recovery, overview and upload), on `opspilot_test` and isolated
    3100/8100 ports with the existing allowlisted web environment builder.
  - Production synthetic browser suite: 16 checks passed, zero page errors; includes
    desktop/mobile direct approval focus and viewport assertions, mobile keyboard
    evidence-node navigation, connector expansion/testing, secondary comparison,
    keyboard technical selectors and full gate criteria on expansion.
  - Updated requested captures plus mobile integrations and symbol-size board are in
    `docs/images/visual-experience-2/refinement/`. Operational screenshots explicitly
    label synthetic fixtures; the approved initial screenshots are preserved.
- No backend, database schema, adapter, inference, enforcement, credential or `.env`
  changes. Existing running services were not interrupted; only this pass's temporary
  test servers were started/stopped. No agent behavior change or evaluation rerun.
- Local commit only; stop for acceptance review. No push, merge, tag or publication.

## Status — 2026-11-19, v0.8.0 release preparation (authorized)

- User approved `31aea99320e13931a2e8f36baaf3f3e4c1dc9d9a` for publication as v0.8.0.
  Verified `origin/main` = published v0.7.1 (`1ee1b70`), with maintenance commit
  `c1514b2` in its ancestry; v0.8.0 tag and GitHub release were absent.
- Integrated both approved UI commits (`0a734f3`, `31aea99`) with a non-rewriting
  merge on `codex/release-v0.8.0` in the existing isolated worktree. No conflicts.
  Local `main` is checked out in another worktree, which remains untouched; the
  verified integration is advanced normally to remote `main` at publication.
- Application, backend, auth, environment builder and launcher code match the
  approved candidate. Only release documentation was added after integration:
  README status/logo/current screenshots and `docs/releases/V0.8.0_NOTES.md`.
  Screenshots are authentic implementation captures with visible synthetic labels.
- Integrated verification: `make lint` and production build passed; `make test`
  passed (396 Python, 3 opt-in live-model skips; 68 frontend); production browser
  suite passed all 16 checks with zero page errors, including desktop/mobile approval
  focus, source chronology, metric labels, evidence navigation and connector disclosures.
- Affected live Playwright journeys: all 7 passed (authentication x3, connected
  telemetry, simulator approval/recovery, overview and uploaded evidence). The real
  local model ran only through the isolated test stack. Temporary test servers stopped.
- Publication gate: both Python and web jobs on the final main commit must pass
  before creating/pushing an annotated v0.8.0 tag and publishing the GitHub release.
  Publication must verify remote main, the peeled annotated tag and the GitHub release target.
- No feature, connector, agent, safety-policy, schema, model or credential changes;
  no migration/data reset. Existing data/uploads/private Phase C1 files and other
  worktrees are not modified. Tests use only `opspilot_test` and isolated test ports;
  existing runtime on 3000/8000 is preserved. No evaluation rerun: agent behavior unchanged.

## Status — 2026-11-19, v0.9.0 Datadog observability integration (`feature/datadog-v0.9.0`, not pushed)

- Base: published v0.8.0 (`origin/main` = `535dfa2`, maintenance fixes from v0.7.1 included). Isolated worktree
  `../opspilot-ai-datadog`. No migration, schema, model, safety-policy or approval change.
- Connector (`opspilot_shared/connectors/datadog.py`, D119–D124):
  - Datadog logs search, APM trace metrics (timeseries query with formulas) and indexed APM spans (error spans plus
    the other indexed spans of ≤ 10 traces);
  - bounded service discovery (log aggregate, top 50) and a per-product connection test;
  - destination from the documented site allowlist only; loopback-only fixture override;
  - `ReadOnlyHttp.post_json` with a per-connector POST allowlist (4 read-query paths), bounded 429/503 retries, at
    most 2 requests in flight, cursor pagination with page and record ceilings.
- Pipeline: templates name their `signal`; provenance adds `signal`, `site`, `link` and `pages`; snapshots add
  `spans` and `collected.span`. The stored-evidence provider, prompt note, report banner, provenance table and next
  steps name Datadog. Loki/Prometheus note and banner wording is unchanged (tested).
- Web (Visual Experience 2.0 kept):
  - Datadog in the provider cards (templates grouped by signal, per-signal test badges, *synthetic fixture* label,
    fixture demo incident);
  - discovery notes; span counts and a span tab; returned metric series charts (no resampling, gaps as breaks);
  - Log Explorer links; Integrations catalogue, matrix, guide and architecture text updated. BFF allows
    `connectors/datadog/(test|services)`, operator-only.
- Fixture: `scripts/datadog_fixture.py` (`make datadog-fixture`). Documented response shapes; fictional orders-api →
  inventory-service → inventory-db lock-contention incident; partial traces, missing series, null gaps, untagged
  logs, failure modes.
- Verified:
  - `make lint` clean (ruff, mypy `--strict` 110 files, import-linter 4/4, ESLint, tsc);
  - `pytest` 442 passed / 3 skipped (live-model opt-in), including 46 new Datadog tests (39 connector/security,
    3 graph, 4 HTTP API) and the 2 live Loki/Prometheus container tests;
  - web 70 passed; `pnpm build` OK;
  - Playwright with `E2E_DATADOG=1 E2E_TELEMETRY=1`: 9 passed (auth ×3; Loki/Prometheus connected; Datadog error
    states; Datadog journey with the real `qwen3.5:9b-q4_K_M`; simulator INC-001 approve → verified recovery;
    overview; upload);
  - Datadog catalogue/mobile screenshot test and the not-configured path (without the fixture) also pass;
  - screenshots in `docs/images/datadog/`.
- Datadog journey result (one run, development testing, not an evaluation): `analysis_complete`, nothing proposed
  or executed. Top hypothesis "inventory-service is degraded by lock contention on stock_levels in inventory-db,
  causing timeouts that propagate to orders-api", cited. Model limitation observed: a second hypothesis asserted that
  no internal change caused the fault, although change history was marked unknown and the `lifecycle` logs show the
  3.8.0 start. The report still lists change history as a gap. Not addressed: no prompt or model change in this
  milestone.
- Not done / open:
  - **live Datadog verification** (no account configured; procedure in `docs/integrations/DATADOG.md`);
  - Datadog Events/Change Tracking deferred;
  - official `make evaluate` not re-run: simulator path unchanged;
  - draft release notes `docs/releases/V0.9.0_NOTES.md`; not tagged or published.

## Status — 2026-11-20, v0.9.0 Datadog correctness and compatibility pass (same branch, not pushed)

- **Unsupported negative change claims (D125).**
  - Connected investigations collect INFO version, start-up and config lines as change observations.
  - The digest lists them when change history is unknown.
  - `claims.py` flags hypotheses or summaries claiming that no change occurred (annotate only, no gate change).
  - The report adds an *Evidence coverage* table.
  - Real `qwen3.5:9b-q4_K_M` on the fixture:
    - before: hypothesis 2 "No internal deployment or configuration change caused the fault" (85%);
    - after, two E2E runs: hypothesis 1 "inventory-service deployment (version 3.8.0) with
      reservation_lock_mode=table introduced a fault…" (65%), citing the observed lines; no negative change claim
      and no warning.
  - The first after-run also exposed a false positive ("change history unavailable to rule out recent changes");
    it is fixed and covered by a test.
- **Service names (D126).**
  - `.` and `_` are accepted for Datadog; values are escaped per Datadog's documented search syntax and kept
    exactly (web form included).
  - Loki/Prometheus stay slug-only.
  - The fixture adds `billing.worker_v2`.
- **Span templates.** Confirmed operation-independent (test); only APM metric templates use `trace.http.request`.
- **Mobile.** The two demo buttons forced a 418 px intake at 390 px when Loki/Prometheus and the Datadog fixture were
  both configured. The button group now wraps; the test asserts no page-level horizontal scroll.
- **Verified.**
  - `make lint` clean (mypy 111 files);
  - pytest 474 passed / 3 skipped (live-model opt-in);
  - web 71 passed; `pnpm build` OK;
  - Playwright with `E2E_DATADOG=1 E2E_TELEMETRY=1`: 10 passed (auth ×3, Loki/Prometheus, Datadog error states,
    Datadog journey with the real model, Datadog catalogue/mobile, simulator INC-001 with verified recovery,
    overview, upload);
  - the not-configured Datadog path passes without the fixture;
  - screenshots refreshed.
- Still open: live Datadog verification; Datadog events deferred; `make evaluate` not re-run (simulator path
  unchanged: the new evidence and checks apply only to connected snapshots or when change history is unknown).

## Status — 2026-11-20, v0.9.0 release preparation (authorized)

- User approved `d2957762e3e2b26c90e1147c1c19dc2af49f0523` for release as v0.9.0.
  - Verified `origin/main` = published v0.8.0 (`535dfa2`), the latest tag and release.
  - The approved commit is a direct descendant (two commits), with no divergence.
- Integrated on `release/v0.9.0` (cut from `origin/main`) with a non-rewriting merge commit whose tree equals the
  approved commit. Local `main` is checked out in another worktree and stays untouched; remote `main` is advanced
  normally at publication.
- One release-correctness wording fix: the report's *Evidence coverage* row now labels observed version and start-up
  lines as "log indicators of a possible change: not a verified deployment history and not proof of cause" (tested).
  No prompt, model, gate or behaviour change.
- README status, limitations and the final `docs/releases/V0.9.0_NOTES.md`:
  - synthetic-fixture testing only; no real Datadog organization used;
  - change events deferred;
  - partial span visibility and operation-specific APM metrics;
  - read-only;
  - connected-source reports include observed change indicators and evidence coverage.
- Publication gate: the Python and web CI jobs on the final `main` commit must pass before the annotated `v0.9.0` tag
  and GitHub release. Phase C1 evaluation and the simulator benchmark are not part of this release.

## Status — 2026-11-20, worktree-independent upload storage (`fix/shared-upload-storage`, not pushed)

- Finding from the v0.9.0 local sync: raw uploaded files lived under the primary checkout's `var/uploads` while the
  API ran from another worktree with its own `var/uploads`.
- Fix (D127):
  - `UPLOAD_DIR` defaults to a shared absolute directory outside every checkout;
  - `UploadStorage` is the single resolver for store, locate and delete (UUID-validated, no symlinks, direct
    containment);
  - deletion stays inside the root and reports legacy copies;
  - new `opspilot uploads migrate-storage [--apply]` (SHA-256 verified copy, originals kept, rows unchanged);
  - `uploads list` shows each dataset's location.
- Procedure: `docs/maintenance/UPLOAD_STORAGE.md`. No migration, schema or model change. The E2E stack keeps its
  isolated `E2E_UPLOAD_DIR`.


## Status — 2026-11-20, v0.10.0 Azure Monitor / Application Insights (`feature/azure-monitor-v0.10.0`, not pushed)

- Base: `origin/main` = `1c30e88` (v0.9.0 plus the shared upload-storage fix, D127). Isolated worktree
  `../opspilot-ai-azure`. Implementation commit `80f3dd0`; this entry records the completion and verification pass.
  No migration, schema, model, safety-policy or approval change. Nothing pushed, merged, tagged or released.
- Connector (`opspilot_shared/connectors/azure_monitor.py`, D128–D132):
  - one read-only call, `POST https://api.loganalytics.azure.com/v1/workspaces/<GUID>/query` (public cloud), as
    the connector's whole allowlist; loopback-only fixture override in `fixture` auth mode;
  - explicit `azure-identity` credential per `AZURE_MONITOR_AUTH_MODE` (service principal, managed identity, Azure
    CLI); token cache, refresh and 401 retry; tokens scrubbed, `AADSTS`-only errors;
  - 13 fixed KQL templates over `AppTraces`, `AppExceptions`, `AppRequests`, `AppDependencies`; validated, quoted
    service names and operation IDs; operator template rules; bounded window, rows, bins, run time, size and
    concurrency;
  - per-table connection test; discovery by `AppRoleName`; partial results, 204, missing tables, sampling and
    partial correlation surfaced, never filled in; dependency targets are not observed services.
- Web (Visual Experience 2.0 kept): Azure in the connected intake and the Integrations catalogue, request/dependency
  preview, provenance with workspace and tables, report banner and next steps. BFF allows
  `connectors/azure_monitor/(test|services)`, operator-only.
- Fixes in the completion pass:
  - **Sampled records flagged (D132).** Only sampled metric bins were flagged; trace, exception, request and
    dependency queries with `ItemCount > 1` now note it, and *Evidence coverage* names them ("record counts understate
    event counts"). Regression tests in the connector and investigation suites.
  - **Capped log search no longer presented as the first error (D134).** Found in the real-model run: for uploads and
    connected snapshots, a truncated WARN+ search is labelled "earliest returned … earlier occurrences may exist" in
    evidence and the timeline. Simulator wording is byte-identical (no `make evaluate` impact). Regression test.
  - **E2E web process allowlist (D133).** Playwright now starts Next.js through `web_env --exec`, so the E2E API's
    database/MCP/signing credentials no longer reach the web process. Security test with sentinel values.
  - **E2E specs.** An ambiguous "synthetic fixture" locator in the Azure journey was made exact. The Datadog and
    Loki/Prometheus journeys now also uncheck Azure Monitor: with every fixture on, Azure had joined the Datadog
    snapshot and failed its banner assertion. No assertion was weakened.
- Verified (isolated stack: `opspilot_test`, API 8100, web 3100, Azure fixture 8129; test credentials read
  key-by-key from the main checkout's `.env` with the user's authorization, never copied or printed):
  - `make lint` clean (mypy `--strict` 113 files, import-linter 4/4, ESLint, tsc);
  - pytest 576 passed / 3 skipped (live-model opt-in); web 73 passed; `pnpm build` OK;
  - Playwright with `E2E_AZURE=1 E2E_DATADOG=1 E2E_TELEMETRY=1`: 13 passed, 5 skipped by design (two
    not-configured tests, three opt-in screenshot tests); without fixtures: 6 passed (Azure and Datadog not
    configured, auth, overview);
  - screenshots (synthetic fixture data) in `docs/images/azure/`.
- Real-model result (two Azure journey runs, `qwen3.5:9b-q4_K_M`; development testing, not an evaluation): top
  hypothesis both times was the observed `db.pool.max_size=5` configuration line exhausting payment-service's pool
  (95%), cited. No recovery, remediation or "nothing changed" claim. Residual model wording: the 2.14.0 start-up line
  is called "the deployment" in hypothesis 2; the summary states the cause as fact; the suggested (not executed)
  restart would not by itself fix the configuration. Not addressed: no prompt or model change.
- Not done / open:
  - **no real Azure tenant or workspace used**: authentication, API compatibility and queries are not
    live-verified (procedure in `docs/integrations/AZURE_MONITOR.md`);
  - native Azure Monitor resource metrics, sovereign clouds and change history are deferred;
  - `make evaluate` not re-run (the simulator path is unchanged);
  - draft notes `docs/releases/V0.10.0_NOTES.md`; not tagged or published.

## Status — 2026-11-20, v0.10.0 RCA truthfulness corrections (same branch, not pushed)

- Final bounded pass on `e54488b`, requested before release approval. Model output is never edited.
- **Claim calibration (D135).**
  - Uploaded and connected reports open with *How to read this report*: observed facts, evidence-supported
    hypotheses, verified causal conclusions (none in a read-only analysis), unknowns.
  - `claims.py` adds deterministic notes, in the report and the workbench, when a summary or hypothesis:
    - states a cause as established;
    - calls an observed start-up or configuration log line a deployment or configuration change while change
      history was not collected;
    - says "ongoing" (anchored to the end of the snapshot window).
  - The impact line reads "Impact at the end of the collected snapshot window (…) … not the current live state".
  - A suggested `restart_service` carries a limitation when the leading hypothesis is a configuration problem.
  - Simulator investigations are not annotated: prompts, outputs and `make evaluate` are unaffected.
- **Empty Azure results (D136).** An empty Azure query is "No accessible matching records — access/coverage not
  independently verified" in provenance, the preview and incident badges, its own *Evidence coverage* row and the
  provenance table; the connection test says "no accessible records". 401/403, `PartialError` and missing tables
  are unchanged. Loki/Prometheus/Datadog empty results keep their wording.
- Tests: `tests/unit/test_claim_calibration.py` (16, including real-run phrasings), a connector test (empty vs 403
  vs `PartialError` vs probe), web `queryStatusLabel` tests, and Azure E2E assertions on the report and preview.
- Verified (isolated stack, as before):
  - `make lint` clean (mypy 113 files, import-linter 4/4, ESLint, tsc);
  - pytest 593 passed / 3 skipped; web 75 passed; `pnpm build` OK;
  - Playwright with all fixtures: 13 passed, 5 skipped by design; Azure journey re-run after the last change:
    3 passed, 1 skipped by design; without fixtures: 6 passed, 6 skipped by design;
  - screenshots in `docs/images/azure/` refreshed.
- Real-model run (`qwen3.5:9b-q4_K_M`, final RCA): the model's text matched the previous run. The summary's "The
  root cause is a configuration change" now carries the established-cause, change-indicator and snapshot-window
  notes; hypotheses 1–2 carry change-indicator notes; the restart suggestion shows its limitation; seven empty Azure
  queries are listed as no accessible matching records.
- Still open: live Azure verification; deferred native metrics, sovereign clouds and change history; the
  calibration is English pattern matching (unrecognized phrasings are not flagged); not tagged or released.

## Status — 2026-11-20, v0.10.0 release preparation (authorized)

- User approved `f31fcf15d57c0cf2472b23b66b4540c2c3f2e3de` for release as v0.10.0.
  - Verified `origin/main` = `1c30e88` (v0.9.0 plus the shared upload-storage fix, D127); latest release v0.9.0.
  - The approved commit is a direct descendant (three commits), with no divergence.
- Integrated on `release/v0.10.0` (cut from `origin/main`) with a non-rewriting merge commit whose tree equals the
  approved commit. Local `main` is checked out in another worktree and stays untouched; remote `main` is advanced
  normally at publication.
- Release docs: README status, Azure sections and limitations; final `docs/releases/V0.10.0_NOTES.md` (implemented
  and synthetically tested / not live-verified / deferred; the RCA stays model-written and the claim warnings are
  heuristic safeguards that also apply to uploaded and other connected investigations). "Unreleased" markers removed.
- Release validation on the merged tree: `make lint` clean; pytest 593 passed / 3 skipped; web 75 passed; build OK;
  Playwright 13 passed / 5 skipped by design (all fixtures) and 6 passed (no fixtures). No migration.
- Publication gate: the Python and web CI jobs on the final `main` commit must pass before the annotated `v0.10.0`
  tag and GitHub release.

## Status — 2026-11-23, v0.11.0 AWS CloudWatch Logs & Metrics (`feature/aws-cloudwatch-v0.11.0`, not pushed)

- Base: verified `origin/main` = `2154211` (v0.10.0, latest release; v0.9.0 Datadog, the shared upload storage fix
  and the web-env allowlist included). Isolated worktree `../opspilot-ai-cloudwatch`; the main checkout, other
  worktrees, `.env`, data, uploads and private `phase-c1`/`.c1/` files were not modified. No migration, schema, model,
  safety-policy or approval change. Nothing pushed, merged, tagged or released.
- Connector (`opspilot_shared/connectors/cloudwatch.py`, `cloudwatch_resources.py`; D137–D142):
  - official SDK (boto3/botocore 1.44): `StartQuery`/`GetQueryResults`/`StopQuery` (own unfinished queries only),
    `DescribeLogGroups` (configured names), `GetMetricData`, `GetCallerIdentity`, optional `AssumeRole`; regional
    endpoints verified per client, endpoint overrides ignored, commercial partition only;
  - explicit auth modes (`profile`, `instance_role`, `access_keys`, loopback `fixture`) with filtered credential chains,
    lazy clients, optional expected account; keys never returned, logged or stored; AWS error text not passed through;
  - `CLOUDWATCH_RESOURCES_FILE` mapping = allowlist; unmapped resources "not queried"; six Logs Insights templates and
    ten AWS metric templates plus configured custom metrics; bounded asynchronous lifecycle (≤ 3 in flight, ≤ 40 polls /
    60 s, shielded StopQuery cleanup incl. cancellation, partial rows marked); scan statistics recorded.
- Pipeline: `QueryProvenance.aws`, `ConnectionStatus.identity`/`log_groups`; prompt note, report banner, provenance,
  coverage and next steps for CloudWatch; Loki/Prometheus/Datadog/Azure wording unchanged.
- RCA truthfulness (D143), found in the real-model run: annotate-only notes for invented version numbers / quoted
  identifiers and for change claims that cite no change evidence (read-only RCAs; simulator unchanged).
- Web (Visual Experience 2.0 kept): catalogue entry now implemented, matrix, connector panel, connected intake (region,
  account, per-log-group badges, cost note, fixture incident, query provenance), incident provenance; BFF allowlist.
- Fixture: `scripts/cloudwatch_fixture.py` (Logs JSON 1.1, CloudWatch JSON 1.0, STS query/XML, SigV4 required),
  `infra/cloudwatch/resources.{fixture,scenarios,example}.yaml`, `infra/cloudwatch/iam-readonly-policy.example.json`,
  `make cloudwatch-fixture`, `E2E_CLOUDWATCH=1`.
- Infra used for verification: Colima and the project PostgreSQL container were started (`make infra-up`, containers
  only) and the local Loki/Prometheus test containers (`make telemetry-up`, tmpfs) for the regression journeys; tests
  read the main checkout's `.env` in-process (not copied); only `opspilot_test` and ports 8100/3100/8133 were used.
- Verified (fixture only):
  - `make lint` clean: ruff, ruff format, mypy `--strict` (115 files), import-linter 4/4, ESLint, `tsc`.
  - pytest: **694 passed, 3 skipped** (live-model opt-in) on `opspilot_test`, including the live local Loki/Prometheus
    tests; new: 92 connector tests (botocore `Stubber` + the protocol fixture through the real SDK), 3 investigation
    tests, 5 API tests, 1 claim-calibration test.
  - Web unit tests: 76 passed; `pnpm build` (production) OK.
  - Playwright on the isolated stack (API 8100, web 3100, `opspilot_test`):
    - every fixture on (`E2E_TELEMETRY=1 E2E_DATADOG=1 E2E_AZURE=1 E2E_CLOUDWATCH=1`): **16 passed, 6 skipped by design**
      (three "not configured" journeys that only apply without fixtures, three opt-in screenshot specs) — CloudWatch,
      Azure Monitor, Datadog, Loki/Prometheus, uploads and the INC-001 simulator approval with verified recovery;
    - CloudWatch journeys re-run after the final UI changes: 3 passed, 1 skipped by design;
    - no fixtures: **9 passed, 13 skipped by design** (CloudWatch, Azure and Datadog show as not configured).
  - Real local-model RCA (`qwen3.5:9b-q4_K_M`, synthetic CloudWatch evidence, several identical runs at temperature 0):
    read-only, cited, no actions; top hypothesis "database connection pool saturation caused inventory-service
    timeouts" (95%), citing the `db_pool_wait_ms` series. Unsupported details are now annotated, not edited: an invented
    "'ConnectionPoolTimeout'" error name, an invented "version 2.3.1" and a "recent deployment" with no change evidence
    (D143); "ongoing" is anchored to the snapshot end. Residual: the model did not use the observed
    `db.pool.max_size=8 (previous 40)` line (listed under *Evidence coverage → Observed events*), and its suggested
    `restart_service` carries no limitation note because hypothesis 1 is not classified as a configuration problem.
- Not done / open: **no real AWS account used** (auth, IAM scoping, quotas, query syntax acceptance and costs are not
  live-verified; procedure in `docs/integrations/AWS_CLOUDWATCH.md`); `make evaluate` not re-run (simulator path
  unchanged); draft notes `docs/releases/V0.11.0_NOTES.md`; not tagged or released.
