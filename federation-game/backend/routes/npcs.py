"""NPC route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

def _get_observer_redis():
    import redis, os
    return redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )

router = APIRouter(prefix="", tags=["npcs"])


@router.get("/npcs/{char_id}")
async def get_npc(char_id: str):
    """Return NPC character data by char_id."""
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    char = game_state.npc_system.characters[char_id]
    return {
        "char_id": char_id,
        "name": getattr(char, "name", "Unknown"),
        "title": getattr(char, "title", ""),
        "description": getattr(char, "description", ""),
        "affiliation": getattr(char, "affiliation", ""),
        "personality_type": getattr(char, "personality_type", ""),
        "loyalty": getattr(char, "loyalty", 0),
        "charisma": getattr(char, "charisma", 0),
        "wisdom": getattr(char, "wisdom", 0),
        "cunning": getattr(char, "cunning", 0),
        "ambition": getattr(char, "ambition", 0),
        "corruption_level": getattr(char, "corruption_level", 0),
        "rumor_level": getattr(char, "rumor_level", 0),
        "status": str(getattr(char, "status", "active")),
        "current_quest": getattr(char, "current_quest", None),
        "relationship_to_player": getattr(char, "relationship_to_player", "neutral"),
        "skills": getattr(char, "skills", []),
        "inventory": getattr(char, "inventory", []),
    }


@router.get("/npcs/{char_id}/decisions")
async def npc_decisions(char_id: str, limit: int = 5):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    from npc_decision_system import get_decision_log

    decisions = get_decision_log(char_id, limit=limit)
    return {"char_id": char_id, "decisions": decisions, "count": len(decisions)}


@router.get("/npcs/{char_id}/decisions/evaluate")
async def npc_evaluate_decisions(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    character = game_state.npc_system.characters[char_id]
    archetype = character.personality_type.value
    affiliation = character.affiliation
    from npc_decision_system import evaluate_decision_options, get_mood

    mood = get_mood(char_id)
    options = evaluate_decision_options(
        char_id, character.name, archetype, affiliation, mood=mood
    )
    return {
        "char_id": char_id,
        "name": character.name,
        "mood": mood,
        "options": options,
    }


@router.get("/npcs/{char_id}/broadcast-events")
async def npc_broadcast_events(char_id: str, limit: int = 10):
    from npc_autonomy import get_broadcast_events

    events = get_broadcast_events(char_id=char_id, limit=limit)
    return {"char_id": char_id, "events": events, "count": len(events)}


@router.get("/broadcast-events")
async def all_broadcast_events(limit: int = 20):
    from npc_autonomy import get_broadcast_events

    events = get_broadcast_events(limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/npcs/{char_id}/quest-chains")
async def get_npc_quest_chains(char_id: str):
    """Get quest chain progress for an NPC."""
    try:
        from npc_quest_engine import NPCQuestEngine
        from quests import create_quest_library

        _r = _get_observer_redis()
        qs = create_quest_library()
        engine = NPCQuestEngine(quest_system=qs, redis_client=_r)

        pattern = f"npc_quests:chain_progress:{char_id}:*"
        keys = [
            k.decode() if isinstance(k, bytes) else k
            for k in _r.scan_iter(match=pattern)
        ]

        chains = []
        for key in keys:
            data = _r.hgetall(key)
            if not data:
                continue
            decoded = {
                k.decode() if isinstance(k, bytes) else k: v.decode()
                if isinstance(v, bytes)
                else v
                for k, v in data.items()
            }
            chains.append(
                {
                    "chain_id": decoded.get("chain_id", ""),
                    "current_position": int(decoded.get("current_position", 0)),
                    "total": int(decoded.get("chain_total", 0)),
                    "status": decoded.get("status", "active"),
                }
            )

        return {"char_id": char_id, "chains": chains}
    except Exception as e:
        return {"char_id": char_id, "chains": [], "error": str(e)}


@router.get("/npcs/{char_id}/goals")
async def npc_goals(char_id: str):
    try:
        from npc_goals import get_goals

        goals = get_goals(char_id)
        return {"char_id": char_id, "goals": goals, "count": len(goals)}
    except Exception as e:
        return {"char_id": char_id, "goals": [], "count": 0, "error": str(e)}


@router.post("/npcs/{char_id}/goals/generate")
async def npc_generate_goal(char_id: str):
    character = game_state.npc_system.characters.get(char_id)
    if not character:
        return {"error": f"NPC {char_id} not found"}
    try:
        from npc_goals import generate_goal

        goal = generate_goal(char_id, character.personality_type.value)
        return {"char_id": char_id, "goal": goal, "status": "generated"}
    except Exception as e:
        return {"char_id": char_id, "error": str(e), "status": "failed"}


@router.post("/npcs/{char_id}/goals/{goal_id}/advance")
async def npc_advance_goal(char_id: str, goal_id: str):
    try:
        from npc_goals import advance_goal

        result = advance_goal(char_id, goal_id)
        return {"char_id": char_id, "goal_id": goal_id, "result": result}
    except Exception as e:
        return {"char_id": char_id, "goal_id": goal_id, "error": str(e)}


@router.post("/npcs/{char_id}/goals/{goal_id}/status")
async def npc_set_goal_status(char_id: str, goal_id: str, status: str = "abandoned"):
    try:
        from npc_goals import set_goal_status

        result = set_goal_status(char_id, goal_id, status)
        return {"char_id": char_id, "goal_id": goal_id, "result": result}
    except Exception as e:
        return {"char_id": char_id, "goal_id": goal_id, "error": str(e)}
