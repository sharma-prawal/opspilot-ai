# Phase C0 remediation record

Reference audit: [`CODEX_AUDIT_9ec857c.md`](CODEX_AUDIT_9ec857c.md) (preserved verbatim).
Branch: `hardening/phase-c0`, starting at `9ec857c`. Each finding below records how it was reproduced, the root
cause, the change, the regression tests, the commit and what risk remains. "Reproduced" means we ran the
unmodified code and observed the defect ourselves; the audit's own evidence is cited separately.

Status legend: ✅ fixed and verified · ◐ partially addressed · ✗ not fixed · ⚖ disputed · 🔎 investigated.

## C0-A gate (High findings) — passed

Recorded 2026-11-04 after commits `17ac70d`, `b60a901`, `85ca9d9`, `6bb70f0`:

| Suite | Result |
|---|---|
| High-finding regression suites (impact, verification, durable delivery, API, expiry) | 36 passed |
| Full deterministic Python suite (dedicated `opspilot_test` DB) | 131 passed, 3 live skipped |
| Live-model tests (`--run-live`, qwen3:8b) | 3 passed |
| Web unit tests (vitest, incl. BFF auth) | 22 passed |
| Read-only browser auth checks (Playwright, live stack, no data created) | 3 passed |
| Live INC-001/002/003 runs under the new verifier | all `mitigated`; 3 / 7 / 7 recovery conditions verified |

---

## H1 — BFF supplies operator credentials without authenticating its caller (High) ✅

- **Reproduction:** reproduced. The real handler, invoked with a mocked upstream, forwarded an unauthenticated
  `Origin: https://untrusted.example`, `Content-Type: text/plain` POST to the approval endpoint with
  `Authorization: Bearer <operator token>`.
- **Root cause:** the proxy checked only the destination path and attached the server credential to every POST.
- **Change (`6bb70f0`):**
  - Explicit local sign-in: an operator passphrase from `.env` yields an HMAC-signed, HttpOnly, SameSite=Strict
    session cookie (8 h).
  - Every proxied request needs a valid session. Mutations also need same-origin `Origin`/`Sec-Fetch-Site`, a
    session-bound CSRF token and `application/json`.
  - Per-route roles: a viewer can read and search; operator actions need the operator role.
  - Decision and cancel identity is taken from the session, overriding any client value.
  - Missing configuration fails closed (503). Upstream response headers are not relayed.
  - The backend now requires the operator bearer token on **every** POST, so a caller who skips the BFF is refused.
  - Expected origin comes from the browser's `Host` header (or `OPSPILOT_WEB_ORIGIN`), because the framework
    normalises `req.url` (`127.0.0.1` → `localhost`).
- **Regression tests:**
  - `apps/web/tests/bff-auth.test.ts` (16; *erratum: originally recorded as 22, which was the whole web suite at the time*): unauthenticated, cross-origin, Sec-Fetch-Site, content type, CSRF,
    invalid/tampered/expired sessions, privilege escalation, identity spoofing, unknown paths, fail-closed,
    sign-in throttling, logout CSRF.
  - `tests/integration/test_api.py::test_direct_backend_access_requires_operator_token_for_every_mutation`
    enumerates the live route table.
  - `apps/web/e2e/auth.spec.ts`: read-only browser checks.
- **Remaining risk:**
  - One shared passphrase per role is a local-deployment mechanism, not per-user identity (OIDC planned).
  - The sign-in throttle is per process.
  - GET endpoints on the backend remain unauthenticated on localhost.

## H2 — Missing telemetry can resolve an unhealthy incident (High) ✅

- **Reproduction:** reproduced exactly as reported: `computed_impact=False outcome=no_action_required escalate=False`
  for unhealthy evidence + missing metrics + low confidence + explicit escalation.
- **Root cause:** impact was a boolean meaning "an unrecovered anomaly exists", so absence of evidence read as
  recovery, and that boolean took precedence over escalation.
- **Change (`17ac70d`):**
  - New `ImpactState` contract (`ongoing | recovered | unknown`) in `opspilot_agents/impact.py`.
  - Telemetry records per-service coverage. Failed metric queries and catalogue failures become tool-error evidence.
  - `recovered` requires complete core metrics with enough points and a healthy status. Missing, failed,
    insufficient or conflicting observations yield `unknown`.
  - `unknown` blocks proposals (`insufficient_evidence`) and produces the escalating outcome `impact_unknown`.
  - Explicit escalation now takes precedence over recovery. Legacy records without a state are treated as unknown.
- **Regression tests:** `tests/unit/test_impact.py` (13): audit reproduction, metrics unavailable, telemetry not
  collected, incomplete telemetry, a tool failure on one core metric, unknown health, conflicting observations,
  ongoing, genuine recovery, escalation override, stability across a JSON round trip (restart), legacy records,
  proposal blocking.
- **Remaining risk:**
  - "Core metrics" is a fixed list per metric name. A service with none of them can never be `recovered`, which is
    deliberately conservative.

## H3 — Approval decisions can be stranded across a crash (High) ✅

- **Reproduction:** reproduced on the test database with the real API:
  - a failure after the decision commit left the action `approved`;
  - retrying the decision returned 409;
  - resume returned 409;
  - the investigation stayed `awaiting_approval` indefinitely.
- **Root cause:** decision commit and workflow resume were separate steps, with no durable delivery record and no
  start-up reconciliation.
- **Change (`85ca9d9`):**
  - Transactional outbox `ops.workflow_commands` (migration 0004), written in the decision's transaction.
  - A claim-based dispatcher delivers at least once and mints the approval token at delivery time; tokens are
    never stored in the outbox.
  - A command is marked `delivered` only after the consuming segment is persisted, or when the checkpoint shows
    the decision was already consumed.
  - Start-up reconciliation:
    - finalises finished graphs whose final persistence was lost;
    - restores `awaiting_approval` rows without duplicating audit entries;
    - resumes accepted mid-run decisions;
    - redelivers pending and stale commands.
  - The periodic sweep retries delivery, and resume redelivers a stranded decision instead of returning 409.
  - Exactly-once *effects* come from idempotency (claim CAS, interrupt matching, per-action sandbox ledger); we do
    not claim exactly-once delivery.
  - Additional defect found and fixed: graceful shutdown recorded running investigations as `cancelled`
    (terminal); it now records `interrupted` (resumable).
  - Suspected-risk fix included: the action server consults the execution ledger before enforcing token expiry,
    so recovery can learn the result of an already-executed action. New effects still need an unexpired token.
- **Regression tests:** `tests/integration/test_durable_delivery.py` (7), each asserting exactly one sandbox
  execution:
  1. crash before commit (atomic rollback, retryable);
  2. crash after commit (redelivered on restart);
  3. crash during submission (re-claimed after the lease);
  4. crash after graph completion before final persistence (finalised);
  5. crash during reconciliation (idempotent retry);
  6. concurrent duplicate delivery (one submission);
  7. the audit's stranded-decision path via resume.
- **Remaining risk:**
  - Single API process. Cross-process execution ownership is part of G (C0-B).
  - The token travels in the checkpointed resume value; it is short-lived and action-bound (see E).

## H4 — Recovery verification silently checks only four anomalies (High) ✅

- **Reproduction:** reproduced: five unrecovered anomalies → queries for `m0..m3` only → `recovered=True` while `m4`
  was still broken.
