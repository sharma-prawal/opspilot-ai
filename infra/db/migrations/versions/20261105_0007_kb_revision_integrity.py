"""kb revision integrity (C0-H1)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05 16:00:00+00:00

A document revision is ``(documents.id, documents.version)``; the database now guarantees that it identifies exactly
one content:

- ``uq_kb_documents_revision`` (id, version) and the composite foreign key ``fk_kb_chunks_document_revision``
  chunks(document_id, document_version) -> documents(id, version), DEFERRABLE INITIALLY DEFERRED: at every commit,
  every chunk of a document belongs to its *current* revision. A committed state can never mix chunks of two
  revisions under one document, and publishing a revision (row update + chunk replacement) is atomic.
- ``trg_kb_documents_revision_guard``: a content change (``content_hash``) must increase ``version``, and ``version``
  never decreases. Different content can therefore never reuse a revision number.

Additive. Refuses to run, changing nothing, if existing chunks do not match their document's version.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    stale = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM kb.chunks c JOIN kb.documents d ON d.id = c.document_id "
                "WHERE c.document_version <> d.version"
            )
        )
        .scalar_one()
    )
    if stale:
        raise RuntimeError(
            f"{stale} chunk(s) do not belong to their document's current version; re-ingest (make ingest) before "
            "applying migration 0007 (nothing was changed)"
        )
    op.create_unique_constraint("uq_kb_documents_revision", "documents", ["id", "version"], schema="kb")
    op.create_foreign_key(
        "fk_kb_chunks_document_revision",
        "chunks",
        "documents",
        ["document_id", "document_version"],
        ["id", "version"],
        source_schema="kb",
        referent_schema="kb",
        ondelete="CASCADE",
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION kb.guard_document_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.version < OLD.version THEN
                RAISE EXCEPTION 'document % revision went backwards (% -> %)', OLD.id, OLD.version, NEW.version
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.content_hash IS DISTINCT FROM OLD.content_hash AND NEW.version <= OLD.version THEN
                RAISE EXCEPTION 'document % content changed without a new revision (version %)', OLD.id, OLD.version
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_kb_documents_revision_guard BEFORE UPDATE OF version, content_hash ON kb.documents "
        "FOR EACH ROW EXECUTE FUNCTION kb.guard_document_revision()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_kb_documents_revision_guard ON kb.documents")
    op.execute("DROP FUNCTION IF EXISTS kb.guard_document_revision()")
    op.drop_constraint("fk_kb_chunks_document_revision", "chunks", schema="kb", type_="foreignkey")
    op.drop_constraint("uq_kb_documents_revision", "documents", schema="kb", type_="unique")
