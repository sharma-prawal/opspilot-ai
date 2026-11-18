"""uploaded incident evidence (v0.5)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18 10:00:00+00:00

Incidents can now be backed by user-uploaded files instead of a simulator environment:

- ``ops.incidents.evidence_source`` ('simulator' | 'upload', default 'simulator'); ``environment_id`` becomes
  nullable, and a check constraint keeps the two consistent (a simulator incident always has an environment, an
  uploaded one never has).
- ``ops.uploaded_datasets``: the normalized records and per-file reports of one upload, deleted with its incident.

Additive for existing rows: every existing incident is a simulator incident with an environment.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("evidence_source", sa.String(16), nullable=False, server_default="simulator"),
        schema="ops",
    )
    op.alter_column("incidents", "environment_id", nullable=True, schema="ops")
    op.create_check_constraint(
        "ck_ops_incidents_evidence_source_env",
        "incidents",
        "(evidence_source = 'simulator' AND environment_id IS NOT NULL) "
        "OR (evidence_source = 'upload' AND environment_id IS NULL)",
        schema="ops",
    )
    op.create_table(
        "uploaded_datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ops.incidents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("affected_services", JSONB, nullable=False, server_default="[]"),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("files", JSONB, nullable=False, server_default="[]"),
        sa.Column("summary", JSONB, nullable=False, server_default="{}"),
        sa.Column("records", JSONB, nullable=False, server_default="{}"),
        sa.Column("storage_dir", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("uploaded_datasets", schema="ops")
    op.execute("DELETE FROM ops.incidents WHERE evidence_source = 'upload'")
    op.drop_constraint("ck_ops_incidents_evidence_source_env", "incidents", schema="ops")
    op.alter_column("incidents", "environment_id", nullable=False, schema="ops")
    op.drop_column("incidents", "evidence_source", schema="ops")
