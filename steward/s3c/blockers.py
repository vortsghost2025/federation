"""S3C live-backend blocker register (S3C-011).

A machine-readable register of every blocker that prevents S3C from ever
advancing to a live backend. Per the directive, ALL blockers remain UNRESOLVED
in this phase. This module is data + serialization only; it never mutates
live state and never attempts to resolve a blocker.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Every blocker is unresolved in S3C. This is the authoritative state.
BLOCKERS: List[Dict[str, str]] = [
    {
        "id": "BLK-001",
        "title": "No live Federation writer object may be constructed in S3C",
        "status": "unresolved",
        "owner": "architecture",
    },
    {
        "id": "BLK-002",
        "title": "Shadow pipeline has no production Redis write path",
        "status": "unresolved",
        "owner": "architecture",
    },
    {
        "id": "BLK-003",
        "title": "Safety interlock must fail closed; no relax-to-live flag exists",
        "status": "unresolved",
        "owner": "policy",
    },
    {
        "id": "BLK-004",
        "title": "Readiness evaluator can never return READY_FOR_LIVE",
        "status": "unresolved",
        "owner": "policy",
    },
    {
        "id": "BLK-005",
        "title": "S2 read-only adapters reused read-only; no mutation adapter present",
        "status": "unresolved",
        "owner": "s2",
    },
    {
        "id": "BLK-006",
        "title": "Dagu shadow workflow is illustrative only; not installed/schema-validated",
        "status": "unresolved",
        "owner": "dagu",
    },
    {
        "id": "BLK-007",
        "title": "No push/merge to any live branch authorized in S3C",
        "status": "unresolved",
        "owner": "release",
    },
]


@dataclass
class BlockerRegister:
    blockers: List[Dict[str, str]] = field(default_factory=list)

    def all_unresolved(self) -> bool:
        return all(b["status"] == "unresolved" for b in self.blockers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_unresolved": self.all_unresolved(),
            "count": len(self.blockers),
            "blockers": [dict(b) for b in self.blockers],
        }


def default_register() -> BlockerRegister:
    return BlockerRegister(blockers=[dict(b) for b in BLOCKERS])
