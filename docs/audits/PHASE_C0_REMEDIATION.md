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

*(C0-B to C0-E entries are added as those milestones complete.)*
