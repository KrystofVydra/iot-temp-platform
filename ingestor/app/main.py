"""Ingestor worker.

Subscribes to MQTT, decodes telemetry payloads, and writes ``Reading`` rows
to TimescaleDB. Maintains a device_key → device_id cache to avoid a SELECT
on every message. Reconnects automatically on MQTT disconnect.

Run with ``python -m app.main``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import aiomqtt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session_factory
from .models import Device, Reading
from .schemas import TelemetryPayload, to_reading_values

log = logging.getLogger("ingestor")

# device_key → device_id. Negative misses are intentionally not cached, so
# a device provisioned after startup will be picked up on its next message.
_device_id_cache: dict[str, int] = {}


async def _get_device_id(session: AsyncSession, device_key: str) -> int | None:
    cached = _device_id_cache.get(device_key)
    if cached is not None:
        return cached
    result = await session.execute(
        select(Device.id).where(Device.device_key == device_key)
    )
    device_id = result.scalar_one_or_none()
    if device_id is not None:
        _device_id_cache[device_key] = device_id
    return device_id


async def _handle_message(topic: str, payload_bytes: bytes) -> None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "devices" or parts[2] != "telemetry":
        log.warning("ignoring unexpected topic: %s", topic)
        return
    device_key = parts[1]

    try:
        raw = json.loads(payload_bytes)
        payload = TelemetryPayload.model_validate(raw)
    except (ValueError, TypeError) as exc:
        log.warning("invalid payload on %s: %s", topic, exc)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        device_id = await _get_device_id(session, device_key)
        if device_id is None:
            log.warning("unknown device_key %s — dropping reading", device_key)
            return

        values = to_reading_values(payload)
        now = datetime.now(UTC)
        session.add(Reading(time=now, device_id=device_id, **values))
        await session.execute(
            update(Device).where(Device.id == device_id).values(last_seen_at=now)
        )
        await session.commit()
        log.info(
            "stored reading device=%s temp=%.2f°C lux=%d batt=%dmV",
            device_key,
            values["temperature"],
            values["lux"],
            values["battery_raw"],
        )


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info(
        "starting ingestor, connecting to mqtt://%s:%d topic=%s",
        settings.MQTT_HOST,
        settings.MQTT_PORT,
        settings.MQTT_TOPIC,
    )
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                username=settings.MQTT_USERNAME,
                password=settings.MQTT_PASSWORD,
            ) as client:
                await client.subscribe(settings.MQTT_TOPIC)
                log.info("subscribed, waiting for messages")
                async for message in client.messages:
                    await _handle_message(str(message.topic), bytes(message.payload))
        except aiomqtt.MqttError as exc:
            log.error("mqtt error: %s — reconnecting in 5s", exc)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
