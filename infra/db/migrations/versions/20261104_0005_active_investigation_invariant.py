"""one active investigation per incident; DB-backed execution ownership lease (audit finding G)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04 16:00:00+00:00

Additive. The partial unique index cannot be created while an incident already has more than one active
investigation; in that case the migration stops with a message and changes nothing. Duplicates are never
resolved automatically (no data is modified or deleted here).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE = "status IN ('queued', 'running', 'awaiting_approval', 'interrupted')"


def upgrade() -> None:
    dupes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM (SELECT incident_id FROM ops.investigations "
                "WHERE status IN ('queued', 'running', 'awaiting_approval', 'interrupted') "
                "GROUP BY incident_id HAVING count(*) > 1) d"
            )
        )
        .scalar_one()
    )
    if dupes:
        raise RuntimeError(
            f"{dupes} incident(s) have more than one active investigation; cancel or resolve the extras "
            "before applying migration 0005 (nothing was changed)"
        )
    op.add_column("investigations", sa.Column("run_owner", sa.String(length=128), nullable=True), schema="ops")
    op.add_column(
        "investigations", sa.Column("run_lease_until", sa.DateTime(timezone=True), nullable=True), schema="ops"
    )
    op.create_index(
        "uq_ops_investigations_one_active_per_incident",
        "investigations",
        ["incident_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text(ACTIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_ops_investigations_one_active_per_incident", table_name="investigations", schema="ops")
    op.drop_column("investigations", "run_lease_until", schema="ops")
    op.drop_column("investigations", "run_owner", schema="ops")
