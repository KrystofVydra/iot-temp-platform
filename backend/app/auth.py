"""V1 authentication: a single static bearer token compared constant-time."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings

_INVALID = "invalid or missing api token"


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """Verify ``Authorization: Bearer <token>`` against ``settings.API_TOKEN``."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID)
    token = authorization.removeprefix("Bearer ").strip()
    expected = get_settings().API_TOKEN
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID)
