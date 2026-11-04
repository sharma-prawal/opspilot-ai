"""Incremental knowledge ingestion.

discover → parse → normalise → metadata → hash/dedup → chunk → embed → store (one txn per doc).
Unchanged documents are skipped without embedding calls; byte-identical content under another
path is recorded as a duplicate and not embedded.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_rag.chunking import chunk_markdown, embedding_text
from opspilot_rag.parsing import ParsedDocument, discover, parser_for
from opspilot_shared.config import Settings
from opspilot_shared.db.models import KbChunk, KbDocument, KbIngestionRun
from opspilot_shared.domain.common import utcnow
from opspilot_shared.errors import OpsPilotError
from opspilot_shared.ids import content_hash, stable_uuid
from opspilot_shared.llm.ports import Embedder
from opspilot_shared.logging import get_logger
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)


class Outcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(slots=True)
class ItemReport:
    source_uri: str
    outcome: Outcome
    document_id: str | None = None
    version: int | None = None
    chunks: int = 0
    duplicate_of: str | None = None
    error: str | None = None


@dataclass(slots=True)
class IngestionReport:
    run_id: str
    status: str
    duration_ms: float
    items: list[ItemReport] = field(default_factory=list)

    @property
    def stats(self) -> dict[str, int]:
        out = {o.value: 0 for o in Outcome}
        for item in self.items:
            out[item.outcome.value] += 1
        out["chunks_written"] = sum(i.chunks for i in self.items if i.outcome in (Outcome.CREATED, Outcome.UPDATED))
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "stats": self.stats,
            "items": [asdict(i) for i in self.items],
        }


def document_id_for(source_uri: str) -> uuid.UUID:
    return stable_uuid("kb-document", source_uri)


def document_hash(doc: ParsedDocument) -> str:
    return content_hash(
        {
            "title": doc.title,
            "doc_type": doc.doc_type.value,
            "body": doc.body,
            "services": doc.services,
            "tags": doc.tags,
        }
    )


class IngestionService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], embedder: Embedder, settings: Settings
    ) -> None:
        self._sf = session_factory
        self._embedder = embedder
        self._s = settings

    async def ingest_directory(self, root: Path | None = None, *, reindex: bool = False) -> IngestionReport:
        root = (root or self._s.knowledge_dir).resolve()
        run_id = uuid.uuid4()
        t0 = time.perf_counter()
        started = utcnow()
        report = IngestionReport(run_id=str(run_id), status="running", duration_ms=0)
        with _tracer.start_as_current_span("rag.ingest") as span:
            files = discover(root)
            span.set_attribute("rag.files", len(files))
            for path in files:
                source_uri = path.relative_to(root).as_posix()
                try:
                    report.items.append(await self._ingest_file(path, source_uri, reindex=reindex))
                except OpsPilotError as exc:
                    _log.warning("ingest_failed", source_uri=source_uri, error=str(exc))
                    report.items.append(ItemReport(source_uri, Outcome.FAILED, error=str(exc)))
                except Exception as exc:  # one bad file must not abort the run
                    _log.exception("ingest_failed_unexpected", source_uri=source_uri)
                    report.items.append(ItemReport(source_uri, Outcome.FAILED, error=f"{type(exc).__name__}: {exc}"))
        report.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        failed = report.stats[Outcome.FAILED.value]
        report.status = "succeeded" if failed == 0 else ("partial" if failed < len(report.items) else "failed")
        async with self._sf() as session, session.begin():
            session.add(
                KbIngestionRun(
                    id=run_id,
                    started_at=started,
                    finished_at=utcnow(),
                    status=report.status,
                    stats=report.stats,
                    items=[asdict(i) for i in report.items],
                )
            )
        _log.info("ingest_completed", run_id=str(run_id), **report.stats, duration_ms=report.duration_ms)
        return report

    async def _ingest_file(self, path: Path, source_uri: str, *, reindex: bool) -> ItemReport:
        parser = parser_for(path)
        assert parser is not None
        doc = parser.parse(source_uri, await asyncio.to_thread(path.read_text, encoding="utf-8"))
        digest = document_hash(doc)
        doc_id = document_id_for(source_uri)

        async with self._sf() as session:
            existing = await session.get(KbDocument, doc_id)
            if (
                existing
                and existing.status == "active"
                and existing.content_hash == digest
                and not reindex
                and existing.embedding_model == self._embedder.model_name
            ):
                return ItemReport(source_uri, Outcome.UNCHANGED, str(doc_id), existing.version, existing.chunk_count)
            # Duplicates are re-checked each run: if their twin changed they become active.
            twin = (
                await session.execute(
                    select(KbDocument.id)
                    .where(KbDocument.content_hash == digest, KbDocument.id != doc_id, KbDocument.status == "active")
                    .limit(1)
                )
            ).scalar_one_or_none()

        version = 1 if existing is None else (existing.version + (existing.content_hash != digest))
        if twin is not None:
            await self._store(doc, doc_id, digest, version, chunks=[], vectors=[], duplicate_of=twin)
            return ItemReport(source_uri, Outcome.DUPLICATE, str(doc_id), version, 0, str(twin))

        chunks = chunk_markdown(doc.body, max_words=self._s.chunk_max_words, overlap_words=self._s.chunk_overlap_words)
        vectors = await self._embedder.embed_documents(
            [embedding_text(doc.title, c.heading_path, c.content) for c in chunks]
        )
        await self._store(doc, doc_id, digest, version, chunks=chunks, vectors=vectors, duplicate_of=None)
        return ItemReport(
            source_uri, Outcome.CREATED if existing is None else Outcome.UPDATED, str(doc_id), version, len(chunks)
        )

    async def _store(
        self,
        doc: ParsedDocument,
        doc_id: uuid.UUID,
        digest: str,
        version: int,
        *,
        chunks: list[Any],
        vectors: list[list[float]],
        duplicate_of: uuid.UUID | None,
    ) -> None:
        async with self._sf() as session, session.begin():
            row = await session.get(KbDocument, doc_id)
            if row is None:
                row = KbDocument(id=doc_id, source_uri=doc.source_uri)
                session.add(row)
            row.title, row.doc_type = doc.title, doc.doc_type.value
            row.services, row.tags, row.metadata_ = doc.services, doc.tags, doc.metadata
            row.content_hash, row.version = digest, version
            row.status = "duplicate" if duplicate_of else "active"
            row.duplicate_of = duplicate_of
            row.chunk_count = len(chunks)
            row.embedding_model = self._embedder.model_name
            await session.flush()
            await session.execute(delete(KbChunk).where(KbChunk.document_id == doc_id))
            session.add_all(
                KbChunk(
                    id=stable_uuid(doc_id, f"{version}:{c.ordinal}"),
                    document_id=doc_id,
                    document_version=version,
                    ordinal=c.ordinal,
                    title=doc.title,
                    heading_path=c.heading_path,
                    content=c.content,
                    word_count=c.word_count,
                    embedding=vec,
                )
                for c, vec in zip(chunks, vectors, strict=True)
            )
