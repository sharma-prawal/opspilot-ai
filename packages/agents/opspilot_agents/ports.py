"""Ports the agent workflow depends on. Implementations live outside this package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from opspilot_shared.domain.evidence import ToolCallRecord


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    ok: bool
    data: dict[str, Any] | None
    error: str | None
    record: ToolCallRecord


class ToolGateway(Protocol):
    """Typed access to an MCP server's tools. Never raises for tool-level failures."""

    @property
    def server_name(self) -> str: ...

    def available_tools(self) -> frozenset[str]: ...

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult: ...
