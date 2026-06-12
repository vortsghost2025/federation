"""
Simulation route handlers — extracted from main.py + new observer endpoints
"""

import json
import os
import threading
import time
import logging

from fastapi import APIRouter, HTTPException, Query
from state import game_state
from faction_ai import FACTION_IDEOLOGY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["simulation"])


@router.get("/simulation")
async def simulation_overview():
    """Compatibility summary for legacy /simulation health checks."""
    from tick_engine import (
        get_tick_redis,
        _TICK_REDIS_KEY,
        _AUTO_TICK_REDIS_KEY,
    )

    return {
        "status": "ok",
        "turn": game_state.turn,
        "tick": get_tick_redis(_TICK_REDIS_KEY),
        "autonomous_tick": get_tick_redis(_AUTO_TICK_REDIS_KEY),
        "endpoints": {
            "status": "/simulation/status",
            "tick": "/simulation/tick",
            "tick_status": "/simulation/tick/status",
            "autonomous_tick": "/simulation/autonomous/tick",
            "autonomous_status": "/simulation/autonomous/status",
            "events": "/simulation/events",
            "factions": "/simulation/factions",
            "npcs": "/simulation/npcs/activity",
        },
    }


# ---------------------------------------------------------------------------
# Simulation tick endpoints
# ---------------------------------------------------------------------------


@router.post("/simulation/tick")
async def simulation_tick_endpoint():
    from tick_engine import (
        _tick_lock,
        get_tick_redis,
        set_tick_redis,
        _TICK_REDIS_KEY,
        run_tick_background,
    )
    from fastapi.responses import JSONResponse

    if not _tick_lock.acquire(blocking=False):
        status = get_tick_redis(_TICK_REDIS_KEY)
        return JSONResponse(
            status_code=409,
            content={
                "status": "already_running",
                "started_at": status.get("last_start", 0.0),
            },
        )
    try:
        status = get_tick_redis(_TICK_REDIS_KEY)
        if status.get("running"):
            return JSONResponse(
                status_code=409,
                content={
                    "status": "already_running",
                    "started_at": status.get("last_start", 0.0),
                },
            )
        tick_id = f"tick_{int(time.time() * 1000)}"
        thread = threading.Thread(target=run_tick_background, daemon=True)
        thread.start()
        return {"status": "started", "tick_id": tick_id}
    finally:
        _tick_lock.release()


@router.get("/simulation/tick/status")
async def simulation_tick_status():
    from tick_engine import get_tick_redis, _TICK_REDIS_KEY

    status = get_tick_redis(_TICK_REDIS_KEY)
    if status.get("running"):
        result = {
            "status": "running",
            "started_at": status.get("last_start", 0.0),
            "elapsed": time.time() - status.get("last_start", 0.0),
        }
    elif status.get("last_error"):
        ls = status.get("last_start", 0.0) or 0.0
        le = status.get("last_end", 0.0) or 0.0
        result = {
            "status": "failed",
            "error": status["last_error"],
            "started_at": ls,
            "ended_at": le,
            "duration": (le - ls) if ls and le else None,
        }
    elif status.get("last_result"):
        ls = status.get("last_start", 0.0) or 0.0
        le = status.get("last_end", 0.0) or 0.0
        result = {
            "status": "completed",
            "started_at": ls,
            "ended_at": le,
            "duration": (le - ls) if ls and le else None,
            "result": status["last_result"],
        }
    else:
        result = {"status": "idle"}
    return result


