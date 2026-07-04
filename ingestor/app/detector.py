"""Notification detector — Round 4 Phase 4B.

Two evaluation paths populate the ``notifications`` table:

* :func:`evaluate_value_based` runs after each MQTT message is committed.
  It looks at the freshly-stored reading for one controller / one node and
  opens or resolves all of the per-message kinds (temp_safe,
  temp_preferred, temp_drift, battery_critical, battery_low,
  node_error_single, node_error_cumulative).

* :func:`evaluate_time_based` runs on a 30-second tick. It scans for
  stale conditions that have nothing to do with any single message —
  gateways and controllers that stopped reporting, doors that have been
  open too long, multi-controller outages, and drift notifications that
  should auto-resolve after their window passes.

The two paths share the same ``notifications`` table and the dedup key
``(user_id, kind, gateway_id, controller_id, node_id) WHERE resolved_at
IS NULL``. Inhibition handling (e.g. don't fire temp_preferred when
temp_safe is already firing on the same controller) is done by
re-evaluating the lower-severity kind right after the higher-severity
state changes.

The module deliberately *never* raises out to its callers; the
``_handle_message`` MQTT path and the time-based loop both wrap calls in
``try/except`` so a buggy detector cannot stop ingestion. Errors are
logged at ``log.exception`` for triage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Controller,
    Gateway,
    Node,
    Notification,
    NotificationKindDefault,
    NotificationSetting,
)
from .schemas import IncomingTelemetry

log = logging.getLogger("ingestor.detector")


# ---------------------------------------------------------------------------
# Defaults (mirror what the alembic seed inserts; used when a row in
# notification_kind_defaults is somehow missing a key the detector needs).
# ---------------------------------------------------------------------------

_KIND_DEFAULTS: dict[str, dict[str, float]] = {
    "temp_safe": {"safe_min": 2.0, "safe_max": 6.0},
    "temp_preferred": {"preferred_min": 3.0, "preferred_max": 5.0},
    "temp_drift": {"drift_c": 3.0, "drift_minutes": 10},
    "door_open": {"max_open_minutes": 5},
    "controller_offline": {"offline_minutes": 5},
    "gateway_offline": {"offline_minutes": 5},
    "battery_critical": {"critical_pct": 10},
    "battery_low": {"low_pct": 25},
}

# Inside-band buffer for resolve hysteresis on the temperature kinds.
_TEMP_HYSTERESIS_C = 0.5
# % buffer for battery hysteresis above the trip threshold before we resolve.
_BATTERY_HYSTERESIS_PCT = 5


# ---------------------------------------------------------------------------
# Settings cache (per-evaluation snapshot)
# ---------------------------------------------------------------------------


@dataclass
class _MergedSetting:
    """A per-user per-kind row with thresholds merged from defaults.

    The user's stored thresholds win; any missing key falls back to the
    seeded default. Disabled kinds are still represented — callers gate on
    ``enabled`` themselves.
    """

    kind: str
    enabled: bool
    severity: str
    scope: str
    thresholds: dict[str, float] = field(default_factory=dict)


async def get_user_settings(
    session: AsyncSession, user_id: int
) -> dict[str, _MergedSetting]:
    """Load one user's settings keyed by kind, defaults merged in."""
    rows = (
        await session.execute(
            select(NotificationSetting, NotificationKindDefault)
            .join(
                NotificationKindDefault,
                NotificationKindDefault.kind == NotificationSetting.kind,
            )
            .where(NotificationSetting.user_id == user_id)
        )
    ).all()
    out: dict[str, _MergedSetting] = {}
    for ns, kd in rows:
        defaults = dict(kd.thresholds or {})
        merged = {**defaults, **(ns.thresholds or {})}
        out[ns.kind] = _MergedSetting(
            kind=ns.kind,
            enabled=ns.enabled,
            severity=kd.severity,
            scope=kd.scope,
            thresholds=merged,
        )
    return out


def get_threshold(setting: _MergedSetting, key: str, default: float) -> float:
    """Read a threshold from a merged setting; fall back if absent or bad."""
    raw = setting.thresholds.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


