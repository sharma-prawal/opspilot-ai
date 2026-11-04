"""Reranking seam. The default is a no-op; a cross-encoder or LLM reranker can be added later."""

from __future__ import annotations

from typing import Protocol

from opspilot_shared.domain.knowledge import RetrievedChunk


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class NoopReranker:
    name = "noop"

    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return chunks
