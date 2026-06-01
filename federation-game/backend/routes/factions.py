"""
Faction route handlers — extracted from main.py.
2 routes: GET /factions, POST /factions/{faction_id}/join
"""

from fastapi import APIRouter, HTTPException

from state import game_state

router = APIRouter(prefix="", tags=["factions"])


@router.get("/factions")
async def get_factions():
    fs = game_state.faction_system
    factions = {}
    for fid, faction in fs.factions.items():
        factions[fid] = {
            "name": faction.name,
            "ideology": faction.ideology.value,
            "headquarters": faction.headquarters_location,
            "level": faction.faction_level,
            "power": faction.accumulated_power,
            "allies": faction.ally_factions,
            "enemies": faction.enemy_factions,
            "reputation": faction.player_reputation.get("player", 0.0),
            "perks": [
                {
                    "id": p.perk_id,
                    "name": p.perk_name,
                    "bonus_type": p.bonus_type.value,
                    "bonus_value": p.bonus_value,
                    "unlocked_at_reputation": p.unlocked_at_reputation,
                }
                for p in faction.available_perks
            ],
            "quests": [
                {
                    "id": q.quest_id,
                    "name": q.quest_name,
                    "difficulty": q.difficulty,
                    "reputation_reward": q.reputation_reward,
                    "objective": q.objective,
                }
                for q in faction.available_quests
            ],
        }
    return {
        "player_faction": fs.player_factions.get("player"),
        "factions": factions,
    }


@router.post("/factions/{faction_id}/join")
async def join_faction(faction_id: str):
    fs = game_state.faction_system
    if faction_id not in fs.factions:
        raise HTTPException(status_code=404, detail=f"Faction '{faction_id}' not found")
    success = fs.join_faction("player", faction_id)
    if not success:
        raise HTTPException(
            status_code=400, detail=f"Already a member of '{faction_id}'"
        )
    game_state.engine_systems["faction_system"]["player_standing"] = {
        fid: fs.get_player_reputation("player", fid) for fid in fs.factions
    }
    return {
        "joined": faction_id,
        "faction_name": fs.factions[faction_id].name,
        "reputation": fs.get_player_reputation("player", faction_id),
        "player_faction": fs.player_factions.get("player"),
    }
