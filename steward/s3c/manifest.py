"""S3C run manifest schema.

Versioned, deterministic, reject-unknown-fields manifest describing a single
S3C shadow run. The manifest is the contract that the orchestrator (S3C-003)
consumes and that the bundle writer (S3C-007) serializes.

DETERMINISM CONTRACT:
* No wall-clock, no uuid, no randomness in this module.
* `run_id` is SHA-256 over the canonical manifest identity material supplied by
  the caller. Two manifests built from identical material get identical ids.
* Only four shadow modes are permitted (S3C-002):
    - fixture_plan
    - fixture_shadow_apply
    - live_readonly_plan
    - live_readonly_shadow_apply
  No live_apply / production mode may ever exist in this module.

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

S3C_MANIFEST_VERSION = "steward-s3c@0.1.0"

ALLOWED_MODES = (
    "fixture_plan",
    "fixture_shadow_apply",
    "live_readonly_plan",
    "live_readonly_shadow_apply",
)

# Fields a manifest may carry. Anything else is rejected (S3C-002).
_ALLOWED_FIELDS = {
    "manifest_version",
    "run_id",
    "mode",
    "source_profile",
    "namespace",
    "snapshot_id",
    "finding_ids",
    "capability",
    "requested_at",
    "idempotency_key",
    "replay_corpus_id",
    "notes",
}

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_:.-]{0,127}$")


def _require(value: str, pattern, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    if not pattern.match(value):
        raise ValueError(f"{field_name} has invalid format: {value!r}")


def _canonical_manifest_bytes(m: "RunManifest") -> bytes:
    material: Dict[str, Any] = {
        "manifest_version": m.manifest_version,
        "mode": m.mode,
        "source_profile": m.source_profile,
        "namespace": m.namespace,
        "snapshot_id": m.snapshot_id,
        "finding_ids": list(m.finding_ids),
        "capability": m.capability,
        "requested_at": m.requested_at,
        "idempotency_key": m.idempotency_key,
        "replay_corpus_id": m.replay_corpus_id,
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_digest(m: "RunManifest") -> str:
    return hashlib.sha256(_canonical_manifest_bytes(m)).hexdigest()


@dataclass
class RunManifest:
    """Strict, versioned, deterministic S3C run manifest.

    Rejects unknown fields, malformed identifiers, illegal modes, and any
    namespace outside `steward:`. `run_id` is filled from the canonical digest
    when left as None.
    """

    manifest_version: str
    mode: str
    source_profile: str
    namespace: str
    snapshot_id: str
    capability: str
    requested_at: str
    idempotency_key: str
    finding_ids: List[str] = field(default_factory=list)
    replay_corpus_id: str = ""
    notes: str = ""
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.manifest_version != S3C_MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest_version: {self.manifest_version!r}; "
                f"expected {S3C_MANIFEST_VERSION!r}"
            )
        if self.mode not in ALLOWED_MODES:
            raise ValueError(
                f"illegal mode {self.mode!r}; allowed: {list(ALLOWED_MODES)}"
            )
        _require(self.source_profile, _ID_PATTERN, "source_profile")
        _require(self.snapshot_id, _ID_PATTERN, "snapshot_id")
        _require(self.capability, _ID_PATTERN, "capability")
        _require(self.requested_at, _ID_PATTERN, "requested_at")
        _require(self.idempotency_key, _ID_PATTERN, "idempotency_key")
        if not self.namespace.startswith("steward:"):
            raise ValueError(
                f"namespace must start with 'steward:': {self.namespace!r}"
            )
        for fid in self.finding_ids:
            _require(fid, _ID_PATTERN, "finding_ids[]")
        if self.replay_corpus_id:
            _require(self.replay_corpus_id, _ID_PATTERN, "replay_corpus_id")
        if self.run_id is None:
            self.run_id = "run_" + _manifest_digest(self)

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "RunManifest":
        """Strict construction: reject unknown keys and missing required keys."""

        extra = set(raw.keys()) - _ALLOWED_FIELDS
        if extra:
            raise ValueError(f"unknown manifest fields rejected: {sorted(extra)}")
        required = {
            "manifest_version",
            "mode",
            "source_profile",
            "namespace",
            "snapshot_id",
            "capability",
            "requested_at",
            "idempotency_key",
        }
        missing = required - set(raw.keys())
        if missing:
            raise ValueError(f"missing required manifest fields: {sorted(missing)}")
        return RunManifest(
            manifest_version=raw["manifest_version"],
            mode=raw["mode"],
            source_profile=raw["source_profile"],
            namespace=raw["namespace"],
            snapshot_id=raw["snapshot_id"],
            capability=raw["capability"],
            requested_at=raw["requested_at"],
            idempotency_key=raw["idempotency_key"],
            finding_ids=list(raw.get("finding_ids", [])),
            replay_corpus_id=raw.get("replay_corpus_id", ""),
            notes=raw.get("notes", ""),
            run_id=raw.get("run_id"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id,
            "mode": self.mode,
            "source_profile": self.source_profile,
            "namespace": self.namespace,
            "snapshot_id": self.snapshot_id,
            "finding_ids": list(self.finding_ids),
            "capability": self.capability,
            "requested_at": self.requested_at,
            "idempotency_key": self.idempotency_key,
            "replay_corpus_id": self.replay_corpus_id,
            "notes": self.notes,
        }
