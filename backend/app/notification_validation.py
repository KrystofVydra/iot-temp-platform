"""Shared threshold validation for notification settings.

Used by both the user-facing PATCH /me/notifications/settings/{kind}
endpoint and the admin equivalents in ``routers/admin.py`` (defaults edit
plus per-user-on-behalf edits).
"""

from __future__ import annotations

from fastapi import HTTPException, status

# Paired keys that must satisfy a < b once the user provides them. The default
# row already obeys this — the check guards against admin or user edits that
# would invert the relationship.
_PAIRED_THRESHOLDS: dict[str, tuple[str, str]] = {
    "temp_safe": ("safe_min", "safe_max"),
    "temp_preferred": ("preferred_min", "preferred_max"),
}


def validate_thresholds(
    kind: str,
    candidate: dict[str, float],
    expected_keys: set[str],
) -> dict[str, float]:
    """Return the cleaned dict on success; raise 400 on shape error.

    Rules:
      * No unknown keys — the candidate must be a subset of the kind's
        seeded threshold keys.
      * Every value is coerced to ``float`` (Pydantic already enforces the
        type but we double-check for clarity).
      * Paired constraints (``temp_safe`` and ``temp_preferred``) require
        ``min < max``.
    """
    unknown = set(candidate) - expected_keys
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown threshold keys for kind '{kind}': {sorted(unknown)}",
        )

    cleaned: dict[str, float] = {}
    for k, v in candidate.items():
        try:
            cleaned[k] = float(v)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"threshold {k!r} must be a number",
            ) from exc

    pair = _PAIRED_THRESHOLDS.get(kind)
    if pair is not None:
        lo_key, hi_key = pair
        if lo_key in cleaned and hi_key in cleaned and cleaned[lo_key] >= cleaned[hi_key]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{lo_key} must be less than {hi_key}",
            )
    return cleaned
