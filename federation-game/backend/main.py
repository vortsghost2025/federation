"""
Federation Game Backend - API + WebSocket Server
Star Trek LCARS Interface for Kids
"""

import json
import random
import hashlib
import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os

from factions import build_faction_system, FactionSystem
from timeline import TimelineSystem, Era
from npcs import build_npc_system, NPCSystem
from npc_chat import chat_with_npc, get_conversation_info
from npc_autonomy import (
    generate_thought,
    get_recent_thoughts,
    update_opinion,
    get_opinion,
    update_mood,
    get_mood,
    generate_action,
    get_recent_actions,
    get_world_events,
    update_npc_relationship,
    get_npc_relationships,
    simulation_tick,
    get_absence_report,
    get_relationship_summary,
    generate_goal,
    get_goals,
    advance_goal,
    set_goal_status,
    generate_goal_driven_action,
    make_decision,
    evaluate_decision_options,
    get_decision_log,
    get_world_state,
    get_world_condition,
    set_world_condition,
    get_world_state_history,
    update_world_state,
)
from quests import create_quest_library, QuestSystem, FactionAffiliation
from technology import create_technology_tree, TechTree
from dataclasses import asdict

from federation_game_db import db_manager
from state import game_state, seed_spatial_system
from faction_ai import FACTION_IDEOLOGY
from faction_dynamics import FACTION_DISPLAY
from routes.core import router as core_router
from routes.timeline import router as timeline_router
from routes.consciousness import router as consciousness_router
from routes.history import router as history_router
from routes.political import router as political_router
from routes.technology import router as technology_router
from routes.rivals import router as rivals_router
from routes.events import router as events_router
from routes.quests import router as quests_router
from routes.spatial import router as spatial_router
from routes.world import router as world_router
from routes.npcs import router as npcs_router
from routes.cognition import router as cognition_router
from routes.narrator import router as narrator_router
from routes.simulation import router as simulation_router
from routes.factions import router as factions_router
from routes.websocket import router as websocket_router
from routes.error_reports import router as error_reports_router
from routes.npc_logs import router as npc_logs_router
from routes.agents import router as agents_router
from routes.universe import router as universe_router
from map_endpoints import router as map_router
from data.events import EVENTS

try:
    from federation_game_rival_simulator import (
        RivalFederation,
        RivalFederationSimulator,
    )

    RIVAL_SYSTEM_AVAILABLE = True
except ImportError:
    RIVAL_SYSTEM_AVAILABLE = False

try:
    from federation_game_console import ConsciousnessSheet

    CONSCIOUSNESS_SYSTEM_AVAILABLE = True
except ImportError:
    CONSCIOUSNESS_SYSTEM_AVAILABLE = False

try:
    from federation_game_state import GameState as FederationGameState

    GAME_STATE_V2_AVAILABLE = True
except ImportError:
    GAME_STATE_V2_AVAILABLE = False

try:
    from federation_game_history_arc import HistoryArcOrchestrator

    HISTORY_ARC_AVAILABLE = True
except ImportError:
    HISTORY_ARC_AVAILABLE = False

try:
    from federation_game_political_integration import PoliticalEngine

    POLITICAL_SYSTEM_AVAILABLE = True
except ImportError:
    POLITICAL_SYSTEM_AVAILABLE = False

try:
    from npc_cognition import run_cognition, get_cognition_stats

    NPC_COGNITION_AVAILABLE = True
except ImportError:
    NPC_COGNITION_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# REDIS CONNECTION (shared observer pattern)
# ============================================================================

def _get_observer_redis():
    import redis

    return redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


# ============================================================================
# SIMULATION TICK INFRASTRUCTURE
# Status stored in Redis so all Uvicorn workers see the same state.
# Keys: fed:tick_status, fed:auto_tick_status  (Redis hashes)
# ============================================================================

_tick_lock = threading.Lock()  # per-process lock for thread safety within a worker
_TICK_REDIS_KEY = "fed:tick_status"
_AUTO_TICK_REDIS_KEY = "fed:auto_tick_status"


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
        pass  # Redis is optional for tick status; don't crash the tick


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
        # Simplified tick placeholder - actual logic should be refactored here
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
    _HARD_TIMEOUT = 300
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
        if time.time() - tick_start > _HARD_TIMEOUT:
            raise TimeoutError(
                f"Autonomous tick exceeded {_HARD_TIMEOUT}s during simulation_tick"
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


# ============================================================================
# FASTAPI APPLICATION SETUP
# ============================================================================

app = FastAPI(title="Federation Game Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_router)
app.include_router(timeline_router)
app.include_router(consciousness_router)
app.include_router(history_router)
app.include_router(political_router)
app.include_router(technology_router)
app.include_router(rivals_router)
app.include_router(spatial_router)
app.include_router(events_router)
app.include_router(quests_router)
app.include_router(world_router)
app.include_router(npcs_router)
app.include_router(cognition_router)
app.include_router(narrator_router)
app.include_router(simulation_router)
app.include_router(factions_router)
app.include_router(websocket_router)
app.include_router(error_reports_router)
app.include_router(npc_logs_router)
app.include_router(agents_router)
app.include_router(universe_router)
app.include_router(map_router)


@app.on_event("startup")
async def _clear_stale_tick_state():
    """Clear stale Redis tick state from previous process.

    When the backend restarts, daemon threads from the old process are killed
    but Redis still shows running=True. New process must clear these ghosts
    or the worker will get 409 on every tick.
    """
    try:
        r = _get_observer_redis()
        for key in (_TICK_REDIS_KEY, _AUTO_TICK_REDIS_KEY):
            raw = r.hgetall(key) if r else {}
            if raw.get("running") == "True":
                logger.warning(
                    "Clearing stale tick state: %s was stuck running since %s",
                    key,
                    raw.get("last_start", "?"),
                )
                r.hset(key, mapping={"running": "False", "last_end": str(time.time())})
    except Exception as exc:
        logger.warning("Failed to clear stale tick state: %s", exc)

    # Auto-seed spatial system on startup (idempotent)
    try:
        result = seed_spatial_system()
        if result.get("status") == "seeded":
            logger.info("Spatial system auto-seeded on startup: %s", result)
        else:
            logger.info("Spatial system already present, skipping seed")
    except Exception as exc:
        logger.warning("Failed to auto-seed spatial system: %s", exc)
