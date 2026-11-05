"""C0-H1 regression: every returned passage belongs to one explicitly identified, immutable document revision.

Real parsing, ingestion, storage and retrieval on PostgreSQL. Interleavings are forced with gated embedders (between
an ingestion's read and its commit) and a reranker hook (between ranking and expansion/validation). Every response is
checked passage by passage: content hash, revision (document version + document content hash), and a single revision
per document. Fixture documents use a unique token and are removed afterwards (the test KB is scratch data).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from opspilot_rag.ingest import IngestionService, document_id_for
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.db.models import KbChunk, KbDocument
from opspilot_shared.domain.knowledge import DocType, RetrievalFilters, RetrievalMode, RetrievedChunk
from opspilot_shared.errors import EmbeddingError
from opspilot_shared.ids import sha256_hex
from tests.fakes.models import HashEmbedder

pytestmark = pytest.mark.integration
RUNBOOKS = RetrievalFilters(doc_types=[DocType.RUNBOOK])


class Source:
    """One logical knowledge source and the snapshots of it that ingestions read."""

    def __init__(self, root: Path, sf: Any, settings: Any) -> None:
        self.token = f"rev{uuid.uuid4().hex}"
        self.uri = f"audit/{self.token}.md"
        self.doc_id = document_id_for(self.uri)
        self.root, self.sf, self.settings = root, sf, settings

    def snapshot(self, marker: str, status: str = "current") -> Path:
        p = self.root / f"{marker}-{uuid.uuid4().hex[:6]}.md"
        p.write_text(
            f"---\ntitle: Revision race\ndoc_type: runbook\nstatus: {status}\n---\n# Revision race\n\n"
            f"## Symptoms\n{self.token} {marker} signal.\n\n## Mitigation\n{marker} instructions for this revision.\n\n"
            f"## Capacity check\nNever act on {marker} without checking capacity.\n"
        )
        return p

    async def ingest(self, path: Path, embedder: Any) -> Any:
        return await IngestionService(self.sf, embedder, self.settings)._ingest_file(path, self.uri, reindex=False)

    async def committed(self) -> tuple[int, str, set[str], set[int]]:
        async with self.sf() as s:
            doc = await s.get(KbDocument, self.doc_id)
            chunks = list((await s.execute(select(KbChunk).where(KbChunk.document_id == self.doc_id))).scalars())
        assert doc is not None
        return doc.version, doc.content_hash, {c.content for c in chunks}, {c.document_version for c in chunks}


class GateEmbedder(HashEmbedder):
    """Blocks document embedding until released: the ingestion has read the committed row but not yet published."""

    def __init__(self, dims: int, *, fail: bool = False) -> None:
        super().__init__(dims)
        self.entered, self.go, self.fail = asyncio.Event(), asyncio.Event(), fail

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.entered.set()
        await self.go.wait()
        if self.fail:
            raise EmbeddingError("embedding service unavailable")
        return await super().embed_documents(texts)


class Hook:
    def __init__(self, fn: Callable[[], Any] | None = None) -> None:
        self.fn = fn

    async def rerank(self, _q: str, results: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if self.fn is not None:
            await self.fn()
        return results


@pytest.fixture
async def source(tmp_path, session_factory, settings) -> AsyncIterator[Source]:  # type: ignore[no-untyped-def]
    src = Source(tmp_path, session_factory, settings)
    yield src
    async with session_factory() as s, s.begin():
        await s.execute(delete(KbChunk).where(KbChunk.document_id == src.doc_id))
        await s.execute(delete(KbDocument).where(KbDocument.id == src.doc_id))


async def search(src: Source, embedder: Any, hook: Hook | None = None, *, exclude: bool = True) -> Any:
    return await HybridRetriever(src.sf, embedder, src.settings, reranker=hook).search(
        src.token,
        mode=RetrievalMode.KEYWORD,
        top_k=1,
        filters=RUNBOOKS,
        record=False,
        expand_sections=4,
        exclude_obsolete=exclude,
    )


def assert_single_revision(resp: Any) -> set[tuple[int, str]]:
    """Every passage hashes to its own content and carries a revision; one document, one revision."""
    revisions: set[tuple[int, str]] = set()
    for p in [*resp.results, *resp.context]:
        assert sha256_hex(p.content or "") == p.content_sha256
        assert p.metadata.get("document_hash") and p.metadata.get("lifecycle_validated") is True
        revisions.add((p.document_version, p.metadata["document_hash"]))
    assert len(revisions) <= 1, revisions
    markers = {m for p in [*resp.results, *resp.context] for m in ("BASE", "ALPHA", "BRAVO") if m in (p.content or "")}
    assert len(markers) <= 1, markers  # never content from two revisions
    return revisions


async def assert_matches_committed(src: Source, revisions: set[tuple[int, str]]) -> None:
    version, digest, _, chunk_versions = await src.committed()
    assert chunk_versions == {version}  # database invariant: all chunks belong to the current revision
    for rev in revisions:
        assert rev == (version, digest)


# ----------------------------------------------------------------------------- the audit interleaving
async def test_codex_n2_overlapping_ingestions_get_distinct_revisions_and_never_mix(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    base = await src.ingest(src.snapshot("BASE"), embedder)
    a, b = GateEmbedder(embedder.dimensions), GateEmbedder(embedder.dimensions)
    ja = asyncio.create_task(src.ingest(src.snapshot("ALPHA"), a))
    jb = asyncio.create_task(src.ingest(src.snapshot("BRAVO"), b))
    await asyncio.wait_for(asyncio.gather(a.entered.wait(), b.entered.wait()), 10)  # both read version 1
    a.go.set()
    ra = await ja
    rb_holder: dict[str, Any] = {}

    async def publish_b() -> None:  # between ranking (ALPHA) and expansion/validation
        b.go.set()
        rb_holder["r"] = await jb

    resp = await search(src, embedder, Hook(publish_b))
    assert (base.version, ra.version, rb_holder["r"].version) == (1, 2, 3)  # never two contents as one version
    assert_single_revision(resp)
    assert resp.results == [] and resp.context == []  # the ranked revision was replaced: nothing stale survives
    assert any("no longer the current" in w for w in resp.warnings)
    fresh = await search(src, embedder)
    revs = assert_single_revision(fresh)
    await assert_matches_committed(src, revs)
    assert "BRAVO" in " ".join(p.content or "" for p in [*fresh.results, *fresh.context])


async def test_concurrent_ingestion_of_two_revisions_serializes(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    for _ in range(3):
        reports = await asyncio.gather(
            src.ingest(src.snapshot("ALPHA"), embedder), src.ingest(src.snapshot("BRAVO"), embedder)
        )
        assert len({r.version for r in reports}) == 2  # each content got its own revision
        version, _digest, contents, chunk_versions = await src.committed()
        assert version == max(r.version for r in reports) and chunk_versions == {version}
        assert sum(m in " ".join(contents) for m in ("ALPHA", "BRAVO")) == 1


# ----------------------------------------------------------------------------- readers
async def test_readers_before_and_after_a_revision_commit(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    gate = GateEmbedder(embedder.dimensions)
    job = asyncio.create_task(src.ingest(src.snapshot("ALPHA"), gate))
    await asyncio.wait_for(gate.entered.wait(), 10)
    before = await search(src, embedder)  # begins and ends before the commit: the old revision, whole
    assert "BASE" in " ".join(p.content or "" for p in [*before.results, *before.context])
    assert_single_revision(before)

    async def commit_alpha() -> None:
        gate.go.set()
        await job

    during = await search(src, embedder, Hook(commit_alpha))  # began before, validated after the commit
    assert_single_revision(during)
    assert during.results == [] and during.context == []
    after = await search(src, embedder)  # begins after the commit: the new revision, whole
    revs = assert_single_revision(after)
    assert "ALPHA" in " ".join(p.content or "" for p in [*after.results, *after.context])
    await assert_matches_committed(src, revs)


async def test_reading_while_only_metadata_changes_keeps_the_revision(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    p_meta = src.root / "meta.md"
    p_meta.write_text(src.snapshot("BASE").read_text().replace("status: current", "status: current\nowner: sre"))

    async def metadata_only() -> None:
        report = await src.ingest(p_meta, embedder)
        assert report.outcome.value == "metadata_updated"

    resp = await search(src, embedder, Hook(metadata_only))
    revs = assert_single_revision(resp)
    assert resp.results and resp.context  # same revision: nothing withdrawn
    await assert_matches_committed(src, revs)
    superseded = src.root / "superseded.md"
    superseded.write_text(src.snapshot("BASE").read_text().replace("status: current", "status: superseded"))

    async def supersede() -> None:
        await src.ingest(superseded, embedder)

    gone = await search(src, embedder, Hook(supersede))  # expansion after supersession: excluded
    assert gone.results == [] and gone.context == []


# ----------------------------------------------------------------------------- failures leave the previous revision
async def test_failed_ingestion_leaves_the_previous_revision_intact(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    before = await src.committed()
    gate = GateEmbedder(embedder.dimensions, fail=True)
    gate.go.set()
    with pytest.raises(EmbeddingError):
        await src.ingest(src.snapshot("ALPHA"), gate)
    assert await src.committed() == before


async def test_publication_rolls_back_atomically_on_transaction_failure(source, embedder, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The commit fails after the document row was updated and its chunks deleted: nothing of it is visible."""
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    before = await src.committed()

    class BadVectors(HashEmbedder):
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 3 for _ in texts]  # wrong dimension: the chunk insert fails inside the transaction

    with pytest.raises(DBAPIError):
        await src.ingest(src.snapshot("ALPHA"), BadVectors(embedder.dimensions))
    assert await src.committed() == before
    resp = await search(src, embedder)
    assert "BASE" in " ".join(p.content or "" for p in resp.results)


