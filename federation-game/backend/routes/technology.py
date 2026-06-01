"""Technology route handlers — extracted from main.py"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from state import game_state

router = APIRouter(prefix="", tags=["technology"])


class StartResearchRequest(BaseModel):
    player_id: str = "player_1"


class AdvanceResearchRequest(BaseModel):
    player_id: str = "player_1"
    project_id: str
    research_points: int = 10


# ============================================================================
# TECHNOLOGY / RESEARCH ENDPOINTS
# ============================================================================


@router.get("/technology")
async def get_technology(philosophy: Optional[str] = None):
    tt = game_state.tech_tree
    available = tt.get_available_techs()
    if philosophy:
        try:
            from technology import ResearchPhilosophy

            phil = ResearchPhilosophy(philosophy)
            available = [t for t in available if t.philosophy == phil]
        except ValueError:
            pass
    return {
        "available": [
            {
                "id": t.tech_id,
                "name": t.name,
                "tier": t.tier,
                "era": t.era.value,
                "philosophy": t.philosophy.value,
                "cost": t.research_cost,
                "prerequisites": t.prerequisites,
                "unlocks_techs": t.unlocks_techs,
            }
            for t in available
        ],
        "completed": list(tt.completed_techs.keys()),
        "total_registered": len(tt.technologies),
    }


@router.get("/technology/tree")
async def get_tech_tree():
    return game_state.tech_tree.get_research_tree()


@router.get("/technology/report")
async def get_tech_report():
    return game_state.tech_tree.get_research_report()


@router.get("/technology/{tech_id}")
async def get_tech_detail(tech_id: str):
    if tech_id not in game_state.tech_tree.technologies:
        raise HTTPException(status_code=404, detail="Technology not found")
    tech = game_state.tech_tree.technologies[tech_id]
    return {
        "tech_id": tech.tech_id,
        "name": tech.name,
        "description": tech.description,
        "tier": tech.tier,
        "era": tech.era.value,
        "philosophy": tech.philosophy.value,
        "research_cost": tech.research_cost,
        "prerequisites": tech.prerequisites,
        "unlocks_techs": tech.unlocks_techs,
        "unlocks_quests": tech.unlocks_quests,
        "unlocks_perks": tech.unlocks_perks,
        "unlocks_features": tech.unlocks_features,
        "bonuses": [b.to_dict() for b in tech.bonuses],
        "is_completed": game_state.tech_tree.is_tech_completed("player_1", tech_id),
    }


@router.post("/technology/{tech_id}/research")
async def start_research(tech_id: str, req: StartResearchRequest):
    success, message, project = game_state.tech_tree.start_research(
        req.player_id, tech_id
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "started": True,
        "message": message,
        "project": project.to_dict() if project else None,
    }


@router.post("/technology/research/advance")
async def advance_research(req: AdvanceResearchRequest):
    success, message, progress = game_state.tech_tree.advance_research(
        req.player_id, req.project_id, req.research_points
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "advanced": True,
        "message": message,
        "progress": progress,
        "is_complete": progress >= 1.0,
    }


@router.get("/technology/unlocks/{tech_id}")
async def get_tech_unlocks(tech_id: str):
    unlocks = game_state.tech_tree.get_unlocked_by_tech(tech_id)
    if not unlocks:
        raise HTTPException(status_code=404, detail="Technology not found")
    return unlocks
