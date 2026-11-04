# ADR-006: Human-approved, catalogue-bound remediation

- Status: Accepted (2026-11-04)

## Context
An LLM can be wrong or manipulated. Any state change must be explicitly approved, auditable and
idempotent, and approval must be enforced by the backend rather than the UI.

## Alternatives considered
1. Autonomous execution with guardrails — unacceptable for state-changing ops.
2. UI-only confirmation — bypassable by calling the API.
3. **Persisted action request + LangGraph interrupt + backend validation + executor re-validation.**

## Decision
- The LLM may only pick from a fixed catalogue (`rollback_deployment`, `restart_service`, …) with
  parameters validated against collected evidence.
- `action_id = uuid5(investigation_id, params_hash)`; requests persisted before the workflow pauses.
- Approval requires the operator token and must echo the `params_hash`; the investigation must be
  paused on that action; status transitions are compare-and-set.
- The action server checks `status = 'approved'` and atomically moves it to `executing` before acting.
- Every step is written to `ops.audit_log`.

## Tradeoffs
More moving parts than a confirm button; deliberate.

## Consequences
Rejection, cancellation and replay paths are tested in `tests/security` and `tests/integration`.