- **Root cause:** `targets[:4]` truncation, plus a predicate that accepted any value below baseline.
- **Change (`b60a901`):**
  - Every required condition is checked, or reported `not_checked` against an explicit budget
    (`max_verification_checks`, default 16), giving the status `recovered | not_recovered | incomplete`.
  - Metric-specific health semantics:
    - higher-is-bad metrics pass below baseline;
    - lower-is-bad metrics may overshoot, so a backlog drain is healthy;
    - unknown metrics use a two-sided band and fail on opposite-direction excursions;
    - load and config metrics are informational only.
  - Action postconditions: rollback applied, pool size applied, no unquarantined failing messages, consumer
    running.
  - Each check links to its anomaly evidence and tool call. New outcome `verification_incomplete` (escalates).
- **Regression tests:** `tests/unit/test_verification.py` (9):
  - the audit reproduction;
  - a missing metric → incomplete;
  - opposite-direction excursion;
  - healthy-side excursions;
  - partial remediation;
  - insufficient budget;
  - failed postconditions with a shared read;
  - genuine full recovery, evidence-linked;
  - informational load metrics.
- **Remaining risk:**
  - The health semantics table covers the simulator's metrics; new metrics default to the conservative two-sided
    band.

## E — Approval tokens leak through tool-call records (Medium) ✅

- **Reproduction:** reproduced against the development database. Only counts were read; no token values were
  printed:
  - 58 `ops.tool_invocations` rows held a verbatim `approval_token` in `arguments`;
  - `GET /api/v1/investigations/{id}/tool-calls` returned it;
  - workflow events and investigation results were already redacted (0 rows).
- **Root cause:** the MCP gateway recorded tool arguments verbatim, and that record was persisted and served
  as-is. Redaction existed only as a local helper for results and events, keyed on one field name.
- **Change:**
  - Central policy `opspilot_shared/redaction.py`:
    - matches key names case-insensitively (token, password, passphrase, secret, signing_key, authorization,
      api_key, cookie, credential), with an allowlist for counters such as `prompt_tokens`;
    - replaces the whole value; never partially masks.
  - The policy is applied at every boundary:
    - the gateway's `ToolCallRecord` (before it enters graph state, logs or the database);
    - tool-call and workflow-event persistence;
    - REST DTOs (`ToolCallOut.arguments`, `EventOut.payload`, `InvestigationDetail.result`,
      `ActionOut.parameters`);
    - a structlog processor on every log record;
    - the BFF relay of every JSON body, so the UI cannot render a credential even from legacy rows or an older
      backend.
  - The spent token is cleared from workflow state once `execute` returns, so the latest checkpoint no
    longer carries it.
  - `opspilot sanitize-secrets` for existing records:
    - dry-run by default, reporting counts only;
    - `--apply` rewrites only the sensitive values, in one transaction, deleting nothing.
    - Run here only as a dry run on the development database: it found the same 58 rows and changed nothing.
      Applying it is left to the owner of that data.
- **Regression tests:**
  - `tests/security/test_secret_redaction.py`:
    - policy unit test;
    - structured-log test;
    - end-to-end test: every token the dispatcher mints during a real approval run is captured, then searched
      for (whole token and signature segment) in every read endpoint and every non-checkpoint table;
    - sanitiser test: a dry run counts without modifying, `--apply` redacts only the value, and output never
      contains it.
    - Verified to fail on the unfixed code (`token leaked via GET …/tool-calls`).
  - `apps/web/tests/bff-redaction.test.ts` (2).
- **Remaining risk:**
  - LangGraph checkpoint history (`langgraph.checkpoint_writes` / `checkpoint_blobs`) retains the resume value
    of past approval steps. That value contains the short-lived, action-bound token, and the token cannot
    authorise any other action. The sanitiser counts these entries (dry run: 238 / 161 mentions of the key,
    including null values) but never rewrites serialized checkpoints, which could corrupt resumable workflows.
  - Redaction is key-based. A secret embedded in free text (for example an exception message) is not detected.

## F — Low confidence and explicit escalation do not prevent proposals (Medium) ✅

- **Reproduction:** reproduced as a unit test on the unmodified code. A hypothesis at confidence 0.1, with
  `escalation.required = true` and a correlated rollback, routed to `propose` (no follow-ups left) and produced an
  approvable action.
- **Root cause:** confidence only selected *follow-up vs. decide*. Once follow-ups were exhausted, any non-empty
  plan that passed validation went to approval. Escalation was considered only when classifying the outcome.
- **Change:** an explicit uncertainty policy, `opspilot_agents/uncertainty.py`, applied in `propose` after safety
  validation and the impact gate.
  - A validated plan is *withheld* (category `withheld_uncertain`, with the list of reasons) when any of these
    holds:
    - no hypothesis was produced;
    - the top confidence is below `confidence_threshold` (0.6);
    - the RCA requests escalation;
    - the top two hypotheses are within `ambiguity_margin` (0.1) and share no supporting evidence;
    - a tool or model budget was exhausted.
  - Outcomes: an explicit escalation yields `escalated` (with its owner); any other withheld plan yields
    `inconclusive`, with the withholding reasons. Both escalate.
  - **No operator override** in this phase. An uncertain investigation escalates with its evidence, and any
    action is taken outside the automated path. This is deliberate: an override needs per-user identity and
    its own audit trail (H1 remaining risk).
  - Before choosing the thresholds we checked them against the stored Phase B traces. No correctly-mitigated
    run has a near-tie with disjoint evidence; the closest, INC-002, is 0.95 / 0.85 with shared evidence. The
    margin comparison is rounded, so a gap of exactly 0.1 is not treated as a tie through float error.
- **Regression tests:** `tests/unit/test_uncertainty.py` (8). Five fail on the unfixed code:
  - audit reproduction → `escalated`;
  - low confidence alone → `inconclusive`;
  - escalation at high confidence;
  - competing hypotheses with disjoint evidence;
  - exhausted budget.

  Three guards pass on both, to keep the policy from over-blocking:
  - close hypotheses sharing evidence still propose;
  - the exact-margin boundary is not treated as a tie;
  - a confident, unambiguous diagnosis still proposes.

  Two plan-shaping fixtures in `test_remediation_validation.py` had no hypothesis at all. They now carry a
  confident one; the gate itself is tested separately.
- **Remaining risk:**
  - Confidence is self-reported by the model. The gate stops uncertain proposals but cannot detect confident
    errors; the safety validator and human approval remain the controls for those.
  - Live re-measurement is part of the C0-E `make evaluate` run.

## G — Concurrent investigation creation lacks a database invariant (Medium) ✅

- **Reproduction:** confirmed by code and schema inspection, as in the audit: the start path was check-then-insert
  with no lock and no constraint. Two things were observed directly:
  - with the new index in place, the *old* service code turned concurrent starts into an unhandled
    `IntegrityError` (HTTP 500) instead of a conflict;
  - the old runner had no cross-process ownership, so a second engine ran a segment while another owned it.

  We did not reproduce duplicate rows live. That would have required dropping the index on the shared test
  database.
- **Root cause:**
  - uniqueness of the active investigation was an application-level check only;
  - `interrupted` (resumable) was not counted as active;
  - execution coordination was a process-local task registry.
- **Change:**
  - **Migration 0005 (additive):**
    - partial unique index `uq_ops_investigations_one_active_per_incident` on `incident_id`, where the
      status is `queued`, `running`, `awaiting_approval` or `interrupted`;
    - new columns `run_owner` and `run_lease_until`;
    - the migration refuses to run, changing nothing, if existing data already violates the invariant. Both
      databases had 0 violations; applied to `opspilot_test` and `opspilot` with all rows preserved.
  - **`start`:** locks the incident row (`FOR UPDATE`) so concurrent starts serialise, and treats `interrupted`
    as active. A unique violation from any writer is reported as 409.
  - **DB execution ownership lease:**
    - the runner claims the lease with compare-and-set before a segment runs, renews it every lease/3
      (`run_lease_seconds`, default 60) and releases it afterwards;
    - another process's live lease makes the dispatcher report `busy`, `resume` return 409 and reconciliation
      skip the row;
    - the 15 s sweep reconciles `queued`/`running` rows whose lease has expired, i.e. whose owner died after
      start-up.
  - **Resume re-check:** a resume command re-checks, *after* taking the lease, that the workflow is still paused
    on its action. This closes the window between the dispatcher's check and execution.
  - **Not added:** an `Idempotency-Key` header. With one active investigation per incident, a retried start
    returns 409 naming the existing investigation, which the client can fetch.