# ---------------------------------------------------------------------------
# Notification row I/O
# ---------------------------------------------------------------------------


async def find_active_notification(
    session: AsyncSession,
    user_id: int,
    kind: str,
    *,
    gateway_id: int | None = None,
    controller_id: int | None = None,
    node_id: int | None = None,
) -> Notification | None:
    """Look up an unresolved notification matching the deepest scope entity provided.

    Resolution order: node_id > controller_id > gateway_id. We match on the
    deepest entity given; upper-level FKs are not constrained because
    open_notification populates them for context but they're not part of
    the notification's identity.

    If multiple actives exist (e.g. duplicates from a past bug or a race),
    keep the OLDEST and silently resolve the rest as duplicate cleanup so
    the caller always sees at most one row.
    """
    stmt = select(Notification).where(
        Notification.user_id == user_id,
        Notification.kind == kind,
        Notification.resolved_at.is_(None),
    )
    if node_id is not None:
        stmt = stmt.where(Notification.node_id == node_id)
    elif controller_id is not None:
        stmt = stmt.where(Notification.controller_id == controller_id)
    elif gateway_id is not None:
        stmt = stmt.where(Notification.gateway_id == gateway_id)
    stmt = stmt.order_by(Notification.opened_at.asc())
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    # Multiple actives — keep the oldest, resolve the rest as duplicates.
    canonical = rows[0]
    extras = rows[1:]
    log.warning(
        "found %d duplicate active notifications for kind=%s user=%s "
        "(gateway=%s controller=%s node=%s); resolving %d extras as duplicate cleanup",
        len(rows),
        kind,
        user_id,
        gateway_id,
        controller_id,
        node_id,
        len(extras),
    )
    now = datetime.now(UTC)
    for extra in extras:
        extra.resolved_at = now
    await session.flush()
    return canonical


async def open_notification(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    severity: str,
    scope: str,
    subject_name: str | None,
    details: dict[str, Any],
    gateway_id: int | None = None,
    controller_id: int | None = None,
    node_id: int | None = None,
) -> Notification:
    """Insert a new active notification. Caller is responsible for the
    no-duplicate-active invariant — call :func:`find_active_notification`
    first."""
    row = Notification(
        user_id=user_id,
        kind=kind,
        severity=severity,
        scope=scope,
        gateway_id=gateway_id,
        controller_id=controller_id,
        node_id=node_id,
        subject_name=subject_name,
        details=details,
    )
    session.add(row)
    await session.flush()
    log.info(
        "opened notification kind=%s user=%s gateway=%s controller=%s node=%s details=%s",
        kind,
        user_id,
        gateway_id,
        controller_id,
        node_id,
        details,
    )
    # Fire push notification (best-effort, never blocks the notification flow)
    try:
        from .push import send_push_for_notification

        await send_push_for_notification(session, row, event="opened")
    except Exception:
        log.exception("push send failed for opened notification id=%s", row.id)
    return row


async def resolve_notification(
    session: AsyncSession, notification: Notification, now: datetime
) -> None:
    """Stamp ``resolved_at`` on an existing active notification."""
    notification.resolved_at = now
    await session.flush()
    log.info(
        "resolved notification id=%s kind=%s user=%s controller=%s",
        notification.id,
        notification.kind,
        notification.user_id,
        notification.controller_id,
    )
    # Fire push notification (best-effort, never blocks the notification flow)
    try:
        from .push import send_push_for_notification

        await send_push_for_notification(session, notification, event="resolved")
    except Exception:
        log.exception(
            "push send failed for resolved notification id=%s", notification.id
        )


# ---------------------------------------------------------------------------
# State helpers (queries against just-committed data)
# ---------------------------------------------------------------------------


