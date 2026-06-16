#!/usr/bin/env python3
"""Backfill realistic demo data into the new gateway/controller/node hierarchy.

Generates one row per minute of node_readings per node plus a matching
controller_telemetry row per minute for a single controller hanging off an
existing gateway. The controller and its nodes are upserted by (gateway, sn)
and (controller, node_index); re-runs over the same window are idempotent
because we delete existing rows in [start, end) before insertion.

Temperatures follow a slow diurnal cycle around ~4 °C with door-open spikes;
per-node offsets simulate physical placement (node 1 near the door is
slightly warmer; higher node_index → slightly colder). Battery drifts from
100 % down to ~80 % over the window (integer percent, clamped 0..100) with
light noise. Door events come in short bursts (1-3 min, ~every 4 h) plus a
handful of long opens.

Usage:
    DATABASE_URL=postgresql+asyncpg://iot:pass@host:5432/iot \\
        python backfill.py \\
            --gateway-key warehouse-01 \\
            --controller-sn 4876 \\
            --node-count 3 \\
            --days-back 180

The +asyncpg dialect suffix is stripped before being passed to
asyncpg.connect(). DATABASE_URL is required.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys
from datetime import UTC, datetime, timedelta

import asyncpg


# ---------- generation tunables ---------------------------------------------

# Per-node baseline temperature (°C). Diurnal cycle adds a small sin wave on top.
T_BASE = 4.0
DIURNAL_AMPLITUDE = 1.0
TEMP_NOISE_SIGMA = 0.15
TEMP_CLAMP_MIN = 1.0
TEMP_CLAMP_MAX = 12.0

# Per-node offset relative to the controller average. Node 1 (near door)
# warmest, node 5 coldest. Linearly spaced.
NODE_OFFSET_RANGE = 1.2   # ±0.6 °C from front to back

# Door open events (controller_telemetry.door_open = TRUE).
SHORT_OPEN_AVG_INTERVAL_MIN = 240        # one short open ≈ every 4 hours
SHORT_OPEN_DURATION_RANGE = (1, 3)       # minutes
LONG_OPEN_COUNT_PER_30_DAYS = 4          # ~ one long open per week
LONG_OPEN_DURATION_RANGE = (10, 25)      # minutes
DOOR_SPIKE_RANGE = (2.0, 5.0)            # °C above baseline at peak
DOOR_RECOVERY_MIN = 10                   # how long after close the spike fully decays
DOOR_DECAY_PER_MIN = 0.18                # exponential decay factor

# Battery drift over the full window (integer percent).
BATTERY_START_PCT = 100
BATTERY_END_PCT = 80
BATTERY_NOISE_SIGMA = 2.0

# Lux model (only for has_lux nodes). Day/night sin² curve.
LUX_PEAK = 600
DAY_START_HOUR = 6
DAY_END_HOUR = 20
LUX_NOISE_SIGMA = 4


# ---------- helpers ---------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill demo data into the new gateway/controller/node hierarchy.",
    )
    p.add_argument(
        "--gateway-key",
        required=True,
        help="device_key of an existing gateway to attach the controller to.",
    )
    p.add_argument(
        "--controller-sn",
        required=True,
        help="Serial number of the synthetic controller (created if missing).",
    )
    p.add_argument(
        "--controller-name",
        default=None,
        help='Name for the controller when first created. Default "Backfill controller {sn}".',
    )
    p.add_argument(
        "--node-count",
        type=int,
        default=1,
        choices=range(1, 6),
        metavar="{1..5}",
        help="Number of nodes inside the controller (1-5). Default 1.",
    )
    p.add_argument(
        "--node-has-lux",
        dest="node_has_lux",
        action="store_true",
        default=True,
        help="Mark new nodes as having a lux sensor (default).",
    )
    p.add_argument(
        "--no-node-has-lux",
        dest="node_has_lux",
        action="store_false",
        help="Mark new nodes as NOT having a lux sensor.",
    )
    p.add_argument(
        "--days-back",
        type=int,
        default=180,
        help="Number of days of history to generate. Default 180.",
    )
    p.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Seconds between samples. Default 60 (one reading per minute).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per COPY chunk. Default 5000.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print row counts, but do not write.",
    )
    return p.parse_args()


def _asyncpg_url() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        print("Error: DATABASE_URL must be set", file=sys.stderr)
        sys.exit(1)
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


def _node_offset(node_index: int, node_count: int) -> float:
    """Return the per-node offset relative to the controller average.

    Linear ramp from +half the range (node 1, warmest) to −half (node N,
    coldest). Single-node controllers get zero offset.
    """
    if node_count <= 1:
        return 0.0
    pos = (node_index - 1) / (node_count - 1)   # 0..1
    return NODE_OFFSET_RANGE * (0.5 - pos)


def _generate_door_events(
    start: datetime, end: datetime
) -> list[tuple[datetime, int]]:
    """Sample door-open windows over [start, end).

    Returns a list of (open_at, duration_minutes) ordered by time. Mixes
    frequent short opens with rarer long-open events.
    """
    events: list[tuple[datetime, int]] = []
    total_minutes = int((end - start).total_seconds() // 60)

    # Short opens: Poisson-ish — exponential gaps with mean SHORT_OPEN_AVG_INTERVAL_MIN.
    t = start + timedelta(minutes=random.expovariate(1 / SHORT_OPEN_AVG_INTERVAL_MIN))
    while t < end:
        dur = random.randint(*SHORT_OPEN_DURATION_RANGE)
        events.append((t, dur))
        gap = random.expovariate(1 / SHORT_OPEN_AVG_INTERVAL_MIN)
        t += timedelta(minutes=gap)

    # Long opens: scatter a fixed count proportional to window length.
    long_open_count = max(
        1, int(LONG_OPEN_COUNT_PER_30_DAYS * total_minutes / (30 * 24 * 60))
    )
    for _ in range(long_open_count):
        when = start + timedelta(minutes=random.uniform(0, total_minutes))
        dur = random.randint(*LONG_OPEN_DURATION_RANGE)
        events.append((when, dur))

    events.sort(key=lambda e: e[0])
    return events


def _build_door_open_map(
    timestamps: list[datetime], events: list[tuple[datetime, int]]
) -> list[bool]:
    """For each timestamp, return True iff a door event is active that minute."""
    door_open = [False] * len(timestamps)
    # events are sorted; walk them in step with timestamps.
    ev_idx = 0
    for i, ts in enumerate(timestamps):
        while ev_idx < len(events) and events[ev_idx][0] + timedelta(
            minutes=events[ev_idx][1]
        ) <= ts:
            ev_idx += 1
        # active event covers ts iff it started ≤ ts and its end > ts
        j = ev_idx
        while j < len(events) and events[j][0] <= ts:
            if events[j][0] + timedelta(minutes=events[j][1]) > ts:
                door_open[i] = True
                break
            j += 1
    return door_open


def _lux_for(ts: datetime) -> int:
    hour = ts.hour + ts.minute / 60
    if DAY_START_HOUR <= hour <= DAY_END_HOUR:
        phase = (hour - DAY_START_HOUR) / (DAY_END_HOUR - DAY_START_HOUR)
        base = LUX_PEAK * math.sin(math.pi * phase) ** 2
    else:
        base = 0.0
    return max(0, int(base + random.gauss(0, LUX_NOISE_SIGMA)))


def _generate_node_readings(
    timestamps: list[datetime],
    node_id: int,
    node_index: int,
    node_count: int,
    has_lux: bool,
    door_open: list[bool],
) -> list[tuple]:
    """Return rows ready for COPY into node_readings.

    Tuple order: (time, node_id, temperature, lux, err).
    """
    offset = _node_offset(node_index, node_count)
    door_offset = 0.0
    last_door = False
    rows: list[tuple] = []
    minutes_per_day = 24 * 60

    for i, ts in enumerate(timestamps):
        # Day-of-week-independent diurnal sin (cooler at night, slightly warmer in afternoon)
        minute_of_day = ts.hour * 60 + ts.minute
        diurnal = DIURNAL_AMPLITUDE * math.sin(
            2 * math.pi * (minute_of_day - 6 * 60) / minutes_per_day
        )

        # Door spike: rises while door open, decays after close.
        if door_open[i]:
            if not last_door:
                door_offset = random.uniform(*DOOR_SPIKE_RANGE)
            else:
                # While the door stays open the spike stays elevated.
                door_offset = max(door_offset, random.uniform(*DOOR_SPIKE_RANGE))
        else:
            door_offset *= 1.0 - DOOR_DECAY_PER_MIN
            if door_offset < 0.02:
                door_offset = 0.0
        last_door = door_open[i]

        t = T_BASE + offset + diurnal + door_offset + random.gauss(0, TEMP_NOISE_SIGMA)
        t = max(TEMP_CLAMP_MIN, min(TEMP_CLAMP_MAX, t))

        lux = _lux_for(ts) if has_lux else None

        rows.append((ts, node_id, round(t, 2), lux, None))

        # Decay after the door closes back below the recovery threshold.
        if not door_open[i] and door_offset == 0.0:
            pass  # already settled

        # Keep door recovery loosely tied to DOOR_RECOVERY_MIN by checking decay.
        # (Door decay constant chosen so ~10 min covers the recovery window.)
        _ = DOOR_RECOVERY_MIN

    return rows


def _generate_telemetry(
    timestamps: list[datetime],
    controller_id: int,
    door_open: list[bool],
) -> list[tuple]:
    """Return rows ready for COPY into controller_telemetry.

    Tuple order: (time, controller_id, battery_pct, door_open).
    """
    total = len(timestamps)
    rows: list[tuple] = []
    for i, ts in enumerate(timestamps):
        frac = i / max(1, total - 1)
        pct = (
            BATTERY_START_PCT
            - (BATTERY_START_PCT - BATTERY_END_PCT) * frac
            + random.gauss(0, BATTERY_NOISE_SIGMA)
        )
        pct = max(0, min(100, round(pct)))
        rows.append((ts, controller_id, pct, door_open[i]))
    return rows


# ---------- DB lookups / upserts -------------------------------------------


async def _get_gateway_id(conn: asyncpg.Connection, device_key: str) -> int:
    row = await conn.fetchrow(
        "SELECT id FROM gateways WHERE device_key = $1", device_key
    )
    if row is None:
        print(
            f"Error: no gateway with device_key={device_key!r}. "
            "Create it via the admin UI first.",
            file=sys.stderr,
        )
        sys.exit(2)
    return row["id"]


async def _get_or_create_controller(
    conn: asyncpg.Connection,
    gateway_id: int,
    sn: str,
    name_for_new: str,
) -> tuple[int, bool]:
    """Return (controller_id, created)."""
    existing = await conn.fetchrow(
        "SELECT id FROM controllers WHERE gateway_id = $1 AND sn = $2",
        gateway_id,
        sn,
    )
    if existing:
        return existing["id"], False
    new_id = await conn.fetchval(
        """
        INSERT INTO controllers (gateway_id, sn, name)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        gateway_id,
        sn,
        name_for_new,
    )
    return new_id, True


