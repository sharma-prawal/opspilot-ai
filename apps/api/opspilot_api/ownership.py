"""Runtime-enforced single execution owner per database (C0-G4), with lifecycle and write fencing (C0-H2).

Admission capacity, the in-process task registry and LangGraph checkpoint writes are process-local, so exactly one
process may execute investigations against a database. Every runtime (API worker, demo/CLI, evaluation) must own
execution before it opens anything else; a second process fails at start-up with a clear error.

**Ownership** is a PostgreSQL session-level advisory lock on a dedicated autocommit connection, held for the
runtime's lifetime, plus a database **epoch**:
- The lock is per database, so the development API, the test suite and E2E (``opspilot_test``) never contend. It is
  released on graceful shutdown and automatically by PostgreSQL when the owning session ends (crash, SIGKILL, network
  loss once detected by the server); TCP keepalives bound how long a silently dead peer keeps it.
- Right after taking the lock the owner increments ``ops.execution_owner.epoch`` and records its lock session's PID.
  ``(epoch, pid)`` is this owner's **fence**. Writes that matter call ``ops.execution_fence(epoch, pid)`` in their own
  transaction (checkpoint tables via trigger, runner state writes, the action server's execution claim). It takes
  ``FOR SHARE`` on the epoch row, so a new owner's increment waits for in-flight fenced writes and every later write of
  the old owner fails; and it fails as soon as the old lock session is gone, without waiting for any watchdog.
- No transaction is held between statements; nothing spans inference.

**Lifecycle** (``RuntimeLifecycle``): ``INITIALIZING → ACQUIRING_OWNERSHIP → READY → OWNERSHIP_LOST → STOPPING →
STOPPED``. Only ``READY`` accepts or executes work. ``READY`` is entered only after initialization has finished *and* an
affirmative fence check succeeded; ``OWNERSHIP_LOST`` is sticky and is entered synchronously (no ``await`` before the
state changes and the listeners have run), whether the loss is noticed by the watchdog or by a write the database
refused. Listeners stop admission, cancel running segments and stop background maintenance; the served API then
exits. Loss before ``READY`` makes runtime start-up fail (C0-H2: the independent audit's N1).
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from enum import StrEnum
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
FENCE_SQLSTATE = "OPF01"  # raised by ops.execution_fence (migration 0008)

__all__ = [
    "ExecutionOwnership",
    "OwnershipError",
    "RuntimeLifecycle",
    "RuntimeState",
    "is_fence_violation",
    "owner_label",
    "validate_worker_config",
]


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


def is_fence_violation(exc: BaseException | None) -> bool:
    """True if ``exc`` (or anything it wraps) is the database refusing a write from a non-owner."""
    seen = 0
    while exc is not None and seen < 8:
        if getattr(exc, "sqlstate", None) == FENCE_SQLSTATE or getattr(exc, "pgcode", None) == FENCE_SQLSTATE:
            return True
        if "execution fence:" in str(exc):
            return True
        exc = getattr(exc, "orig", None) or exc.__cause__ or exc.__context__
        seen += 1
    return False


# ----------------------------------------------------------------------------- lifecycle
class RuntimeState(StrEnum):
    INITIALIZING = "initializing"
    ACQUIRING_OWNERSHIP = "acquiring_ownership"
    READY = "ready"
    OWNERSHIP_LOST = "ownership_lost"
    STOPPING = "stopping"
    STOPPED = "stopped"


_S = RuntimeState
ALLOWED: dict[RuntimeState, frozenset[RuntimeState]] = {
    _S.INITIALIZING: frozenset({_S.ACQUIRING_OWNERSHIP, _S.STOPPING}),
    _S.ACQUIRING_OWNERSHIP: frozenset({_S.READY, _S.OWNERSHIP_LOST, _S.STOPPING}),
    _S.READY: frozenset({_S.OWNERSHIP_LOST, _S.STOPPING}),
    _S.OWNERSHIP_LOST: frozenset({_S.STOPPING}),
    _S.STOPPING: frozenset({_S.STOPPED}),
    _S.STOPPED: frozenset(),
}


class RuntimeLifecycle:
    """Single source of truth for whether this process may execute. Transitions and listeners are synchronous."""

    def __init__(self) -> None:
        self.state = RuntimeState.INITIALIZING
        self.reason: str | None = None
        self.lost = False  # sticky: once ownership was lost, this runtime never becomes READY again
        self._listeners: list[Callable[[RuntimeState, str | None], None]] = []

    @property
    def ready(self) -> bool:
        return self.state is RuntimeState.READY

    def on_change(self, listener: Callable[[RuntimeState, str | None], None]) -> None:
        self._listeners.append(listener)

    def transition(self, to: RuntimeState, reason: str | None = None) -> bool:
        frm = self.state
        if to is frm:
            return False
        if to is RuntimeState.OWNERSHIP_LOST:
            self.lost = True  # recorded even if the runtime is already stopping
        if to not in ALLOWED[frm]:
            _log.warning("runtime_transition_ignored", current=frm.value, target=to.value, reason=reason)
            return False
        if to is RuntimeState.READY and self.lost:
            return False
        self.state, self.reason = to, reason
        log = _log.error if to is RuntimeState.OWNERSHIP_LOST else _log.info
        log("runtime_state_changed", previous=frm.value, state=to.value, reason=reason)
        for listener in list(self._listeners):
            try:
                listener(to, reason)
            except Exception:  # a listener must never block the transition
                _log.exception("runtime_state_listener_failed", state=to.value)
        return True

    def require_ready(self, what: str = "work") -> None:
        if not self.ready:
            raise OwnershipError(
                f"runtime is {self.state.value}; refusing {what}" + (f" ({self.reason})" if self.reason else "")
            )


# ----------------------------------------------------------------------------- ownership
class ExecutionOwnership:
    def __init__(
        self,
        settings: Settings,
        *,
        on_lost: Callable[[str], Awaitable[None]] | None = None,
        database: str | None = None,
        lifecycle: RuntimeLifecycle | None = None,
    ) -> None:
        self._s = settings
        self._db = database or settings.db_name
        self._on_lost = on_lost
        self._conn: AsyncConnection[Any] | None = None
        self._watch: asyncio.Task[None] | None = None
        self._after_loss: asyncio.Task[None] | None = None
        self.lifecycle = lifecycle or RuntimeLifecycle()
        self.label = owner_label()
        self.held = False
        self.lost_reason: str | None = None
        self.epoch: int | None = None
        self.pid: int | None = None

    @property
    def database(self) -> str:
        return self._db

    @property
    def fence(self) -> tuple[int, int] | None:
        """``(epoch, lock-session pid)`` while held; None otherwise."""
        if not self.held or self.epoch is None or self.pid is None:
            return None
        return self.epoch, self.pid

    async def _connect(self, *, name: str | None = None) -> AsyncConnection[Any]:
        return await AsyncConnection.connect(
            self._s.libpq_dsn(database=self._db),
            autocommit=True,
            application_name=(name or self.label)[:63],
            connect_timeout=5,
            **KEEPALIVE,
        )

    async def holder(self) -> str:
        """Who holds the lock (application name, client address, since), for the error message."""
        try:
            async with await self._connect(name="opspilot-owner-probe") as c:
                row = await (
                    await c.execute(
                        "SELECT a.application_name, a.client_addr::text, a.backend_start::text "
                        "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                        "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s AND l.objsubid = 2 "
                        "AND l.granted "
                        "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())",
                        (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
                    )
                ).fetchone()
        except Exception as exc:  # pragma: no cover - diagnostic only
            return f"unknown ({exc})"
        return f"{row[0] or 'unnamed'} from {row[1] or 'local socket'} since {row[2]}" if row else "unknown"

    async def acquire(self) -> None:
        self.lifecycle.transition(RuntimeState.ACQUIRING_OWNERSHIP)
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
            # New epoch, bound to this lock session. Waits for any in-flight fenced write of a previous owner.
            try:
                bumped = await (
                    await conn.execute(
                        "UPDATE ops.execution_owner SET epoch = epoch + 1, owner = %s, owner_pid = pg_backend_pid(), "
                        "acquired_at = now() WHERE id = 1 RETURNING epoch, owner_pid",
                        (self.label,),
                    )
                ).fetchone()
            except Exception as exc:
                raise OwnershipError(
                    f"execution-owner fencing is not installed in '{self._db}' ({type(exc).__name__}); "
                    "run `make migrate`"
                ) from exc
            if bumped is None:
                raise OwnershipError(f"execution-owner row missing in '{self._db}'; run `make migrate`")
        except BaseException:
            await conn.close()
            raise
        self._conn, self.held = conn, True
        self.epoch, self.pid = int(bumped[0]), int(bumped[1])
        self._watch = asyncio.create_task(self._watchdog(), name="execution-owner-watchdog")
        _log.info("execution_owner_acquired", database=self._db, owner=self.label, epoch=self.epoch)

    async def verify(self) -> None:
        """Affirmative check through an ordinary connection: this owner's fence is current and its lock session is
        alive. Raises ``OwnershipError`` (and records the loss) otherwise."""
        fence = self.fence
        if fence is None:
            raise OwnershipError(f"execution ownership not held ({self.lost_reason or 'never acquired'})")
        try:
            async with await self._connect(name="opspilot-owner-verify") as c:
                await c.execute("SELECT ops.execution_fence(%s, %s)", fence)
        except Exception as exc:
            reason = f"fence verification failed: {type(exc).__name__}: {exc}"[:500]
            self.lose_now(reason)
            raise OwnershipError(reason) from exc

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
                self.lose_now(reason)
                return

    def lose_now(self, reason: str) -> None:
        """Synchronous part of a loss: state and listeners change before anything else can run. Idempotent.
        Called by the watchdog, by ``verify``, and by any writer whose fenced write the database refused."""
        if not self.held and self.lost_reason is not None:
            return
        self.held, self.lost_reason = False, reason
        _log.error("execution_owner_lost", database=self._db, owner=self.label, epoch=self.epoch, reason=reason)
        self.lifecycle.transition(RuntimeState.OWNERSHIP_LOST, reason)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop: nothing asynchronous to finish
            return
        self._after_loss = loop.create_task(self._finish_loss(reason), name="execution-owner-loss")

    async def _finish_loss(self, reason: str) -> None:
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
        if self._after_loss is not None:
            await asyncio.gather(self._after_loss, return_exceptions=True)
        if self._conn is not None and not self._conn.closed:
            try:
                if was_held:
                    await self._conn.execute(
                        "SELECT pg_advisory_unlock(%s, %s)", (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER)
                    )
            finally:
                await self._conn.close()
        if was_held:
            _log.info("execution_owner_released", database=self._db, owner=self.label, epoch=self.epoch)
