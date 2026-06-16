"""Notification summary templates.

A single ``build_summary(kind, subject_name, details)`` helper renders the
short human-readable line shown in the bell list. Templates are kept
together so adding a kind in Phase 4B is one diff.

Templates use ``str.format`` substitution against ``details`` plus a
``subject_name`` keyword. Missing keys fall back to a generic line rather
than raising — the detector should ideally populate every field, but a
firing notification with a malformed payload should still display
*something* in the UI.
"""

from __future__ import annotations

from typing import Any

_TEMPLATES: dict[str, str] = {
    "temp_safe": (
        "{subject_name} temperature is {observed}°C "
        "(safe range {threshold_min}-{threshold_max}°C)"
    ),
    "temp_preferred": (
        "{subject_name} temperature is {observed}°C "
        "(preferred range {threshold_min}-{threshold_max}°C)"
    ),
    "temp_drift": (
        "{subject_name} temperature changed by {delta_c}°C "
        "over {drift_minutes} minutes"
    ),
    "door_open": "{subject_name} door has been open for {open_minutes} minutes",
    "controller_offline": (
        "{subject_name} hasn't reported in {offline_minutes} minutes"
    ),
    "gateway_offline": (
        "{subject_name} hasn't reported in {offline_minutes} minutes"
    ),
    "multi_controller_offline": (
        "{subject_name}: {affected_count} controllers went offline together"
    ),
    "battery_critical": (
        "{subject_name} battery critically low ({observed_pct}%)"
    ),
    "battery_low": "{subject_name} battery getting low ({observed_pct}%)",
    "node_error_single": (
        "{subject_name} reported a sensor error ({err})"
    ),
    "node_error_cumulative": (
        "{subject_name}: {error_count} nodes reporting errors"
    ),
}


def build_summary(
    kind: str, subject_name: str | None, details: dict[str, Any] | None
) -> str:
    """Render the one-line summary for a notification row.

    Falls back to ``"{kind} on {subject_name}"`` if the template can't be
    rendered (missing field, no template registered, etc.) so the UI never
    has to deal with an empty string.
    """
    subject = subject_name or "Unknown"
    template = _TEMPLATES.get(kind)
    if template is None:
        return f"{kind} on {subject}"

    fields: dict[str, Any] = {"subject_name": subject}
    if details:
        fields.update(details)
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return f"{kind} on {subject}"
