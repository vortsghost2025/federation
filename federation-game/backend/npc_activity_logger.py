import json
import os
import time
from typing import Dict, Any, Optional, List

try:
    import redis
except ImportError:
    redis = None


PILOT_NPCS = {"char_101", "char_102"}
MAX_ENTRIES = 200
TTL_SECONDS = 7 * 86400


def _get_redis():
    """Get Redis client using existing environment pattern."""
    if redis is None:
        return None
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis.from_url(url, decode_responses=True, socket_timeout=5)


def _should_log(char_id: str) -> bool:
    """Check if this NPC should have activity logged (pilot only)."""
    return char_id in PILOT_NPCS


def log_npc_activity(
    char_id: str,
    entry_type: str,
    payload: Dict[str, Any],
    timestamp: Optional[int] = None
) -> bool:
    """
    Log an NPC activity entry to Redis ZSET.
    
    Args:
        char_id: NPC character ID
        entry_type: One of 'cognition', 'interaction', 'decision', 'chat'
        payload: Dictionary with entry-specific data
        timestamp: Unix timestamp (defaults to now)
    
    Returns:
        True if logged, False if skipped (not pilot NPC) or failed
    """
    if not _should_log(char_id):
        return False
    
    r = _get_redis()
    if r is None:
        return False
    
    ts = timestamp or int(time.time())
    entry = {
        "type": entry_type,
        "timestamp": ts,
        "char_id": char_id,
        "data": payload
    }
    
    try:
        key = f"npc_activity:{char_id}"
        r.zadd(key, {json.dumps(entry): ts})
        r.zremrangebyrank(key, 0, -(MAX_ENTRIES + 1))
        r.expire(key, TTL_SECONDS)
        return True
    except Exception:
        return False


def get_npc_activity_log(
    char_id: str,
    limit: int = 50,
    entry_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve NPC activity log entries.
    
    Args:
        char_id: NPC character ID
        limit: Maximum entries to return (most recent first)
        entry_types: Optional filter by entry type(s)
    
    Returns:
        List of activity entries, most recent first
    """
    r = _get_redis()
    if r is None:
        return []
    
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
        return results
    except Exception:
        return []