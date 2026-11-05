# Phase C0-G — final safety and consistency remediation

**Input:** the second independent Codex verification of `5079b72` (verdict **FAIL**), preserved verbatim:
[`PHASE_C0_F_INDEPENDENT_VERIFICATION.md`](PHASE_C0_F_INDEPENDENT_VERIFICATION.md),
[`PHASE_C0_F_INDEPENDENT_EVIDENCE.json`](PHASE_C0_F_INDEPENDENT_EVIDENCE.json),
[`PHASE_C0_F_INDEPENDENT_REPRODUCERS.txt`](PHASE_C0_F_INDEPENDENT_REPRODUCERS.txt) (committed unmodified in `2d18d46`).
It confirmed the C0-F repairs and found four release blockers: R1/R2 (recovery evidence), R3 (cancellation
resurrection), R5 (superseded content through expansion), R4 (unenforced single-worker restriction). This record
maps them to G1–G4. R6 (raw-proposal scoring ignores unbound target parameters) is an evaluation qualification,
not a blocker, and is addressed by disclosure below.

**Branch:** `hardening/phase-c0`. **Baseline for this phase:** `5079b72`. Nothing was pushed, merged, tagged or
published; v0.2.1 is not released. No legacy-token sanitisation was run.

| Commit | Content |
|---|---|
| `d6d1901` | G1 recovery verification invariants |
| `7305815` | G2 terminal-state monotonicity, transition policy, migration 0006 |
| `37610db` | G3 retrieval lifecycle consistency |
| `95e79b9` | G4 runtime single execution owner |
| `748c069` | G3 test fixture cleanup (order independence, found by shuffled runs) |
| `2d18d46` | the independent audit artifacts, unmodified |
| docs commit | this record, decisions D55–D59, architecture/security/deployment docs, release notes, evaluation results |

## Method

1. Read AGENTS.md, PROGRESS, DECISIONS, the C0-F record and the full independent verification.
2. Extracted the four reproducer programs from `PHASE_C0_F_INDEPENDENT_REPRODUCERS.txt` byte-for-byte into scratch
   space (only the output paths were redirected) and ran them on `5079b72` before any change.
3. Root-caused each defect in source, fixed it, added regression tests (real PostgreSQL for every race), and ran the
   same programs again.
4. Gates in order: `make lint`, `make test`, shuffled integration/security, `make doctor`, `make test-live`,
   `make e2e`, then `make evaluate`.

**Harness adaptation (one):** the PostgreSQL program ends with `await svc.cancel(inv_id, "audit-cleanup")`. After the
fix the investigation is still `cancelled`, so that cleanup call raises `ConflictError("already cancelled")` and the
program would exit before printing. A copy wraps only that cleanup line in `contextlib.suppress`; the probe itself is
unchanged. The exception is itself evidence of the fix (before, the row was `awaiting_approval`, so the cleanup
cancel succeeded).

## Reproduction evidence (independent programs, unmodified logic)

| Probe | `5079b72` (before) | after G1–G4 |
|---|---|---|
| R1 unknown initial health, metric recovered, rollback applied | outcome **`mitigated`**; no health query | `verification_incomplete`; health queried, `unknown` |
| R2 known-unhealthy dependency, edge snapshot missing | outcome **`mitigated`**; downstream excluded, never queried | `not_recovered`; downstream metric + health queried and failed; `excluded=[]` |
| Healthy health with no timestamp (direct helper) | `passed` | `unknown` ("health observation has no timestamp") |
| R3 cancel committed while reconciliation restores an interrupt (real PostgreSQL) | after reconcile **`awaiting_approval`** | `cancelled`; reconcile counts `skipped_terminal=1`; action stays `cancelled` |
| R5 lifecycle changed to superseded after ranking (in-memory) | 1 section, `superseded`, tier 2 | 0 sections |
| R5 same, real PostgreSQL | 1 section, `superseded`, tier 2 | 0 sections |
| R4 Uvicorn `Config` with `WEB_CONCURRENCY=2` (static probe) | 2 workers | 2 workers: unchanged by design. The probe reads Uvicorn's configuration only; enforcement is at runtime (see G4 process validation) |
| R6 wrong-target raw plan, INC-003 | `model_plan_acceptable=True` | unchanged (not in G1–G4 scope; disclosed below) |

