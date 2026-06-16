"""Admin endpoints — user, gateway, controller, node management.

Mirrors the user-facing ``/controllers/*`` shapes for gateway-scoped
reads (latest/readings/telemetry) but without the ownership filter, and
adds the management endpoints (create/patch/delete + pending-controller
accept/reject + MQTT password generation).

MQTT credentials are still never persisted server-side. The
create-gateway and rotate endpoints generate a one-shot password,
return it in the response, and forget it. The admin runs the printed
``ssh_command`` on the VPS to register it with Mosquitto and flips
``mqtt_provisioned`` via PATCH /admin/gateways/{id}.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    INVITATION_TOKEN_TTL,
    PASSWORD_RESET_TOKEN_TTL,
    generate_token,
    get_current_admin,
)
from ..config import get_settings
from ..db import get_db
from ..models import (
    AuthToken,
    Controller,
    Gateway,
    Node,
    Notification,
    NotificationKindDefault,
    NotificationSetting,
    PendingController,
    User,
)
from ..models import Session as UserSession
from ..notification_messages import build_summary
from ..notification_validation import validate_thresholds
from ..schemas import (
    AcceptPendingControllerIn,
    AdminNotificationListOut,
    AdminNotificationOut,
    ControllerDetailOut,
    ControllerForGatewayOut,
    CreateGatewayIn,
    CreateGatewayOut,
    CreateUserIn,
    CreateUserOut,
    GatewayAdminOut,
    GatewayDetailAdminOut,
    GatewayForUserOut,
    InvitationLinkOut,
    NotificationKindDefaultOut,
    NotificationOut,
    NotificationSettingOut,
    OwnerOut,
    PatchControllerIn,
    PatchGatewayIn,
    PatchKindDefaultIn,
    PatchNodeIn,
    PatchNotificationSettingIn,
    PendingControllerOut,
    ReadingsPointOut,
    ResetLinkOut,
    RotateMqttOut,
    TelemetryPointOut,
    TestNotificationIn,
    UserAdminDetailOut,
    UserAdminOut,
    UserBrief,
)
from .controllers import (
    _build_controller_detail,
    _fetch_controller_readings,
    _fetch_controller_telemetry,
)

log = logging.getLogger("admin")

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

_DEVICE_KEY_RE = re.compile(r"^[a-z0-9_-]+$")
_ONLINE_WINDOW = timedelta(minutes=5)


# ===========================================================================
# Shape helpers
# ===========================================================================


def _user_admin_out(user: User, gateway_count: int) -> UserAdminOut:
    return UserAdminOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        has_password=user.password_hash is not None,
        gateway_count=gateway_count,
    )


def _owner_out(user: User) -> OwnerOut:
    return OwnerOut(id=user.id, email=user.email, display_name=user.display_name)


def _gateway_admin_out(
    gateway: Gateway, owner: User, controller_count: int
) -> GatewayAdminOut:
    return GatewayAdminOut(
        id=gateway.id,
        device_key=gateway.device_key,
        name=gateway.name,
        location=gateway.location,
        mqtt_provisioned=gateway.mqtt_provisioned,
        created_at=gateway.created_at,
        last_seen_at=gateway.last_seen_at,
        owner=_owner_out(owner),
        controller_count=controller_count,
    )


async def _controller_count_for_gateway(
    db: AsyncSession, gateway_id: int
) -> int:
    return (
        await db.execute(
            select(sa.func.count(Controller.id)).where(
                Controller.gateway_id == gateway_id
            )
        )
    ).scalar_one()


async def _gateway_count_for_user(db: AsyncSession, user_id: int) -> int:
    return (
        await db.execute(
            select(sa.func.count(Gateway.id)).where(Gateway.user_id == user_id)
        )
    ).scalar_one()


# ===========================================================================
# MQTT helpers
# ===========================================================================


def _generate_mqtt_password() -> str:
    """24-char URL-safe password (18 random bytes → base64url)."""
    return secrets.token_urlsafe(18)


def _build_ssh_command(device_key: str, password: str) -> str:
    """SSH one-liner the admin runs on the VPS to register the password."""
    resource = get_settings().MOSQUITTO_RESOURCE_NAME
    return (
        f'docker exec $(docker ps --filter "label=coolify.resourceName={resource}" -q) '
        f"sh /mosquitto/config/scripts/add_device.sh {device_key} {password}"
    )


# ===========================================================================
# USERS
# ===========================================================================


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserAdminOut]:
    users = (
        (await db.execute(select(User).order_by(User.created_at.desc())))
        .scalars()
        .all()
    )
    out: list[UserAdminOut] = []
    for user in users:
        gw_count = await _gateway_count_for_user(db, user.id)
        out.append(_user_admin_out(user, gw_count))
    return out


@router.post(
    "/users", response_model=CreateUserOut, status_code=status.HTTP_201_CREATED
)
async def create_user(
    payload: CreateUserIn, db: AsyncSession = Depends(get_db)
) -> CreateUserOut:
    settings = get_settings()
    email = payload.email.strip().lower()

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already exists")

    user = User(
        email=email,
        display_name=payload.display_name,
        is_active=True,
        is_admin=False,
        password_hash=None,
    )
    db.add(user)
    await db.flush()

    raw, token_hash_value = generate_token()
    db.add(
        AuthToken(
            user_id=user.id,
            kind="invitation",
            token_hash=token_hash_value,
            expires_at=datetime.now(UTC) + INVITATION_TOKEN_TTL,
        )
    )

    # Auto-provision the user's notification settings from the global
    # defaults. Round 4 backfill seeded existing users; this keeps newly
    # created users in the same shape.
    await db.execute(
        sa.text(
            """
            INSERT INTO notification_settings (user_id, kind, enabled, thresholds)
            SELECT :uid, d.kind, d.enabled_default, d.thresholds
            FROM notification_kind_defaults d
            """
        ),
        {"uid": user.id},
    )

    await db.commit()
    await db.refresh(user)

    invitation_url = (
        f"{settings.FRONTEND_ORIGIN}/set-password?token={raw}&mode=invitation"
    )
    log.info("admin created user id=%s email=%s; invitation issued", user.id, email)
    return CreateUserOut(
        user=_user_admin_out(user, gateway_count=0),
        invitation_url=invitation_url,
    )


@router.get("/users/{user_id}", response_model=UserAdminDetailOut)
async def get_user(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> UserAdminDetailOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    gateway_rows = (
        await db.execute(
            select(
                Gateway,
                sa.func.coalesce(sa.func.count(Controller.id), 0).label("ccnt"),
            )
            .outerjoin(Controller, Controller.gateway_id == Gateway.id)
            .where(Gateway.user_id == user_id)
            .group_by(Gateway.id)
            .order_by(Gateway.created_at.desc())
        )
    ).all()

    gateways_out = [
        GatewayForUserOut(
            id=g.id,
            device_key=g.device_key,
            name=g.name,
            location=g.location,
            mqtt_provisioned=g.mqtt_provisioned,
            created_at=g.created_at,
            last_seen_at=g.last_seen_at,
            controller_count=ccnt,
        )
        for g, ccnt in gateway_rows
    ]

    return UserAdminDetailOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        has_password=user.password_hash is not None,
        gateway_count=len(gateways_out),
        gateways=gateways_out,
    )


@router.post("/users/{user_id}/resend-invitation", response_model=InvitationLinkOut)
async def resend_invitation(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> InvitationLinkOut:
    settings = get_settings()
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.password_hash is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "user already has a password; use the reset-link flow",
        )

    raw, token_hash_value = generate_token()
    db.add(
        AuthToken(
            user_id=user.id,
            kind="invitation",
            token_hash=token_hash_value,
            expires_at=datetime.now(UTC) + INVITATION_TOKEN_TTL,
        )
    )
    await db.commit()
    invitation_url = (
        f"{settings.FRONTEND_ORIGIN}/set-password?token={raw}&mode=invitation"
    )
    log.info("admin re-issued invitation for user id=%s", user.id)
    return InvitationLinkOut(invitation_url=invitation_url)


@router.post("/users/{user_id}/reset-link", response_model=ResetLinkOut)
async def issue_reset_link(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> ResetLinkOut:
    settings = get_settings()
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.password_hash is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "user has not set a password yet; use the invitation flow",
        )

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
    reset_url = f"{settings.FRONTEND_ORIGIN}/set-password?token={raw}&mode=reset"
    log.info("admin issued reset link for user id=%s", user.id)
    return ResetLinkOut(reset_url=reset_url)


@router.post("/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if user_id == current_admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot deactivate yourself")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await db.execute(update(User).where(User.id == user_id).values(is_active=False))
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await db.commit()
    log.info("admin deactivated user id=%s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_user(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await db.execute(update(User).where(User.id == user_id).values(is_active=True))
    await db.commit()
    log.info("admin reactivated user id=%s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if user_id == current_admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete yourself")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await db.delete(user)
    await db.commit()
    log.info("admin deleted user id=%s email=%s", user_id, user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# GATEWAYS
# ===========================================================================


@router.get("/gateways", response_model=list[GatewayAdminOut])
async def list_gateways(
    q: str | None = Query(default=None),
    gateway_status: Literal["online", "offline"] | None = Query(
        default=None, alias="status"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[GatewayAdminOut]:
    stmt = (
        select(
            Gateway,
            User,
            sa.func.coalesce(sa.func.count(Controller.id), 0).label("ccnt"),
        )
        .join(User, Gateway.user_id == User.id)
        .outerjoin(Controller, Controller.gateway_id == Gateway.id)
        .group_by(Gateway.id, User.id)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Gateway.device_key.ilike(pattern),
                Gateway.name.ilike(pattern),
                Gateway.location.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if gateway_status is not None:
        threshold = datetime.now(UTC) - _ONLINE_WINDOW
        if gateway_status == "online":
            stmt = stmt.where(Gateway.last_seen_at >= threshold)
        else:
            stmt = stmt.where(
                or_(Gateway.last_seen_at < threshold, Gateway.last_seen_at.is_(None))
            )
    stmt = stmt.order_by(
        Gateway.last_seen_at.desc().nullslast(),
        Gateway.created_at.desc(),
    )
    rows = (await db.execute(stmt)).all()
    return [_gateway_admin_out(g, u, ccnt) for g, u, ccnt in rows]


@router.get("/gateways/{gateway_id}", response_model=GatewayDetailAdminOut)
async def get_gateway(
    gateway_id: int, db: AsyncSession = Depends(get_db)
) -> GatewayDetailAdminOut:
    row = (
        await db.execute(
            select(Gateway, User)
            .join(User, Gateway.user_id == User.id)
            .where(Gateway.id == gateway_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "gateway not found")
    gateway, owner = row

    controllers_rows = (
        await db.execute(
            select(
                Controller,
                sa.func.coalesce(sa.func.count(Node.id), 0).label("ncnt"),
            )
            .outerjoin(Node, Node.controller_id == Controller.id)
            .where(Controller.gateway_id == gateway_id)
            .group_by(Controller.id)
            .order_by(Controller.created_at.desc())
        )
    ).all()
    controllers_out = [
        ControllerForGatewayOut(
            id=c.id,
            sn=c.sn,
            name=c.name,
            location=c.location,
            created_at=c.created_at,
            last_seen_at=c.last_seen_at,
            node_count=ncnt,
        )
        for c, ncnt in controllers_rows
    ]

    pending = (
        (
            await db.execute(
                select(PendingController)
                .where(PendingController.gateway_id == gateway_id)
                .order_by(PendingController.first_seen_at.desc())
            )
        )
        .scalars()
        .all()
    )
    pending_out = [
        PendingControllerOut(
            id=p.id,
            sn=p.sn,
            first_seen_at=p.first_seen_at,
            last_seen_at=p.last_seen_at,
            message_count=p.message_count,
        )
        for p in pending
    ]

    return GatewayDetailAdminOut(
        id=gateway.id,
        device_key=gateway.device_key,
        name=gateway.name,
        location=gateway.location,
        mqtt_provisioned=gateway.mqtt_provisioned,
        created_at=gateway.created_at,
        last_seen_at=gateway.last_seen_at,
        owner=_owner_out(owner),
        controller_count=len(controllers_out),
        controllers=controllers_out,
        pending_controllers=pending_out,
    )


@router.post(
    "/gateways", response_model=CreateGatewayOut, status_code=status.HTTP_201_CREATED
)
async def create_gateway(
    payload: CreateGatewayIn, db: AsyncSession = Depends(get_db)
) -> CreateGatewayOut:
    if not _DEVICE_KEY_RE.fullmatch(payload.device_key):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "device_key must match ^[a-z0-9_-]+$",
        )
    owner = await db.get(User, payload.user_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    existing = (
        await db.execute(
            select(Gateway).where(Gateway.device_key == payload.device_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "device_key already exists")

    gateway = Gateway(
        user_id=payload.user_id,
        device_key=payload.device_key,
        name=payload.name,
        location=payload.location,
        mqtt_provisioned=False,
    )
    db.add(gateway)
    await db.commit()
    await db.refresh(gateway)

    password = _generate_mqtt_password()
    ssh_command = _build_ssh_command(payload.device_key, password)
    log.info(
        "admin created gateway id=%s key=%s owner=%s; mqtt password=<redacted>",
        gateway.id,
        gateway.device_key,
        owner.id,
    )
    return CreateGatewayOut(
        gateway=_gateway_admin_out(gateway, owner, controller_count=0),
        mqtt_password=password,
        ssh_command=ssh_command,
    )


@router.patch("/gateways/{gateway_id}", response_model=GatewayAdminOut)
async def patch_gateway(
    gateway_id: int,
    payload: PatchGatewayIn,
    db: AsyncSession = Depends(get_db),
) -> GatewayAdminOut:
    gateway = await db.get(Gateway, gateway_id)
    if gateway is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "gateway not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        gateway.name = updates["name"]
    if "location" in updates:
        gateway.location = updates["location"]
    if "mqtt_provisioned" in updates and updates["mqtt_provisioned"] is not None:
        gateway.mqtt_provisioned = updates["mqtt_provisioned"]
    if "user_id" in updates and updates["user_id"] is not None:
        new_owner = await db.get(User, updates["user_id"])
        if new_owner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user_id not found")
        gateway.user_id = updates["user_id"]

    await db.commit()
    await db.refresh(gateway)

    owner = await db.get(User, gateway.user_id)
    assert owner is not None
    ccnt = await _controller_count_for_gateway(db, gateway.id)
    log.info(
        "admin patched gateway id=%s fields=%s", gateway_id, sorted(updates.keys())
    )
    return _gateway_admin_out(gateway, owner, ccnt)


@router.post(
    "/gateways/{gateway_id}/rotate-mqtt-password", response_model=RotateMqttOut
)
async def rotate_mqtt_password(
    gateway_id: int, db: AsyncSession = Depends(get_db)
) -> RotateMqttOut:
    gateway = await db.get(Gateway, gateway_id)
    if gateway is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "gateway not found")

    password = _generate_mqtt_password()
    gateway.mqtt_provisioned = False
    await db.commit()

    ssh_command = _build_ssh_command(gateway.device_key, password)
    log.info(
        "admin rotated MQTT password for gateway id=%s key=%s; password=<redacted>",
        gateway.id,
        gateway.device_key,
    )
    return RotateMqttOut(mqtt_password=password, ssh_command=ssh_command)


@router.delete("/gateways/{gateway_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gateway(
    gateway_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    gateway = await db.get(Gateway, gateway_id)
    if gateway is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "gateway not found")
    # Cascade drops controllers → nodes → node_readings, plus pending_controllers
    # and controller_telemetry chains.
    await db.delete(gateway)
    await db.commit()
    log.info("admin deleted gateway id=%s key=%s", gateway_id, gateway.device_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# PENDING CONTROLLERS
# ===========================================================================


@router.post(
    "/pending-controllers/{pending_id}/accept",
    response_model=ControllerForGatewayOut,
    status_code=status.HTTP_201_CREATED,
)
async def accept_pending_controller(
    pending_id: int,
    payload: AcceptPendingControllerIn,
    db: AsyncSession = Depends(get_db),
) -> ControllerForGatewayOut:
    pending = await db.get(PendingController, pending_id)
    if pending is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "pending controller not found"
        )

    # Race-condition guard: it's possible an admin previously accepted a
    # controller with this (gateway_id, sn). Reject the duplicate.
    existing = (
        await db.execute(
            select(Controller).where(
                Controller.gateway_id == pending.gateway_id,
                Controller.sn == pending.sn,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "controller with this (gateway, sn) already exists",
        )

    controller = Controller(
        gateway_id=pending.gateway_id,
        sn=pending.sn,
        name=payload.name,
        location=payload.location,
    )
    db.add(controller)
    await db.flush()
    await db.delete(pending)
    await db.commit()
    await db.refresh(controller)

    log.info(
        "admin accepted pending controller id=%s sn=%s gateway=%s as controller id=%s",
        pending_id,
        pending.sn,
        pending.gateway_id,
        controller.id,
    )
    return ControllerForGatewayOut(
        id=controller.id,
        sn=controller.sn,
        name=controller.name,
        location=controller.location,
        created_at=controller.created_at,
        last_seen_at=controller.last_seen_at,
        node_count=0,
    )


@router.post(
    "/pending-controllers/{pending_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reject_pending_controller(
    pending_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    pending = await db.get(PendingController, pending_id)
    if pending is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "pending controller not found"
        )
    await db.delete(pending)
    await db.commit()
    log.info(
        "admin rejected pending controller id=%s sn=%s gateway=%s",
        pending_id,
        pending.sn,
        pending.gateway_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# CONTROLLERS (admin)
# ===========================================================================


@router.get("/controllers/{controller_id}", response_model=ControllerDetailOut)
async def admin_get_controller(
    controller_id: int, db: AsyncSession = Depends(get_db)
) -> ControllerDetailOut:
    return await _build_controller_detail(db, controller_id)


@router.patch("/controllers/{controller_id}", response_model=ControllerDetailOut)
async def patch_controller(
    controller_id: int,
    payload: PatchControllerIn,
    db: AsyncSession = Depends(get_db),
) -> ControllerDetailOut:
    controller = await db.get(Controller, controller_id)
    if controller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        controller.name = updates["name"]
    if "location" in updates:
        controller.location = updates["location"]

    await db.commit()
    log.info(
        "admin patched controller id=%s fields=%s",
        controller_id,
        sorted(updates.keys()),
    )
    return await _build_controller_detail(db, controller_id)


@router.delete(
    "/controllers/{controller_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_controller(
    controller_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    controller = await db.get(Controller, controller_id)
    if controller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    await db.delete(controller)
    await db.commit()
    log.info("admin deleted controller id=%s sn=%s", controller_id, controller.sn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/controllers/{controller_id}/readings",
    response_model=list[ReadingsPointOut],
)
async def admin_get_controller_readings(
    controller_id: int,
    from_: datetime = Query(..., alias="from"),
    to: datetime | None = Query(default=None),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
) -> list[ReadingsPointOut]:
    # Existence check via _build_controller_detail's first SELECT would
    # be heavier than needed; a cheap db.get suffices.
    controller = await db.get(Controller, controller_id)
    if controller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    return await _fetch_controller_readings(
        db, controller_id, from_, to or datetime.now(UTC), bucket, limit
    )


@router.get(
    "/controllers/{controller_id}/telemetry",
    response_model=list[TelemetryPointOut],
)
async def admin_get_controller_telemetry(
    controller_id: int,
    from_: datetime = Query(..., alias="from"),
    to: datetime | None = Query(default=None),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
) -> list[TelemetryPointOut]:
    controller = await db.get(Controller, controller_id)
    if controller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    return await _fetch_controller_telemetry(
        db, controller_id, from_, to or datetime.now(UTC), bucket, limit
    )


# ===========================================================================
# NODES (admin)
# ===========================================================================


@router.patch("/nodes/{node_id}", status_code=status.HTTP_200_OK)
async def patch_node(
    node_id: int,
    payload: PatchNodeIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update node ``name`` and/or ``has_lux``.

    Per the design decision: flipping ``has_lux`` from True to False does
    NOT bulk-update existing rows — only NEW readings discard lux.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        # Nullable: explicit None clears the name.
        node.name = updates["name"]
    if "has_lux" in updates and updates["has_lux"] is not None:
        node.has_lux = updates["has_lux"]

    await db.commit()
    await db.refresh(node)
    log.info("admin patched node id=%s fields=%s", node_id, sorted(updates.keys()))
    return {
        "id": node.id,
        "node_index": node.node_index,
        "name": node.name,
        "has_lux": node.has_lux,
        "last_seen_at": (
            node.last_seen_at.isoformat() if node.last_seen_at is not None else None
        ),
    }


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    await db.delete(node)
    await db.commit()
    log.info(
        "admin deleted node id=%s controller=%s", node_id, node.controller_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# NOTIFICATIONS — global defaults + cross-user log
# ===========================================================================


@router.get(
    "/notification-defaults", response_model=list[NotificationKindDefaultOut]
)
async def list_kind_defaults(
    db: AsyncSession = Depends(get_db),
) -> list[NotificationKindDefaultOut]:
    rows = (
        (
            await db.execute(
                select(NotificationKindDefault).order_by(
                    NotificationKindDefault.kind.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        NotificationKindDefaultOut(
            kind=r.kind,
            severity=r.severity,
            scope=r.scope,
            enabled_default=r.enabled_default,
            thresholds=dict(r.thresholds or {}),
            description=r.description,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.patch(
    "/notification-defaults/{kind}", response_model=NotificationKindDefaultOut
)
async def patch_kind_default(
    kind: str,
    payload: PatchKindDefaultIn,
    db: AsyncSession = Depends(get_db),
) -> NotificationKindDefaultOut:
    """Update the global defaults for one kind.

    Note: this does NOT cascade to existing users' notification_settings rows
    — they keep their customised values. New users (and existing users that
    haven't customised a particular kind) get the new defaults next time
    they're provisioned.
    """
    row = await db.get(NotificationKindDefault, kind)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown notification kind")

    if payload.enabled_default is not None:
        row.enabled_default = payload.enabled_default
    if payload.thresholds is not None:
        row.thresholds = validate_thresholds(
            kind, payload.thresholds, set(row.thresholds or {})
        )
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    log.info("admin updated notification defaults kind=%s", kind)
    return NotificationKindDefaultOut(
        kind=row.kind,
        severity=row.severity,
        scope=row.scope,
        enabled_default=row.enabled_default,
        thresholds=dict(row.thresholds or {}),
        description=row.description,
        updated_at=row.updated_at,
    )


@router.get("/notifications", response_model=AdminNotificationListOut)
async def admin_list_notifications(
    user_id: int | None = Query(default=None),
    user_email: str | None = Query(default=None),
    status_filter: Literal["active", "all", "resolved"] = Query(
        default="all", alias="status"
    ),
    kind: str | None = Query(default=None),
    severity: Literal["critical", "alert"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AdminNotificationListOut:
    """Cross-user notification log with pagination.

    All filters are AND-combined. ``user_email`` is an ILIKE substring
    search (so ``"@acme.com"`` matches any user at that domain).
    ``total`` in the response counts rows matching the filter, not the
    page size.
    """
    # Escape SQL LIKE wildcards so admins typing literal '_' / '%' in an
    # email get a literal substring search rather than a regex surprise.
    email_pattern: str | None = None
    if user_email:
        escaped = user_email.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        email_pattern = f"%{escaped}%"

    base = select(Notification).join(User, User.id == Notification.user_id)
    if user_id is not None:
        base = base.where(Notification.user_id == user_id)
    if email_pattern is not None:
        base = base.where(User.email.ilike(email_pattern, escape="\\"))
    if status_filter == "active":
        base = base.where(Notification.resolved_at.is_(None))
    elif status_filter == "resolved":
        base = base.where(Notification.resolved_at.is_not(None))
    if kind is not None:
        base = base.where(Notification.kind == kind)
    if severity is not None:
        base = base.where(Notification.severity == severity)

    count_stmt = select(sa.func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    page_stmt = (
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .order_by(Notification.opened_at.desc())
        .offset(offset)
        .limit(limit)
    )
    # Re-apply the same WHERE filters on the joined query so we don't have
    # to re-derive them from the subquery (which would require row-by-row
    # IN lookups).
    if user_id is not None:
        page_stmt = page_stmt.where(Notification.user_id == user_id)
    if email_pattern is not None:
        page_stmt = page_stmt.where(User.email.ilike(email_pattern, escape="\\"))
    if status_filter == "active":
        page_stmt = page_stmt.where(Notification.resolved_at.is_(None))
    elif status_filter == "resolved":
        page_stmt = page_stmt.where(Notification.resolved_at.is_not(None))
    if kind is not None:
        page_stmt = page_stmt.where(Notification.kind == kind)
    if severity is not None:
        page_stmt = page_stmt.where(Notification.severity == severity)

    rows = (await db.execute(page_stmt)).all()
    notifications = [
        AdminNotificationOut(
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
            user=UserBrief(id=u.id, email=u.email, display_name=u.display_name),
        )
        for n, u in rows
    ]
    return AdminNotificationListOut(
        notifications=notifications, total=int(total)
    )


# ---------------------------------------------------------------------------
# Admin-on-behalf: per-user notification settings + test-fire
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user_id}/notification-settings",
    response_model=list[NotificationSettingOut],
)
async def admin_get_user_settings(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[NotificationSettingOut]:
    """List one user's per-kind settings — same shape as /me equivalent."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    rows = (
        await db.execute(
            select(NotificationSetting, NotificationKindDefault)
            .join(
                NotificationKindDefault,
                NotificationKindDefault.kind == NotificationSetting.kind,
            )
            .where(NotificationSetting.user_id == user_id)
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


@router.patch(
    "/users/{user_id}/notification-settings/{kind}",
    response_model=NotificationSettingOut,
)
async def admin_patch_user_setting(
    user_id: int,
    kind: str,
    payload: PatchNotificationSettingIn,
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingOut:
    """Edit a user's per-kind setting on their behalf. Same validation as
    the /me/notifications endpoint — paired-threshold rules and key
    whitelist are reused via :func:`validate_thresholds`."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    kind_row = await db.get(NotificationKindDefault, kind)
    if kind_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown notification kind")

    setting = (
        await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.user_id == user_id,
                NotificationSetting.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if setting is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "notification setting missing for this user/kind",
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
    log.info(
        "admin patched user notification setting user=%s kind=%s", user_id, kind
    )
    return NotificationSettingOut(
        kind=setting.kind,
        severity=kind_row.severity,
        scope=kind_row.scope,
        enabled=setting.enabled,
        thresholds=dict(setting.thresholds or {}),
        description=kind_row.description,
    )


async def _pick_test_entity(
    db: AsyncSession, user_id: int, scope: str
) -> tuple[int | None, int | None, int | None, str | None]:
    """Pick a representative entity for a test notification.

    Selection: lowest-id row of the appropriate type owned by the user
    (chosen for deterministic, reproducible test fires). Returns
    ``(gateway_id, controller_id, node_id, subject_name)`` with the
    higher-level FKs always populated for consistency with how the
    detector writes them. ``subject_name`` carries the " [TEST]" suffix
    so the UI can render it as obviously synthetic.
    """
    if scope == "gateway":
        row = (
            await db.execute(
                select(Gateway)
                .where(Gateway.user_id == user_id)
                .order_by(Gateway.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None, None, None, None
        return row.id, None, None, f"{row.name} [TEST]"

    if scope == "controller":
        row = (
            await db.execute(
                select(Controller, Gateway)
                .join(Gateway, Gateway.id == Controller.gateway_id)
                .where(Gateway.user_id == user_id)
                .order_by(Controller.id.asc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None, None, None, None
        c, g = row
        return g.id, c.id, None, f"{c.name} [TEST]"

    if scope == "node":
        row = (
            await db.execute(
                select(Node, Controller, Gateway)
                .join(Controller, Controller.id == Node.controller_id)
                .join(Gateway, Gateway.id == Controller.gateway_id)
                .where(Gateway.user_id == user_id)
                .order_by(Node.id.asc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None, None, None, None
        n, c, g = row
        return g.id, c.id, n.id, f"{c.name} - Node {n.node_index} [TEST]"

    return None, None, None, None


def _build_test_details(
    kind: str,
    thresholds: dict[str, float],
    now: datetime,
    node_index: int | None,
    sibling_controller_ids: list[int],
) -> dict[str, object]:
    """Per-kind 'believable' detail payload for a test notification.

    Every kind gets ``is_test=True`` and the kind's threshold values so
    the summary template renders meaningfully. Observation values are
    seeded just past the trip threshold so the summary reads like a real
    firing condition. Nothing here is wired into the detector — the row
    is inserted directly.
    """
    base: dict[str, object] = {"is_test": True, **(thresholds or {})}

    if kind == "temp_safe":
        safe_max = float(thresholds.get("safe_max", 6.0))
        safe_min = float(thresholds.get("safe_min", 2.0))
        return {
            **base,
            "observed": round(safe_max + 1.5, 2),
            "threshold_min": safe_min,
            "threshold_max": safe_max,
            "direction": "above",
        }
    if kind == "temp_preferred":
        pref_max = float(thresholds.get("preferred_max", 5.0))
        pref_min = float(thresholds.get("preferred_min", 3.0))
        return {
            **base,
            "observed": round(pref_max + 0.7, 2),
            "threshold_min": pref_min,
            "threshold_max": pref_max,
            "direction": "above",
        }
    if kind == "temp_drift":
        window = int(thresholds.get("drift_minutes", 10))
        drift = float(thresholds.get("drift_c", 3.0))
        return {
            **base,
            "current": 8.0,
            "previous": 8.0 - (drift + 0.5),
            "delta": round(drift + 0.5, 2),
            "delta_c": round(drift + 0.5, 2),
            "window_minutes": window,
            "drift_minutes": window,
        }
    if kind == "door_open":
        threshold = int(thresholds.get("max_open_minutes", 5))
        open_since = (now - timedelta(minutes=threshold + 2)).isoformat()
        return {
            **base,
            "open_since": open_since,
            "open_minutes": threshold + 2,
            "threshold_minutes": threshold,
        }
    if kind in ("controller_offline", "gateway_offline"):
        threshold = int(thresholds.get("offline_minutes", 5))
        last_seen = (now - timedelta(minutes=threshold + 5)).isoformat()
        return {
            **base,
            "last_seen_at": last_seen,
            "offline_minutes": threshold,
        }
    if kind == "multi_controller_offline":
        return {
            **base,
            "offline_controller_count": max(2, len(sibling_controller_ids)),
            "offline_controller_ids": sibling_controller_ids,
        }
    if kind == "battery_critical":
        crit = int(thresholds.get("critical_pct", 10))
        return {**base, "observed_pct": max(0, crit - 2), "threshold_pct": crit}
    if kind == "battery_low":
        low = int(thresholds.get("low_pct", 25))
        return {**base, "observed_pct": max(0, low - 3), "threshold_pct": low}
    if kind == "node_error_single":
        return {
            **base,
            "err": "sensor_temp",
            "err_label": "Temp sensor",
            "node_index": node_index if node_index is not None else 1,
        }
    if kind == "node_error_cumulative":
        return {**base, "erroring_nodes": [], "error_count": 2}
    return base


@router.post(
    "/users/{user_id}/notifications/test",
    response_model=NotificationOut,
    status_code=status.HTTP_201_CREATED,
)
async def admin_fire_test_notification(
    user_id: int,
    payload: TestNotificationIn,
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    """Insert a synthetic notification of ``payload.kind`` for ``user_id``.

    The notification appears in the user's normal feed (mark-read /
    dismiss work as usual). It carries ``details.is_test = True`` and a
    ``[TEST]`` suffix in ``subject_name`` so the UI can render a
    distinguishing badge.

    Returns 400 if the user has no entity of the required scope (no
    gateways for gateway-scoped kinds, no controllers for
    controller-scoped, no nodes for node-scoped).
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    kind_row = await db.get(NotificationKindDefault, payload.kind)
    if kind_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown notification kind")

    gateway_id, controller_id, node_id, subject_name = await _pick_test_entity(
        db, user_id, kind_row.scope
    )
    if subject_name is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"user has no {kind_row.scope} to attach a test notification to",
        )

    # Look up the lowest few sibling controller ids on the chosen gateway —
    # used to populate believable ids for multi_controller_offline tests.
    sibling_ids: list[int] = []
    if gateway_id is not None:
        sibling_ids = list(
            (
                await db.execute(
                    select(Controller.id)
                    .where(Controller.gateway_id == gateway_id)
                    .order_by(Controller.id.asc())
                    .limit(3)
                )
            ).scalars().all()
        )

    # For node_error_single the subject's node_index belongs in details so
    # the summary template can substitute it.
    node_index_for_details: int | None = None
    if node_id is not None:
        node_index_for_details = (
            await db.execute(
                select(Node.node_index).where(Node.id == node_id)
            )
        ).scalar_one_or_none()

    now = datetime.now(UTC)
    details = _build_test_details(
        payload.kind,
        dict(kind_row.thresholds or {}),
        now,
        node_index_for_details,
        sibling_ids,
    )

    row = Notification(
        user_id=user_id,
        kind=payload.kind,
        severity=kind_row.severity,
        scope=kind_row.scope,
        gateway_id=gateway_id,
        controller_id=controller_id,
        node_id=node_id,
        subject_name=subject_name,
        details=details,
        opened_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    log.info(
        "admin fired test notification kind=%s user=%s id=%s subject=%s",
        payload.kind,
        user_id,
        row.id,
        subject_name,
    )
    return NotificationOut(
        id=row.id,
        kind=row.kind,
        severity=row.severity,
        scope=row.scope,
        gateway_id=row.gateway_id,
        controller_id=row.controller_id,
        node_id=row.node_id,
        subject_name=row.subject_name,
        details=dict(row.details or {}),
        opened_at=row.opened_at,
        resolved_at=row.resolved_at,
        read_at=row.read_at,
        summary=build_summary(row.kind, row.subject_name, row.details),
    )
