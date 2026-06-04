"""Device + reading endpoints, scoped to the current user.

Every endpoint resolves the caller via the session cookie (``get_current_user``)
and refuses to return devices belonging to anyone else. A 404 is returned
for "device id exists but isn't yours" as well as "device id doesn't exist"
so callers can't enumerate other users' device ids.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_db
from ..models import Device, Reading, User
from ..schemas import DeviceOut, DeviceWithLatestReading, ReadingOut, reading_to_out

router = APIRouter(prefix="/devices", tags=["devices"])

_BUCKET_PATTERN = re.compile(r"^(\d+)([smhd])$")
_BUCKET_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


async def _get_device_or_404(
    db: AsyncSession, device_id: int, user_id: int
) -> Device:
    """Return the device only if it exists AND is owned by user_id."""
    stmt = select(Device).where(Device.id == device_id, Device.user_id == user_id)
    device = (await db.execute(stmt)).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    return device


async def _latest_reading(db: AsyncSession, device_id: int) -> Reading | None:
    stmt = (
        select(Reading)
        .where(Reading.device_id == device_id)
        .order_by(Reading.time.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=list[DeviceWithLatestReading])
async def list_devices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceWithLatestReading]:
    devices = (
        await db.execute(select(Device).where(Device.user_id == user.id).order_by(Device.id))
    ).scalars().all()
    out: list[DeviceWithLatestReading] = []
    for device in devices:
        latest = await _latest_reading(db, device.id)
        out.append(
            DeviceWithLatestReading(
                device=DeviceOut.model_validate(device),
                latest=reading_to_out(latest) if latest is not None else None,
            )
        )
    return out


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceOut:
    device = await _get_device_or_404(db, device_id, user.id)
    return DeviceOut.model_validate(device)


@router.get(
    "/{device_id}/readings/latest",
    response_model=ReadingOut,
    responses={204: {"description": "device has no readings yet"}},
)
async def get_latest_reading(
    device_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingOut | Response:
    await _get_device_or_404(db, device_id, user.id)
    latest = await _latest_reading(db, device_id)
    if latest is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return reading_to_out(latest)


@router.get("/{device_id}/readings", response_model=list[ReadingOut])
async def get_device_readings(
    device_id: int,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReadingOut]:
    await _get_device_or_404(db, device_id, user.id)
    return await _fetch_readings(db, device_id, from_, to, bucket, limit)


async def _fetch_readings(
    db: AsyncSession,
    device_id: int,
    from_: datetime,
    to: datetime,
    bucket: str | None,
    limit: int,
) -> list[ReadingOut]:
    """Shared readings fetch used by both /devices and /admin/devices routers.

    Does NOT check ownership — the caller does. Encapsulates the from/to
    range check, raw vs bucketed branch, and the time_bucket SQL.
    """
    if to <= from_:
        raise HTTPException(status_code=400, detail="`to` must be greater than `from`")

    if bucket is None:
        stmt = (
            select(Reading)
            .where(
                Reading.device_id == device_id,
                Reading.time >= from_,
                Reading.time < to,
            )
            .order_by(Reading.time.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [reading_to_out(r) for r in rows]

    match = _BUCKET_PATTERN.fullmatch(bucket)
    if match is None:
        raise HTTPException(
            status_code=400,
            detail="`bucket` must match \\d+[smhd] (e.g. 1m, 15m, 1h, 1d)",
        )
    n, unit = match.group(1), match.group(2)
    interval_str = f"{n} {_BUCKET_UNITS[unit]}"

    # interval_str is already regex-validated above and mapped through
    # _BUCKET_UNITS, so it's safe to f-string into the SQL. Binding it as
    # :bucket doesn't work because SQLAlchemy's parser mis-handles the
    # adjacent `::interval` cast.
    sql = text(
        f"""
        SELECT time_bucket('{interval_str}'::interval, time) AS bucket_time,
               AVG(temperature)::REAL AS temperature,
               AVG(lux)::INTEGER AS lux,
               AVG(battery_raw)::INTEGER AS battery_raw,
               AVG(rssi)::SMALLINT AS rssi
        FROM readings
        WHERE device_id = :device_id AND time >= :from_time AND time < :to_time
        GROUP BY bucket_time
        ORDER BY bucket_time ASC
        LIMIT :limit
        """
    )
    result = await db.execute(
        sql,
        {
            "device_id": device_id,
            "from_time": from_,
            "to_time": to,
            "limit": limit,
        },
    )
    return [
        ReadingOut(
            time=row.bucket_time,
            temperature=row.temperature,
            lux=row.lux,
            battery_raw=row.battery_raw,
            battery_v=row.battery_raw / 1000.0 if row.battery_raw is not None else None,
            rssi=row.rssi,
        )
        for row in result
    ]