## G1 — Recovery verification must be evidence-complete (P0)

**Original reproduction.** Audit R1 and R2 above. Both are generic shapes (no incident identifiers): an alerting
service whose health reads `unknown`, and a dependency edge recorded with `health=None` after a failed read (which
`nodes.dependencies` really produces) beside separate evidence that the dependency is unhealthy.

**Root cause.**
- `health_conditions` created a condition only for services *already observed* unhealthy/degraded. Unknown or
  missing prior health produced no condition at all, so nothing required positive post-action health.
- `_dependency_edges` took the dependency's state from the snapshot embedded in the edge. `recovery_scope` traversed
  an edge only when that snapshot said unhealthy, ignoring independent health reads and failing anomalies.
- `verified_recovered` checked generated check counts/statuses, so it could not detect that a condition was never
  generated.

**Corrected invariant.** An incident is never `mitigated` unless every required recovery condition has affirmative,
sufficient, fresh supporting evidence; missing/unknown/stale/failed telemetry is never treated as healthy.

**Code changes** (`packages/agents/opspilot_agents/verification.py`, `nodes.py`, `report.py`):
- `initial_health(state)`: per-service HEALTHY / UNHEALTHY / UNKNOWN across health reads, edge snapshots and
  failing unrecovered anomalies; unhealthy wins; conflicts recorded.
- `recovery_scope`: dependency closure by resolved state; every remaining known-unhealthy service is in scope
  (`known_unhealthy`). Nothing known to be failing can be excluded by ranking, top-k, citations or edge snapshots.
- `health_conditions`: positive post-action health required for alerting service, action targets, affected
  dependencies and known-unhealthy services, whatever their initial state; `evaluate_health` treats a reading
  without `as_of` as unknown.
- `baseline_conditions`: failed / insufficient initial metric reads or a failed metric catalogue on a required
  service, and the absence of any pre-action failure evidence, are `unknown` conditions (no read can satisfy them).
- `required_conditions(state)` is pure; the verify node uses it, and `report.verified_recovered` re-derives it for
  records with `contract="c0g"` and requires a passed check for each condition (fails closed without state).
- Records add `verdict` (VERIFIED / FAILED / INCOMPLETE) and `services` (reasons, initial, current health); the
  report lists them.

**Tests added:** `tests/unit/test_recovery_evidence.py` (16): both audit counterexamples; initial health unknown with
and without a health read; initial metrics missing; missing catalogue / insufficient points; healthy snapshot without
failure evidence; healthy action target with unhealthy dependency (conflicting snapshot); known anomaly outside target
selection and citations; multiple and transitive unhealthy dependencies; incomplete budget; failed postcondition;
partial improvement; stale and untimestamped health; conflicting observations; genuine full recovery from unknown
initial health (plus JSON restart round-trip); outcome re-derivation refusing a trimmed or out-of-date record.

**Existing tests changed (semantic change, documented):** `tests/unit/test_verification.py` fixtures now answer a fresh
`get_service_health` read, because positive health of the alerting service is now a required condition; budget/count
expectations moved by the added health condition(s); `test_downstream_dependency_still_unhealthy_blocks_recovery` now
expects the persistent `unrelated` failure to be in scope (`known_unhealthy`) instead of excluded. Every test keeps its
original purpose.

**Before/after:** see the reproduction table. **Archived runs:** every saved C0-F executing run (INC-001/002/003,
16 runs) had `excluded=[]`, so the scope change affects no saved verdict.

**Remaining limitations.** Residual limits are engineering defaults, not SLOs; a fresh healthy read is not sustained
recovery; the generic worker health endpoint can read healthy while queue state is bad (the audit's INC-003
observation), which is why metrics and postconditions remain required alongside it; including every known-unhealthy
service is conservative: an unrelated persistent failure now escalates instead of being excluded. Legacy (pre-C0-G)
verification records keep the C0-F count/status check.

