"""
Narrator route handlers — extracted from main.py
"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["narrator"])


@router.get("/narrator")
async def narrator_overview(limit: int = 3):
    """Compatibility summary for legacy /narrator health checks."""
    limit = min(max(limit, 1), 10)
    try:
        from narrator import get_narration_history

        narrations = get_narration_history(limit=limit)
        return {
            "status": "ok",
            "available": True,
            "count": len(narrations),
            "recent": narrations,
            "endpoints": {
                "generate": "/narrator/generate",
                "history": "/narrator/history",
            },
        }
    except ImportError:
        return {
            "status": "unavailable",
            "available": False,
            "count": 0,
            "recent": [],
            "endpoints": {
                "generate": "/narrator/generate",
                "history": "/narrator/history",
            },
            "error": "narrator module not imported",
        }
    except Exception as e:
        return {
            "status": "error",
            "available": True,
            "count": 0,
            "recent": [],
            "endpoints": {
                "generate": "/narrator/generate",
                "history": "/narrator/history",
            },
            "error": str(e),
        }


@router.post("/narrator/generate")
async def narrator_generate():
    """Manually trigger narration generation.

    This is a standalone endpoint for testing/observation.
    Normally, narration runs inside autonomous_tick() Step 6.
    """
    try:
        from tick_engine import _get_observer_redis
        try:
            from main import NARRATOR_AVAILABLE, logger
        except ImportError:
            NARRATOR_AVAILABLE = False
            logger = None
    except ImportError:
        NARRATOR_AVAILABLE = False
        _get_observer_redis = None
        logger = None

    if not NARRATOR_AVAILABLE:
        return {"status": "unavailable", "error": "narrator module not imported"}

    _r = _get_observer_redis()

    npc_list = []
    for char_id, character in game_state.npc_system.characters.items():
        npc_list.append(
            {
                "id": char_id,
                "char_id": char_id,
                "name": character.name,
                "affiliation": character.affiliation,
            }
        )

    import json

    tick_decisions = []
    for npc in npc_list:
        cid = npc["char_id"]
        try:
            raw = _r.zrange(f"npc_decisions:{cid}", 0, -1)
            for item in raw:
                try:
                    tick_decisions.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

    world_state = {}
    try:
        from npc_autonomy import get_world_state

        world_state = get_world_state()
    except Exception:
        pass

    try:
        from narrator import generate_narration

        result = generate_narration(
            world_state=world_state,
            tick_decisions=tick_decisions,
        )
        return {"status": "completed", **result}
    except Exception as e:
        if logger:
            logger.error("Narrator generate failed: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/narrator/history")
async def narrator_history(limit: int = 10):
    """Get recent narrations for the observer dashboard."""
    try:
        from tick_engine import _get_observer_redis
        try:
            from main import NARRATOR_AVAILABLE, logger
        except ImportError:
            NARRATOR_AVAILABLE = False
            logger = None
    except ImportError:
        NARRATOR_AVAILABLE = False
        logger = None

    if not NARRATOR_AVAILABLE:
        return {"status": "unavailable", "error": "narrator module not imported"}

    limit = min(max(limit, 1), 50)
    try:
        from narrator import get_narration_history

        narrations = get_narration_history(limit=limit)
        return {"status": "ok", "narrations": narrations, "count": len(narrations)}
    except Exception as e:
        if logger:
            logger.error("Narrator history failed: %s", e)
        return {"status": "error", "error": str(e)}
