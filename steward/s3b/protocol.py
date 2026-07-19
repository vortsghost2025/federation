"""S3B backend qualification conformance protocol.

Local-only backend qualification for the steward Federation-world writer.

This module defines the abstract contract every *qualification* backend must
satisfy, plus the fault-injection surface the harness exercises. It contains
NO live connectors (no redis, requests, socket, subprocess, docker, paramiko,
psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client, telnetlib).

A qualification backend is a thin, deterministic, offline stand-in for a real
Federation backend (Redis today; others later). It implements the same write
shape the S3A writer emits so that the writer's behavior can be proven against
a contract without touching production.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3 (sqlite3 is used only by the sqlite qualification backend).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FaultKind(str, Enum):
    """Faults the harness can inject into a qualification backend."""

    NONE = "none"
    WRITE_FAIL = "write_fail"          # raise on every put
    PARTIAL_WRITE = "partial_write"    # commit some keys, drop others
    LATENCY = "latency"                # simulate slow backend (no real sleep in unit path)
    CORRUPT_READ = "corrupt_read"      # return mutated bytes on get
    STALE_READ = "stale_read"          # return a previously-known value
    CONNECTION_DROP = "connection_drop"  # simulate mid-transaction drop (raises)
    RACE_LOST = "race_lost"            # simulate losing a compare-and-swap


class InjectedFault(Exception):
    """Raised by a qualification backend when a fault injection fires.

    Distinct from built-in OSError/IOError so tests can assert the fault
    surfaced rather than some incidental backend error.
    """

    def __init__(self, kind: FaultKind, message: str) -> None:
        self.kind = kind
        super().__init__(f"[{kind.value}] {message}")


# The minimal contract a qualification backend must implement.
# The harness drives these methods and asserts post-conditions.
PROTOCOL_METHODS = (
    "put",          # put(key: str, value: bytes, opts) -> Receipt
    "get",          # get(key: str) -> Optional[bytes]
    "cas",          # cas(key, expected, value) -> bool  (compare-and-swap)
    "delete",       # delete(key) -> None
    "list_keys",    # list_keys(prefix) -> List[str]
    "flush",        # flush() -> None  (clear local state only)
)


@dataclass
class Receipt:
    """Returned by a successful put. Local-only, no network."""

    key: str
    ok: bool
    seq: int
    fault_injected: Optional[FaultKind] = None
    note: str = ""


@dataclass
class Capability:
    """What a given backend is permitted to do.

    The harness enforces these at the capability boundary before any write.
    """

    name: str
    can_write: bool = False
    can_delete: bool = False
    can_cas: bool = False
    can_persist: bool = False          # False => in-memory only
    requires_approval: bool = True     # every qualification write needs approval
    notes: str = ""


@dataclass
class Approval:
    """An explicitly granted, revocable approval for a single write batch."""

    token: str
    capability: str
    granted_for: str                   # e.g. "world:gastown"
    revoked: bool = False
    revocation_reason: str = ""


# Global, in-process revocation registry. Survives within the process and is
# the single source of truth for whether an approval is live. This is what
# lets a test prove that *revoking an approval after a write was accepted does
# not alter the already-persisted value* (the central safety property).
_REVOCATIONS: Dict[str, Approval] = {}


def register_approval(approval: Approval) -> None:
    """Record an approval in the revocation registry.

    Re-attaching an already-revoked token must NOT resurrect it: a second
    `attach_approval` with the same token after a revoke keeps the revoked
    state, so a post-revocation write is still refused.
    """
    existing = _REVOCATIONS.get(approval.token)
    if existing is not None and existing.revoked:
        # Preserve the revocation; do not overwrite with a live copy.
        return
    _REVOCATIONS[approval.token] = approval


def revoke_approval(token: str, reason: str) -> bool:
    """Revoke a previously granted approval. Returns True if it was live."""

    ap = _REVOCATIONS.get(token)
    if ap is None:
        return False
    if ap.revoked:
        return False
    ap.revoked = True
    ap.revocation_reason = reason
    return True


def is_approval_live(token: str) -> bool:
    """True only if the token exists and has not been revoked."""

    ap = _REVOCATIONS.get(token)
    return ap is not None and not ap.revoked


def clear_registry() -> None:
    """Clear the revocation registry (test isolation only)."""

    _REVOCATIONS.clear()