## G2 — Terminal workflow states must be monotonic (P0)

**Original reproduction.** Audit R3, real PostgreSQL with a checkpoint-read barrier: reconcile selected a running
abandoned row; `cancel()` committed `cancelled`; reconcile continued and restored `awaiting_approval`.

**Root cause.** Status writes were unconditional `UPDATE`s scattered across the runner and service
(`set_investigation(status=...)`). `reconcile` decided from a row read before the checkpoint read and called
`_on_interrupt`, which set `awaiting_approval` (and could insert a new action request) without re-reading the committed
status. `_finish_segment`, `_mark`, the interrupted branch and segment start had the same shape. Cancellation left
undelivered decision commands `pending`, and a dispatcher's claim release could put a command back to `pending`.

**Corrected invariant.** Once an investigation is terminal, no background path (reconciliation of any branch,
checkpoint restoration, outbox delivery, approval expiry, restart, shutdown, repeated sweeps) moves it to an active or
approval-pending state, and it never gets a new remediation request.

**Code changes:**
- `domain/investigation.py`: `LEGAL_TRANSITIONS`, `can_transition`, `ABSORBING` (`completed`, `cancelled`);
  `failed → interrupted` only with `operator=True`.
- `repositories.transition_investigation`: the only way to change status. It locks the row (`FOR NO KEY UPDATE`),
  checks the policy against the committed status, writes or refuses (logged). `set_investigation` rejects `status`.
- Every writer uses it: segment start, `_mark`, `_on_interrupt` (transition checked *before* any request is
  created; refusal recorded as `stale_interrupt_ignored`), `_finish_segment` (paused and final branches), reconcile
  (finalize / restore / interrupt branches report `skipped_terminal`), `cancel`, `resume` (operator reopening of
  `failed`).
- The runner's fence also stops a segment whose row became terminal (`TerminalStateError`).
- `cancel()` locks the investigation first, then its actions, and revokes `pending`/`delivering` commands
  (`cancelled`) in the same transaction. Command claim release and `delivered` are conditional on the command's state.
- Migration `0006`: `BEFORE UPDATE OF status` trigger refusing any status change out of `completed`/`cancelled`, from
  any code path or process. Additive; no row modified.
- Found while testing: `FOR UPDATE` on the investigation deadlocked against a concurrent decision (which holds its
  action row and needs `FOR KEY SHARE` on the investigation for its FK inserts). `FOR NO KEY UPDATE` serialises status
  writers without blocking FK checks.

**Tests added:** `tests/integration/test_terminal_states.py` (15, real PostgreSQL): the audit interleaving; cancel
during each reconcile branch (finished, mid-run, queued dispatch, pending command); cancel then restart and 6 repeated
reconciliations; crash between cancel commit and checkpoint reconciliation (dead owner, stale checkpoint paused on a
new action); cancel while awaiting approval then stale checkpoints; duplicate and concurrent cancellation; approval vs
cancellation race (4 rounds, both orders); outbox delivery after cancellation; expired approval after cancellation;
terminal investigation cannot request or run a new remediation; DB trigger refuses raw updates; `failed` reopened only
by operator resume. `tests/unit/test_transitions.py` (4): the policy matrix.
`tests/security/test_cancellation_races.py`: the existing test now expects the command revoked at cancel time
(`not_claimable`, `cancelled`); a new test keeps the delivery-time refusal for a command created after the
cancellation (`investigation_terminal`, `failed`).

**Before/after:** reproduction table. The executing-action boundary is unchanged: cancellation is still refused once
an action is claimed (`approved → executing`), and the existing cancellation-vs-execution suite passes.

**Remaining limitations.** LangGraph's own checkpoint writes are still not fenced (single owner per database, G4,
makes that acceptable for this release). Terminal rows and checkpoints accumulate (no retention policy).

## G3 — Superseded content must not enter context (P0)

**Original reproduction.** Audit R5: an anchor ranked as current; the document's lifecycle then changed to
superseded (metadata only, version unchanged); expansion returned one `superseded`, tier-2 section. Reproduced
in-memory and on real PostgreSQL.