async def _latest_temp_avg(session: AsyncSession, controller_id: int) -> float | None:
    """Average of latest temperature across all nodes on this controller.

    Considers the just-inserted row(s) — caller commits before invoking.
    Excludes nodes whose latest reading has no temperature (e.g. err).
    """
    result = await session.execute(
        text(
            """
            SELECT AVG(lr.temperature)::float AS avg_temp
            FROM (
                SELECT DISTINCT ON (nr.node_id)
                       nr.node_id, nr.temperature
                FROM node_readings nr
                JOIN nodes n ON n.id = nr.node_id
                WHERE n.controller_id = :cid
                ORDER BY nr.node_id, nr.time DESC
            ) lr
            WHERE lr.temperature IS NOT NULL
            """
        ),
        {"cid": controller_id},
    )
    row = result.first()
    return row.avg_temp if row else None


async def _temp_avg_at(
    session: AsyncSession, controller_id: int, target: datetime
) -> float | None:
    """Average temperature across all nodes ~at the given time.

    "At" means: for each node, the last reading at-or-before ``target``.
    """
    result = await session.execute(
        text(
            """
            SELECT AVG(lr.temperature)::float AS avg_temp
            FROM (
                SELECT DISTINCT ON (nr.node_id)
                       nr.node_id, nr.temperature
                FROM node_readings nr
                JOIN nodes n ON n.id = nr.node_id
                WHERE n.controller_id = :cid
                  AND nr.time <= :target
                ORDER BY nr.node_id, nr.time DESC
            ) lr
            WHERE lr.temperature IS NOT NULL
            """
        ),
        {"cid": controller_id, "target": target},
    )
    row = result.first()
    return row.avg_temp if row else None


async def _latest_node_errs(
    session: AsyncSession, controller_id: int
) -> dict[int, tuple[int, str]]:
    """Return ``{node_id: (node_index, err)}`` for nodes whose latest reading is errored."""
    rows = (
        await session.execute(
            text(
                """
                SELECT lr.node_id, n.node_index, lr.err
                FROM (
                    SELECT DISTINCT ON (nr.node_id)
                           nr.node_id, nr.err
                    FROM node_readings nr
                    JOIN nodes n ON n.id = nr.node_id
                    WHERE n.controller_id = :cid
                    ORDER BY nr.node_id, nr.time DESC
                ) lr
                JOIN nodes n ON n.id = lr.node_id
                WHERE lr.err IS NOT NULL
                """
            ),
            {"cid": controller_id},
        )
    ).all()
    return {r.node_id: (r.node_index, r.err) for r in rows}


# ---------------------------------------------------------------------------
# Value-based evaluation
# ---------------------------------------------------------------------------


_ERR_LABEL = {
    "sensor_lux": "Lux sensor",
    "sensor_temp": "Temp sensor",
    "sensor_both": "Both sensors",
    "comms": "Comms failure",
}


async def evaluate_value_based(
    session: AsyncSession,
    gateway: Gateway,
    controller: Controller,
    node: Node,
    payload: IncomingTelemetry,
    now: datetime,
) -> None:
    """Per-message detector — runs after a successful insert."""
    user_id = gateway.user_id
    settings = await get_user_settings(session, user_id)

    state = await _gather_value_state(session, controller, payload)
    log.debug(
        "value-state controller=%s temp_avg=%s battery=%s door=%s errs=%s",
        controller.id,
        state.temp_avg,
        state.battery_pct,
        state.door_open,
        list(state.node_errs),
    )

    # Temperature pair: safe first (it inhibits preferred).
    await _eval_temp_safe(session, settings, controller, state, now, user_id)
    await _eval_temp_preferred(session, settings, controller, state, now, user_id)
    await _eval_temp_drift(session, settings, controller, state, now, user_id)

    # Battery: critical inhibits low.
    await _eval_battery(session, settings, controller, state, now, user_id)

    # Node errors: cumulative inhibits single.
    await _eval_node_errors(session, settings, controller, state, now, user_id)


@dataclass
class _ValueState:
    """Snapshot of the just-committed view of a controller."""

    temp_avg: float | None
    battery_pct: int | None
    door_open: bool | None
    # node_id -> (node_index, err)
    node_errs: dict[int, tuple[int, str]] = field(default_factory=dict)


