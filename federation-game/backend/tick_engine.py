"""Tick engine for Federation Game backend.
Provides Redis-backed background task infrastructure for simulation ticks.
"""
import json
import logging
import threading
import time
import os
import redis
from typing import Dict, Any, List, Optional

# Import dependencies (avoid circular imports by importing at module level)
from state import game_state
from npc_autonomy import simulation_tick
from faction_ai import FACTION_IDEOLOGY
from simulation_operator import run_simulation_operator_tick

logger = logging.getLogger(__name__)

# Redis keys (shared)
_TICK_REDIS_KEY = "fed:tick_status"
_AUTO_TICK_REDIS_KEY = "fed:auto_tick_status"
_tick_lock = threading.Lock()

# Optional watchdog support
WATCHDOG_AVAILABLE = False
try:
    from tick_watchdog import try_start_tick, tick_heartbeat, complete_tick
    WATCHDOG_AVAILABLE = True
except ImportError:
    pass


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
        pass


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


def _read_world_state_for_cognition():
    """Read world state from Redis for cognition."""
    try:
        r = _get_observer_redis()
        if r:
            raw = r.hgetall("world_state")
            return {k: float(v) for k, v in raw.items()} if raw else {}
    except Exception:
        pass
    return {}


def _run_autonomous_tick_background(game_state=None, faction_ideology=None):
    tick_id = int(time.time() * 1000)
    if WATCHDOG_AVAILABLE:
        if not try_start_tick(tick_id):
            logger.warning("Could not start tick %d: another tick is active", tick_id)
            return
    if not _tick_lock.acquire(blocking=False):
        logger.warning("Legacy lock failed for tick %d", tick_id)
        return
    try:
        _set_tick_redis(
            _AUTO_TICK_REDIS_KEY,
            {
                "running": True,
                "last_start": time.time(),
                "last_error": "",
                "last_result": "",
                "tick_id": tick_id,
            },
        )
        if WATCHDOG_AVAILABLE:
            tick_heartbeat()
        results = run_simulation_operator_tick(game_state, FACTION_IDEOLOGY)
        if WATCHDOG_AVAILABLE:
            tick_heartbeat()
        try:
            game_state.save_to_db(snapshot_type="auto")
        except Exception:
            logger.warning("Auto-save snapshot after autonomous tick failed")
        result = {"status": "completed", "details": results}
        _set_tick_redis(_AUTO_TICK_REDIS_KEY, {"last_result": result})
        if WATCHDOG_AVAILABLE:
            complete_tick(tick_id)
    except Exception as e:
        logger.error("Autonomous tick failed: %s", e)
        _set_tick_redis(_AUTO_TICK_REDIS_KEY, {"last_error": str(e)})
        if WATCHDOG_AVAILABLE:
            complete_tick(tick_id)
    finally:
        _set_tick_redis(
            _AUTO_TICK_REDIS_KEY,
            {
                "running": False,
                "last_end": time.time(),
            },
        )
        if WATCHDOG_AVAILABLE:
            complete_tick(tick_id)
        _tick_lock.release()


# Public aliases for routes/simulation.py imports
get_tick_redis = _get_tick_redis
set_tick_redis = _set_tick_redis
run_tick_background = _run_tick_background
run_autonomous_tick_background = _run_autonomous_tick_background
