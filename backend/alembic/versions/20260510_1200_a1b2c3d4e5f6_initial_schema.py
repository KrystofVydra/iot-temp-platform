"""initial schema

Creates ``users``, ``devices``, and ``readings``. Enables the TimescaleDB
extension and converts ``readings`` into a hypertable partitioned on
``time``. The supporting ``(device_id, time DESC)`` index is created
explicitly so the DESC ordering is preserved.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-10 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The extension must exist before create_hypertable can be called.
    # init.sql creates it on first boot too; this keeps migrations standalone.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_devices_user_id"
        ),
        sa.UniqueConstraint("device_key", name="uq_devices_device_key"),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])

    op.create_table(
        "readings",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("temperature", sa.REAL(), nullable=False),
        sa.Column("lux", sa.Integer(), nullable=False),
        sa.Column("battery_raw", sa.Integer(), nullable=True),
        sa.Column("rssi", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("time", "device_id", name="pk_readings"),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE", name="fk_readings_device_id"
        ),
    )

    # Convert readings into a TimescaleDB hypertable. Must happen after the
    # table is created and before any rows are inserted.
    op.execute(
        "SELECT create_hypertable('readings', 'time', if_not_exists => TRUE)"
    )

    # DESC ordering on time is the access pattern for "latest readings" queries.
    op.execute(
        "CREATE INDEX idx_readings_device_time ON readings (device_id, time DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_readings_device_time")
    # drop_table on a hypertable removes the hypertable and its chunks.
    op.drop_table("readings")
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
    op.drop_table("users")
    # Intentionally not dropping the timescaledb extension — other databases
    # in the cluster may rely on it.
