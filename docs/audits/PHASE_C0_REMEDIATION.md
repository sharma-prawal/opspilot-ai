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
  - `apps/web/tests/bff-auth.test.ts` (22): unauthenticated, cross-origin, Sec-Fetch-Site, content type, CSRF,
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
- **Regression tests:** `tests/integration/test_concurrency.py` (8). Seven fail on the old service code:
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
- **Regression tests:** `tests/unit/test_plan_scoring.py` (7):
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

*(C0-E: full regression, evaluation and documentation follow.)*
