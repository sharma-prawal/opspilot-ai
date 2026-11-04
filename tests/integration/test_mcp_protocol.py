"""MCP protocol tests: the tools are spoken to through a real MCP Client, not called as functions."""

import os
import sys
import uuid

import pytest
from mcp import Client, StdioServerParameters

from opspilot_mcp.action_server import ACTION_TOOLS, build_action_server
from opspilot_mcp.gateway import McpToolGateway
from opspilot_mcp.read_server import READ_TOOLS, build_read_server
from tests.integration.helpers import backend, make_incident

pytestmark = pytest.mark.integration
W = {"start": "2026-11-03T11:00:00+00:00", "end": "2026-11-03T14:30:00+00:00"}


async def test_tool_listing_separates_read_and_write(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    b = backend(settings, session_factory, embedder)
    async with Client(build_read_server(b)) as rc, Client(build_action_server(b)) as ac:
        read = {t.name: t for t in (await rc.list_tools()).tools}
        act = {t.name: t for t in (await ac.list_tools()).tools}
    assert set(read) == READ_TOOLS and set(act) == ACTION_TOOLS and not (set(read) & set(act))
    assert all(t.annotations and t.annotations.read_only_hint for t in read.values())
    assert act["execute_remediation"].annotations.destructive_hint is True
    schema = read["search_logs"].input_schema
    assert schema["properties"]["limit"]["maximum"] == 500 and "environment_id" in schema["required"]
    assert read["search_logs"].output_schema is not None  # structured output declared


async def test_structured_results_and_errors(settings, session_factory, embedder, ingested) -> None:  # type: ignore[no-untyped-def]
    _, env = await make_incident(session_factory)
    async with Client(build_read_server(backend(settings, session_factory, embedder))) as c:
        logs = await c.call_tool(
            "search_logs",
            {
                "environment_id": str(env),
                "service": "ledger-service",
                "min_level": "ERROR",
                "contains": "UndefinedColumn",
                "limit": 5,
                **W,
            },
        )
        assert not logs.is_error and logs.structured_content["total_matched"] > 100
        assert len(logs.structured_content["entries"]) == 5
        unknown = await c.call_tool("get_service_health", {"environment_id": str(env), "service": "payments-db"})
        assert unknown.is_error and "unknown service" in unknown.content[0].text
        too_big = await c.call_tool(
            "search_logs", {"environment_id": str(env), "service": "ledger-service", "limit": 10_000, **W}
        )
        assert too_big.is_error  # schema validation at the protocol boundary
        injection = await c.call_tool("get_service_health", {"environment_id": str(env), "service": "x; DROP TABLE"})
        assert injection.is_error
        window = await c.call_tool(
            "query_metrics",
            {
                "environment_id": str(env),
                "service": "transaction-api",
                "metric": "http_5xx_ratio",
                "start": "2026-11-01T00:00:00+00:00",
                "end": "2026-11-03T14:00:00+00:00",
            },
        )
        assert window.is_error and "24h" in window.content[0].text
        kb = await c.call_tool("search_runbooks", {"query": "roll back schema migration", "top_k": 3})
        assert not kb.is_error and kb.structured_content["results"]
        assert all(r["doc_type"] != "incident_report" for r in kb.structured_content["results"])
        assert "untrusted" in kb.structured_content["notice"]


async def test_gateway_records_and_rejects_unexposed_tools(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    _, env = await make_incident(session_factory)
    async with Client(build_read_server(backend(settings, session_factory, embedder))) as c:
        gw = McpToolGateway(c, server_name="read", tools=READ_TOOLS, timeout_seconds=5)
        ok = await gw.call("get_service_dependencies", {"environment_id": env, "service": "transaction-api"}, agent="t")
        assert ok.ok and ok.record.status.value == "ok" and ok.data["downstream"]
        bad = await gw.call("execute_remediation", {"action_id": str(uuid.uuid4())}, agent="t")
        assert not bad.ok and bad.record.status.value == "rejected"


async def test_stdio_transport_subprocess(settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    _, env = await make_incident(session_factory)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "opspilot_mcp.cli", "serve", "--profile", "read"], env=dict(os.environ)
    )
    async with Client(params) as c:
        assert c.server_info.name == "opspilot-ops-read"
        res = await c.call_tool("get_service_health", {"environment_id": str(env), "service": "ledger-service"})
    assert not res.is_error and res.structured_content["status"] == "unhealthy"