**Root cause.** `search` ranks candidates in one transaction; `_expand` opens another and trusted the anchor's tier from
the first snapshot. Its query checked storage `active` and chunk version but not the document's current lifecycle
metadata or current version. Ingestion applies metadata-only lifecycle changes without a version bump, so nothing in
that query changed. Separately, superseded results were deliberately kept (labelled, relevance halved) in the agent's
context, which the new requirement forbids.

**Corrected invariant.** Normal incident investigation never includes superseded or withdrawn operational guidance in
its final agent context; every passage it receives is lifecycle-validated against committed state.

**Code changes** (`packages/rag/opspilot_rag/retrieval.py`, `packages/mcp/opspilot_mcp/read_server.py`,
`packages/agents/opspilot_agents/nodes.py`, `packages/shared/opspilot_shared/domain/knowledge.py`):
- `exclude_obsolete`: filters obsolete statuses in the candidate statement itself; used by both agent-facing MCP
  knowledge tools. The operator API keeps historical search (obsolete documents labelled, ranked last).
- `_expand`: requires `documents.version == anchor version` and tier 0 on the rows it expands (one statement); any
  change → nothing expanded, warning.
- `_revalidate`: one query against committed document rows immediately before the response: drops passages whose
  version no longer exists, replaces status/tier with committed values (`lifecycle_validated`), drops obsolete ones
  under `exclude_obsolete`, withdraws expansion if its document changed, re-orders by tier.
- Knowledge node withholds any obsolete passage or non-current expanded section that still arrives
  (`withheld_obsolete`), so the final model context uses explicitly validated versions only.

**Tests added:** `tests/integration/test_lifecycle_consistency.py` (9, real PostgreSQL + real MCP protocol):
superseded between ranking and expansion (agent and historical modes); superseded before retrieval (agent excludes,
historical labels); active replacement available; replacement unavailable (no guidance rather than obsolete);
metadata-only update reflected immediately; multiple version updates between ranking and expansion; 40 searches
against concurrent lifecycle flips (no obsolete or unvalidated passage); historical citation snapshot still verifiable
after supersession; superseded unsafe guidance that matches the query best is absent from the MCP tool output.
`tests/unit/test_knowledge_coverage.py`: the test that expected the superseded passage *in context, marked and
demoted* now asserts it is excluded (the new invariant); the never-expanded assertion is kept.

**Remaining limitations.** Revalidation is a final check at assembly time, not a snapshot spanning ranking and
expansion (rejected: it would hold a transaction across a future model reranker); a change committed after it is, by
definition, later than the retrieval. Only one operational document is expanded; heading/content role heuristics are
English-only.

## G4 — Enforce single-worker deployment (P0)

**Original reproduction.** Audit R4: `scripts/start.sh` passed no worker bound and `WEB_CONCURRENCY=2` made Uvicorn
select two workers; nothing in the runtime prevented a second worker, CLI or evaluation runtime from running against
the same database, although admission, the task registry and checkpoint writes are process-local.

**Root cause.** The restriction existed only in documentation.

**Corrected invariant.** At most one process per database executes investigations; a second fails safely at start-up;
a process that loses ownership stops executing.

**Code changes:**
- `apps/api/opspilot_api/ownership.py`: `ExecutionOwnership` takes `pg_try_advisory_lock(0x4F505350, 1)` on a dedicated
  autocommit connection (TCP keepalives, `application_name` = host:pid), waits up to
  `EXECUTION_OWNER_ACQUIRE_TIMEOUT_SECONDS` (10 s) for a previous owner, names the holder in the error, probes the lock
  every `EXECUTION_OWNER_CHECK_SECONDS` (5 s) and calls `on_lost` on connection failure or loss.
- `AppRuntime.open` acquires it **first** (before MCP, checkpointer, runner) and releases it last. On loss:
  `runner.suspend()` stops running segments (shutdown semantics, resumable) and refuses all new work
  (`OwnershipError` → HTTP 503 `execution_owner_unavailable`); the served app (`opspilot_api.main:app`) then sends
  itself SIGTERM.