@router.post("/simulation/autonomous/tick")
async def autonomous_simulation_tick():
    """Autonomous simulation tick: fire-and-forget with background thread.

    Returns HTTP 202 immediately. The tick runs in a background thread.
    Poll /simulation/autonomous/status for results.
    """
    from tick_engine import (
        get_tick_redis,
        _AUTO_TICK_REDIS_KEY,
        run_autonomous_tick_background,
    )
    from fastapi.responses import JSONResponse

    status = get_tick_redis(_AUTO_TICK_REDIS_KEY)
    if status.get("running"):
        return JSONResponse(
            status_code=409,
            content={
                "status": "already_running",
                "started_at": status.get("last_start", 0.0),
            },
        )

    tick_id = f"auto_tick_{int(time.time() * 1000)}"
    thread = threading.Thread(
        target=run_autonomous_tick_background,
        args=(game_state, FACTION_IDEOLOGY),
        daemon=True,
    )
    thread.start()
    return JSONResponse(
        status_code=202,
        content={"status": "started", "tick_id": tick_id},
    )


@router.get("/simulation/autonomous/status")
async def autonomous_tick_status():
    from tick_engine import get_tick_redis, set_tick_redis, _AUTO_TICK_REDIS_KEY

    STALE_THRESHOLD_SECONDS = 300  # 5 minutes

    status = get_tick_redis(_AUTO_TICK_REDIS_KEY)
    if status.get("running"):
        elapsed = time.time() - status.get("last_start", 0.0)
        if elapsed > STALE_THRESHOLD_SECONDS:
            # Ghost tick — previous process was killed before finally block ran.
            # Clear the stale state so the worker can start a fresh tick.
            logger.warning(
                "Autonomous tick stuck for %.0fs — clearing stale state", elapsed
            )
            set_tick_redis(
                _AUTO_TICK_REDIS_KEY,
                {
                    "running": False,
                    "last_end": time.time(),
                    "last_error": "stale_tick_cleared",
                },
            )
            result = {"status": "failed", "error": "stale_tick_cleared", "elapsed": elapsed}
        else:
            result = {
                "status": "running",
                "started_at": status.get("last_start", 0.0),
                "elapsed": elapsed,
            }
    elif status.get("last_error"):
        ls = status.get("last_start", 0.0) or 0.0
        le = status.get("last_end", 0.0) or 0.0
        result = {
            "status": "failed",
            "error": status["last_error"],
            "started_at": ls,
            "ended_at": le,
            "duration": (le - ls) if ls and le else None,
        }
    elif status.get("last_result"):
        ls = status.get("last_start", 0.0) or 0.0
        le = status.get("last_end", 0.0) or 0.0
        result = {
            "status": "completed",
            "started_at": ls,
            "ended_at": le,
            "duration": (le - ls) if ls and le else None,
            "result": status["last_result"],
        }
    else:
        result = {"status": "idle"}
    return result


@router.get("/simulation/operator/status")
async def simulation_operator_status():
    from simulation_operator import get_operator_status

    return get_operator_status()


@router.post("/simulation/operator/tick")
async def simulation_operator_tick():
    """Manual trigger for a supervised autonomous tick."""
    from tick_engine import (
        get_tick_redis,
        _AUTO_TICK_REDIS_KEY,
        run_autonomous_tick_background,
    )
    from fastapi.responses import JSONResponse

    status = get_tick_redis(_AUTO_TICK_REDIS_KEY)
    if status.get("running"):
        return JSONResponse(
            status_code=409,
            content={
                "status": "already_running",
                "started_at": status.get("last_start", 0.0),
            },
        )

    tick_id = f"operator_tick_{int(time.time() * 1000)}"
    thread = threading.Thread(
        target=run_autonomous_tick_background,
        args=(game_state, FACTION_IDEOLOGY),
        daemon=True,
    )
    thread.start()
    return JSONResponse(status_code=202, content={"status": "started", "tick_id": tick_id})


# ---------------------------------------------------------------------------
# Lazy shared Redis connection for observer endpoints
# ---------------------------------------------------------------------------


def _get_observer_redis():
    import redis as _redis

    return _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


# ---------------------------------------------------------------------------
# Simulation observer endpoints
# ---------------------------------------------------------------------------


