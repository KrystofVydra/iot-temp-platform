"""push tokens for mobile push notifications (Round 4 Phase 4D)

Adds the ``push_tokens`` table backing Expo push delivery. Each row is one
Expo push token registered by a mobile device. ``token`` is UNIQUE globally
(not per user) because Expo push tokens are globally unique — a physical
device holds one token, so re-registering it under a new account moves the
row rather than duplicating it.

The detector (ingestor) fans notifications out to every token owned by the
notification's user; invalid tokens are pruned via Expo receipt polling.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-18 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=200), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("app_version", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_used_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_push_tokens_user_id",
        ),
        sa.UniqueConstraint("token", name="uq_push_tokens_token"),
        sa.CheckConstraint(
            "platform IN ('ios', 'android')",
            name="ck_push_tokens_platform",
        ),
    )
    op.create_index(
        "ix_push_tokens_user_id", "push_tokens", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_push_tokens_user_id", table_name="push_tokens")
    op.drop_table("push_tokens")
