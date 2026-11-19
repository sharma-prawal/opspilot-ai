"""connected telemetry snapshots (v0.6)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18 18:00:00+00:00

Incidents can now be backed by a read-only telemetry snapshot taken from a configured Loki/Prometheus connector:

- ``ops.incidents.evidence_source`` accepts 'connector' (no simulator environment, like 'upload');
- ``ops.uploaded_datasets.queries``: the provenance of every connector query (connector, template, rendered query,
  window, step/limit, status, counts). Empty for uploads.

Additive: existing rows keep their values.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
FULL_NAME = "ck_incidents_ck_ops_incidents_evidence_source_env"


def upgrade() -> None:
    # Created by 0009 through the metadata naming convention (ck_<table>_<name>); drop it by its full name.
    op.drop_constraint(op.f(FULL_NAME), "incidents", schema="ops", type_="check")
    op.create_check_constraint(
        "ck_ops_incidents_evidence_source_env",
        "incidents",
        "(evidence_source = 'simulator' AND environment_id IS NOT NULL) "
        "OR (evidence_source IN ('upload', 'connector') AND environment_id IS NULL)",
        schema="ops",
    )
    op.add_column("uploaded_datasets", sa.Column("queries", JSONB, nullable=False, server_default="[]"), schema="ops")


def downgrade() -> None:
    op.drop_column("uploaded_datasets", "queries", schema="ops")
    op.execute("DELETE FROM ops.incidents WHERE evidence_source = 'connector'")
    op.drop_constraint(op.f(FULL_NAME), "incidents", schema="ops", type_="check")
    op.create_check_constraint(
        "ck_ops_incidents_evidence_source_env",
        "incidents",
        "(evidence_source = 'simulator' AND environment_id IS NOT NULL) "
        "OR (evidence_source = 'upload' AND environment_id IS NULL)",
        schema="ops",
    )