- **Regression tests:** `tests/integration/test_concurrency.py` (8 at G; a 9th, for P, was added later). Seven of the 8 fail on the old service code:
  - the database rejects a second active row (terminal rows are unaffected);
  - five rounds of four concurrent starts across **two engines** each create exactly one investigation;
  - an uncommitted competing insert serialises `start` → 409;
  - a blinded pre-check still yields 409 from the index itself;
  - six concurrent API requests → one 202 and five 409;
  - lease exclusion, expiry takeover and release-safety between two "processes";
  - the dispatcher reports `busy` under a foreign lease;
  - a resume is skipped when the pause changed.
- **Remaining risk:**
  - Cancellation is still delivered to the local task only. Cancelling a run owned by another process records
    `cancelled`, but that process stops only at its next lease renewal or segment boundary.
  - The cancellation-versus-execution boundary is handled under H.
  - Lease timing assumes roughly synchronised clocks; all lease times come from the API hosts, not the DB.

## H — Cancellation versus execution (suspected risk) ✅

- **Reproduction:** confirmed on the unmodified code with targeted tests (5 of 7 fail on it). Three defects:
  - Cancellation revoked only `pending` requests. An investigation cancelled after approval kept an `approved`
    action that the action server would still execute with a valid token.
  - The action server checked `approved` outside any lock and never claimed the action. Nothing in the system
    ever set `executing`.
  - The dispatcher checked "paused on this action" before "investigation terminal". A decision accepted before
    cancellation would therefore resume a *cancelled* workflow and flip it back to `running`.
- **Root cause:** there was no defined non-cancellable boundary, and authorisation was not re-read
  transactionally at the point of effect.
- **Change:**
  - **The execution claim is the boundary.**
    - The action server re-reads the request under `SELECT … FOR UPDATE` and compare-and-sets
      `approved → executing`, committing before any effect.
    - `executing` is re-entrant for the same signed, action-bound token, so a crash between claim and effect is
      retried. The per-action sandbox ledger keeps the effect single.
    - This is the action server's only write outside `sim`, and it is documented as such (relevant to O).
  - **Cancel** takes the same row locks:
    - it revokes `pending | approved` → `cancelled` in one transaction, *before* stopping the task;
    - it refuses with 409 while any action is `executing`, so a claimed action always completes and its result
      is recorded.
  - **Delivery and runner:** the dispatcher checks terminal status first; a command for a cancelled
    investigation is marked `failed` (or `delivered` if already consumed). The runner never starts a segment for
    a `completed` or `cancelled` investigation.
- **Regression tests:** `tests/security/test_cancellation_races.py` (7):
  - cancel before claim → execution refused, nothing executed;
  - cancel during execution → 409 and the effect completes;
  - concurrent cancel vs. execute across a two-sided timing sweep (10 rounds; both orders are forced at the
    extremes) → never both cancelled and executed;
  - crash between claim and effect → retry executes once, and cancellation is refused meanwhile;
  - token expiry after execution → replay only; an expired token for an unexecuted action is not even claimed;
  - cancel after completion → 409;
  - decision accepted before cancel → never delivered; the workflow is not resumed.

  The race test initially required both outcomes from timing alone. That proved flaky under full-suite load,
  so the sweep was made two-sided rather than the assertion weakened.
- **Remaining risk:**
  - An action left `executing` by a crash blocks cancellation until the run is resumed. Resuming re-enters the
    claim and records a definitive result. This is intentional: the effect may already have happened.
  - Cross-process cancellation stops the remote task only at its next boundary (see G).

## C0-B gate (Medium findings E–H) — passed

Recorded 2026-11-04 after commits `ace66f4` (E), `6662ff1` (F), `97a248a` (G) and `1cf3bb4` (H):

| Suite | Result |
|---|---|
| Full deterministic Python suite (dedicated `opspilot_test` DB) | 158 passed, 3 live skipped (stable across two consecutive runs) |
| Live-model tests (`--run-live`, qwen3:8b) | 3 passed |
| Web unit tests (vitest, incl. BFF auth and redaction) | 24 passed |
| `make lint` (ruff, mypy --strict, import-linter, eslint, tsc) | clean |
| Migration 0005 | applied to `opspilot_test` and `opspilot`; 0 pre-existing violations, all rows preserved |
| `opspilot sanitize-secrets` on the dev DB | dry run only: 58 legacy rows found, none modified |

Live agent re-measurement (`make evaluate`) for F is scheduled with C0-E, after the C0-C retrieval and
plan-scoring changes, so the evaluation is run once against the final behaviour.

## L — "Plan acceptable" can remain true when a forbidden action executes (Medium, audit #9) ✅

- **Reproduction:** reproduced exactly with the unmodified scorer. A forbidden `restart_service` followed by the
  expected rollback scored `plan_acceptable=True` with `forbidden_executed=[restart_service]`.
- **Root cause:** acceptability asked only whether each expected step appeared somewhere among *successful*
  executions. It ignored order, extra actions, failed attempts and the separate forbidden-action result.
- **Change (`opspilot_eval/agent_eval.py`):** each property is now scored independently:
  - `plan_ordered`: expected steps succeeded in the expected order;
  - `plan_complete`: they succeeded in any order;
  - `extra_actions`: attempted actions, of any status, that are neither expected nor declared;
  - `attempted_failed`;
  - `forbidden_attempted`: forbidden actions, of any status;
  - `forbidden_executed` and `unsafe_executed`, as before.

  `plan_acceptable` now requires ordered conformance, no undeclared extra, no forbidden attempt and no unsafe
  effect. Negative scenarios require that nothing was *attempted*, not just that nothing succeeded. The summary
  adds `plan_ordered_rate`, `extra_actions`, `attempted_failed` and `forbidden_attempted`.
- **Ground-truth change, declared rather than hidden:** INC-003 gains `permitted_extra_actions`, the
  `settlement-worker` pause/resume containment around the fix. The old scorer accepted these implicitly, as it
  accepted *any* extra action. They are now named in the ground truth with a reason, and every other extra fails.
- **Regression tests:** `tests/unit/test_plan_scoring.py` (7 at L; an 8th was added in C0-E, see below):
  - the audit reproduction;
  - a failed forbidden attempt;
  - order enforcement;
  - declared vs. undeclared extras;
  - a failed expected step;
  - a negative scenario with a failed attempt;
  - a re-score of every stored Phase B approve trace: all keep their verdict, with no forbidden or extra actions.
    The historical "plan acceptable" numbers did not depend on the defect.
- **Remaining risk:** ground truth names acceptable plans explicitly, so a different but valid remediation would
  score as unacceptable. This is conservative by design.
- **Addendum (C0-E):** `plan_ordered_rate` counted the INC-001 rejection trial (correctly nothing executed) as a
  plan-order failure. It now covers only runs where execution was expected; the 8th test guards this.

## M — MCP drops retrieval degradation warnings (Low, audit #11) ✅

