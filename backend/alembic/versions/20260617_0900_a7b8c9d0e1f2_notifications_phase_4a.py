"""notification settings infrastructure (Round 4 Phase 4A)

Lays the schema for the notification system. The detector that *creates*
notification rows lands in Phase 4B; this migration only stands up:

  * ``notification_kind_defaults`` — global catalogue of the 11 kinds
    (severity, scope, default thresholds, description). Editable by
    admins; sets the defaults applied to new users at creation time.
  * ``notification_settings`` — per-user per-kind toggle + threshold
    overrides. Every existing user is backfilled with one row per kind
    using the seeded defaults. ``backend/app/routers/admin.py`` is updated
    in the same commit to insert defaults for any **new** user too.
  * ``notifications`` — the firing log. Two partial indexes on
    ``(user_id) WHERE resolved_at IS NULL`` and ``(user_id) WHERE read_at
    IS NULL`` keep the bell-badge and active-list queries cheap.

The notifications table stays empty until Phase 4B brings the detector
online.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-17 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (kind, severity, scope, enabled_default, thresholds_json, description)
_SEEDED_KINDS: list[tuple[str, str, str, bool, str, str]] = [
    (
        "temp_safe", "critical", "controller", True,
        '{"safe_min": 2.0, "safe_max": 6.0}',
        "Temperature outside the safe range — immediate attention required.",
    ),
    (
        "temp_preferred", "alert", "controller", True,
        '{"preferred_min": 3.0, "preferred_max": 5.0}',
        "Temperature outside the preferred range but still safe.",
    ),
    (
        "temp_drift", "alert", "controller", True,
        '{"drift_c": 3.0, "drift_minutes": 10}',
        "Temperature changed sharply over a short period.",
    ),
    (
        "door_open", "critical", "controller", True,
        '{"max_open_minutes": 5}',
        "Door has been open longer than the threshold.",
    ),
    (
        "controller_offline", "critical", "controller", True,
        '{"offline_minutes": 5}',
        "Controller has not reported in the threshold time.",
    ),
    (
        "gateway_offline", "critical", "gateway", True,
        '{"offline_minutes": 5}',
        "Gateway has not reported in the threshold time.",
    ),
    (
        "multi_controller_offline", "critical", "gateway", True,
        "{}",
        "Multiple controllers on the same gateway went offline simultaneously.",
    ),
    (
        "battery_critical", "critical", "controller", True,
        '{"critical_pct": 10}',
        "Battery level critically low.",
    ),
    (
        "battery_low", "alert", "controller", True,
        '{"low_pct": 25}',
        "Battery level getting low.",
    ),
    (
        "node_error_single", "alert", "node", True,
        "{}",
        "One node reported a sensor or comms error.",
    ),
    (
        "node_error_cumulative", "critical", "controller", True,
        "{}",
        "Multiple nodes on the same controller reported errors.",
    ),
]


def upgrade() -> None:
    # ----- notification_kind_defaults -----
    op.create_table(
        "notification_kind_defaults",
        sa.Column("kind", sa.String(length=50), primary_key=True),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column(
            "enabled_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'alert')",
            name="ck_kind_defaults_severity",
        ),
        sa.CheckConstraint(
            "scope IN ('gateway', 'controller', 'node')",
            name="ck_kind_defaults_scope",
        ),
    )

    # Seed all 11 kinds. Parametrized inserts avoid any risk of bad escaping
    # in the description strings.
    insert_sql = sa.text(
        """
        INSERT INTO notification_kind_defaults
            (kind, severity, scope, enabled_default, thresholds, description)
        VALUES
            (:kind, :severity, :scope, :enabled_default,
             CAST(:thresholds AS JSONB), :description)
        """
    )
    bind = op.get_bind()
    for kind, severity, scope, enabled, thresholds, description in _SEEDED_KINDS:
        bind.execute(
            insert_sql,
            {
                "kind": kind,
                "severity": severity,
                "scope": scope,
                "enabled_default": enabled,
                "thresholds": thresholds,
                "description": description,
            },
        )

    # ----- notification_settings -----
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_notification_settings_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["notification_kind_defaults.kind"],
            ondelete="CASCADE",
            name="fk_notification_settings_kind",
        ),
        sa.UniqueConstraint(
            "user_id", "kind", name="uq_notification_settings_user_kind"
        ),
    )
    op.create_index(
        "ix_notification_settings_user_id",
        "notification_settings",
        ["user_id"],
    )

    # Backfill: cross-join existing users × all kinds. enabled / thresholds
    # come straight from the seeded defaults.
    op.execute(
        """
        INSERT INTO notification_settings (user_id, kind, enabled, thresholds)
        SELECT u.id, d.kind, d.enabled_default, d.thresholds
        FROM users u
        CROSS JOIN notification_kind_defaults d
        """
    )

    # ----- notifications -----
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("gateway_id", sa.BigInteger(), nullable=True),
        sa.Column("controller_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_name", sa.String(length=255), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "opened_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_notifications_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["notification_kind_defaults.kind"],
            ondelete="CASCADE",
            name="fk_notifications_kind",
        ),
        sa.ForeignKeyConstraint(
            ["gateway_id"],
            ["gateways.id"],
            ondelete="CASCADE",
            name="fk_notifications_gateway_id",
        ),
        sa.ForeignKeyConstraint(
            ["controller_id"],
            ["controllers.id"],
            ondelete="CASCADE",
            name="fk_notifications_controller_id",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
            ondelete="CASCADE",
            name="fk_notifications_node_id",
        ),
    )
    op.create_index(
        "ix_notifications_user_opened",
        "notifications",
        ["user_id", sa.text("opened_at DESC")],
    )
    op.execute(
        "CREATE INDEX ix_notifications_user_active "
        "ON notifications (user_id) WHERE resolved_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_notifications_user_unread "
        "ON notifications (user_id) WHERE read_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_user_unread")
    op.execute("DROP INDEX IF EXISTS ix_notifications_user_active")
    op.drop_index("ix_notifications_user_opened", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(
        "ix_notification_settings_user_id", table_name="notification_settings"
    )
    op.drop_table("notification_settings")

    op.drop_table("notification_kind_defaults")
