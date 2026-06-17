import json
import os
import time
from typing import Dict, Any, Optional, List

try:
    import redis
except ImportError:
    redis = None

try:
    from federation_game_db import db_manager
except ImportError:
    db_manager = None


# Phase 2: PILOT_NPCS guard removed — log ALL NPCs to Postgres
# Redis still capped at MAX_ENTRIES for fast recent lookups
MAX_ENTRIES = 200
TTL_SECONDS = 7 * 86400


def _get_redis():
    """Get Redis client using existing environment pattern."""
    if redis is None:
        return None
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


def log_npc_activity(
    char_id: str,
    entry_type: str,
    payload: Dict[str, Any],
    timestamp: Optional[int] = None
) -> bool:
    """
    Log an NPC activity entry to both Redis (fast recent) and Postgres (persistent).

    Phase 2: writes to ALL NPCs (no pilot guard). Redis capped at 200 entries/NPC.
    Postgres stores unlimited history for CSV export.

    Args:
        char_id: NPC character ID
        entry_type: One of 'cognition', 'interaction', 'decision', 'chat'
        payload: Dictionary with entry-specific data
        timestamp: Unix timestamp (defaults to now)

    Returns:
        True if logged to at least one backend, False if both failed
    """
    ts = timestamp or int(time.time())
    entry = {
        "type": entry_type,
        "timestamp": ts,
        "char_id": char_id,
        "data": payload
    }

    redis_ok = False
    postgres_ok = False

    # Write to Redis (recent entries, capped)
    r = _get_redis()
    if r is not None:
        try:
            key = f"npc_activity:{char_id}"
            r.zadd(key, {json.dumps(entry): ts})
            r.zremrangebyrank(key, 0, -(MAX_ENTRIES + 1))
            r.expire(key, TTL_SECONDS)
            redis_ok = True
        except Exception:
            pass

    # Write to Postgres (persistent, unlimited)
    if db_manager is not None and db_manager._initialized:
        try:
            # Pass payload directly as data_json
            postgres_ok = db_manager.log_npc_action(
                char_id=char_id,
                entry_type=entry_type,
                data_json=payload,
                timestamp=ts,
            )
        except Exception:
            pass

    return redis_ok or postgres_ok


def log_npc_turn_trace(
    turn: Dict[str, Any],
    memory_events: Optional[List[Dict[str, Any]]] = None,
    tool_events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Log a full NPC LLM turn trace to Postgres and a compact Redis feed."""
    turn_id = None
    if db_manager is not None and db_manager._initialized:
        try:
            turn_id = db_manager.log_npc_turn(
                turn=turn,
                memory_events=memory_events,
                tool_events=tool_events,
            )
        except Exception:
            turn_id = None

    compact = dict(turn)
    if turn_id:
        compact["turn_id"] = turn_id
    compact["input_text"] = (compact.get("input_text") or "")[:300]
    compact["system_prompt_text"] = (compact.get("system_prompt_text") or "")[:300]
    compact["output_text"] = (compact.get("output_text") or "")[:500]

    r = _get_redis()
    if r is not None:
        try:
            npc_id = compact.get("npc_id") or compact.get("char_id") or "unknown"
            ts = int(compact.get("timestamp") or time.time())
            key = f"npc_turns:{npc_id}"
            r.zadd(key, {json.dumps(compact): ts})
            r.zremrangebyrank(key, 0, -(MAX_ENTRIES + 1))
            r.expire(key, TTL_SECONDS)
        except Exception:
            pass

    return turn_id


def get_npc_turn_traces(
    npc_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_events: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve full NPC turn traces from Postgres."""
    if db_manager is not None and db_manager._initialized:
        try:
            return db_manager.get_npc_turns(
                npc_id=npc_id,
                limit=limit,
                offset=offset,
                include_events=include_events,
            )
        except Exception:
            pass
    return []


def get_npc_activity_log(
    char_id: str,
    limit: int = 50,
    entry_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve NPC activity log entries.

    Phase 2: Try Redis first (fast, recent), fallback to Postgres (complete history).

    Args:
        char_id: NPC character ID
        limit: Maximum entries to return (most recent first)
        entry_types: Optional filter by entry type(s)

    Returns:
        List of activity entries, most recent first
    """
    # Try Redis first
    r = _get_redis()
    if r is not None:
        try:
            key = f"npc_activity:{char_id}"
            raw = r.zrevrange(key, 0, limit - 1)
            results = []
            for item in raw:
                try:
                    entry = json.loads(item)
                    if entry_types is None or entry.get("type") in entry_types:
                        results.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue
            if results:
                return results
        except Exception:
            pass

    # Fallback to Postgres
    if db_manager is not None and db_manager._initialized:
        try:
            pg_results = db_manager.get_npc_action_log(
                char_id=char_id,
                entry_types=entry_types,
                limit=limit,
                offset=0,
            )
            # Convert to Redis-compatible format
            return [
                {
                    "type": r["entry_type"],
                    "timestamp": r["timestamp"],
                    "char_id": r["char_id"],
                    "data": r["data"],
                }
                for r in pg_results
            ]
        except Exception:
            pass

    return []


def export_npc_activity_csv(
    char_id: str,
    entry_types: Optional[List[str]] = None,
    limit: int = 10000,
) -> str:
    """
    Export NPC activity logs as CSV from PostgreSQL.

    Phase 2: Uses Postgres backend for complete history export.

    Args:
        char_id: NPC character ID
        entry_types: Optional filter by entry type(s)
        limit: Maximum entries to include

    Returns:
        CSV string with headers
    """
    if db_manager is not None and db_manager._initialized:
        try:
            return db_manager.export_npc_action_log_csv(
                char_id=char_id,
                entry_types=entry_types,
                limit=limit,
            )
        except Exception:
            pass
    return ""
