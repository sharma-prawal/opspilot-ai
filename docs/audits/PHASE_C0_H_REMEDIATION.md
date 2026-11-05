# Phase C0-H — concurrency consistency and ownership fencing

**Input:** the third independent Codex verification of `b2a76d5` (verdict **FAIL**), preserved verbatim:
[`PHASE_C0_G_INDEPENDENT_VERIFICATION.md`](PHASE_C0_G_INDEPENDENT_VERIFICATION.md),
[`PHASE_C0_G_INDEPENDENT_EVIDENCE.json`](PHASE_C0_G_INDEPENDENT_EVIDENCE.json),
[`PHASE_C0_G_INDEPENDENT_REPRODUCERS.txt`](PHASE_C0_G_INDEPENDENT_REPRODUCERS.txt) (committed unmodified, `2116ef1`).
G1 and G2 passed; two release blockers remained:

- **N1 (High) → H2:** ownership lost during runtime initialization was forgotten; the runtime opened, executed an
  investigation and wrote checkpoints beside a replacement owner.
- **N2 (Medium) → H1:** overlapping ingestions of one source both committed different content as the same version;
  retrieval combined ranked text from one with expanded sections from the other, both "validated".

**Branch:** `hardening/phase-c0`. Nothing pushed, merged, tagged or published; no legacy-token sanitisation; no
development data deleted.

| Commit | Content |
|---|---|
| `1e28076` | H1 document revision consistency (migration 0007, serialized publication, revision pinning) |
| `5729dbb` | H2 runtime lifecycle and database-enforced owner fencing (migration 0008, checkpoint trigger, fenced runner/claim/tokens); tests that write checkpoints or execute actions now hold a real owner |
| `1635170` | H3 concurrency and fault-injection regression suites (21 tests); `release()` tolerates a dead lock session |
| `2116ef1` | the independent audit artifacts, unmodified |
| docs commit | this record, D60–D63, architecture/security/deployment docs, release notes, evaluation results |

## Original reproduction (before any change, at `b2a76d5`)

Programs extracted byte-for-byte from `PHASE_C0_G_INDEPENDENT_REPRODUCERS.txt` (output paths redirected to scratch).

| Program | Result at `b2a76d5` |
|---|---|
| `c0g_startup_loss` | old runtime: `held=false`, `lost_reason` "ownership connection failed: AdminShutdown", `suspended=null`, `admits_work=true`; **both** runtimes started an investigation that reached `awaiting_approval` with checkpoints written |
| `c0g_ingestion_race` | A and B both reported **version 2**; ranked `REVISIONA signal` and context `REVISIONB instructions`, both version 2, both `lifecycle_validated=true`, `warnings=[]` |

## H1 — immutable document revision consistency (N2)

**Exact sequence.** Ingest BASE (v1). Ingestions A and B of the same source both read the committed row (v1) in their
own short read transaction, then embed (gated, outside any transaction). A commits: `_store` overwrote the row with the
version computed from its earlier read (2) and replaced the chunks. Retrieval ranks A's symptom chunk (statement 1,
v2). B commits with the version it computed from *its* earlier read — also 2 — and replaces the chunks with B's. Expansion
(statement 2) selects chunks with `document_version = 2` and `documents.version = 2`: B's. Final revalidation
(statement 3) compares only `documents.version` with the passage version: 2 = 2 for both. Mixed result accepted.

**Root cause.** The revision number was not an identity: it was computed from an unlocked, possibly stale read and
written without compare-and-set, so different contents could commit under one version. Retrieval treated
`(document_id, version)` as identifying content.

**Existing tests that missed it.** The C0-G lifecycle tests changed lifecycle metadata or bumped versions from a
single writer; none ran two ingestions of the same source concurrently, and none compared content between ranked and
expanded passages.

**Consistency model.**
- A *revision* is `(documents.id, documents.version)`; its content hash is `documents.content_hash`.
- **Publication** (`IngestionService._publish`) takes `pg_advisory_xact_lock(0x4F50534B, hashtext(document_id))`,
  re-reads the committed row under the lock, and assigns `committed version + 1` when the content differs (same version
  for identical content, e.g. a re-index). It updates the row, deletes the previous chunks and inserts the new ones in the
  same transaction. **Linearization point:** that transaction's commit. Writers of one document are serialized; readers
  see either the previous or the new revision, never a mixture, in any single statement. Embedding happens before, with
  no transaction open; a writer whose "metadata only" decision went stale under the lock retries with embeddings (at most
  3 attempts).
