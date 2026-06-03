"""Real session-based authentication.

Replaces the static API_TOKEN auth from Phase 4. Passwords are bcrypt-hashed.
Sessions are server-side rows keyed by sha256(raw_cookie_value); the raw
value is delivered to the client as an httpOnly cookie. Invitation and
password-reset tokens use the same hash-on-store / raw-in-URL pattern.

We never store raw tokens at rest, so a database leak doesn't grant session
access. Constant-time comparison is provided by bcrypt for passwords; for
session/invitation/reset tokens, exact-equality lookups on the sha256 hash
are constant-time relative to the candidate token (the hash function eats
any per-input timing variation).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import Session, User

SESSION_TTL = timedelta(days=30)
INVITATION_TOKEN_TTL = timedelta(days=7)
PASSWORD_RESET_TOKEN_TTL = timedelta(hours=1)

SESSION_COOKIE_NAME = "session_token"

# Pre-computed bcrypt hash of a random string. Used as a dummy comparison
# target on login when the user doesn't exist, so the timing of the failure
# path matches the success path. Generated once at import time.
_DUMMY_BCRYPT_HASH: bytes = bcrypt.hashpw(
    secrets.token_bytes(32), bcrypt.gensalt(rounds=12)
)


def hash_password(password: str) -> str:
    """bcrypt-hash a plaintext password with the configured cost factor."""
    rounds = get_settings().BCRYPT_ROUNDS
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt verification. Malformed hashes return False."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_token(raw: str) -> str:
    """SHA-256 hex of a raw token — the storage key for sessions + auth_tokens."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)`` — raw to the client, hex to the DB."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def constant_time_dummy_password_check() -> None:
    """Run a bcrypt verify against a dummy hash.

    Called on login failure paths where no real user was found, so the
    overall response time doesn't reveal email enumeration.
    """
    bcrypt.checkpw(b"dummy", _DUMMY_BCRYPT_HASH)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Resolve the current ``User`` from the ``session_token`` cookie.

    Raises 401 on missing/invalid/expired session or disabled user. Touches
    ``last_used_at`` on success so we can later expire idle sessions.
    """
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    token_hash_value = hash_token(raw)
    now = datetime.now(UTC)

    stmt = (
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.token_hash == token_hash_value)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")

    session, user = row
    if session.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account disabled")

    # Refresh last_used_at. Inexpensive at this scale; if this becomes hot
    # we can rate-limit (e.g. only update if older than 60s).
    await db.execute(
        update(Session).where(Session.id == session.id).values(last_used_at=now)
    )
    await db.commit()
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Authenticated + ``is_admin``. 403 if not. Not used in Round 1; ready for Round 2."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user
