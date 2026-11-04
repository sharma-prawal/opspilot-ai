"""Audit finding 13 (C0 item J): an old RCA's citations stay reconstructable after re-ingestion."""

import shutil
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from opspilot_rag.ingest import IngestionService
from opspilot_shared.db.models import KbChunk
from opspilot_shared.ids import sha256_hex
from tests.integration.test_api import client, poll  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration


async def test_cited_passage_survives_reingestion_of_its_document(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient,  # noqa: F811
    tmp_path: Path,
    session_factory,
    embedder,
    settings,
) -> None:
    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    await poll(client, inv, {"awaiting_approval", "completed", "failed"})
    cited = [e for e in (await client.get(f"/api/v1/investigations/{inv}/evidence")).json() if e["citation"]]
    assert cited
    for e in cited:
        c = e["citation"]
        assert c["passage"] and c["passage_sha256"] == sha256_hex(c["passage"])
        assert c["document_version"] >= 1 and c["lifecycle_status"] and c["retrieved_at"]
    target = cited[0]["citation"]

    # Re-ingest a changed version of the cited document: its chunks are replaced (new IDs, new version).
    root = tmp_path / "kb"
    shutil.copytree(settings.knowledge_dir, root)
    doc = root / target["source_uri"]
    original = doc.read_text()
    svc = IngestionService(session_factory, embedder, settings)
    try:
        doc.write_text(original + "\n## Addendum\n\nNew guidance added after the investigation.\n")
        report = await svc.ingest_directory(root)
        assert any(i.source_uri == target["source_uri"] and i.outcome.value == "updated" for i in report.items)
        async with session_factory() as s:
            assert await s.get(KbChunk, target["chunk_id"]) is None  # the cited chunk no longer exists in kb
            newer = (
                (await s.execute(select(KbChunk.document_version).where(KbChunk.document_id == target["document_id"])))
                .scalars()
                .all()
            )
            assert newer and min(newer) > target["document_version"]

        # The investigation's record still holds the exact passage it cited, verifiable by hash.
        again = {
            e["evidence_id"]: e["citation"] for e in (await client.get(f"/api/v1/investigations/{inv}/evidence")).json()
        }
        snap = again[cited[0]["evidence_id"]]
        assert snap == target and sha256_hex(snap["passage"]) == snap["passage_sha256"]
    finally:
        doc.write_text(original)
        await svc.ingest_directory(root)
