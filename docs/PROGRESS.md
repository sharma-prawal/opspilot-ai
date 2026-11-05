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
