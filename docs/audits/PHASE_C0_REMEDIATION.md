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

*(C0-C to C0-E entries are added as those milestones complete.)*
