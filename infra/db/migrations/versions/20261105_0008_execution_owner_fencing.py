"""execution-owner fencing (C0-H2)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05 16:30:00+00:00

Database-enforced fencing for the single execution owner (C0-G4 advisory lock):

- ``ops.execution_owner`` (one row): ``epoch`` is incremented by every new owner right after it takes the advisory
  lock, together with the PID of the session that holds the lock.
- ``ops.execution_fence(epoch, pid)``: raises ``OPF01`` unless ``epoch`` is the current epoch *and* that session still
  holds the lock. It takes ``FOR SHARE`` on the row, so it is atomic with the caller's transaction: a new owner's epoch
  increment (``UPDATE``) waits until every in-flight fenced write has committed, and every later write of the old
  owner fails. Writes of a previous owner can therefore never interleave with the new owner's.
- ``ops.fence_checkpoint_write()``: statement-level trigger function for the LangGraph checkpoint tables. It reads the
  fence the connection was opened with (``opspilot.owner_epoch`` / ``opspilot.owner_pid``); a connection without one
  cannot write checkpoints at all. The triggers themselves are installed by ``opspilot migrate`` after LangGraph's own
  ``setup()`` creates those tables (``checkpointing.install_fencing``).

Additive; no existing row is modified.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NAMESPACE = 0x4F505350  # must match opspilot_api.ownership (inlined below as 1330664272)
LOCK_EXECUTION_OWNER = 1
assert LOCK_NAMESPACE == 1330664272


def upgrade() -> None:
    op.execute(
        "CREATE TABLE ops.execution_owner ("
        " id smallint PRIMARY KEY CHECK (id = 1),"
        " epoch bigint NOT NULL DEFAULT 0,"
        " owner text,"
        " owner_pid integer,"
        " acquired_at timestamptz)"
    )
    op.execute("INSERT INTO ops.execution_owner (id, epoch) VALUES (1, 0)")
    # pg_locks classid/objid literals: LOCK_NAMESPACE (0x4F505350 = 1330664272) and LOCK_EXECUTION_OWNER (1).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.execution_fence(p_epoch bigint, p_pid integer) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, ops AS $$
        DECLARE
            cur_epoch bigint;
            cur_pid integer;
        BEGIN
            IF p_epoch IS NULL OR p_pid IS NULL THEN
                RAISE EXCEPTION 'execution fence: write without execution ownership' USING ERRCODE = 'OPF01';
            END IF;
            SELECT epoch, owner_pid INTO cur_epoch, cur_pid FROM ops.execution_owner WHERE id = 1 FOR SHARE;
            IF cur_epoch IS DISTINCT FROM p_epoch OR cur_pid IS DISTINCT FROM p_pid THEN
                RAISE EXCEPTION 'execution fence: stale execution owner (epoch %, current %)', p_epoch, cur_epoch
                    USING ERRCODE = 'OPF01';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_locks
                WHERE locktype = 'advisory' AND classid = 1330664272 AND objid = 1
                  AND objsubid = 2 AND granted AND pid = p_pid
                  AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
            ) THEN
                RAISE EXCEPTION 'execution fence: owner session % no longer holds the execution-owner lock', p_pid
                    USING ERRCODE = 'OPF01';
            END IF;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ops.execution_fence(bigint, integer) FROM PUBLIC")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.fence_checkpoint_write() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, ops AS $$
        BEGIN
            PERFORM ops.execution_fence(
                nullif(current_setting('opspilot.owner_epoch', true), '')::bigint,
                nullif(current_setting('opspilot.owner_pid', true), '')::integer
            );
            RETURN NULL;
        END;
        $$
        """
    )


def downgrade() -> None:
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_fence_{table} ON langgraph.{table}")
    op.execute("DROP FUNCTION IF EXISTS ops.fence_checkpoint_write()")
    op.execute("DROP FUNCTION IF EXISTS ops.execution_fence(bigint, integer)")
    op.execute("DROP TABLE IF EXISTS ops.execution_owner")