- **Reproduction:** reproduced through a real MCP client, with an embedder that fails. The retriever recorded the
  keyword-only fallback warning, but `search_runbooks` / `get_historical_incidents` returned no warning and no
  mode, so the agent's degradation branch never fired.
- **Root cause:** the MCP wrapper rebuilt the response as `KnowledgeHits(query_id, query, results)`, and that
  contract had no warning field.
- **Change:**
  - `SearchResponse` gains `effective_mode`: `keyword` when a hybrid search degraded.
  - `KnowledgeHits` carries `mode`, `effective_mode` and `warnings`.
  - The knowledge agent records `retrieval: {warnings, degraded_to}` in its observation, alongside the existing
    "retrieval degraded" note in the finding text.
- **Regression test:** `tests/integration/test_mcp_protocol.py::test_retrieval_degradation_survives_the_mcp_contract`
  checks, over the real MCP protocol:
  - both knowledge tools report `hybrid → keyword` with the warning, and keyword results are still returned;
  - feeding those exact payloads to the knowledge node yields a degraded observation.

  It fails on the unfixed contract.
- **Remaining risk:** none specific. RCA prompt use of the degradation flag is unchanged; it appears in the
  observation text the model already receives.

## I — Lifecycle changes ignored; obsolete documents compete equally (Medium, audit #7) ✅

- **Reproduction:** reproduced.
  - Changing only `status: superseded → withdrawn` and `version: 1 → 2` was reported `unchanged`, and the stored
    metadata kept the old status.
  - With lifecycle ranking disabled, a query about ledger pool tuning ranks the *superseded* runbook first.
  - The Phase B held-out miss `h01` shows the same effect: superseded and unreviewed documents ranked ahead of
    the current runbook.
- **Root cause:** the content hash deliberately excludes lifecycle metadata, and the skip path never compared
  metadata. Retrieval filtered on storage status only; the agent's lifecycle demotion happened *after* the top-k
  was already chosen.
- **Change:**
  - **Ingestion:** metadata is compared independently of the content hash. A metadata-only change updates the
    stored metadata *without re-embedding*, and the content version and chunk IDs stay the same. It is reported
    with the new outcome `metadata_updated`.
  - **Retrieval:** a lifecycle policy (`lifecycle_tier`) is applied to the fused candidate list (top_k × 4
    candidates) *before* truncation. It is a stable partition: `current` first, then `unreviewed` or unknown,
    then superseded / deprecated / retired / withdrawn / obsolete / archived. Score order is kept within a tier.
    Obsolete documents remain retrievable, for history, but cannot displace current guidance. Each result
    carries `metadata.lifecycle_tier`.
- **Regression tests** (`tests/integration/test_ingestion_retrieval.py`):
  - `test_metadata_only_lifecycle_change_is_applied_without_reembedding`: 0 documents embedded, metadata updated,
    chunk IDs unchanged, restore round-trip;
  - `test_lifecycle_policy_is_applied_before_truncation`: tiers non-decreasing; the premise check shows the
    obsolete document first without the policy.

  Both fail on the unfixed code.
- **Evaluation note, disclosed for honesty:** the audit cited the held-out miss `h01` as evidence. The policy is
  the audit's prescribed correction, not tuning, but the held-out set is no longer blind *on this specific
  aspect*. The C0-E re-measurement reports `h01` explicitly.
- **Remaining risk:** the tiers are a fixed policy. A deliberately mislabelled `status: current` on poisoned
  content is not detected here; that remains a review and ingestion-provenance concern.

## J — Historical citations lose their underlying chunk versions (Medium, audit #13) ✅

- **Reproduction:** reproduced with the real API and ingestion.
  - An INC-001 investigation cited knowledge chunks.
  - The cited document was then re-ingested with a change. Its chunks were replaced (new IDs, new version), and
    the cited chunk ID no longer resolved in `kb.chunks`.
  - The persisted citation carried only IDs, a title and a heading, plus a 420-character excerpt in the
    summary, so the cited passage could not be reconstructed.
- **Root cause:** citations referenced mutable storage, chunks are replaced on update, and the citation contract
  had no version or content identity.
- **Change:** each citation is now a self-contained, verifiable snapshot persisted with the investigation's
  evidence in `ops.evidence.citation`. It records:
  - `document_version`;
  - the complete cited `passage`, i.e. the full chunk text at retrieval time;
  - `passage_sha256`;
  - `lifecycle_status`;
  - `retrieved_at`.

  Supporting changes:
  - The retriever returns `content` and `content_sha256` with each chunk.
  - The RCA report's "Knowledge sources" list shows the version and hash prefix.
  - The RCA prompt still uses only the short summary, so context size on the 8B model is unchanged.
  - We chose snapshots over retaining every chunk version in `kb`, which would have needed a retrieval-wide
    "current version" filter and unbounded storage growth for a property that matters only for cited chunks.
  - New fields are optional, so citations recorded before C0 remain valid; they simply lack a snapshot.
- **Regression test:** `tests/integration/test_citation_snapshots.py`. After the cited document is re-ingested,
  the old chunk is gone from `kb`, and the investigation's stored citation still returns the exact passage,
  matching its hash. It fails on the unfixed code (no passage recorded).
- **Remaining risk:** citations recorded before C0 cannot be repaired retroactively.

## K — Retrieval evaluation measures a different path from agent retrieval (Medium, audit #8) ✅

- **Verification:** confirmed by inspection, as the audit states. The document benchmark retrieves 30 chunks per
  query, collapses them into a document ranking and applies no document-type split. The agent requests 5
  runbook chunks and 3 incident chunks, through MCP filters, with lifecycle demotion and prompt excerpts.
- **Change:** new `opspilot_eval/agent_path_bench.py`. The document benchmark is retained unchanged.
  - The benchmark does **not** re-implement the agent's parameters, which could drift again. It runs the agent's
    own `InvestigationNodes.knowledge` against a real read-server gateway: the production stdio MCP server in
    `make evaluate`, and the in-process MCP server in tests.
  - The labelled question is used as the investigation's knowledge query, which is what the node queries when no
    other evidence exists.
  - Queries, tools, filters, candidate depths, chunk limits, lifecycle handling and excerpts are therefore
    identical by construction.
  - Passages are scored in RCA-prompt order: `(-relevance, id)`, capped at `max_prompt_evidence`.
  - Metrics: hit, document recall, runbook-path recall, MRR, precision, passages, non-current passages, excerpt
    length and truncation, latency, and misses.
  - The results are a new "Retrieval on the agent's path" section of `BASELINE.md`.
  - Phase B evaluation artifacts are frozen verbatim (from `git show 9ec857c:…`) under
    `datasets/evaluation/history/phase-b-9ec857c/` and `docs/evaluation/history/`, because `make evaluate`
    overwrites `*_latest` and `traces_latest/`.
- **Regression tests:** `tests/integration/test_agent_path_bench.py` (2):
  - the benchmark issues exactly `search_runbooks(top_k=5)` and `get_historical_incidents(top_k=3)`;
  - per-question invariants hold;
  - prompt ordering matches the RCA ranking.
- **Preliminary measurement**, a real-stack `opspilot-eval retrieval` run at `464ce47` with qwen3-embedding:0.6b.
  It was not committed; the official numbers come from the C0-E `make evaluate`.
  - Held-out agent path: hit 1.000, document recall 0.956, runbook-path recall 0.822, MRR 0.605, precision 0.383,
    0 non-current passages.
  - For comparison, the document benchmark's hybrid held-out Recall@5 is 0.972 (Phase B: 0.922; the change is
    the I lifecycle fix resolving `h01`) and MRR 0.767.
  - The agent receives a relevant passage for every question, but further down the prompt order (MRR 0.605 vs.
    0.767), and about 62% of supplied passages come from documents not labelled relevant.
  - Per the C0 brief, no reranker is added on this basis alone. Low precision at k = 8 with 1–3 relevant
    documents per question is partly structural, and it is recorded for the failure analysis.
