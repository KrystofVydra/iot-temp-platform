"""User-facing controller endpoints — ``/controllers/*``.

The dashboard's primary unit is the *controller* (e.g. one fridge): a list
of controllers the user owns (via their gateways), a detail page with
nodes + latest reading + latest battery/door, and bucketed history.

Several helpers in this module (``_fetch_controller_readings``,
``_fetch_controller_telemetry``, ``_build_controller_detail``,
``_parse_bucket``) are imported by ``routers/admin.py`` so the admin
parallels can reuse the same SQL without duplicating it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_db
from ..models import Controller, ControllerTelemetry, Gateway, Node, User
from ..schemas import (
    ControllerDetailOut,
    ControllerLatest,
    ControllerOut,
    GatewayBrief,
    GatewayBriefDetail,
    LatestTelemetry,
    NodeLatest,
    NodeOut,
    ReadingsPointOut,
    TelemetryPointOut,
)

router = APIRouter(prefix="/controllers", tags=["controllers"])


# ---------------------------------------------------------------------------
# Shared helpers (also used by routers/admin.py)
# ---------------------------------------------------------------------------

_BUCKET_PATTERN = re.compile(r"^(\d+)([mhd])$")
_BUCKET_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


def _parse_bucket(bucket: str) -> str:
    """Validate the bucket arg and return a PostgreSQL interval literal."""
    match = _BUCKET_PATTERN.fullmatch(bucket)
    if match is None:
        raise HTTPException(
            status_code=400,
            detail="`bucket` must match \\d+[mhd] (e.g. 1m, 15m, 1h, 1d)",
        )
    n, unit = match.group(1), match.group(2)
    return f"{n} {_BUCKET_UNITS[unit]}"


async def _user_owns_controller(
    db: AsyncSession, user_id: int, controller_id: int
) -> bool:
    """Return True iff the controller's gateway is owned by user_id."""
    stmt = (
        select(Controller.id)
        .join(Gateway, Controller.gateway_id == Gateway.id)
        .where(Controller.id == controller_id, Gateway.user_id == user_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _build_controller_detail(
    db: AsyncSession, controller_id: int
) -> ControllerDetailOut:
    """Build the detail-shape response for a controller (no ownership check)."""
    row = (
        await db.execute(
            select(Controller, Gateway)
            .join(Gateway, Controller.gateway_id == Gateway.id)
            .where(Controller.id == controller_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    controller, gateway = row

    nodes = (
        (
            await db.execute(
                select(Node)
                .where(Node.controller_id == controller_id)
                .order_by(Node.node_index.asc())
            )
        )
        .scalars()
        .all()
    )

    # Latest reading per node — one DISTINCT ON query rather than N per node.
    latest_per_node: dict[int, sa.Row] = {}
    if nodes:
        latest_sql = text(
            """
            SELECT DISTINCT ON (node_id)
                   node_id, time, temperature, lux, err
            FROM node_readings
            WHERE node_id = ANY(:nids)
            ORDER BY node_id, time DESC
            """
        )
        for r in (
            await db.execute(latest_sql, {"nids": [n.id for n in nodes]})
        ).all():
            latest_per_node[r.node_id] = r

    tlm = (
        await db.execute(
            select(ControllerTelemetry)
            .where(ControllerTelemetry.controller_id == controller_id)
            .order_by(ControllerTelemetry.time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    node_outs: list[NodeOut] = []
    for n in nodes:
        lr = latest_per_node.get(n.id)
        if lr is not None:
            latest = NodeLatest(
                time=lr.time,
                temperature=lr.temperature,
                lux=lr.lux,
                err=lr.err,
            )
        else:
            latest = NodeLatest(time=None, temperature=None, lux=None, err=None)
        node_outs.append(
            NodeOut(
                id=n.id,
                node_index=n.node_index,
                name=n.name,
                has_lux=n.has_lux,
                last_seen_at=n.last_seen_at,
                latest=latest,
            )
        )

    return ControllerDetailOut(
        id=controller.id,
        sn=controller.sn,
        name=controller.name,
        location=controller.location,
        gateway=GatewayBriefDetail(
            id=gateway.id,
            device_key=gateway.device_key,
            name=gateway.name,
            location=gateway.location,
        ),
        nodes=node_outs,
        latest_telemetry=LatestTelemetry(
            time=tlm.time if tlm is not None else None,
            battery_pct=tlm.battery_pct if tlm is not None else None,
            door_open=tlm.door_open if tlm is not None else None,
        ),
    )


async def _fetch_controller_readings(
    db: AsyncSession,
    controller_id: int,
    from_: datetime,
    to: datetime,
    bucket: str | None,
    limit: int,
) -> list[ReadingsPointOut]:
    """Averaged temperature series across the controller's nodes.

    No ownership check — caller does that. Raw mode groups by exact time
    (rare collisions across nodes). Bucketed mode uses TimescaleDB's
    ``time_bucket``.
    """
    if to <= from_:
        raise HTTPException(status_code=400, detail="`to` must be greater than `from`")

    if bucket is None:
        sql = text(
            """
            SELECT nr.time AS time,
                   AVG(nr.temperature)::REAL AS temperature_avg
            FROM node_readings nr
            JOIN nodes n ON n.id = nr.node_id
            WHERE n.controller_id = :cid
              AND nr.time >= :from_time AND nr.time < :to_time
            GROUP BY nr.time
            ORDER BY nr.time ASC
            LIMIT :limit
            """
        )
    else:
        interval_str = _parse_bucket(bucket)
        sql = text(
            f"""
            SELECT time_bucket('{interval_str}'::interval, nr.time) AS time,
                   AVG(nr.temperature)::REAL AS temperature_avg
            FROM node_readings nr
            JOIN nodes n ON n.id = nr.node_id
            WHERE n.controller_id = :cid
              AND nr.time >= :from_time AND nr.time < :to_time
            GROUP BY time
            ORDER BY time ASC
            LIMIT :limit
            """
        )

    result = await db.execute(
        sql,
        {
            "cid": controller_id,
            "from_time": from_,
            "to_time": to,
            "limit": limit,
        },
    )
    return [
        ReadingsPointOut(time=row.time, temperature_avg=row.temperature_avg)
        for row in result
    ]


async def _fetch_controller_telemetry(
    db: AsyncSession,
    controller_id: int,
    from_: datetime,
    to: datetime,
    bucket: str | None,
    limit: int,
) -> list[TelemetryPointOut]:
    """Battery + door state series for the controller.

    No ownership check — caller does that. Bucketed mode averages
    ``battery_pct`` (rounded to int — the column is already a 0..100
    integer percentage) and uses TimescaleDB's ``last(door_open, time)``
    for door state (the meaningful aggregate — the bucket's last known
    door state).
    """
    if to <= from_:
        raise HTTPException(status_code=400, detail="`to` must be greater than `from`")

    if bucket is None:
        sql = text(
            """
            SELECT time, battery_pct, door_open
            FROM controller_telemetry
            WHERE controller_id = :cid
              AND time >= :from_time AND time < :to_time
            ORDER BY time ASC
            LIMIT :limit
            """
        )
    else:
        interval_str = _parse_bucket(bucket)
        sql = text(
            f"""
            SELECT time_bucket('{interval_str}'::interval, time) AS time,
                   ROUND(AVG(battery_pct))::int AS battery_pct,
                   last(door_open, time) AS door_open
            FROM controller_telemetry
            WHERE controller_id = :cid
              AND time >= :from_time AND time < :to_time
            GROUP BY time
            ORDER BY time ASC
            LIMIT :limit
            """
        )

    result = await db.execute(
        sql,
        {
            "cid": controller_id,
            "from_time": from_,
            "to_time": to,
            "limit": limit,
        },
    )
    return [
        TelemetryPointOut(
            time=row.time, battery_pct=row.battery_pct, door_open=row.door_open
        )
        for row in result
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ControllerOut])
async def list_controllers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ControllerOut]:
    """List controllers owned by the current user (via their gateways).

    Uses 4 queries total: controllers+gateway, node counts, latest reading
    aggregates, latest telemetry. N+1 would be acceptable at our scale; the
    bulk form is just cleaner.
    """
    rows = (
        await db.execute(
            select(Controller, Gateway)
            .join(Gateway, Controller.gateway_id == Gateway.id)
            .where(Gateway.user_id == user.id)
        )
    ).all()
    if not rows:
        return []

    controllers = [(c, g) for c, g in rows]
    cids = [c.id for c, _ in controllers]

    # Node counts per controller.
    nc_rows = (
        await db.execute(
            select(Node.controller_id, sa.func.count(Node.id))
            .where(Node.controller_id.in_(cids))
            .group_by(Node.controller_id)
        )
    ).all()
    node_counts = {row[0]: row[1] for row in nc_rows}

    # Latest reading per node → aggregate per controller in one query.
    reading_sql = text(
        """
        SELECT n.controller_id,
               MAX(lr.time) AS time,
               AVG(lr.temperature)::REAL AS temperature_avg,
               BOOL_OR(lr.err IS NOT NULL) AS any_node_error
        FROM (
            SELECT DISTINCT ON (nr.node_id)
                   nr.node_id, nr.time, nr.temperature, nr.err
            FROM node_readings nr
            JOIN nodes n ON n.id = nr.node_id
            WHERE n.controller_id = ANY(:cids)
            ORDER BY nr.node_id, nr.time DESC
        ) lr
        JOIN nodes n ON n.id = lr.node_id
        GROUP BY n.controller_id
        """
    )
    reading_rows = (await db.execute(reading_sql, {"cids": cids})).all()
    reading_map = {r.controller_id: r for r in reading_rows}

    # Latest telemetry per controller.
    telemetry_sql = text(
        """
        SELECT DISTINCT ON (controller_id)
               controller_id, time, battery_pct, door_open
        FROM controller_telemetry
        WHERE controller_id = ANY(:cids)
        ORDER BY controller_id, time DESC
        """
    )
    telemetry_rows = (await db.execute(telemetry_sql, {"cids": cids})).all()
    telemetry_map = {r.controller_id: r for r in telemetry_rows}

    # Build (ControllerOut, created_at) pairs so we can sort with secondary key.
    pairs: list[tuple[ControllerOut, datetime]] = []
    for c, g in controllers:
        reading = reading_map.get(c.id)
        telemetry = telemetry_map.get(c.id)
        candidates = []
        if reading is not None and reading.time is not None:
            candidates.append(reading.time)
        if telemetry is not None:
            candidates.append(telemetry.time)
        latest_time = max(candidates) if candidates else None

        co = ControllerOut(
            id=c.id,
            sn=c.sn,
            name=c.name,
            location=c.location,
            gateway=GatewayBrief(
                id=g.id, device_key=g.device_key, name=g.name
            ),
            node_count=node_counts.get(c.id, 0),
            last_seen_at=c.last_seen_at,
            latest=ControllerLatest(
                time=latest_time,
                temperature_avg=(
                    reading.temperature_avg if reading is not None else None
                ),
                battery_pct=(
                    telemetry.battery_pct if telemetry is not None else None
                ),
                door_open=telemetry.door_open if telemetry is not None else None,
                any_node_error=(
                    bool(reading.any_node_error) if reading is not None else False
                ),
            ),
        )
        pairs.append((co, c.created_at))

    # latest.time DESC NULLS LAST, then created_at DESC.
    def sort_key(pair: tuple[ControllerOut, datetime]) -> tuple:
        out, created = pair
        t = out.latest.time
        return (
            t is None,
            -t.timestamp() if t is not None else 0.0,
            -created.timestamp(),
        )

    pairs.sort(key=sort_key)
    return [p[0] for p in pairs]


@router.get("/{controller_id}", response_model=ControllerDetailOut)
async def get_controller(
    controller_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ControllerDetailOut:
    if not await _user_owns_controller(db, user.id, controller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    return await _build_controller_detail(db, controller_id)


@router.get(
    "/{controller_id}/readings", response_model=list[ReadingsPointOut]
)
async def get_controller_readings(
    controller_id: int,
    from_: datetime = Query(..., alias="from"),
    to: datetime | None = Query(default=None),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReadingsPointOut]:
    if not await _user_owns_controller(db, user.id, controller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    return await _fetch_controller_readings(
        db, controller_id, from_, to or datetime.now(UTC), bucket, limit
    )


@router.get(
    "/{controller_id}/telemetry", response_model=list[TelemetryPointOut]
)
async def get_controller_telemetry(
    controller_id: int,
    from_: datetime = Query(..., alias="from"),
    to: datetime | None = Query(default=None),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TelemetryPointOut]:
    if not await _user_owns_controller(db, user.id, controller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "controller not found")
    return await _fetch_controller_telemetry(
        db, controller_id, from_, to or datetime.now(UTC), bucket, limit
    )