- **Database invariants (migration 0007):** `UNIQUE (id, version)` on documents; deferred composite FK
  `chunks(document_id, document_version) → documents(id, version)` (checked at commit: every committed chunk belongs to
  its document's current revision); trigger `trg_kb_documents_revision_guard`: a content change must increase the
  version, and the version never decreases. These hold for any writer, not just the ingestion service.
- **Readers:** every passage carries its revision as `(document_version, metadata.document_hash)`. Expansion requires
  the anchor's exact revision on the rows it expands. Final revalidation keeps a passage only if the committed row has the
  same version **and** content hash; any change drops it (fail closed, with a warning). An explicit check refuses two
  revisions of one document in one response.
- **Validation → handoff.** The guarantee: every returned passage is a byte-identical copy (content + SHA-256) of a chunk
  of the revision that was the committed current revision at the final validation statement, and all passages of a
  document share that revision. Because a revision's chunks are immutable (any content change is a new version), text read
  in an earlier statement is that revision's text. Passages are handed over as value snapshots; nothing re-reads a chunk
  later, so a revision published after validation is later than the retrieval and cannot change what was returned. No
  lock or transaction spans ranking, reranking or inference.
- Lifecycle filtering, citation snapshots, embedding reuse (unchanged and metadata-only documents are not re-embedded)
  and INC-002 section coverage are unchanged.

**After (same program):** A = 2, **B = 3**; `results=[]`, `context=[]`; warnings "section expansion withheld: … v2 is no
longer the current active version" and "passage(s) changed lifecycle after ranking". A fresh search returns BRAVO only,
at v3.

**Tests** (`tests/integration/test_revision_consistency.py`, 9): the audit interleaving; three rounds of two concurrent
ingestions (distinct versions, final chunks one content); readers before/during/after a commit; metadata-only change
during a read (revision kept) and supersession during a read (excluded); failed ingestion (embedding error) and a
transaction failure after the chunk delete (wrong-dimension vectors) leave the previous revision intact; database
refusal of a content change without a new version, a backwards version, and a version bump that keeps old chunks
(deferred FK); historical citation still verifiable after two updates while current search returns v3 only; stale
metadata-only writer retried. Every response is checked passage by passage for content hash, revision and a single
revision per document.

**Remaining limitations.** Previous revisions' chunks are replaced, not archived: historical evidence is the citation
snapshot (D43), not stored old revisions. Ingestion of a document waits for a concurrent publication of the same
document (lock held only for the commit, not during embedding).

## H2 — ownership loss stops execution and persistence (N1)

**Exact sequence.** `AppRuntime.open` acquired the lock, then awaited gateway start-up. The owner session was terminated
during that await; the watchdog set `held=False` and called the loss callback, which suspended a runner only if
`holder["rt"]` existed — it did not yet — and the watchdog task ended. Initialization continued, constructed an
unsuspended runner and yielded it. `reserve`/`submit` checked `runner.suspended` only. Meanwhile a replacement acquired.
Both runtimes executed investigations and wrote checkpoints (LangGraph writes through its own pool, with no ownership
check at all).

**Root cause.** Ownership loss was an event delivered to whoever happened to be registered, not durable state; the
runtime never re-checked it before publishing the runner; and nothing at the persistence boundary could refuse a stale
owner's writes (the advisory lock is held by a different session than the one writing, and loss detection is
asynchronous).

**Existing tests that missed it.** The C0-G owner tests covered loss after the runtime was established and process-level
exclusion; none injected loss *during* initialization, and none counted checkpoint rows after a loss.

**Lifecycle (`ownership.RuntimeLifecycle`).** `INITIALIZING → ACQUIRING_OWNERSHIP → READY → OWNERSHIP_LOST → STOPPING →
STOPPED`; only `READY` admits or runs work; `OWNERSHIP_LOST` is sticky (never READY again). The transition is
synchronous: the state changes and listeners run before any `await` — the runner refuses admission and cancels every
segment (`suspend_now`), the API's maintenance sweep is cancelled — then the lock connection is closed and
`on_owner_lost` runs (the served API exits; CLI/evaluation runtimes refuse all further work). `READY` is entered only
after initialization completed *and* `ownership.verify()` re-proved the fence through an ordinary connection; loss at any
earlier point makes `AppRuntime.open` raise `OwnershipError`. The ownership-loss event is a structured log record
(`execution_owner_lost`, `runtime_state_changed`; a database event cannot be written when the database connection is the
thing that was lost).