@router.get("/simulation/status")
async def simulation_status():
    """Read-only view of the autonomous simulation's current state.
    Uses Redis pipelines to batch commands instead of N+1 sequential calls.
    """
    from npc_autonomy import (
        get_world_state,
        get_world_events,
    )
    from state import get_cascade_summary, EVENT_CASCADE_AVAILABLE
    from faction_dynamics import get_faction_dynamics

    _r = _get_observer_redis()
    result = {
        "world_state": {},
        "faction_dynamics": {},
        "cascade_summary": {},
        "recent_events": [],
        "npc_activity_summary": {},
        "pending_items": {},
    }

    # World state
    try:
        result["world_state"] = get_world_state()
    except Exception:
        pass

    # Faction dynamics
    try:
        result["faction_dynamics"] = get_faction_dynamics()
    except Exception:
        pass

    # Event cascade summary
    try:
        if EVENT_CASCADE_AVAILABLE:
            result["cascade_summary"] = get_cascade_summary()
    except Exception:
        pass

    # Recent events from world state
    try:
        ws = result.get("world_state", {})
        recent = ws.get("recent_events", [])[-10:]
        result["recent_events"] = recent
    except Exception:
        pass

    # NPC activity summary
    try:
        activity = {}
        for npc_id, npc_data in (result.get("world_state", {}).get("npcs", {})).items():
            last_active = npc_data.get("last_active", 0)
            goals = len(npc_data.get("current_goals", []))
            activity[npc_id] = {
                "last_active": last_active,
                "goals": goals,
            }
        result["npc_activity_summary"] = activity
    except Exception:
        pass

    # Pending items (tick queue, etc.)
    try:
        _r = _get_observer_redis()
        pending = {
            "tick_queue": _r.llen("tick_queue") or 0,
            "event_cascade": _r.llen("event_cascade") or 0,
        }
        result["pending_items"] = pending
    except Exception:
        pass

    # Tick info — expose turn count and last tick timestamp for the frontend
    try:
        from tick_engine import get_tick_redis, _TICK_REDIS_KEY, _AUTO_TICK_REDIS_KEY
        from state import game_state

        tick_info = get_tick_redis(_TICK_REDIS_KEY)
        auto_tick_info = get_tick_redis(_AUTO_TICK_REDIS_KEY)
        result["tick_count"] = game_state.turn
        if tick_info and tick_info.get("last_end"):
            result["last_tick_timestamp"] = int(tick_info["last_end"])
        elif auto_tick_info and auto_tick_info.get("last_end"):
            result["last_tick_timestamp"] = int(auto_tick_info["last_end"])
        if tick_info and tick_info.get("last_result"):
            result["last_tick_result"] = tick_info["last_result"]
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# GET /simulation/state — alias for legacy frontend callers (earth.js, etc.)
# ---------------------------------------------------------------------------


@router.get("/simulation/state")
async def simulation_state():
    """Alias for /simulation/status — legacy frontends call this."""
    return await simulation_status()


@router.get("/simulation/world/state")
async def simulation_world_state():
    """Alias for /simulation/status — legacy frontends call /world/state."""
    return await simulation_status()


# ---------------------------------------------------------------------------
# GET /simulation/factions — detailed faction AI status
# ---------------------------------------------------------------------------


