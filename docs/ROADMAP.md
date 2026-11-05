# Roadmap

## Implemented

| Version | Scope |
|---|---|
| v0.1.0 | INC-001 end to end: LangGraph workflow with Postgres checkpoints and HITL, MCP read/action servers, hybrid RAG, FastAPI, Next.js UI, CI |
| v0.2.0 (Phase B) | INC-002, INC-003, NEG-001..003; capacity/queue/config tools; multi-step plans approved per step; evidence-based safety gates; explicit outcomes and escalation; approval expiry; supervised MCP sessions; held-out retrieval set; incident-level evaluation |
| Phase C0 (branch `hardening/phase-c0`, unreleased) | Remediation of the Codex audit: BFF authentication, tri-state impact, durable decision delivery, complete recovery verification, credential redaction, uncertainty policy, DB-enforced investigation invariant and execution lease, cancellation boundary, lifecycle-aware retrieval, citation snapshots, agent-path retrieval benchmark, stricter plan scoring, MCP degradation warnings, isolated E2E, least-privilege MCP roles, resource bounds. Details: `docs/audits/PHASE_C0_REMEDIATION.md` |
| Phase C0-F (same branch, unreleased) | Remediation of the independent verification: observed-scope recovery verification with health conditions and metric-specific ranges, atomic admission with durable dispatch and lease fencing, current-runbook section coverage, test-workflow ownership, INC-003 answer-key specification check with occurrence/order-aware scoring. Details: `docs/audits/PHASE_C0_F_REMEDIATION.md` |
| Phase C0-G (same branch, unreleased) | Remediation of the second independent verification: evidence-complete recovery verification, monotonic terminal states (transition policy + DB trigger), lifecycle-validated retrieval with no superseded guidance in investigations, runtime-enforced single execution owner per database. Details: `docs/audits/PHASE_C0_G_REMEDIATION.md` |
| Phase C0-H (same branch, unreleased) | Remediation of the third independent verification: immutable, serialized document revisions enforced by the database; explicit runtime lifecycle; epoch-based database fencing of checkpoint writes, runner state writes and remediation claims. Details: `docs/audits/PHASE_C0_H_REMEDIATION.md` |

## Planned

| Priority | Item | Why |
|---|---|---|
| P1 | A second set of unseen scenarios to test the safety gates out of sample | The gates were designed after observing failures on the current scenarios |
| P1 | An unseen scenario set authored and sealed by someone other than the author of the gates and labels (deployment and non-deployment cases, including cases where rollback is wrong) | The gates were designed after observing failures on the current scenarios; C0-F has no novel-case measurement |
| P1 | Planner robustness: bounded, typed, catalogue-only candidates recorded in shadow mode first, eligible only with an explicit causal-change link plus mechanism evidence (never "any correlated, cited deployment"), evaluated on the unseen set before enabling | INC-002 diagnosis/plan inconsistency. The independent audit showed "offer the rollback of a correlated, cited deployment" is unsafe as a general rule (NEG-002 cites an unrelated deploy) |
| P1 | Multi-worker readiness: a DB-enforced global admission budget; fencing tokens through the checkpointer; stale-owner pause/takeover/resume tests | C0-F2 admission and fencing are per process; LangGraph checkpoint writes are not fenced; C0-G4 therefore enforces one execution owner per database |
| P2 | Raw model-plan scoring that binds or evidence-validates every target parameter | Independent audit R6: `model_plan_acceptable` is partial pattern conformance (INC-003's key binds no rollback service or queue) |
| P2 | Owner-scoped test cleanup and terminal-row/checkpoint retention | C0-F4 isolation is temporal on an exclusively used test DB; terminal rows accumulate |
| P1 | Per-service SLO definitions for recovery verification | C0-F1 residual limits are conservative defaults, not SLOs |
| P2 | Pin evaluation to a dedicated, verified `*_test` database with its own real-embedding KB | Evaluation still writes simulation rows to the development DB (additive) |
| P1 | INC-004 (downstream degradation with a circuit breaker action) and INC-005 (worker backlog / scale-out) | Broaden the action catalogue beyond rollback/queue actions |
| P1 | Per-server OS users or containers for the MCP servers | C0 O: DB roles and a minimal environment limit a compromised child, but it can still read `.env` from disk as the same OS user |
| P2 | OIDC operator identity; per-user approval audit; role separation (approver ≠ requester); then an audited operator override for withheld plans | Replace the shared passphrases (C0 H1 remaining risk); C0 F deliberately ships without an override |
| P2 | Cross-process cancellation signal (DB-backed) | C0 G: cancelling a run owned by another API process takes effect only at its next boundary |
| P2 | Server-Sent Events for workflow events | Replace polling |
| P2 | Model-graded faithfulness (Ragas or local judge), reported separately from deterministic metrics | Measure report quality beyond citation validity |
| P3 | Real adapters behind the MCP read server (Prometheus, Loki, Argo CD) | The agents already depend only on the tool contracts |
| P3 | Worker process for investigations (runner out of the API process) | Checkpoints already make runs portable |

Not planned: autonomous execution without approval; free-form shell/SQL tools; cloud inference as a default.
