"""Investigation graph assembly."""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from opspilot_agents.nodes import (
    AgentDeps,
    InvestigationNodes,
    instrumented,
    make_route_after_rca,
    route_after_approval,
    route_after_followup,
    route_after_intake,
    route_after_propose,
    route_dispatch,
)
from opspilot_agents.state import InvestigationState

NODE_NAMES = (
    "intake",
    "plan",
    "dispatch",
    "telemetry",
    "dependencies",
    "changes",
    "knowledge",
    "rca",
    "followup",
    "propose",
    "await_approval",
    "execute",
    "verify",
    "report",
    "failed",
)
TOOL_NODES = {"intake", "telemetry", "dependencies", "changes", "knowledge", "verify"}


def _transient(exc: Exception) -> bool:
    return bool(getattr(exc, "transient", False))


def build_graph(deps: AgentDeps, checkpointer: Any | None = None, *, node_timeout_seconds: float = 300.0) -> Any:
    nodes = InvestigationNodes(deps)
    g: StateGraph[InvestigationState] = StateGraph(InvestigationState)
    retry = RetryPolicy(max_attempts=2, initial_interval=1.0, retry_on=_transient)
    for name in NODE_NAMES:
        fn = instrumented(name)(getattr(nodes, name))
        kwargs: dict[str, Any] = {}
        if name in TOOL_NODES:
            kwargs["retry_policy"] = retry
        if name != "await_approval":
            kwargs["timeout"] = node_timeout_seconds
        g.add_node(name, cast(Any, fn), **kwargs)

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", route_after_intake, ["plan", "failed"])
    g.add_edge("plan", "dispatch")
    g.add_conditional_edges("dispatch", route_dispatch, ["telemetry", "dependencies", "changes", "knowledge", "rca"])
    for cap in ("telemetry", "dependencies", "changes", "knowledge"):
        g.add_edge(cap, "dispatch")
    g.add_conditional_edges("rca", make_route_after_rca(deps.policy), ["followup", "propose", "report", "failed"])
    g.add_conditional_edges("followup", route_after_followup, ["dispatch", "propose", "report"])
    g.add_conditional_edges("propose", route_after_propose, ["await_approval", "report"])
    g.add_conditional_edges("await_approval", route_after_approval, ["execute", "report"])
    g.add_edge("execute", "verify")
    g.add_edge("verify", "report")
    g.add_edge("report", END)
    g.add_edge("failed", END)
    return g.compile(checkpointer=checkpointer, name="opspilot-investigation")
