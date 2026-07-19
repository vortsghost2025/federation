"""Semantic-loop adapter (S2).

Reads pair-workspace convergence state and normalizes it to the
``semantic-loops`` S1 fixture shape. No mutation, no inference of "healthy"
from a missing source -- missing -> UNKNOWN.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot


def collect(
    fetcher: Callable[[], Any],
    *,
    observed_at: str,
    source: str = "pair_workspace",
    provenance: str = "",
) -> ObservationSnapshot:
    """Fetch pair-workspace state and normalize to S1 fixture shape.

    ``fetcher`` returns ``{"pairs": [...]}`` matching the S1 semantic-loops
    fixture schema. On failure -> UNKNOWN.
    """
    try:
        raw = fetcher()
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"pair workspace read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    if not isinstance(raw, dict):
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="pair workspace source returned non-object", provenance=provenance,
        )

    pairs = raw.get("pairs")
    if pairs is None:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="pair workspace source missing 'pairs'", provenance=provenance,
        )

    data = asdict_safe({"pairs": pairs})
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="read-only pair-workspace poll",
        provenance=provenance,
    )
