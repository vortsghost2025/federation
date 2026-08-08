"""
NPC Character Arc Tracking System

Tracks major turning points, growth milestones, and narrative arcs for each NPC.
Uses Redis for persistence. Key features:
- Record turning points (relationship shifts, goal completions, era changes)
- Query arc status (current arc phase, turning point count, growth trajectory)
- Generate arc summaries for frontend display
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Redis keys
ARC_KEY = "npc_arc:{char_id}"
ARC_TURNING_POINTS_KEY = "npc_arc_turning_points:{char_id}"
ARC_PHASE_KEY = "npc_arc_phase:{char_id}"
ARC_MILESTONES_KEY = "npc_arc_milestones:{char_id}"

MAX_TURNING_POINTS = 50
MAX_MILESTONES = 20
TURNING_POINT_TTL = 86400 * 30  # 30 days

# Arc phases based on emotional trajectory
ARC_PHASES = {
    "origin": {"description": "Beginning of journey", "icon": "seed"},
    "growth": {"description": "Learning and expanding", "icon": "sprout"},
    "conflict": {"description": "Facing challenges", "icon": "storm"},
    "revelation": {"description": "Key insight or change", "icon": "lightning"},
    "transformation": {"description": "Fundamental shift", "icon": "butterfly"},
    "mastery": {"description": "Achieved new state", "icon": "crown"},
    "decline": {"description": "Losing ground", "icon": "shadow"},
    "redemption": {"description": "Recovering from fall", "icon": "dawn"},
}

# Turning point categories and their significance
TURNING_POINT_CATEGORIES = {
    "relationship_shift": {
        "description": "Major change in relationship with another NPC",
        "significance": 3,
    },
    "goal_achievement": {
        "description": "Completed a significant goal",
        "significance": 4,
    },
    "goal_failure": {
        "description": "Failed at a significant goal",
        "significance": 3,
    },
    "faction_change": {
        "description": "Changed faction allegiance",
        "significance": 5,
    },
    "era_transition": {
        "description": "Experienced an era shift",
        "significance": 4,
    },
    "betrayal": {
        "description": "Was betrayed or betrayed someone",
        "significance": 5,
    },
    "discovery": {
        "description": "Made a significant discovery",
        "significance": 3,
    },
    "loss": {
        "description": "Experienced a significant loss",
        "significance": 4,
    },
    "triumph": {
        "description": "Achieved a major victory",
        "significance": 4,
    },
    "moral_crossroads": {
        "description": "Faced a difficult moral choice",
        "significance": 4,
    },
    "alliance_formed": {
        "description": "Formed a significant alliance",
        "significance": 3,
    },
    "rivalry_ignited": {
        "description": "Started a major rivalry",
        "significance": 3,
    },
}


def _get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def record_turning_point(
    char_id: str,
    category: str,
    description: str,
    other_npc_id: Optional[str] = None,
    other_npc_name: Optional[str] = None,
    emotional_intensity: float = 0.5,
    details: Optional[Dict] = None,
) -> Dict:
    """Record a major turning point in an NPC's character arc."""
    cat_info = TURNING_POINT_CATEGORIES.get(category, {
        "description": category,
        "significance": 2,
    })

    turning_point = {
        "category": category,
        "description": description[:300],
        "other_npc_id": other_npc_id,
        "other_npc_name": other_npc_name,
        "emotional_intensity": emotional_intensity,
        "significance": cat_info["significance"],
        "details": details or {},
        "ts": int(time.time()),
    }

    r = _get_redis()
    key = ARC_TURNING_POINTS_KEY.format(char_id=char_id)
    r.zadd(key, {json.dumps(turning_point): turning_point["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_TURNING_POINTS + 1))
    r.expire(key, TURNING_POINT_TTL)

    # Update arc phase based on accumulated turning points
    _update_arc_phase(char_id, r)

    return turning_point


def _update_arc_phase(char_id: str, r: redis.Redis):
    """Determine current arc phase based on recent turning points and sentiment."""
    key = ARC_TURNING_POINTS_KEY.format(char_id=char_id)
    recent = r.zrevrange(key, 0, 9)  # Last 10 turning points

    if not recent:
        _set_arc_phase(char_id, "origin", r)
        return

    categories = []
    total_intensity = 0
    for raw in recent:
        try:
            tp = json.loads(raw)
            categories.append(tp.get("category", ""))
            total_intensity += tp.get("emotional_intensity", 0.5)
        except (json.JSONDecodeError, TypeError):
            continue

    avg_intensity = total_intensity / max(len(recent), 1)
    cat_set = set(categories)

    # Determine phase based on patterns
    if "goal_achievement" in cat_set or "triumph" in cat_set:
        if avg_intensity > 0.7:
            phase = "mastery"
        else:
            phase = "growth"
    elif "betrayal" in cat_set or "loss" in cat_set:
        if "redemption" in cat_set or "alliance_formed" in cat_set:
            phase = "redemption"
        else:
            phase = "conflict"
    elif "moral_crossroads" in cat_set:
        phase = "revelation"
    elif "faction_change" in cat_set:
        phase = "transformation"
    elif "decline" in cat_set or avg_intensity < 0.3:
        phase = "decline"
    elif len(categories) < 3:
        phase = "origin"
    else:
        phase = "growth"

    _set_arc_phase(char_id, phase, r)


def _set_arc_phase(char_id: str, phase: str, r: redis.Redis):
    """Set the current arc phase for an NPC."""
    key = ARC_PHASE_KEY.format(char_id=char_id)
    phase_info = ARC_PHASES.get(phase, ARC_PHASES["origin"])
    r.set(key, json.dumps({
        "phase": phase,
        "description": phase_info["description"],
        "icon": phase_info["icon"],
        "updated_at": int(time.time()),
    }), ex=TURNING_POINT_TTL)


def get_arc_phase(char_id: str) -> Dict[str, Any]:
    """Get the current arc phase for an NPC."""
    r = _get_redis()
    key = ARC_PHASE_KEY.format(char_id=char_id)
    raw = r.get(key)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {"phase": "origin", "description": "Beginning of journey", "icon": "seed"}


def get_turning_points(
    char_id: str, limit: int = 10, category: Optional[str] = None
) -> List[Dict]:
    """Get an NPC's turning points, optionally filtered by category."""
    r = _get_redis()
    key = ARC_TURNING_POINTS_KEY.format(char_id=char_id)
    raw_list = r.zrevrange(key, 0, limit - 1)
    turning_points = []
    for raw in raw_list:
        try:
            tp = json.loads(raw)
            if category and tp.get("category") != category:
                continue
            turning_points.append(tp)
        except (json.JSONDecodeError, TypeError):
            continue
    return turning_points


def record_milestone(
    char_id: str,
    title: str,
    description: str,
    milestone_type: str = "achievement",
) -> Dict:
    """Record a milestone in an NPC's arc."""
    milestone = {
        "title": title[:100],
        "description": description[:300],
        "type": milestone_type,
        "ts": int(time.time()),
    }
    r = _get_redis()
    key = ARC_MILESTONES_KEY.format(char_id=char_id)
    r.zadd(key, {json.dumps(milestone): milestone["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_MILESTONES + 1))
    r.expire(key, TURNING_POINT_TTL)
    return milestone


def get_milestones(char_id: str, limit: int = 10) -> List[Dict]:
    """Get an NPC's milestones."""
    r = _get_redis()
    key = ARC_MILESTONES_KEY.format(char_id=char_id)
    raw_list = r.zrevrange(key, 0, limit - 1)
    milestones = []
    for raw in raw_list:
        try:
            milestones.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return milestones


def get_arc_summary(char_id: str) -> Dict[str, Any]:
    """Get a complete character arc summary for an NPC."""
    phase = get_arc_phase(char_id)
    turning_points = get_turning_points(char_id, limit=20)
    milestones = get_milestones(char_id, limit=10)

    # Compute arc statistics
    categories = {}
    total_intensity = 0
    for tp in turning_points:
        cat = tp.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        total_intensity += tp.get("emotional_intensity", 0.5)

    dominant_category = max(categories.items(), key=lambda x: x[1])[0] if categories else "none"

    return {
        "char_id": char_id,
        "phase": phase,
        "turning_point_count": len(turning_points),
        "milestone_count": len(milestones),
        "dominant_category": dominant_category,
        "category_breakdown": categories,
        "avg_emotional_intensity": round(total_intensity / max(len(turning_points), 1), 2),
        "recent_turning_points": turning_points[:5],
        "recent_milestones": milestones[:3],
    }


def auto_harvest_arc_events(
    char_id: str,
    npc_data: Dict,
    tick_results: Optional[Dict] = None,
) -> int:
    """Automatically harvest arc events from tick results. Returns count of events harvested."""
    harvested = 0

    # Goal completions
    if tick_results:
        quest_data = tick_results.get("step7_npc_quests", {})
        completed = quest_data.get("completed_details", [])
        for cq in completed:
            if cq.get("char_id") == char_id:
                record_turning_point(
                    char_id,
                    "goal_achievement",
                    f"Completed quest: {cq.get('quest_title', 'unknown')}",
                    emotional_intensity=0.7,
                    details={"quest_id": cq.get("quest_id")},
                )
                record_milestone(
                    char_id,
                    f"Quest Complete: {cq.get('quest_title', 'Unknown')[:50]}",
                    f"Achieved a major goal: {cq.get('quest_title', '')}",
                    "achievement",
                )
                harvested += 1

    # Relationship shifts (from interactions)
    if tick_results:
        interactions = tick_results.get("interactions", [])
        for ix in interactions:
            if not isinstance(ix, dict):
                continue
            char_ids = ix.get("char_ids", [])
            if char_id in char_ids:
                delta = ix.get("relationship_delta", 0)
                if abs(delta) > 8:  # Significant shift
                    other_ids = [cid for cid in char_ids if cid != char_id]
                    other_id = other_ids[0] if other_ids else None
                    category = "betrayal" if delta < -10 else "alliance_formed" if delta > 8 else "relationship_shift"
                    record_turning_point(
                        char_id,
                        category,
                        ix.get("description", "")[:200],
                        other_npc_id=other_id,
                        emotional_intensity=min(abs(delta) / 15, 1.0),
                    )
                    harvested += 1

    return harvested
