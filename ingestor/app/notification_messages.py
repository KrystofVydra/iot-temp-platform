"""Notification summary templates.

A single ``build_summary(kind, subject_name, details)`` helper renders the
short human-readable line shown in the bell list. Templates are kept
together so adding a kind in Phase 4B is one diff.

Templates use ``str.format`` substitution against ``details`` plus a
``subject_name`` keyword. Missing keys fall back to a generic line rather
than raising — the detector should ideally populate every field, but a
firing notification with a malformed payload should still display
*something* in the UI.

Admin-fired test notifications (``details["is_test"] is True``) render from
a parallel set of templates where every numeric/value placeholder is the
literal string ``TEST_VALUE`` — only ``{subject_name}`` is substituted. The
stored ``details`` JSON keeps its real integer values; only the rendered
text changes, so the row is obviously synthetic while the badge in the UI
flags it as a test.
"""

from __future__ import annotations

from typing import Any

_FALLBACK = "{kind} on {subject}"

# Real templates — value placeholders substituted from ``details``.
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
        "{subject_name}: {offline_controller_count} controllers went offline together"
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

# Test templates — structurally identical to the real ones above, but every
# value placeholder is replaced with the literal ``TEST_VALUE``. Only
# ``{subject_name}`` remains a placeholder.
_TEST_TEMPLATES: dict[str, str] = {
    "temp_safe": (
        "{subject_name} temperature is TEST_VALUE°C "
        "(safe range TEST_VALUE-TEST_VALUE°C)"
    ),
    "temp_preferred": (
        "{subject_name} temperature is TEST_VALUE°C "
        "(preferred range TEST_VALUE-TEST_VALUE°C)"
    ),
    "temp_drift": (
        "{subject_name} temperature changed by TEST_VALUE°C "
        "over TEST_VALUE minutes"
    ),
    "door_open": "{subject_name} door has been open for TEST_VALUE minutes",
    "controller_offline": (
        "{subject_name} hasn't reported in TEST_VALUE minutes"
    ),
    "gateway_offline": (
        "{subject_name} hasn't reported in TEST_VALUE minutes"
    ),
    "multi_controller_offline": (
        "{subject_name}: TEST_VALUE controllers went offline together"
    ),
    "battery_critical": (
        "{subject_name} battery critically low (TEST_VALUE%)"
    ),
    "battery_low": "{subject_name} battery getting low (TEST_VALUE%)",
    "node_error_single": (
        "{subject_name} reported a sensor error (TEST_VALUE)"
    ),
    "node_error_cumulative": (
        "{subject_name}: TEST_VALUE nodes reporting errors"
    ),
}


def build_summary(
    kind: str, subject_name: str | None, details: dict[str, Any] | None
) -> str:
    """Render the one-line summary for a notification row.

    For admin test notifications (``details["is_test"]``), numeric values are
    rendered as ``TEST_VALUE`` so the line is unmistakably synthetic.

    Falls back to ``"{kind} on {subject_name}"`` if the template can't be
    rendered (missing field, no template registered, etc.) so the UI never
    has to deal with an empty string.
    """
    subject = subject_name or "Unknown"
    is_test = bool(details and details.get("is_test"))

    if is_test:
        template = _TEST_TEMPLATES.get(kind)
        if template is None:
            return _FALLBACK.format(kind=kind, subject=subject)
        # Test templates only have {subject_name} left to fill.
        try:
            return template.format(subject_name=subject)
        except (KeyError, IndexError, ValueError):
            return _FALLBACK.format(kind=kind, subject=subject)

    template = _TEMPLATES.get(kind)
    if template is None:
        return _FALLBACK.format(kind=kind, subject=subject)

    fields: dict[str, Any] = {"subject_name": subject}
    if details:
        fields.update(details)
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return _FALLBACK.format(kind=kind, subject=subject)