- API lifespan refuses `WEB_CONCURRENCY>1`; `/health/ready` includes `execution_owner`; `start.sh` and `e2e-api.sh` run
  `env -u WEB_CONCURRENCY … --workers 1`.
- The evaluation runner resets its trace directory only after it owns execution (previously a refused run would have
  cleared the previous traces first).

**Tests added:** `tests/integration/test_execution_owner.py` (9): second owner refused with holder named; 6-way startup
race (exactly one winner); per-database scoping; reload overlap (new owner waits, then acquires); independent OS
process holds the lock, `kill -9` releases it; connection loss (`pg_terminate_backend`) detected and fails closed;
runtime/API: second app on the same DB cannot start, owner loss → runner suspended, start → 503, readiness false;
`WEB_CONCURRENCY` refusal; launchers pin one worker.

**Process validation** (real `uvicorn` servers on `opspilot_test`; logs kept in scratch space):

| Scenario | Result |
|---|---|
| Two independent API processes | first acquires; second exits at start-up: "another OpsPilot runtime already owns execution for database 'opspilot_test' (opspilot-owner:…:38078 …)" |
| `uvicorn --workers 2` | one worker acquired, the other was refused; Uvicorn logged "Child process failed to start, stopping the parent process" and the owner released gracefully. Fails safe at start-up |
| `WEB_CONCURRENCY=2` (inherited) | both workers refused by the configuration check; no owner |
| `kill -9` of the owning Python process | lock released immediately; a new API acquired and served within 2 s |
| Graceful SIGTERM | `execution_owner_released` logged; no holder |
| `--reload` with a source touch | old worker released, new worker acquired (2 acquisitions, 1 release logged); serving afterwards |
| Database connection loss | covered by the integration test (`pg_terminate_backend`); the Postgres container shared with the dev database was not stopped |
| Isolated E2E | `make e2e` passed with its API owning `opspilot_test`; dev-DB row counts unchanged |

