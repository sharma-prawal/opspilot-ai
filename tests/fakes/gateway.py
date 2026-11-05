"""Scripted ToolGateway for node-level tests (no MCP, no DB)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from opspilot_agents.ports import ToolResult
from opspilot_shared.domain.evidence import ToolCallRecord, ToolCallStatus

Handler = Callable[[dict[str, Any]], dict[str, Any] | None]


class ScriptedGateway:
    """Each tool maps to a handler returning structured data, or None to simulate a tool error."""

    def __init__(self, handlers: dict[str, Handler]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def server_name(self) -> str:
        return "scripted"

    def available_tools(self) -> frozenset[str]:
        return frozenset(self.handlers)

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        self.calls.append((tool, arguments))
        data = self.handlers[tool](arguments) if tool in self.handlers else None
        status = ToolCallStatus.OK if data is not None else ToolCallStatus.ERROR
        error = None if data is not None else f"scripted failure for {tool}"
        rec = ToolCallRecord(
            id=f"tc-{len(self.calls)}",
            tool=tool,
            server="scripted",
            agent=agent,
            arguments=arguments,
            status=status,
            latency_ms=1.0,
            started_at=datetime(2026, 11, 3, 14, tzinfo=UTC),
            error=error,
        )
        return ToolResult(tool=tool, ok=data is not None, data=data, error=error, record=rec)
