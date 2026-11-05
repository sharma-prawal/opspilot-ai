"""C0-G4 regression: one execution owner per database, enforced at runtime (real PostgreSQL, real processes).

The independent audit showed that `WEB_CONCURRENCY=2` gave the launcher two Uvicorn workers and that CLI/evaluation
runtimes could coexist with the API against one database, although admission and checkpoint writes are
process-local. Every runtime now takes a session-level advisory lock first; these tests exercise contention, races,
crashes, connection loss, graceful release, reload overlap and the fail-closed behaviour of a runtime that loses it.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from psycopg import AsyncConnection

from opspilot_api.main import create_app
from opspilot_api.ownership import (
    LOCK_EXECUTION_OWNER,
    LOCK_NAMESPACE,
    ExecutionOwnership,
    OwnershipError,
    validate_worker_config,
)
from opspilot_shared.config import Settings
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def fast(settings: Settings, **kw: float) -> Settings:
    return settings.model_copy(
        update={"execution_owner_acquire_timeout_seconds": 0, "execution_owner_check_seconds": 0.2, **kw}
    )


async def holders(settings: Settings) -> list[tuple[int, str]]:
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        rows = await (
            await c.execute(
                "SELECT l.pid, a.application_name FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s AND l.objsubid = 2 AND l.granted "
                "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())",
                (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
            )
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


async def terminate(settings: Settings, pid: int) -> None:
    async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
        await c.execute("SELECT pg_terminate_backend(%s)", (pid,))


@pytest.fixture
async def free(settings: Settings) -> AsyncIterator[None]:
    assert settings.db_name.endswith("_test")
    assert await holders(settings) == [], "another runtime owns the test database (E2E or a second suite running?)"
    yield
    assert await holders(settings) == [], "an owner leaked past its test"


# ----------------------------------------------------------------------------- contention and races
async def test_second_owner_is_refused_with_a_clear_error(settings, free) -> None:  # type: ignore[no-untyped-def]
    first, second = ExecutionOwnership(fast(settings)), ExecutionOwnership(fast(settings))
    await first.acquire()
    try:
        with pytest.raises(OwnershipError, match="already owns execution") as err:
            await second.acquire()
        assert first.label in str(err.value) and settings.db_name in str(err.value)
        assert second.held is False and [n for _, n in await holders(settings)] == [first.label]
    finally:
        await first.release()


async def test_startup_race_has_exactly_one_winner(settings, free) -> None:  # type: ignore[no-untyped-def]
    owners = [ExecutionOwnership(fast(settings)) for _ in range(6)]
    results = await asyncio.gather(*(o.acquire() for o in owners), return_exceptions=True)
    try:
        assert sum(r is None for r in results) == 1
        assert all(isinstance(r, OwnershipError) for r in results if r is not None)
        assert len(await holders(settings)) == 1
    finally:
        for o in owners:
            await o.release()


async def test_lock_is_scoped_to_the_database(settings, free) -> None:  # type: ignore[no-untyped-def]
    """The lock row names this database's OID: the dev API (``opspilot``) and the test/E2E database never contend."""
    owner = ExecutionOwnership(fast(settings))
    await owner.acquire()
    try:
        async with await AsyncConnection.connect(settings.libpq_dsn(), autocommit=True) as c:
            dbs = await (
                await c.execute(
                    "SELECT DISTINCT d.datname FROM pg_locks l JOIN pg_database d ON d.oid = l.database "
                    "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s",
                    (LOCK_NAMESPACE, LOCK_EXECUTION_OWNER),
                )
            ).fetchall()
        assert settings.db_name in {r[0] for r in dbs}
    finally:
        await owner.release()


# ----------------------------------------------------------------------------- lifecycle
async def test_graceful_release_and_reload_overlap(settings, free) -> None:  # type: ignore[no-untyped-def]
    """Development reload / restart: the new process waits for the old owner to release, then acquires."""
    old = ExecutionOwnership(fast(settings))
    await old.acquire()
    new = ExecutionOwnership(fast(settings, execution_owner_acquire_timeout_seconds=10))
    waiting = asyncio.create_task(new.acquire())
    await asyncio.sleep(0.6)
    assert not waiting.done()  # still waiting for the previous owner
    await old.release()
    await asyncio.wait_for(waiting, 10)
    try:
        assert new.held and [n for _, n in await holders(settings)] == [new.label]
    finally:
        await new.release()


