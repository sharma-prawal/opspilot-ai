"""Shared fixtures. Tests run against the dedicated ``opspilot_test`` database.

The DB name is switched via the environment *before* any settings are loaded, so MCP stdio
children spawned by tests inherit it too.
"""

from __future__ import annotations

import os

os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "opspilot_test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_FORMAT", "console")

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_shared.config import Settings, get_settings
from opspilot_shared.db.session import create_engine, create_session_factory
from tests.fakes.models import HashEmbedder


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-live", action="store_true", help="run tests that need a live Ollama model")
    parser.addoption(
        "--shuffle-seed",
        type=int,
        default=None,
        help="run tests in a seeded random order (order-independence check, C0-F4)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    seed = config.getoption("--shuffle-seed")
    if seed is not None:
        import random

        random.Random(seed).shuffle(items)
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live (local Ollama models)")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = get_settings()
    assert s.db_name.endswith("_test"), "refusing to run tests against a non-test database"
    return s


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> Settings:
    from opspilot_api.cli import main as cli

    cli(["migrate", "--database", settings.db_name])
    return settings


@pytest.fixture
async def owner(migrated: Settings) -> AsyncIterator[object]:
    """C0-H2: this test owns execution of the test database (advisory lock + fresh epoch), so its checkpoint writes
    and action executions pass the database's owner fence. Do not combine with a test app (it acquires its own)."""
    from opspilot_api.ownership import ExecutionOwnership

    o = ExecutionOwnership(migrated.model_copy(update={"execution_owner_acquire_timeout_seconds": 10}))
    await o.acquire()
    try:
        yield o
    finally:
        await o.release()


@pytest.fixture(scope="session")
async def session_factory(migrated: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(migrated)
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL not reachable ({exc}); run make infra-up")
    yield create_session_factory(engine)
    await engine.dispose()


# Fixtures through which a test reaches the shared test database (directly or via an application stack).
DB_FIXTURES = frozenset({"session_factory", "ingested", "client", "migrated", "owner"})
_stale_work_retired = False


def _run_isolated(settings: Settings, fn: Any) -> Any:
    """Run ``fn(session_factory)`` on its own engine and event loop (fixtures here must not touch the test loop)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    async def main() -> Any:
        engine = create_engine(settings)
        try:
            return await fn(create_session_factory(engine))
        finally:
            await engine.dispose()

    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, main()).result()


@pytest.fixture(autouse=True)
def _owned_test_work(request: pytest.FixtureRequest) -> Iterator[None]:
    """A test owns the workflows it creates (C0-F4): unfinished work from earlier sessions is retired once before
    the first database test, and whatever a test leaves unfinished is retired after it. See tests/isolation.py."""
    global _stale_work_retired
    if not DB_FIXTURES & set(request.fixturenames):
        yield
        return
    from tests.isolation import db_now, retire_unfinished

    settings: Settings = request.getfixturevalue("migrated")
    started = _run_isolated(settings, db_now)
    if not _stale_work_retired:
        _run_isolated(
            settings,
            lambda sf: retire_unfinished(
                sf,
                created_since=None,
                created_before=started,
                reason="retired by the test harness: left unfinished by an earlier test session",
            ),
        )
        _stale_work_retired = True
    yield
    _run_isolated(
        settings,
        lambda sf: retire_unfinished(
            sf,
            created_since=started,
            created_before=None,
            reason=f"retired by the test harness after {request.node.nodeid}",
        ),
    )


@pytest.fixture(scope="session")
def embedder(settings: Settings) -> HashEmbedder:
    return HashEmbedder(settings.embedding_dimensions)


@pytest.fixture(scope="session")
async def ingested(
    session_factory: async_sessionmaker[AsyncSession], embedder: HashEmbedder, settings: Settings
) -> dict[str, object]:
    """Knowledge base in the test DB, embedded with the deterministic hash embedder."""
    from opspilot_rag.ingest import IngestionService

    async with session_factory() as s, s.begin():
        await s.execute(text("TRUNCATE kb.chunks, kb.documents, kb.ingestion_runs, kb.retrieval_queries"))
    report = await IngestionService(session_factory, embedder, settings).ingest_directory()
    return report.as_dict()
