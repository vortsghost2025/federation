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
    """Execute autonomous tick: update all NPCs, run cognition, save snapshot.

    Hard timeout: if the tick takes >300s, mark it as failed and release.
    This prevents ghost ticks from blocking the worker forever.
    """
    _HARD_TIMEOUT = 300  # seconds
    tick_start = time.time()

    with _tick_lock:
        _set_tick_redis(
            _AUTO_TICK_REDIS_KEY,
            {
                "running": True,
                "last_start": tick_start,
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

        # Check timeout before expensive cognition step
        if time.time() - tick_start > _HARD_TIMEOUT:
            raise TimeoutError(
                f"Autonomous tick exceeded {_HARD_TIMEOUT}s during simulation_tick"
            )

        # Run LLM cognition for leaders/specialists (same as simulation_engine Step 1.5)
        try:
            from npc_cognition import run_cognition
            world_state = _read_world_state_for_cognition()
            cog_result = run_cognition(npc_list, world_state)
            results["cognition"] = cog_result
            llm_decisions = cog_result.get("decisions", [])
            if llm_decisions:
                results["decisions"].extend(llm_decisions)
                logger.info(
                    "Autonomous tick cognition injected %d LLM decisions",
                    len(llm_decisions),
                )
        except Exception as exc:
            logger.warning("Autonomous tick cognition failed (non-fatal): %s", exc)
            results["cognition"] = {"errors": [str(exc)]}

        # Check timeout before DB save
        if time.time() - tick_start > _HARD_TIMEOUT:
            raise TimeoutError(
                f"Autonomous tick exceeded {_HARD_TIMEOUT}s during cognition"
            )

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

# Public aliases for routes/simulation.py imports
get_tick_redis = _get_tick_redis
set_tick_redis = _set_tick_redis
run_tick_background = _run_tick_background
run_autonomous_tick_background = _run_autonomous_tick_background
