import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from opspilot_rag.ingest import IngestionService
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.db.models import KbChunk, KbDocument, KbRetrievalQuery
from opspilot_shared.domain.knowledge import DocType, RetrievalFilters, RetrievalMode
from opspilot_shared.errors import EmbeddingError

pytestmark = pytest.mark.integration


def expected_counts(settings) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """(unique documents, duplicates) derived from the corpus on disk, so tests track corpus changes."""
    from opspilot_rag.ingest import document_hash
    from opspilot_rag.parsing import discover, parser_for

    root = settings.knowledge_dir
    seen: set[str] = set()
    dups = 0
    for path in discover(root):
        doc = parser_for(path).parse(path.relative_to(root).as_posix(), path.read_text())  # type: ignore[union-attr]
        h = document_hash(doc)
        dups += h in seen
        seen.add(h)
    return len(seen), dups


async def test_initial_ingest_dedups_archive_copy(ingested, session_factory, settings) -> None:  # type: ignore[no-untyped-def]
    stats = ingested["stats"]
    assert stats["failed"] == 0 and (stats["created"], stats["duplicate"]) == expected_counts(settings)
    async with session_factory() as s:
        dup = (await s.execute(select(KbDocument).where(KbDocument.status == "duplicate"))).scalar_one()
        assert dup.source_uri.startswith("archive/") and dup.chunk_count == 0
        canonical = await s.get(KbDocument, dup.duplicate_of)
        assert canonical is not None and canonical.source_uri == "runbooks/high-5xx-error-rate.md"
        n = (await s.execute(select(func.count()).select_from(KbChunk))).scalar_one()
        assert n == sum(i["chunks"] for i in ingested["items"] if i["outcome"] == "created")


async def test_reingest_is_incremental(ingested, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    report = await IngestionService(session_factory, embedder, settings).ingest_directory()
    assert (report.stats["unchanged"], report.stats["duplicate"]) == expected_counts(settings) and report.stats[
        "chunks_written"
    ] == 0


async def test_changed_document_bumps_version(tmp_path: Path, session_factory, embedder, settings, ingested) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "kb"
    shutil.copytree(settings.knowledge_dir, root)
    svc = IngestionService(session_factory, embedder, settings)
    target = root / "runbooks" / "queue-backlog.md"
    target.write_text(target.read_text() + "\n## New section\n\nScale out consumers to 6 replicas.\n")
    report = await svc.ingest_directory(root)
    [item] = [i for i in report.items if i.source_uri == "runbooks/queue-backlog.md"]
    assert item.outcome.value == "updated" and item.version == 2
    async with session_factory() as s:
        chunks = (await s.execute(select(KbChunk).where(KbChunk.document_id == item.document_id))).scalars().all()
        assert chunks and {c.document_version for c in chunks} == {2}
    # restore original content → version 3, content back to original
    target.write_text((settings.knowledge_dir / "runbooks" / "queue-backlog.md").read_text())
    items = (await svc.ingest_directory(root)).items
    assert next(i for i in items if i.source_uri.endswith("queue-backlog.md")).version == 3


async def test_bad_file_is_reported_not_fatal(tmp_path: Path, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "broken.md").write_text("no front matter here")
    report = await IngestionService(session_factory, embedder, settings).ingest_directory(tmp_path)
    assert report.status == "failed" and report.items[0].error and "front matter" in report.items[0].error


async def test_embedding_dimension_guard(settings) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from opspilot_shared.llm.ollama import OllamaEmbedder

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1] * 8]})

    emb = OllamaEmbedder(
        settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    )
    with pytest.raises(EmbeddingError, match="dimension 8"):
        await emb.embed_documents(["x"])