@router.get("/simulation/factions")
async def simulation_factions():
    """Detailed faction AI status for the simulation observer.
    Combines faction_system (power, allies, enemies) with
    faction_dynamics (cohesion, stances) and recent actions from Redis."""
    from faction_dynamics import (
        KNOWN_FACTIONS,
        FACTION_DISPLAY,
        get_faction_detail,
        get_faction_stances,
    )

    _r = _get_observer_redis()
    result = {}

    # Pipeline: batch actions + power for all factions
    try:
        pipe = _r.pipeline(transaction=False)
        for fid in KNOWN_FACTIONS:
            pipe.zrevrange(f"faction_actions:{fid}", 0, 4)
            pipe.get(f"faction_power:{fid}")
        pipe_results = pipe.execute()
    except Exception:
        pipe_results = [None, None] * len(KNOWN_FACTIONS)

    for i, fid in enumerate(KNOWN_FACTIONS):
        faction_data = {
            "id": fid,
            "name": FACTION_DISPLAY.get(fid, fid),
            "dynamics": {},
            "stances": {},
            "recent_actions": [],
            "power": 0.0,
        }

        # Dynamics (cohesion, influence, standing, vigilance, etc.)
        try:
            faction_data["dynamics"] = get_faction_detail(fid) or {}
        except Exception:
            pass

        # Stances toward other factions
        try:
            faction_data["stances"] = get_faction_stances(fid)
        except Exception:
            pass

        # Recent actions from Redis
        try:
            actions_raw = pipe_results[i * 2] if pipe_results else []
            faction_data["recent_actions"] = []
            for a in actions_raw or []:
                try:
                    faction_data["recent_actions"].append(json.loads(a))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        # Power from Redis
        try:
            power_raw = pipe_results[i * 2 + 1] if pipe_results else None
            faction_data["power"] = float(power_raw) if power_raw else 0.0
        except Exception:
            pass

        # Faction system in-memory data (allies, enemies, ideology)
        try:
            fs_faction = game_state.faction_system.factions.get(fid)
            if fs_faction:
                faction_data["ideology"] = (
                    fs_faction.ideology.value
                    if hasattr(fs_faction.ideology, "value")
                    else str(fs_faction.ideology)
                )
                faction_data["allies"] = (
                    list(fs_faction.ally_factions)
                    if hasattr(fs_faction, "ally_factions")
                    else []
                )
                faction_data["enemies"] = (
                    list(fs_faction.enemy_factions)
                    if hasattr(fs_faction, "enemy_factions")
                    else []
                )
                # Override power from faction_system if Redis was empty
                if not faction_data["power"] and hasattr(
                    fs_faction, "accumulated_power"
                ):
                    faction_data["power"] = fs_faction.accumulated_power
        except Exception:
            pass

        # Spatial fields (optional, graceful fallback)
        try:
            from state import SPATIAL_SYSTEM_AVAILABLE, is_spatial_enabled

            if SPATIAL_SYSTEM_AVAILABLE and is_spatial_enabled():
                from routes.spatial import (
                    get_faction_home,
                    get_faction_territories,
                    get_faction_discoveries,
                )

                home = get_faction_home(fid)
                faction_data["home_sector_id"] = home.home_sector_id if home else None
                territories = get_faction_territories(fid)
                faction_data["territory"] = [
                    {
                        "sector_id": t.sector_id,
                        "control_level": t.control_level,
                        "claim_type": t.claim_type,
                    }
                    for t in territories
                ]
                faction_discoveries = get_faction_discoveries(fid)
                faction_data["discovered_factions"] = [
                    d.faction_b_id if d.faction_a_id == fid else d.faction_a_id
                    for d in faction_discoveries
                    if d.state in ("detected", "contacted", "relations_open")
                ]
                faction_data["expansion_policy"] = (
                    home.expansion_policy if home else None
                )
            else:
                faction_data["home_sector_id"] = None
                faction_data["territory"] = []
                faction_data["discovered_factions"] = []
                faction_data["expansion_policy"] = None
        except Exception:
            faction_data["home_sector_id"] = None
            faction_data["territory"] = []
            faction_data["discovered_factions"] = []
            faction_data["expansion_policy"] = None

        result[fid] = faction_data

    return result


# ---------------------------------------------------------------------------
# GET /simulation/events  —  world + cascade + broadcast events
# ---------------------------------------------------------------------------


