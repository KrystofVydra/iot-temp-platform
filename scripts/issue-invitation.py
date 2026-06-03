#!/usr/bin/env python3
"""Issue a one-time invitation token for a user.

Used during the auth cutover: run once against production to issue yourself
an invitation, then visit the printed URL to set your admin password.

Stays standalone (no SQLAlchemy / app imports) so it can be run from a
plain asyncpg-only image without the full backend installed — mirrors the
backfill.py pattern.

Usage:
    DATABASE_URL=postgresql+asyncpg://iot:pass@host:5432/iot \\
    FRONTEND_ORIGIN=https://app.otti.cz \\
        python issue-invitation.py admin@example.com [--force]

Exits non-zero on any failure so callers can branch on it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta

import asyncpg

INVITATION_TTL = timedelta(days=7)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Issue an invitation token.")
    parser.add_argument("email", help="email address of an existing user")
    parser.add_argument(
        "--force",
        action="store_true",
        help="issue even if the user already has a password (emergency unlock)",
    )
    args = parser.parse_args()

    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        print("Error: DATABASE_URL must be set", file=sys.stderr)
        return 1
    # asyncpg expects bare postgres URLs.
    asyncpg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    frontend = os.environ.get("FRONTEND_ORIGIN", "https://app.otti.cz")
    email = args.email.strip().lower()

    conn = await asyncpg.connect(asyncpg_url)
    try:
        user = await conn.fetchrow(
            "SELECT id, password_hash FROM users WHERE email = $1", email
        )
        if user is None:
            print(f"Error: no user with email {email}", file=sys.stderr)
            return 2

        if user["password_hash"] is not None and not args.force:
            print(
                f"Error: user {email} already has a password set. "
                "Re-run with --force to issue anyway.",
                file=sys.stderr,
            )
            return 3

        raw = secrets.token_urlsafe(32)
        token_hash_value = _hash_token(raw)
        now = datetime.now(UTC)
        expires_at = now + INVITATION_TTL

        await conn.execute(
            """
            INSERT INTO auth_tokens (user_id, kind, token_hash, expires_at)
            VALUES ($1, 'invitation', $2, $3)
            """,
            user["id"],
            token_hash_value,
            expires_at,
        )

        url = f"{frontend}/accept-invitation?token={raw}"
        print()
        print("=" * 64)
        print("Invitation issued.")
        print(f"  User:    {email} (id={user['id']})")
        print(f"  Expires: {expires_at.isoformat()}")
        print()
        print(f"  {url}")
        print()
        print("Visit the URL within 7 days to set the password.")
        print("=" * 64)
    finally:
        await conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
