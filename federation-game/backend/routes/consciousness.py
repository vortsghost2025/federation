"""Consciousness route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["consciousness"])


@router.get("/consciousness")
async def get_consciousness():
    """Get full consciousness sheet status"""
    if not game_state.consciousness_sheet:
        return {"system_available": False}
    try:
        cs = game_state.consciousness_sheet
        return {
            "system_available": True,
            "morale": cs.morale,
            "identity": cs.identity,
            "anxiety": cs.anxiety,
            "confidence": cs.confidence,
            "expansion_hunger": cs.expansion_hunger,
            "diplomacy_tendency": cs.diplomacy_tendency,
            "dreams": getattr(cs, "dreams", []) or [],
            "prophecies": getattr(cs, "prophecies", []) or [],
            "archetypes": getattr(cs, "archetypes", []) or [],
            "traumas": getattr(cs, "traumas", []) or [],
        }
    except Exception as e:
        return {"system_available": False, "error": str(e)}