@router.get("/simulation/events")
async def simulation_events(limit: int = 50):
    """World events and cascade events for the simulation observer."""
    from npc_autonomy import get_world_events

    _r = _get_observer_redis()
    limit = min(max(limit, 1), 100)

    result = {
        "world_events": [],
        "cascade_events": [],
        "broadcast_events": [],
    }

    # World events from npc_autonomy
    try:
        result["world_events"] = get_world_events(limit=limit)
    except Exception:
        pass

    # Batch cascade + broadcast fetch in one pipeline
    try:
        pipe = _r.pipeline(transaction=False)
        pipe.zrevrange("cascade_reactions", 0, limit - 1)
        pipe.zrevrange("npc_broadcast_events", 0, min(limit, 20) - 1)
        pipe_results = pipe.execute()

        for c in pipe_results[0]:
            try:
                result["cascade_events"].append(json.loads(c))
            except (json.JSONDecodeError, TypeError):
                pass

        for b in pipe_results[1]:
            try:
                result["broadcast_events"].append(json.loads(b))
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# GET /simulation/npcs/activity  —  NPC activity feed with moods/thoughts/actions
# ---------------------------------------------------------------------------


@router.get("/simulation/npcs/activity")
async def simulation_npcs_activity():
    """NPC activity feed for the simulation observer.
    Uses Redis pipelines: 5 batched calls instead of N+1 sequential."""
    _r = _get_observer_redis()

    # Build NPC list from in-memory game state
    npc_chars = list(game_state.npc_system.characters.items())
    char_ids = [char_id for char_id, _ in npc_chars]

    # Pipeline 1: moods (GET x N)
    try:
        pipe_moods = _r.pipeline(transaction=False)
        for cid in char_ids:
            pipe_moods.get(f"npc_mood:{cid}")
        moods = pipe_moods.execute()
    except Exception:
        moods = [None] * len(char_ids)

    # Pipeline 2: thoughts (ZREVRANGE x N)
    try:
        pipe_thoughts = _r.pipeline(transaction=False)
        for cid in char_ids:
            pipe_thoughts.zrevrange(f"npc_thoughts:{cid}", 0, 2)
        thoughts = pipe_thoughts.execute()
    except Exception:
        thoughts = [[]] * len(char_ids)

    # Pipeline 3: decisions (LRANGE x N)
    try:
        pipe_decisions = _r.pipeline(transaction=False)
        for cid in char_ids:
            pipe_decisions.lrange(f"npc_decisions:{cid}", 0, 2)
        decisions = pipe_decisions.execute()
    except Exception:
        decisions = [[]] * len(char_ids)

    # Pipeline 4: actions (LRANGE x N)
    try:
        pipe_actions = _r.pipeline(transaction=False)
        for cid in char_ids:
            pipe_actions.lrange(f"npc_actions:{cid}", 0, 2)
        actions = pipe_actions.execute()
    except Exception:
        actions = [[]] * len(char_ids)

    # Pipeline 5: state (HGETALL x N)
    try:
        pipe_state = _r.pipeline(transaction=False)
        for cid in char_ids:
            pipe_state.hgetall(f"npc_state:{cid}")
        states = pipe_state.execute()
    except Exception:
        states = [{}] * len(char_ids)

    # Assemble results from pipeline responses
    npcs = []
    for i, (char_id, character) in enumerate(npc_chars):
        npc_data = {
            "char_id": char_id,
            "name": character.name,
            "affiliation": character.affiliation,
            "archetype": character.personality_type.value
            if hasattr(character, "personality_type")
            and hasattr(character.personality_type, "value")
            else "unknown",
            "mood": moods[i] or "unknown",
            "recent_thoughts": [],
            "recent_decisions": [],
            "recent_actions": [],
            "corruption_level": 0.0,
            "rumor_level": 0.0,
            "status": "active",
        }

        # Thoughts
        try:
            for t in thoughts[i] or []:
                try:
                    npc_data["recent_thoughts"].append(json.loads(t))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        # Decisions
        try:
            for d in decisions[i] or []:
                try:
                    npc_data["recent_decisions"].append(json.loads(d))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        # Actions
        try:
            for a in actions[i] or []:
                try:
                    npc_data["recent_actions"].append(json.loads(a))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        # State (corruption, rumor, status)
        try:
            state = states[i] or {}
            npc_data["corruption_level"] = float(state.get("corruption_level", 0))
            npc_data["rumor_level"] = float(state.get("rumor_level", 0))
            npc_data["status"] = state.get("status", "active")
        except Exception:
            pass

        # Fallback corruption from Character object
        try:
            if not npc_data["corruption_level"] and hasattr(
                character, "corruption_level"
            ):
                npc_data["corruption_level"] = float(character.corruption_level)
        except Exception:
            pass

        npcs.append(npc_data)

    return {"npcs": npcs, "count": len(npcs)}


