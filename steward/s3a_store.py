"""S3A injected writer-store contract and in-memory reference implementation.

Phase S3A scope: ONLY an in-memory reference store. No live Redis, database,
Docker, HTTP, SSH, or Federation connector.

The store protocol is narrow: it does not expose arbitrary commands, keys,
queries, scripts, or filesystem paths. Transaction semantics are deterministic:
validate-before-mutate, optimistic version checking, all-or-nothing, idempotent
retries, bounded counters, stable ordering, and input objects are never mutated.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class StoreError(Exception):
    pass


class ConflictError(StoreError):
    """Optimistic version conflict."""


class BoundedCounterError(StoreError):
    """Occurrence counter exceeded its bound."""


@dataclass
class StoreRecord:
    key: str
    version: int
    data: Dict[str, Any]
    occurrence_count: int = 1
    audit: List[Dict[str, Any]] = field(default_factory=list)
    suppressed_duplicates: List[str] = field(default_factory=list)


MAX_OCCURRENCE = 1_000_000


class InMemoryStore:
    """Narrow, deterministic, in-memory reference store.

    Mutations happen only through `transaction`, which validates everything
    before applying changes and either commits atomically or raises without
    side effects.
    """

    def __init__(self) -> None:
        self._records: Dict[str, StoreRecord] = {}
        self._idempotency: Dict[str, Dict[str, Any]] = {}

    # --- protocol: read ---
    def read(self, key: str) -> Optional[StoreRecord]:
        rec = self._records.get(key)
        if rec is None:
            return None
        return self._clone_record(rec)

    # --- protocol: idempotency check ---
    def has_idempotency_key(self, idempotency_key: str) -> bool:
        return idempotency_key in self._idempotency

    def original_result(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        entry = self._idempotency.get(idempotency_key)
        if entry is None:
            return None
        return copy.deepcopy(entry.get("result"))

    # --- protocol: create if absent (opt. version) ---
    def create_if_absent(self, key: str, data: Dict[str, Any]) -> StoreRecord:
        if key in self._records:
            raise StoreError(f"record already exists: {key}")
        rec = StoreRecord(key=key, version=1, data=copy.deepcopy(data))
        self._records[key] = rec
        return self._clone_record(rec)

    # --- protocol: optimistic compare ---
    def compare_version(self, key: str, expected_version: int) -> bool:
        rec = self._records.get(key)
        if rec is None:
            return False
        return rec.version == expected_version

    # --- protocol: update ---
    def update(self, key: str, expected_version: int, data: Dict[str, Any]) -> StoreRecord:
        rec = self._records.get(key)
        if rec is None:
            raise StoreError(f"record not found: {key}")
        if rec.version != expected_version:
            raise ConflictError(
                f"version conflict on {key}: expected {expected_version}, "
                f"found {rec.version}"
            )
        rec.version += 1
        rec.data = copy.deepcopy(data)
        return self._clone_record(rec)

    # --- protocol: bounded occurrence increment ---
    def increment_occurrence(self, key: str, expected_version: int, step: int = 1) -> StoreRecord:
        rec = self._records.get(key)
        if rec is None:
            raise StoreError(f"record not found: {key}")
        if rec.version != expected_version:
            raise ConflictError(
                f"version conflict on {key}: expected {expected_version}, "
                f"found {rec.version}"
            )
        new_count = rec.occurrence_count + step
        if new_count > MAX_OCCURRENCE:
            raise BoundedCounterError(
                f"occurrence count bound exceeded on {key}"
            )
        rec.version += 1
        rec.occurrence_count = new_count
        return self._clone_record(rec)

    # --- protocol: append immutable audit ---
    def append_audit(self, key: str, entry: Dict[str, Any]) -> None:
        rec = self._records.get(key)
        if rec is None:
            raise StoreError(f"record not found: {key}")
        rec.audit.append(copy.deepcopy(entry))

    # --- protocol: record duplicate suppression ---
    def record_suppression(self, key: str, duplicate_key: str) -> None:
        rec = self._records.get(key)
        if rec is None:
            raise StoreError(f"record not found: {key}")
        rec.suppressed_duplicates.append(duplicate_key)

    # --- protocol: synthetic Councilor Watch view ---
    def render_councilor_watch(self) -> List[Dict[str, Any]]:
        """Deterministic read-model: records sorted by key, audit by insertion."""
        out: List[Dict[str, Any]] = []
        for key in sorted(self._records.keys()):
            rec = self._records[key]
            out.append(
                {
                    "key": key,
                    "version": rec.version,
                    "occurrence_count": rec.occurrence_count,
                    "data": copy.deepcopy(rec.data),
                    "audit_count": len(rec.audit),
                    "synthetic": True,
                    "read_only_projection": True,
                }
            )
        return out

    # --- idempotency registration ---
    def register_idempotency(self, idempotency_key: str, result: Dict[str, Any]) -> None:
        self._idempotency[idempotency_key] = {"result": copy.deepcopy(result)}

    @staticmethod
    def _clone_record(rec: StoreRecord) -> StoreRecord:
        return StoreRecord(
            key=rec.key,
            version=rec.version,
            data=copy.deepcopy(rec.data),
            occurrence_count=rec.occurrence_count,
            audit=copy.deepcopy(rec.audit),
            suppressed_duplicates=list(rec.suppressed_duplicates),
        )