async def _get_or_create_node(
    conn: asyncpg.Connection,
    controller_id: int,
    node_index: int,
    has_lux: bool,
) -> tuple[int, bool]:
    """Return (node_id, created). has_lux only applied to newly-inserted rows."""
    existing = await conn.fetchrow(
        "SELECT id FROM nodes WHERE controller_id = $1 AND node_index = $2",
        controller_id,
        node_index,
    )
    if existing:
        return existing["id"], False
    new_id = await conn.fetchval(
        """
        INSERT INTO nodes (controller_id, node_index, has_lux)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        controller_id,
        node_index,
        has_lux,
    )
    return new_id, True


# ---------- main ------------------------------------------------------------


async def main() -> None:
    args = parse_args()
    if args.days_back <= 0:
        print("Error: --days-back must be positive", file=sys.stderr)
        sys.exit(1)
    if args.interval_seconds <= 0:
        print("Error: --interval-seconds must be positive", file=sys.stderr)
        sys.exit(1)

    controller_name = (
        args.controller_name or f"Backfill controller {args.controller_sn}"
    )

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days_back)

    # Pre-compute the timestamp grid in memory (one entry per sample). At 1
    # row/min for 180 days that's 259200 timestamps — well under a MB.
    timestamps: list[datetime] = []
    ts = start
    step = timedelta(seconds=args.interval_seconds)
    while ts < end:
        timestamps.append(ts)
        ts += step
    samples_per_node = len(timestamps)
    total_node_rows = samples_per_node * args.node_count
    total_telemetry_rows = samples_per_node

    print("=" * 60)
    print("Backfill plan")
    print(f"  gateway_key:         {args.gateway_key}")
    print(f"  controller_sn:       {args.controller_sn}")
    print(f"  controller_name:     {controller_name}")
    print(f"  node_count:          {args.node_count} (has_lux={args.node_has_lux})")
    print(f"  window:              {start.isoformat()} → {end.isoformat()}")
    print(f"  interval:            {args.interval_seconds}s")
    print(f"  samples per node:    {samples_per_node:,}")
    print(f"  node_readings rows:  {total_node_rows:,}")
    print(f"  telemetry rows:      {total_telemetry_rows:,}")
    print("=" * 60)

    if args.dry_run:
        print("Dry run — exiting without DB connection.")
        return

    conn = await asyncpg.connect(_asyncpg_url())
    try:
        gateway_id = await _get_gateway_id(conn, args.gateway_key)
        print(f"Gateway id = {gateway_id}")

        controller_id, ctl_created = await _get_or_create_controller(
            conn, gateway_id, args.controller_sn, controller_name
        )
        print(
            f"Controller id = {controller_id} "
            f"({'created' if ctl_created else 'reused'})"
        )

        node_ids: list[tuple[int, int]] = []   # (node_index, node_id)
        for idx in range(1, args.node_count + 1):
            nid, n_created = await _get_or_create_node(
                conn, controller_id, idx, args.node_has_lux
            )
            print(
                f"  Node {idx}: id={nid} "
                f"({'created' if n_created else 'reused'})"
            )
            node_ids.append((idx, nid))

        print("Generating door-event schedule…")
        door_events = _generate_door_events(start, end)
        door_open = _build_door_open_map(timestamps, door_events)
        print(f"  {len(door_events):,} door events; "
              f"{sum(door_open):,} minutes door-open")

        # Idempotency wipe — delete anything we're about to replace.
        del_nodes = await conn.execute(
            """
            DELETE FROM node_readings
            WHERE node_id = ANY($1::bigint[])
              AND time >= $2 AND time < $3
            """,
            [nid for _, nid in node_ids],
            start,
            end,
        )
        del_tel = await conn.execute(
            """
            DELETE FROM controller_telemetry
            WHERE controller_id = $1 AND time >= $2 AND time < $3
            """,
            controller_id,
            start,
            end,
        )
        print(f"Deleted: {del_nodes}, {del_tel}")

        # Generate + insert node_readings.
        progress_every = 50_000
        inserted_nodes = 0
        for node_index, node_id in node_ids:
            print(f"Generating readings for node {node_index} (id={node_id})…")
            rows = _generate_node_readings(
                timestamps,
                node_id=node_id,
                node_index=node_index,
                node_count=args.node_count,
                has_lux=args.node_has_lux,
                door_open=door_open,
            )
            for off in range(0, len(rows), args.batch_size):
                chunk = rows[off : off + args.batch_size]
                await conn.copy_records_to_table(
                    "node_readings",
                    records=chunk,
                    columns=("time", "node_id", "temperature", "lux", "err"),
                )
                inserted_nodes += len(chunk)
                if inserted_nodes % progress_every < args.batch_size:
                    print(f"  node_readings: {inserted_nodes:,} / {total_node_rows:,}")

        # Generate + insert controller_telemetry.
        print("Generating controller telemetry…")
        telemetry_rows = _generate_telemetry(timestamps, controller_id, door_open)
        inserted_tel = 0
        for off in range(0, len(telemetry_rows), args.batch_size):
            chunk = telemetry_rows[off : off + args.batch_size]
            await conn.copy_records_to_table(
                "controller_telemetry",
                records=chunk,
                columns=("time", "controller_id", "battery_pct", "door_open"),
            )
            inserted_tel += len(chunk)
            if inserted_tel % progress_every < args.batch_size:
                print(
                    f"  controller_telemetry: "
                    f"{inserted_tel:,} / {total_telemetry_rows:,}"
                )

        # Last-seen bookkeeping — use the final sampled minute.
        last_time = timestamps[-1]
        await conn.execute(
            "UPDATE controllers SET last_seen_at = $1 WHERE id = $2",
            last_time,
            controller_id,
        )
        await conn.execute(
            "UPDATE nodes SET last_seen_at = $1 WHERE controller_id = $2",
            last_time,
            controller_id,
        )

        # ---- post-insert validation ----
        print()
        print("=" * 60)
        print("Validation")
        for node_index, node_id in node_ids:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n, MIN(time) AS t_min, MAX(time) AS t_max
                FROM node_readings WHERE node_id = $1
                """,
                node_id,
            )
            print(
                f"  node {node_index} (id={node_id}): "
                f"{row['n']:,} rows, {row['t_min']} → {row['t_max']}"
            )
        tel_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n, MIN(time) AS t_min, MAX(time) AS t_max
            FROM controller_telemetry WHERE controller_id = $1
            """,
            controller_id,
        )
        print(
            f"  telemetry: {tel_row['n']:,} rows, "
            f"{tel_row['t_min']} → {tel_row['t_max']}"
        )

        # Compression-eligible chunks (> 7 days old). The compression policy
        # job will eventually pick them up.
        nr_chunks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM timescaledb_information.chunks
            WHERE hypertable_name = 'node_readings'
              AND range_end < now() - INTERVAL '7 days'
            """
        )
        ct_chunks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM timescaledb_information.chunks
            WHERE hypertable_name = 'controller_telemetry'
              AND range_end < now() - INTERVAL '7 days'
            """
        )
        print(f"  compression-eligible chunks: "
              f"node_readings={nr_chunks}, controller_telemetry={ct_chunks}")
        print("=" * 60)
        print("Backfill complete.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
