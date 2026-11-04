# ADR-005: Model Context Protocol for agent tools

- Status: Accepted (2026-11-04)

## Context
Agents need telemetry, change, dependency and knowledge tools. Tomorrow these will be real systems
(Prometheus, Loki, Argo CD). The agent code must not know the simulator exists.

## Alternatives considered
1. Direct Python calls into the simulator — simplest, but couples agents to the implementation.
2. Internal REST service — workable, but bespoke schemas and no ecosystem reuse.
3. **MCP (Python SDK 2.x)** — standard tool discovery, JSON-schema inputs, structured outputs, stdio and Streamable HTTP transports, usable by other MCP hosts.

## Decision
Two MCP servers built with `mcp.server.MCPServer`: a **read** server (observability + knowledge) and an
**action** server (approval-gated sandbox remediation). The API connects with `mcp.Client` over stdio.
Agents depend on a `ToolGateway` port; `McpToolGateway` implements it.

## Rationale
Read/write separation is structural: the investigation nodes hold a client that cannot even see
write tools. Tool inputs are validated twice (pydantic on the server; typed wrappers in the gateway).

## Tradeoffs
stdio children add process start-up (~1–2 s, once per API lifetime) and an extra hop per call.

## Consequences
Protocol-level tests use both in-process `Client(server)` and a real stdio subprocess.
