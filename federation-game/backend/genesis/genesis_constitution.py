"""
genesis_constitution — L1 Constitutional layer: Symmetry Preservation.

Operationalizes the WE4FREE SNAPSHOT_PROTOCOL for Federation NPCs.

Closes:
  NFM-002 (self-state aliasing) — identity frozen atomically, recovered functorially.
  NFM-009 (freshness != liveness) — verify_aliveness probes REAL liveness (Redis
            round-trip), never conflates file/timestamp freshness with process liveness.

Source-of-truth precedence (WE4FREE Paper F 2.3):
  runtime (live) > lock (fresh local) > registry (advisory) > history (never authoritative)

Storage: Redis (matches Federation infra). Atomic write via temp key + RENAME
(which is atomic on Redis, unlike a multi-key transaction across processes).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("genesis.constitution")

SNAPSHOT_KEY = "genesis:snapshot:{char_id}"
SNAPSHOT_TMP_KEY = "genesis:snapshot:{char_id}:tmp"
LIVENESS_KEY = "npc:{char_id}:alive"


def _redis():
    """Lazy Redis connection (decode_responses=True to match npc_autonomy)."""
    import redis

    url = __import__("os").environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


def freeze_snapshot(char_id: str, live_state: dict[str, Any], ttl: int = 3600) -> str:
    """Atomically freeze an NPC's identity. Returns the version hash.

    Symmetry Preservation: the snapshot is written to a temp key first, then
    atomically RENAMEd to the canonical key. A reader never sees a half-written
    state object (this is the Windows-unsafe multi-write problem, NFM-014, avoided).
    """
    version = hashlib.sha256(
        (char_id + str(time.time()) + json.dumps(live_state, sort_keys=True)).encode()
    ).hexdigest()[:16]
    payload = {
        "char_id": char_id,
        "version": version,
        "ts": int(time.time()),
        "state": live_state,
    }
    r = _redis()
    tmp = SNAPSHOT_TMP_KEY.format(char_id=char_id)
    final = SNAPSHOT_KEY.format(char_id=char_id)
    r.set(tmp, json.dumps(payload), ex=ttl + 60)
    r.rename(tmp, final)  # atomic
    r.expire(final, ttl)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("L1 freeze %s -> v%s", char_id, version)
    return version


def recover_snapshot(char_id: str) -> Optional[dict[str, Any]]:
    """Functorial recovery — return the last stable identity, or None if absent.

    Structure-preserving: the returned dict has the same shape as a live state, so
    it can be re-anchored without a central reset (NFM-002 guard).
    """
    r = _redis()
    raw = r.get(SNAPSHOT_KEY.format(char_id=char_id))
    if not raw:
        return None
    try:
        return json.loads(raw)["state"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def verify_aliveness(char_id: str) -> bool:
    """NFM-009 guard. Freshness (timestamp) != liveness (process).

    We probe the NPC's real liveness channel (a heartbeat key set by the running
    process), NOT the snapshot mtime. A stale-but-alive process must not be judged
    dead, and a fresh-looking file for a dead process must not be trusted.
    """
    r = _redis()
    # A heartbeat key with recent TTL remaining == the process is alive NOW.
    ttl = r.ttl(LIVENESS_KEY.format(char_id=char_id))
    if ttl is None or ttl == -2:
        return False  # key absent -> not alive
    if ttl == -1:
        return True  # no expiry set -> treat as alive (operator override)
    return ttl > 0


def touch_liveness(char_id: str, ttl: int = 60) -> None:
    """Called by the running process each tick to assert liveness."""
    _redis().set(LIVENESS_KEY.format(char_id=char_id), int(time.time()), ex=ttl)


def clear_snapshot(char_id: str) -> None:
    r = _redis()
    r.delete(SNAPSHOT_KEY.format(char_id=char_id))
    r.delete(SNAPSHOT_TMP_KEY.format(char_id=char_id))
    r.delete(LIVENESS_KEY.format(char_id=char_id))
