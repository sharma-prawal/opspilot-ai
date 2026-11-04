"""Application runtime: long-lived resources opened once per process (API lifespan or CLI)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps, AgentPolicy
from opspilot_agents.ports import ToolGateway
from opspilot_api.checkpointing import checkpointer_pool
from opspilot_api.container import Infrastructure
from opspilot_api.services.approvals import ApprovalService
from opspilot_api.services.commands import CommandDispatcher
from opspilot_api.services.incidents import IncidentService
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_mcp.gateway import Profile, connect_gateway
from opspilot_shared.config import Settings
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)
GatewayFactory = Callable[[Profile], AbstractAsyncContextManager[ToolGateway]]


def policy_from(settings: Settings) -> AgentPolicy:
    return AgentPolicy(
        max_tool_calls=settings.agent_max_tool_calls,
        max_llm_calls=settings.agent_max_llm_calls,
        max_rounds=settings.agent_max_rounds,
        confidence_threshold=settings.rca_confidence_threshold,
    )


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    infra: Infrastructure
    read_tools: ToolGateway
    action_tools: ToolGateway
    graph: Any
    runner: InvestigationRunner
    incidents: IncidentService
    investigations: InvestigationService
    approvals: ApprovalService
    dispatcher: CommandDispatcher

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        settings: Settings,
        *,
        chat: Any | None = None,
        gateways: GatewayFactory | None = None,
        embedder: Any | None = None,
    ) -> AsyncIterator[AppRuntime]:
        """``chat`` / ``gateways`` / ``embedder`` let tests inject deterministic adapters."""
        infra = Infrastructure.create(settings, embedder=embedder)
        connect: GatewayFactory = gateways or (lambda profile: connect_gateway(settings, profile))
        try:
            async with AsyncExitStack() as stack:
                read_gw = await stack.enter_async_context(connect("read"))
                act_gw = await stack.enter_async_context(connect("actions"))
                saver = await stack.enter_async_context(checkpointer_pool(settings))
                deps = AgentDeps(
                    chat=chat or infra.chat_model, tools=read_gw, actions=act_gw, policy=policy_from(settings)
                )
                graph = build_graph(deps, saver, node_timeout_seconds=settings.llm_timeout_seconds * 2)
                runner = InvestigationRunner(infra.session_factory, graph, settings.max_concurrent_investigations)
                dispatcher = CommandDispatcher(infra.session_factory, runner, graph, settings)
                investigations = InvestigationService(infra.session_factory, runner, graph, settings.llm_model)
                investigations.dispatcher = dispatcher
                rt = cls(
                    settings,
                    infra,
                    read_gw,
                    act_gw,
                    graph,
                    runner,
                    IncidentService(infra.session_factory),
                    investigations,
                    ApprovalService(infra.session_factory, runner, graph, settings, dispatcher),
                    dispatcher,
                )
                _log.info(
                    "runtime_ready",
                    read_tools=len(read_gw.available_tools()),
                    action_tools=len(act_gw.available_tools()),
                    model=settings.llm_model,
                )
                try:
                    yield rt
                finally:
                    await runner.shutdown()
        finally:
            await infra.aclose()
