"""C0 item O: each MCP server's database role can do only what its tools need (run on opspilot_test)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

READ_ALLOWED = [
    "SELECT count(*) FROM sim.logs",
    "SELECT count(*) FROM kb.chunks",
    "SELECT count(*) FROM ops.incidents",
    "INSERT INTO kb.retrieval_queries (id, query, mode, top_k, latency_ms, filters, results, warnings) "
    "VALUES (gen_random_uuid(), 'q', 'hybrid', 1, 1.0, '{}', '[]', '[]')",
]
READ_DENIED = [
    "SELECT count(*) FROM ops.action_requests",
    "SELECT count(*) FROM ops.audit_log",
    "SELECT count(*) FROM langgraph.checkpoints",
    "UPDATE sim.environments SET state = state",
    "UPDATE ops.incidents SET status = status",
    "DELETE FROM kb.chunks",
]
ACT_ALLOWED = [
    "SELECT count(*) FROM ops.action_requests",
    "UPDATE ops.action_requests SET status = status WHERE false",
    "UPDATE sim.environments SET state = state WHERE false",
    "SELECT id FROM ops.action_requests LIMIT 1 FOR UPDATE",
]
ACT_DENIED = [
    "UPDATE ops.action_requests SET parameters = parameters WHERE false",
    "UPDATE ops.action_requests SET decided_by = 'x' WHERE false",
    "SELECT count(*) FROM ops.investigations",
    "SELECT count(*) FROM ops.audit_log",
    "INSERT INTO ops.audit_log (actor, action, entity_type, entity_id, details) VALUES ('x','x','x','x','{}')",
    "DELETE FROM sim.action_executions WHERE false",
    "SELECT count(*) FROM langgraph.checkpoints",
]


async def check(settings, user: str, password: str, allowed: list[str], denied: list[str]) -> None:  # type: ignore[no-untyped-def]
    url = f"postgresql+psycopg://{user}:{password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(url)
    try:
        for sql in allowed:
            async with engine.connect() as c:
                await c.execute(text(sql))
                await c.rollback()
        for sql in denied:
            async with engine.connect() as c:
                with pytest.raises(ProgrammingError, match="permission denied"):
                    await c.execute(text(sql))
                await c.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def roles(settings):  # type: ignore[no-untyped-def]
    if not (settings.mcp_read_db_password.get_secret_value() and settings.mcp_actions_db_password.get_secret_value()):
        pytest.skip("MCP roles not provisioned (run scripts/db-roles.sh)")
    assert settings.db_name.endswith("_test")
    return settings


async def test_read_role_privileges(roles) -> None:  # type: ignore[no-untyped-def]
    await check(roles, roles.mcp_read_db_user, roles.mcp_read_db_password.get_secret_value(), READ_ALLOWED, READ_DENIED)


async def test_actions_role_privileges(roles) -> None:  # type: ignore[no-untyped-def]
    await check(
        roles, roles.mcp_actions_db_user, roles.mcp_actions_db_password.get_secret_value(), ACT_ALLOWED, ACT_DENIED
    )