@pytest.mark.parametrize("mode", list(RetrievalMode))
async def test_exact_error_token_query_finds_schema_runbook(
    mode, ingested, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    r = HybridRetriever(session_factory, embedder, settings)
    resp = await r.search(
        'UndefinedColumn column "amount" of relation ledger_entries does not exist', mode=mode, top_k=5
    )
    uris = [x.source_uri for x in resp.results]
    assert any(
        u in uris
        for u in (
            "troubleshooting/postgres-troubleshooting.md",
            "runbooks/schema-migration-rollback.md",
            "incidents/2025-08-14-ledger-column-drop.md",
        )
    )
    for x in resp.results:  # provenance on every hit
        assert x.chunk_id and x.document_id and x.source_uri and x.heading_path is not None


async def test_filters_and_trace(ingested, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    r = HybridRetriever(session_factory, embedder, settings)
    resp = await r.search(
        "rollback schema migration",
        top_k=4,
        caller="test",
        filters=RetrievalFilters(doc_types=[DocType.INCIDENT_REPORT]),
    )
    assert resp.results and {x.doc_type for x in resp.results} == {DocType.INCIDENT_REPORT}
    svc = await r.search("queue lag", top_k=3, filters=RetrievalFilters(services=["settlement-worker"]))
    assert all("settlement-worker" in x.metadata["services"] for x in svc.results)
    async with session_factory() as s:
        trace = await s.get(KbRetrievalQuery, resp.query_id)
    assert trace is not None and trace.caller == "test" and len(trace.results) == len(resp.results)
    assert trace.filters == {"doc_types": ["incident_report"]}


class _DownEmbedder:
    model_name, dimensions = "down", 1024

    async def embed_documents(self, texts):  # type: ignore[no-untyped-def]
        raise EmbeddingError("embedding service unreachable")

    async def embed_query(self, text):  # type: ignore[no-untyped-def]
        raise EmbeddingError("embedding service unreachable")


async def test_hybrid_degrades_to_keyword_when_embeddings_unavailable(ingested, session_factory, settings) -> None:  # type: ignore[no-untyped-def]
    r = HybridRetriever(session_factory, _DownEmbedder(), settings)  # type: ignore[arg-type]
    resp = await r.search("LEDGER_WRITE_FAILED", top_k=3, caller="degraded-test")
    assert resp.results and all(x.vector_rank is None for x in resp.results)
    assert resp.warnings and "keyword-only" in resp.warnings[0]
    async with session_factory() as s:
        trace = await s.get(KbRetrievalQuery, resp.query_id)
    assert trace is not None and trace.warnings == resp.warnings
    with pytest.raises(EmbeddingError):  # vector-only mode has nothing to fall back to
        await r.search("LEDGER_WRITE_FAILED", mode=RetrievalMode.VECTOR)


class CountingEmbedder:
    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self.inner, self.documents_embedded = inner, 0
        self.model_name, self.dimensions = inner.model_name, inner.dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents_embedded += len(texts)
        return await self.inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self.inner.embed_query(text)


async def test_metadata_only_lifecycle_change_is_applied_without_reembedding(  # type: ignore[no-untyped-def]
    tmp_path: Path, session_factory, embedder, settings, ingested
) -> None:
    """Audit finding 7: status/version edits used to hash identically and were silently skipped."""
    root = tmp_path / "kb"
    shutil.copytree(settings.knowledge_dir, root)
    target = root / "runbooks" / "legacy-ledger-pool-tuning.md"
    original = target.read_text()
    counting = CountingEmbedder(embedder)
    svc = IngestionService(session_factory, counting, settings)
    async with session_factory() as s:
        before = (
            await s.execute(select(KbDocument).where(KbDocument.source_uri == target.relative_to(root).as_posix()))
        ).scalar_one()
        chunk_ids = set((await s.execute(select(KbChunk.id).where(KbChunk.document_id == before.id))).scalars())
    try:
        target.write_text(
            original.replace("status: superseded", "status: withdrawn").replace("version: 1", "version: 2")
        )
        report = await svc.ingest_directory(root)
        [item] = [i for i in report.items if i.source_uri == "runbooks/legacy-ledger-pool-tuning.md"]
        assert item.outcome.value == "metadata_updated" and counting.documents_embedded == 0
        others = {i.outcome.value for i in report.items if i is not item}
        assert report.stats["metadata_updated"] == 1 and others <= {"unchanged", "duplicate"}
        async with session_factory() as s:
            after = await s.get(KbDocument, before.id)
            assert after is not None and after.metadata_["status"] == "withdrawn" and after.metadata_["version"] == 2
            assert after.version == before.version and after.content_hash == before.content_hash
            assert (
                set((await s.execute(select(KbChunk.id).where(KbChunk.document_id == before.id))).scalars())
                == chunk_ids
            )
    finally:
        target.write_text(original)
        restored = await svc.ingest_directory(root)
    assert [i.outcome.value for i in restored.items if i.source_uri.endswith("legacy-ledger-pool-tuning.md")] == [
        "metadata_updated"
    ]


async def test_lifecycle_policy_is_applied_before_truncation(  # type: ignore[no-untyped-def]
    ingested, session_factory, embedder, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Obsolete and unreviewed guidance can no longer displace current guidance in the top-k."""
    from opspilot_rag import retrieval as retrieval_mod

    r = HybridRetriever(session_factory, embedder, settings)
    query = "ledger connection pool tuning max connections legacy settings"
    tier = retrieval_mod.lifecycle_tier
    with_policy = await r.search(query, top_k=5, record=False)
    monkeypatch.setattr(retrieval_mod, "lifecycle_tier", lambda _status: 0)  # policy off: raw fused order
    without = await r.search(query, top_k=5, record=False)

    tiers = [hit.metadata["lifecycle_tier"] for hit in with_policy.results]
    assert tiers == sorted(tiers), tiers  # current < unreviewed < obsolete, order kept within a tier
    raw = [h.source_uri for h in without.results]
    assert tier(without.results[0].metadata["status"]) > 0, raw  # premise: an obsolete doc ranks first without policy
    first_current = next(h.source_uri for h in with_policy.results if h.metadata["lifecycle_tier"] == 0)
    assert with_policy.results[0].source_uri == first_current
