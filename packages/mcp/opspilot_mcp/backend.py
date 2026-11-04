"""Adapters the MCP servers sit on top of. Created once per server process."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.config import Settings
from opspilot_shared.db.session import create_engine, create_session_factory
from opspilot_shared.llm.ollama import OllamaEmbedder
from opspilot_simulator.store import SimulatorStore


@dataclass(slots=True)
class OpsBackend:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    store: SimulatorStore
    retriever: HybridRetriever

    @classmethod
    def create(cls, settings: Settings) -> OpsBackend:
        engine = create_engine(settings)
        sf = create_session_factory(engine)
        return cls(settings, engine, sf, SimulatorStore(sf), HybridRetriever(sf, OllamaEmbedder(settings), settings))
