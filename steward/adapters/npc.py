"""NPC heartbeat adapter (S2).

Reads NPC liveness observations (last heartbeat timestamps, expected
intervals) from a normalized source and produces an ``npc-heartbeats``-shaped
snapshot compatible with the existing pure S1 check.

This adapter performs NO cognition and NO inbox writes (spec Section 7.2).
It only normalizes observation data. A missing actor list -> UNKNOWN.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot


def collect(
    fetcher: Callable[[], Any],
    *,
    observed_at: str,
    source: str = "npc_heartbeat_api",
    provenance: str = "",
) -> ObservationSnapshot:
    """Fetch NPC heartbeat observations and normalize to S1 fixture shape.

    ``fetcher`` returns a dict ``{"actors": [...]}`` where each actor matches
    the S1 npc-heartbeats fixture schema (char_id, last_heartbeat_ts,
    expected_interval_seconds, age_factor). On failure -> UNKNOWN.
    """
    try:
        raw = fetcher()
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"npc heartbeat read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    if not isinstance(raw, dict):
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="npc heartbeat source returned non-object", provenance=provenance,
        )

    actors = raw.get("actors")
    if actors is None:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="npc heartbeat source missing 'actors'", provenance=provenance,
        )

    data = asdict_safe({"actors": actors, "observed_at": observed_at})
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="read-only npc heartbeat poll",
        provenance=provenance,
    )
