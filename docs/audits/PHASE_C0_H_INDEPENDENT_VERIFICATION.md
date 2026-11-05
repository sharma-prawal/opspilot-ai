# Phase C0-H — final independent release verification

**Overall verdict: CONDITIONAL. Recommend signing off Phase C0 for a local-first experimental v0.2.1 release, with the claim qualifications below.**

The two original blockers are independently verified closed: overlapping ingestion assigns distinct versions to different source content, and initialization-time ownership loss prevents the old runtime reaching READY, executing, or checkpointing. No new release-blocking violation was verified through the supported ingestion, investigation, approval, cancellation or takeover paths.

This is not an unqualified certification of every stronger sentence in the implementation report. Two verified boundaries must remain explicit in release claims:

1. **Document revision identity is logical source-content identity; physical chunk mappings are not immutable.** Reindexing unchanged text with different chunk settings can reuse a chunk ID/version for a different slice. Citation snapshots remain valid. Arbitrary direct chunk SQL is also not independently protected by migration 0007.
2. **The application database role is a trusted schema administrator.** It owns the epoch/checkpoint tables and can disable triggers or edit the epoch. The fence blocks stale normal application writes and unprivileged MCP roles; it is not tamper-proof against that owner credential.

These qualifications do not require a new architecture, multi-worker support or another model. They distinguish demonstrated local application guarantees from stronger database-tamper-resistance and physical-chunk-immutability claims that were **not** established.

## Baseline and audit boundaries

Reviewed 2026-11-05 at `de879a2cd4b1d793cd211c0457db97406d9e02bc`, branch `hardening/phase-c0`. The working tree was initially clean. All requested commits are consecutive ancestors of HEAD:

| Commit | Reviewed change |
|---|---|
| `1e28076` | Serialized document publication, revision/hash pinning, migration 0007 |
| `5729dbb` | Lifecycle, ownership epochs, database fencing, checkpoint pool binding, approval-token binding, migration 0008 |
| `1635170` | H1/H2 fault/concurrency tests and dead-session release handling |
| `2116ef1` | Preserved C0-G independent audit artifacts |
| `de879a2` | Remediation record, documentation and frozen evaluation results |

Read AGENTS.md/RTK.md, PROGRESS, DECISIONS, the C0-G independent verification and reproduction programs, C0-H remediation, relevant migrations/source/tests, deployment/security contracts, release notes and latest evaluation artifacts. Reviewed the implementation/test diff from `b2a76d5`. No application source, repository tests, existing audit reports, prompts, answer keys or evaluation history were modified. No ground-truth files or simulator scenario internals were opened.

All mutating probes used `opspilot_test` exclusively and ran sequentially. Preflight SQL established the database identity, head `0008`, no owner lock and no unfinished workflows. The final check again found zero holders, zero unfinished workflows, and all three checkpoint triggers enabled. Direct probes used UUID-owned KB documents/threads. Administrative trigger changes were transaction-rolled-back; audit documents were retired. No development database mutation, full LLM evaluation, merge, push, tag or publication occurred.

Supporting artifacts: [evidence and exact test inventory](PHASE_C0_H_INDEPENDENT_EVIDENCE.json), [independent reproduction programs and commands](PHASE_C0_H_INDEPENDENT_REPRODUCERS.txt).

## H1 — document revision consistency

**Result: PASS for the original N2 blocker and the supported logical document-revision contract. The stronger immutable-physical-chunk/database-only claim requires qualification.**

