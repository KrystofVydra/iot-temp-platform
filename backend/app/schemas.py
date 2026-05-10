"""Pydantic v2 response schemas for the public API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
