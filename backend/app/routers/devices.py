"""Device + reading endpoints. All routes require a valid bearer token."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_api_token
from ..db import get_db
from ..models import Device, Reading
from ..schemas import DeviceOut, DeviceWithLatestReading, ReadingOut, reading_to_out

router = APIRouter(
    prefix="/devices",
    tags=["devices"],
    dependencies=[Depends(require_api_token)],
)

_BUCKET_PATTERN = re.compile(r"^(\d+)([smhd])$")
_BUCKET_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


async def _get_device_or_404(session: AsyncSession, device_id: int) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    return device


async def _latest_reading(session: AsyncSession, device_id: int) -> Reading | None:
    stmt = (
        select(Reading)
        .where(Reading.device_id == device_id)
        .order_by(Reading.time.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=list[DeviceWithLatestReading])
async def list_devices(
    session: AsyncSession = Depends(get_db),
) -> list[DeviceWithLatestReading]:
    devices = (await session.execute(select(Device).order_by(Device.id))).scalars().all()
    out: list[DeviceWithLatestReading] = []
    for device in devices:
        latest = await _latest_reading(session, device.id)
        out.append(
            DeviceWithLatestReading(
                device=DeviceOut.model_validate(device),
                latest=reading_to_out(latest) if latest is not None else None,
            )
        )
    return out


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, session: AsyncSession = Depends(get_db)) -> DeviceOut:
    device = await _get_device_or_404(session, device_id)
    return DeviceOut.model_validate(device)


@router.get(
    "/{device_id}/readings/latest",
    response_model=ReadingOut,
    responses={204: {"description": "device has no readings yet"}},
)
async def get_latest_reading(
    device_id: int, session: AsyncSession = Depends(get_db)
) -> ReadingOut | Response:
    await _get_device_or_404(session, device_id)
    latest = await _latest_reading(session, device_id)
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
    session: AsyncSession = Depends(get_db),
) -> list[ReadingOut]:
    if to <= from_:
        raise HTTPException(status_code=400, detail="`to` must be greater than `from`")

    await _get_device_or_404(session, device_id)

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
        rows = (await session.execute(stmt)).scalars().all()
        return [reading_to_out(r) for r in rows]

    match = _BUCKET_PATTERN.fullmatch(bucket)
    if match is None:
        raise HTTPException(
            status_code=400,
            detail="`bucket` must match \\d+[smhd] (e.g. 1m, 15m, 1h, 1d)",
        )
    n, unit = match.group(1), match.group(2)
    interval_str = f"{n} {_BUCKET_UNITS[unit]}"

    # interval_str is already validated by the regex above and mapped through
    # _BUCKET_UNITS, so it's safe to interpolate as a SQL literal. Binding it
    # as :bucket doesn't work because SQLAlchemy's parser mis-handles the
    # adjacent `::interval` cast (sees `:bucket::interval` as one token).
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
    result = await session.execute(
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
