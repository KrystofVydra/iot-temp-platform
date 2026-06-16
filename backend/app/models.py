"""SQLAlchemy 2.0 ORM models for the IoT temperature platform.

Topology (Phase 3+):
  users → gateways → controllers → nodes → node_readings
                                 → controller_telemetry

Each ``Gateway`` is an MQTT identity (an ESP32 with broker creds, no
sensors of its own). A gateway hosts one or more ``Controllers``
(battery-powered, e.g. one per fridge). Each controller hosts 1–5
``Nodes`` (the actual temp/lux sensors). Per-node sensor readings land in
``node_readings``; per-controller battery/door state lands in
``controller_telemetry``. Both are TimescaleDB hypertables.

``pending_controllers`` is the staging area for controller serial numbers
the ingestor has seen but no admin has accepted yet.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(60), nullable=True)
    display_name: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="User"
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    gateways: Mapped[list[Gateway]] = relationship(
        "Gateway", back_populates="user"
    )
    notification_settings: Mapped[list[NotificationSetting]] = relationship(
        "NotificationSetting", back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )


class Gateway(Base):
    """MQTT identity. Holds 1+ controllers."""

    __tablename__ = "gateways"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    mqtt_provisioned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="gateways")
    controllers: Mapped[list[Controller]] = relationship(
        "Controller", back_populates="gateway"
    )


class Controller(Base):
    """One battery-powered controller (e.g. one per fridge). Hosts 1–5 nodes."""

    __tablename__ = "controllers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    gateway_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("gateways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sn: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    gateway: Mapped[Gateway] = relationship(
        "Gateway", back_populates="controllers"
    )
    nodes: Mapped[list[Node]] = relationship(
        "Node", back_populates="controller"
    )

    __table_args__ = (
        UniqueConstraint("gateway_id", "sn", name="uq_controllers_gateway_sn"),
    )


class Node(Base):
    """One physical temp/lux sensor under a controller. ``node_index`` is 1–5."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    controller_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("controllers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    has_lux: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    controller: Mapped[Controller] = relationship(
        "Controller", back_populates="nodes"
    )

    __table_args__ = (
        UniqueConstraint(
            "controller_id", "node_index", name="uq_nodes_controller_index"
        ),
    )


class PendingController(Base):
    """Controller serial numbers seen by the ingestor but not yet accepted."""

    __tablename__ = "pending_controllers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    gateway_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("gateways.id", ondelete="CASCADE"),
        nullable=False,
    )
    sn: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    __table_args__ = (
        UniqueConstraint(
            "gateway_id", "sn", name="uq_pending_controllers_gateway_sn"
        ),
    )


class NodeReading(Base):
    """Per-node temp/lux/err sample. TimescaleDB hypertable on ``time``."""

    __tablename__ = "node_readings"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    temperature: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lux: Mapped[int | None] = mapped_column(Integer, nullable=True)
    err: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index(
            "idx_node_readings_node_time",
            "node_id",
            text("time DESC"),
        ),
    )


class ControllerTelemetry(Base):
    """Per-controller battery/door sample. TimescaleDB hypertable on ``time``."""

    __tablename__ = "controller_telemetry"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    controller_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("controllers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    door_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index(
            "idx_controller_telemetry_controller_time",
            "controller_id",
            text("time DESC"),
        ),
    )


class Session(Base):
    """Server-side session row. ``token_hash`` is sha256-hex of the raw cookie value."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationKindDefault(Base):
    """Catalogue row per notification kind. Admin-editable globals."""

    __tablename__ = "notification_kind_defaults"

    kind: Mapped[str] = mapped_column(String(50), primary_key=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    thresholds: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class NotificationSetting(Base):
    """Per-user per-kind preference. Created at user-creation time."""

    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("notification_kind_defaults.kind", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    thresholds: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship("User", back_populates="notification_settings")

    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_notification_settings_user_kind"),
    )


class Notification(Base):
    """One firing notification. Created by the detector (Phase 4B)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("notification_kind_defaults.kind", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    gateway_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("gateways.id", ondelete="CASCADE"),
        nullable=True,
    )
    controller_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("controllers.id", ondelete="CASCADE"),
        nullable=True,
    )
    node_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    subject_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="notifications")


class AuthToken(Base):
    """One-time tokens: ``kind`` is 'invitation' or 'password_reset'."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
