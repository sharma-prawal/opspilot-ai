"""Application runtime: long-lived resources opened once per process (API lifespan or CLI)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps, AgentPolicy
from opspilot_agents.ports import ToolGateway
from opspilot_api.checkpointing import checkpointer_pool
from opspilot_api.container import Infrastructure
from opspilot_api.ownership import ExecutionOwnership
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
    ownership: ExecutionOwnership

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        settings: Settings,
        *,
        chat: Any | None = None,
        gateways: GatewayFactory | None = None,
        embedder: Any | None = None,
        on_owner_lost: Callable[[str], Awaitable[None]] | None = None,
    ) -> AsyncIterator[AppRuntime]:
        """``chat`` / ``gateways`` / ``embedder`` let tests inject deterministic adapters.

        C0-G4: the database's single execution-owner lock is taken *first*; a second runtime against the same
        database (another API worker, a CLI/evaluation run) fails here before connecting anything else. If ownership
        is later lost, every running segment is stopped and all new work is refused (``runner.suspend``), then
        ``on_owner_lost`` runs (the API process uses it to exit)."""
        holder: dict[str, AppRuntime] = {}

        async def lost(reason: str) -> None:
            rt = holder.get("rt")
            if rt is not None:
                await rt.runner.suspend(reason)
            if on_owner_lost is not None:
                await on_owner_lost(reason)

        ownership = ExecutionOwnership(settings, on_lost=lost)
        await ownership.acquire()
        try:
            infra = Infrastructure.create(settings, embedder=embedder)
        except BaseException:
            await ownership.release()
            raise
        connect: GatewayFactory = gateways or (lambda profile: connect_gateway(settings, profile))
        try:
            async with AsyncExitStack() as stack:
                stack.push_async_callback(ownership.release)  # released last, after the runner has stopped
                read_gw = await stack.enter_async_context(connect("read"))
                act_gw = await stack.enter_async_context(connect("actions"))
                saver = await stack.enter_async_context(checkpointer_pool(settings))
                deps = AgentDeps(
                    chat=chat or infra.chat_model, tools=read_gw, actions=act_gw, policy=policy_from(settings)
                )
                graph = build_graph(deps, saver, node_timeout_seconds=settings.llm_timeout_seconds * 2)
                runner = InvestigationRunner(
                    infra.session_factory,
                    graph,
                    settings.max_concurrent_investigations,
                    lease_seconds=settings.run_lease_seconds,
                    max_pending=settings.max_pending_investigations,
                )
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
                    ownership,
                )
                holder["rt"] = rt
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
