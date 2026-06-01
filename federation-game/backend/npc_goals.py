"""
Stub npc_goals module.

Provides goal tracking for NPCs: get, generate, advance, and status updates.
Designed to return valid responses so routes stay operational even before
full NPC goal logic is wired in.
"""
import logging
import random
import time
import uuid

logger = logging.getLogger("federation_game")

_SAMPLE_GOAL_TEMPLATES = [
    {
        "title": "Strengthen faction loyalty",
        "description": "Work to improve standing with the NPC's primary faction.",
    },
    {
        "title": "Expand influence",
        "description": "Seek opportunities to increase the NPC's sphere of influence.",
    },
    {
        "title": "Heal old wounds",
        "description": "Attempt to repair a strained relationship with a rival or ally.",
    },
    {
        "title": "Pursue forbidden knowledge",
        "description": "Investigate restricted archives or anomalous phenomena.",
    },
    {
        "title": "Secure resource supply lines",
        "description": "Establish reliable access to critical resources for the NPC's faction.",
    },
    {
        "title": "Mentor a junior officer",
        "description": "Take a promising subordinate under wing and guide their career.",
    },
    {
        "title": "Defend a contested sector",
        "description": "Reinforce defences in a border or contested region.",
    },
]

_STATUS_LIST = ["active", "completed", "abandoned"]


def _make_goal(char_id: str, personality: str = "neutral") -> dict:
    template = random.choice(_SAMPLE_GOAL_TEMPLATES)
    return {
        "id": str(uuid.uuid4()),
        "char_id": char_id,
        "title": template["title"],
        "description": template["description"],
        "status": random.choice(["active"]),
        "progress": random.randint(0, 3),
        "max_progress": random.randint(3, 6),
        "personality": personality,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }


_goal_registry: dict = {}


def get_goals(char_id: str) -> list:
    key = char_id.lower()
    if key not in _goal_registry:
        _goal_registry[key] = [_make_goal(char_id)]
    return _goal_registry[key]


def generate_goal(char_id: str, personality: str = "neutral") -> dict:
    goal = _make_goal(char_id, personality)
    key = char_id.lower()
    if key not in _goal_registry:
        _goal_registry[key] = []
    _goal_registry[key].append(goal)
    logger.info("Generated goal for %s: %s", char_id, goal["title"])
    return goal


def advance_goal(char_id: str, goal_id: str) -> dict:
    key = char_id.lower()
    goals = _goal_registry.get(key, [])
    for goal in goals:
        if goal["id"] == goal_id:
            goal["progress"] = min(goal.get("max_progress", 5), goal["progress"] + 1)
            goal["updated_at"] = int(time.time())
            if goal["progress"] >= goal.get("max_progress", 5):
                goal["status"] = "completed"
            return {"ok": True, "goal": goal}
    return {"ok": False, "error": "Goal not found"}


def set_goal_status(char_id: str, goal_id: str, status: str) -> dict:
    if status not in _STATUS_LIST:
        return {"ok": False, "error": f"Invalid status: {status}. Must be one of {_STATUS_LIST}"}
    key = char_id.lower()
    goals = _goal_registry.get(key, [])
    for goal in goals:
        if goal["id"] == goal_id:
            goal["status"] = status
            goal["updated_at"] = int(time.time())
            return {"ok": True, "goal": goal}
    return {"ok": False, "error": "Goal not found"}
