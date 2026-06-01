"""Political route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["political"])


@router.get("/political")
async def get_political_status():
    """Get political engine status"""
    if not game_state.political_engine:
        return {"system_available": False}
    try:
        status = game_state.political_engine.summary
        return {"system_available": True, "status": status}
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@router.post("/political/process-turn")
async def process_political_turn():
    """Process one political turn"""
    if not game_state.political_engine:
        raise HTTPException(status_code=503, detail="Political system not available")
    try:
        current_year = game_state.timeline.current_year if game_state.timeline else 2387
        fed_state = (
            game_state.game_state_v2.federation if game_state.game_state_v2 else None
        )
        if fed_state:
            result = game_state.political_engine.process_year(current_year, fed_state)
        else:
            result = []
        return {"result": "processed", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
