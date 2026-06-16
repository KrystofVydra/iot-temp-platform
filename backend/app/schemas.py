"""Pydantic v2 response schemas for the public API.

Organised around the Phase 3+ topology:

  users → gateways → controllers → nodes → node_readings
                                 → controller_telemetry

The schemas fall into three groups:

  * Auth / user-management (shared with admin)
  * User-facing controller views (used by the dashboard)
  * Admin gateway / controller / node management
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

# ===========================================================================
# Auth / user-management shared between /auth and /admin/users/*
# ===========================================================================


class OwnerOut(BaseModel):
    """Truncated user info embedded in admin gateway responses."""

    id: int
    email: str
    display_name: str


class UserAdminOut(BaseModel):
    """User row as returned to admins. ``has_password`` / ``gateway_count`` are derived."""

    id: int
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    has_password: bool
    gateway_count: int


class GatewayForUserOut(BaseModel):
    """Gateway sub-object embedded in GET /admin/users/{id}.gateways."""

    id: int
    device_key: str
    name: str
    location: str | None
    mqtt_provisioned: bool
    created_at: datetime
    last_seen_at: datetime | None
    controller_count: int


class UserAdminDetailOut(UserAdminOut):
    """GET /admin/users/{id} — user shape + their gateways."""

    gateways: list[GatewayForUserOut]


class CreateUserIn(BaseModel):
    email: EmailStr
    display_name: str


class CreateUserOut(BaseModel):
    user: UserAdminOut
    invitation_url: str


class ResetLinkOut(BaseModel):
    reset_url: str


class InvitationLinkOut(BaseModel):
    invitation_url: str


# ===========================================================================
# User-facing controller endpoints (/controllers/*)
# ===========================================================================


class GatewayBrief(BaseModel):
    """Gateway summary embedded in list-controllers response."""

    id: int
    device_key: str
    name: str


class GatewayBriefDetail(BaseModel):
    """Gateway summary embedded in controller-detail response (adds location)."""

    id: int
    device_key: str
    name: str
    location: str | None


class ControllerLatest(BaseModel):
    """Latest-status summary for the controller list view."""

    time: datetime | None
    temperature_avg: float | None
    battery_pct: int | None
    door_open: bool | None
    any_node_error: bool


class ControllerOut(BaseModel):
    """Controller row in GET /controllers."""

    id: int
    sn: str
    name: str
    location: str | None
    gateway: GatewayBrief
    node_count: int
    last_seen_at: datetime | None
    latest: ControllerLatest


class NodeLatest(BaseModel):
    time: datetime | None
    temperature: float | None
    lux: int | None
    err: str | None


class NodeOut(BaseModel):
    id: int
    node_index: int
    name: str | None
    has_lux: bool
    last_seen_at: datetime | None
    latest: NodeLatest


class LatestTelemetry(BaseModel):
    time: datetime | None
    battery_pct: int | None
    door_open: bool | None


class ControllerDetailOut(BaseModel):
    """GET /controllers/{id} and GET /admin/controllers/{id}."""

    id: int
    sn: str
    name: str
    location: str | None
    gateway: GatewayBriefDetail
    nodes: list[NodeOut]
    latest_telemetry: LatestTelemetry


class ReadingsPointOut(BaseModel):
    """Single time-bucket of averaged temperature for the controller chart."""

    time: datetime
    temperature_avg: float | None


class TelemetryPointOut(BaseModel):
    """Single time-bucket of controller battery + door state."""

    time: datetime
    battery_pct: int | None
    door_open: bool | None


# ===========================================================================
# Admin gateway / controller / node management
# ===========================================================================


class GatewayAdminOut(BaseModel):
    """Gateway row in admin list / created / patched responses."""

    id: int
    device_key: str
    name: str
    location: str | None
    mqtt_provisioned: bool
    created_at: datetime
    last_seen_at: datetime | None
    owner: OwnerOut
    controller_count: int


class ControllerForGatewayOut(BaseModel):
    """Controller sub-object embedded in GET /admin/gateways/{id}.controllers."""

    id: int
    sn: str
    name: str
    location: str | None
    created_at: datetime
    last_seen_at: datetime | None
    node_count: int


class PendingControllerOut(BaseModel):
    """Pending controller sub-object embedded in GET /admin/gateways/{id}."""

    id: int
    sn: str
    first_seen_at: datetime
    last_seen_at: datetime
    message_count: int


class GatewayDetailAdminOut(GatewayAdminOut):
    """GET /admin/gateways/{id} — gateway shape + its controllers + pending."""

    controllers: list[ControllerForGatewayOut]
    pending_controllers: list[PendingControllerOut]


class CreateGatewayIn(BaseModel):
    user_id: int
    device_key: str
    name: str
    location: str | None = None


class CreateGatewayOut(BaseModel):
    """POST /admin/gateways response. The mqtt_password is shown once."""

    gateway: GatewayAdminOut
    mqtt_password: str
    ssh_command: str


class PatchGatewayIn(BaseModel):
    """Partial update. ``device_key`` is immutable."""

    name: str | None = None
    location: str | None = None
    user_id: int | None = None
    mqtt_provisioned: bool | None = None


class RotateMqttOut(BaseModel):
    mqtt_password: str
    ssh_command: str


class AcceptPendingControllerIn(BaseModel):
    """POST /admin/pending-controllers/{id}/accept body."""

    name: str
    location: str | None = None


class PatchControllerIn(BaseModel):
    """PATCH /admin/controllers/{id}. ``sn`` is immutable (hardware id);
    gateway reassignment is intentionally not supported in this phase."""

    name: str | None = None
    location: str | None = None


class PatchNodeIn(BaseModel):
    """PATCH /admin/nodes/{id}. ``node_index`` is immutable (hardware id)."""

    name: str | None = None
    has_lux: bool | None = None
