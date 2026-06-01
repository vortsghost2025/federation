"""Rival federation route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["rivals"])


@router.get("/rivals")
async def get_rivals():
    """Get all rival federations"""
    if not game_state.rival_simulator:
        return {"rivals": [], "system_available": False}
    try:
        states = game_state.rival_simulator.get_all_rival_states()
        return {
            "rivals": states,
            "system_available": True,
            "total": len(game_state.rival_simulator.rivals)
            if hasattr(game_state.rival_simulator, "rivals")
            else 0,
        }
    except Exception as e:
        return {"rivals": [], "system_available": False, "error": str(e)}


@router.get("/rivals/status")
async def get_rivals_status():
    """Get rival federation system status"""
    if not game_state.rival_simulator:
        return {
            "system_available": False,
            "active_rivals": 0,
            "total_rivals": 0,
        }
    try:
        total = (
            len(game_state.rival_simulator.rivals)
            if hasattr(game_state.rival_simulator, "rivals")
            else 0
        )
        return {
            "system_available": True,
            "active_rivals": total,
            "total_rivals": total,
        }
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@router.post("/rivals/spawn")
async def spawn_rival():
    """Spawn a new rival federation"""
    if not game_state.rival_simulator:
        raise HTTPException(status_code=503, detail="Rival system not available")
    try:
        game_state.rival_simulator.initialize_rivals()
        game_state.engine_systems["rival_simulator"]["active_rivals"] = (
            len(game_state.rival_simulator.rivals)
            if hasattr(game_state.rival_simulator, "rivals")
            else 0
        )
        return {
            "result": "spawned",
            "total_rivals": game_state.engine_systems["rival_simulator"][
                "active_rivals"
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