**Fencing (migration 0008, `checkpointing.install_fencing`).**
- `ops.execution_owner(id=1, epoch, owner, owner_pid, acquired_at)`. Right after taking the advisory lock, a new owner runs
  `UPDATE … SET epoch = epoch + 1, owner_pid = pg_backend_pid()` on its lock session. Its fence is `(epoch, pid)`.
- `ops.execution_fence(epoch, pid)` (SECURITY DEFINER, EXECUTE revoked from PUBLIC; granted to the action role by
  `make db-roles`): `SELECT … FOR SHARE` on the epoch row; raises `OPF01` unless the epoch and pid are current **and**
  that pid still holds the advisory lock in this database.
- **Atomicity / no interleaving.** The check runs inside the writing transaction and its `FOR SHARE` lasts until commit.
  A new owner's epoch `UPDATE` therefore waits for every in-flight fenced write; once it commits, every later write of the
  old owner fails. A stale write is either ordered strictly before the new epoch or refused. Before any new owner exists,
  the old owner's writes already fail as soon as its lock session is gone (the pid check), without waiting for the
  watchdog.
- **Where it applies:** every LangGraph checkpoint write — a statement-level `BEFORE INSERT OR UPDATE OR DELETE` trigger on
  `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` reads the fence the pool connection was opened with
  (`-c opspilot.owner_epoch=… -c opspilot.owner_pid=…`); a connection without one cannot write checkpoints at all. The
  runner's lease claim/renewal and every persistence transaction (`_fence`), reconciliation's restoration/interrupt writes
  and finalization. The action server's execution claim: approval tokens are minted with the owner's epoch and pid, and the
  claim transaction calls the fence — a stale owner cannot start a new remediation, and tokens without an owner binding are
  refused.
- A refused write raises `StaleOwnerError` / is recognised by SQLSTATE `OPF01` and triggers the synchronous loss.
- The runtime refuses to start if the checkpoint triggers are missing (`make migrate` installs them). LangGraph itself is
  unchanged.

**After.** Exact `c0g_startup_loss`: the old runtime fails start-up, so the probe's assumption that both contexts open no
longer holds and it times out waiting (exit 1; log shows `acquiring_ownership → ownership_lost → stopping → stopped` for
the old runtime and `ready` at epoch 2 for the replacement). An outcome-recording copy (waits for either the old context or
its failure; otherwise identical) reports `simultaneous_runtime_contexts=false`, `old_startup_error` =
`OwnershipError('execution ownership lost during start-up: …')`, and only the replacement's investigation
(`awaiting_approval`, checkpoint written).

**Tests** (`tests/integration/test_owner_fencing.py`, 12; real PostgreSQL, one independent OS process): lifecycle
stickiness; the audit's start-up loss (old runtime never opens, replacement runs alone and checkpoints); READY last,
STOPPING/STOPPED on exit, epoch +1 on restart; loss before reconciliation (nothing written); *undetected* loss during
reconciliation (60 s watchdog; the restoration write is refused by the database and moves the runtime to OWNERSHIP_LOST);
undetected loss during agent execution (graph held in a model call; after release, checkpoint rows for the thread do not
grow, the run is suspended, the investigation is not advanced); checkpoint write immediately after loss rejected; unfenced
connection cannot write; an in-flight write blocks the new owner's epoch until it commits, and the next write fails;
stale-owner token refused by the action server (action not even claimed), current owner's token accepted; unbound token
refused; independent stale-owner process whose lock session was killed and replaced: its delayed checkpoint write is
refused. Existing `test_execution_owner.py` (contention, 6-way race, crash release, reload overlap, connection loss,
WEB_CONCURRENCY, launchers) passes unchanged.

**Process validation** (audit `c0g_process_checks`, real Uvicorn on `opspilot_test`): second API exits 3, one holder;
graceful shutdown 0 holders; SIGKILL then recovery serving with one holder; `--workers 2` one acquisition then refusal,
0 holders after; `WEB_CONCURRENCY=2` refused with no acquisition; reload changes the owner PID with one holder; final 0.

