"""Structured Finding schema for The Steward.

S1 scope: pure data model only. No I/O, no mutation, no imports from the
live Federation backend. The Finding is the single source of truth; all
rendering (UI, model, Councilor Watch) is derived from it, never the reverse.

DETERMINISM CONTRACT (spec Sections 6, 8, 15):
* No wall-clock, no uuid, no randomness anywhere in this module.
* `observed_at` is ALWAYS supplied by the caller (frozen fixture or explicit
  value). The schema never reads the system clock.
* `finding_id` is SHA-256 over the canonical JSON of the stable identity
  material (check_id, dedupe_key, observed_at, status, severity,
  affected_entities, evidence, source_versions). Two findings built from
  identical material get identical ids -> byte-identical output is repeatable.
* `first_seen == last_seen == observed_at` and `occurrence_count == 1`.
  S1 performs single-shot observation only; it does NOT persist or update
  prior occurrences. Persistent dedupe/occurrence counting is explicitly OUT
  of S1 scope (spec Phase S2+).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

ENGINE_VERSION = "steward@0.1.0"

SEVERITIES = ("info", "warning", "error")
STATUSES = ("open", "unknown", "resolved")

# Fields that define a finding's stable identity. Order is fixed so the
# canonical digest is reproducible regardless of dict insertion order.
_CANONICAL_FIELDS = (
    "check_id",
    "dedupe_key",
    "observed_at",
    "status",
    "severity",
    "affected_entities",
    "evidence",
    "source_versions",
)


def _canonical_bytes(finding: "Finding") -> bytes:
    """Deterministic JSON of the identity material, sorted keys, stable lists."""
    material: Dict[str, Any] = {}
    for name in _CANONICAL_FIELDS:
        value = getattr(finding, name)
        # Normalize lists/tuples to plain lists for stable serialization.
        if isinstance(value, (list, tuple)):
            value = list(value)
        material[name] = value
    return json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(finding: "Finding") -> str:
    return hashlib.sha256(_canonical_bytes(finding)).hexdigest()


@dataclass
class Finding:
    """One observation emitted by a check.

    `status: unknown` is used when a source could not be read. The engine
    never infers "healthy" from "could not read" (spec Section 6).
    """

    check_id: str
    observed_at: str
    severity: str
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    affected_entities: List[str] = field(default_factory=list)
    dedupe_key: str = ""
    recommended_action: str = ""
    required_capability: str = ""
    approval_required: bool = False
    status: str = "open"
    finding_id: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    occurrence_count: int = 1
    source_versions: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity!r}")
        if self.status not in STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if not self.dedupe_key:
            raise ValueError("dedupe_key is required")
        if not self.observed_at:
            raise ValueError("observed_at is required and must be supplied by the caller")
        # Engine version metadata is recorded but never read from a clock.
        if not self.source_versions or "engine" not in self.source_versions:
            self.source_versions = {"engine": ENGINE_VERSION, **(self.source_versions or {})}
        # Single-shot observation: first_seen == last_seen == observed_at.
        if self.first_seen is None:
            self.first_seen = self.observed_at
        if self.last_seen is None:
            self.last_seen = self.observed_at
        if self.occurrence_count != 1:
            # S1 never updates occurrences; force the deterministic invariant.
            self.occurrence_count = 1
        # Determinism: finding_id derives from material, never uuid/random.
        if self.finding_id is None:
            self.finding_id = "fdg_" + _digest(self)

    def to_dict(self) -> Dict[str, Any]:
        # Emit the exact 16-field order required by the spec (Section 8) so
        # serialized output is stable and tool-comparable.
        return {
            "finding_id": self.finding_id,
            "check_id": self.check_id,
            "observed_at": self.observed_at,
            "severity": self.severity,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
            "affected_entities": self.affected_entities,
            "dedupe_key": self.dedupe_key,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrence_count": self.occurrence_count,
            "recommended_action": self.recommended_action,
            "required_capability": self.required_capability,
            "approval_required": self.approval_required,
            "source_versions": self.source_versions,
        }


def make_finding(**kwargs: Any) -> Finding:
    """Construct a Finding, defaulting engine version metadata.

    `observed_at` MUST be supplied by the caller (frozen fixture or explicit
    value). It is never derived from the system clock.
    """
    if "observed_at" not in kwargs:
        raise ValueError("observed_at is required to build a deterministic Finding")
    kwargs.setdefault("source_versions", {"engine": ENGINE_VERSION})
    return Finding(**kwargs)
