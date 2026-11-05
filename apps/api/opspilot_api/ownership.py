"""Runtime-enforced single execution owner per database (C0-G4).

Admission capacity, the in-process task registry and LangGraph checkpoint writes are process-local, so exactly one
process may execute investigations against a database. Every runtime (API worker, demo/CLI, evaluation) must hold
the *execution-owner* lock before it opens anything else; a second process fails at start-up with a clear error.

Mechanism: a PostgreSQL **session-level advisory lock** on a dedicated autocommit connection, held for the runtime's
lifetime.
- Robust across independent processes, workers and hosts sharing the database; scoped to that database (advisory
  locks are per-database), so the development API, the test suite (``opspilot_test``) and E2E (its own test DB)
  never contend with each other.
- Released on graceful shutdown (``pg_advisory_unlock``) and **automatically** by PostgreSQL when the owning
  session ends: a crashed or killed process cannot block recovery. TCP keepalives bound how long a silently dead
  peer can keep it.
- No transaction is held: the connection is in autocommit mode and only runs the lock and probe statements, never
  inference.
- A watchdog probes the lock on the same session. If the connection fails or the lock is no longer held, ownership
  is **lost**: the ``on_lost`` callback stops all execution (fail closed). The process never silently continues as
  an unprotected owner.
- Start-up waits briefly (``execution_owner_acquire_timeout_seconds``) so a development reload or a restart right
  after a crash, whose old session the server has not yet reaped, acquires once the old owner is gone.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection

from opspilot_shared.config import Settings
from opspilot_shared.errors import OwnershipError
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)

# pg_try_advisory_lock(int4, int4): fixed namespace + purpose. Visible in pg_locks as classid/objid, objsubid = 2.
LOCK_NAMESPACE = 0x4F505350  # "OPSP"
LOCK_EXECUTION_OWNER = 1
KEEPALIVE: dict[str, Any] = {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3}


__all__ = ["ExecutionOwnership", "OwnershipError", "owner_label", "validate_worker_config"]


def owner_label() -> str:
    return f"opspilot-owner:{socket.gethostname()}:{os.getpid()}"


def validate_worker_config(environ: dict[str, str] | None = None) -> None:
    """Static guard (the lock is the real enforcement): refuse an explicit multi-worker configuration."""
    env = os.environ if environ is None else environ
    raw = env.get("WEB_CONCURRENCY")
    if raw is not None and raw.strip() not in ("", "1"):
        raise OwnershipError(
            f"WEB_CONCURRENCY={raw!r}: OpsPilot supports exactly one API worker per database (single execution "
            "owner); unset it or set it to 1"
        )


class ExecutionOwnership:
    def __init__(
        self,
        settings: Settings,
        *,
        on_lost: Callable[[str], Awaitable[None]] | None = None,
        database: str | None = None,
    ) -> None:
        self._s = settings
        self._db = database or settings.db_name
        self._on_lost = on_lost
        self._conn: AsyncConnection[Any] | None = None
        self._watch: asyncio.Task[None] | None = None
        self.label = owner_label()
        self.held = False
        self.lost_reason: str | None = None

    @property
    def database(self) -> str:
        return self._db

    async def _connect(self) -> AsyncConnection[Any]:
        return await AsyncConnection.connect(
            self._s.libpq_dsn(database=self._db),
            autocommit=True,
            application_name=self.label[:63],
            connect_timeout=5,
            **KEEPALIVE,
        )

    async def holder(self) -> str:
        """Who holds the lock (application name, client address, since), for the error message."""
        try:
            async with await self._connect() as c:
                row = await (
                    await c.execute(
                        "SELECT a.application_name, a.client_addr::text, a.backend_start::text "
                        "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                        "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s AND l.objsubid = 2 "
                        "AND l.granted",
                        (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
                    )
                ).fetchone()
        except Exception as exc:  # pragma: no cover - diagnostic only
            return f"unknown ({exc})"
        return f"{row[0] or 'unnamed'} from {row[1] or 'local socket'} since {row[2]}" if row else "unknown"

    async def acquire(self) -> None:
        conn = await self._connect()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._s.execution_owner_acquire_timeout_seconds
        try:
            while True:
                row = await (
                    await conn.execute("SELECT pg_try_advisory_lock(%s, %s)", (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER))
                ).fetchone()
                if row is not None and row[0]:
                    break
                if loop.time() >= deadline:
                    who = await self.holder()
                    raise OwnershipError(
                        f"another OpsPilot runtime already owns execution for database '{self._db}' ({who}). "
                        "Only one API worker / CLI / evaluation runtime may run against a database at a time; stop "
                        "it first (multi-worker execution is not supported)."
                    )
                await asyncio.sleep(0.25)
        except BaseException:
            await conn.close()
            raise
        self._conn, self.held = conn, True
        self._watch = asyncio.create_task(self._watchdog(), name="execution-owner-watchdog")
        _log.info("execution_owner_acquired", database=self._db, owner=self.label)

    async def _probe(self) -> bool:
        assert self._conn is not None
        row = await (
            await self._conn.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s AND objid = %s "
                "AND objsubid = 2 AND pid = pg_backend_pid() AND granted",
                (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
            )
        ).fetchone()
        return bool(row and row[0])

    async def _watchdog(self) -> None:
        while self.held:
            await asyncio.sleep(self._s.execution_owner_check_seconds)
            try:
                ok = await asyncio.wait_for(self._probe(), timeout=max(2.0, self._s.execution_owner_check_seconds))
                reason = None if ok else "advisory lock no longer held by this session"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason = f"ownership connection failed: {type(exc).__name__}: {exc}"[:500]
            if reason is not None:
                await self._lose(reason)
                return

    async def _lose(self, reason: str) -> None:
        if not self.held:
            return
        self.held, self.lost_reason = False, reason
        _log.error("execution_owner_lost", database=self._db, owner=self.label, reason=reason)
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:  # pragma: no cover - the session is already gone
                _log.debug("execution_owner_close_failed", error=str(exc))
        if self._on_lost is not None:
            try:
                await self._on_lost(reason)
            except Exception:
                _log.exception("execution_owner_lost_handler_failed")

    async def release(self) -> None:
        was_held = self.held
        self.held = False
        if self._watch is not None:
            self._watch.cancel()
            await asyncio.gather(self._watch, return_exceptions=True)
        if self._conn is not None and not self._conn.closed:
            try:
                if was_held:
                    await self._conn.execute(
                        "SELECT pg_advisory_unlock(%s, %s)", (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER)
                    )
            finally:
                await self._conn.close()
        if was_held:
            _log.info("execution_owner_released", database=self._db, owner=self.label)
