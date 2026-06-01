"""
Cognition route handlers — extracted from main.py
"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["cognition"])


@router.get("/cognition")
async def cognition_overview():
    """Compatibility summary for legacy /cognition health checks."""
    try:
        from npc_cognition import get_cognition_stats

        stats = get_cognition_stats()
        return {
            "status": "ok",
            "available": True,
            "endpoints": {
                "tick": "/cognition/tick",
                "stats": "/simulation/cognition/stats",
            },
            "stats": stats,
        }
    except ImportError:
        return {
            "status": "unavailable",
            "available": False,
            "endpoints": {
                "tick": "/cognition/tick",
                "stats": "/simulation/cognition/stats",
            },
            "error": "npc_cognition module not imported",
        }
    except Exception as e:
        return {
            "status": "error",
            "available": True,
            "endpoints": {
                "tick": "/cognition/tick",
                "stats": "/simulation/cognition/stats",
            },
            "error": str(e),
        }


@router.post("/cognition/tick")
async def cognition_tick():
    """Manually trigger LLM cognition for eligible NPCs.

    This is a standalone endpoint for testing/observation.
    Normally, cognition runs inside autonomous_tick() Step 1.5.
    """
    try:
        from tick_engine import _get_observer_redis
        try:
            from main import COGNITION_AVAILABLE, logger
        except ImportError:
            COGNITION_AVAILABLE = False
            logger = None
    except ImportError:
        COGNITION_AVAILABLE = False
        _get_observer_redis = None
        logger = None

    if not COGNITION_AVAILABLE:
        return {"status": "unavailable", "error": "npc_cognition module not imported"}

    _r = _get_observer_redis()
    try:
        from npc_cognition import run_cognition
    except ImportError:
        return {"status": "unavailable", "error": "npc_cognition module not imported"}

    npc_list = []
    for char_id, character in game_state.npc_system.characters.items():
        npc_list.append(
            {
                "id": char_id,
                "char_id": char_id,
                "name": character.name,
                "archetype": character.personality_type.value,
                "affiliation": character.affiliation,
                "title": character.title,
            }
        )

    world_state = {}
    try:
        raw_ws = _r.hgetall("world_state")
        if raw_ws:
            world_state = raw_ws
    except Exception:
        pass

    try:
        result = run_cognition(npc_list, world_state)
        return {"status": "completed", **result}
    except Exception as e:
        if logger:
            logger.error("Cognition tick failed: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/simulation/cognition/stats")
async def cognition_stats():
    """Get cognition layer statistics for the observer dashboard."""
    try:
        from tick_engine import _get_observer_redis
        try:
            from main import COGNITION_AVAILABLE, logger
        except ImportError:
            COGNITION_AVAILABLE = False
            logger = None
    except ImportError:
        COGNITION_AVAILABLE = False
        logger = None

    if not COGNITION_AVAILABLE:
        return {"status": "unavailable"}

    try:
        from npc_cognition import get_cognition_stats

        stats = get_cognition_stats()
        return {"status": "ok", **stats}
    except Exception as e:
        if logger:
            logger.error("Cognition stats failed: %s", e)
        return {"status": "error", "error": str(e)}
