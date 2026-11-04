"""``ToolGateway`` implementation over an MCP ``Client`` session (stdio or Streamable HTTP)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp import Client, StdioServerParameters
from mcp.types import TextContent

from opspilot_agents.ports import ToolResult
from opspilot_shared.config import Settings
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import ToolCallRecord, ToolCallStatus
from opspilot_shared.logging import get_logger, log_context
from opspilot_shared.redaction import redact
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
Profile = Literal["read", "actions"]
TRANSPORT_ERROR = "transport: "


def _summarize(data: dict[str, Any] | None) -> str | None:
    if data is None:
        return None
    parts = []
    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key}: {len(value)} item(s)")
        elif isinstance(value, (str, int, float, bool)) and len(str(value)) < 60:
            parts.append(f"{key}={value}")
    return ", ".join(parts)[:300] or None


class McpToolGateway:
    def __init__(self, client: Client, *, server_name: str, tools: frozenset[str], timeout_seconds: float) -> None:
        self._client = client
        self._server = server_name
        self._tools = tools
        self._timeout = timeout_seconds

    @property
    def server_name(self) -> str:
        return self._server

    def available_tools(self) -> frozenset[str]:
        return self._tools

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        call_id = f"tc-{uuid.uuid4().hex[:16]}"
        started = utcnow()
        t0 = time.perf_counter()
        args = json.loads(json.dumps(arguments, default=str))  # ISO datetimes, UUID strings
        status, data, error = ToolCallStatus.OK, None, None
        with (
            log_context(tool_call_id=call_id, tool=tool, agent=agent),
            _tracer.start_as_current_span(f"mcp.tool/{tool}") as span,
        ):
            span.set_attribute("mcp.server", self._server)
            span.set_attribute("mcp.tool", tool)
            if tool not in self._tools:
                status, error = ToolCallStatus.REJECTED, f"tool {tool!r} is not exposed by {self._server}"
            else:
                try:
                    result = await asyncio.wait_for(self._client.call_tool(tool, args), self._timeout)
                except TimeoutError:
                    status, error = ToolCallStatus.TIMEOUT, f"timed out after {self._timeout}s"
                except Exception as exc:  # transport/protocol failure (session may be dead)
                    status, error = ToolCallStatus.ERROR, f"{TRANSPORT_ERROR}{type(exc).__name__}: {exc}"
                else:
                    if result.is_error:
                        text = " ".join(b.text for b in result.content if isinstance(b, TextContent))
                        status, error = ToolCallStatus.ERROR, text[:1000] or "tool error"
                    else:
                        data = result.structured_content
            latency = round((time.perf_counter() - t0) * 1000, 1)
            span.set_attribute("mcp.status", status.value)
            record = ToolCallRecord(
                id=call_id,
                tool=tool,
                server=self._server,
                agent=agent,
                arguments=redact(args),
                status=status,
                latency_ms=latency,
                started_at=started,
                result_summary=_summarize(data),
                error=error,
            )
            _log.info("tool_call", status=status.value, latency_ms=latency, error=error)
        return ToolResult(tool=tool, ok=status is ToolCallStatus.OK, data=data, error=error, record=record)


def stdio_params(profile: Profile) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "opspilot_mcp.cli", "serve", "--profile", profile], env=dict(os.environ)
    )


class SupervisedMcpGateway:
    """ToolGateway with bounded session recovery.

    A dedicated supervisor task owns the MCP ``Client`` context (anyio cancel scopes must be entered and
    exited in the same task). When a call fails at the transport level (child process died, stream closed)
    the supervisor reconnects with exponential backoff, at most ``max_reconnects`` consecutive times, and the
    call is retried once. Retrying is safe: read tools are idempotent and ``execute_remediation`` is
    idempotent per action_id (the sandbox returns the recorded execution). After the budget is exhausted
    the gateway fails fast with a clear error instead of hanging.
    """

    def __init__(
        self,
        target_factory: Any,
        *,
        profile: Profile,
        expected_tools: frozenset[str],
        timeout_seconds: float,
        max_reconnects: int = 3,
        backoff_base: float = 1.0,
        connect_timeout: float = 60.0,
    ) -> None:
        self._target_factory = target_factory
        self._profile = profile
        self._expected = expected_tools
        self._timeout = timeout_seconds
        self._max_reconnects = max_reconnects
        self._backoff = backoff_base
        self._connect_timeout = connect_timeout
        self._inner: McpToolGateway | None = None
        self._ready = asyncio.Event()
        self._reconnect = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None
        self.server_label = f"opspilot-ops-{profile}"
        self.reconnects = 0
        self.last_error: str | None = None
        self.exhausted = False

    @property
    def server_name(self) -> str:
        return self.server_label

    @property
    def connected(self) -> bool:
        return self._inner is not None and self._ready.is_set()

    def available_tools(self) -> frozenset[str]:
        return self._expected

    async def start(self) -> None:
        self._task = asyncio.create_task(self._supervise(), name=f"mcp-supervisor-{self._profile}")
        await asyncio.wait_for(self._ready.wait(), self._connect_timeout)
        if self._inner is None:
            raise RuntimeError(f"MCP {self._profile} server unavailable: {self.last_error}")

    async def aclose(self) -> None:
        self._stopping = True
        self._reconnect.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _supervise(self) -> None:
        consecutive = 0
        while not self._stopping:
            try:
                async with Client(self._target_factory()) as client:
                    listed = {t.name for t in (await client.list_tools()).tools}
                    if listed != self._expected:
                        raise RuntimeError(f"MCP {self._profile} tool mismatch: {sorted(listed ^ self._expected)}")
                    if client.server_info:
                        self.server_label = client.server_info.name
                    self._inner = McpToolGateway(
                        client, server_name=self.server_label, tools=frozenset(listed), timeout_seconds=self._timeout
                    )
                    consecutive = 0
                    self._ready.set()
                    _log.info("mcp_session_ready", profile=self._profile, reconnects=self.reconnects)
                    await self._reconnect.wait()
                    self._reconnect.clear()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                _log.warning("mcp_session_lost", profile=self._profile, error=self.last_error)
            finally:
                self._inner = None
                self._ready.clear()
            if self._stopping:
                break
            consecutive += 1
            if consecutive > self._max_reconnects:
                self.exhausted = True
                self._ready.set()  # release waiters; calls now fail fast
                _log.error("mcp_reconnect_exhausted", profile=self._profile, attempts=consecutive - 1)
                return
            self.reconnects += 1
            await asyncio.sleep(min(self._backoff * 2 ** (consecutive - 1), 10.0))

    async def _session(self) -> McpToolGateway | None:
        if self.exhausted:
            return None
        try:
            await asyncio.wait_for(self._ready.wait(), self._connect_timeout)
        except TimeoutError:
            return None
        return self._inner

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        res: ToolResult | None = None
        for attempt in (1, 2):
            inner = await self._session()
            if inner is None:
                break
            res = await inner.call(tool, arguments, agent=agent)
            if not (res.error or "").startswith(TRANSPORT_ERROR):
                return res
            _log.warning("mcp_transport_failure", tool=tool, attempt=attempt, error=res.error)
            self._ready.clear()
            self._reconnect.set()
        if res is not None:
            return res
        record = ToolCallRecord(
            id=f"tc-{uuid.uuid4().hex[:16]}",
            tool=tool,
            server=self.server_label,
            agent=agent,
            arguments=redact(json.loads(json.dumps(arguments, default=str))),
            status=ToolCallStatus.ERROR,
            latency_ms=0.0,
            started_at=utcnow(),
            error=f"MCP {self._profile} session unavailable: {self.last_error}",
        )
        return ToolResult(tool=tool, ok=False, data=None, error=record.error, record=record)


@asynccontextmanager
async def connect_gateway(settings: Settings, profile: Profile) -> AsyncIterator[SupervisedMcpGateway]:
    """Open an MCP session to the read or action server and expose it as a ToolGateway."""
    from opspilot_mcp.action_server import ACTION_TOOLS
    from opspilot_mcp.read_server import READ_TOOLS

    if settings.mcp_transport == "stdio":
        target: Any = stdio_params(profile)
    else:
        port = settings.mcp_http_port + (0 if profile == "read" else 1)
        target = f"http://{settings.mcp_http_host}:{port}/mcp"
    expected = READ_TOOLS if profile == "read" else ACTION_TOOLS
    gw = SupervisedMcpGateway(
        lambda: target, profile=profile, expected_tools=expected, timeout_seconds=settings.tool_timeout_seconds
    )
    await gw.start()
    try:
        yield gw
    finally:
        await gw.aclose()
