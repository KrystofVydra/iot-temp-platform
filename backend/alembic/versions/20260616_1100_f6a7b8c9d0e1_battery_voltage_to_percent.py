"""battery storage: voltage → percentage

Phase: pre-Round-4 cleanup. ``controller_telemetry.battery_v`` (REAL volts)
is replaced with ``battery_pct`` (SMALLINT 0–100). The wire payload from
firmware is unchanged — only the ingestor's conversion and the column
storing the result move.

Existing rows are converted in-place via the inverse of the firmware mapping
(``volts = 1.4 + (b/255) * 2.2`` → ``pct = round((volts - 1.4) / 2.2 * 100)``)
and clamped to [0, 100].

``controller_telemetry`` is a TimescaleDB hypertable with a 7-day
compression policy attached, so any chunks older than 7 days are
compressed. UPDATE and DROP COLUMN can't touch compressed chunks, so the
migration decompresses everything first and lets the policy recompress
naturally on the next run.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-16 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DECOMPRESS_ALL = """
DO $$
DECLARE
    chunk regclass;
BEGIN
    FOR chunk IN
        SELECT format('%I.%I', chunk_schema, chunk_name)::regclass
        FROM timescaledb_information.chunks
        WHERE hypertable_name = 'controller_telemetry'
          AND is_compressed
    LOOP
        PERFORM decompress_chunk(chunk);
    END LOOP;
END$$;
"""


def upgrade() -> None:
    # 1. Decompress so UPDATE / DROP COLUMN can touch every chunk.
    op.execute(_DECOMPRESS_ALL)

    # 2. Add the new column (nullable — no default needed).
    op.add_column(
        "controller_telemetry",
        sa.Column("battery_pct", sa.SmallInteger(), nullable=True),
    )

    # 3. Convert existing rows. Firmware sends b ∈ [0, 255] mapped linearly
    # to [1.4 V, 3.6 V]; the inverse is below, clamped to [0, 100].
    op.execute(
        """
        UPDATE controller_telemetry
        SET battery_pct = GREATEST(
            0,
            LEAST(
                100,
                ROUND(((battery_v - 1.4) / 2.2) * 100)::int
            )
        )
        WHERE battery_v IS NOT NULL
        """
    )

    # 4. Drop the old column. The compression policy will re-compress on its
    # next scheduled run; we don't force it here.
    op.drop_column("controller_telemetry", "battery_v")


def downgrade() -> None:
    op.execute(_DECOMPRESS_ALL)

    op.add_column(
        "controller_telemetry",
        sa.Column("battery_v", sa.REAL(), nullable=True),
    )

    # Reverse mapping. Clamp lower bound at 1.4 V (the floor of the original
    # range — anything that came in as 0 % maps back to 1.4 V exactly).
    op.execute(
        """
        UPDATE controller_telemetry
        SET battery_v = GREATEST(
            1.4,
            1.4 + (battery_pct::real / 100.0) * 2.2
        )
        WHERE battery_pct IS NOT NULL
        """
    )

    op.drop_column("controller_telemetry", "battery_pct")
