"""User push-token registration endpoints.

Mobile devices register their Expo push token here so the detector can fan
notifications out to them. Tokens are globally unique (one physical device
holds one token), so registering an existing token re-associates it to the
current user rather than creating a duplicate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..auth import get_current_user
from ..db import get_db
from ..models import PushToken, User
from ..push import send_test_push

router = APIRouter(prefix="/me/push-tokens", tags=["push-tokens"])


@router.post("", response_model=schemas.PushTokenOut, status_code=status.HTTP_201_CREATED)
async def register_token(
    payload: schemas.PushTokenIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushToken:
    # UPSERT: find by token (globally unique). If it exists, re-associate to
    # the current user and refresh metadata + last_used_at.
    existing = (
        await db.execute(select(PushToken).where(PushToken.token == payload.token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        existing.user_id = current_user.id
        existing.platform = payload.platform
        existing.device_name = payload.device_name
        existing.app_version = payload.app_version
        existing.last_used_at = now
        await db.commit()
        await db.refresh(existing)
        return existing
    row = PushToken(
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
        device_name=payload.device_name,
        app_version=payload.app_version,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=list[schemas.PushTokenOut])
async def list_my_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PushToken]:
    rows = (
        await db.execute(
            select(PushToken)
            .where(PushToken.user_id == current_user.id)
            .order_by(PushToken.last_used_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.post("/deregister", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_by_token(
    payload: schemas.DeregisterPushTokenIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(PushToken).where(
                PushToken.token == payload.token,
                PushToken.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    # Idempotent: 204 whether or not the row existed.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(PushToken).where(
                PushToken.id == token_id,
                PushToken.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{token_id}/test", response_model=schemas.TestPushOut)
async def test_push(
    token_id: int,
    payload: schemas.TestPushIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(PushToken).where(
                PushToken.id == token_id,
                PushToken.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    title = payload.title or "Test notification"
    body = payload.body or "Push works — this is a test."
    return await send_test_push(row.token, title, body)
