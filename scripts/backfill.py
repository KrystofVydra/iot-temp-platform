#!/usr/bin/env python3
"""Backfill realistic demo sensor data into the readings hypertable.

One-shot script. Ensures a demo user + device exist, generates ~6 months of
1-minute readings with a realistic fridge-temperature sawtooth, day/night
lux curve, and slow battery drain, then bulk-loads via copy_records_to_table.

Idempotent within its time window: any existing readings for the demo device
in [start, end) are deleted before insertion, so re-runs replace rather than
duplicate.

Usage:
    DATABASE_URL=postgresql+asyncpg://iot:pass@host:5432/iot python backfill.py

DATABASE_URL is in SQLAlchemy form for compatibility with the rest of the
platform; the ``+asyncpg`` dialect suffix is stripped before being passed
to ``asyncpg.connect()``.
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import sys
from datetime import UTC, datetime, timedelta

import asyncpg

# --- Demo entity identity --------------------------------------------------

DEMO_USER_EMAIL = "demo@example.com"
DEMO_DEVICE_KEY = "demo-backfill"
DEMO_DEVICE_NAME = "Demo Sensor"
DEMO_DEVICE_LOCATION = "Demo Lab"

# --- Generation parameters -------------------------------------------------

INTERVAL_SECONDS = 60
DAYS_BACK = 6 * 30          # ~6 months
BATCH_SIZE = 50_000

# Fridge thermostat: slow drift up between compressor kicks, fast drop down.
T_LOWER = 3.5
T_UPPER = 6.5
WARMING_RATE = 0.083        # °C / min when compressor off (~36 min over 3°C)
COOLING_RATE = -0.33        # °C / min when compressor on  (~9 min over 3°C)
WARMING_RATE_JITTER = (0.75, 1.25)   # per-cycle multiplier → 28–48 min warming
THRESHOLD_JITTER = 0.3      # ±°C noise on switch-over points each cycle
TEMP_NOISE_SIGMA = 0.2
TEMP_CLAMP_MIN = 2.0
TEMP_CLAMP_MAX = 10.0

# Door-opening events: brief upward spike + exponential recovery.
DOOR_EVENTS_PER_DAY_MIN = 3
DOOR_EVENTS_PER_DAY_MAX = 8
DOOR_HOUR_RANGE = (7.0, 23.0)        # 07:00 – 23:00 UTC
DOOR_SPIKE_RANGE = (2.0, 5.0)        # °C added per event
DOOR_DECAY_PER_MIN = 0.07            # ≈ 10-min half-life

# Day/night lux model.
LUX_PEAK = 800
DAY_START_HOUR = 6
DAY_END_HOUR = 20
LUX_NOISE_SIGMA = 5

# Battery drain.
BATTERY_START_MV = 4100
BATTERY_END_MV = 3600
BATTERY_NOISE_SIGMA = 1.0
BATTERY_BUMP_PROB = 5e-5             # rare upward jolt
BATTERY_BUMP_RANGE = (10, 30)


def _generate_door_events(start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Sample door-opening event timestamps + spike magnitudes over the window."""
    events: list[tuple[datetime, float]] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        n = random.randint(DOOR_EVENTS_PER_DAY_MIN, DOOR_EVENTS_PER_DAY_MAX)
        for _ in range(n):
            hour = random.uniform(*DOOR_HOUR_RANGE)
            event_ts = day + timedelta(hours=hour)
            if start <= event_ts <= end:
                events.append((event_ts, random.uniform(*DOOR_SPIKE_RANGE)))
        day += timedelta(days=1)
    events.sort(key=lambda e: e[0])
    return events


