"""Pydantic v2 response schemas for the public API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from .models import Reading


class DeviceOut(BaseModel):
    id: int
    device_key: str
    name: str
    location: str | None
    last_seen_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ReadingOut(BaseModel):
    time: datetime
    temperature: float
    lux: int
    battery_raw: int | None
    battery_v: float | None
    rssi: int | None

    model_config = ConfigDict(from_attributes=True)


class DeviceWithLatestReading(BaseModel):
    device: DeviceOut
    latest: ReadingOut | None


def _battery_v(battery_raw: int | None) -> float | None:
    return battery_raw / 1000.0 if battery_raw is not None else None


def reading_to_out(reading: Reading) -> ReadingOut:
    """Build a ``ReadingOut`` from an ORM ``Reading``, computing ``battery_v``."""
    return ReadingOut(
        time=reading.time,
        temperature=reading.temperature,
        lux=reading.lux,
        battery_raw=reading.battery_raw,
        battery_v=_battery_v(reading.battery_raw),
        rssi=reading.rssi,
    )


# =============================================================================
# Admin endpoints (/admin/*) — schemas
# =============================================================================


class OwnerOut(BaseModel):
    """Truncated user info embedded in DeviceAdminOut.owner."""

    id: int
    email: str
    display_name: str


class UserAdminOut(BaseModel):
    """A user as returned to admins. has_password / device_count are derived."""

    id: int
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    has_password: bool
    device_count: int


class DeviceForUserOut(BaseModel):
    """Device sub-object embedded in GET /admin/users/{id}.devices."""

    id: int
    device_key: str
    name: str
    location: str | None
    created_at: datetime
    last_seen_at: datetime | None
    mqtt_provisioned: bool


class UserAdminDetailOut(UserAdminOut):
    """GET /admin/users/{id}: user shape + their devices."""

    devices: list[DeviceForUserOut]


class CreateUserIn(BaseModel):
    email: EmailStr
    display_name: str


class CreateUserOut(BaseModel):
    user: UserAdminOut
    invitation_url: str


class ResetLinkOut(BaseModel):
    reset_url: str


class DeviceAdminOut(BaseModel):
    """Full device row in admin responses, with embedded owner."""

    id: int
    device_key: str
    name: str
    location: str | None
    created_at: datetime
    last_seen_at: datetime | None
    mqtt_provisioned: bool
    owner: OwnerOut


class CreateDeviceIn(BaseModel):
    user_id: int
    device_key: str
    name: str
    location: str | None = None


class CreateDeviceOut(BaseModel):
    """POST /admin/devices response. The mqtt_password is shown once; the
    backend never persists it. ssh_command is the one-shot provisioning
    command the admin runs on the VPS.
    """

    device: DeviceAdminOut
    mqtt_password: str
    ssh_command: str


class RotateMqttOut(BaseModel):
    """POST /admin/devices/{id}/rotate-mqtt-password response."""

    mqtt_password: str
    ssh_command: str


class PatchDeviceIn(BaseModel):
    """Partial update for a device. Fields omitted from the JSON body are
    left unchanged. An explicit ``"location": null`` clears the location.
    Other non-nullable fields are ignored when sent as null.
    """

    name: str | None = None
    location: str | None = None
    user_id: int | None = None
    mqtt_provisioned: bool | None = None
