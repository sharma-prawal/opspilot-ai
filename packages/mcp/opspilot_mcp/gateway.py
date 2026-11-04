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
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
Profile = Literal["read", "actions"]


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
                except Exception as exc:  # transport/protocol failure
                    status, error = ToolCallStatus.ERROR, f"{type(exc).__name__}: {exc}"
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
                arguments=args,
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


@asynccontextmanager
async def connect_gateway(settings: Settings, profile: Profile) -> AsyncIterator[McpToolGateway]:
    """Open an MCP session to the read or action server and expose it as a ToolGateway."""
    from opspilot_mcp.action_server import ACTION_TOOLS
    from opspilot_mcp.read_server import READ_TOOLS

    if settings.mcp_transport == "stdio":
        target: Any = stdio_params(profile)
    else:
        port = settings.mcp_http_port + (0 if profile == "read" else 1)
        target = f"http://{settings.mcp_http_host}:{port}/mcp"
    async with Client(target) as client:
        listed = {t.name for t in (await client.list_tools()).tools}
        expected = READ_TOOLS if profile == "read" else ACTION_TOOLS
        if listed != expected:
            raise RuntimeError(f"MCP {profile} server tool mismatch: {sorted(listed ^ expected)}")
        name = client.server_info.name if client.server_info else f"opspilot-ops-{profile}"
        yield McpToolGateway(
            client, server_name=name, tools=frozenset(listed), timeout_seconds=settings.tool_timeout_seconds
        )
