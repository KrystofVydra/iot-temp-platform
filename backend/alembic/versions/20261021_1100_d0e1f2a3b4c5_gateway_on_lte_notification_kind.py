"""gateway_on_lte notification kind (Phase C)

Twelfth notification kind. Fires when a gateway's current connection
source is LTE (``gateways.last_source = 1``) and resolves when it returns
to WiFi — so a user learns their fridge monitoring fell back to cellular
backup while data is still flowing.

Severity is ``alert`` rather than ``critical``: nothing has stopped
working, the link is just more expensive and less reliable. There is no
user-configurable threshold — the condition is a plain state read — so
``thresholds`` stays ``{}``.

The kind row is seeded with the same parametrized INSERT the Phase 4A
migration used, and existing users are backfilled one settings row each
from that row's own defaults (rather than repeating the literals), so the
two can't drift.

Downgrade deletes the catalogue row. ``notification_settings.kind`` and
``notifications.kind`` are both FKs with ON DELETE CASCADE, so the
per-user settings rows *and* any notifications already fired for this
kind go with it.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-21 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KIND = "gateway_on_lte"
_SEVERITY = "alert"
_SCOPE = "gateway"
_THRESHOLDS = "{}"
_DESCRIPTION = (
    "Gateway has fallen back to LTE — WiFi connection lost. "
    "Data is still flowing but using cellular backup."
)


def upgrade() -> None:
    # ----- catalogue row -----
    # Parametrized so the em-dash / apostrophes in the description can't
    # break escaping (same approach as the Phase 4A seed).
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO notification_kind_defaults
                (kind, severity, scope, enabled_default, thresholds, description)
            VALUES
                (:kind, :severity, :scope, true,
                 CAST(:thresholds AS JSONB), :description)
            """
        ),
        {
            "kind": _KIND,
            "severity": _SEVERITY,
            "scope": _SCOPE,
            "thresholds": _THRESHOLDS,
            "description": _DESCRIPTION,
        },
    )

    # ----- backfill existing users -----
    # enabled / thresholds are read back from the row just inserted, so a
    # later edit to the defaults above needs no change here.
    # (_KIND is a module constant, so the f-string carries no outside input.)
    op.execute(
        f"""
        INSERT INTO notification_settings (user_id, kind, enabled, thresholds)
        SELECT u.id, d.kind, d.enabled_default, d.thresholds
        FROM users u
        CROSS JOIN notification_kind_defaults d
        WHERE d.kind = '{_KIND}'
        """
    )


def downgrade() -> None:
    # notification_settings.kind and notifications.kind cascade from here.
    op.execute(f"DELETE FROM notification_kind_defaults WHERE kind = '{_KIND}'")
