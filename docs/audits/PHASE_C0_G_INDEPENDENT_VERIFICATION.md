# Phase C0-G — final independent release gate

**Overall verdict: FAIL. Do not release v0.2.1 at this revision.**

Reviewed 2026-11-05 on `hardening/phase-c0`, HEAD `b2a76d5`, against `5079b72`. The original recovery, cancellation and lifecycle reproducers now demonstrate their intended corrections. G1 and G2 pass. Two additional, independently reproduced failures prevent signing off the complete G3/G4 contracts:

- **N1, High — ownership loss during initialization is forgotten by the runner.** A runtime whose watchdog already detected loss can subsequently execute an investigation and write checkpoints alongside a replacement owner. This affects the supported CLI/evaluation runtime path.
- **N2, Medium — concurrent ingestion can reuse a document version for different content.** Retrieval can silently combine ranked content from revision A with expanded guidance from revision B, label both the same current version, and mark both lifecycle-validated.

These are narrow corrections to the requested release invariants. They do not require multi-worker support, a new planner, an unseen scenario set, or production deployment infrastructure. No unauthorized remediation, duplicate effect, or checkpoint corruption was demonstrated by these probes.

## Baseline, scope and evidence boundaries

Read AGENTS.md and RTK.md, PROGRESS, DECISIONS, ROADMAP, the C0-F independent verification and original reproduction programs, C0-G remediation, affected implementation/tests, deployment/security contracts, release notes, and latest/frozen evaluation artifacts. Reviewed the implementation diff and each requested commit:

| Commit | Verified content |
|---|---|
| `d6d1901` | Recovery scope, affirmative health, baseline sufficiency, outcome reconstruction |
| `7305815` | Transition policy, locked status writers, terminal trigger, command revocation |
| `37610db` | Lifecycle exclusion, expansion checks, final revalidation |
| `95e79b9` | Execution-owner lock/watchdog and launcher restrictions |
| `748c069` | Lifecycle-test fixture cleanup only |
| `2d18d46` | Preserved previous independent audit artifacts |
| `b9166fb` | Documentation and evaluation results |
| `b2a76d5` | Frozen-artifact index |

All eight commits are ancestors of HEAD and form the stated consecutive chain from `5079b72`. The checkout was clean before the audit. The only audit additions are under `docs/audits/`; application source, tests, prompts, answer keys, historical benchmarks and existing reports were not changed. No commit, push, merge, tag, publication, legacy-token sanitization or full model evaluation was performed. No ground-truth files or simulator scenario internals were opened.

Mutating checks used `opspilot_test` exclusively. Direct probes asserted both configured database name and SQL `current_database()` before writes. Preflight verified migration `0006` and no execution-owner holder on that database. Test infrastructure was used sequentially, with no concurrent Python/E2E suite. The process harness additionally required no unfinished investigations before starting an API, used temporary loopback ports, and stopped only its own processes. The development API/database were left alone; no development row-count comparison was performed or needed to direct these guarded test connections.

Supporting artifacts: [evidence and test-case inventory](PHASE_C0_G_INDEPENDENT_EVIDENCE.json), [additional reproduction programs and execution boundaries](PHASE_C0_G_INDEPENDENT_REPRODUCERS.txt). Formal test results are distinguished below from probes that successfully reproduce a defect.

## G1–G4 verification matrix

| Gate | Result | Independent conclusion |
|---|---|---|
| G1 — recovery evidence | **PASS** | R1/R2 fail closed; all required conditions are generated before budgets and reconstructed before mitigation. Previous scope/partial-recovery defects remain fixed. |
| G2 — terminal state | **PASS** | R3 preserves cancellation. PostgreSQL races, trigger enforcement, command revocation, repeated reconciliation and explicit failed-run resume pass. |
| G3 — document lifecycle | **FAIL** | Original R5 is fixed, including real PostgreSQL. N2 defeats the version-identity assumption under overlapping ingestion; mixed revisions pass final validation. |
| G4 — single execution owner | **FAIL** | Ordinary competing processes/workers, crash recovery, shutdown and reload pass. N1 permits execution and checkpoint writes after already-detected initialization-time loss. |

