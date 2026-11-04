from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from opspilot_shared.config import Settings


def create_engine(settings: Settings, *, database: str | None = None) -> AsyncEngine:
    return create_async_engine(
        settings.database_url(database=database),
        pool_size=settings.db_pool_size,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        yield session