# ----------------------------------------------------------------------------- database invariants
async def test_database_refuses_content_change_without_new_revision_and_mixed_chunks(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    with pytest.raises(DBAPIError, match="without a new revision"):
        async with src.sf() as s, s.begin():
            await s.execute(update(KbDocument).where(KbDocument.id == src.doc_id).values(content_hash="f" * 64))
    with pytest.raises(DBAPIError, match="went backwards"):
        async with src.sf() as s, s.begin():
            await s.execute(update(KbDocument).where(KbDocument.id == src.doc_id).values(version=0))
    with pytest.raises(DBAPIError, match="fk_kb_chunks_document_revision"):
        async with src.sf() as s, s.begin():  # bump the revision but keep the old revision's chunks
            await s.execute(
                update(KbDocument)
                .where(KbDocument.id == src.doc_id)
                .values(version=KbDocument.version + 1, content_hash="e" * 64)
            )
    async with src.sf() as s:
        mixed = (
            await s.execute(
                text(
                    "SELECT count(*) FROM kb.chunks c JOIN kb.documents d ON d.id = c.document_id "
                    "WHERE c.document_version <> d.version"
                )
            )
        ).scalar_one()
    assert mixed == 0


# ----------------------------------------------------------------------------- history
async def test_historical_citations_survive_multiple_updates(source, embedder) -> None:  # type: ignore[no-untyped-def]
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    cited = (await search(src, embedder)).results[0]
    for marker in ("ALPHA", "BRAVO"):
        await src.ingest(src.snapshot(marker), embedder)
    # The citation snapshot is self-contained and still verifies; the stored revision moved on twice.
    assert sha256_hex(cited.content or "") == cited.content_sha256 and "BASE" in (cited.content or "")
    assert cited.document_version == 1
    version, digest, contents, _ = await src.committed()
    assert version == 3 and digest != cited.metadata["document_hash"] and not any("BASE" in c for c in contents)
    current = await search(src, embedder, exclude=False)  # historical mode returns the current revision only
    revs = assert_single_revision(current)
    assert revs == {(3, digest)}


async def test_stale_metadata_only_decision_is_retried_with_embedding(source, embedder) -> None:  # type: ignore[no-untyped-def]
    """Writer M read BASE and decided "metadata only" (no embedding). Before it publishes, ALPHA commits. Under the
    revision lock M sees the content changed, retries with embeddings and publishes its own content as a new
    revision: last writer wins, never a mix and never BASE metadata over ALPHA content."""
    src = source
    await src.ingest(src.snapshot("BASE"), embedder)
    base_text = src.snapshot("BASE").read_text()
    meta = src.root / "meta.md"
    meta.write_text(base_text.replace("status: current", "status: current\nowner: sre"))
    service = IngestionService(src.sf, embedder, src.settings)
    publish = service._publish
    paused = asyncio.Event()

    async def slow_publish(*a: Any, **k: Any) -> Any:
        if not paused.is_set():
            paused.set()
            await src.ingest(src.snapshot("ALPHA"), embedder)  # commits version 2 in between
        return await publish(*a, **k)

    service._publish = slow_publish  # type: ignore[method-assign]
    report = await service._ingest_file(meta, src.uri, reindex=False)
    version, digest, contents, chunk_versions = await src.committed()
    assert report.outcome.value == "updated" and report.version == version == 3 and chunk_versions == {3}
    assert any("BASE" in c for c in contents) and not any("ALPHA" in c for c in contents)
    revs = assert_single_revision(await search(src, embedder))
    assert revs == {(3, digest)}