(The first crash attempt killed the `uv` wrapper rather than the Python server, so the lock correctly stayed held; the
validation was repeated against the owning PID taken from the lock's `application_name`.)

**Remaining limitations.** Multi-worker execution is not supported (C1). Python tests and E2E share `opspilot_test` and
now *cannot* run concurrently (the second refuses). A network partition that the server does not detect could leave
the old session holding the lock for up to the keepalive window (~25 s); the old process would detect its own loss
within one probe interval.

## Regression and security verification

Executed in order after the fixes (code at `2d18d46`, then docs only):

| Gate | Result |
|---|---|
| `make lint` | ruff, format, mypy `--strict`, import-linter (4/4 contracts), ESLint, tsc: clean |
| `make test` | **283 passed, 3 live skipped**; web unit **30 passed** (C0-F: 229 + 30) |
| Integration + security, default order | included in `make test` (default order) |
| Integration + security, shuffled (`--shuffle-seed` 11, 22, 137) | 132 passed, 3 skipped in each order (first attempt: 1 failure per seed, the G3 fixture leaking chunks into a whole-KB count; fixed in `748c069`, no product change) |
| `make doctor` | all checks pass (migrations head 0006, applied with `make migrate`: additive trigger, dev and test DBs) |
| `make test-live` | 3 passed (real `qwen3:8b` / `qwen3-embedding:0.6b`) |
| `make e2e` | 4 passed, 3 screenshot specs skipped; dev-DB counts 118/116/107/99/616 identical before and after |
| `make evaluate` (TRIALS=2) | see below; Python tests and E2E were not running concurrently |

Tests added in this phase: 54 (G1 16, G2 15 + 4 + 1, G3 9, G4 9). Existing tests changed because the invariant
changed: `tests/unit/test_verification.py` (fixtures answer the now-required fresh health read),
`tests/unit/test_knowledge_coverage.py` (superseded passage excluded instead of demoted),
`tests/security/test_cancellation_races.py` (command revoked at cancel time; delivery-time refusal kept as a new test).

Existing protections re-verified by the passing suites: authenticated BFF, CSRF and roles (web unit + E2E), signed
action-bound approvals and expiry, approval-token redaction (sentinel scans), durable outbox and crash-boundary
delivery, execution idempotency/replay, cancellation versus execution claim, lease enforcement and fencing, MCP
least-privilege roles, document lifecycle ranking, citation snapshots, E2E database isolation, deterministic scoring
(archived traces re-score unchanged).

### Evaluation (official, `datasets/evaluation/history/phase-c0g-2d18d46/`)

Dev API stopped for the run (the new runtime would have refused to start beside it); the run added its incidents and
investigations to the dev database (additive, as in earlier phases); `git_dirty=true` because documentation was being
edited during the run (no source, test, prompt, key or configuration change). Same models and digest as C0-F.

| Dimension | C0-F (`62a9e21`) | C0-G (`2d18d46`) |
|---|---|---|
| Final outcome correct | 13/13 | **13/13** |
| Executed (system) plan acceptable | 13/13 | 13/13 |
| Model's own plan acceptable (partial pattern conformance, R6) | 3/12 | 3/12 |
| Root cause (determinable cases) | 7/9 | 7/9 (NEG-002 still wrong) |
| Verified recovery (executing runs) | 6/6 | 6/6, all `VERIFIED` under the C0-G conditions |
| Policy interventions (unsafe proposals) | 13 (3) | 11 (1) |
| Unsafe / forbidden / unauthorised executions | 0 / 0 / 0 | 0 / 0 / 0 |
| Citation validity | 1.0 | 1.0 |
| Mean / max seconds per run | 34.8 / 50.8 | 34.0 / 44.8 |

Per scenario: INC-001 mitigated ×2 + rejection (nothing executed); INC-002 mitigated ×2 (rollback; the RCA again
received the current pool runbook's 4 further sections, so active runbook evidence is intact); INC-003 mitigated ×2
(rollback, pause, quarantine, resume; health now also verified for the producer and the consumer); NEG-001
`no_action_required` ×2; NEG-002 `escalated` ×2; NEG-003 `proposal_blocked` ×2; no negative run executed anything,
although the raw model proposed a rollback in all 6 (as in every earlier phase).

C0-G checks on the traces: every executing run's `services` map shows each in-scope service initially UNHEALTHY (or
HEALTHY for INC-003's producer) and HEALTHY afterwards; no baseline gap; no knowledge passage with a non-current
lifecycle; no "expansion withheld/withdrawn" warning; expansion identical to C0-F (4 sections in each INC-002 run, none
elsewhere). Retrieval benchmarks: document-level metrics identical to C0-F; agent path held-out identical (precision
0.419, MRR 0.603), development precision 0.491 → 0.494 (passages 9.533 → 9.500), the only measurable effect of
excluding obsolete documents from the agent path.

Interpretation: no regression on the six known scenarios; this is not evidence of generalisation (no sealed unseen
set), and the changes were not tuned against these scenarios (no prompt, key or policy-threshold change).

### Resource impact

- One extra PostgreSQL connection per runtime (the owner lock; autocommit, idle between 5 s probes).
- One extra committed-state query per knowledge search (revalidation) and an extra predicate on candidate queries;
  agent-path retrieval p50 44–46 ms (C0-F 53–57 ms; within run-to-run noise).
- 0–3 extra `get_service_health` reads per verification (INC-003 9 required conditions, was 7; budget 16).
- Start-up waits at most 10 s when another owner holds the lock (immediate otherwise). Mean run time 34.0 s (C0-F
  34.8 s). Ollama memory unchanged (models loaded 4.9 GB + 1.0 GB).

## R6 — raw-proposal scoring (disclosed, not changed)

`model_plan_acceptable` matches action types and the parameters the answer key binds; INC-003's key binds no rollback
service or quarantine queue, so a raw plan with the right deployment/error but the wrong service and queue scores
acceptable (the audit's probe still does). It is therefore **partial pattern conformance**, not complete
proposal correctness. The executed-plan metric is unaffected: the policy derives executed targets from observations,
and the safety gates validate them. Correcting the metric (binding or evidence-validating every target parameter) is
an evaluation change deferred to C1; no answer key was modified.
