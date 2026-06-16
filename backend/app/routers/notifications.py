"""User-facing notification endpoints.

The notifications table is empty until Phase 4B brings the detector
online, but the surface this router exposes (settings, list, mark-read,
unread-count) is already wired so the web app can drive the bell icon
and the preferences UI from day one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    Notification,
    NotificationKindDefault,
    NotificationSetting,
    User,
)
from ..notification_messages import build_summary
from ..notification_validation import validate_thresholds
from ..schemas import (
    NotificationListOut,
    NotificationOut,
    NotificationSettingOut,
    PatchNotificationSettingIn,
)

log = logging.getLogger("notifications")

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=list[NotificationSettingOut])
async def get_my_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationSettingOut]:
    """List the current user's per-kind settings joined with the kind catalogue."""
    rows = (
        await db.execute(
            select(NotificationSetting, NotificationKindDefault)
            .join(
                NotificationKindDefault,
                NotificationKindDefault.kind == NotificationSetting.kind,
            )
            .where(NotificationSetting.user_id == current_user.id)
            .order_by(NotificationKindDefault.kind.asc())
        )
    ).all()
    return [
        NotificationSettingOut(
            kind=ns.kind,
            severity=kd.severity,
            scope=kd.scope,
            enabled=ns.enabled,
            thresholds=dict(ns.thresholds or {}),
            description=kd.description,
        )
        for ns, kd in rows
    ]


@router.patch("/settings/{kind}", response_model=NotificationSettingOut)
async def patch_my_setting(
    kind: str,
    payload: PatchNotificationSettingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingOut:
    """Update one of the current user's notification settings."""
    kind_row = await db.get(NotificationKindDefault, kind)
    if kind_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown notification kind")

    setting = (
        await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.user_id == current_user.id,
                NotificationSetting.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if setting is None:
        # Defensive: the migration backfills one row per user/kind, and the
        # admin endpoint inserts on user creation. If we still hit this, the
        # account is in a partial state — surface it rather than silently
        # creating the row, which would mask the deeper inconsistency.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "notification setting missing for this kind",
        )

    if payload.enabled is not None:
        setting.enabled = payload.enabled
    if payload.thresholds is not None:
        setting.thresholds = validate_thresholds(
            kind, payload.thresholds, set(kind_row.thresholds or {})
        )
    setting.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(setting)

    return NotificationSettingOut(
        kind=setting.kind,
        severity=kind_row.severity,
        scope=kind_row.scope,
        enabled=setting.enabled,
        thresholds=dict(setting.thresholds or {}),
        description=kind_row.description,
    )


# ---------------------------------------------------------------------------
# Notifications list & state changes
# ---------------------------------------------------------------------------


# Static routes registered BEFORE the dynamic /{notification_id}/read route
# so FastAPI doesn't try to coerce "mark-all-read" or "unread-count" through
# the int converter.


@router.post("/mark-all-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Mark every unread notification for the current user as read."""
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Cheap unread-count query — driven by the partial index."""
    count = (
        await db.execute(
            select(sa.func.count(Notification.id)).where(
                Notification.user_id == current_user.id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    return {"count": int(count)}


@router.get("", response_model=NotificationListOut)
async def list_my_notifications(
    status_filter: Literal["active", "all", "resolved"] = Query(
        default="all", alias="status"
    ),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListOut:
    base = select(Notification).where(Notification.user_id == current_user.id)
    if status_filter == "active":
        base = base.where(Notification.resolved_at.is_(None))
    elif status_filter == "resolved":
        base = base.where(Notification.resolved_at.is_not(None))
    if kind is not None:
        base = base.where(Notification.kind == kind)

    rows = (
        (await db.execute(base.order_by(Notification.opened_at.desc()).limit(limit)))
        .scalars()
        .all()
    )

    # Three count queries — all cheap because of the partial indexes.
    total = (
        await db.execute(
            select(sa.func.count(Notification.id)).where(
                Notification.user_id == current_user.id
            )
        )
    ).scalar_one()
    unread = (
        await db.execute(
            select(sa.func.count(Notification.id)).where(
                Notification.user_id == current_user.id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    active = (
        await db.execute(
            select(sa.func.count(Notification.id)).where(
                Notification.user_id == current_user.id,
                Notification.resolved_at.is_(None),
            )
        )
    ).scalar_one()

    return NotificationListOut(
        notifications=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                severity=n.severity,
                scope=n.scope,
                gateway_id=n.gateway_id,
                controller_id=n.controller_id,
                node_id=n.node_id,
                subject_name=n.subject_name,
                details=dict(n.details or {}),
                opened_at=n.opened_at,
                resolved_at=n.resolved_at,
                read_at=n.read_at,
                summary=build_summary(n.kind, n.subject_name, n.details),
            )
            for n in rows
        ],
        total=int(total),
        unread=int(unread),
        active=int(active),
    )


@router.post(
    "/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT
)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Mark a single notification read. Idempotent — already-read is a no-op."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        # Either it doesn't exist, isn't ours, or was already read. The
        # first two are 404s; the third is a no-op. We don't differentiate
        # — the client just refetches.
        already_exists = (
            await db.execute(
                select(Notification.id).where(
                    Notification.id == notification_id,
                    Notification.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if already_exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
