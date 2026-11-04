# Roadmap

## Implemented

| Version | Scope |
|---|---|
| v0.1.0 | INC-001 end to end: LangGraph workflow with Postgres checkpoints and HITL, MCP read/action servers, hybrid RAG, FastAPI, Next.js UI, CI |
| Phase B (unreleased → v0.2.0) | INC-002, INC-003, NEG-001..003; capacity/queue/config tools; multi-step plans approved per step; evidence-based safety gates; explicit outcomes and escalation; approval expiry; supervised MCP sessions; held-out retrieval set; incident-level evaluation |

## Planned

| Priority | Item | Why |
|---|---|---|
| P1 | Status-aware retrieval ranking (demote superseded/unreviewed documents) | Held-out failure analysis (h01): lifecycle, not semantics, caused the miss. A reranker is not indicated. |
| P1 | A second set of unseen scenarios to test the safety gates out of sample | The gates were designed after observing failures on the current scenarios |
| P1 | INC-004 (downstream degradation with a circuit breaker action) and INC-005 (worker backlog / scale-out) | Broaden the action catalogue beyond rollback/queue actions |
| P2 | OIDC operator identity; per-user approval audit; role separation (approver ≠ requester) | Replace the shared operator token |
| P2 | Server-Sent Events for workflow events | Replace polling |
| P2 | Model-graded faithfulness (Ragas or local judge), reported separately from deterministic metrics | Measure report quality beyond citation validity |
| P3 | Real adapters behind the MCP read server (Prometheus, Loki, Argo CD) | The agents already depend only on the tool contracts |
| P3 | Worker process for investigations (runner out of the API process) | Checkpoints already make runs portable |

Not planned: autonomous execution without approval; free-form shell/SQL tools; cloud inference as a default.