The [publication transaction](../../packages/rag/opspilot_rag/ingest.py#L196) takes a per-document transaction advisory lock before reading the committed document. It assigns the version from that read, updates document metadata, deletes previous chunks and inserts replacements in one transaction. Embedding occurs beforehand; a stale metadata-only decision retries rather than publishing unprepared content. The publication linearization point is transaction commit. Advisory-key hash collisions would serialize additional documents, not weaken exclusion.

[Migration 0007](../../infra/db/migrations/versions/20261105_0007_kb_revision_integrity.py#L49) adds the deferred composite FK from chunk `(document_id, document_version)` to document `(id, version)`. Its [document trigger](../../infra/db/migrations/versions/20261105_0007_kb_revision_integrity.py#L64) rejects a backwards version or a changed document hash without a version increase. Fresh PostgreSQL tests directly exercised those refusals and deferred-FK failure; this assessment does not rely only on application checks.

[Expansion](../../packages/rag/opspilot_rag/retrieval.py#L319) pins the anchor's version and document hash. [Final validation](../../packages/rag/opspilot_rag/retrieval.py#L371) reads the selected document rows in one statement and drops mismatching versions/hashes, inactive documents and obsolete lifecycle statuses. All surviving passages for one document must have one version/hash pair.

| Requested guarantee | Independent evidence / boundary |
|---|---|
| 1. Overlapping ingestions cannot publish different source content under one version | Exact original N2 program now produces A=2, B=3; ranked A is dropped after B commits. Concurrent-writer regression passes. |
| 2. Unique, stable committed source revision identity | Version assigned under publication lock; hash changes require increasing version. New A → B → A schedule produces versions 1 → 2 → 3: identical final hash does not revive the old version-1 response. Physical chunk identity is separately qualified below. |
| 3. Returned passages use one logical revision per document | Version/hash-pinned expansion, final committed-row comparison and explicit mixed-pair exclusion; existing and independent concurrency assertions pass. |
| 4. Hashes agree with selected content/revision | Each passage carries its own SHA-256 and pinned document hash. All 112 saved citation snapshot hashes checked correctly. This is not database recomputation of the source hash from arbitrary chunk SQL. |
| 5. Failed ingestion cannot partially publish | Embedding failure and wrong-dimensional chunk insert after row update/delete both preserve the previous committed revision in real PostgreSQL. Deferred-FK failure also rolls back the transaction. |
| 6. Readers do not mix different source revisions | Original rank-A/publish-B/expand schedule fails closed; before/after-commit tests pass. One statement sees one committed publication. |
| 7. Metadata-only lifecycle updates take effect | Current-metadata update preserves source revision; supersession during retrieval excludes it. Both existing revision/lifecycle suites pass. |
| 8. Superseded/withdrawn guidance excluded from normal agent context | Agent tools use obsolete exclusion; expansion and final validation recheck lifecycle; knowledge assembly also withholds obsolete evidence. Lifecycle/MCP regression selection passes. |
| 9. Retrieval concurrent with publication has a defined validation point | The final document SELECT establishes a committed logical revision/lifecycle snapshot. A later publication makes the response historical, which is allowed. It is not a lock spanning inference or a promise that physical chunk rows never change. |
| 10. Historical citation snapshots remain valid | Passage/hash/version/lifecycle/time are self-contained; historical-citation regression and the independent A → B → A snapshot check pass. Old complete document revisions are not archived. |

### Additional H1 schedules and exact scope of database enforcement

**New concurrency schedule:** rank source A at version 1; publish B as version 2; republish byte-identical A as version 3 before expansion/validation. Final document hash equals the original hash, but version differs. The response is empty; a fresh search returns version 3, and the old citation still self-verifies. This specifically tests an ABA schedule absent from the implementation's reproducer.

**Verified physical-chunk boundary through supported ingestion:** ingest a 125-word section with `chunk_max_words=200`; rank its chunk; reindex the identical source through `IngestionService` with `chunk_max_words=50` before expansion. Both publications report version 1 and the same document hash. The ranked snapshot still has 125 words while the current row for the same chunk ID/version has 50. Final validation accepts it without a warning. Its text remains an authentic slice of the same unchanged source revision; no different-source guidance or unsafe action was demonstrated. However, it disproves a literal claim that final validation guarantees equality with the **currently stored physical chunk bytes**. Version/hash pinning is not a physical chunk-generation fence.

**Verified SQL boundary:** as `opspilot_app`, a direct committed `UPDATE kb.chunks SET content=...` on an audit document can change text without changing document version/hash. A controlled retrieval then retains the old ranked text plus changed expansion, both labelled validated. Migration 0007 guards the document hash/version fields and FK membership; it does **not** guard chunk bytes or prove that a supplied document hash describes those bytes. This is a real counterexample to arbitrary-writer database immutability, not a hypothetical concern. The source was retired after the probe. Both MCP roles lack KB write privileges; no supported ingestion/tool path publishes that inconsistent SQL mutation.

**Classification:** acceptable trusted-publisher/representation boundary for this local release, with accurate claims. The original two-writer ingestion failure is fixed. Physical reindexing does not change the logical source content; deliberate out-of-contract SQL by the trusted application/schema owner is not an unprivileged agent capability. Do not describe this as immutable physical chunk IDs or database-enforced correctness against arbitrary chunk writers. This audit does not accept application checks as proof of those stronger properties.

## H2 — lifecycle, epochs and checkpoint fencing

**Result: PASS for stale normal runtime execution/persistence and unprivileged MCP access. Administrative table-owner tamper resistance is outside the verified guarantee.**

[Ownership acquisition](../../apps/api/opspilot_api/ownership.py#L215) holds a dedicated autocommit session advisory lock, then increments the singleton epoch and records that session's PostgreSQL PID. The epoch update commits before acquisition returns. Closing/crashing that session releases the advisory lock. The [lifecycle](../../apps/api/opspilot_api/ownership.py#L110) is synchronous and sticky; [runtime initialization](../../apps/api/opspilot_api/runtime.py#L68) binds the pool/runner, requires installed triggers, proves the fence and only then publishes READY.

[Migration 0008's fence](../../infra/db/migrations/versions/20261105_0008_execution_owner_fencing.py#L52) locks the epoch row `FOR SHARE`, compares epoch/PID, and checks that PID's granted advisory lock in this database. The lock lasts until the caller's outer transaction ends. New acquisition's epoch UPDATE conflicts with that share lock: an accepted in-flight write completes before the new epoch, or a later old-epoch write is refused. Fresh tests exercised the actual blocking/commit ordering.

[Checkpoint pools](../../apps/api/opspilot_api/checkpointing.py#L45) bind integer epoch/PID settings to every connection. The [installed statement triggers](../../apps/api/opspilot_api/checkpointing.py#L92) fence INSERT/UPDATE/DELETE on checkpoints, blobs and writes in their writing transaction. The fence uses a fixed SECURITY DEFINER search path; PUBLIC cannot execute `execution_fence`, and the action role receives only its required EXECUTE grant.

| Requested guarantee | Independent verification |
|---|---|
| 1. READY requires ownership | Adapted N1: loss during read-gateway initialization yields acquiring → lost → stopping → stopped, never READY. New late-startup schedule loses the owner after the checkpoint pool and runner exist, with watchdog asleep; affirmative verification still refuses startup. |
| 2. Second runtime cannot own concurrently | Real six-way acquisition and independent process tests pass. Fresh two-API Uvicorn run refuses the second process, leaving one holder. |
| 3. Loss prevents new execution | Detection synchronously suspends admission/cancels segments. Before detection, lease claim/persistence database fences reject stale execution. Independent control-plane probes show no stale graph/checkpoint/effect despite durable request writes. |
| 4. Old checkpoints cannot commit after the replacement epoch | Immediate-loss, independent stale-process and new-pool-after-takeover probes refuse old-epoch writes. The new pool establishes a fresh physical connection with the old binding, proving reconnect does not refresh ownership accidentally. |
| 5. In-flight writes ordered relative to takeover | Held fenced transaction blocks the epoch increment; its commit precedes takeover. Subsequent old-epoch write fails. This is fencing order, not a promise to abort a write that passed before loss. |
| 6. Trigger/role enforcement | Normal checkpoint DML without/stale binding fails. Actual MCP-role connections cannot access/disable checkpoint triggers or become `opspilot_app`. The application table owner can administratively disable triggers; see qualification below. |
| 7. Unprivileged roles cannot forge/change epoch | Both MCP roles are non-superuser/non-createrole, have no SELECT/UPDATE on `ops.execution_owner`, and actual UPDATE/SET ROLE attempts fail with SQLSTATE 42501. Application owner credentials remain trusted. |
| 8. Stale approval tokens cannot authorize new effects | Token carries signed epoch/PID; stale and unbound token tests refuse the action before claim. Reading an existing idempotency-ledger result is not a new execution. |
| 9. Claim enforces epoch | [Action claim](../../packages/mcp/opspilot_mcp/action_server.py#L91) checks the fence inside the transaction that claims the persisted approved action. Already-claimed effects are ordered before transfer and retain the existing non-cancellable/idempotent semantics. |
| 10. Shutdown stops execution/reconciliation/delivery | Non-READY runner gating, reconciliation entry/transaction fences, dispatcher refusal and maintenance cancellation prevent further execution. Command claim/release bookkeeping can still write safely; the claim is not that every SQL statement stops instantaneously. |
| 11. Crash permits safe takeover | Fresh owning-process SIGKILL/restart and independent stale-owner process tests pass; epoch increases and old writes fail. |
| 12. Reload/restart correct | Fresh Uvicorn reload changes owner PID, serves afterwards with one holder; graceful termination leaves zero holders. Restart test verifies increasing epoch. |

The N1 adaptations assert outcome directly: old context never entered, READY absent from its transition history, old model calls zero, no growth across checkpoints/blobs/writes or action executions before replacement work, and replacement-owned investigation reaches approval pause with checkpoints. The old program's timeout/exit assumption is not used as a failure oracle.

### Database-role qualification

Catalog and actual connection checks establish that `opspilot_app` is a non-superuser but **owns** `ops.execution_owner` and LangGraph tables. In a rolled-back audit transaction it successfully disabled the checkpoint-write trigger and inserted an unfenced audit row; rollback removed the row and restored the enabled trigger. The epoch table is likewise writable by its owner. Merely being non-superuser does not prevent these operations.

The two MCP roles could neither update the epoch, disable the trigger, nor SET ROLE to the application owner. The final catalog check showed all three triggers enabled. Therefore this is not an MCP escalation or an observed stale runtime bypass. It is an administrative trust boundary: database-enforced fencing applies with the installed schema and cooperating application code, not against a malicious holder of its owner credential. Do not claim that **all** ordinary application credentials are incapable of bypassing it. Additional migration/runtime role separation is not imposed as a new v0.2.1 requirement by this audit.

## Control-plane race assessment

The reported unfenced API writes are real, but are not equivalent to authorization for stale execution. Independently exercised these additional schedules with a slow watchdog, real PostgreSQL/MCP/checkpointers and deterministic models:

| Schedule | Actual result | Classification |
|---|---|---|
| Start transaction reserved/flushed before loss; commit and submit after a replacement owns the new epoch | Queued row commits, stale segment writes zero checkpoints. Replacement redispatches it and reaches approval pause after the ordinary lease-expiry condition is modeled on that audit row. | **B — recoverable state-management limitation.** Durable request may wait for lease/sweep recovery; not permanent loss or stale execution. |
| Old process accepts approval after its owner session dies and the replacement acquires | Approval/outbox intent commits; stale checkpoint count does not grow and no effect exists. After modeling command-lease expiry, replacement reconciliation remints a current-epoch token, executes the authorized action, completes and marks delivery. | **B — recoverable delivery delay.** No obsolete-epoch execution or duplicate effect. |
| Cancellation versus decision/execution/reconciliation | Existing current-code terminal/cancellation races pass. Status CAS, terminal trigger, action lock and command revocation remain intact. | No verified A defect. Unexercised timing combinations remain **C**, supported by the transaction argument rather than claimed as exhaustive measurement. |

Only audit-owned lease timestamps were advanced to model expiration; approval payloads and authorization were not rewritten. Defaults allow recovery delays up to the run lease (60 s), command lease (120 s), plus sweep timing. A start can be accepted durably and run later; an accepted approval remains an operator decision for the same persisted action/hash. Replacement token issuance deliberately binds delivery to its current epoch.

Terminal investigation updates still serialize against cancellation; pending/approved actions are revoked before task cancellation, and an executing claim makes cancellation conflict. Dispatcher settlement cannot revert a revoked command. Old lease release is conditional on its owner string, so it cannot clear a replacement's lease. These controls explain why the observed management writes do not reopen terminal work or grant obsolete-epoch authority.

**Control-plane conclusion:** B for the reproduced delays, C for additional unmeasured schedules; **no verified A release blocker**. No demand for fencing every control-plane row or eliminating all request races is justified by this evidence.

## Exact tests executed and original reproducer outcomes

| Selection / program | Actual result |
|---|---|
| `test_revision_consistency.py`, `test_owner_fencing.py`, `test_execution_owner.py` | **30 passed**, 7.86 s; PostgreSQL and independent processes. |
| Cross-cutting selection below | **93 passed**, 75.00 s; no live inference. |
| Independent scratch tests: two startup stages, ABA, chunk-DML rollback characterization, stale binding on a new pool, start takeover, approval takeover | **7 passed**, 4.21 s. Characterization success does not establish the stronger invariant it disproves. |
| Committed direct chunk-SQL characterization | Assertions passed: same document pair, changed expansion bytes, response validated. Audit document retired. |
| Corrected administrative-role boundary and supported changed-chunking reindex characterization | **2 passed**, 0.73 s. Administrative DDL/row changes rolled back. |
| Original N2 ingestion program, extracted unchanged | Exit 0; A=2/B=3; stale results/context empty with warnings. |
| Original N1, adapted to expected startup refusal | Both original gateway schedule and additional after-pool schedule pass direct non-READY/no-write assertions; replacement works. No old timeout is counted as a defect. |
| Original process program, byte-for-byte preserved | Two APIs: second exits 3; graceful/crash/reload correct; workers=2 acquires once then shuts down; WEB_CONCURRENCY=2 acquires zero times; final holders zero. Uvicorn parent exits 0 on worker-startup refusal, so exit code alone is not the oracle. |
| Offline evaluation/history verification | Stored totals and trace copies agree; 112 citation hashes valid; latest equals frozen; 102 pre-existing historical artifact files unchanged. |

The **123 existing targeted regression tests** all passed. Ten additional independent cases completed successfully across the scratch selections, including explicit boundary characterizations. Exact case names/statuses and commands are preserved in the supporting artifacts.

Cross-cutting files executed: `tests/integration/test_admission.py`, `test_terminal_states.py`, `test_lifecycle_consistency.py`, `test_citation_snapshots.py`, `test_durable_delivery.py`, `test_checkpoint_resume.py`; `tests/security/test_action_enforcement.py`, `test_cancellation_races.py`, `test_secret_redaction.py`, `test_mcp_db_roles.py`; `tests/unit/test_recovery_evidence.py`, `test_approval_tokens.py`, `test_transitions.py`.

Audit-harness errors were corrected without changing product code: first the scratch invocation lacked PYTHONPATH; then it omitted the repository's async pytest configuration (one unsupported-async failure and six setup errors); a later administrative checkpoint fixture used NULL in a NOT NULL blob column. The final fixture used bytes. The administrative transaction rolled back on that error. These attempts and their statuses remain identified in evidence; they are not product failures or hidden successful release tests.

No full 304-test rerun, full shuffle rerun, web rerun, live-model suite, browser E2E or `make evaluate` was necessary. Prior reported **304 Python / 30 web / 153 integration-security in each of three orders / 3 live / 4 E2E** results were checked against the remediation record; the frozen evaluation archive does not contain independent raw execution logs proving all those test totals. They are prior evidence, not fresh executions claimed here.

## Cross-cutting security and correctness

Fresh selections preserve recovery-evidence completeness, terminal monotonicity, atomic admission, action-specific signed/expiring approvals, cancellation, idempotency, durable delivery, redaction, lifecycle filtering, historical citation snapshots and MCP-role restrictions. Epoch binding adds to action/hash authorization; it does not replace it. No free-form shell/SQL/path agent capability was added.

BFF authentication/CSRF and isolated E2E identity guards are unchanged from the previously independently tested code. They were reviewed/reused rather than rerun with a live model. Tests and probes here were exclusively isolated; final test-DB state has no unfinished workflows/owner. The Python retirement fixture still requires exclusive test-database use and is not a cross-suite provenance mechanism.

## Evaluation integrity

Reviewed [generated baseline](../evaluation/BASELINE.md), `datasets/evaluation/history/phase-c0h-2116ef1/` and all official trace/score pairs without reopening answer keys or running inference. Latest results and BASELINE match frozen copies. All 102 pre-existing historical artifact files compared with `b2a76d5` are unchanged; the archive index is intentionally updated separately.

| Dimension | Verified saved figure | Scope |
|---|---|---|
| Final system outcomes | **13/13 correct** | Six mitigations, six negative outcomes, one rejection; not 13 independent correct model decisions. |
| Recorded recovery | **6/6 VERIFIED** | `contract=c0g`; all recorded checks pass, 5/5 for INC-001 and 9/9 for INC-002/003. Inspection of saved records, not independent telemetry replay. |
| Executed action safety | **0 unsafe, 0 forbidden, 0 recorded approval bypass** | Scoring definitions/known fixtures; fresh authorization tests provide stronger boundary evidence. |
| Raw model plans | **3/12 acceptable** | Approve trials only; disclosed partial pattern conformance, not full target/parameter correctness. |
| Root causes | **7/9 correct** | Determinable cases only; NEG-002 remains incorrect. |
| Policy enforcement | **11 interventions, 1 unsafe proposal** | Safety-policy success is distinct from correct model reasoning. All six negative raw plans still include rollback, with zero execution. |
| Mean investigation latency | **37.4 s** | Recomputed aggregate of saved `seconds_total`; no independent causal attribution of the difference from C0-G. |
| Citations / INC-002 guidance | **112 snapshot hashes valid** | No obsolete saved citation; four expanded current sections per INC-002 trial, all within the actual top-34 RCA evidence selection. |

Stored run scores, aggregate denominators and recorded outcomes agree. The scorer's recovery headline reads recorded verification; public traces do not retain every initial coverage detail needed to rebuild all baseline gaps independently. Metadata records source commit, model digest and selected settings, with a dirty-tree flag; it does not preserve a complete dirty diff/transport provenance. These qualifications do not justify relabelling scenarios or rewriting benchmarks.

The absence of a sealed independently authored unseen set is **Phase C1**. Near-deterministic known-case stability is not a generalization or model-autonomy claim. Preserve the existing distinction between model planning, root-cause reasoning, policy interventions, executed safety and final outcomes in publication.

## Remaining limitations and release recommendation

| Item | Classification |
|---|---|
| One execution owner/worker per database; stop API before CLI investigation/evaluation | **ACCEPTABLE LIMITATION**, freshly verified and fenced. Multi-worker capability is not required. |
| Trusted application/schema-owner SQL and physical chunk remapping on unchanged-source reindex | **ACCEPTABLE LIMITATION with explicit claim qualification**; stronger tamper/physical-immutability guarantees are not certified. |
| Unfenced control-plane requests with lease/outbox recovery delays | **ACCEPTABLE LIMITATION**, reproduced as recoverable without stale execution. |
| Server-side partition/keepalive delay; writes already fenced before loss commit before takeover | **ACCEPTABLE LIMITATION**. No new owner overlaps the held lock; accepted writes are ordered before epoch transfer. |
| Historical citations stored as snapshots rather than old full document revisions | **ACCEPTABLE LIMITATION**. Do not promise historical whole-document retrieval. |
| Conservative residual health defaults, shared OS user for MCP, historical expired tokens | **ACCEPTABLE documented local limitations**. Tokens were not recounted/sanitized in the development DB here. |
| Exclusive Python/E2E test DB, additive evaluation writes to dev DB | **ACCEPTABLE documented operating restrictions**. No evaluation or dev mutation occurred in this audit. |
| Unseen scenarios, partial raw-plan metric, model diagnosis weakness, terminal/checkpoint retention | **PHASE C1**; no new release prerequisite. |

**Release blockers: none verified within the supported local application operating contract.** No new source correction is independently justified for the original N1/N2 failures: both are closed. The observed database/representation exceptions above prevent an unqualified broader certification and must not be hidden behind the passing tests.

**Recommendation: sign off Phase C0 and proceed with the local-first experimental v0.2.1 release, conditionally on accurately scoped claims.** Publish serialized/version-hash-pinned logical document retrieval, snapshot citations, and epoch-fenced normal execution with trusted schema administration. Do not publish immutable-physical-chunk or application-owner-tamper-proof database claims. Keep the measured model weaknesses and known deployment restrictions explicit. No merge, tag or release was performed by this audit.
