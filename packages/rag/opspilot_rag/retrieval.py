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
    OBSOLETE_STATUSES,
    DocType,
    RetrievalFilters,
    RetrievalMode,
    RetrievedChunk,
    SearchResponse,
    lifecycle_tier,
)
from opspilot_shared.errors import EmbeddingError
from opspilot_shared.ids import sha256_hex
from opspilot_shared.llm.ports import Embedder
from opspilot_shared.logging import get_logger
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
_TERM = re.compile(r"[A-Za-z0-9_]{2,}")
SNIPPET_CHARS = 700
# Lifecycle policy, applied to the fused candidate list BEFORE truncation (audit finding 7): current guidance
# always outranks unreviewed or unknown-status material, which outranks superseded / withdrawn guidance.
# Within a tier the retrieval order is preserved. Obsolete documents stay retrievable for explicitly authorised
# historical search but can no longer displace current ones; with ``exclude_obsolete`` (every agent-facing MCP search,
# C0-G3) they are not candidates at all. ``OBSOLETE_STATUSES``/``lifecycle_tier`` live in the shared domain.
__all__ = ["OBSOLETE_STATUSES", "HybridRetriever", "lifecycle_tier", "section_role"]


OVERFETCH = 4

# Section coverage (C0-F3). A long current runbook is chunked by heading; ranking often selects only its symptom
# paragraph while the sections that say what to check, what to do and what never to do rank poorly. When asked,
# the retriever adds other sections of the *top-ranked current operational document* (same document version),
# bounded in count, so the reader sees the document's own guidance rather than a fragment of it. Only one
# document is expanded, only lifecycle tier 0 (current) qualifies, and superseded/unreviewed material never does.
OPERATIONAL_DOC_TYPES = frozenset({"runbook", "troubleshooting"})
MAX_EXPAND_SECTIONS = 4
SECTION_ROLES: tuple[tuple[str, re.Pattern[str]], ...] = (  # selection priority, highest first
    (
        "remediation",
        re.compile(r"\b(mitigat|remediat|resolut|resolv|roll ?back|revert|recover|workaround|procedure)", re.I),
    ),
    (
        "constraints",
        re.compile(r"\b(never|do not|don't|precondition|prerequisite|caution|warning|capacity|limit|safety)", re.I),
    ),
    ("diagnostics", re.compile(r"\b(diagnos|identify|investigat|check|verify|look for|triage|confirm)", re.I)),
    ("causes", re.compile(r"\b(cause|root)", re.I)),
    ("symptoms", re.compile(r"\b(symptom|signal|alert)", re.I)),
)
ROLE_PRIORITY = {role: i for i, (role, _) in enumerate(SECTION_ROLES)}


