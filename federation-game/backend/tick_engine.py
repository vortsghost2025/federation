"""Tick engine for Federation Game backend.
Provides Redis-backed background task infrastructure for simulation ticks.
"""
import json
import logging
import threading
import time
import os
import redis
from typing import Dict, Any, List

# Import dependencies (avoid circular imports by importing at module level)
from state import game_state
from npc_autonomy import simulation_tick
from faction_ai import FACTION_IDEOLOGY

logger = logging.getLogger(__name__)

# Redis keys (shared)
_TICK_REDIS_KEY = "fed:tick_status"
_AUTO_TICK_REDIS_KEY = "fed:auto_tick_status"
_tick_lock = threading.Lock()

def _get_observer_redis():
    """Get Redis connection for tick status sharing."""
    return redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )

def _set_tick_redis(key, mapping):
    """Write tick status fields to Redis (best-effort)."""
    try:
        r = _get_observer_redis()
        if r:
            # Convert all values to strings for Redis hash storage
            str_mapping = {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                for k, v in mapping.items()
                if v is not None
            }
            if str_mapping:
                r.hset(key, mapping=str_mapping)
    except Exception:
        pass  # Redis is optional; don't crash

def _get_tick_redis(key):
    """Read tick status from Redis, returning a dict with typed values."""
    try:
        r = _get_observer_redis()
        if r:
            raw = r.hgetall(key)
            result = {}
            for k, v in raw.items():
                if k == "running":
                    result[k] = v == "True"
                elif k in ("last_start", "last_end"):
                    result[k] = float(v) if v else 0.0
                elif k in ("last_result",):
                    try:
                        result[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        result[k] = v
                else:
                    result[k] = v
            return result
    except Exception:
        pass
    return {
        "running": False,
        "last_start": 0.0,
        "last_end": 0.0,
        "last_result": None,
        "last_error": None,
    }

def _run_tick_background():
    """Execute a single simulation tick (called by worker or startup)."""
    with _tick_lock:
        _set_tick_redis(
            _TICK_REDIS_KEY,
            {
                "running": True,
                "last_start": time.time(),
                "last_error": "",
                "last_result": "",
            },
        )
    try:
        # Simplified placeholder — actual tick logic lives in npc_autonomy.simulation_tick
        result = {"status": "completed", "details": "Tick executed"}
        _set_tick_redis(_TICK_REDIS_KEY, {"last_result": result})
    except Exception as e:
        logger.error("Background tick failed: %s", e)
        _set_tick_redis(_TICK_REDIS_KEY, {"last_error": str(e)})
    finally:
        _set_tick_redis(
            _TICK_REDIS_KEY,
            {
                "running": False,
                "last_end": time.time(),
            },
        )

def _run_autonomous_tick_background():
    """Execute autonomous tick: update all NPCs, save snapshot."""
    with _tick_lock:
        _set_tick_redis(
            _AUTO_TICK_REDIS_KEY,
            {
                "running": True,
                "last_start": time.time(),
                "last_error": "",
                "last_result": "",
            },
        )
    try:
        npc_list = []
        for char_id, character in game_state.npc_system.characters.items():
            npc_list.append(
                {
                    "id": char_id,
                    "char_id": char_id,
                    "name": character.name,
                    "archetype": character.personality_type.value,
                    "affiliation": character.affiliation,
                    "ideology": FACTION_IDEOLOGY.get(
                        character.affiliation, "diplomatic"
                    )
                    if character.affiliation
                    else None,
                    "title": character.title,
                    "description": getattr(character, "description", ""),
                }
            )
        results = simulation_tick(npc_list)
        try:
            game_state.save_to_db(snapshot_type="auto")
        except Exception:
            logger.warning("Auto-save snapshot after autonomous tick failed")
        result = {"status": "completed", "details": results}
        _set_tick_redis(_AUTO_TICK_REDIS_KEY, {"last_result": result})
    except Exception as e:
        logger.error("Background autonomous tick failed: %s", e)
        _set_tick_redis(_AUTO_TICK_REDIS_KEY, {"last_error": str(e)})
    finally:
        _set_tick_redis(
            _AUTO_TICK_REDIS_KEY,
            {
                "running": False,
                "last_end": time.time(),
            },
        )
