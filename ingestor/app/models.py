"""SQLAlchemy 2.0 ORM models — mirror of backend/app/models.py.

The two files must stay in sync. Auth-only models (Session, AuthToken) are
omitted; the ingestor doesn't touch them.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
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


class Gateway(Base):
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
