"""Composition root: builds adapters from Settings. The only place concrete adapters are chosen."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from opspilot_rag.ingest import IngestionService
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.config import Settings
from opspilot_shared.db.session import create_engine, create_session_factory
from opspilot_shared.llm.ollama import OllamaChatModel, OllamaEmbedder
from opspilot_shared.llm.ports import Embedder


@dataclass(slots=True)
class Infrastructure:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    embedder: Embedder
    chat_model: OllamaChatModel

    @classmethod
    def create(
        cls, settings: Settings, *, database: str | None = None, embedder: Embedder | None = None
    ) -> Infrastructure:
        engine = create_engine(settings, database=database)
        sf = create_session_factory(engine)
        return cls(settings, engine, sf, embedder or OllamaEmbedder(settings), OllamaChatModel(settings))

    def ingestion(self) -> IngestionService:
        return IngestionService(self.session_factory, self.embedder, self.settings)

    def retriever(self) -> HybridRetriever:
        return HybridRetriever(self.session_factory, self.embedder, self.settings)

    async def aclose(self) -> None:
        close = getattr(self.embedder, "aclose", None)
        if close is not None:
            await close()
        await self.chat_model.aclose()
        await self.engine.dispose()
