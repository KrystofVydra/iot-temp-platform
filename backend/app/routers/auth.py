"""Authentication endpoints — login, logout, me, forgot/reset, accept-invitation.

All token-bearing URLs (invitation + password-reset) are constructed using
``FRONTEND_ORIGIN`` so the SPA can route them. While ``EXPOSE_AUTH_LINKS`` is
True the reset/invitation URLs are returned in the API response so an
operator can hand-deliver them; once email delivery is wired up the flag is
flipped to False and the URLs are only ever emailed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    PASSWORD_RESET_TOKEN_TTL,
    SESSION_COOKIE_NAME,
    SESSION_TTL,
    constant_time_dummy_password_check,
    generate_token,
    get_current_user,
    hash_password,
    hash_token,
    verify_password,
)
from ..config import get_settings
from ..db import get_db
from ..models import (
    AuthToken,
    User,
)
from ..models import Session as UserSession

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_INVALID = "invalid credentials"


# --- request / response shapes --------------------------------------------


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool


class ForgotPasswordIn(BaseModel):
    email: str


class ForgotPasswordOut(BaseModel):
    # Always present in the response shape. Populated only while
    # EXPOSE_AUTH_LINKS is True; null otherwise.
    reset_url: str | None = None


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class ResetPasswordOut(BaseModel):
    success: bool


class AcceptInvitationIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


# --- internal helpers -----------------------------------------------------


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=int(SESSION_TTL.total_seconds()),
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


async def _issue_session(
    db: AsyncSession, user_id: int, user_agent: str | None
) -> str:
    """Generate a session row + return the raw cookie value to hand to the client."""
    raw, token_hash_value = generate_token()
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=token_hash_value,
            expires_at=datetime.now(UTC) + SESSION_TTL,
            user_agent=user_agent,
        )
    )
    return raw


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


# --- endpoints ------------------------------------------------------------


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    email = payload.email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    # Single generic failure response. Order of checks matters less than
    # avoiding leakage of which check failed.
    if user is None or not user.is_active or user.password_hash is None:
        # Burn one bcrypt verify so timing matches the success path.
        constant_time_dummy_password_check()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_INVALID)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_INVALID)

    raw = await _issue_session(db, user.id, request.headers.get("user-agent"))
    await db.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
    )
    await db.commit()
    _set_session_cookie(response, raw)
    return _user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),  # noqa: ARG001  enforces auth
    db: AsyncSession = Depends(get_db),
) -> Response:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if raw:
        await db.execute(
            delete(UserSession).where(UserSession.token_hash == hash_token(raw))
        )
        await db.commit()
    _clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post("/forgot-password", response_model=ForgotPasswordOut)
async def forgot_password(
    payload: ForgotPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordOut:
    """Always returns 200 with the same shape regardless of whether the email
    matched a real user, to avoid enumeration. While EXPOSE_AUTH_LINKS is
    True the reset URL is included so an operator can hand-deliver it; once
    email is wired up the flag is flipped and reset_url stays None.
    """
    settings = get_settings()
    email = payload.email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    reset_url: str | None = None
    if user is not None and user.is_active and user.password_hash is not None:
        raw, token_hash_value = generate_token()
        db.add(
            AuthToken(
                user_id=user.id,
                kind="password_reset",
                token_hash=token_hash_value,
                expires_at=datetime.now(UTC) + PASSWORD_RESET_TOKEN_TTL,
            )
        )
        await db.commit()
        if settings.EXPOSE_AUTH_LINKS:
            reset_url = f"{settings.FRONTEND_ORIGIN}/set-password?token={raw}&mode=reset"

    return ForgotPasswordOut(reset_url=reset_url)


@router.post("/reset-password", response_model=ResetPasswordOut)
async def reset_password(
    payload: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordOut:
    now = datetime.now(UTC)
    token = (
        await db.execute(
            select(AuthToken).where(
                AuthToken.token_hash == hash_token(payload.token),
                AuthToken.kind == "password_reset",
            )
        )
    ).scalar_one_or_none()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    new_hash = hash_password(payload.new_password)
    await db.execute(
        update(User).where(User.id == token.user_id).values(password_hash=new_hash)
    )
    await db.execute(
        update(AuthToken).where(AuthToken.id == token.id).values(used_at=now)
    )
    # Invalidate any existing sessions on other devices — a password reset
    # implies the user no longer trusts whatever sessions were out there.
    await db.execute(delete(UserSession).where(UserSession.user_id == token.user_id))
    await db.commit()
    return ResetPasswordOut(success=True)


@router.post("/accept-invitation", response_model=UserOut)
async def accept_invitation(
    payload: AcceptInvitationIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    now = datetime.now(UTC)
    token = (
        await db.execute(
            select(AuthToken).where(
                AuthToken.token_hash == hash_token(payload.token),
                AuthToken.kind == "invitation",
            )
        )
    ).scalar_one_or_none()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    new_hash = hash_password(payload.password)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(password_hash=new_hash, last_login_at=now)
    )
    await db.execute(
        update(AuthToken).where(AuthToken.id == token.id).values(used_at=now)
    )
    raw = await _issue_session(db, user.id, request.headers.get("user-agent"))
    await db.commit()
    _set_session_cookie(response, raw)

    # Re-fetch so the response reflects the freshly-updated row.
    await db.refresh(user)
    return _user_out(user)