**Existing tests changed (invariant change):** tests that build their own checkpointer or mint tokens now hold a real
test-database owner (`owner` fixture, `owner_token` helper): `test_checkpoint_resume`, `test_resilience` (one test),
`test_prompt_injection`, `test_live_llm`, `test_action_enforcement`, `test_cancellation_races`. Without it their writes and
executions are correctly refused.

**Remaining race windows / limitations.**
- A fenced write that passed the fence just before the owner's lock session died may still commit afterwards; it is ordered
  before any new owner (standard fencing-token guarantee), and nothing later is accepted.
- Writes that are not fenced: operator API writes (start, cancel, decisions) from a process that has just lost ownership
  but not yet exited. They are compare-and-set protected (G2) and are not execution; the served API exits on detection.
- A network partition the server has not detected keeps the old lock session alive up to the keepalive window (~25 s); no
  new owner can be elected in that time, so there is no overlap.
- Multi-worker execution remains unsupported; the restriction is enforced (C0-G4) and now also fenced.

## Regression verification

Executed after the fixes (code at `1635170`/`2116ef1`, then docs only):

| Gate | Result |
|---|---|
| Audit `c0g_startup_loss` (exact) | old runtime never opens (log: `acquiring_ownership → ownership_lost → stopping → stopped`); probe exits 1 waiting for the context that no longer opens. Outcome-recording copy: exit 0, only the replacement investigates |
| Audit `c0g_ingestion_race` (exact) | exit 0; versions A 2, B 3; `results=[]`, `context=[]`, two warnings |
| Audit `c0g_process_checks` (exact) | exit 0; every case as expected (see H2) |
| Earlier reproducers (R1/R2/R3/R5) | R1 `verification_incomplete`, R2 `not_recovered`, R3 `cancelled` (`skipped_terminal=1`), R5 empty in memory and PostgreSQL |
| `make lint` | ruff, format, mypy `--strict`, import-linter 4/4, ESLint, tsc: clean |
| `make test` | **304 passed, 3 live skipped**; web unit **30 passed** |
| Integration + security, shuffled (seeds 11, 22, 137) | **153 passed, 3 skipped** in each order |
| `make doctor` | all checks pass, migrations head **0008** (applied to the dev DB with the API stopped, then `make db-roles`) |
| `make test-live` | 3 passed |
| `make e2e` | 4 passed, 3 screenshot specs skipped; dev-DB counts 132/130/121/112/692 identical before and after |
| `make evaluate` | below |

Not run concurrently: Python suites and E2E share `opspilot_test` (the owner lock now also enforces this).

### Evaluation (official, `datasets/evaluation/history/phase-c0h-2116ef1/`)

Run because the agent's persistence path changed (every checkpoint write and every remediation claim is now fenced, the
latter through the real MCP action role). Same models; dev API stopped; rows added to the dev DB (additive).

| Dimension | C0-G (`2d18d46`) | C0-H (`2116ef1`) |
|---|---|---|
| Final outcome correct | 13/13 | **13/13** |
| Executed plan acceptable | 13/13 | 13/13 |
| Model's own plan acceptable (partial pattern conformance) | 3/12 | 3/12 |
| Root cause | 7/9 | 7/9 |
| Verified recovery | 6/6 | 6/6 (`VERIFIED`) |
| Policy interventions (unsafe proposals) | 11 (1) | 11 (1) |
| Unsafe / forbidden / unauthorised executions | 0 / 0 / 0 | 0 / 0 / 0 |
| Citation validity | 1.0 | 1.0 |
| Mean / max seconds per run | 34.0 / 44.8 | 37.4 / 47.9 |

INC-002 still receives the current pool runbook's 4 further sections in both runs; no fence refusal occurred anywhere in
the run (no `execution fence` message in the log). Retrieval and agent-path benchmarks: identical metrics to C0-G.

**Latency.** The fence costs ≈ 0.07 ms per fenced statement over a plain round trip (500-call measurement: 0.286 vs
0.213 ms), i.e. well under 0.1 s per investigation. The +3.4 s difference is in the model-bound phase (mean time to the
approval pause 32.9 → 36.3 s) and within the run-to-run variation seen across phases (C0-F 34.8, C0-G 34.0); it is not
attributed to fencing.

### Resource impact

One `ops.execution_fence` call per fenced statement/transaction (checkpoint statements, runner persistence, lease
renewals every `run_lease_seconds/3`, one per remediation claim); one advisory transaction lock per document publication;
two extra columns compared in retrieval revalidation. No new connections or processes beyond C0-G.