HOLDER = textwrap.dedent(
    """
    import asyncio, sys
    from opspilot_api.ownership import ExecutionOwnership
    from opspilot_shared.config import get_settings
    async def main():
        o = ExecutionOwnership(get_settings())
        await o.acquire()
        print("held", flush=True)
        await asyncio.sleep(120)
    asyncio.run(main())
    """
)


async def test_independent_process_blocks_and_a_crash_releases(settings, free) -> None:  # type: ignore[no-untyped-def]
    env = {**os.environ, "DB_NAME": settings.db_name, "PYTHONPATH": str(ROOT)}
    # A real, independent OS process is the point of this test.
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        assert proc.stdout is not None
        out = proc.stdout

        def wait_held() -> str:
            seen = ""
            for line in out:  # log lines precede the marker
                seen += line
                if line.strip() == "held":
                    return "held"
            return seen

        assert await asyncio.wait_for(asyncio.to_thread(wait_held), 30) == "held"
        with pytest.raises(OwnershipError, match="already owns execution"):
            await ExecutionOwnership(fast(settings)).acquire()
    finally:
        proc.send_signal(signal.SIGKILL)  # abnormal termination: no unlock, no graceful shutdown
        await asyncio.to_thread(proc.wait, 10)
    recovered = ExecutionOwnership(fast(settings, execution_owner_acquire_timeout_seconds=15))
    await recovered.acquire()  # PostgreSQL released the dead session's lock: recovery is never blocked
    await recovered.release()


async def test_connection_loss_is_detected_and_fails_closed(settings, free) -> None:  # type: ignore[no-untyped-def]
    lost: list[str] = []

    async def on_lost(reason: str) -> None:
        lost.append(reason)

    owner = ExecutionOwnership(fast(settings), on_lost=on_lost)
    await owner.acquire()
    [(pid, _)] = await holders(settings)
    await terminate(settings, pid)  # the owning session dies (database restart / network loss)
    for _ in range(50):
        if lost:
            break
        await asyncio.sleep(0.1)
    assert lost and "connection failed" in lost[0] and owner.held is False and owner.lost_reason
    await owner.release()  # idempotent after loss
    assert await holders(settings) == []


# ----------------------------------------------------------------------------- the runtime and the API
async def test_runtime_refuses_work_after_losing_ownership(settings, session_factory, embedder, ingested, free) -> None:  # type: ignore[no-untyped-def]
    s = fast(settings)
    app = create_app(
        s, chat=ScriptedChatModel(), embedder=embedder, gateways=inprocess_gateways(s, session_factory, embedder)
    )
    second = create_app(
        s, chat=ScriptedChatModel(), embedder=embedder, gateways=inprocess_gateways(s, session_factory, embedder)
    )
    headers = {"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"}
    async with app.router.lifespan_context(app):
        # A second API "worker" on the same database cannot start.
        with pytest.raises(OwnershipError, match="already owns execution"):
            async with second.router.lifespan_context(second):
                pass  # pragma: no cover
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers) as c:
            ready = (await c.get("/health/dependencies")).json()["checks"]["execution_owner"]
            assert ready["ok"] is True and ready["database"] == settings.db_name
            [(pid, _)] = await holders(settings)
            await terminate(settings, pid)
            rt = app.state.runtime
            for _ in range(50):
                if rt.runner.suspended:
                    break
                await asyncio.sleep(0.1)
            assert rt.runner.suspended and not rt.ownership.held
            inc = (await c.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
            r = await c.post(f"/api/v1/incidents/{inc['id']}/investigations")
            assert r.status_code == 503 and r.json()["error"]["class"] == "execution_owner_unavailable"
            assert (await c.get("/health/dependencies")).json()["checks"]["execution_owner"]["ok"] is False


def test_explicit_multi_worker_configuration_is_refused() -> None:
    for value in ("2", "4", " 3 "):
        with pytest.raises(OwnershipError, match="exactly one API worker"):
            validate_worker_config({"WEB_CONCURRENCY": value})
    for ok in ({}, {"WEB_CONCURRENCY": "1"}, {"WEB_CONCURRENCY": ""}):
        validate_worker_config(ok)


def test_launchers_pin_a_single_worker() -> None:
    for script in ("scripts/start.sh", "scripts/e2e-api.sh"):
        text = (ROOT / script).read_text()
        assert "--workers 1" in text and "env -u WEB_CONCURRENCY" in text, script
