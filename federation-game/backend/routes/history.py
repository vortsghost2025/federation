"""History arc route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["history-arc"])


@router.get("/history-arc")
async def get_history_arc():
    """Get history arc status"""
    if not game_state.history_arc:
        return {"system_available": False}
    try:
        ha = game_state.history_arc
        return {
            "system_available": True,
            "current_era": getattr(ha, "current_era", "unknown"),
            "year": getattr(ha, "current_year", 0)
            if hasattr(ha, "current_year")
            else getattr(ha.timeline, "current_year", 0),
            "initialized": getattr(ha, "_initialized", False),
        }
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@router.post("/history-arc/advance")
async def advance_history_year():
    """Advance the history arc by one year"""
    if not game_state.history_arc:
        raise HTTPException(status_code=503, detail="History arc not available")
    try:
        result = game_state.history_arc.advance_year()
        return {"result": "advanced", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history-arc/export")
async def export_history_state():
    """Export full history arc state"""
    if not game_state.history_arc:
        raise HTTPException(status_code=503, detail="History arc not available")
    try:
        return game_state.history_arc.export_full_state()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
