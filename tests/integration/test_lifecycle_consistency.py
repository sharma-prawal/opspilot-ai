"""C0-G3 regression: superseded guidance never enters normal investigation context (real PostgreSQL).

The independent audit changed a document's lifecycle to superseded after its chunk had been ranked as current and
then expanded it: the expansion returned the superseded section. Lifecycle is now validated on the rows being
expanded and once more, against committed state, before the response is assembled; agent-facing tools exclude
obsolete documents entirely, while explicitly authorised historical search still returns them (labelled).

Fixture documents use a unique token so keyword retrieval is deterministic and isolated from the corpus. They are
left ``retired`` (never deleted).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from sqlalchemy import update

from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.db.models import KbChunk, KbDocument
from opspilot_shared.domain.knowledge import DocType, RetrievalFilters, RetrievalMode, RetrievedChunk
from opspilot_shared.ids import sha256_hex
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration
RUNBOOKS = RetrievalFilters(doc_types=[DocType.RUNBOOK])
UNSAFE = "Restart every consumer and raise max_connections to 500 immediately; skip the capacity check."


class KB:
    def __init__(self, sf: Any, dims: int) -> None:
        self.sf, self.dims, self.docs = sf, dims, []
        self.token = f"qz{uuid.uuid4().hex[:10]}"

    async def doc(self, title: str, status: str, sections: list[tuple[str, str]], version: int = 1) -> uuid.UUID:
        did = uuid.uuid4()
        async with self.sf() as s, s.begin():
            s.add(
                KbDocument(
                    id=did,
                    source_uri=f"audit/{did}.md",
                    title=title,
                    doc_type="runbook",
                    status="active",
                    version=version,
                    metadata_={"status": status},
                    content_hash=sha256_hex(title + str(version)),
                    chunk_count=len(sections),
                    services=[],
                    tags=[],
                )
            )
            await s.flush()
            await self._chunks(s, did, version, title, sections)
        self.docs.append(did)
        return did

    async def _chunks(self, s: Any, did: uuid.UUID, version: int, title: str, sections: list[tuple[str, str]]) -> None:
        for ordinal, (heading, text) in enumerate(sections):
            s.add(
                KbChunk(
                    id=uuid.uuid4(),
                    document_id=did,
                    document_version=version,
                    ordinal=ordinal,
                    title=title,
                    heading_path=f"{title} > {heading}",
                    content=f"{text} {self.token}" if ordinal == 0 else text,
                    word_count=len(text.split()),
                    embedding=[0.01] * self.dims,
                )
            )

    async def set_status(self, did: uuid.UUID, status: str) -> None:  # metadata-only lifecycle change
        async with self.sf() as s, s.begin():
            await s.execute(update(KbDocument).where(KbDocument.id == did).values(metadata_={"status": status}))

    async def new_version(self, did: uuid.UUID, version: int, sections: list[tuple[str, str]]) -> None:
        """Content update as ingestion does it: version bump and chunk replacement in one transaction."""
        from sqlalchemy import delete

        async with self.sf() as s, s.begin():
            row = await s.get(KbDocument, did)
            row.version, row.content_hash = version, sha256_hex(f"{did}{version}")
            await s.execute(delete(KbChunk).where(KbChunk.document_id == did))
            await self._chunks(s, did, version, row.title, sections)

    async def retire(self) -> None:
        async with self.sf() as s, s.begin():
            await s.execute(update(KbDocument).where(KbDocument.id.in_(self.docs)).values(status="retired"))


@pytest.fixture
async def kb(session_factory, settings) -> AsyncIterator[KB]:  # type: ignore[no-untyped-def]
    k = KB(session_factory, settings.embedding_dimensions)
    yield k
    await k.retire()


class Hook:
    """A reranker that runs a callback between ranking and expansion (the audit's interleaving)."""

    def __init__(self, fn: Callable[[], Any] | None = None) -> None:
        self.fn = fn

    async def rerank(self, _query: str, results: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if self.fn is not None:
            await self.fn()
        return results


def sections(lead: str) -> list[tuple[str, str]]:
    return [
        ("Symptoms", f"{lead} symptoms: pool saturation"),
        ("Mitigation", f"{lead} mitigation: revert the deployment"),
        ("Capacity check", f"{lead} never change a pool without the capacity check"),
    ]


def retriever(session_factory, embedder, settings, hook: Hook | None = None) -> HybridRetriever:  # type: ignore[no-untyped-def]
    return HybridRetriever(session_factory, embedder, settings, reranker=hook)


async def search(r: HybridRetriever, kb: KB, *, exclude_obsolete: bool, expand: int = 4) -> Any:
    return await r.search(
        kb.token,
        mode=RetrievalMode.KEYWORD,
        top_k=5,
        filters=RUNBOOKS,
        record=False,
        expand_sections=expand,
        exclude_obsolete=exclude_obsolete,
    )


def statuses(resp: Any) -> list[str]:
    return [x.metadata["status"] for x in [*resp.results, *resp.context]]


# ----------------------------------------------------------------------------- the audit interleaving
async def test_codex_r5_superseded_between_ranking_and_expansion_is_not_expanded(
    kb, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    did = await kb.doc("Pool Runbook", "current", sections("current"))
    hook = Hook(lambda: kb.set_status(did, "superseded"))
    for exclude in (False, True):
        await kb.set_status(did, "current")
        resp = await search(retriever(session_factory, embedder, settings, hook), kb, exclude_obsolete=exclude)
        assert resp.context == []
        assert any("expansion withheld" in w for w in resp.warnings)
        if exclude:  # normal investigation: the now-superseded anchor is dropped too
            assert resp.results == []
        else:  # historical: kept, but labelled with the committed lifecycle, never as current
            assert {r.metadata["status"] for r in resp.results} == {"superseded"}
            assert {r.metadata["lifecycle_tier"] for r in resp.results} == {2}


async def test_superseded_before_retrieval_is_excluded_from_agent_search_only(
    kb, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    await kb.doc("Old Pool Tuning", "superseded", sections("obsolete"))
    r = retriever(session_factory, embedder, settings)
    agent = await search(r, kb, exclude_obsolete=True)
    historical = await search(r, kb, exclude_obsolete=False)
    assert agent.results == [] and agent.context == []
    assert historical.results and set(statuses(historical)) == {"superseded"}
    assert historical.context == []  # obsolete documents are never expanded
    assert all(x.metadata.get("lifecycle_validated") for x in historical.results)


async def test_active_replacement_is_used_when_available(kb, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    old = await kb.doc("Legacy Pool Tuning", "superseded", [("Mitigation", UNSAFE)])
    new = await kb.doc("Pool Runbook", "current", sections("current"))
    resp = await search(retriever(session_factory, embedder, settings), kb, exclude_obsolete=True)
    assert {x.document_id for x in [*resp.results, *resp.context]} == {new}
    assert old not in {x.document_id for x in resp.results}
    assert resp.context and all(x.metadata["lifecycle_validated"] for x in resp.context)


async def test_no_replacement_available_returns_no_guidance_rather_than_obsolete(
    kb, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    await kb.doc("Legacy Pool Tuning", "withdrawn", [("Mitigation", UNSAFE)])
    resp = await search(retriever(session_factory, embedder, settings), kb, exclude_obsolete=True)
    assert resp.results == [] and resp.context == []


async def test_metadata_only_lifecycle_update_is_reflected_immediately(kb, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    did = await kb.doc("Pool Runbook", "current", sections("current"))
    r = retriever(session_factory, embedder, settings)
    assert set(statuses(await search(r, kb, exclude_obsolete=True))) == {"current"}
    await kb.set_status(did, "withdrawn")
    after = await search(r, kb, exclude_obsolete=True)
    assert after.results == [] and after.context == []
    await kb.set_status(did, "current")
    assert set(statuses(await search(r, kb, exclude_obsolete=True))) == {"current"}


async def test_multiple_version_updates_between_ranking_and_expansion(kb, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    did = await kb.doc("Pool Runbook", "current", sections("v1"))

    async def two_updates() -> None:
        await kb.new_version(did, 2, sections("v2"))
        await kb.new_version(did, 3, sections("v3"))

    resp = await search(retriever(session_factory, embedder, settings, Hook(two_updates)), kb, exclude_obsolete=True)
    # The ranked v1 passage no longer exists: it is dropped, and nothing is expanded from a stale version.
    assert resp.results == [] and resp.context == []
    fresh = await search(retriever(session_factory, embedder, settings), kb, exclude_obsolete=True)
    assert {x.document_version for x in [*fresh.results, *fresh.context]} == {3}
    assert all("v3" in (x.content or "") for x in [*fresh.results, *fresh.context])


async def test_concurrent_lifecycle_flips_never_leak_obsolete_context(kb, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    did = await kb.doc("Pool Runbook", "current", sections("current"))
    r = retriever(session_factory, embedder, settings)
    stop = asyncio.Event()

    async def flipper() -> None:
        flip = False
        while not stop.is_set():
            await kb.set_status(did, "superseded" if flip else "current")
            flip = not flip
            await asyncio.sleep(0)

    task = asyncio.create_task(flipper())
    try:
        responses = [await search(r, kb, exclude_obsolete=True) for _ in range(40)]
    finally:
        stop.set()
        await task
    for resp in responses:
        assert set(statuses(resp)) <= {"current"}
        assert all(x.metadata.get("lifecycle_validated") for x in [*resp.results, *resp.context])


async def test_historical_citation_snapshot_remains_verifiable_after_supersession(
    kb, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    did = await kb.doc("Pool Runbook", "current", sections("current"))
    r = retriever(session_factory, embedder, settings)
    cited = (await search(r, kb, exclude_obsolete=True, expand=0)).results[0]
    await kb.set_status(did, "superseded")
    later = (await search(r, kb, exclude_obsolete=False, expand=0)).results[0]
    # The snapshot taken at citation time still hashes to its recorded digest and names its version; the same
    # passage is now reported with its committed (superseded) lifecycle.
    assert sha256_hex(cited.content or "") == cited.content_sha256 and cited.metadata["status"] == "current"
    assert later.chunk_id == cited.chunk_id and later.content_sha256 == cited.content_sha256
    assert later.document_version == cited.document_version and later.metadata["status"] == "superseded"


async def test_agent_tools_never_return_superseded_unsafe_guidance(kb, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    """Through the real MCP protocol: the obsolete unsafe instruction matches the query best, yet is absent."""
    await kb.doc("Legacy Pool Tuning", "superseded", [("Mitigation", UNSAFE + " restart consumers max_connections")])
    await kb.doc("Pool Runbook", "current", sections("current"))
    async with inprocess_gateways(settings, session_factory, embedder)("read") as gw:
        res = await gw.call(
            "search_runbooks",
            {"query": f"{kb.token} restart consumers max_connections", "top_k": 5, "expand_sections": 4},
            agent="t",
        )
    assert res.ok and res.data is not None
    texts = [x.get("content") or x["snippet"] for x in [*res.data["results"], *res.data["context"]]]
    assert texts and not any(UNSAFE[:40] in t for t in texts)
    assert {x["metadata"]["status"] for x in [*res.data["results"], *res.data["context"]]} == {"current"}
