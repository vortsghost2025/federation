"""S3A governed action schemas.

Phase S3A scope: governed Federation-world writer *core and contracts only*.
No live connector, no clock, no randomness, no live mutation.

Every proposed action is a strict, versioned, deterministic structure.

DETERMINISM CONTRACT:
* No wall-clock, no uuid, no randomness anywhere in this module.
* `observed_at`/`requested_at` are ALWAYS supplied by the caller.
* `action_id` is SHA-256 over the canonical JSON of the stable identity
  material. Two actions built from identical material get identical ids.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

S3A_SCHEMA_VERSION = "steward@0.3.0"

# Capability namespaces are strictly restricted to this prefix.
ALLOWED_NAMESPACE_PREFIX = "steward:"

_ACTION_IDENTITY_FIELDS = (
    "schema_version",
    "action_type",
    "source_finding_id",
    "source_snapshot_id",
    "target_namespace",
    "requested_capability",
    "actor_id",
    "requested_at",
    "idempotency_key",
    "dedupe_key",
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_:.-]{0,127}$")
_NAMESPACE_PATTERN = re.compile(r"^steward:[a-z0-9_]+$")


def _require(value: str, pattern, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    if not pattern.match(value):
        raise ValueError(f"{field_name} has invalid format: {value!r}")


def _canonical_action_bytes(action: "ProposedAction") -> bytes:
    material: Dict[str, Any] = {}
    for name in _ACTION_IDENTITY_FIELDS:
        material[name] = getattr(action, name)
    # Normalize nested dict/list for stable serialization.
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return payload.encode("utf-8")


def _action_digest(action: "ProposedAction") -> str:
    return hashlib.sha256(_canonical_action_bytes(action)).hexdigest()


@dataclass
class ProposedAction:
    """A single governed, deterministic proposed world mutation.

    Reject unknown fields, malformed identifiers, and namespaces outside
    `steward:`. No action may default to a Federation-wide namespace.
    """

    schema_version: str
    action_type: str
    action_id: Optional[str]
    source_finding_id: str
    source_snapshot_id: str
    target_namespace: str
    requested_capability: str
    actor_id: str
    requested_at: str
    idempotency_key: str
    approval_state: str
    normalized_payload: Dict[str, Any] = field(default_factory=dict)
    redacted_provenance: Dict[str, Any] = field(default_factory=dict)
    expected_preconditions: Dict[str, Any] = field(default_factory=dict)
    resulting_status: str = "proposed"
    dedupe_key: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != S3A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version: {self.schema_version!r}; "
                f"expected {S3A_SCHEMA_VERSION!r}"
            )
        _require(self.action_type, _ID_PATTERN, "action_type")
        _require(self.source_finding_id, _ID_PATTERN, "source_finding_id")
        _require(self.source_snapshot_id, _ID_PATTERN, "source_snapshot_id")
        _require(self.requested_capability, _ID_PATTERN, "requested_capability")
        _require(self.actor_id, _ID_PATTERN, "actor_id")
        _require(self.idempotency_key, _ID_PATTERN, "idempotency_key")
        _require(self.requested_at, _ID_PATTERN, "requested_at")
        if not self.target_namespace.startswith(ALLOWED_NAMESPACE_PREFIX):
            raise ValueError(
                f"target_namespace must start with {ALLOWED_NAMESPACE_PREFIX!r}: "
                f"{self.target_namespace!r}"
            )
        if not _NAMESPACE_PATTERN.match(self.target_namespace):
            raise ValueError(
                f"target_namespace has invalid format: {self.target_namespace!r}"
            )
        if self.approval_state not in ("none", "pending", "approved", "denied"):
            raise ValueError(f"invalid approval_state: {self.approval_state!r}")
        if self.action_id is None:
            self.action_id = "act_" + _action_digest(self)

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "ProposedAction":
        """Strict construction: reject unknown keys and missing required keys."""
        allowed = {
            "schema_version",
            "action_type",
            "action_id",
            "source_finding_id",
            "source_snapshot_id",
            "target_namespace",
            "requested_capability",
            "actor_id",
            "requested_at",
            "idempotency_key",
            "approval_state",
            "normalized_payload",
            "redacted_provenance",
            "expected_preconditions",
            "resulting_status",
            "dedupe_key",
        }
        extra = set(raw.keys()) - allowed
        if extra:
            raise ValueError(f"unknown action fields rejected: {sorted(extra)}")
        missing = {
            "schema_version",
            "action_type",
            "source_finding_id",
            "source_snapshot_id",
            "target_namespace",
            "requested_capability",
            "actor_id",
            "requested_at",
            "idempotency_key",
            "approval_state",
        } - set(raw.keys())
        if missing:
            raise ValueError(f"missing required action fields: {sorted(missing)}")
        # Normalize nested structures to plain dict/list for determinism.
        payload = raw.get("normalized_payload") or {}
        provenance = raw.get("redacted_provenance") or {}
        preconds = raw.get("expected_preconditions") or {}
        if not isinstance(payload, dict):
            raise ValueError("normalized_payload must be an object")
        return ProposedAction(
            schema_version=raw["schema_version"],
            action_type=raw["action_type"],
            action_id=raw.get("action_id"),
            source_finding_id=raw["source_finding_id"],
            source_snapshot_id=raw["source_snapshot_id"],
            target_namespace=raw["target_namespace"],
            requested_capability=raw["requested_capability"],
            actor_id=raw["actor_id"],
            requested_at=raw["requested_at"],
            idempotency_key=raw["idempotency_key"],
            approval_state=raw.get("approval_state", "none"),
            normalized_payload=dict(payload),
            redacted_provenance=dict(provenance),
            expected_preconditions=dict(preconds),
            resulting_status=raw.get("resulting_status", "proposed"),
            dedupe_key=raw.get("dedupe_key", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action_type": self.action_type,
            "action_id": self.action_id,
            "source_finding_id": self.source_finding_id,
            "source_snapshot_id": self.source_snapshot_id,
            "target_namespace": self.target_namespace,
            "requested_capability": self.requested_capability,
            "actor_id": self.actor_id,
            "requested_at": self.requested_at,
            "idempotency_key": self.idempotency_key,
            "approval_state": self.approval_state,
            "normalized_payload": dict(self.normalized_payload),
            "redacted_provenance": dict(self.redacted_provenance),
            "expected_preconditions": dict(self.expected_preconditions),
            "resulting_status": self.resulting_status,
            "dedupe_key": self.dedupe_key,
        }
