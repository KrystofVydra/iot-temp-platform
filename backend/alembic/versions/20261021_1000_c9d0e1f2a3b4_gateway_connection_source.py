"""gateway connection source (WiFi / LTE) tracking

Phase A of the connection-source feature. The MQTT payload has always
carried a ``source`` field; firmware now uses it to report the link the
gateway is on (0 = WiFi, 1 = LTE fallback). Until now the ingestor
validated and then discarded it.

Two storage shapes, because two questions get asked:

  * ``controller_telemetry.source`` — the per-message history, so the
    series can be charted / audited later.
  * ``gateways.last_source`` + ``last_source_changed_at`` — the current
    state plus when it last flipped, so the UI can render "LTE since
    14:32" without scanning the hypertable.

All three columns are nullable: rows written before this migration have
no source, and NULL is rendered as "unknown" rather than guessed at.

``controller_telemetry`` is a TimescaleDB hypertable with a 7-day
compression policy (see ``e5f6a7b8c9d0``). ADD / DROP COLUMN can't touch
compressed chunks, so the migration decompresses everything first and
lets the policy recompress on its next scheduled run — the same pattern
as ``f6a7b8c9d0e1``. ``gateways`` is a plain table and needs no such
dance.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-21 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
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
    # 1. Decompress so ADD COLUMN can touch every chunk.
    op.execute(_DECOMPRESS_ALL)

    # 2. Per-message history.
    op.add_column(
        "controller_telemetry",
        sa.Column("source", sa.SmallInteger(), nullable=True),
    )

    # 3. Current state on the gateway. Both NULL until the next message
    # arrives — the ingestor fills them on the first telemetry it sees.
    op.add_column(
        "gateways",
        sa.Column("last_source", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "gateways",
        sa.Column(
            "last_source_changed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("gateways", "last_source_changed_at")
    op.drop_column("gateways", "last_source")

    op.execute(_DECOMPRESS_ALL)
    op.drop_column("controller_telemetry", "source")
