"""add real auth

Replaces the static API_TOKEN auth model with session-based password auth.

- ``users`` gains: password_hash, display_name, is_admin, is_active, last_login_at
- new ``sessions`` table: server-stored session rows keyed by sha256(raw token)
- new ``auth_tokens`` table: one-time invitations and password resets
- promotes user id=1 to admin (Admin) and labels demo user id=2 as 'Demo User'

Forward-only in practice — downgrade drops new tables / columns and reverses
the display_name label changes (best-effort), but the bcrypt password hashes
on existing users would be lost.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-11 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users: new columns ---------------------------------------------------
    # password_hash is nullable; NULL means "no password set yet" (account is
    # awaiting an invitation acceptance). bcrypt produces fixed 60-char hashes.
    op.add_column("users", sa.Column("password_hash", sa.String(length=60), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "display_name",
            sa.String(length=255),
            nullable=False,
            server_default="User",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # --- sessions ------------------------------------------------------------
    # user_id is BigInteger to match users.id (BIGSERIAL).
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "last_used_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_sessions_user_id"
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"])
    op.create_index(
        "ix_sessions_user_id_expires_at", "sessions", ["user_id", "expires_at"]
    )

    # --- auth_tokens ---------------------------------------------------------
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_tokens_user_id"
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
    )
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])
    op.create_index(
        "ix_auth_tokens_user_id_kind", "auth_tokens", ["user_id", "kind"]
    )

    # --- promote initial admin + label demo user ----------------------------
    op.execute("UPDATE users SET is_admin = TRUE, display_name = 'Admin' WHERE id = 1")
    op.execute("UPDATE users SET display_name = 'Demo User' WHERE id = 2")


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_user_id_kind", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_table("auth_tokens")

    op.drop_index("ix_sessions_user_id_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "display_name")
    op.drop_column("users", "password_hash")
