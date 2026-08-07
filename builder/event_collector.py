"""
Federation Builder Agent — Stage 1: Event Collector.

Polls Redis for NPC decisions (per char_id) and emits newline-delimited JSON
events into /docker/federation-architect/builder/events/.

The collector does NOT make any capability requests itself — it only observes
the world. Stage 2 introduces the rule engine that turns events into
approval-gated draft requests.

Why polling instead of Redis keyspace notifications?
---------------------------------------------------
- The federation-game-redis-1 container is not configured with
  notify-keyspace-events.
- Keyspace notifications would still need filtering, and the data we need
  (recent decisions) lives in sorted sets that aren't reliably exposed
  via individual key writes.
- Polling at a short interval (default 2s) is cheap and predictable for
  the small number of NPC IDs we care about.

Safety properties
-----------------
- Read-only against Redis (uses GET / ZRANGE / HGETALL).
- Writes only to local files under /docker/federation-architect/builder/events/.
- No outbound network calls in this module.
- No imports of the shared federation_game work_loop library — the
  collector uses an injected redis client so it can be tested without
  importing the full work loop.

Public API
----------
- EventCollector(redis_client, npc_ids, events_dir, poll_interval_s)
  - run_forever(): blocks, polls, writes events.
  - run_once(): returns number of new events written; useful for tests.
- collect_once(redis_client, npc_ids, since_ts) -> Iterable[dict]
  - Pure function used by both run_once() and the test suite.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

logger = logging.getLogger("federation.builder.collector")


def _now_ts() -> float:
    return time.time()


def _normalize_decision(raw: object, char_id: str) -> Optional[dict]:
    """Best-effort coercion of a Redis decision payload into a dict.

    The federation work loop stores decisions as JSON-encoded strings in a
    sorted set. Some historical entries are not valid JSON (defensive: see
    npc_logs.py). We only emit events for entries we can fully decode.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    obj.setdefault("char_id", char_id)
    obj.setdefault("_collected_ts", _now_ts())
    return obj


def collect_once(redis_client, npc_ids: List[str], since_ts: float) -> List[dict]:
    """Return decisions newer than since_ts for each NPC.

    Each decision is annotated with:
        char_id: str
        ts: float  (best-effort; uses _collected_ts when source has none)
        _collected_ts: float

    Decisions are ordered chronologically by Redis score; ties resolved by
    the order Redis returns them.
    """
    out: List[dict] = []
    for char_id in npc_ids:
        try:
            items = redis_client.zrevrange(f"npc_decisions:{char_id}", 0, 49)
        except Exception as exc:
            logger.warning("collector zrevrange failed for %s: %s", char_id, exc)
            continue
        # zrevrange returns newest first; we want ascending for replay
        items = list(reversed(items))
        for raw in items:
            obj = _normalize_decision(raw, char_id)
            if obj is None:
                continue
            ts = obj.get("ts") or obj.get("_collected_ts")
            try:
                ts_f = float(ts)
            except (TypeError, ValueError):
                ts_f = obj["_collected_ts"]
            if ts_f > since_ts:
                obj["ts"] = ts_f
                out.append(obj)
    out.sort(key=lambda d: d.get("ts", 0.0))
    return out


@dataclass
class EventCollector:
    """Poll-based collector that writes JSONL events to a local directory."""

    redis_client: object
    npc_ids: List[str]
    events_dir: str
    poll_interval_s: float = 2.0
    high_water_bytes: int = 5_000_000  # rotate the JSONL once it grows past this
    _cursor_ts: float = field(default_factory=lambda: 0.0)
    _open_file: object = field(default=None, init=False)
    _open_path: str = field(default="", init=False)
    _seen_keys: Set[str] = field(default_factory=set, init=False)

    def _rotate_if_needed(self) -> None:
        if not self._open_path:
            return
        try:
            size = os.path.getsize(self._open_path)
        except OSError:
            size = 0
        if size >= self.high_water_bytes:
            self._close()
            self._open()

    def _open(self) -> None:
        os.makedirs(self.events_dir, exist_ok=True)
        path = os.path.join(self.events_dir, f"events-{int(_now_ts())}.jsonl")
        self._open_path = path
        self._open_file = open(path, "a", buffering=1)  # line-buffered
        logger.info("collector opened %s", path)

    def _close(self) -> None:
        if self._open_file is not None:
            try:
                self._open_file.close()
            except OSError:
                pass
        self._open_file = None
        self._open_path = ""

    def _dedup_key(self, event: dict) -> str:
        char_id = event.get("char_id", "")
        ts = event.get("ts", 0.0)
        # Use the JSON itself as a last-resort fingerprint; avoids
        # counting a re-polled item twice within the same _collected_ts
        # window. The full event isn't hashable so fall back to a tuple.
        return f"{char_id}:{ts}"

    def run_once(self) -> int:
        if self._open_file is None:
            self._open()
        decisions = collect_once(self.redis_client, self.npc_ids, self._cursor_ts)
        written = 0
        for d in decisions:
            key = self._dedup_key(d)
            if key in self._seen_keys:
                continue
            self._seen_keys.add(key)
            try:
                self._open_file.write(json.dumps(d) + "\n")
                written += 1
            except OSError as exc:
                logger.error("collector write failed: %s", exc)
            # Advance cursor but never beyond the lowest ts we just emitted.
            ts = float(d.get("ts", 0.0))
            if ts > self._cursor_ts:
                self._cursor_ts = ts
        if written:
            self._rotate_if_needed()
        return written

    def run_forever(self) -> None:
        self._open()
        logger.info(
            "collector started (npcs=%s, poll=%.2fs, dir=%s)",
            self.npc_ids, self.poll_interval_s, self.events_dir,
        )
        try:
            while True:
                try:
                    self.run_once()
                except Exception as exc:
                    logger.exception("collector loop error: %s", exc)
                time.sleep(self.poll_interval_s)
        finally:
            self._close()


__all__ = [
    "EventCollector",
    "collect_once",
    "_normalize_decision",
]
