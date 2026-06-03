"""SQLAlchemy 2.0 ORM models for the IoT temperature platform.

Tables: ``users``, ``devices``, ``readings``, ``sessions``, ``auth_tokens``.
``readings`` is a TimescaleDB hypertable; the others are plain Postgres
tables. From SQLAlchemy's perspective ``readings`` has a composite primary
key on ``(time, device_id)``.
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
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # NULL = account exists but no password set yet (awaiting invitation accept).
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


class Device(Base):
    __tablename__ = "devices"

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
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class Reading(Base):
    __tablename__ = "readings"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    temperature: Mapped[float] = mapped_column(REAL, nullable=False)
    lux: Mapped[int] = mapped_column(Integer, nullable=False)
    battery_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rssi: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    __table_args__ = (
        Index(
            "idx_readings_device_time",
            "device_id",
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