def _generate_records(
    start: datetime, end: datetime, device_id: int
) -> tuple[list[tuple], float, float, int]:
    """Generate readings.

    Returns ``(records, temp_min, temp_max, final_battery_mv)`` where each
    record is the tuple ``(time, device_id, temperature, lux, battery_raw, rssi)``
    ready for ``copy_records_to_table``.
    """

    door_events = _generate_door_events(start, end)
    total_seconds = (end - start).total_seconds()

    temp = (T_LOWER + T_UPPER) / 2
    compressor_on = False
    upper_target = T_UPPER + random.uniform(-THRESHOLD_JITTER, THRESHOLD_JITTER)
    lower_target = T_LOWER + random.uniform(-THRESHOLD_JITTER, THRESHOLD_JITTER)
    warming_rate = WARMING_RATE * random.uniform(*WARMING_RATE_JITTER)

    door_offset = 0.0
    door_idx = 0

    records: list[tuple] = []
    temp_min = math.inf
    temp_max = -math.inf

    ts = start
    while ts < end:
        # Fire any door events whose start time has just passed.
        while door_idx < len(door_events) and door_events[door_idx][0] <= ts:
            door_offset += door_events[door_idx][1]
            door_idx += 1

        # Compressor state machine.
        if compressor_on:
            temp += COOLING_RATE
            if temp <= lower_target:
                compressor_on = False
                upper_target = T_UPPER + random.uniform(-THRESHOLD_JITTER, THRESHOLD_JITTER)
                warming_rate = WARMING_RATE * random.uniform(*WARMING_RATE_JITTER)
        else:
            temp += warming_rate
            if temp >= upper_target:
                compressor_on = True
                lower_target = T_LOWER + random.uniform(-THRESHOLD_JITTER, THRESHOLD_JITTER)

        # Door spike decays toward zero each minute.
        door_offset *= 1.0 - DOOR_DECAY_PER_MIN
        if door_offset < 0.01:
            door_offset = 0.0

        # Final temperature reading.
        t_reading = temp + door_offset + random.gauss(0, TEMP_NOISE_SIGMA)
        t_reading = max(TEMP_CLAMP_MIN, min(TEMP_CLAMP_MAX, t_reading))

        # Lux: peaked sin² curve during daylight, zero at night.
        hour_of_day = ts.hour + ts.minute / 60
        if DAY_START_HOUR <= hour_of_day <= DAY_END_HOUR:
            phase = (hour_of_day - DAY_START_HOUR) / (DAY_END_HOUR - DAY_START_HOUR)
            base_lux = LUX_PEAK * math.sin(math.pi * phase) ** 2
        else:
            base_lux = 0.0
        lux = max(0, int(base_lux + random.gauss(0, LUX_NOISE_SIGMA)))

        # Battery: linear decline + tiny noise + rare upward bumps.
        fraction = (ts - start).total_seconds() / total_seconds
        battery_base = BATTERY_START_MV - (BATTERY_START_MV - BATTERY_END_MV) * fraction
        battery_noise = random.gauss(0, BATTERY_NOISE_SIGMA)
        battery_bump = (
            random.uniform(*BATTERY_BUMP_RANGE) if random.random() < BATTERY_BUMP_PROB else 0
        )
        battery_raw = int(battery_base + battery_noise + battery_bump)

        records.append((ts, device_id, round(t_reading, 2), lux, battery_raw, None))
        if t_reading < temp_min:
            temp_min = t_reading
        if t_reading > temp_max:
            temp_max = t_reading

        ts += timedelta(seconds=INTERVAL_SECONDS)

    final_battery = records[-1][4]
    return records, temp_min, temp_max, final_battery


async def main() -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        print("Error: DATABASE_URL must be set", file=sys.stderr)
        sys.exit(1)
    # asyncpg expects the bare postgres URL — strip SQLAlchemy's +asyncpg dialect.
    asyncpg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    print("Connecting to database…")
    conn = await asyncpg.connect(asyncpg_url)
    try:
        # Demo user (upsert by email).
        await conn.execute(
            "INSERT INTO users (email) VALUES ($1) ON CONFLICT (email) DO NOTHING",
            DEMO_USER_EMAIL,
        )
        user_id = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", DEMO_USER_EMAIL
        )
        print(f"Demo user id = {user_id}")

        # Demo device (upsert by device_key).
        await conn.execute(
            """
            INSERT INTO devices (user_id, device_key, name, location)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (device_key) DO NOTHING
            """,
            user_id,
            DEMO_DEVICE_KEY,
            DEMO_DEVICE_NAME,
            DEMO_DEVICE_LOCATION,
        )
        device_id = await conn.fetchval(
            "SELECT id FROM devices WHERE device_key = $1", DEMO_DEVICE_KEY
        )
        print(f"Demo device id = {device_id}")

        # Generation window — snap end to whole minute so timestamps are clean.
        end = datetime.now(UTC).replace(second=0, microsecond=0)
        start = end - timedelta(days=DAYS_BACK)
        print(f"Time window: {start.isoformat()} → {end.isoformat()}")

        print("Generating readings…")
        records, t_min, t_max, final_battery = _generate_records(start, end, device_id)
        print(f"Generated {len(records):,} rows")

        # Idempotency: wipe any existing rows in the window for this device.
        delete_status = await conn.execute(
            "DELETE FROM readings WHERE device_id = $1 AND time >= $2 AND time < $3",
            device_id,
            start,
            end,
        )
        n_deleted = (
            int(delete_status.split()[-1]) if delete_status.startswith("DELETE") else 0
        )
        print(f"Deleted {n_deleted:,} pre-existing rows in window")

        # Bulk-insert via COPY in batches.
        inserted = 0
        for offset in range(0, len(records), BATCH_SIZE):
            chunk = records[offset : offset + BATCH_SIZE]
            await conn.copy_records_to_table(
                "readings",
                records=chunk,
                columns=("time", "device_id", "temperature", "lux", "battery_raw", "rssi"),
            )
            inserted += len(chunk)
            print(f"  inserted {inserted:,} / {len(records):,}")

        # Update device's last_seen_at to the final reading's timestamp.
        last_time = records[-1][0]
        await conn.execute(
            "UPDATE devices SET last_seen_at = $1 WHERE id = $2",
            last_time,
            device_id,
        )

        print()
        print("=" * 60)
        print("Backfill complete.")
        print(f"  Device id:        {device_id}")
        print(f"  Time range:       {start.isoformat()}")
        print(f"                  → {end.isoformat()}")
        print(f"  Rows generated:   {len(records):,}")
        print(f"  Old rows deleted: {n_deleted:,}")
        print(f"  Rows inserted:    {inserted:,}")
        print(f"  Temp min / max:   {t_min:.2f}°C / {t_max:.2f}°C")
        print(f"  Final battery:    {final_battery} mV")
        print(f"  last_seen_at set: {last_time.isoformat()}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
