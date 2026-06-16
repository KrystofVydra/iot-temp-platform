"""Pydantic schemas for incoming MQTT telemetry.

Wire format (firmware-controlled — keep the validators in sync):

    {
      "source": 0,            // 0=wifi, 1=cellular (reserved)
      "sn":     "4876",       // last 4 chars of controller serial
      "b":      87,           // uint8 battery percentage 0..100 (firmware computes per hardware revision)
      "d":      0,            // 0=door closed, 1=door open
      "node": {
        "id":  1,             // 1..5
        "t":   5.42,          // optional float; OMITTED on temp error
        "l":   4,             // optional int 0..1310; OMITTED on lux error
        "err": "sensor_lux"   // optional; one of the four values below
      }
    }

The error pattern is: invalid measurements are OMITTED from the wire
(not nulled), and ``err`` flags which. ``node.l`` is also omitted when the
node has no lux sensor — the ingestor decides whether to store it based on
its persisted ``Node.has_lux`` flag.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The four discriminator values the firmware emits.
TelemetryErr = Literal["sensor_lux", "sensor_temp", "sensor_both", "comms"]


class IncomingTelemetryNode(BaseModel):
    """The ``node`` sub-object on each MQTT message."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1, le=5)
    t: float | None = Field(default=None, ge=-99.99, le=99.99)
    # Wire key ``l`` is single-letter and ambiguous with ``1``/``I``; suppress
    # ruff's E741 since the firmware dictates this name.
    l: int | None = Field(default=None, ge=0, le=1310)  # noqa: E741
    err: TelemetryErr | None = None


class IncomingTelemetry(BaseModel):
    """Top-level MQTT message payload."""

    model_config = ConfigDict(extra="forbid")

    source: int = Field(ge=0)
    sn: str = Field(min_length=1)
    b: int = Field(ge=0, le=100)
    d: int = Field(ge=0, le=1)
    node: IncomingTelemetryNode
