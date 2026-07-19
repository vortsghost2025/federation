"""S3C shadow data model — wire-compatible shadows of the S3A contract.

These dataclasses mirror the S3A governed-action schema (`steward@0.3.0`) so
that S3C shadow records are structurally identical to real S3A records. S3C
does NOT import the live S3A writer (`steward.s3a_writer`) because that module
pulls in live connectors (redis, requests, etc.). Instead S3C defines a
self-contained, offline shadow that exercises the same deterministic,
governed shape through S3B qualification backends.

S3C SHADOW CONTRACT:
* No wall-clock, no uuid, no randomness anywhere in this module.
* `requested_at` / observed timestamps are ALWAYS supplied by the caller.
* `action_id` is SHA-256 over the canonical JSON of the stable identity
  material. Two actions built from identical material get identical ids.
* No live connector imports. No auto-approval. No model calls.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

S3C_SCHEMA_VERSION = "steward@0.3.0"  # shadow-compatible with S3A

ALLOWED_NAMESPACE_PREFIX = "steward:"
SHADOW_NAMESPACE_PREFIX = "steward:shadow:"

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
# A shadow namespace is `steward:shadow:<segment>` where the segment matches
# the same restricted character class as a normal steward namespace.
_SHADOW_NAMESPACE_PATTERN = re.compile(r"^steward:shadow:[a-z0-9_]+$")


def _require(value: str, pattern, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    if not pattern.match(value):
        raise ValueError(f"{field_name} has invalid format: {value!r}")


def _canonical_action_bytes(action: "ShadowProposedAction") -> bytes:
    material: Dict[str, Any] = {}
    for name in _ACTION_IDENTITY_FIELDS:
        material[name] = getattr(action, name)
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return payload.encode("utf-8")


def _action_digest(action: "ShadowProposedAction") -> str:
    return hashlib.sha256(_canonical_action_bytes(action)).hexdigest()


@dataclass
class ShadowProposedAction:
    """Shadow-equivalent of S3A ProposedAction.

    Must use a `steward:shadow:` target namespace so it can never be mistaken
    for a live Federation mutation.
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
        if self.schema_version != S3C_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version: {self.schema_version!r}; "
                f"expected {S3C_SCHEMA_VERSION!r}"
            )
        _require(self.action_type, _ID_PATTERN, "action_type")
        _require(self.source_finding_id, _ID_PATTERN, "source_finding_id")
        _require(self.source_snapshot_id, _ID_PATTERN, "source_snapshot_id")
        _require(self.requested_capability, _ID_PATTERN, "requested_capability")
        _require(self.actor_id, _ID_PATTERN, "actor_id")
        _require(self.idempotency_key, _ID_PATTERN, "idempotency_key")
        _require(self.requested_at, _ID_PATTERN, "requested_at")
        if not self.target_namespace.startswith(SHADOW_NAMESPACE_PREFIX):
            raise ValueError(
                f"target_namespace must start with {SHADOW_NAMESPACE_PREFIX!r}: "
                f"{self.target_namespace!r}"
            )
        if not _SHADOW_NAMESPACE_PATTERN.match(self.target_namespace):
            raise ValueError(
                f"target_namespace has invalid format: {self.target_namespace!r}"
            )
        if self.approval_state not in ("none", "pending", "approved", "denied"):
            raise ValueError(f"invalid approval_state: {self.approval_state!r}")
        if self.action_id is None:
            self.action_id = "act_" + _action_digest(self)

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "ShadowProposedAction":
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
        payload = raw.get("normalized_payload") or {}
        provenance = raw.get("redacted_provenance") or {}
        preconds = raw.get("expected_preconditions") or {}
        if not isinstance(payload, dict):
            raise ValueError("normalized_payload must be an object")
        return ShadowProposedAction(
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


@dataclass
class ShadowApprovalArtifact:
    """Shadow-equivalent of S3A ApprovalArtifact. Never wildcard, never live."""

    schema_version: str
    approval_id: str
    action_id: str
    approving_authority: str
    granted_capability: str
    issued_at: str
    scope: str
    signature: str
    expires_at: Optional[str] = None

    def validate_against(self, action: ShadowProposedAction, now: str) -> None:
        """Raise ValueError if this approval cannot gate `action`."""

        if self.schema_version != S3C_SCHEMA_VERSION:
            raise ValueError("approval schema_version mismatch")
        if self.expires_at is not None and now > self.expires_at:
            raise ValueError("approval expired")
        if self.action_id != action.action_id:
            raise ValueError("approval.action_id != action.action_id")
        if self.granted_capability != action.requested_capability:
            raise ValueError("granted_capability mismatch")
        if not self.scope.startswith(SHADOW_NAMESPACE_PREFIX):
            raise ValueError("approval scope must be steward:shadow:")
        if self.scope != action.target_namespace:
            raise ValueError("approval scope != target_namespace")
        if "*" in self.granted_capability or "*" in self.scope:
            raise ValueError("wildcard approval is forbidden")


@dataclass
class ShadowWriteOutcome:
    """Outcome of the shadow writer core for a single action."""

    action_id: str
    decision: str  # committed | denied
    reason: str
    idempotent_replay: bool = False
    approval_attached: bool = False
    persisted: bool = False
    backend: str = ""
    seq: int = 0
    fault_injected: Optional[str] = None
    error: str = ""
