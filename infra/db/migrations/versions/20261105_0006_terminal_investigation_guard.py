"""terminal investigation guard (C0-G2)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05 14:00:00+00:00

Additive. A ``BEFORE UPDATE`` trigger makes ``completed`` and ``cancelled`` investigations absorbing: any UPDATE that
would change their status raises, whatever code path (or process) issues it. This is the database backstop for the
application transition policy (``domain.investigation.can_transition``), which additionally keeps ``failed``
terminal for background work. No existing row is modified.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.guard_terminal_investigation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('completed', 'cancelled') AND NEW.status IS DISTINCT FROM OLD.status THEN
                RAISE EXCEPTION 'investigation % is % (terminal); status change to % refused',
                    OLD.id, OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_ops_investigations_terminal_guard BEFORE UPDATE OF status ON ops.investigations "
        "FOR EACH ROW EXECUTE FUNCTION ops.guard_terminal_investigation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ops_investigations_terminal_guard ON ops.investigations")
    op.execute("DROP FUNCTION IF EXISTS ops.guard_terminal_investigation()")
