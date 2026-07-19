"""Adapter contract and normalized snapshot model for S2 read-only adapters.

Every adapter returns a normalized ``ObservationSnapshot`` plus explicit
source metadata (source name, observed timestamp, availability status,
version, timeout/error detail, redacted evidence, provenance).

Determinism rule: the normalized payload is plain JSON-serializable data with
stable key ordering. Identical live observations produce identical snapshots,
so the downstream S1 engine remains deterministic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Availability(str, Enum):
    """Source availability status reported by every adapter."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# Fields every normalized snapshot must carry (stable order for determinism).
_SNAPSHOT_FIELDS = (
    "source",
    "observed_at",
    "availability",
    "version",
    "status_detail",
    "provenance",
    "data",
)


@dataclass
class ObservationSnapshot:
    """Normalized observation from one read-only source.

    ``data`` holds the source-specific normalized payload. ``availability`` is
    UNKNOWN when the source could not be read -- the adapter must never infer
    "healthy" from a failed read.
    """

    source: str
    observed_at: str
    availability: str = Availability.UNKNOWN.value
    version: Optional[str] = None
    status_detail: str = ""
    provenance: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # Stable ordering so serialization is reproducible.
        return {k: getattr(self, k) for k in _SNAPSHOT_FIELDS}

    def to_json(self, redact: bool = True) -> str:
        payload = self.to_dict()
        if redact:
            from ..redact import redact_value

            payload = redact_value(payload)
        return json.dumps(payload, sort_keys=True, indent=2)


def unknown_snapshot(
    source: str,
    observed_at: str,
    detail: str,
    provenance: str = "",
    version: Optional[str] = None,
) -> ObservationSnapshot:
    """Convenience constructor for an unavailable/errored source.

    Used whenever a read times out, is refused, or the source is missing. The
    engine never treats UNKNOWN as healthy (spec Section 6).
    """
    return ObservationSnapshot(
        source=source,
        observed_at=observed_at,
        availability=Availability.UNKNOWN.value,
        version=version,
        status_detail=detail,
        provenance=provenance,
        data={},
    )


def snapshot_from(
    source: str,
    observed_at: str,
    data: Dict[str, Any],
    *,
    availability: str = Availability.AVAILABLE.value,
    version: Optional[str] = None,
    status_detail: str = "",
    provenance: str = "",
) -> ObservationSnapshot:
    return ObservationSnapshot(
        source=source,
        observed_at=observed_at,
        availability=availability,
        version=version,
        status_detail=status_detail,
        provenance=provenance,
        data=data,
    )


def asdict_safe(obj: Any) -> Any:
    """Recursively convert dataclasses / lists / dicts to JSON-safe primitives.

    Guarantees adapters never leak non-serializable live objects into the
    normalized snapshot (which would break deterministic JSON output).
    """
    if isinstance(obj, dict):
        return {k: asdict_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [asdict_safe(v) for v in obj]
    if hasattr(obj, "to_dict"):
        return asdict_safe(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__"):
        return asdict_safe(asdict(obj))
    return obj