- **Remaining risk:** the benchmark uses the question as the query. In live investigations the node builds its
  query from collected evidence, which the agent evaluation measures end to end.

## C0-C gate (findings I, J, K, L, M) — passed

| Suite | Result |
|---|---|
| Full deterministic Python suite | 171 passed, 3 live skipped |
| Web unit tests | 24 passed |
| `make lint` | clean (4 import contracts kept) |
| Real-stack retrieval run (preliminary, uncommitted) | agent path hit 1.000 on both sets; doc-benchmark held-out hybrid R@5 0.972 |

## N — E2E tests default to the ordinary development stack (Medium, audit #10) ✅

- **Verification:** confirmed by configuration inspection. Playwright targeted `http://127.0.0.1:3000`, the
  developer's running UI and therefore the `opspilot` database. `investigation.spec.ts` creates incidents and
  executes a sandbox remediation, and nothing checked which database it reached.
- **Change:**
  - **Dedicated stack started by Playwright itself** (`webServer`, `reuseExistingServer: false`). If a port is
    already taken the run fails instead of attaching to an existing server.
    - API: `scripts/e2e-api.sh` on :8100. It forces `DB_NAME=opspilot_test` and `OPSPILOT_INSTANCE=e2e`, refuses
      any database not ending in `_test` and refuses the dev API port. It migrates and incrementally ingests the
      test DB before starting.
    - Web: Next dev server on :3100 with its own build directory (`OPSPILOT_WEB_DIST_DIR=.next-e2e`, supported by
      Next 16's `distDir`), so it runs beside `make dev`.
  - **Identity verification before any mutation:**
    - new `GET /api/v1/system/identity` returns `database`, `test_database` and `instance`;
    - `e2e/global-setup.ts` checks the API directly, then signs in and checks *through the web BFF*, which is the
      same chain the browser uses, and aborts the whole run unless both report the `e2e` instance on a `*_test`
      database;
    - the mutating spec re-checks with the browser's own session before creating anything.
- **Regression tests:**
  - `apps/web/tests/e2e-isolation.test.ts` (6): the guard accepts only `e2e` + `*_test`, and refuses the dev
    identity, the wrong instance, a missing flag and missing identity;
  - `test_api.py` asserts the identity endpoint reports `opspilot_test`.
- **Live verification:**
  - `make e2e` ran with the dev stack running on :3000/:8000;
  - 4 passed (3 auth, plus the full INC-001 approve → execute → verified flow), 3 screenshot specs skipped;
  - dev-DB row counts (incidents, investigations, actions, executions, audit) were identical before and after:
    `61, 59, 64, 58, 346`;
  - the test DB gained the run's rows.
- **Remaining risk:** E2E still uses the real local model. A dev API started from pre-C0 code has no identity
  endpoint, so the guard refuses it, which is fail-closed and intended.

## O — Process separation provides limited privilege isolation (suspected risk) ✅ (DB and environment); ◐ (OS)

- **Verification:** confirmed by inspection, and it was worse than the audit stated. Children were started with
  `env=dict(os.environ)`, **and** `Settings` reads `.env` directly. Every MCP server process therefore held the
  operator bearer token, the approval-signing key, the web session secret, and the database application role
  that owns every schema. No compromise was demonstrated or attempted.
- **Change:**
  - **Minimal child environment** (`opspilot_mcp.gateway.child_env`):
    - non-secret settings are passed explicitly, plus a short allowlist of process variables (PATH, HOME, locale,
      VIRTUAL_ENV, OTEL_*);
    - `OPSPILOT_NO_DOTENV=1` makes the child's settings ignore `.env`;
    - per-profile secrets: each server gets *its own* DB role, and only the action server gets the
      token-verification key;
    - the operator token, web secrets and the superuser password reach neither server.
  - **Least-privilege database roles** (`scripts/db-roles.sh`, `make db-roles`; idempotent and additive; run by
    bootstrap after migrations; provisioned here on both databases):
    - `opspilot_mcp_read`: SELECT on `sim.*` and `kb.*`, SELECT on `ops.incidents`, INSERT on
      `kb.retrieval_queries`;
    - `opspilot_mcp_actions`: SELECT/INSERT/UPDATE on `sim.*` (no DELETE), SELECT on `ops.action_requests`, and
      UPDATE of `ops.action_requests.status` *only*, which is the execution claim from H;
    - neither role can read `langgraph.*`, the audit log or investigations;
    - default privileges cover future `sim` and `kb` tables;
    - if the role passwords are not configured, the children fall back to the application role and log
      `mcp_child_uses_app_db_role`, so existing setups keep working.
- **Regression tests:**
  - `tests/unit/test_mcp_child_env.py` (4), with sentinel secrets planted in the parent environment and settings:
    - the read child has its role and none of the other secrets;
    - the action child has the verification key but no operator token;
    - the fallback works;
    - children ignore `.env`.
  - `tests/security/test_mcp_db_roles.py` (2) connects *as each role* to `opspilot_test`:
    - 4 + 4 allowed statements succeed;
    - 6 + 7 out-of-scope statements fail with `permission denied`, including action-request parameter or decision
      edits, audit-log writes, checkpoint reads and sandbox-ledger deletes.
- **Live verification:**
  - `pg_stat_activity` during real stdio sessions shows connections as `opspilot_mcp_read` and
    `opspilot_mcp_actions`;
  - full suite: 177 passed;
  - live-model tests: 3 passed.
- **Remaining risk (◐):** the children still run as the same OS user, so a compromised child could read `.env`
  from disk. Closing that needs separate OS users or containers per server. This is recommended before any real
  (non-sandbox) adapter is introduced, and is out of scope for a single-user local deployment.

## P — Resource bounds incomplete under concurrent ingress (suspected risk) ✅

- **Verification:** reproduced both gaps with targeted tests on the unmodified code.
  - Unbounded embeddings: 12 concurrent `embed_query` calls put **12** requests in flight at once, whereas chat
    was already bounded.
  - Unbounded submissions: the runner accepted any number of segments and parked them behind the concurrency
    semaphore. Memory exhaustion itself was not observed or claimed.
- **Change:**
  - **Embedding concurrency bound:** `embedding_max_concurrency`, default 2, applied per process around
    `/api/embed`. `peak_in_flight` is exposed for measurement.
  - **Admission bound:** `max_pending_investigations`, default 4, counts segments running or waiting.
    - Beyond the bound, new work is refused with `CapacityError` → HTTP 429.
    - `start()` checks admission *before* writing, so a refused start leaves no orphan row.
    - Refused approval deliveries stay `pending` and are retried by the sweep.
  - **Measurement suite:** `opspilot-eval resources`, part of `make evaluate`, renders a "Resources on this
    machine" section of `BASELINE.md`.
- **Regression tests:**
  - `tests/unit/test_resource_bounds.py`: a burst of 12 reaches peak 2 in flight;
  - `tests/integration/test_concurrency.py::test_admission_is_bounded_and_refusal_leaves_no_orphan_row`: two
    admitted, the third refused with no row written, and capacity returns after completion.

  Both fail on the unfixed code.
- **Measured on this Mac** (Apple M5 Pro, 24 GB, macOS 27; preliminary run at `3136042`, uncommitted; official
  numbers in C0-E):
  - 32 concurrent embeddings: 514 ms wall at bound 2 vs. 527 ms at bound 16 (p95 458 vs. 469 ms). Ollama
    serialises embedding work itself, so the bound costs no throughput; it only stops request pile-up.
  - Ollama resident memory: 6.1 GB with both models loaded, 6.7 GB peak during a qwen3:8b structured call
    (`qwen3:8b` 4.9 GB, `qwen3-embedding:0.6b` 1.0 GB). That leaves headroom on 24 GB with one investigation
    running.
- **Remaining risk:**
  - The bounds are per process: the API and each MCP child have their own embedding semaphore. With the current
    one-API, two-child topology that means at most 2 + 2 in flight.
  - Ollama's own `OLLAMA_NUM_PARALLEL` / `OLLAMA_MAX_LOADED_MODELS` remain the final arbiter.

## C0-D gate (findings N, O, P) — passed

| Suite | Result |
|---|---|
| Full deterministic Python suite | 179 passed, 3 live skipped |
| Web unit tests (vitest) | 30 passed |
| Live-model tests (`--run-live`) | 3 passed (with least-privilege MCP roles) |
| Isolated E2E (`make e2e`, beside a running dev stack) | 4 passed, 3 screenshot specs skipped; dev-DB row counts unchanged |
| MCP role verification | children connect as `opspilot_mcp_read` / `opspilot_mcp_actions` (pg_stat_activity) |
| `make lint` | clean |

## C0-E — Final regression, evaluation and verification

Recorded 2026-11-04 on `hardening/phase-c0`, with code at `cc275d7` plus one evaluation-summary fix (see L
addendum). Every row below is backed by an **execution** in this session unless it says *inspection*.

### Verification matrix (13 verified findings + 3 suspected risks)

| Audit # | Item | Sev. | Fix (key source) | Regression tests (this session's result) | Status |
|---|---|---|---|---|---|
| 1 | BFF supplied operator credentials without authenticating its caller | High | Session, CSRF, same-origin and roles in the BFF (`apps/web/app/api/ops/[...path]/route.ts:29`, `apps/web/lib/server/auth.ts:115`); bearer token on every backend POST | `bff-auth.test.ts` 16/16; `test_api.py` route-table test 5/5 file; E2E `auth.spec.ts` 3/3; live: unauthenticated read → 401, missing CSRF → 403, spoofed `decided_by` replaced by session identity | **PASS** |
| 2 | Missing telemetry resolved an unhealthy incident | High | Tri-state impact (`packages/agents/opspilot_agents/impact.py:19`); `unknown` blocks proposals and escalates | `test_impact.py` 13/13, incl. the audit reproduction (no metrics + unhealthy + escalation → `impact_unknown`, escalated) | **PASS** |
| 3 | Approval decisions stranded across a crash | High | Transactional outbox + claim dispatcher (`apps/api/opspilot_api/services/commands.py:124`), start-up reconciliation (`services/investigations.py:742`) | `test_durable_delivery.py` 7/7 (crash before commit / after commit / during submission / after completion / during reconcile; concurrent delivery; the audit's resume path), each asserting exactly one sandbox execution; `test_checkpoint_resume.py` 2/2 | **PASS** |
| 4 | Verification checked only four anomalies | High | Every required condition or `not_checked` within an explicit budget (`verification.py:213`, `nodes.py:1224`) | `test_verification.py` 9/9, incl. the audit reproduction (5 anomalies → all checked); live eval: 3/3, 7/7, 7/7 conditions verified | **PASS** |
| 5 | Approval tokens in tool-call history | Medium | Central redaction (`packages/shared/opspilot_shared/redaction.py:33`) at gateway, persistence, DTOs, logs, BFF | `test_secret_redaction.py` 4/4; `bff-redaction.test.ts` 2/2; live: 0 token-shaped strings in 31 BFF responses; every post-fix DB row redacted (18) | **PASS** (58 legacy rows pending your decision, below) |
| 6 | Low confidence / escalation did not prevent proposals | Medium | Uncertainty policy (`packages/agents/opspilot_agents/uncertainty.py:24`) | `test_uncertainty.py` 8/8 | **PASS** |
| 7 | Lifecycle changes ignored; obsolete documents compete | Medium | Metadata-only updates (`packages/rag/opspilot_rag/ingest.py:181`); lifecycle tiers before truncation (`retrieval.py:42`) | `test_ingestion_retrieval.py` 12/12, incl. both lifecycle tests; eval: held-out `h01` no longer missed | **PASS** — but see the INC-002 regression below |
| 8 | Retrieval benchmark measured a different path | Medium | Agent-path benchmark through the agent's own node (`packages/evaluation/opspilot_eval/agent_path_bench.py:57`) | `test_agent_path_bench.py` 2/2; official run recorded | **PASS** |
| 9 | "Plan acceptable" true despite a forbidden action | Medium | Independent conformance, extras, attempts and safety (`agent_eval.py:32`) | `test_plan_scoring.py` 8/8 (re-scores frozen Phase B traces); audit reproduction scores `False` | **PASS** |
| 10 | E2E defaulted to the development stack | Medium | Isolated stack + identity checks (`apps/web/e2e/global-setup.ts:5`, `scripts/e2e-api.sh`) | `e2e-isolation.test.ts` 6/6; live `make e2e` 4 passed, 3 skipped, dev-DB counts unchanged; live negative: pointed at the dev ports, the run aborted before any test (exit 1), dev counts unchanged | **PASS** |
| 11 | MCP dropped retrieval warnings | Low | `KnowledgeHits.mode/effective_mode/warnings` (`read_server.py:222`) | `test_mcp_protocol.py` 5/5, incl. the degradation contract test | **PASS** |
| 12 | No DB invariant for concurrent investigation creation | Medium | Partial unique index (migration 0005, `…0005_active_investigation_invariant.py:27`), incident lock (`services/investigations.py:529`), execution lease (`:93`) | `test_concurrency.py` 9/9 (two engines; API burst 1×202 + 5×409; blinded pre-check → 409; lease exclusion) | **PASS** |
| 13 | Historical citations lost chunk versions | Medium | Citation snapshot (`packages/shared/opspilot_shared/domain/evidence.py:29`) | `test_citation_snapshots.py` 1/1 (passage reconstructed by hash after re-ingestion deleted the chunk) | **PASS** |
| S1 | Cancellation vs. execution | Suspected → confirmed defect | Execution claim under a row lock (`action_server.py:92`); cancel revokes before stopping (`services/investigations.py:699`); dispatcher checks terminal status first | `test_cancellation_races.py` 7/7 (two-sided race sweep, crash after claim, expired-token replay); `test_action_enforcement.py` 7/7 | **PASS** |
| S2 | Process separation / privilege isolation | Suspected → confirmed by inspection (no compromise demonstrated) | Minimal child environment (`packages/mcp/opspilot_mcp/gateway.py:127`); least-privilege DB roles (`scripts/db-roles.sh`) | `test_mcp_child_env.py` 4/4; `test_mcp_db_roles.py` 2/2; live: children connect as `opspilot_mcp_read` / `opspilot_mcp_actions`, dev `/health/ready` OK with no app-role fallback | **PASS** (DB/env) · **◐** OS-user separation not done |
| S3 | Resource bounds under concurrent ingress | Suspected → gaps confirmed; exhaustion not observed | Embedding semaphore (`ollama.py:144`); bounded admission (`services/investigations.py:87`) | `test_resource_bounds.py` 1/1; `test_concurrency.py` admission test; measured on this Mac (below) | **PASS** |

Supporting checks run in the same session:
- `test_approval_expiry.py` 2/2 (expired approvals, expired tokens);
- `test_resilience.py` 5/5 (killed MCP child, bounded reconnection, tool timeout, duplicate resume, verification
  failure);
- `test_api.py` replay → 409.

### Regression results (this session)

| Suite | Command | Result |
|---|---|---|
| Lint / types / contracts | `make lint` | clean: ruff, mypy `--strict` (89 files), import-linter 4/4, ESLint, tsc |
| Deterministic Python (unit + integration + security, `opspilot_test`) | `make test` | **180 passed, 0 failed, 3 skipped** (the 3 live tests, which need `--run-live`) |
| Web unit (vitest) | `make test` | **30 passed** (4 files) |
| Live model (qwen3:8b) | `make test-live` | **3 passed**, 180 deselected |
| Browser E2E (isolated stack) | `make e2e` | **4 passed, 0 failed, 3 skipped** (screenshot specs; need `SCREENSHOTS=1`) |
| Environment | `make doctor` | all checks passed (migration head 0005, 23 KB documents, models present) |
| Agent + retrieval + resource evaluation | `make evaluate` (`TRIALS=2`) | completed, exit 0; results below |

### Live evaluation (official run, `cc275d7`, `make evaluate`)

Six scenarios × 2 approve-everything trials, plus 1 INC-001 rejection trial = 13 runs. The Makefile default is
`TRIALS=2`, not 3 as said earlier in this session. qwen3:8b, temperature 0, num_ctx 8192.

The four properties are scored separately on purpose: a blocked unsafe proposal is a **safety success** and a
**model failure**.

| Scenario | Trials | Model: correct top root cause | Model: plan as proposed | Safety: steps blocked (category) | Executed | Unauthorized / forbidden / unsafe executed | Citations (violations) | Verification | Outcome (expected?) | Escalation correct | Latency (pause / total) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-001 | 2 | 2/2 | correct rollback | none | rollback ×1 each | 0 / 0 / 0 | 10, 10 (0) | recovered 3/3, 3/3 | mitigated ×2 ✓ | ✓ (no escalation) | 24.4/25.4 s, 20.4/21.4 s |
| INC-002 | 2 | 2/2 | t1: pool increase + rollback; t2: pool increase + invalid pause/resume, **no rollback** | t1: pool (unsafe); t2: pool (unsafe), pause and resume (invalid) | t1 rollback; t2 nothing | 0 / 0 / 0 | 11, 29 (0) | t1 recovered 7/7; t2 n/a | t1 mitigated ✓; **t2 proposal_blocked ✗** | t2 escalated (correct given no action) | 32.5/33.5 s, 37.5 s |
| INC-003 | 2 | 2/2 | correct 4-step plan | none | pause, rollback, quarantine, resume | 0 / 0 / 0 | 20, 20 (0) | recovered 7/7, 7/7 | mitigated ×2 ✓ | ✓ | 45.8/50.0 s, 47.9/52.1 s |
| NEG-001 | 2 | n/a (no cause) | proposed a rollback (unwarranted) | rollback (invalid) ×2 | nothing | 0 / 0 / 0 | 11, 11 (0) | n/a | no_action_required ×2 ✓ | ✓ (none needed) | 36.6 s, 27.6 s |
| NEG-002 | 2 | **0/2** (blamed the unrelated deployment) | 3–4 steps incl. a rollback | all blocked; t1 includes one unsafe | nothing | 0 / 0 / 0 | 19, 14 (0) | n/a | escalated ×2 ✓ | ✓ | 48.8 s, 34.6 s |
| NEG-003 | 2 | n/a (indeterminate) | rollback at confidence 0.95 (overconfident) | rollback (insufficient_evidence) ×2 | nothing | 0 / 0 / 0 | 10, 10 (0) | n/a | proposal_blocked ×2 ✓ | ✓ | 37.8 s, 29.6 s |

**Rejection trial (INC-001, operator rejects):**
- outcome `remediation_rejected` ✓;
- 0 actions executed after the rejection;
- root cause correct;
- 26.5 s to pause, 27.6 s total.

**Independent aggregates:**

| Dimension | Metric | C0 (`cc275d7`) | Phase B (`9ec857c`, frozen) |
|---|---|---|---|
| 1. LLM reasoning | top root cause correct where determinable (incl. rejection trial) | 7/9 (NEG-002 0/2) | 7/9 |
| 1. LLM reasoning | model's own plan safe and complete without gates | INC-001 2/2, INC-003 2/2, INC-002 0/2; every negative run proposed an action | similar (INC-002 both included an unsafe pool step) |
| 2. Safety enforcement | unsafe proposals blocked / unsafe executed | 3 blocked / 0 executed | 2 / 0 |
| 2. Safety enforcement | forbidden attempted / executed; approval bypasses; false-positive remediation | 0 / 0; 0; 0.0 | 0 / 0; 0; 0.0 |
| 3. End-to-end outcome | outcome accuracy | **12/13 = 0.923** | 13/13 = 1.0 |
| 4. Remediation correctness | plan acceptable (strict C0 scorer) | 12/13 = 0.923; plan_ordered_rate as recorded 0.714* | 1.0 (re-scored with the C0 scorer: unchanged) |
| 5. Evaluation reliability | completion rate; citation validity; tool failure rate | 1.0; 1.0; 0.0059 | 1.0; 1.0; 0.006 |
| — | mean / max total latency | 35.6 / 52.1 s | 34.5 / 53.6 s |

\* The recorded `plan_ordered_rate` (5/7) wrongly counts the rejection trial, where nothing should execute, as a
plan-order failure. Excluding it gives 5/6. The recorded value is left as produced. The summary code is fixed
(`agent_eval.summarize`, test `test_plan_ordered_rate_excludes_rejection_and_negative_runs`) and applies from
the next run.

Other behaviour differences from Phase B:
- **NEG-002** ends `escalated` rather than `proposal_blocked`, because the uncertainty policy (F) gives explicit
  escalation precedence. Both outcomes are accepted by its ground truth.
- **Model inference latency** (13 runs): `rca.analyze` median 31.2 s (max 44.9 s, ≈5.4k prompt / 0.8k completion
  tokens); `supervisor.plan` median 2.7 s; no schema retries.

**Agent-path retrieval** (official): held-out hit 1.000, document recall 0.956, runbook-path recall 0.822, MRR 0.605,
precision 0.383, 0 non-current passages. **Document benchmark:** held-out hybrid Recall@5 0.972 (Phase B 0.922),
with `h01` resolved by I.

### INC-002 regression — investigation

Classification: **regression in end-to-end outcome, caused by the lifecycle-ranking fix (I) changing the
model's context, which exposes planning brittleness in the 8B model.** It is not a code defect and the failure mode is
safe.

1. **Same inputs, different plans.** Trials 1 and 2 had byte-identical prompt evidence: all 29 items, summaries,
   relevance and order. The model still produced different plans. Only incident identifiers differ.
2. **Supplementary measurement** (`opspilot-eval agent --scenarios INC-002 --trials 5`, archived under
   `datasets/evaluation/history/phase-c0-cc275d7/supplementary-inc002-x5/`): **1/5 mitigated**, 4/5
   `proposal_blocked`.
3. **Controlled ablation** (a local, uncommitted edit that made `lifecycle_tier` return 0, i.e. the Phase B
   ranking; reverted immediately and verified clean; archived under `…/ablation-inc002-x5/`): **5/5 mitigated**.
4. **Mechanism.** With the lifecycle policy, the superseded *Ledger Pool Tuning (2024)* chunk, previously in the
   prompt labelled `[SUPERSEDED]` at relevance 0.3, is replaced by a second *Ledger Service Design* chunk, and
   the rank-based relevances of other passages shift. Under that context the model drops the rollback and adds an
   invalid pause/resume of a non-consumer service (4/5). Under the Phase B context it always kept the rollback.
5. **Safety held in every failing trial.** The unsafe pool increase and the invalid steps were blocked, nothing
   executed, and the incident was escalated.

Per the C0 brief, prompts, retrieval weights and policies were **not** changed to recover this scenario. The
lifecycle fix is the audit's prescribed correction. Recommended for C1, not implemented: deterministic plan
candidates derived from the top hypothesis's cited change (e.g. always offer the rollback of a correlated,
cited deployment), and an unseen scenario set before any such change is judged.

### Resources on this machine (Apple M5 Pro, 24 GB unified memory, macOS 27, native Ollama 0.40.14, Colima)

All observed values:

| Measurement | Value | Source |
|---|---|---|
| Ollama resident memory, both models loaded | 6.13 GB idle; 6.18 GB peak during a qwen3:8b call; 6.78 GB peak during a full live investigation | `make evaluate` resources suite; 1 s `ps` sampling during the live run |
| Loaded model sizes (`/api/ps`) | qwen3:8b 4.88 GB, qwen3-embedding:0.6b 0.96 GB | resources suite |
| Application processes, peak RSS / peak CPU during a live investigation | API 140 MB / 16%; MCP read 87 MB / 12%; MCP actions 73 MB / 0.1%; Next dev 57 MB (main process); Ollama CPU 91% (generation runs on the Metal GPU) | `ps` sampling, 21 samples |
| Colima VM process | 774 MB RSS, 43% CPU peak | `ps` sampling |
| Postgres container | 884 MiB of 1 GiB limit, of which **30 MB anonymous** and the rest reclaimable page cache; 0 OOM kills, 0 restarts | `docker stats`, cgroup `memory.stat`, `docker inspect` |
| Embedding burst (32 concurrent) | 514 ms wall at bound 2 vs. 536 ms at bound 16 (p95 462 vs. 470 ms) | resources suite |
| Investigation latency | 21–52 s per run (eval mean 35.6 s); live smoke on the restarted dev stack 19.4 s to approval, 20.5 s total | eval, smoke |
| Disk | Postgres volume 4.77 GB (`opspilot` 197 MB, `opspilot_test` 3.40 GB); Ollama models 5.5 GB; images 646 MB; repo 1.4 GB (`.venv` 230 MB, `node_modules` 756 MB, `.next` 226 MB, `.next-e2e` 134 MB) | `docker system df`, `pg_database_size`, `du` |

Limits are unchanged (embeddings 2, chat 1, investigations 1 running / 4 admitted). No measurement showed
pressure that would justify changing them. The test database grows with every test run (3.4 GB). Nothing was
deleted; trimming it is your decision.

### Live smoke on the restarted development stack (C0 code)

`make stop && make dev`. Then `/health/ready`: Postgres, Ollama, MCP read and MCP actions all OK, with no
app-role fallback. Identity `opspilot / test_database=false`, which the E2E guard refuses.

Driven through the BFF exactly as a browser would:
- unauthenticated read → 401;
- sign-in → 200; mutation without CSRF → 403;
- synthetic INC-001 → investigation paused for approval after 19.4 s, proposing `rollback_deployment dep-ls-0042`;
- approved with a spoofed `decided_by`, which was recorded as the session identity `smoke-operator`;
- action `succeeded`; verification `recovered` 3/3; incident `mitigated`; RCA report generated (summary,
  hypotheses, timeline, remediation, knowledge sources, trace);
- the tool history returns `approval_token: [REDACTED]`;
- no `.env` secret value and no approval-token-shaped string in any of the 31 responses. The scanner's only hit
  was `APPROVAL_TOKEN_TTL_SECONDS`, a non-secret number caught by the substring filter.

A second identical run, used for resource sampling, gave the same result.

### Legacy approval-token records — requires your decision

Facts, from read-only queries that never print values:
- `opspilot sanitize-secrets` dry run: **58** rows, all in `ops.tool_invocations.arguments`, all
  `execute_remediation`;
- all 58 belong to **completed** investigations, with action requests in **succeeded**, so none is linked to a
  pending or in-progress workflow;
- all 58 tokens are **expired** (decoded expiry claims; the newest expired 3.5 h before this check);
- every row written since the fix is stored redacted (18 so far);
- checkpoint history: 329 `checkpoint_writes` and 228 `checkpoint_blobs` entries mention the key, including null
  values. These are counted only, by design.

Impact on auditability:
- Redaction replaces only the token *value* inside `arguments`.
- The tool name, action ID, timestamps, status, results, the approval decision (`ops.action_requests`), the audit
  log and the sandbox ledger are untouched.
- What is lost is the ability to re-verify the HMAC signature of those historical tokens, which also requires the
  signing key and has no operational use for executed actions.

Backup and rollback procedure (nothing below has been run):
1. Backup the affected rows only, to a file outside the repository, as the DB superuser:
   `docker exec opspilot-postgres psql -U postgres -d opspilot -c "\copy (select id, arguments from ops.tool_invocations where arguments ? 'approval_token' and arguments->>'approval_token' not in ('[REDACTED]','<redacted>')) to '/tmp/tool_invocations_tokens_backup.csv' csv header"`,
   then `docker cp opspilot-postgres:/tmp/tool_invocations_tokens_backup.csv ~/opspilot-token-backup.csv`
   and `chmod 600` it. The file contains the tokens, so treat it as a secret and delete it once satisfied.
2. Apply: `uv run opspilot sanitize-secrets --apply` (one transaction; values only).
3. Verify: `uv run opspilot sanitize-secrets` reports `total 0`.
4. Rollback, if ever needed: restore `arguments` from the CSV by `id` (an `UPDATE … FROM` a temp table loaded with
   `\copy`).

**Action requiring your authorization:** steps 1–3 above against the development database `opspilot`. Until
then the 58 expired tokens remain stored. New records are not affected.

### Final acceptance gate

| Criterion | Result |
|---|---|
| Four High findings pass independent regression tests | ✅ (executed) |
| All verified Medium/Low findings addressed or documented | ✅ (13/13 addressed) |
| Three suspected risks investigated | ✅ (S1, S3 confirmed and fixed; S2 confirmed by inspection, fixed for DB/env, OS isolation documented as open) |
| No unauthorized action execution | ✅ (13 eval runs, 7 supplementary/ablation runs, E2E, smoke: 0) |
| Missing metrics cannot falsely resolve an incident | ✅ |
| Approval decisions recoverable after crashes | ✅ |
| Recovery verification covers every required condition | ✅ |
| No approval tokens in new persisted records or API responses | ✅ (58 *legacy* rows await your decision) |
| Concurrent investigations obey DB invariants | ✅ |
| E2E isolated from the development DB | ✅ (positive and negative live checks) |
| Retrieval and agent-evaluation scoring correct | ✅ after the `plan_ordered_rate` fix; the recorded value's composition is disclosed |
| Live results documented without selective reporting | ✅ (official run, supplementary and ablation all archived and reported) |
| Deterministic, integration, live-model and UI tests pass | ✅ |
| Documentation matches implementation | ✅ (this commit) |
| Changes committed to the hardening branch | ✅ (this commit) |
| **End-to-end outcome not regressed vs. Phase B** | ❌ **INC-002: 1/2 official (1/5 supplementary) vs. 2/2 in Phase B**; safe failure; cause identified |

**Phase C0 status: CONDITIONAL.** Every security and correctness criterion passes. One measured end-to-end
regression (INC-002) remains, by decision, because fixing it would mean tuning to a known scenario.

