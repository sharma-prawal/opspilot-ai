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
from opspilot_api.ownership import ExecutionOwnership, RuntimeLifecycle, RuntimeState
from opspilot_api.services.approvals import ApprovalService
from opspilot_api.services.commands import CommandDispatcher
from opspilot_api.services.incidents import IncidentService
from opspilot_api.services.investigations import InvestigationRunner, InvestigationService
from opspilot_mcp.gateway import Profile, connect_gateway
from opspilot_shared.config import Settings
from opspilot_shared.errors import OwnershipError
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

        Lifecycle (C0-H2): ``INITIALIZING → ACQUIRING_OWNERSHIP`` (the database's execution-owner lock and a new
        epoch are taken *first*; a second runtime fails here) → initialization (gateways, fenced checkpointer, runner
        gated on the lifecycle) → affirmative fence check → ``READY`` → yield. Loss at any point is sticky and
        synchronous: before READY it makes start-up fail (resources are closed normally); after READY it stops
        admission and running segments at once, and ``on_owner_lost`` runs (the served API exits). On exit:
        ``STOPPING`` → runner stopped → lock released → ``STOPPED``."""
        lifecycle = RuntimeLifecycle()
        ownership = ExecutionOwnership(settings, on_lost=on_owner_lost, lifecycle=lifecycle)
        try:
            await ownership.acquire()
        except BaseException:
            lifecycle.transition(RuntimeState.STOPPING, "start-up refused")
            lifecycle.transition(RuntimeState.STOPPED)
            raise
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
                fence = ownership.fence
                if fence is None:  # lost while the gateways were starting (independent audit N1)
                    raise OwnershipError(f"execution ownership lost during start-up: {ownership.lost_reason}")
                saver = await stack.enter_async_context(checkpointer_pool(settings, fence=fence))
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
                    lifecycle=lifecycle,
                    fence=fence,
                    on_fence_violation=ownership.lose_now,
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
                await _require_fencing(infra)
                # The runner is registered and gated; ownership is now re-proven against the database before READY.
                await ownership.verify()
                if not lifecycle.transition(RuntimeState.READY, f"epoch {fence[0]}"):
                    raise OwnershipError(f"execution ownership lost during start-up: {ownership.lost_reason}")
                _log.info(
                    "runtime_ready",
                    read_tools=len(read_gw.available_tools()),
                    action_tools=len(act_gw.available_tools()),
                    model=settings.llm_model,
                    epoch=fence[0],
                )
                try:
                    yield rt
                finally:
                    lifecycle.transition(RuntimeState.STOPPING, "runtime closing")
                    await runner.shutdown()
        finally:
            lifecycle.transition(RuntimeState.STOPPING, "runtime closing")
            await infra.aclose()
            lifecycle.transition(RuntimeState.STOPPED)


async def _require_fencing(infra: Infrastructure) -> None:
    """Refuse to run if the checkpoint write fence is not installed (``make migrate`` installs it)."""
    from psycopg import AsyncConnection

    from opspilot_api.checkpointing import fencing_installed

    async with await AsyncConnection.connect(infra.settings.libpq_dsn(), autocommit=True) as conn:
        if not await fencing_installed(conn):
            raise OwnershipError("checkpoint write fencing is not installed; run `make migrate`")