# ---------------------------------------------------------------------------
# GET /simulation/npc-quests  —  quest log + per-NPC quest detail
# ---------------------------------------------------------------------------


@router.get("/simulation/npc-quests")
async def simulation_npc_quests(limit: int = 20):
    """NPC quest log and global stats for the simulation observer."""
    try:
        from npc_quest_engine import NPCQuestEngine
        from quests import create_quest_library

        _r = _get_observer_redis()
        qs = create_quest_library()
        engine = NPCQuestEngine(quest_system=qs, redis_client=_r)
        return {
            "quest_log": engine.get_quest_log(limit=limit),
            "stats": "see per-npc endpoints",
        }
    except Exception as e:
        # Graceful fallback: read quest_events ZSET directly from Redis
        try:
            _r = _get_observer_redis()
            raw = _r.zrevrange("quest_events", 0, limit - 1)
            quest_log = []
            for item in raw:
                try:
                    quest_log.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    pass
            return {"quest_log": quest_log}
        except Exception:
            return {"quest_log": [], "error": str(e)}


@router.get("/simulation/npc-quests/{char_id}")
async def simulation_npc_quest_detail(char_id: str):
    """Per-NPC quest summary: active, completed, failed, stats."""
    try:
        from npc_quest_engine import NPCQuestEngine
        from quests import create_quest_library

        _r = _get_observer_redis()
        qs = create_quest_library()
        engine = NPCQuestEngine(quest_system=qs, redis_client=_r)
        return engine.get_npc_quest_summary(char_id)
    except Exception as e:
        # Graceful fallback: read from Redis directly
        try:
            _r = _get_observer_redis()
            active_raw = _r.hgetall(f"npc_quests:active:{char_id}") or {}
            active_quests = []
            for qid, qjson in active_raw.items():
                try:
                    active_quests.append(json.loads(qjson))
                except (json.JSONDecodeError, TypeError):
                    pass
            completed_count = _r.llen(f"npc_quests:completed:{char_id}") or 0
            failed_count = _r.llen(f"npc_quests:failed:{char_id}") or 0
            return {
                "active_quests": active_quests,
                "completed_count": completed_count,
                "failed_count": failed_count,
            }
        except Exception:
            return {"char_id": char_id, "error": str(e)}


# ---------------------------------------------------------------------------
# GET /simulation/faction-tech  —  faction tech research summary
# ---------------------------------------------------------------------------


