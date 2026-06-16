"""Ingestor worker.

Subscribes to MQTT, decodes telemetry payloads under the new topology
(gateway → controller → node), and writes:
  * one ``node_readings`` row per message (per-node temperature/lux/err)
  * one ``controller_telemetry`` row per message (per-controller battery_pct/door_open)

Unknown controllers (sn we've never seen on this gateway) are recorded in
``pending_controllers`` for the admin to accept before any readings land —
this prevents an unprovisioned-but-MQTT-authenticated node from polluting
the time-series.

Nodes are auto-created on first sight (the admin can rename them later);
the ``has_lux`` flag is captured at creation time from whether the first
message carried a lux value.

Run with ``python -m app.main``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import aiomqtt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session_factory
from .models import Controller, ControllerTelemetry, Gateway, Node, NodeReading
from .schemas import IncomingTelemetry

log = logging.getLogger("ingestor")


async def _record_pending_controller(
    session: AsyncSession, gateway_id: int, sn: str, now: datetime
) -> None:
    """Upsert into pending_controllers. Raw SQL for the ON CONFLICT clause."""
    await session.execute(
        text(
            """
            INSERT INTO pending_controllers
                (gateway_id, sn, first_seen_at, last_seen_at, message_count)
            VALUES (:gateway_id, :sn, :now, :now, 1)
            ON CONFLICT (gateway_id, sn) DO UPDATE
            SET last_seen_at = EXCLUDED.last_seen_at,
                message_count = pending_controllers.message_count + 1
            """
        ),
        {"gateway_id": gateway_id, "sn": sn, "now": now},
    )


async def _handle_message(topic: str, payload_bytes: bytes) -> None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "devices" or parts[2] != "telemetry":
        log.warning("ignoring unexpected topic: %s", topic)
        return
    gateway_key = parts[1]

    try:
        raw = json.loads(payload_bytes)
        payload = IncomingTelemetry.model_validate(raw)
    except (ValueError, TypeError) as exc:
        log.warning("invalid payload on %s: %s", topic, exc)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        now = datetime.now(UTC)

        # 1. Gateway must exist (provisioned via the admin panel).
        gateway = (
            await session.execute(
                select(Gateway).where(Gateway.device_key == gateway_key)
            )
        ).scalar_one_or_none()
        if gateway is None:
            log.warning(
                "unknown gateway_key %s — dropping (MQTT ACL should have blocked)",
                gateway_key,
            )
            return
        gateway.last_seen_at = now

        # 2. Controller — accepted controllers only. Unknowns get staged.
        controller = (
            await session.execute(
                select(Controller).where(
                    Controller.gateway_id == gateway.id,
                    Controller.sn == payload.sn,
                )
            )
        ).scalar_one_or_none()
        if controller is None:
            await _record_pending_controller(session, gateway.id, payload.sn, now)
            await session.commit()
            log.info(
                "pending controller sn=%s on gateway %s (message dropped)",
                payload.sn,
                gateway_key,
            )
            return
        controller.last_seen_at = now

        # 3. Node — auto-created on first sight. has_lux captured from this message.
        node = (
            await session.execute(
                select(Node).where(
                    Node.controller_id == controller.id,
                    Node.node_index == payload.node.id,
                )
            )
        ).scalar_one_or_none()
        if node is None:
            node = Node(
                controller_id=controller.id,
                node_index=payload.node.id,
                name=None,
                has_lux=payload.node.l is not None,
                last_seen_at=now,
            )
            session.add(node)
            await session.flush()  # populate node.id for the FK below
            log.info(
                "auto-created node idx=%d on controller sn=%s has_lux=%s",
                payload.node.id,
                payload.sn,
                node.has_lux,
            )
        node.last_seen_at = now

        # 4. Build the per-node reading.
        temperature = payload.node.t  # already None if omitted
        lux: int | None = None
        if payload.node.l is not None:
            if node.has_lux:
                lux = payload.node.l
            else:
                log.debug(
                    "discarding lux for has_lux=false node idx=%d controller sn=%s",
                    payload.node.id,
                    payload.sn,
                )
        err = payload.node.err

        # 5. Build the per-controller telemetry (battery + door). Firmware
        # sends `b` as a 0..100 percentage directly (each revision handles
        # its own chemistry → percentage mapping); Pydantic already enforced
        # the range on parse.
        battery_pct = payload.b
        door_open = payload.d == 1

        session.add(
            NodeReading(
                time=now,
                node_id=node.id,
                temperature=temperature,
                lux=lux,
                err=err,
            )
        )
        session.add(
            ControllerTelemetry(
                time=now,
                controller_id=controller.id,
                battery_pct=battery_pct,
                door_open=door_open,
            )
        )
        await session.commit()

        # 6. Log line — skip None-valued fields so the output stays readable.
        log_fields = [
            f"controller={payload.sn}",
            f"node={payload.node.id}",
        ]
        if temperature is not None:
            log_fields.append(f"temp={temperature:.2f}")
        if lux is not None:
            log_fields.append(f"lux={lux}")
        if err is not None:
            log_fields.append(f"err={err}")
        log.info("stored reading %s", " ".join(log_fields))


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
                    # Retained messages are replayed by the broker on every
                    # (re)subscribe; ingesting them stamps stale telemetry with
                    # a fresh "now" and falsely keeps devices "online".
                    if message.retain:
                        log.info(
                            "ignoring retained message on %s", str(message.topic)
                        )
                        continue
                    await _handle_message(str(message.topic), bytes(message.payload))
        except aiomqtt.MqttError as exc:
            log.error("mqtt error: %s — reconnecting in 5s", exc)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
