"""S3C run bundles (S3C-007).

A run bundle is the serialized, byte-deterministic artifact of a shadow run:
the manifest, the shadow actions, the write outcomes, and a SHA-256 of the
canonical payload. Bundles are written atomically (temp file + rename) to a
local output directory.

SAFETY:
* No secrets, IPs, hostnames, or absolute paths are ever serialized. The only
  host reference is an opaque label (e.g. "federation-vps") that never resolves.
* Bundles are canonical JSON (sorted keys, no whitespace) so identical runs
  produce byte-identical files and identical SHA-256.
* Live bundles from S3C-008 rehearsal are NOT committed (directive: DO NOT
  commit live bundles). This module writes them locally only.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .manifest import RunManifest
from .shadow_model import ShadowProposedAction, ShadowWriteOutcome


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class RunBundle:
    """In-memory representation of a run bundle."""

    manifest: RunManifest
    actions: List[Dict[str, Any]] = field(default_factory=list)
    outcomes: List[Dict[str, Any]] = field(default_factory=list)
    sha256: str = ""

    def canonical_payload(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "actions": self.actions,
            "outcomes": self.outcomes,
        }

    def finalize(self) -> None:
        self.sha256 = hashlib.sha256(
            _canonical_bytes(self.canonical_payload())
        ).hexdigest()

    @staticmethod
    def from_payload(payload: Dict[str, Any]) -> "RunBundle":
        bundle = RunBundle(
            manifest=RunManifest.from_dict(payload["manifest"]),
            actions=list(payload.get("actions", [])),
            outcomes=list(payload.get("outcomes", [])),
            sha256=payload.get("sha256", ""),
        )
        return bundle

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "actions": self.actions,
            "outcomes": self.outcomes,
            "sha256": self.sha256,
        }


def write_bundle(bundle: RunBundle, out_dir: str, atomic: bool = True) -> str:
    """Atomically write a bundle to out_dir; returns the file path.

    The file name embeds the manifest run_id (no secrets/paths). Returns the
    absolute path. The caller is responsible for not committing live bundles.
    """

    if not os.path.isdir(out_dir):
        raise ValueError(f"output dir does not exist: {out_dir!r}")
    bundle.finalize()
    payload = bundle.to_dict()
    data = _canonical_bytes(payload)
    path = os.path.join(out_dir, f"s3c_bundle_{bundle.manifest.run_id}.json")
    if atomic:
        fd, tmp = tempfile.mkstemp(
            dir=out_dir, prefix=".s3c_tmp_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
    else:
        with open(path, "wb") as fh:
            fh.write(data)
    return path


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
