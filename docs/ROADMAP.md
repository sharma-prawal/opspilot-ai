# Roadmap

## Implemented

| Version | Scope |
|---|---|
| v0.1.0 | INC-001 end to end: LangGraph workflow with Postgres checkpoints and HITL, MCP read/action servers, hybrid RAG, FastAPI, Next.js UI, CI |
| v0.2.0 (Phase B) | INC-002, INC-003, NEG-001..003; capacity/queue/config tools; multi-step plans approved per step; evidence-based safety gates; explicit outcomes and escalation; approval expiry; supervised MCP sessions; held-out retrieval set; incident-level evaluation |
| Phase C0 (branch `hardening/phase-c0`, unreleased) | Remediation of the Codex audit: BFF authentication, tri-state impact, durable decision delivery, complete recovery verification, credential redaction, uncertainty policy, DB-enforced investigation invariant and execution lease, cancellation boundary, lifecycle-aware retrieval, citation snapshots, agent-path retrieval benchmark, stricter plan scoring, MCP degradation warnings, isolated E2E, least-privilege MCP roles, resource bounds. Details: `docs/audits/PHASE_C0_REMEDIATION.md` |

## Planned

| Priority | Item | Why |
|---|---|---|
| P1 | A second set of unseen scenarios to test the safety gates out of sample | The gates were designed after observing failures on the current scenarios |
| P1 | Planner robustness: deterministic plan candidates from the top hypothesis's cited change (e.g. offer the rollback of a correlated, cited deployment), evaluated on unseen scenarios first | C0 INC-002 regression: identical evidence, different plans; the lifecycle-correct context made the 8B model drop the rollback in 4/5 trials (ablation 5/5 with the old context) |
| P1 | INC-004 (downstream degradation with a circuit breaker action) and INC-005 (worker backlog / scale-out) | Broaden the action catalogue beyond rollback/queue actions |
| P1 | Per-server OS users or containers for the MCP servers | C0 O: DB roles and a minimal environment limit a compromised child, but it can still read `.env` from disk as the same OS user |
| P2 | OIDC operator identity; per-user approval audit; role separation (approver ≠ requester); then an audited operator override for withheld plans | Replace the shared passphrases (C0 H1 remaining risk); C0 F deliberately ships without an override |
| P2 | Cross-process cancellation signal (DB-backed) | C0 G: cancelling a run owned by another API process takes effect only at its next boundary |
| P2 | Server-Sent Events for workflow events | Replace polling |
| P2 | Model-graded faithfulness (Ragas or local judge), reported separately from deterministic metrics | Measure report quality beyond citation validity |
| P3 | Real adapters behind the MCP read server (Prometheus, Loki, Argo CD) | The agents already depend only on the tool contracts |
| P3 | Worker process for investigations (runner out of the API process) | Checkpoints already make runs portable |

Not planned: autonomous execution without approval; free-form shell/SQL tools; cloud inference as a default.
