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
    PendingController,
    User,
)
from ..models import Session as UserSession
from ..schemas import (
    AcceptPendingControllerIn,
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
    OwnerOut,
    PatchControllerIn,
    PatchGatewayIn,
    PatchNodeIn,
    PendingControllerOut,
    ReadingsPointOut,
    ResetLinkOut,
    RotateMqttOut,
    TelemetryPointOut,
    UserAdminDetailOut,
    UserAdminOut,
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
