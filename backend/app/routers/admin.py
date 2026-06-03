"""Admin endpoints — user + device management, MQTT provisioning workflow.

All endpoints are gated by router-level ``Depends(get_current_admin)``; the
admin check applies uniformly so handlers don't repeat it. Endpoints that
need the calling admin's identity (e.g. for self-action refusal) inject
``current_admin`` as a parameter — FastAPI caches the dependency so it
runs once per request regardless.

**MQTT credentials are never persisted server-side.** The create-device and
rotate-mqtt-password endpoints generate a one-shot password, return it in
the response, and forget it. The admin then runs the printed ``ssh_command``
on the VPS to register the password with Mosquitto, and flips
``mqtt_provisioned`` via PATCH /admin/devices/{id} as their own
bookkeeping. The source of truth is the Mosquitto password file.
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
from ..models import AuthToken, Device, User
from ..models import Session as UserSession
from ..schemas import (
    CreateDeviceIn,
    CreateDeviceOut,
    CreateUserIn,
    CreateUserOut,
    DeviceAdminOut,
    DeviceForUserOut,
    OwnerOut,
    PatchDeviceIn,
    ResetLinkOut,
    RotateMqttOut,
    UserAdminDetailOut,
    UserAdminOut,
)

log = logging.getLogger("admin")

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

_DEVICE_KEY_RE = re.compile(r"^[a-z0-9_-]+$")
_ONLINE_WINDOW = timedelta(minutes=5)


# --- shape helpers --------------------------------------------------------


def _user_admin_out(user: User, device_count: int) -> UserAdminOut:
    return UserAdminOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        has_password=user.password_hash is not None,
        device_count=device_count,
    )


def _device_for_user_out(device: Device) -> DeviceForUserOut:
    return DeviceForUserOut(
        id=device.id,
        device_key=device.device_key,
        name=device.name,
        location=device.location,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        mqtt_provisioned=device.mqtt_provisioned,
    )


def _device_admin_out(device: Device, owner: User) -> DeviceAdminOut:
    return DeviceAdminOut(
        id=device.id,
        device_key=device.device_key,
        name=device.name,
        location=device.location,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        mqtt_provisioned=device.mqtt_provisioned,
        owner=OwnerOut(id=owner.id, email=owner.email, display_name=owner.display_name),
    )


# --- MQTT helpers ---------------------------------------------------------


def _generate_mqtt_password() -> str:
    """24-char URL-safe password (18 random bytes → base64url)."""
    return secrets.token_urlsafe(18)


def _build_ssh_command(device_key: str, password: str) -> str:
    """Construct the SSH one-liner the admin runs on the VPS to register the
    password with Mosquitto. device_key has already passed _DEVICE_KEY_RE so
    shell-quoting is not a concern; the password is URL-safe alphanumeric +
    ``-_`` so it also can't break out of the argv slot.
    """
    resource = get_settings().MOSQUITTO_RESOURCE_NAME
    return (
        f'docker exec $(docker ps --filter "label=coolify.resourceName={resource}" -q) '
        f"sh /mosquitto/config/scripts/add_device.sh {device_key} {password}"
    )


async def _device_count(db: AsyncSession, user_id: int) -> int:
    count = await db.execute(
        select(sa.func.count(Device.id)).where(Device.user_id == user_id)
    )
    return count.scalar_one()


# =========================================================================
# USERS
# =========================================================================


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserAdminOut]:
    users = (
        (await db.execute(select(User).order_by(User.created_at.desc())))
        .scalars()
        .all()
    )
    # N+1 over the device_count subquery is fine at this scale (≤10 users).
    out: list[UserAdminOut] = []
    for user in users:
        count = await _device_count(db, user.id)
        out.append(_user_admin_out(user, count))
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
    await db.flush()  # populate user.id before inserting the token row

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
        user=_user_admin_out(user, device_count=0),
        invitation_url=invitation_url,
    )


@router.get("/users/{user_id}", response_model=UserAdminDetailOut)
async def get_user(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> UserAdminDetailOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    devices = (
        (
            await db.execute(
                select(Device)
                .where(Device.user_id == user_id)
                .order_by(Device.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return UserAdminDetailOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        has_password=user.password_hash is not None,
        device_count=len(devices),
        devices=[_device_for_user_out(d) for d in devices],
    )


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
    # FK cascades take care of sessions, auth_tokens, devices, readings.
    await db.delete(user)
    await db.commit()
    log.info("admin deleted user id=%s email=%s", user_id, user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =========================================================================
# DEVICES
# =========================================================================


@router.get("/devices", response_model=list[DeviceAdminOut])
async def list_devices(
    q: str | None = Query(default=None),
    device_status: Literal["online", "offline"] | None = Query(
        default=None, alias="status"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceAdminOut]:
    stmt = select(Device, User).join(User, Device.user_id == User.id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Device.device_key.ilike(pattern),
                Device.name.ilike(pattern),
                Device.location.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if device_status is not None:
        threshold = datetime.now(UTC) - _ONLINE_WINDOW
        if device_status == "online":
            stmt = stmt.where(Device.last_seen_at >= threshold)
        else:
            stmt = stmt.where(
                or_(Device.last_seen_at < threshold, Device.last_seen_at.is_(None))
            )
    stmt = stmt.order_by(
        Device.last_seen_at.desc().nullslast(),
        Device.created_at.desc(),
    )
    rows = (await db.execute(stmt)).all()
    return [_device_admin_out(device, owner) for device, owner in rows]


@router.get("/devices/{device_id}", response_model=DeviceAdminOut)
async def get_device(
    device_id: int, db: AsyncSession = Depends(get_db)
) -> DeviceAdminOut:
    row = (
        await db.execute(
            select(Device, User)
            .join(User, Device.user_id == User.id)
            .where(Device.id == device_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    device, owner = row
    return _device_admin_out(device, owner)


@router.post(
    "/devices", response_model=CreateDeviceOut, status_code=status.HTTP_201_CREATED
)
async def create_device(
    payload: CreateDeviceIn, db: AsyncSession = Depends(get_db)
) -> CreateDeviceOut:
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
            select(Device).where(Device.device_key == payload.device_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "device_key already exists")

    device = Device(
        user_id=payload.user_id,
        device_key=payload.device_key,
        name=payload.name,
        location=payload.location,
        mqtt_provisioned=False,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    password = _generate_mqtt_password()
    ssh_command = _build_ssh_command(payload.device_key, password)
    log.info(
        "admin created device id=%s key=%s owner=%s; mqtt password=<redacted>",
        device.id,
        device.device_key,
        owner.id,
    )
    return CreateDeviceOut(
        device=_device_admin_out(device, owner),
        mqtt_password=password,
        ssh_command=ssh_command,
    )


@router.patch("/devices/{device_id}", response_model=DeviceAdminOut)
async def patch_device(
    device_id: int,
    payload: PatchDeviceIn,
    db: AsyncSession = Depends(get_db),
) -> DeviceAdminOut:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")

    # exclude_unset distinguishes "field omitted" from "field set to null".
    updates = payload.model_dump(exclude_unset=True)

    if "name" in updates and updates["name"] is not None:
        device.name = updates["name"]
    if "location" in updates:
        # location is nullable: explicit None means "clear it".
        device.location = updates["location"]
    if "mqtt_provisioned" in updates and updates["mqtt_provisioned"] is not None:
        device.mqtt_provisioned = updates["mqtt_provisioned"]
    if "user_id" in updates and updates["user_id"] is not None:
        new_owner = await db.get(User, updates["user_id"])
        if new_owner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user_id not found")
        device.user_id = updates["user_id"]

    await db.commit()
    await db.refresh(device)

    owner = await db.get(User, device.user_id)
    assert owner is not None  # FK guarantees this; assert silences type checker
    log.info(
        "admin patched device id=%s fields=%s", device_id, sorted(updates.keys())
    )
    return _device_admin_out(device, owner)


@router.post(
    "/devices/{device_id}/rotate-mqtt-password", response_model=RotateMqttOut
)
async def rotate_mqtt_password(
    device_id: int, db: AsyncSession = Depends(get_db)
) -> RotateMqttOut:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")

    password = _generate_mqtt_password()
    # New password not yet pushed to Mosquitto; reset the flag.
    device.mqtt_provisioned = False
    await db.commit()

    ssh_command = _build_ssh_command(device.device_key, password)
    log.info(
        "admin rotated MQTT password for device id=%s key=%s; password=<redacted>",
        device.id,
        device.device_key,
    )
    return RotateMqttOut(mqtt_password=password, ssh_command=ssh_command)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    # FK cascade drops the device's readings.
    await db.delete(device)
    await db.commit()
    log.info("admin deleted device id=%s key=%s", device_id, device.device_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
