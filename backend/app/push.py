"""Expo Push API client.

Two send paths:
- send_test_push(token, title, body): one-off test from the backend
- send_push_for_notification(session, notification, event): called by the
  detector when a notification opens or resolves, sends to all of the
  user's registered tokens

Uses the authenticated Expo API with EXPO_ACCESS_TOKEN.
Batches up to 100 messages per HTTP call.
Handles push receipts asynchronously (~15 min delay) to prune invalid tokens.

This module is kept identical between the backend and the ingestor
packages (parallel-file pattern, same as models.py) — the backend serves
the test-push endpoint, the ingestor's detector fires real pushes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Notification, NotificationSetting, PushToken
from .notification_messages import build_summary

log = logging.getLogger("push")

_EXPO_SEND_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
_BATCH_SIZE = 100
_RECEIPT_DELAY_SECONDS = 900  # 15 minutes


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    }
    if settings.EXPO_ACCESS_TOKEN:
        h["Authorization"] = f"Bearer {settings.EXPO_ACCESS_TOKEN}"
    return h


async def _post_to_expo(url: str, body: Any) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=body, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def _build_message(
    token: str, title: str, body: str, data: dict[str, Any], priority: str = "high"
) -> dict[str, Any]:
    return {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "priority": priority,  # "high" for critical, "normal" for alert
        "channelId": "default",  # Android channel
        "data": data,
    }


async def send_test_push(token: str, title: str, body: str) -> dict[str, Any]:
    """Fire a single test push. Returns {ticket_id, status, message}."""
    msg = _build_message(token, title, body, {"is_test_only": True}, priority="high")
    try:
        result = await _post_to_expo(_EXPO_SEND_URL, [msg])
    except Exception as exc:
        log.exception("expo push failed for token=%s", token[:30])
        return {"ticket_id": None, "status": "error", "message": str(exc)[:200]}

    tickets = result.get("data", [])
    if not tickets:
        return {"ticket_id": None, "status": "error", "message": "no ticket returned"}
    ticket = tickets[0]
    if ticket.get("status") == "ok":
        return {"ticket_id": ticket.get("id"), "status": "ok", "message": None}
    return {
        "ticket_id": ticket.get("id"),
        "status": "error",
        "message": ticket.get("message") or ticket.get("details", {}).get("error"),
    }


async def send_push_for_notification(
    session: AsyncSession,
    notification: Notification,
    event: str,  # "opened" | "resolved"
) -> None:
    """Send push to all of the user's registered tokens for this notification.

    Called from the detector's open_notification and resolve_notification
    paths, wrapped by the caller in try/except so a push failure never
    blocks the notification flow.

    - Respects notification_settings.enabled: skips if the kind is disabled.
    - For "resolved" event: only fires for critical severity kinds.
    - Sends to all user's tokens in a single batched call.
    - Enqueues receipt polling ~15 min later to detect DeviceNotRegistered.
    """
    # Gate: only resolve pushes for critical kinds
    if event == "resolved" and notification.severity != "critical":
        return

    # Check the user's setting for this kind — the same flag gates in-app + push
    setting = (
        await session.execute(
            select(NotificationSetting).where(
                NotificationSetting.user_id == notification.user_id,
                NotificationSetting.kind == notification.kind,
            )
        )
    ).scalar_one_or_none()
    if setting is None or not setting.enabled:
        return

    # Load user's tokens
    tokens = (
        await session.execute(
            select(PushToken).where(PushToken.user_id == notification.user_id)
        )
    ).scalars().all()
    if not tokens:
        return

    # Build the shared push body
    subject = notification.subject_name or "Notification"
    body_text = build_summary(notification.kind, subject, notification.details or {})
    if event == "resolved":
        title = f"Resolved: {subject}"
        priority = "normal"
    else:
        title = subject
        priority = "high" if notification.severity == "critical" else "normal"

    is_test = bool((notification.details or {}).get("is_test"))
    data = {
        "notification_id": notification.id,
        "kind": notification.kind,
        "severity": notification.severity,
        "scope": notification.scope,
        "gateway_id": notification.gateway_id,
        "controller_id": notification.controller_id,
        "node_id": notification.node_id,
        "opened_at": (
            notification.opened_at.isoformat() if notification.opened_at else None
        ),
        "is_test": is_test,
        "event": event,
    }

    token_strings = [t.token for t in tokens]
    messages = [
        _build_message(tok, title, body_text, data, priority) for tok in token_strings
    ]

    # Send in batches of 100, correlating each ticket with the exact token that
    # produced it *within its batch*. Pairing per-batch (rather than by a global
    # positional index) keeps the ticket→token mapping correct even when a
    # non-final batch's HTTP call fails and contributes zero tickets. Expo
    # returns one ticket per message in order; strict=False tolerates a short
    # data array by pairing only what lines up (unpaired tokens are simply not
    # pruned — the safe direction).
    ticket_token_pairs: list[tuple[dict[str, Any], str]] = []
    for i in range(0, len(messages), _BATCH_SIZE):
        batch = messages[i : i + _BATCH_SIZE]
        batch_tokens = token_strings[i : i + _BATCH_SIZE]
        try:
            result = await _post_to_expo(_EXPO_SEND_URL, batch)
        except Exception:
            log.exception("expo batch send failed (batch of %d)", len(batch))
            continue
        tickets = result.get("data", [])
        ticket_token_pairs.extend(zip(tickets, batch_tokens, strict=False))

    # Immediate ticket errors → prune (e.g. DeviceNotRegistered on send)
    for ticket, token in ticket_token_pairs:
        if ticket.get("status") == "error":
            details_error = (ticket.get("details") or {}).get("error")
            if details_error == "DeviceNotRegistered":
                await _prune_token(session, token)

    # Enqueue receipt poll ~15 min later
    token_by_ticket = {
        ticket.get("id"): token
        for ticket, token in ticket_token_pairs
        if ticket.get("status") == "ok" and ticket.get("id")
    }
    if token_by_ticket:
        asyncio.create_task(
            _poll_receipts_later(list(token_by_ticket.keys()), token_by_ticket)
        )


async def _prune_token(session: AsyncSession, token: str) -> None:
    """Delete a push_tokens row and commit. Idempotent."""
    await session.execute(delete(PushToken).where(PushToken.token == token))
    await session.commit()
    log.info("pruned push token=%s (invalid/unregistered)", token[:30])


async def _poll_receipts_later(
    ticket_ids: list[str], token_by_ticket: dict[str, str]
) -> None:
    """Sleep ~15 min, then fetch receipts and prune invalid tokens."""
    await asyncio.sleep(_RECEIPT_DELAY_SECONDS)
    try:
        # Get a fresh session — the caller's session is long gone
        from .db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            # Expo receipts endpoint takes {"ids": [...]}
            for i in range(0, len(ticket_ids), _BATCH_SIZE):
                batch_ids = ticket_ids[i : i + _BATCH_SIZE]
                try:
                    result = await _post_to_expo(_EXPO_RECEIPTS_URL, {"ids": batch_ids})
                except Exception:
                    log.exception("expo receipts fetch failed")
                    continue
                receipts = result.get("data", {})
                for ticket_id, receipt in receipts.items():
                    if receipt.get("status") != "error":
                        continue
                    err = (receipt.get("details") or {}).get("error")
                    if err in ("DeviceNotRegistered", "InvalidCredentials"):
                        token = token_by_ticket.get(ticket_id)
                        if token:
                            await _prune_token(session, token)
    except Exception:
        log.exception("receipt polling task failed")
