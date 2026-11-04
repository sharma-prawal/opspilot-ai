"""Hybrid retrieval: pgvector cosine search + PostgreSQL full-text search fused with RRF."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, Text, func, select, text
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_rag.reranker import NoopReranker, Reranker
from opspilot_shared.config import Settings
from opspilot_shared.db.models import KbChunk, KbDocument, KbRetrievalQuery
from opspilot_shared.domain.knowledge import (
    DocType,
    RetrievalFilters,
    RetrievalMode,
    RetrievedChunk,
    SearchResponse,
)
from opspilot_shared.errors import EmbeddingError
from opspilot_shared.llm.ports import Embedder
from opspilot_shared.logging import get_logger
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
_TERM = re.compile(r"[A-Za-z0-9_]{2,}")
SNIPPET_CHARS = 700
OVERFETCH = 4


@dataclass(frozen=True, slots=True)
class _Hit:
    chunk: KbChunk
    document: KbDocument
    rank: int
    raw_score: float


def keyword_query(query: str, max_terms: int = 24) -> str | None:
    """OR-combined tsquery source. Only ``[A-Za-z0-9_]`` survives, so no tsquery syntax injection."""
    seen: list[str] = []
    for term in _TERM.findall(query.lower()):
        if term not in seen:
            seen.append(term)
    return " | ".join(seen[:max_terms]) or None


def rrf_fuse(rankings: list[list[uuid.UUID]], k: int) -> dict[uuid.UUID, float]:
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        settings: Settings,
        reranker: Reranker | None = None,
    ) -> None:
        self._sf = session_factory
        self._embedder = embedder
        self._s = settings
        self._reranker = reranker or NoopReranker()

    @staticmethod
    def _filtered(stmt: Select[Any], filters: RetrievalFilters | None) -> Select[Any]:
        stmt = stmt.where(KbDocument.status == "active")
        if filters is None:
            return stmt
        if filters.doc_types:
            stmt = stmt.where(KbDocument.doc_type.in_([d.value for d in filters.doc_types]))
        if filters.services:
            stmt = stmt.where(KbDocument.services.has_any(array(filters.services, type_=Text)))
        if filters.tags:
            stmt = stmt.where(KbDocument.tags.has_any(array(filters.tags, type_=Text)))
        return stmt

    async def _vector(self, session: AsyncSession, query: str, n: int, filters: RetrievalFilters | None) -> list[_Hit]:
        qvec = await self._embedder.embed_query(query)
        await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = KbChunk.embedding.cosine_distance(qvec).label("distance")
        stmt = (
            self._filtered(
                select(KbChunk, KbDocument, distance).join(KbDocument, KbChunk.document_id == KbDocument.id), filters
            )
            .order_by(distance)
            .limit(n)
        )
        rows = (await session.execute(stmt)).all()
        return [_Hit(c, d, i, 1.0 - float(dist)) for i, (c, d, dist) in enumerate(rows, start=1)]

    async def _keyword(self, session: AsyncSession, query: str, n: int, filters: RetrievalFilters | None) -> list[_Hit]:
        source = keyword_query(query)
        if source is None:
            return []
        tsq = func.to_tsquery("english", source)
        rank = func.ts_rank_cd(KbChunk.tsv, tsq).label("rank")
        stmt = (
            self._filtered(
                select(KbChunk, KbDocument, rank)
                .join(KbDocument, KbChunk.document_id == KbDocument.id)
                .where(KbChunk.tsv.op("@@")(tsq)),
                filters,
            )
            .order_by(rank.desc(), KbChunk.id)
            .limit(n)
        )
        rows = (await session.execute(stmt)).all()
        return [_Hit(c, d, i, float(r)) for i, (c, d, r) in enumerate(rows, start=1)]

    @staticmethod
    def _to_result(hit: _Hit, score: float, vrank: int | None, krank: int | None) -> RetrievedChunk:
        c, d = hit.chunk, hit.document
        return RetrievedChunk(
            chunk_id=c.id,
            document_id=d.id,
            document_version=c.document_version,
            source_uri=d.source_uri,
            title=d.title,
            doc_type=DocType(d.doc_type),
            heading_path=c.heading_path,
            snippet=c.content[:SNIPPET_CHARS],
            score=round(score, 6),
            vector_rank=vrank,
            keyword_rank=krank,
            metadata={"services": d.services, "tags": d.tags, "ordinal": c.ordinal},
        )

    async def search(
        self,
        query: str,
        *,
        mode: RetrievalMode = RetrievalMode.HYBRID,
        top_k: int | None = None,
        filters: RetrievalFilters | None = None,
        caller: str | None = None,
        record: bool = True,
    ) -> SearchResponse:
        top_k = top_k or self._s.retrieval_top_k
        n = top_k * OVERFETCH
        t0 = time.perf_counter()
        with _tracer.start_as_current_span("rag.search") as span:
            span.set_attribute("rag.mode", mode.value)
            span.set_attribute("rag.top_k", top_k)
            warnings: list[str] = []
            async with self._sf() as session, session.begin():
                vhits: list[_Hit] = []
                if mode != RetrievalMode.KEYWORD:
                    try:
                        vhits = await self._vector(session, query, n, filters)
                    except EmbeddingError as exc:
                        if mode == RetrievalMode.VECTOR:
                            raise
                        # Hybrid degrades to keyword-only rather than failing the caller; surfaced as a warning.
                        warnings.append(f"vector retrieval unavailable, keyword-only results: {exc}")
                        span.set_attribute("rag.degraded", True)
                        _log.warning("retrieval_degraded", reason=str(exc))
                khits = await self._keyword(session, query, n, filters) if mode != RetrievalMode.VECTOR else []

            by_id = {h.chunk.id: h for h in [*khits, *vhits]}
            vrank = {h.chunk.id: h.rank for h in vhits}
            krank = {h.chunk.id: h.rank for h in khits}
            if mode == RetrievalMode.VECTOR:
                ordered = [(h.chunk.id, h.raw_score) for h in vhits]
            elif mode == RetrievalMode.KEYWORD:
                ordered = [(h.chunk.id, h.raw_score) for h in khits]
            else:
                fused = rrf_fuse([[h.chunk.id for h in vhits], [h.chunk.id for h in khits]], self._s.retrieval_rrf_k)
                ordered = sorted(fused.items(), key=lambda kv: (-kv[1], str(kv[0])))
            results = [self._to_result(by_id[cid], s, vrank.get(cid), krank.get(cid)) for cid, s in ordered[:top_k]]
            results = await self._reranker.rerank(query, results)
            latency = round((time.perf_counter() - t0) * 1000, 2)
            span.set_attribute("rag.results", len(results))

        query_id = uuid.uuid4()
        if record:
            async with self._sf() as session, session.begin():
                session.add(
                    KbRetrievalQuery(
                        id=query_id,
                        query=query[:4000],
                        mode=mode.value,
                        top_k=top_k,
                        latency_ms=latency,
                        caller=caller,
                        warnings=warnings,
                        filters=filters.model_dump(mode="json", exclude_none=True) if filters else {},
                        results=[
                            {
                                "chunk_id": str(r.chunk_id),
                                "document_id": str(r.document_id),
                                "score": r.score,
                                "vector_rank": r.vector_rank,
                                "keyword_rank": r.keyword_rank,
                            }
                            for r in results
                        ],
                    )
                )
        _log.info(
            "retrieval",
            query_id=str(query_id),
            mode=mode.value,
            results=len(results),
            latency_ms=latency,
            caller=caller,
        )
        return SearchResponse(
            query_id=query_id, query=query, mode=mode, results=results, latency_ms=latency, warnings=warnings
        )
