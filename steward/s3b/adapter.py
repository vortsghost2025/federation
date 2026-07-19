"""S3B steward writer-adapter.

Consumes an S3A WriteOutcome (the already-governed, deterministic result of the
S3A WriterCore) and persists the *approved mutation* to a qualification backend.

This adapter is the component under qualification. It proves:
- capability boundary: a backend whose Capability denies write/delete/cas is
  never asked to perform that op;
- approval boundary: a write is refused unless a live approval is attached and
  not revoked (revocation does NOT alter already-persisted values);
- fault injection: injected backend faults surface as failed persists without
  corrupting the governance record;
- crash recovery: a persisted value in the SQLite backend survives reopen.

The adapter NEVER imports or talks to Redis, requests, socket, subprocess,
docker, paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
or telnetlib. The only connector used anywhere in S3B is sqlite3, and only
inside sqlitedb.py.

Input: an S3A WriteOutcome (already redacted + governed).
Output: a PersistReceipt (local-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..s3a_writer import WriteOutcome
from .protocol import (
    Approval,
    Capability,
    FaultKind,
    Receipt,
    InjectedFault,
    register_approval,
)
from .memory import MemoryBackend
from .sqlitedb import SqliteBackend


@dataclass
class PersistReceipt:
    """Local-only result of persisting a governance outcome to a backend."""

    action_id: str
    persisted: bool
    backend: str
    seq: int = 0
    fault_injected: Optional[FaultKind] = None
    error: str = ""
    # The S3A decision is preserved untouched regardless of backend result.
    s3a_decision: str = ""
    s3a_replayed: bool = False


class QualificationAdapter:
    """Routes governed S3A outcomes to a qualification backend safely."""

    def __init__(self, backend: Any, capability: Capability) -> None:
        self.backend = backend
        self.cap = capability

    def attach_approval(self, approval: Approval) -> None:
        self.backend.attach_approval(approval)

    def set_fault(self, fault: FaultKind) -> None:
        self.backend.set_fault(fault)

    def persist(self, outcome: WriteOutcome) -> PersistReceipt:
        """Persist a governed outcome.

        Replayed outcomes are idempotent: they are re-asserted (no new mutation
        beyond confirming the value is present). Denied outcomes are never sent
        to a backend.
        """

        res = outcome.result
        rec = PersistReceipt(
            action_id=res.action_id,
            persisted=False,
            backend=type(self.backend).__name__,
            s3a_decision=res.decision,
            s3a_replayed=outcome.replayed,
        )
        if res.decision == "denied":
            # Governance refused: never touch a backend.
            rec.error = "s3a denied; backend untouched"
            return rec
        if not res.idempotent_replay and res.decision != "committed":
            rec.error = f"unexpected s3a decision: {res.decision}"
            return rec

        key = f"world:{res.action_id}"
        value = res.action_id.encode("utf-8") + b"|" + res.decision.encode("utf-8")
        try:
            r: Receipt = self.backend.put(key, value)
            rec.persisted = r.ok
            rec.seq = r.seq
            rec.fault_injected = r.fault_injected
            if not r.ok:
                rec.error = r.note or "backend returned not-ok"
        except (PermissionError, OSError, InjectedFault) as exc:
            if isinstance(exc, InjectedFault):
                rec.error = f"InjectedFault[{exc.kind.value}]: {exc}"
            else:
                rec.error = f"{type(exc).__name__}: {exc}"
        return rec


def build_memory_adapter(capability: Capability) -> QualificationAdapter:
    return QualificationAdapter(MemoryBackend(capability), capability)


def build_sqlite_adapter(capability: Capability, db_path: str) -> QualificationAdapter:
    return QualificationAdapter(SqliteBackend(capability, db_path), capability)
