"""
Federation Builder Agent — State Schema.

The builder maintains a small piece of on-disk state:

    state.json
    {
        "version": 1,
        "updated_at": "2026-08-07T16:00:00Z",
        "pending_requests": [
            {
                "id": "...",
                "kind": "capability_request",
                "created_at": "...",
                "proposed_action": { ... },
                "rationale": "...",
                "evidence": [ ... ],
                "status": "pending|approved|rejected|executed",
                "approved_at": null,
                "approved_by": null,
                "executed_at": null,
                "execution_result": null,
                "rejected_reason": null
            }
        ],
        "stats": {
            "events_processed": 0,
            "drafts_created": 0,
            "drafts_approved": 0,
            "drafts_rejected": 0,
            "last_event_ts": 0.0
        }
    }

All access goes through `BuilderState` so we have one place to validate,
log, and version-bump the schema. Schema changes bump `version` and add a
migration function in `migrate()`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("federation.builder.state")

CURRENT_VERSION = 1


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _now_ts() -> float:
    return time.time()


class BuilderState:
    """Threadsafe, atomic-write JSON state container."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return self._initial()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("state load failed (%s); resetting", exc)
            return self._initial()
        return self.migrate(data)

    @staticmethod
    def _initial() -> Dict[str, Any]:
        return {
            "version": CURRENT_VERSION,
            "updated_at": _now_iso(),
            "pending_requests": [],
            "stats": {
                "events_processed": 0,
                "drafts_created": 0,
                "drafts_approved": 0,
                "drafts_rejected": 0,
                "last_event_ts": 0.0,
            },
        }

    @staticmethod
    def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply forward-only migrations. Always returns a v=CURRENT_VERSION doc."""
        v = int(data.get("version", 0))
        if v < 1:
            # Pre-v1 docs are best-effort folded forward.
            data.setdefault("version", 1)
            data.setdefault("updated_at", _now_iso())
            data.setdefault("pending_requests", [])
            data.setdefault("stats", {})
            data["stats"].setdefault("events_processed", 0)
            data["stats"].setdefault("drafts_created", 0)
            data["stats"].setdefault("drafts_approved", 0)
            data["stats"].setdefault("drafts_rejected", 0)
            data["stats"].setdefault("last_event_ts", 0.0)
            v = 1
        # Future migrations go here: if v < 2: ...
        data["version"] = CURRENT_VERSION
        return data

    def save(self) -> None:
        with self._lock:
            self._data["updated_at"] = _now_iso()
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=".state.", suffix=".tmp", dir=os.path.dirname(self.path) or "."
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, sort_keys=True)
                os.replace(tmp_path, self.path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise

    # -- read --------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data["stats"])

    def pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._data["pending_requests"]]

    def get_pending(self, req_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for p in self._data["pending_requests"]:
                if p.get("id") == req_id:
                    return dict(p)
        return None

    # -- write -------------------------------------------------------------

    def add_pending(self, req: Dict[str, Any]) -> None:
        with self._lock:
            req.setdefault("status", "pending")
            req.setdefault("created_at", _now_iso())
            req.setdefault("approved_at", None)
            req.setdefault("approved_by", None)
            req.setdefault("executed_at", None)
            req.setdefault("execution_result", None)
            req.setdefault("rejected_reason", None)
            self._data["pending_requests"].append(req)
            self._data["stats"]["drafts_created"] = int(
                self._data["stats"].get("drafts_created", 0)
            ) + 1
            self.save()

    def approve(self, req_id: str, by: str) -> bool:
        with self._lock:
            for p in self._data["pending_requests"]:
                if p.get("id") == req_id and p.get("status") == "pending":
                    p["status"] = "approved"
                    p["approved_at"] = _now_iso()
                    p["approved_by"] = by
                    self._data["stats"]["drafts_approved"] = int(
                        self._data["stats"].get("drafts_approved", 0)
                    ) + 1
                    self.save()
                    return True
        return False

    def reject(self, req_id: str, reason: str, by: str) -> bool:
        with self._lock:
            for p in self._data["pending_requests"]:
                if p.get("id") == req_id and p.get("status") == "pending":
                    p["status"] = "rejected"
                    p["approved_by"] = by
                    p["rejected_reason"] = reason
                    p["approved_at"] = _now_iso()
                    self._data["stats"]["drafts_rejected"] = int(
                        self._data["stats"].get("drafts_rejected", 0)
                    ) + 1
                    self.save()
                    return True
        return False

    def mark_executed(self, req_id: str, result: Dict[str, Any]) -> bool:
        with self._lock:
            for p in self._data["pending_requests"]:
                if p.get("id") == req_id and p.get("status") == "approved":
                    p["status"] = "executed"
                    p["executed_at"] = _now_iso()
                    p["execution_result"] = result
                    self.save()
                    return True
        return False

    def record_event(self) -> None:
        with self._lock:
            self._data["stats"]["events_processed"] = int(
                self._data["stats"].get("events_processed", 0)
            ) + 1
            self._data["stats"]["last_event_ts"] = _now_ts()
            # We don't save on every event to avoid disk thrash; the
            # caller is expected to call save() periodically (the agent
            # loop saves after each cycle).

    def save_if_dirty(self) -> None:
        with self._lock:
            self.save()


__all__ = ["BuilderState", "CURRENT_VERSION"]