def section_role(heading_path: str, content: str) -> str:
    """Generic role of a section: the highest-priority role its own heading or its text expresses.

    A section headed "X is usually a symptom" that says "revert that deployment" is remediation guidance."""
    heading = heading_path.split(" > ")[-1] if heading_path else ""
    for role, pattern in SECTION_ROLES:
        if pattern.search(heading) or pattern.search(content):
            return role
    return "other"


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
    def _filtered(stmt: Select[Any], filters: RetrievalFilters | None, exclude_obsolete: bool = False) -> Select[Any]:
        stmt = stmt.where(KbDocument.status == "active")
        if exclude_obsolete:  # evaluated in the same statement (snapshot) as the candidate chunks
            stmt = stmt.where(
                func.lower(func.coalesce(KbDocument.metadata_["status"].astext, "current")).notin_(
                    sorted(OBSOLETE_STATUSES)
                )
            )
        if filters is None:
            return stmt
        if filters.doc_types:
            stmt = stmt.where(KbDocument.doc_type.in_([d.value for d in filters.doc_types]))
        if filters.services:
            stmt = stmt.where(KbDocument.services.has_any(array(filters.services, type_=Text)))
        if filters.tags:
            stmt = stmt.where(KbDocument.tags.has_any(array(filters.tags, type_=Text)))
        return stmt

    async def _vector(
        self, session: AsyncSession, query: str, n: int, filters: RetrievalFilters | None, exclude_obsolete: bool
    ) -> list[_Hit]:
        qvec = await self._embedder.embed_query(query)
        await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = KbChunk.embedding.cosine_distance(qvec).label("distance")
        stmt = (
            self._filtered(
                select(KbChunk, KbDocument, distance).join(KbDocument, KbChunk.document_id == KbDocument.id),
                filters,
                exclude_obsolete,
            )
            .order_by(distance)
            .limit(n)
        )
        rows = (await session.execute(stmt)).all()
        return [_Hit(c, d, i, 1.0 - float(dist)) for i, (c, d, dist) in enumerate(rows, start=1)]

    async def _keyword(
        self, session: AsyncSession, query: str, n: int, filters: RetrievalFilters | None, exclude_obsolete: bool
    ) -> list[_Hit]:
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
                exclude_obsolete,
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
            content=c.content,
            content_sha256=sha256_hex(c.content),
            score=round(score, 6),
            vector_rank=vrank,
            keyword_rank=krank,
            metadata={
                "services": d.services,
                "tags": d.tags,
                "ordinal": c.ordinal,
                "status": str(d.metadata_.get("status", "current")),
                "lifecycle_tier": lifecycle_tier(d.metadata_.get("status")),
                "doc_version": d.metadata_.get("version"),
                # C0-H1: the revision this passage belongs to is (document_id, document_version, document_hash).
                "document_hash": d.content_hash,
            },
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
        expand_sections: int = 0,
        exclude_obsolete: bool = False,
    ) -> SearchResponse:
        """``exclude_obsolete``: normal incident investigation (agent-facing tools) never receives superseded or
        withdrawn guidance; ``False`` is explicitly authorised historical search (operator API, evaluation)."""
        top_k = top_k or self._s.retrieval_top_k
        expand_sections = max(0, min(expand_sections, MAX_EXPAND_SECTIONS))
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
                        vhits = await self._vector(session, query, n, filters, exclude_obsolete)
                    except EmbeddingError as exc:
                        if mode == RetrievalMode.VECTOR:
                            raise
                        # Hybrid degrades to keyword-only rather than failing the caller; surfaced as a warning.
                        warnings.append(f"vector retrieval unavailable, keyword-only results: {exc}")
                        span.set_attribute("rag.degraded", True)
                        _log.warning("retrieval_degraded", reason=str(exc))
                khits = (
                    await self._keyword(session, query, n, filters, exclude_obsolete)
                    if mode != RetrievalMode.VECTOR
                    else []
                )

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
            ordered = [
                item
                for _, item in sorted(
                    enumerate(ordered),
                    key=lambda t: (lifecycle_tier((by_id[t[1][0]].document.metadata_ or {}).get("status")), t[0]),
                )
            ]
            results = [self._to_result(by_id[cid], s, vrank.get(cid), krank.get(cid)) for cid, s in ordered[:top_k]]
            results = await self._reranker.rerank(query, results)
            context = await self._expand(results, expand_sections, warnings) if expand_sections else []
            # C0-G3: candidates, expansion and this check run in separate snapshots; the lifecycle is validated
            # once more, against committed state, immediately before the response is assembled.
            results, context = await self._revalidate(results, context, warnings, exclude_obsolete)
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
        degraded = mode == RetrievalMode.HYBRID and bool(warnings)
        return SearchResponse(
            query_id=query_id,
            query=query,
            mode=mode,
            results=results,
            latency_ms=latency,
            warnings=warnings,
            effective_mode=RetrievalMode.KEYWORD if degraded else mode,
            context=context,
        )

    async def _expand(
        self, results: list[RetrievedChunk], limit: int, warnings: list[str] | None = None
    ) -> list[RetrievedChunk]:
        """Other sections of the top-ranked current operational document, by role priority, in document order.

        C0-G3: the anchor's tier comes from an earlier snapshot, so the document's lifecycle and version are checked
        again on the very rows being expanded (one statement, one snapshot). If the document is no longer the
        current, active version the anchor was taken from, nothing is expanded (fail closed)."""
        anchor = next(
            (
                r
                for r in results
                if r.doc_type.value in OPERATIONAL_DOC_TYPES and r.metadata.get("lifecycle_tier", 1) == 0
            ),
            None,
        )
        if anchor is None:
            return []
        have = {r.chunk_id for r in results}
        async with self._sf() as session:
            rows = (
                await session.execute(
                    select(KbChunk, KbDocument)
                    .join(KbDocument, KbChunk.document_id == KbDocument.id)
                    .where(
                        KbChunk.document_id == anchor.document_id,
                        KbChunk.document_version == anchor.document_version,
                        KbDocument.version == anchor.document_version,
                        KbDocument.content_hash == anchor.metadata.get("document_hash"),  # same revision (C0-H1)
                        KbDocument.status == "active",
                    )
                    .order_by(KbChunk.ordinal)
                )
            ).all()
        # ``rows`` always includes the anchor chunk itself, so an empty result means the version is gone.
        if not rows or any(lifecycle_tier((d.metadata_ or {}).get("status")) != 0 for _, d in rows):
            (warnings if warnings is not None else []).append(
                f"section expansion withheld: '{anchor.title}' v{anchor.document_version} is no longer the "
                "current active version (lifecycle changed after ranking)"
            )
            return []
        candidates = [
            (section_role(c.heading_path, c.content), c, d) for c, d in rows if c.id not in have and c.content.strip()
        ]
        chosen = sorted(candidates, key=lambda t: (ROLE_PRIORITY.get(t[0], len(ROLE_PRIORITY)), t[1].ordinal))[:limit]
        out = []
        for role, c, d in sorted(chosen, key=lambda t: t[1].ordinal):
            item = self._to_result(_Hit(c, d, 0, 0.0), anchor.score, None, None)
            item.metadata.update({"expanded_from": str(anchor.chunk_id), "section_role": role})
            out.append(item)
        return out

    async def _revalidate(
        self,
        results: list[RetrievedChunk],
        context: list[RetrievedChunk],
        warnings: list[str],
        exclude_obsolete: bool,
    ) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
        """Final lifecycle validation against committed document rows (C0-G3, C0-H1).

        Validation point: this one statement. A passage survives only if its document's committed revision is the
        one it was read from (same version *and* document content hash). Because a revision's chunks are immutable
        (any content change publishes a new version, enforced by migration 0007), the passage text is then exactly
        that current revision's text. Passages are handed over as value snapshots (content + SHA-256 + revision);
        nothing re-reads a chunk afterwards, so a revision published after this statement is simply later than the
        retrieval and cannot alter what was returned.

        - A passage whose document is no longer active at that version (replaced or retired since ranking) is
          dropped: its version no longer exists, so it can never be presented as current.
        - Every surviving passage carries the document's *committed* status/tier (a metadata-only supersession is
          reflected, never silently treated as current) and ``lifecycle_validated``.
        - With ``exclude_obsolete`` a passage that became obsolete is dropped.
        - Context (section expansion) survives only if its document is still current at that version; otherwise
          all of it is withdrawn.
        Results are re-ordered by tier (stable) so a newly superseded document cannot keep a current rank."""
        ids = {r.document_id for r in [*results, *context]}
        if not ids:
            return results, context
        async with self._sf() as session:
            docs = {
                row.id: row
                for row in (
                    await session.execute(
                        select(
                            KbDocument.id,
                            KbDocument.version,
                            KbDocument.content_hash,
                            KbDocument.status,
                            KbDocument.metadata_,
                        ).where(KbDocument.id.in_(ids))
                    )
                ).all()
            }

        def committed(r: RetrievedChunk) -> tuple[bool, str, int]:
            d = docs.get(r.document_id)
            if (
                d is None
                or d.status != "active"
                or d.version != r.document_version
                or d.content_hash != r.metadata.get("document_hash")  # C0-H1: the same revision, not just its number
            ):
                return False, "replaced", 2
            status = str((d.metadata_ or {}).get("status", "current"))
            return True, status, lifecycle_tier(status)

        kept: list[RetrievedChunk] = []
        changed = 0
        for r in results:
            live, status, tier = committed(r)
            if status != r.metadata.get("status") or tier != r.metadata.get("lifecycle_tier"):
                changed += 1
            if not live or (exclude_obsolete and tier == 2):
                continue
            r.metadata.update({"status": status, "lifecycle_tier": tier, "lifecycle_validated": True})
            kept.append(r)
        kept = [r for _, r in sorted(enumerate(kept), key=lambda t: (t[1].metadata["lifecycle_tier"], t[0]))]
        valid_context = all(committed(c)[0] and committed(c)[2] == 0 for c in context)
        if context and not valid_context:
            warnings.append("section expansion withdrawn: the expanded document's lifecycle changed")
            context = []
        # C0-H1: one document, one revision. Every survivor matches the committed revision, so a mix cannot remain;
        # the check is kept explicit (fail closed) rather than implied.
        revisions: dict[uuid.UUID, set[tuple[int, Any]]] = {}
        for x in [*kept, *context]:
            revisions.setdefault(x.document_id, set()).add((x.document_version, x.metadata.get("document_hash")))
        mixed = {d for d, revs in revisions.items() if len(revs) > 1}
        if mixed:  # pragma: no cover - unreachable while the checks above hold
            warnings.append(f"{len(mixed)} document(s) returned mixed revisions; their passages were withdrawn")
            kept = [r for r in kept if r.document_id not in mixed]
            context = [c for c in context if c.document_id not in mixed]
        for c in context:
            c.metadata.update({"lifecycle_validated": True})
        if changed:
            warnings.append(f"{changed} passage(s) changed lifecycle after ranking; labels reflect committed state")
        return kept, context
