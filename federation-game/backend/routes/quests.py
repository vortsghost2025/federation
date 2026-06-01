import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from state import game_state
from quests import FactionAffiliation, create_quest_library

logger = logging.getLogger("federation_game")
router = APIRouter(prefix="", tags=["quests"])


def _ensure_quest_system():
    if game_state.quest_system is None:
        game_state.quest_system = create_quest_library()
    return game_state.quest_system


# ============================================================================
# QUEST / CAMPAIGN ENDPOINTS
# ============================================================================


@router.get("/quests")
async def get_quests(faction: Optional[str] = None):
    qs = _ensure_quest_system()
    faction_filter = None
    if faction:
        try:
            faction_filter = FactionAffiliation(faction)
        except ValueError:
            logger.info(f"Ignoring unrecognized faction filter: {faction}")
    available = qs.get_available_quests(faction_filter=faction_filter)
    active = qs.get_active_quests()
    completed = qs.get_completed_quests()
    return {
        "available": [q.to_dict() for q in available],
        "active": [q.to_dict() for q in active],
        "completed": [q.to_dict() for q in completed],
        "total_registered": len(qs.quests),
    }


@router.get("/quests/report/summary")
async def get_quest_report():
    return _ensure_quest_system().get_quest_sync_report()


@router.get("/quests/{quest_id}")
async def get_quest_detail(quest_id: str):
    qs = _ensure_quest_system()
    if quest_id not in qs.quests:
        raise HTTPException(status_code=404, detail="Quest not found")
    quest = qs.quests[quest_id]
    return quest.to_dict()


class QuestAcceptRequest(BaseModel):
    player_id: str = "player_1"


@router.post("/quests/{quest_id}/accept")
async def accept_quest(quest_id: str, req: QuestAcceptRequest):
    qs = _ensure_quest_system()
    success, message = qs.accept_quest(req.player_id, quest_id, game_state.turn)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"accepted": True, "message": message, "quest_id": quest_id}


class QuestProgressRequest(BaseModel):
    player_id: str = "player_1"
    objective_id: str
    amount: int = 1


@router.post("/quests/{quest_id}/progress")
async def progress_quest(quest_id: str, req: QuestProgressRequest):
    qs = _ensure_quest_system()
    success, message = qs.progress_objective(
        req.player_id, quest_id, req.objective_id, req.amount
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    quest = qs.quests.get(quest_id)
    return {
        "progressed": True,
        "message": message,
        "quest_id": quest_id,
        "all_objectives_complete": quest.are_all_objectives_complete() if quest else False,
    }


class QuestCompleteRequest(BaseModel):
    player_id: str = "player_1"


@router.post("/quests/{quest_id}/complete")
async def complete_quest(quest_id: str, req: QuestCompleteRequest):
    qs = _ensure_quest_system()
    success, message, rewards = qs.complete_quest(req.player_id, quest_id, game_state.turn)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "completed": True,
        "message": message,
        "quest_id": quest_id,
        "rewards": rewards.to_dict() if rewards else None,
    }


class QuestAbandonRequest(BaseModel):
    player_id: str = "player_1"


@router.post("/quests/{quest_id}/abandon")
async def abandon_quest(quest_id: str, req: QuestAbandonRequest):
    qs = _ensure_quest_system()
    success, message = qs.abandon_quest(req.player_id, quest_id, game_state.turn)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"abandoned": True, "message": message, "quest_id": quest_id}
