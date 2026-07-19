"""In-memory qualification backend.

Local-only, deterministic, offline. Implements the S3B conformance protocol
with no persistence. Used to prove the writer's behavior under fault injection
without any real backend.

Forbidden: redis, requests, urllib, socket, subprocess, docker, paramiko,
psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client, telnetlib, sqlite3.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .protocol import (
    Capability,
    FaultKind,
    Receipt,
    Approval,
    InjectedFault,
    register_approval,
    is_approval_live,
)


class MemoryBackend:
    """An in-memory key/value store conforming to the S3B protocol."""

    def __init__(self, capability: Capability) -> None:
        self.cap = capability
        self._store: Dict[str, bytes] = {}
        self._seq = 0
        self._fault: FaultKind = FaultKind.NONE
        self._partial_keep = 0  # keys to keep before dropping under PARTIAL_WRITE
        # Approval state (every write needs a live approval token).
        self._approval: Optional[Approval] = None

    # ---- approval boundary -------------------------------------------------
    def attach_approval(self, approval: Approval) -> None:
        register_approval(approval)
        self._approval = approval

    def _check_approval(self) -> None:
        if not self.cap.requires_approval:
            return
        if self._approval is None:
            raise PermissionError("no approval attached")
        if not is_approval_live(self._approval.token):
            raise PermissionError("approval not live (revoked)")

    # ---- fault-injection surface ------------------------------------------
    def set_fault(self, fault: FaultKind) -> None:
        self._fault = fault

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---- protocol methods --------------------------------------------------
    def put(self, key: str, value: bytes, opts: Optional[dict] = None) -> Receipt:
        if not self.cap.can_write:
            raise PermissionError("capability denies write")
        self._check_approval()
        if self._fault is FaultKind.WRITE_FAIL:
            raise InjectedFault(FaultKind.WRITE_FAIL, "injected write failure")
        if self._fault is FaultKind.CONNECTION_DROP:
            # simulate a mid-transaction drop: nothing persisted
            raise InjectedFault(FaultKind.CONNECTION_DROP,
                                "injected connection drop before commit")
        seq = self._next_seq()
        if self._fault is FaultKind.PARTIAL_WRITE:
            self._partial_keep += 1
            if self._partial_keep % 2 == 0:
                # drop every other key => partial durability
                return Receipt(key=key, ok=False, seq=seq,
                               fault_injected=self._fault,
                               note="partial: key dropped")
        if self._fault is FaultKind.STALE_READ:
            # still persist, but get() will serve stale
            pass
        self._store[key] = bytes(value)
        return Receipt(key=key, ok=True, seq=seq,
                       fault_injected=self._fault if self._fault != FaultKind.NONE else None)

    def get(self, key: str) -> Optional[bytes]:
        if key not in self._store:
            return None
        val = self._store[key]
        if self._fault is FaultKind.CORRUPT_READ:
            return val + b"\x00CORRUPTED"
        if self._fault is FaultKind.STALE_READ:
            # return an empty/older view
            return b""
        return bytes(val)

    def cas(self, key: str, expected: bytes, value: bytes) -> bool:
        if not self.cap.can_cas:
            raise PermissionError("capability denies cas")
        self._check_approval()
        if self._fault is FaultKind.RACE_LOST:
            return False
        cur = self._store.get(key)
        if cur != expected:
            return False
        self._store[key] = bytes(value)
        return True

    def delete(self, key: str) -> None:
        if not self.cap.can_delete:
            raise PermissionError("capability denies delete")
        self._check_approval()
        self._store.pop(key, None)

    def list_keys(self, prefix: str = "") -> List[str]:
        return sorted(k for k in self._store if k.startswith(prefix))

    def flush(self) -> None:
        self._store.clear()
        self._seq = 0
