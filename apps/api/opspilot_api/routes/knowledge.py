from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from opspilot_api.deps import Operator, Runtime
from opspilot_api.schemas import IngestRequest, SearchRequest
from opspilot_shared.db.models import KbDocument, KbIngestionRun, KbRetrievalQuery
from opspilot_shared.domain.knowledge import SearchResponse
from opspilot_shared.errors import NotFoundError

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post("/ingest", dependencies=[Operator])
async def ingest(rt: Runtime, body: IngestRequest | None = None) -> dict[str, Any]:
    report = await rt.infra.ingestion().ingest_directory(reindex=bool(body and body.reindex))
    return report.as_dict()


@router.get("/documents")
async def documents(rt: Runtime) -> list[dict[str, Any]]:
    async with rt.infra.session_factory() as s:
        rows = (await s.execute(select(KbDocument).order_by(KbDocument.doc_type, KbDocument.source_uri))).scalars()
        return [
            {
                "id": str(d.id),
                "source_uri": d.source_uri,
                "title": d.title,
                "doc_type": d.doc_type,
                "services": d.services,
                "tags": d.tags,
                "version": d.version,
                "status": d.status,
                "duplicate_of": str(d.duplicate_of) if d.duplicate_of else None,
                "chunk_count": d.chunk_count,
                "content_hash": d.content_hash,
                "embedding_model": d.embedding_model,
                "updated_at": d.updated_at.isoformat(),
            }
            for d in rows
        ]


@router.get("/ingestion-runs")
async def ingestion_runs(rt: Runtime, limit: int = 10) -> list[dict[str, Any]]:
    async with rt.infra.session_factory() as s:
        rows = (
            await s.execute(select(KbIngestionRun).order_by(KbIngestionRun.started_at.desc()).limit(limit))
        ).scalars()
        return [
            {"id": str(r.id), "started_at": r.started_at.isoformat(), "status": r.status, "stats": r.stats}
            for r in rows
        ]


@router.post("/search")
async def search(rt: Runtime, body: SearchRequest) -> SearchResponse:
    return await rt.infra.retriever().search(
        body.query, mode=body.mode, top_k=body.top_k, filters=body.filters, caller="api.knowledge.search"
    )


@router.get("/queries/{query_id}")
async def retrieval_trace(rt: Runtime, query_id: uuid.UUID) -> dict[str, Any]:
    async with rt.infra.session_factory() as s:
        row = await s.get(KbRetrievalQuery, query_id)
    if row is None:
        raise NotFoundError(f"retrieval query {query_id} not found")
    return {
        "id": str(row.id),
        "query": row.query,
        "mode": row.mode,
        "filters": row.filters,
        "top_k": row.top_k,
        "results": row.results,
        "latency_ms": row.latency_ms,
        "caller": row.caller,
        "created_at": row.created_at.isoformat(),
    }
