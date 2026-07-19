"""SQLite qualification backend.

Local-only. Uses sqlite3 (the one connector explicitly permitted for the
local qualification backend) to give the harness a *persistent* target so that
crash-recovery semantics can be proven: a write that returns ok=1 must survive
a backend teardown and reopen.

Forbidden: redis, requests, urllib, socket, subprocess, docker, paramiko,
psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client, telnetlib.
"""

from __future__ import annotations

import os
import sqlite3
from typing import List, Optional

from .protocol import (
    Capability,
    FaultKind,
    Receipt,
    Approval,
    InjectedFault,
    register_approval,
    is_approval_live,
)


class SqliteBackend:
    """A persistent qualification backend backed by a local SQLite file.

    The DB file lives under a local temp/work directory. It is NEVER the
    production Federation Redis. The harness proves persistence + recovery by
    closing and reopening the connection.
    """

    def __init__(self, capability: Capability, db_path: str) -> None:
        self.cap = capability
        self.db_path = db_path
        self._fault: FaultKind = FaultKind.NONE
        self._partial_keep = 0
        self._approval: Optional[Approval] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    # ---- connection lifecycle (local file only) ---------------------------
    def _open(self) -> None:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  key TEXT PRIMARY KEY,"
            "  value BLOB,"
            "  seq INTEGER"
            ")"
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def reopen(self) -> None:
        """Simulate a crash/recovery: drop the live connection and reopen.

        This proves a committed row survives even when the *process handle*
        is lost (the central crash-recovery property).
        """

        self.close()
        self._open()

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

    # ---- protocol methods --------------------------------------------------
    def put(self, key: str, value: bytes, opts: Optional[dict] = None) -> Receipt:
        if self._conn is None:
            self._open()
        if not self.cap.can_write:
            raise PermissionError("capability denies write")
        self._check_approval()
        if self._fault is FaultKind.WRITE_FAIL:
            raise InjectedFault(FaultKind.WRITE_FAIL, "injected write failure")
        if self._fault is FaultKind.CONNECTION_DROP:
            raise InjectedFault(FaultKind.CONNECTION_DROP,
                                "injected connection drop before commit")
        seq = self._next_seq()
        if self._fault is FaultKind.PARTIAL_WRITE:
            self._partial_keep += 1
            if self._partial_keep % 2 == 0:
                return Receipt(key=key, ok=False, seq=seq,
                               fault_injected=self._fault,
                               note="partial: key dropped")
        cur = self._conn.execute(
            "INSERT INTO kv(key, value, seq) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, seq=excluded.seq",
            (key, sqlite3.Binary(value), seq),
        )
        self._conn.commit()
        return Receipt(key=key, ok=True, seq=seq,
                       fault_injected=self._fault if self._fault != FaultKind.NONE else None)

    def get(self, key: str) -> Optional[bytes]:
        if self._conn is None:
            self._open()
        if key not in self._present():
            return None
        row = self._conn.execute(
            "SELECT value FROM kv WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        val = bytes(row[0])
        if self._fault is FaultKind.CORRUPT_READ:
            return val + b"\x00CORRUPTED"
        if self._fault is FaultKind.STALE_READ:
            return b""
        return val

    def cas(self, key: str, expected: bytes, value: bytes) -> bool:
        if not self.cap.can_cas:
            raise PermissionError("capability denies cas")
        self._check_approval()
        if self._fault is FaultKind.RACE_LOST:
            return False
        cur = self.get(key)
        if cur is None or cur != expected:
            return False
        self.put(key, value)
        return True

    def delete(self, key: str) -> None:
        if not self.cap.can_delete:
            raise PermissionError("capability denies delete")
        self._check_approval()
        self._conn.execute("DELETE FROM kv WHERE key=?", (key,))
        self._conn.commit()

    def list_keys(self, prefix: str = "") -> List[str]:
        if self._conn is None:
            self._open()
        rows = self._conn.execute(
            "SELECT key FROM kv WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        ).fetchall()
        return [r[0] for r in rows]

    def _present(self) -> set:
        rows = self._conn.execute("SELECT key FROM kv").fetchall()
        return {r[0] for r in rows}

    def _next_seq(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM kv"
        ).fetchone()
        return int(row[0]) + 1

    def flush(self) -> None:
        self._conn.execute("DELETE FROM kv")
        self._conn.commit()
