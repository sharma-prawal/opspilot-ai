"""Shared fixtures. Tests run against the dedicated ``opspilot_test`` database.

The DB name is switched via the environment *before* any settings are loaded, so MCP stdio
children spawned by tests inherit it too.
"""

from __future__ import annotations

import os

os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "opspilot_test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_FORMAT", "console")

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_shared.config import Settings, get_settings
from opspilot_shared.db.session import create_engine, create_session_factory
from tests.fakes.models import HashEmbedder


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-live", action="store_true", help="run tests that need a live Ollama model")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
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
