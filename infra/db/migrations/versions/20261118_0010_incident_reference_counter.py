"""durable incident reference counter (v0.5)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18 16:00:00+00:00

Incident references (``INC-YYYYMMDD-NNNN``) were numbered from the incidents that still exist (count, then max + 1).
Since uploaded incidents can be deleted (v0.5), a number could be handed out again. ``ops.incident_reference_counters``
keeps the last number issued per day; ``repositories.next_incident_reference`` increments it with a single
``INSERT … ON CONFLICT DO UPDATE … RETURNING`` in the incident's transaction, so concurrent creators serialize on the
row lock and a number is never reused after a deletion. Seeded from existing references.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_reference_counters",
        sa.Column("day", sa.String(8), primary_key=True),  # YYYYMMDD, as in the reference
        sa.Column("last_number", sa.Integer, nullable=False),
        schema="ops",
    )
    op.execute(
        "INSERT INTO ops.incident_reference_counters (day, last_number) "
        "SELECT substr(reference, 5, 8), max(substr(reference, 14)::int) FROM ops.incidents "
        "WHERE reference ~ '^INC-[0-9]{8}-[0-9]+$' GROUP BY substr(reference, 5, 8)"
    )


def downgrade() -> None:
    op.drop_table("incident_reference_counters", schema="ops")
