"""enable timescaledb compression on readings

Turns on row-level compression for the ``readings`` hypertable with
``segmentby = device_id`` (queries almost always filter by device) and
``orderby = time DESC`` (matches latest-reading access). A background
policy compresses chunks older than 7 days.

Compression typically shrinks time-series storage by 90%+ and accelerates
range scans, at the cost of making compressed chunks effectively read-only
(INSERT/UPDATE on them is rejected by TimescaleDB).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-11 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE readings SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'device_id',
            timescaledb.compress_orderby = 'time DESC'
        )
        """
    )
    op.execute("SELECT add_compression_policy('readings', INTERVAL '7 days')")


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('readings', if_exists => true)")

    # Decompress any compressed chunks. Wrapped in a DO block + exception
    # handler so the downgrade still succeeds if the hypertable has no
    # compressed chunks or the extension has already been removed in a
    # partial-rollback scenario.
    op.execute(
        """
        DO $$
        BEGIN
            PERFORM decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass)
            FROM timescaledb_information.chunks
            WHERE hypertable_name = 'readings' AND is_compressed;
        EXCEPTION WHEN OTHERS THEN
            -- nothing to decompress, or extension already gone — ignore
            NULL;
        END;
        $$
        """
    )

    op.execute("ALTER TABLE readings SET (timescaledb.compress = false)")
