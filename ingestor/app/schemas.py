"""Pydantic schemas for incoming sensor telemetry.

The wire format is intentionally terse — single-character keys — to keep
ESP32 firmware MQTT payloads small. Decoding happens here so the database
stores values that are convenient to query.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TelemetryPayload(BaseModel):
    t: int = Field(ge=0, le=65535)  # raw uint16 temperature
    l: int = Field(ge=0, le=65535)  # noqa: E741  raw uint16 lux (wire format)
    b: int = Field(ge=0, le=65535)  # raw uint16 battery mV


def to_reading_values(payload: TelemetryPayload) -> dict[str, float | int]:
    """Convert a validated payload into kwargs for the ``Reading`` model.

    Sensor encoding:
      * temperature = (t - 9999) / 100  →  -99.99 .. 555.36 °C, 2-dp
      * lux         = l                 →  raw lux units, stored as-is
      * battery_raw = b                 →  battery mV, stored as-is
    """
    return {
        "temperature": round((payload.t - 9999) / 100.0, 2),
        "lux": payload.l,
        "battery_raw": payload.b,
    }
