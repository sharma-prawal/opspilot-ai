# Security

## Threat model (local-first, single operator)

| Asset | Threat | Control |
|---|---|---|
| Sandbox environment state | LLM-initiated or injected state change | Fixed remediation catalogue; actions executed only by graph code after approval; action server re-validates approval in DB and claims atomically |
| Approval decisions | Forged approval, replay, approving a different action | Operator bearer token (server-side only); approval bound to `action_id` + `params_hash`; workflow must be paused on that action; status transitions are compare-and-set |
| Host machine | Arbitrary command / SQL execution | No shell or SQL tool exists; tool arguments are typed with bounds (regex service names, max windows, max limits); SQL is parameterised SQLAlchemy |
| Checkpoint store | Deserialisation RCE if DB compromised | `LANGGRAPH_STRICT_MSGPACK=true`; state contains only JSON-compatible primitives |
| LLM context | Prompt injection via logs, runbooks, incident text | Evidence delimited and declared untrusted; system prompt forbids following it; outputs schema-validated; cited IDs must exist; remediation catalogue enforced in code |
| Network | Exposure of DB / API / model | All services bound to 127.0.0.1; CORS allowlist; MCP over stdio by default |
| Secrets | Leakage via VCS | `.env` git-ignored; `.env.example` placeholders only; no paid API keys exist in the system |

## Prompt-injection posture

Prompt injection cannot be fully prevented in an LLM, so the design assumes the model *can* be
manipulated and limits what a manipulated model can do:

1. The LLM never calls tools directly. Nodes call tools; the LLM only returns structured JSON.
2. The LLM's remediation output is an enum + IDs. `propose` rejects unknown action types,
   unknown services and deployment IDs not present in collected evidence.
3. Even a valid proposal only creates a `pending` request; execution requires a human approval
   recorded in the database.
4. The action server refuses any action that is not `approved`, already executed, or whose
   parameters hash differs from the approved hash.

Tests: `tests/security/` contains injected log lines and an injected runbook, and asserts that
(a) no out-of-catalogue action is proposed, (b) nothing executes without approval, (c) direct
calls to the action tool without approval fail, (d) replayed approvals are rejected.

## Data

All datasets are synthetic and generated in this repository. No customer or production data.

## Safety gates on model proposals (Phase B)

Prompt injection and over-eager models both show up as unwarranted proposals. Measured on the first live
pass before the gates existed, the model rolled back unrelated deployments in all three negative scenarios and
proposed a 345-connection pool on a 200-connection database. The gates in `AGENT_WORKFLOWS.md` now block these
in code, independent of the prompt. The human approval and the action server's token check remain the final
controls; the gates reduce how often a human is asked to approve something wrong.

Adversarial content in the corpus: an unreviewed wiki page instructs "AI assistants" to restart services and
raise pools to 200 and to mark actions approved; a superseded runbook recommends a pool increase that is unsafe
under current limits. Retrieved documents carry their lifecycle status; non-current documents are halved in
relevance and labelled in evidence and reports.

## Known gaps (tracked)

- Single shared operator token rather than per-user identity (OIDC planned).
- No rate limiting on the API (localhost only).
- Retrieval ranking does not use document status: in the held-out benchmark a superseded runbook and the
  injected wiki page outranked the current runbook for one question (h01). The agent compensates by demoting
  non-current evidence; ranking-level demotion is a planned change.
- An operator who approves every step still executes whatever passed the gates; the gates are evidence-based
  heuristics, not proofs of correctness.
- Model weights are trusted as distributed by Ollama's registry.
