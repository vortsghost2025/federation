"""Host resource adapter (S2).

Reads host-level resource observations (disk, RAM, DB availability) from a
normalized source and produces a snapshot. Sources are provided by injected
readers; the adapter itself performs no syscalls. Missing source -> UNKNOWN.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot


def collect(
    reader: Callable[[], Any],
    *,
    observed_at: str,
    source: str = "host_resource",
    provenance: str = "",
) -> ObservationSnapshot:
    """Read host resource observations from an injected reader.

    ``reader`` returns a dict such as
    ``{"disk": {...}, "ram": {...}, "db_available": bool}``. On failure ->
    UNKNOWN.
    """
    try:
        raw = reader()
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"host resource read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    if not isinstance(raw, dict):
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="host resource source returned non-object", provenance=provenance,
        )

    data = asdict_safe(raw)
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="read-only host resource poll",
        provenance=provenance,
    )