async def _gather_value_state(
    session: AsyncSession, controller: Controller, payload: IncomingTelemetry
) -> _ValueState:
    return _ValueState(
        temp_avg=await _latest_temp_avg(session, controller.id),
        battery_pct=payload.b,
        door_open=(payload.d == 1),
        node_errs=await _latest_node_errs(session, controller.id),
    )


async def _eval_temp_safe(
    session: AsyncSession,
    settings: dict[str, _MergedSetting],
    controller: Controller,
    state: _ValueState,
    now: datetime,
    user_id: int,
) -> None:
    setting = settings.get("temp_safe")
    if setting is None or not setting.enabled or state.temp_avg is None:
        return
    safe_min = get_threshold(setting, "safe_min", 2.0)
    safe_max = get_threshold(setting, "safe_max", 6.0)
    temp = state.temp_avg
    active = await find_active_notification(
        session, user_id, "temp_safe", controller_id=controller.id
    )

    if active is None:
        if temp < safe_min or temp > safe_max:
            direction = "below" if temp < safe_min else "above"
            await open_notification(
                session,
                user_id=user_id,
                kind="temp_safe",
                severity=setting.severity,
                scope=setting.scope,
                subject_name=controller.name,
                details={
                    "observed": round(temp, 2),
                    "threshold_min": safe_min,
                    "threshold_max": safe_max,
                    "direction": direction,
                },
                gateway_id=controller.gateway_id,
                controller_id=controller.id,
            )
            # Inhibition: an active temp_preferred is now redundant — resolve it.
            inhibited = await find_active_notification(
                session, user_id, "temp_preferred", controller_id=controller.id
            )
            if inhibited is not None:
                await resolve_notification(session, inhibited, now)
    else:
        # Hysteresis — only resolve when comfortably inside the band.
        if safe_min + _TEMP_HYSTERESIS_C <= temp <= safe_max - _TEMP_HYSTERESIS_C:
            await resolve_notification(session, active, now)


async def _eval_temp_preferred(
    session: AsyncSession,
    settings: dict[str, _MergedSetting],
    controller: Controller,
    state: _ValueState,
    now: datetime,
    user_id: int,
) -> None:
    setting = settings.get("temp_preferred")
    if setting is None or not setting.enabled or state.temp_avg is None:
        return
    preferred_min = get_threshold(setting, "preferred_min", 3.0)
    preferred_max = get_threshold(setting, "preferred_max", 5.0)
    temp = state.temp_avg

    # Inhibition: if temp_safe just fired (or is currently active), don't open
    # preferred alongside it.
    safe_active = (
        await find_active_notification(
            session, user_id, "temp_safe", controller_id=controller.id
        )
        is not None
    )
    active = await find_active_notification(
        session, user_id, "temp_preferred", controller_id=controller.id
    )

    if safe_active:
        if active is not None:
            await resolve_notification(session, active, now)
        return

    if active is None:
        if temp < preferred_min or temp > preferred_max:
            direction = "below" if temp < preferred_min else "above"
            await open_notification(
                session,
                user_id=user_id,
                kind="temp_preferred",
                severity=setting.severity,
                scope=setting.scope,
                subject_name=controller.name,
                details={
                    "observed": round(temp, 2),
                    "threshold_min": preferred_min,
                    "threshold_max": preferred_max,
                    "direction": direction,
                },
                gateway_id=controller.gateway_id,
                controller_id=controller.id,
            )
    else:
        if (
            preferred_min + _TEMP_HYSTERESIS_C
            <= temp
            <= preferred_max - _TEMP_HYSTERESIS_C
        ):
            await resolve_notification(session, active, now)