@router.get("/simulation/faction-tech")
async def simulation_faction_tech():
    """Faction tech research summary for all 8 factions."""
    try:
        from faction_tech_research import FactionTechBridge
        from technology import create_technology_tree
        from faction_ai import FACTION_IDEOLOGY

        _r = _get_observer_redis()
        tree = create_technology_tree()
        bridge = FactionTechBridge(tech_tree=tree, redis_client=_r)
        summaries = {}
        for fid in FACTION_IDEOLOGY:
            summaries[fid] = bridge.get_faction_tech_summary(fid)
        return {"factions": summaries}
    except Exception as e:
        # Graceful fallback: read Redis directly
        try:
            _r = _get_observer_redis()
            summaries = {}
            for fid in FACTION_IDEOLOGY:
                summary = {
                    "active_research": None,
                    "completed_techs": [],
                    "research_points": 0.0,
                    "unlocks": [],
                    "progress_percent": 0.0,
                }
                raw = _r.get(f"faction_tech:active:{fid}")
                if raw:
                    try:
                        proj = json.loads(raw)
                        summary["active_research"] = proj
                        summary["progress_percent"] = proj.get(
                            "progress_percentage", 0.0
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass
                completed = _r.smembers(f"faction_tech:completed:{fid}")
                if completed:
                    summary["completed_techs"] = list(completed)
                pts = _r.get(f"faction_tech:points:{fid}")
                if pts:
                    summary["research_points"] = float(pts)
                unlocks = _r.smembers(f"faction_tech:unlocks:{fid}")
                if unlocks:
                    summary["unlocks"] = list(unlocks)
                summaries[fid] = summary
            return {"factions": summaries}
        except Exception:
            return {"factions": {}, "error": str(e)}


@router.get("/simulation/faction-tech/{faction_id}")
async def simulation_faction_tech_detail(faction_id: str):
    """Per-faction tech research detail: active, completed, unlocks."""
    try:
        from faction_tech_research import FactionTechBridge
        from technology import create_technology_tree

        _r = _get_observer_redis()
        tree = create_technology_tree()
        bridge = FactionTechBridge(tech_tree=tree, redis_client=_r)
        return bridge.get_faction_tech_summary(faction_id)
    except Exception as e:
        return {"faction_id": faction_id, "error": str(e)}


# ---------------------------------------------------------------------------
# GET /simulation/choice-resolutions  —  ideology voting stats
# ---------------------------------------------------------------------------


@router.get("/simulation/choice-resolutions")
async def simulation_choice_resolutions(limit: int = 20):
    """Recent faction choice resolution history."""
    try:
        from autonomous_choice_resolver import AutonomousChoiceResolver

        _r = _get_observer_redis()
        resolver = AutonomousChoiceResolver(redis_client=_r)
        return {
            "stats": resolver.get_resolution_stats(),
        }
    except Exception as e:
        # Graceful fallback: read Redis directly
        try:
            _r = _get_observer_redis()
            raw = _r.hgetall("choice_resolution_stats")
            stats = {k: int(v) for k, v in raw.items()}
            return {"stats": stats}
        except Exception:
            return {"stats": {}, "error": str(e)}


@router.get("/simulation/choice-resolutions/{faction_id}")
async def simulation_choice_resolution_faction(faction_id: str, limit: int = 20):
    """Per-faction choice voting history."""
    try:
        from autonomous_choice_resolver import AutonomousChoiceResolver

        _r = _get_observer_redis()
        resolver = AutonomousChoiceResolver(redis_client=_r)
        return {
            "faction_id": faction_id,
            "choice_history": resolver.get_faction_choice_history(
                faction_id, limit=limit
            ),
        }
    except Exception as e:
        # Graceful fallback: read Redis directly
        try:
            _r = _get_observer_redis()
            key = f"faction_choice_history:{faction_id}"
            entries = _r.lrange(key, 0, limit - 1)
            return {
                "faction_id": faction_id,
                "choice_history": list(entries),
            }
        except Exception:
            return {"faction_id": faction_id, "choice_history": [], "error": str(e)}


# ---------------------------------------------------------------------------
# GET /simulation/nim-stats — NIM client statistics
# ---------------------------------------------------------------------------


@router.get("/simulation/nim-stats")
async def simulation_nim_stats():
    """NIM client statistics — keys available, call counts, fallbacks."""
    try:
        from nvidia_nim_client import get_nim_client

        client = get_nim_client()
        stats = client.get_stats()
        return {"status": "ok", **stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}
