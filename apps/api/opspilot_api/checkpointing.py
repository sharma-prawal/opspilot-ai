"""LangGraph Postgres checkpointer lifecycle.

Checkpoint tables live in the ``langgraph`` schema (search_path set per connection). The
serializer is constructed in strict mode explicitly so safety does not depend on import-time env.

Fencing (C0-H2): every write to a checkpoint table fires ``ops.fence_checkpoint_write()`` (statement level, same
transaction as the write), which accepts it only if the connection was opened with the *current* execution-owner
fence (``opspilot.owner_epoch`` / ``opspilot.owner_pid``) and that owner's lock session is alive. A pool opened
without a fence can read checkpoints but cannot write them; a stale owner's writes fail as soon as its lock session is
gone, before any watchdog notices, and can never interleave with a newer owner's writes.
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

CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")

CONNECTION_KWARGS: dict[str, Any] = {
    "autocommit": True,  # required by AsyncPostgresSaver (setup + writes)
    "row_factory": dict_row,  # saver reads rows by column name
    "prepare_threshold": 0,
    "options": f"-c search_path={LANGGRAPH_SCHEMA}",
}


def strict_serde() -> JsonPlusSerializer:
    # allowed_msgpack_modules=None → only LangGraph's safe built-in types deserialize.
    return JsonPlusSerializer(allowed_msgpack_modules=None)


def fenced_kwargs(fence: tuple[int, int] | None) -> dict[str, Any]:
    """Connection kwargs binding the owner's fence ``(epoch, lock-session pid)`` to every pooled connection."""
    if fence is None:
        return CONNECTION_KWARGS
    epoch, pid = (int(x) for x in fence)
    return {
        **CONNECTION_KWARGS,
        "options": f"{CONNECTION_KWARGS['options']} -c opspilot.owner_epoch={epoch} -c opspilot.owner_pid={pid}",
    }


@asynccontextmanager
async def checkpointer_pool(
    settings: Settings,
    *,
    database: str | None = None,
    max_size: int = 4,
    fence: tuple[int, int] | None = None,
) -> AsyncIterator[AsyncPostgresSaver]:
    """``fence``: the execution owner's ``(epoch, pid)`` (``ExecutionOwnership.fence``). Without it the saver is
    read-only in effect: the database refuses its checkpoint writes."""
    pool: AsyncConnectionPool[AsyncConnection[dict[str, object]]] = AsyncConnectionPool(
        conninfo=settings.libpq_dsn(database=database),
        min_size=1,
        max_size=max_size,
        kwargs=fenced_kwargs(fence),
        open=False,
    )
    await pool.open(wait=True, timeout=15)
    try:
        yield AsyncPostgresSaver(pool, serde=strict_serde())  # type: ignore[arg-type]
    finally:
        await pool.close()


async def setup_checkpointer(settings: Settings, *, database: str | None = None) -> None:
    """Create/upgrade checkpoint tables and install the write fence. Called by ``opspilot migrate``, not at start-up."""
    async with await AsyncConnection.connect(settings.libpq_dsn(database=database), **CONNECTION_KWARGS) as conn:
        await AsyncPostgresSaver(conn, serde=strict_serde()).setup()  # type: ignore[arg-type]
        await install_fencing(conn)


async def install_fencing(conn: AsyncConnection[Any]) -> None:
    """Idempotent: one statement-level BEFORE trigger per checkpoint table (function from migration 0008)."""
    for table in CHECKPOINT_TABLES:
        await conn.execute(
            f"CREATE OR REPLACE TRIGGER trg_fence_{table} BEFORE INSERT OR UPDATE OR DELETE "
            f"ON {LANGGRAPH_SCHEMA}.{table} FOR EACH STATEMENT EXECUTE FUNCTION ops.fence_checkpoint_write()"
        )


async def fencing_installed(conn: AsyncConnection[Any]) -> bool:
    row = await (
        await conn.execute(
            "SELECT count(*) AS n FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND t.tgname = ANY(%s) AND NOT t.tgisinternal",
            (LANGGRAPH_SCHEMA, [f"trg_fence_{t}" for t in CHECKPOINT_TABLES]),
        )
    ).fetchone()
    count = row["n"] if isinstance(row, dict) else (row[0] if row else 0)
    return int(count) == len(CHECKPOINT_TABLES)
