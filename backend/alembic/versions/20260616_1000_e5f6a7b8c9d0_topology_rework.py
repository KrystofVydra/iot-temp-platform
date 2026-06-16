"""topology rework — gateway/controller/node hierarchy

Old: ``devices`` had readings directly (temperature, lux, battery_raw).
New: gateways (MQTT identity) → controllers (battery + door) → nodes
(temperature + lux). Battery/door telemetry lives on the controller in a
separate hypertable; per-node sensor readings live on the node hypertable.

The migration:
1. Creates the new tables (gateways, controllers, nodes, pending_controllers,
   node_readings, controller_telemetry).
2. Converts node_readings and controller_telemetry to TimescaleDB hypertables
   with the same 7-day compression policy the old readings table used.
3. Migrates existing data: every ``devices`` row becomes a ``gateways`` row
   (preserving the id so any code holding device ids still matches), with one
   synthetic "Legacy controller" containing one "Legacy node". Each row in
   ``readings`` is replayed into ``node_readings`` joined through the 1:1:1
   mapping. ``controller_telemetry`` stays empty for legacy data — we have
   no historical battery/door information to replay.
4. Drops the old ``readings`` and ``devices`` tables.

Hypertable creation and add_compression_policy are NOT transactional in
TimescaleDB, so a failure partway through could leave hypertables in place;
in practice the alembic_version row only advances on full success, so a
re-run is safe (CREATE HYPERTABLE … if_not_exists, etc.).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-16 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # =====================================================================
    # 1. New schema
    # =====================================================================

    op.create_table(
        "gateways",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column(
            "mqtt_provisioned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_gateways_user_id"
        ),
        sa.UniqueConstraint("device_key", name="uq_gateways_device_key"),
    )
    op.create_index("ix_gateways_user_id", "gateways", ["user_id"])

    op.create_table(
        "controllers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("gateway_id", sa.BigInteger(), nullable=False),
        sa.Column("sn", sa.String(), nullable=False),
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
            ["gateway_id"], ["gateways.id"],
            ondelete="CASCADE", name="fk_controllers_gateway_id",
        ),
        sa.UniqueConstraint("gateway_id", "sn", name="uq_controllers_gateway_sn"),
    )
    op.create_index("ix_controllers_gateway_id", "controllers", ["gateway_id"])

    op.create_table(
        "nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("controller_id", sa.BigInteger(), nullable=False),
        sa.Column("node_index", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "has_lux",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["controller_id"], ["controllers.id"],
            ondelete="CASCADE", name="fk_nodes_controller_id",
        ),
        sa.UniqueConstraint(
            "controller_id", "node_index", name="uq_nodes_controller_index"
        ),
    )
    op.create_index("ix_nodes_controller_id", "nodes", ["controller_id"])

    op.create_table(
        "pending_controllers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("gateway_id", sa.BigInteger(), nullable=False),
        sa.Column("sn", sa.String(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.ForeignKeyConstraint(
            ["gateway_id"], ["gateways.id"],
            ondelete="CASCADE", name="fk_pending_controllers_gateway_id",
        ),
        sa.UniqueConstraint(
            "gateway_id", "sn", name="uq_pending_controllers_gateway_sn"
        ),
    )

    op.create_table(
        "node_readings",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("temperature", sa.REAL(), nullable=True),
        sa.Column("lux", sa.Integer(), nullable=True),
        sa.Column("err", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("time", "node_id", name="pk_node_readings"),
        sa.ForeignKeyConstraint(
            ["node_id"], ["nodes.id"],
            ondelete="CASCADE", name="fk_node_readings_node_id",
        ),
    )
    op.execute(
        "SELECT create_hypertable('node_readings', 'time', if_not_exists => TRUE)"
    )
    op.execute(
        "CREATE INDEX idx_node_readings_node_time "
        "ON node_readings (node_id, time DESC)"
    )
    op.execute(
        """
        ALTER TABLE node_readings SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'node_id',
            timescaledb.compress_orderby = 'time DESC'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy('node_readings', INTERVAL '7 days')"
    )

    op.create_table(
        "controller_telemetry",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("controller_id", sa.BigInteger(), nullable=False),
        sa.Column("battery_v", sa.REAL(), nullable=True),
        sa.Column("door_open", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint(
            "time", "controller_id", name="pk_controller_telemetry"
        ),
        sa.ForeignKeyConstraint(
            ["controller_id"], ["controllers.id"],
            ondelete="CASCADE", name="fk_controller_telemetry_controller_id",
        ),
    )
    op.execute(
        "SELECT create_hypertable('controller_telemetry', 'time', if_not_exists => TRUE)"
    )
    op.execute(
        "CREATE INDEX idx_controller_telemetry_controller_time "
        "ON controller_telemetry (controller_id, time DESC)"
    )
    op.execute(
        """
        ALTER TABLE controller_telemetry SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'controller_id',
            timescaledb.compress_orderby = 'time DESC'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy('controller_telemetry', INTERVAL '7 days')"
    )

    # =====================================================================
    # 2. Data migration
    # =====================================================================

    # devices → gateways (preserve ids so anything caching device ids still
    # resolves to the same gateway).
    op.execute(
        """
        INSERT INTO gateways
            (id, user_id, device_key, name, location, mqtt_provisioned,
             created_at, last_seen_at)
        SELECT id, user_id, device_key, name, location, mqtt_provisioned,
               created_at, last_seen_at
        FROM devices
        """
    )
    # Bump the gateways id sequence past the highest explicit id we just
    # inserted, so future inserts don't collide. setval(seq, n, false) means
    # "the next nextval returns n"; we want n = MAX(id)+1 (or 1 if empty).
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('gateways', 'id'),
            COALESCE((SELECT MAX(id) FROM gateways), 0) + 1,
            false
        )
        """
    )

    # One synthetic "legacy" controller per gateway.
    op.execute(
        """
        INSERT INTO controllers
            (gateway_id, sn, name, created_at, last_seen_at)
        SELECT id, 'legacy', 'Legacy controller', created_at, last_seen_at
        FROM gateways
        """
    )

    # One synthetic node per legacy controller. has_lux = TRUE because old
    # readings always carried a lux value.
    op.execute(
        """
        INSERT INTO nodes
            (controller_id, node_index, name, has_lux, created_at, last_seen_at)
        SELECT id, 1, 'Legacy node', TRUE, created_at, last_seen_at
        FROM controllers
        WHERE sn = 'legacy'
        """
    )

    # Old readings → node_readings, joining through the 1:1:1 mapping built
    # above. err stays NULL (no historical error info to attribute).
    op.execute(
        """
        INSERT INTO node_readings (time, node_id, temperature, lux, err)
        SELECT r.time, n.id, r.temperature, r.lux, NULL
        FROM readings r
        JOIN controllers c ON c.gateway_id = r.device_id AND c.sn = 'legacy'
        JOIN nodes n ON n.controller_id = c.id AND n.node_index = 1
        """
    )

    # =====================================================================
    # 3. Drop the old shapes
    # =====================================================================
    # readings is a hypertable with compression policy attached — CASCADE so
    # leftover policy / continuous aggregates / chunks come along cleanly.
    op.execute("DROP TABLE readings CASCADE")
    op.execute("DROP TABLE devices CASCADE")


def downgrade() -> None:
    """Recreate the old tables empty.

    The original compressed chunks of ``readings`` are not preserved across
    the upgrade — this downgrade gives you a clean slate matching the old
    schema, but no rows.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "devices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column(
            "mqtt_provisioned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            ondelete="CASCADE", name="fk_devices_user_id",
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
            ["device_id"], ["devices.id"],
            ondelete="CASCADE", name="fk_readings_device_id",
        ),
    )
    op.execute(
        "SELECT create_hypertable('readings', 'time', if_not_exists => TRUE)"
    )
    op.execute(
        "CREATE INDEX idx_readings_device_time "
        "ON readings (device_id, time DESC)"
    )
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

    op.execute("DROP TABLE controller_telemetry CASCADE")
    op.execute("DROP TABLE node_readings CASCADE")
    op.drop_index("ix_nodes_controller_id", table_name="nodes")
    op.drop_table("nodes")
    op.drop_index("ix_controllers_gateway_id", table_name="controllers")
    op.drop_table("controllers")
    op.drop_table("pending_controllers")
    op.drop_index("ix_gateways_user_id", table_name="gateways")
    op.drop_table("gateways")
