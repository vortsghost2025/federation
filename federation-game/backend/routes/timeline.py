"""Timeline route handlers — extracted from main.py"""

from fastapi import APIRouter
from state import game_state

router = APIRouter(prefix="", tags=["timeline"])


@router.get("/timeline")
async def get_timeline():
    return game_state.timeline.get_timeline_status()


@router.get("/timeline/narrative")
async def get_narrative_arc(limit: int = 20):
    return game_state.timeline.get_narrative_arc(limit=limit)


@router.get("/timeline/divergences")
async def get_divergences():
    return game_state.timeline.get_divergence_status()