### G1 — recovery evidence

Source: [initial health resolution](../../packages/agents/opspilot_agents/verification.py#L163), [scope](../../packages/agents/opspilot_agents/verification.py#L189), [required conditions](../../packages/agents/opspilot_agents/verification.py#L514), [verification node](../../packages/agents/opspilot_agents/nodes.py#L1262), [outcome guard](../../packages/agents/opspilot_agents/report.py#L53).

| Requested property | Verification |
|---|---|
| 1. Unknown never means healthy | Required services get positive post-action health checks regardless of initial state. Exact R1 returns `verification_incomplete`, with health `unknown`. |
| 2. Required unhealthy dependencies cannot disappear | Health is resolved across all observations; a missing/healthy edge snapshot cannot hide independent unhealthy evidence. Exact R2 queries downstream metrics and health and returns `not_recovered`, with no exclusions. |
| 3. Every required health condition evaluated | Conditions are enumerated before budgets; omitted calls become explicit `not_checked`. Multiple/transitive dependencies and budget exhaustion pass existing targeted tests. |
| 4. Partial improvement is not recovery | Original 0.002 → 0.4 → 0.08 reproducer fails the 0.012 limit. Metric-specific direction/ranges and opposite-direction checks remain present. |
| 5. Missing post-action telemetry prevents mitigation | Failed/unknown health or metrics cannot pass; baseline read/catalogue gaps create unknown conditions. Relevant tests pass. |
| 6. Stale observations cannot prove recovery | Health requires an `as_of` at or after execution; stale and untimestamped cases fail closed. Metric calls use the action's post-execution window. This establishes the current simulator/read-tool contract, not arbitrary future telemetry-adapter integrity. |
| 7. Conflicting evidence is conservative | Initial unhealthy evidence wins and requires a fresh check. Unhealthy post-action health or failed metrics prevent mitigation even when other observations pass. A historical initial conflict can legitimately be resolved by fresh post-action success. |
| 8. Final outcome agrees with verification | C0-G records require all recorded checks to pass and every reconstructed condition key to be present. Tests reject trimmed/outdated verification records. |
| 9. Earlier defects stay fixed | Original omitted-worker and partial-improvement cases still fail recovery; original admission/scoring probes also retain their corrections. |
| 10. No known-scenario dependency | Condition/scope implementation uses observed services, edges, metrics and executed targets; no incident/scenario identifier branches were introduced. Generic renamed-service cases pass. |

An unrelated known persistent failure now blocks mitigation. This is a documented conservative limitation, not an unsafe outcome: it can escalate an otherwise repaired incident, but cannot falsely report full recovery. Residual limits remain defaults, fresh health is not sustained recovery, and pre-C0-G records retain their documented compatibility semantics. This audit does not retroactively certify historical labels under the new contract.

### G2 — terminal-state consistency and locks

Source: [transition policy](../../packages/shared/opspilot_shared/domain/investigation.py#L24), [locked transition](../../apps/api/opspilot_api/repositories.py#L115), [interrupt restoration](../../apps/api/opspilot_api/services/investigations.py#L480), [cancel](../../apps/api/opspilot_api/services/investigations.py#L911), [reconcile](../../apps/api/opspilot_api/services/investigations.py#L968), [database trigger](../../infra/db/migrations/versions/20261105_0006_terminal_investigation_guard.py#L25).

| Requested property | Verification |
|---|---|
| 1–2. Cancelled/completed remain terminal | Policy refuses transitions out of both; migration 0006 independently rejects direct SQL changes. Real-DB tests cover both states. |
| 3. Stale checkpoints cannot reopen | R3 and tests for finished, mid-run, queued, pending-command and stale-interrupt branches preserve committed cancellation. Restoration checks before creating an action request. |
| 4. Outbox cannot resurrect cancellation | Cancellation revokes pending/delivering commands atomically. Dispatcher settlement/release is conditional and terminal workflows do not execute. |
| 5. Approval/cancel races safe | Both timing orders and cancellation-versus-execution-claim tests pass. A claimed action remains the documented non-cancellable boundary. |
| 6. Expiry cannot change terminal state | Expired-approval-after-cancel test passes; action CAS and terminal restoration checks prevent reopening. |
| 7. Duplicate reconciliation idempotent | Repeated/restarted reconciliation and duplicate/concurrent cancellation tests pass; duplicate cancellation may return conflict rather than a second success. |
| 8. Direct invalid transitions rejected | Actual PostgreSQL trigger tests pass, beyond repository helper tests. |
| 9. Lock ordering avoids the identified deadlock | Investigation writers serialize with `FOR NO KEY UPDATE`; cancellation then locks actions in ID order and revokes commands. Approval/expiry lock their action and insert referencing events/commands; FK `KEY SHARE` is compatible with the investigation lock. Dispatcher command claims commit before inspecting/submitting work. No cycle was found in these paths; targeted races completed. |
| 10. Designed operator resume remains possible | Failed → interrupted is operator-only; the explicit-resume test passes. Completed/cancelled cannot be resumed. |

Independently compiled the installed SQLAlchemy expression `.with_for_update(key_share=True)` with the PostgreSQL dialect: it emits **`FOR NO KEY UPDATE`**, not `FOR KEY SHARE`. This is the correct lock for the affected non-key status writes: it serializes competing status updates while allowing FK checks. [Action execution](../../packages/mcp/opspilot_mcp/action_server.py#L92) claims its action in a separate committed transaction before simulator effects. None of these reviewed transactions spans inference. Passing these races is evidence for these paths, not a universal deadlock-freedom proof.

### G3 — lifecycle, revisions and citations

Source: [candidate exclusion](../../packages/rag/opspilot_rag/retrieval.py#L119), [expansion](../../packages/rag/opspilot_rag/retrieval.py#L317), [final revalidation](../../packages/rag/opspilot_rag/retrieval.py#L368), [agent tool policy](../../packages/mcp/opspilot_mcp/read_server.py#L216), [knowledge assembly](../../packages/agents/opspilot_agents/nodes.py#L890).

| Requested property | Verification |
|---|---|
| 1–2. Superseded/withdrawn excluded | Agent-facing searches exclude the shared obsolete-status set in candidate SQL and final validation; the knowledge node also withholds obsolete hits. Exact R5 returns no expanded sections in memory and PostgreSQL. |
| 3. Concurrent ingestion cannot silently mix revisions | **FAIL, N2 below.** Different contents reuse version 2 and are mixed in one validated response. |
| 4. Citations match content/version hashes | Passage snapshots are self-hashed and retain selected content/version. All 112 saved citation snapshots checked here match their SHA-256. N2 shows the integer document version is not a unique revision identity under concurrency; a correct passage hash does not repair that ambiguity. |
| 5. Metadata-only changes take effect | Real-DB metadata-only lifecycle tests pass; R5 changes no version and is excluded. |
| 6. Historical evidence reconstructable | Citation snapshots retain passage/hash/version/lifecycle/time after ingestion changes. Existing reconstruction test and saved snapshot checks pass. Full old document storage is not claimed. |
| 7. Authorized historical search functional | Historical-mode retrieval tests preserve labelled obsolete content; the operator-authenticated `/knowledge/search` route keeps historical mode. The route/auth implementation is unchanged. |
| 8. INC-002 retains current guidance | Both official saved traces contain four expanded current pool-runbook sections with diagnostics/remediation/capacity guidance, all within the actual top-34 RCA evidence selection. No obsolete saved citation was found. No new live trial was needed. |
| 9. Expansion bounded | Public search clamps expansion to four sections of one operational document; agent evidence selection is also capped. This is a count bound, not a tokenizer-enforced worst-case budget. |
| 10. No scenario exceptions | Selection uses document type, lifecycle and generic heading/content roles; no scenario-specific branch was introduced. |

The ordinary final-check window is acceptable: a lifecycle change committed **after** the final query is later than that retrieval's validation point. Retrieval is a historical observation, not an everlasting freshness guarantee. No long transaction across ranking/inference is required for this experimental release. **N2 is different:** revision B has already committed before expansion/final validation, yet revision A survives because both have the same version number.

### G4 — ownership enforcement

Source: [advisory lock and watchdog](../../apps/api/opspilot_api/ownership.py#L111), [runtime lifecycle](../../apps/api/opspilot_api/runtime.py#L68), [admission/suspension](../../apps/api/opspilot_api/services/investigations.py#L140), [API loss callback](../../apps/api/opspilot_api/main.py#L67), [CLI](../../apps/api/opspilot_api/demo.py#L107), [evaluation](../../packages/evaluation/opspilot_eval/runner.py#L111).

| Requested property | Verification |
|---|---|
| 1. Two API processes excluded | Fresh independent Uvicorn servers: second exits 3 with holder error, first remains the only holder. |
| 2. Multiple workers cannot execute concurrently normally | Real `--workers 2`: one acquisition, second refused, parent stops and releases ownership. Parent exit is **0**, so startup log/health is stronger evidence than exit status alone. |
| 3. WEB_CONCURRENCY rejected | Real inherited `WEB_CONCURRENCY=2`: zero acquisitions, configuration refusal, no remaining holder. Parent also exits 0. Launchers explicitly unset it and pin one worker. |
| 4. Acquisition race-safe | Real-PostgreSQL six-way acquisition test has one winner. Lock session is dedicated/autocommit and database-scoped. |
| 5. Abnormal termination permits recovery | Existing independent-process SIGKILL test and fresh owning-server SIGKILL/restart both pass. |
| 6. Graceful shutdown releases | Fresh SIGTERM leaves zero holders. Runtime normally releases ownership after runner/gateway/checkpointer shutdown. |
| 7. Reload works | Fresh Uvicorn reload of a scratch import module changes worker PID, serves afterwards and has one holder. Application source was not touched. |
| 8. Connectivity loss stops execution | Established-runtime loss test detects terminated owner connection, suspends runner and refuses start with 503. **Initialization-time case fails, N1 below.** |
| 9. Test ownership isolated | Only `opspilot_test` was used, no competing holder before/after process probes. Python/E2E exclusivity remains required; the retirement fixture is not an owner-scoped cross-suite lock. |
| 10. CLI/evaluation obey contract | Both enter `AppRuntime.open`, so ordinary exclusion applies. **They inherit N1 and have no API process-exit callback.** Evaluation now resets traces only after runtime entry, but N1 can return that entry unowned. |

The watchdog is asynchronous. Work/checkpoint writes during the interval **before detection** are possible; this is not synchronous saver fencing. Default idle detection involves a 5-second sleep and, for a stalled probe, up to a further 5-second timeout, with scheduling qualifications. Server-side keepalives address a separate roughly 25-second stale-session window. A new owner cannot acquire while PostgreSQL still holds the old lock. These bounded local failure-detection limits and full fencing belong in documented limitations/C1; N1 instead permits continued work **after detection**, with the watchdog already finished.

## New verified defects and smallest required corrections

### N1 — High, release blocker: initialization loses ownership permanently but still returns an executable runtime

At [runtime.py:70](../../apps/api/opspilot_api/runtime.py#L70), loss suspends execution only if `holder["rt"]` exists. The holder is populated at [line 118](../../apps/api/opspilot_api/runtime.py#L118), after awaiting gateway and checkpointer initialization. If the owner connection dies during one of those awaits, the watchdog sets `held=False`, invokes the callback with an empty holder, and exits. Initialization subsequently constructs an unsuspended runner and yields it without checking the sticky loss state. [reserve/submit](../../apps/api/opspilot_api/services/investigations.py#L140) check runner suspension rather than the runtime's lost ownership.

**Independent reproduction:** gate read-gateway initialization; terminate only the test runtime's owner connection; wait until its loss callback has run; start a replacement runtime and let it acquire; finish the first initialization. Both runtime contexts admit work. Start a separate incident through each service with deterministic models and real MCP/PostgreSQL/checkpointers. Both reach `awaiting_approval` and write checkpoints; the old runtime reports `held=false`, a recorded loss reason, and `runner.suspended=null`. Neither receives an approval or executes remediation. Both workflows are then cancelled for cleanup.

The two contexts in this probe share an OS process but use independent owner connections, runners, graph instances and checkpoint pools. This controls the real failing initialization interleaving; separate API process exclusion was tested independently. The custom loss hook only signals the test barrier. It supplies no suspension/exit behavior, equivalent to the default CLI/evaluation paths at the cited entry points. A slow local MCP startup plus a lost/reaped owner session is sufficient; unsupported multi-worker configuration is unnecessary.

**Required correction:** make loss sticky throughout initialization and refuse runtime entry if ownership was lost before publishing its runner; ensure loss already observed before runner construction is applied to that runner. Close partial resources normally. Add this controlled initialization-loss case for the default CLI/evaluation runtime path. No global admission service or fully fenced checkpointer is required to close this defect.

### N2 — Medium, release blocker for the requested document-consistency contract: two contents share one revision identity

[ingest.py:149](../../packages/rag/opspilot_rag/ingest.py#L149) reads the current document in a separate transaction. [Line 183](../../packages/rag/opspilot_rag/ingest.py#L183) derives the next version from that old object before embedding. [_store:208](../../packages/rag/opspilot_rag/ingest.py#L208) later overwrites the committed row using the supplied version, without a lock/CAS that assigns a distinct revision from current state. Thus overlapping updates that both observe version 1 both commit different content as version 2. Chunk IDs are also derived from version/ordinal.

**Independent reproduction:** ingest one UUID-named current test runbook as version 1. Begin two normal per-file ingestion paths with different content snapshots of the same logical source; gate their deterministic embedding after both read version 1. Commit A (version 2); rank its symptom passage; commit B (also version 2); continue expansion and final validation. The response contains `REVISIONA signal` in ranked results and `REVISIONB instructions` in context. Both claim version 2, both carry `lifecycle_validated=true`, and `warnings=[]`. The audit document is then retired.

The probe uses real parsing, ingestion, chunk storage and retrieval; it does not force versions through raw SQL. Scratch files represent two captured snapshots of one source, as can occur when a knowledge file changes between overlapping ingests. The single execution-owner lock does not serialize ingestion requests. No unsafe action was demonstrated. This is a material violation of the explicitly requested consistent-version guidance/citation contract, at the same lifecycle boundary as R5; it is not a demand for immutable whole-document archival. The underlying ingestion race was not established as newly introduced by G3.

**Required correction:** serialize/CAS each document's commit and assign the revision from the locked committed row, or reject/retry a stale writer, so different content cannot reuse the same document version. Use the actual committed revision for chunks and returned metadata. Existing expansion/revalidation must then reject changed revisions. Add this overlapping-ingestion/ranking/expansion case. Embedding need not run inside a database transaction, and retrieval need not hold one across reranking.

## Reproducer results and tests actually executed

| Check | Fresh result |
|---|---|
| Exact R1/R2 program, including pure R5/helper timestamp check | R1 `verification_incomplete`; R2 `not_recovered`, downstream checked; timestamp-free health `unknown`; R5 expansion empty. Exit 0. |
| Exact PostgreSQL R3/R5 program | R3 logs refused `cancelled → awaiting_approval`, `skipped_terminal=1`; exits 1 at its duplicate-cancel cleanup with the expected `ConflictError`. This harness stop is not a product failure. |
| Same PostgreSQL program, only duplicate-cancel cleanup suppressed | Cancellation remains cancelled, action cancelled; R5 expansion empty. Exit 0. Probe/database guards unchanged. |
| Earlier four-case independent program | Worker checked/fails recovery; one admitted row/no orphan; partial recovery fails; duplicate rollback unacceptable. Exit 0. |
| Recovery/verification/transitions/knowledge unit selection | **51 passed**, 0 failed/skipped; 0.15 s. |
| Terminal/owner/lifecycle/cancellation-race selection | **41 passed**, 0 failed/skipped; 12.74 s; real PostgreSQL and child processes. |
| Admission/concurrency/durable-delivery/expiry/checkpoint/action-enforcement/redaction/DB-role selection | **44 passed**, 0 failed/skipped; 66.62 s; real PostgreSQL. |
| Real Uvicorn process checks | Ordinary exclusion, worker overrides, graceful release, owner SIGKILL/recovery, reload all pass their assertions/observations; final holders 0. |
| Additional startup-loss probe | **N1 reproduced**, including actual investigation/checkpoint writes after loss. |
| Additional overlapping-ingestion probe | **N2 reproduced**, mixed revisions accepted without warning. |
| Saved evaluation/artifact consistency | Totals/trace score copies/outcomes agree; citation snapshot hashes match; frozen/latest artifacts agree. |

The three pytest selections contain **136 passing tests**, without rerunning the full deterministic suite. Exact selections and every case name are in the evidence artifact. New probes returning exit 0 mean the probe ran successfully, not that the release invariant passed.

No full LLM evaluation, live-model tests, browser E2E, full lint or shuffled whole-suite rerun was needed. The C0-G implementation record reports **283 Python passed, 30 web passed, 132 integration/security passed in each of seeds 11/22/137, 3 live passed, 4 E2E passed**. Those are prior reported results, not fresh executions here; raw execution logs for all those totals are not part of the frozen evaluation archive. The previous independent audit separately established the unchanged BFF/web guards. Their existence is useful regression evidence but cannot override N1/N2.

## Security regression assessment

No additional approval/authentication bypass was verified. Fresh targeted tests pass action-specific signature/hash/expiry enforcement, persisted-parameter execution, idempotency, cancellation versus action claim, durable outbox delivery/crash boundaries, admission/lease fencing, token redaction and MCP DB-role restrictions. The read/action server separation remains; no new free-form shell, SQL or file-path tool was added.

BFF authentication, session-bound CSRF, roles and server-side decision identity are unchanged from the independently tested baseline ([auth.ts](../../apps/web/lib/server/auth.ts#L94), [BFF route](../../apps/web/app/api/ops/%5B...path%5D/route.ts#L60)). Backend mutations retain [operator authorization](../../apps/api/opspilot_api/deps.py#L21). E2E keeps the [database/instance identity guard](../../apps/web/e2e/isolation.ts#L12) and forced test stack; only its launcher worker bound changed. These unchanged paths were reviewed and prior test evidence reused, rather than claiming fresh browser execution.

N1 compromises execution-owner consistency, not signed approval checks; N2 compromises guidance/revision integrity, not tool authorization. No new secret values were printed or copied into audit artifacts. Historical expired-token findings were not recounted or sanitized; the prior report's 58 tool-call records must not be conflated with checkpoint token-key counts or current valid tokens. Key-based redaction remains narrower than arbitrary free-text secret detection, and same-OS-user MCP processes are not hostile-process isolation.

## Evaluation integrity review

Latest official evidence is [the generated baseline](../evaluation/BASELINE.md) and `datasets/evaluation/history/phase-c0g-2d18d46/`. Independently checked aggregate/per-trace consistency without opening answer keys or running inference. All latest evaluation files, all 13 traces and BASELINE match the frozen copies. All **84 pre-existing historical files** compare byte-for-byte with `5079b72`; none was rewritten.

| Dimension | Verified saved result | Interpretation |
|---|---|---|
| Final system outcomes | **13/13 correct** | Six mitigations, six negative outcomes and one initial-action rejection; not 13 recoveries or 13 correct model decisions. |
| Executed system plan | **13/13 acceptable** | Includes correct no-execution cases; execution plans are policy-shaped/validated. |
| Recorded recovery evidence | **6/6 VERIFIED** | All six executing traces carry `contract=c0g`, all recorded conditions pass; required/check counts are 5/5 for INC-001, 9/9 for INC-002 and INC-003. This is inspection of saved evidence, not an independent replay of underlying telemetry. |
| Raw model planning | **3/12 acceptable** | Approve trials only. R6 remains disclosed as partial pattern conformance, not complete target/parameter correctness. |
| Root-cause reasoning | **7/9 correct** | Only determinable causes enter the denominator, including the INC-001 rejection run. NEG-002 remains wrong. Keyword/change-ID scoring is narrower than semantic causal proof. |
| Policy intervention | **11 interventions; 1 unsafe proposal** | Safety-policy intervention is distinct from correct model reasoning. Negative raw plans still propose rollback in all six saved negative runs. |
| Executed action safety | **0 unsafe, 0 forbidden, 0 recorded approval bypass** | Applies to these saved fixtures and scoring definitions. Approval-bypass counting is before the first decision; fresh enforcement tests provide stronger coverage of authorization/replay. |
| Citations/current guidance | **112 snapshot hashes checked; no obsolete saved citations** | INC-002 retains four expanded current sections in each official run. Does not disprove the independently reproduced concurrent-ingestion gap. |

The saved trace scores and summary agree; no saved successful outcome was invalidated by the two new probes. Ground truth was not reopened/relabelled. Recovery scoring still reads the recorded verification status; saved public trace fields do not preserve every initial coverage detail necessary for a full independent reconstruction of baseline gaps. Metadata records `git=2d18d46`, `git_dirty=true`, model digest, temperature/context and selected policy fields. The documentation says only documentation was dirty; the stored metadata alone does not independently reconstruct that dirty diff or complete transport prompts/options.

The release notes already distinguish model weaknesses from gate-driven system outcomes and disclose partial plan scoring. Preserve those qualifications. No release claim should imply that the LLM independently made correct decisions in all runs. The missing sealed, independently authored unseen set remains C1, not a standalone release blocker.

## Remaining risk classification

| Limitation | Classification | Release treatment |
|---|---|---|
| No independently authored sealed unseen scenarios | **PHASE C1** | Known-scenario stability only; no generalization sign-off. |
| Single-worker deployment restriction | **ACCEPTABLE LIMITATION**, enforcement correction blocked by N1 | One owner is a valid experimental contract; multi-worker support/fenced saver/global admission are C1. |
| Conservative recovery thresholds/unrelated persistent failures | **ACCEPTABLE LIMITATION** | May escalate; does not manufacture recovery. Service SLOs and sustained-health windows can be C1. |
| Historical approval-token records | **ACCEPTABLE LIMITATION** | Previously verified expired/action-bound; owner-authorized sanitization remains separate. No new dev-DB inspection here. |
| Shared OS user for MCP | **ACCEPTABLE LIMITATION** | Local trusted-user boundary, minimal environment and DB roles; OS separation is C1. |
| Completed workflow/checkpoint growth | **PHASE C1** | Retention/owner-scoped cleanup improvement; no demonstrated immediate corruption/capacity failure. |
| Evaluation writes to development DB | **ACCEPTABLE LIMITATION** | Documented additive opt-in evaluation; stop API first. Dedicated verified evaluation DB is C1. No evaluation was run here. |
| Python/E2E not simultaneous | **ACCEPTABLE LIMITATION** | Reserve test DB exclusively. Harness retirement precedes some runtime locking, so the owner lock alone is not a safe cross-suite coordination mechanism. |
| Incomplete raw model-plan metric | **PHASE C1** | Publish only as partial pattern conformance; keep root cause, gates, safety and final outcomes separate. |
| Advisory-lock detection/partition delay | **ACCEPTABLE LIMITATION** within documented local bounds | Pre-detection work is possible; complete synchronous fencing is C1. Continued work after detected loss in N1 is a **BLOCKER**, not this limitation. |
| Same-version concurrent content replacement, N2 | **BLOCKER** | Violates consistent current guidance/revision identity before final validation; narrow commit-serialization correction required. |

## Final recommendation for v0.2.1

**Do not proceed at `b2a76d5`.** Close N1's initialization-time ownership hole and N2's concurrent revision reuse, then rerun their preserved programs plus the affected ownership/lifecycle regression tests. Both corrections are within Phase C0-G. The original R1/R2/R3/R5 repairs should be retained; normal single-owner process enforcement is a substantial correction and should also be retained.

No other independently verified release blocker was found in this finite gate. Once these two narrow failures are closed and required change checks pass, the listed local restrictions, model weaknesses, historical state and C1 evaluation work can support proceeding with a clearly described **local-first experimental v0.2.1** release. No correction or release publication is included in this audit.
