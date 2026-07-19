"""S3C source profiles (S3C-005).

Two profile kinds are permitted:
  - fixture: a fully offline, deterministic fixture bundle used for
    `fixture_plan` / `fixture_shadow_apply`.
  - live_readonly: a read-only connection description for
    `live_readonly_plan` / `live_readonly_shadow_apply`. The connection is
    NEVER used to mutate; it is a description only, and the actual rehearsal
    (S3C-008) issues read-only SSH/docker inspect commands itself.

No live connector is opened here. No secrets are stored — only an opaque host
label and a non-credential port description. This module is documentation of
intent, not a live client.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceProfile:
    """Describes where shadow input originates. Never holds live credentials."""

    profile_id: str
    kind: str  # "fixture" | "live_readonly"
    description: str
    host_label: str = ""          # opaque label, e.g. "federation-vps"; NOT an IP
    read_only: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "kind": self.kind,
            "description": self.description,
            "host_label": self.host_label,
            "read_only": self.read_only,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "SourceProfile":
        if raw.get("kind") not in ("fixture", "live_readonly"):
            raise ValueError(f"unsupported profile kind: {raw.get('kind')!r}")
        if raw.get("read_only") is not True:
            raise ValueError("source profile must be read_only=True")
        return SourceProfile(
            profile_id=raw["profile_id"],
            kind=raw["kind"],
            description=raw.get("description", ""),
            host_label=raw.get("host_label", ""),
            read_only=True,
            notes=raw.get("notes", ""),
        )


def default_fixture_profile() -> SourceProfile:
    return SourceProfile(
        profile_id="fixture.default",
        kind="fixture",
        description="Offline deterministic fixture bundle for shadow rehearsal.",
        host_label="",
        read_only=True,
    )


def default_live_readonly_profile() -> SourceProfile:
    return SourceProfile(
        profile_id="live_readonly.federation_vps",
        kind="live_readonly",
        description=(
            "Read-only observation of the federation VPS. Rehearsal issues only "
            "SSH read-only + docker inspect/stats/logs/network/volume commands. "
            "No writes, no credential inspection, no app-container exec."
        ),
        host_label="federation-vps",  # opaque label only; never resolved here
        read_only=True,
    )
