# ADR-002: LangGraph for agent orchestration

- Status: Accepted (2026-11-04)

## Context
Investigations are multi-step, must pause for human approval for arbitrarily long periods, survive
restarts, and be inspectable. Routing must depend on evidence, but loops must be bounded.

## Alternatives considered
1. **LangGraph** — explicit state graph, conditional edges, `interrupt`/`Command(resume)`, Postgres checkpointer.
2. Hand-rolled state machine + job table — full control, but re-implements checkpointing, interrupts and replay.
3. Conversational multi-agent frameworks (AutoGen/CrewAI style) — agent-to-agent chat loops are hard to bound and inspect.
4. Temporal — excellent durability, but a heavy extra service for a laptop footprint.

## Decision
Use LangGraph 1.x `StateGraph` with a `TypedDict` state of JSON-compatible values, compiled with
`AsyncPostgresSaver`. Supervisor-planned task queue + conditional edges; `interrupt` for approval.

## Rationale
Durable execution and HITL are first-class; the graph is explicit enough to draw and test.
Nodes are plain async functions over injected ports, so they are unit-testable without LangGraph internals.

## Tradeoffs
Interrupted nodes are re-executed on resume, so nodes before/at interrupts must be side-effect free —
persistence is therefore done by the runner, not inside nodes. Library churn risk is mitigated by
keeping LangGraph usage inside `graph.py`.

## Consequences
`LANGGRAPH_STRICT_MSGPACK=true` is mandatory; state never contains arbitrary Python objects.
