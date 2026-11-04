"""LangGraph Postgres checkpointer lifecycle.

Checkpoint tables live in the ``langgraph`` schema (search_path set per connection). The
serializer is constructed in strict mode explicitly so safety does not depend on import-time env.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from opspilot_shared.config import Settings
from opspilot_shared.db.base import LANGGRAPH_SCHEMA

CONNECTION_KWARGS: dict[str, Any] = {
    "autocommit": True,  # required by AsyncPostgresSaver (setup + writes)
    "row_factory": dict_row,  # saver reads rows by column name
    "prepare_threshold": 0,
    "options": f"-c search_path={LANGGRAPH_SCHEMA}",
}


def strict_serde() -> JsonPlusSerializer:
    # allowed_msgpack_modules=None → only LangGraph's safe built-in types deserialize.
    return JsonPlusSerializer(allowed_msgpack_modules=None)


@asynccontextmanager
async def checkpointer_pool(
    settings: Settings, *, database: str | None = None, max_size: int = 4
) -> AsyncIterator[AsyncPostgresSaver]:
    pool: AsyncConnectionPool[AsyncConnection[dict[str, object]]] = AsyncConnectionPool(
        conninfo=settings.libpq_dsn(database=database),
        min_size=1,
        max_size=max_size,
        kwargs=CONNECTION_KWARGS,
        open=False,
    )
    await pool.open(wait=True, timeout=15)
    try:
        yield AsyncPostgresSaver(pool, serde=strict_serde())  # type: ignore[arg-type]
    finally:
        await pool.close()


async def setup_checkpointer(settings: Settings, *, database: str | None = None) -> None:
    """Create/upgrade checkpoint tables. Called by ``opspilot migrate``, not at app start-up."""
    async with await AsyncConnection.connect(settings.libpq_dsn(database=database), **CONNECTION_KWARGS) as conn:
        await AsyncPostgresSaver(conn, serde=strict_serde()).setup()  # type: ignore[arg-type]