async def _eval_temp_drift(
    session: AsyncSession,
    settings: dict[str, _MergedSetting],
    controller: Controller,
    state: _ValueState,
    now: datetime,
    user_id: int,
) -> None:
    """One-shot drift detection. Auto-resolution happens in the time-based pass."""
    setting = settings.get("temp_drift")
    if setting is None or not setting.enabled or state.temp_avg is None:
        return
    drift_c = get_threshold(setting, "drift_c", 3.0)
    drift_minutes = int(get_threshold(setting, "drift_minutes", 10))
    if drift_minutes <= 0:
        return
    back_time = now - timedelta(minutes=drift_minutes)

    previous = await _temp_avg_at(session, controller.id, back_time)
    if previous is None:
        return  # no historical reference

    delta = state.temp_avg - previous
    if abs(delta) < drift_c:
        return

    # Don't re-open if a drift notification was opened within the window.
    window_cutoff = now - timedelta(minutes=drift_minutes)
    recent = (
        await session.execute(
            select(Notification.id)
            .where(
                Notification.user_id == user_id,
                Notification.kind == "temp_drift",
                Notification.controller_id == controller.id,
                Notification.opened_at >= window_cutoff,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None:
        return

    await open_notification(
        session,
        user_id=user_id,
        kind="temp_drift",
        severity=setting.severity,
        scope=setting.scope,
        subject_name=controller.name,
        details={
            "current": round(state.temp_avg, 2),
            "previous": round(previous, 2),
            "delta": round(delta, 2),
            "delta_c": round(delta, 2),
            "window_minutes": drift_minutes,
            "drift_minutes": drift_minutes,
        },
        gateway_id=controller.gateway_id,
        controller_id=controller.id,
    )


async def _eval_battery(
    session: AsyncSession,
    settings: dict[str, _MergedSetting],
    controller: Controller,
    state: _ValueState,
    now: datetime,
    user_id: int,
) -> None:
    if state.battery_pct is None:
        return

    crit_setting = settings.get("battery_critical")
    low_setting = settings.get("battery_low")
    crit_pct = (
        int(get_threshold(crit_setting, "critical_pct", 10))
        if crit_setting is not None
        else 10
    )
    low_pct = (
        int(get_threshold(low_setting, "low_pct", 25))
        if low_setting is not None
        else 25
    )
    observed = state.battery_pct

    # Critical first.
    if crit_setting is not None and crit_setting.enabled:
        active = await find_active_notification(
            session, user_id, "battery_critical", controller_id=controller.id
        )
        if active is None:
            if observed < crit_pct:
                await open_notification(
                    session,
                    user_id=user_id,
                    kind="battery_critical",
                    severity=crit_setting.severity,
                    scope=crit_setting.scope,
                    subject_name=controller.name,
                    details={
                        "observed_pct": observed,
                        "threshold_pct": crit_pct,
                    },
                    gateway_id=controller.gateway_id,
                    controller_id=controller.id,
                )
                # Inhibit any active battery_low.
                inhibited = await find_active_notification(
                    session, user_id, "battery_low", controller_id=controller.id
                )
                if inhibited is not None:
                    await resolve_notification(session, inhibited, now)
        elif observed >= crit_pct + _BATTERY_HYSTERESIS_PCT:
            await resolve_notification(session, active, now)

    # Low — only meaningful when critical isn't currently active.
    if low_setting is not None and low_setting.enabled:
        crit_active = await find_active_notification(
            session, user_id, "battery_critical", controller_id=controller.id
        )
        active = await find_active_notification(
            session, user_id, "battery_low", controller_id=controller.id
        )
        if crit_active is not None:
            # Critical already covers this controller; suppress / resolve low.
            if active is not None:
                await resolve_notification(session, active, now)
            return
        if active is None:
            if crit_pct <= observed < low_pct:
                await open_notification(
                    session,
                    user_id=user_id,
                    kind="battery_low",
                    severity=low_setting.severity,
                    scope=low_setting.scope,
                    subject_name=controller.name,
                    details={
                        "observed_pct": observed,
                        "threshold_pct": low_pct,
                    },
                    gateway_id=controller.gateway_id,
                    controller_id=controller.id,
                )
        elif observed >= low_pct + _BATTERY_HYSTERESIS_PCT:
            await resolve_notification(session, active, now)


async def _eval_node_errors(
    session: AsyncSession,
    settings: dict[str, _MergedSetting],
    controller: Controller,
    state: _ValueState,
    now: datetime,
    user_id: int,
) -> None:
    cumul_setting = settings.get("node_error_cumulative")
    single_setting = settings.get("node_error_single")
    errs = state.node_errs
    erroring_count = len(errs)

    # Cumulative — also drives inhibition of the per-node single rows.
    cumul_active = await find_active_notification(
        session, user_id, "node_error_cumulative", controller_id=controller.id
    )
    if cumul_setting is not None and cumul_setting.enabled:
        if erroring_count >= 2:
            if cumul_active is None:
                cumul_active = await open_notification(
                    session,
                    user_id=user_id,
                    kind="node_error_cumulative",
                    severity=cumul_setting.severity,
                    scope=cumul_setting.scope,
                    subject_name=controller.name,
                    details={
                        "erroring_nodes": sorted(errs),
                        "error_count": erroring_count,
                    },
                    gateway_id=controller.gateway_id,
                    controller_id=controller.id,
                )
        elif cumul_active is not None:
            await resolve_notification(session, cumul_active, now)
            cumul_active = None

    # Single — per-node. Loop over all nodes on this controller so we catch
    # both the just-arrived node and any siblings whose state changed via
    # the cumulative inhibition above.
    if single_setting is None or not single_setting.enabled:
        return

    nodes = (
        (
            await session.execute(
                select(Node).where(Node.controller_id == controller.id)
            )
        )
        .scalars()
        .all()
    )
    for n in nodes:
        active = await find_active_notification(
            session,
            user_id,
            "node_error_single",
            controller_id=controller.id,
            node_id=n.id,
        )
        # When cumulative is active, single is inhibited — resolve any open.
        if cumul_active is not None:
            if active is not None:
                await resolve_notification(session, active, now)
            continue

        err_info = errs.get(n.id)
        if err_info is None:
            if active is not None:
                await resolve_notification(session, active, now)
            continue
        # Exactly this node erroring (or cumulative was below threshold) — open.
        if active is None:
            _, err = err_info
            await open_notification(
                session,
                user_id=user_id,
                kind="node_error_single",
                severity=single_setting.severity,
                scope=single_setting.scope,
                subject_name=f"{controller.name} - Node {n.node_index}",
                details={
                    "err": err,
                    "err_label": _ERR_LABEL.get(err, err),
                    "node_index": n.node_index,
                },
                gateway_id=controller.gateway_id,
                controller_id=controller.id,
                node_id=n.id,
            )


# ---------------------------------------------------------------------------
# Time-based evaluation (30-second tick)
# ---------------------------------------------------------------------------


async def evaluate_time_based(session: AsyncSession, now: datetime) -> None:
    """Periodic scan for stale conditions (offline, long door open, drift TTL)."""
    # Pre-load every user's settings once. Users × kinds is small (~hundreds).
    user_ids = [
        uid
        for (uid,) in (
            await session.execute(
                select(NotificationSetting.user_id).distinct()
            )
        ).all()
    ]
    settings_by_user: dict[int, dict[str, _MergedSetting]] = {
        uid: await get_user_settings(session, uid) for uid in user_ids
    }

    gateways = (
        (
            await session.execute(
                select(Gateway).order_by(Gateway.id.asc())
            )
        )
        .scalars()
        .all()
    )
    controllers = (
        (
            await session.execute(
                select(Controller).order_by(Controller.id.asc())
            )
        )
        .scalars()
        .all()
    )
    controllers_by_gateway: dict[int, list[Controller]] = {}
    for c in controllers:
        controllers_by_gateway.setdefault(c.gateway_id, []).append(c)

    await _eval_gateway_offline(
        session, settings_by_user, gateways, now
    )
    offline_controllers = await _eval_controller_offline(
        session, settings_by_user, controllers, now
    )
    await _eval_multi_controller_offline(
        session,
        settings_by_user,
        gateways,
        controllers_by_gateway,
        offline_controllers,
        now,
    )
    await _eval_door_open(session, settings_by_user, controllers, now)
    await _eval_drift_auto_resolve(session, settings_by_user, now)


async def _eval_gateway_offline(
    session: AsyncSession,
    settings_by_user: dict[int, dict[str, _MergedSetting]],
    gateways: list[Gateway],
    now: datetime,
) -> None:
    for g in gateways:
        settings = settings_by_user.get(g.user_id)
        if settings is None:
            continue
        setting = settings.get("gateway_offline")
        if setting is None or not setting.enabled:
            continue
        threshold = int(get_threshold(setting, "offline_minutes", 5))
        cutoff = now - timedelta(minutes=threshold)
        offline = g.last_seen_at is None or g.last_seen_at < cutoff

        active = await find_active_notification(
            session, g.user_id, "gateway_offline", gateway_id=g.id
        )
        if offline:
            if active is None:
                await open_notification(
                    session,
                    user_id=g.user_id,
                    kind="gateway_offline",
                    severity=setting.severity,
                    scope=setting.scope,
                    subject_name=g.name,
                    details={
                        "last_seen_at": (
                            g.last_seen_at.isoformat() if g.last_seen_at else None
                        ),
                        "offline_minutes": threshold,
                    },
                    gateway_id=g.id,
                )
        elif active is not None:
            await resolve_notification(session, active, now)


async def _eval_controller_offline(
    session: AsyncSession,
    settings_by_user: dict[int, dict[str, _MergedSetting]],
    controllers: list[Controller],
    now: datetime,
) -> set[int]:
    """Open/resolve controller_offline. Returns the set of controller ids
    currently considered offline (for multi-controller use below)."""
    offline_ids: set[int] = set()
    # We need user_id per controller — load gateway map once.
    gateway_owner = dict(
        (
            await session.execute(
                select(Gateway.id, Gateway.user_id)
            )
        ).all()
    )
    for c in controllers:
        user_id = gateway_owner.get(c.gateway_id)
        if user_id is None:
            continue
        settings = settings_by_user.get(user_id)
        if settings is None:
            continue
        setting = settings.get("controller_offline")
        if setting is None:
            continue
        threshold = int(get_threshold(setting, "offline_minutes", 5))
        cutoff = now - timedelta(minutes=threshold)
        offline = c.last_seen_at is None or c.last_seen_at < cutoff
        if offline:
            offline_ids.add(c.id)

        if not setting.enabled:
            continue
        active = await find_active_notification(
            session,
            user_id,
            "controller_offline",
            controller_id=c.id,
        )
        if offline:
            if active is None:
                await open_notification(
                    session,
                    user_id=user_id,
                    kind="controller_offline",
                    severity=setting.severity,
                    scope=setting.scope,
                    subject_name=c.name,
                    details={
                        "last_seen_at": (
                            c.last_seen_at.isoformat() if c.last_seen_at else None
                        ),
                        "offline_minutes": threshold,
                    },
                    gateway_id=c.gateway_id,
                    controller_id=c.id,
                )
        elif active is not None:
            await resolve_notification(session, active, now)
    return offline_ids


async def _eval_multi_controller_offline(
    session: AsyncSession,
    settings_by_user: dict[int, dict[str, _MergedSetting]],
    gateways: list[Gateway],
    controllers_by_gateway: dict[int, list[Controller]],
    offline_controllers: set[int],
    now: datetime,
) -> None:
    for g in gateways:
        settings = settings_by_user.get(g.user_id)
        if settings is None:
            continue
        setting = settings.get("multi_controller_offline")
        if setting is None or not setting.enabled:
            continue
        siblings = controllers_by_gateway.get(g.id, [])
        offline_here = sorted(c.id for c in siblings if c.id in offline_controllers)
        active = await find_active_notification(
            session,
            g.user_id,
            "multi_controller_offline",
            gateway_id=g.id,
        )
        if len(offline_here) >= 2:
            if active is None:
                await open_notification(
                    session,
                    user_id=g.user_id,
                    kind="multi_controller_offline",
                    severity=setting.severity,
                    scope=setting.scope,
                    subject_name=g.name,
                    details={
                        "offline_controller_count": len(offline_here),
                        "offline_controller_ids": offline_here,
                    },
                    gateway_id=g.id,
                )
        elif active is not None:
            await resolve_notification(session, active, now)


async def _eval_door_open(
    session: AsyncSession,
    settings_by_user: dict[int, dict[str, _MergedSetting]],
    controllers: list[Controller],
    now: datetime,
) -> None:
    gateway_owner = dict(
        (
            await session.execute(
                select(Gateway.id, Gateway.user_id)
            )
        ).all()
    )
    for c in controllers:
        user_id = gateway_owner.get(c.gateway_id)
        if user_id is None:
            continue
        settings = settings_by_user.get(user_id)
        if settings is None:
            continue
        setting = settings.get("door_open")
        if setting is None or not setting.enabled:
            continue
        threshold = int(get_threshold(setting, "max_open_minutes", 5))

        latest_row = (
            await session.execute(
                text(
                    """
                    SELECT time, door_open
                    FROM controller_telemetry
                    WHERE controller_id = :cid
                    ORDER BY time DESC
                    LIMIT 1
                    """
                ),
                {"cid": c.id},
            )
        ).first()

        active = await find_active_notification(
            session, user_id, "door_open", controller_id=c.id
        )

        if latest_row is None or not latest_row.door_open:
            if active is not None:
                await resolve_notification(session, active, now)
            continue

        # Has the door been continuously open for ≥ threshold? If there's no
        # closed-door row in the last `threshold` minutes, treat it as such.
        window_start = now - timedelta(minutes=threshold)
        closed_in_window = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM controller_telemetry
                    WHERE controller_id = :cid
                      AND time > :start
                      AND door_open = false
                    LIMIT 1
                    """
                ),
                {"cid": c.id, "start": window_start},
            )
        ).first()
        if closed_in_window is not None:
            # Door was closed at least once recently — not continuous.
            if active is not None:
                # Edge case: an active notification exists, but the door has
                # since been opened *and* closed within the window. Resolve
                # the stale notification; the next opening will start a
                # fresh window.
                await resolve_notification(session, active, now)
            continue

        # Door's been continuously open for at least `threshold` minutes.
        # Find when it first opened (the earliest open row in this run).
        open_since_row = (
            await session.execute(
                text(
                    """
                    SELECT MIN(time) AS first_open
                    FROM controller_telemetry
                    WHERE controller_id = :cid
                      AND door_open = true
                      AND time > COALESCE(
                          (SELECT MAX(time) FROM controller_telemetry
                           WHERE controller_id = :cid AND door_open = false),
                          '-infinity'::timestamptz
                      )
                    """
                ),
                {"cid": c.id},
            )
        ).first()
        open_since = (
            open_since_row.first_open if open_since_row is not None else None
        )
        open_minutes = (
            int((now - open_since).total_seconds() // 60)
            if open_since is not None
            else threshold
        )
        if active is None:
            await open_notification(
                session,
                user_id=user_id,
                kind="door_open",
                severity=setting.severity,
                scope=setting.scope,
                subject_name=c.name,
                details={
                    "open_since": (
                        open_since.isoformat() if open_since is not None else None
                    ),
                    "open_minutes": open_minutes,
                    "threshold_minutes": threshold,
                },
                gateway_id=c.gateway_id,
                controller_id=c.id,
            )


async def _eval_drift_auto_resolve(
    session: AsyncSession,
    settings_by_user: dict[int, dict[str, _MergedSetting]],
    now: datetime,
) -> None:
    """temp_drift is one-shot — resolve any notification older than the
    user's configured drift window."""
    actives = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.kind == "temp_drift",
                    Notification.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for n in actives:
        settings = settings_by_user.get(n.user_id)
        window = 10
        if settings is not None:
            s = settings.get("temp_drift")
            if s is not None:
                window = int(get_threshold(s, "drift_minutes", 10))
        if (now - n.opened_at) >= timedelta(minutes=window):
            await resolve_notification(session, n, now)
