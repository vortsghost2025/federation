"""Federation Star Map API - aggregated visualization data endpoint."""

import json
import logging
import os
from fastapi import APIRouter

logger = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional

try:
    import redis
except ImportError:
    redis = None

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


router = APIRouter(prefix="/map", tags=["map"])


def _safe_json_parse(raw: Optional[str]) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _zset_latest(r, key: str) -> Optional[Any]:
    """Get the most recent entry from a ZSET (highest score = latest)."""
    try:
        items = r.zrevrange(key, 0, 0)
        if items:
            return _safe_json_parse(items[0])
    except Exception:
        pass  # Redis key missing or corrupt; return None as fallback
    return None


def _list_first(r, key: str) -> Optional[Any]:
    """Get the first element from a LIST."""
    try:
        items = r.lrange(key, 0, 0)
        if items:
            return _safe_json_parse(items[0])
    except Exception:
        pass  # Redis key missing or corrupt; return None as fallback
    return None


# Mood-to-color mapping for the star map visual
MOOD_COLORS = {
    "inspired": "#ffd700",
    "contemplative": "#4fc3f7",
    "curious": "#ab47bc",
    "frustrated": "#ef5350",
    "suspicious": "#ff7043",
    "paranoid": "#f44336",
    "stoic": "#78909c",
    "vigilant": "#ff9800",
    "burdened": "#8d6e63",
    "stern": "#546e7a",
    "restless": "#ffa726",
    "homesick": "#7986cb",
    "impatient": "#ff5722",
    "withdrawn": "#607d8b",
    "battle-ready": "#d32f2f",
    "commanding": "#1565c0",
    "watchful": "#0288d1",
    "distracted": "#9e9e9e",
    "smug": "#fdd835",
    "bored": "#757575",
    "visionary": "#7c4dff",
    "transcendent": "#e040fb",
    "serene": "#26a69a",
    "troubled": "#ff6e40",
    "patient": "#66bb6a",
    "adventurous": "#ffab00",
    "satisfied": "#8bc34a",
    "steadfast": "#3f51b5",
    "strategic": "#00bcd4",
    "calculating": "#009688",
    "peaceful": "#4caf50",
    "anxious": "#ff9100",
    "determined": "#c62828",
    "hostile": "#b71c1c",
    "joyful": "#ffee58",
    "concerned": "#ffab40",
    "alarmed": "#ff3d00",
}

# Faction color mapping
FACTION_COLORS = {
    "research_division": "#4fc3f7",
    "military_command": "#ef5350",
    "diplomatic_corps": "#66bb6a",
    "consciousness_collective": "#ab47bc",
    "cultural_ministry": "#ffa726",
    "economic_council": "#ffd700",
    "exploration_initiative": "#26c6da",
    "preservation_society": "#8d6e63",
}


@router.get("/data")
async def get_map_data():
    """Aggregate all visualization data for the star map frontend."""
    r = _get_redis()
    result: Dict[str, Any] = {
        "world_state": {},
        "npcs": [],
        "factions": {},
        "events": [],
        "worker": {},
    }

    # --- World State ---
    try:
        stored = r.hgetall("world_state")
        for k, v in stored.items():
            if k.startswith("_"):
                continue
            try:
                result["world_state"][k] = int(v)
            except (ValueError, TypeError):
                result["world_state"][k] = v
    except Exception:
        logger.debug(f"Unexpected error parsing world_state key '{k}'; skipped")

    # --- NPCs ---
    try:
        mood_keys = r.keys("npc_mood:*")
        npc_ids = [k.replace("npc_mood:", "") for k in mood_keys]
        npc_ids = [nid for nid in npc_ids if not nid.startswith("test_")]

        enriched = []
        for cid in npc_ids:
            entry = {"id": cid}

            # Mood
            try:
                mood = r.get(f"npc_mood:{cid}")
                entry["mood"] = mood if mood else None
                entry["mood_color"] = MOOD_COLORS.get(mood, "#9e9e9e")
            except Exception:
                entry["mood"] = None
                entry["mood_color"] = "#9e9e9e"

            # Last active
            try:
                raw_ts = r.get(f"npc_last_active:{cid}")
                entry["last_active"] = int(raw_ts) if raw_ts else None
            except Exception:
                entry["last_active"] = None

            # Latest decision
            latest_decision = _zset_latest(r, f"npc_decisions:{cid}")
            if latest_decision:
                entry["name"] = latest_decision.get("char_name", cid)
                entry["archetype"] = latest_decision.get("category", "unknown")
                entry["latest_decision"] = latest_decision.get("description", "")
                entry["action_taken"] = latest_decision.get("action_taken", "")
                entry["decision_mood"] = latest_decision.get("mood", "")
                entry["decision_score"] = latest_decision.get("score", 0)
            else:
                entry["name"] = cid
                entry["latest_decision"] = None

            # Latest action
            latest_action = _zset_latest(r, f"npc_actions:{cid}")
            if latest_action:
                if "name" not in entry or entry["name"] == cid:
                    entry["name"] = latest_action.get("char_name", cid)
                entry["latest_action"] = latest_action.get("description", "")
                entry["action_type"] = latest_action.get("action_type", "")
            else:
                entry["latest_action"] = None

            # Latest thought
            latest_thought = _zset_latest(r, f"npc_thoughts:{cid}")
            if latest_thought:
                if "name" not in entry or entry["name"] == cid:
                    entry["name"] = latest_thought.get("char_name", cid)
                entry["latest_thought"] = latest_thought.get("thought", "")
            else:
                entry["latest_thought"] = None

            # Goal
            latest_goal = _list_first(r, f"npc_goals:{cid}")
            if latest_goal:
                entry["goal"] = latest_goal.get("description", "")
                entry["goal_status"] = latest_goal.get("status", "")
            else:
                entry["goal"] = None

            # NPC category from ID prefix
            if cid.startswith("char_1"):
                entry["category"] = "federation_leader"
            elif cid.startswith("char_2"):
                entry["category"] = "rival"
            elif cid.startswith("char_3"):
                entry["category"] = "neutral"
            elif cid.startswith("char_4"):
                entry["category"] = "enigma"
            elif cid.startswith("comp_"):
                entry["category"] = "companion"
            else:
                entry["category"] = "unknown"

            # Relationships
            try:
                raw_rels = r.hgetall(f"npc_relationships:{cid}")
                rels = {}
                for other_id, score in raw_rels.items():
                    try:
                        rels[other_id] = float(score)
                    except (ValueError, TypeError):
                        pass  # Skip non-numeric relationship score
                entry["relationships"] = rels
            except Exception:
                entry["relationships"] = {}

            enriched.append(entry)

        # Enrich with affiliation/title from npc_profiles (if stored)
        try:
            npc_profiles_raw = r.get("npc_profiles")
            if npc_profiles_raw:
                npc_profiles = _safe_json_parse(npc_profiles_raw)
                if isinstance(npc_profiles, list):
                    profile_map = {
                        p.get("id"): p for p in npc_profiles if isinstance(p, dict)
                    }
                    for entry in enriched:
                        prof = profile_map.get(entry["id"])
                        if prof:
                            entry["affiliation"] = prof.get("affiliation")
                            entry["title"] = prof.get("title")
                            entry["archetype"] = prof.get(
                                "archetype", entry.get("archetype")
                            )
                            if not entry.get("name") or entry["name"] == entry["id"]:
                                entry["name"] = prof.get("name", entry["id"])
        except Exception:
            logger.debug(
                f"NPC profile enrichment failed for {entry.get('id', 'unknown')}"
            )

        result["npcs"] = enriched
    except Exception:
        logger.warning(
            "NPC enrichment section failed; NPCs may be incomplete in map data"
        )

    # --- Factions ---
    try:
        stored_dynamics = r.hgetall("faction_dynamics")
        factions: Dict[str, Any] = {}
        for faction_id, data in stored_dynamics.items():
            parsed = _safe_json_parse(data)
            if parsed is None:
                continue
            faction_entry = {
                "display_name": parsed.get("display_name", faction_id),
                "member_count": parsed.get("member_count", 0),
                "cohesion": parsed.get("cohesion", 0),
                "influence": parsed.get("influence", 0),
                "standing": parsed.get("standing", 0),
                "vigilance": parsed.get("vigilance", 0),
                "avg_mood": parsed.get("avg_mood", 0),
                "activity_rate": parsed.get("activity_rate", 0),
                "decisions_this_tick": parsed.get("decisions_this_tick", 0),
                "events_this_tick": parsed.get("events_this_tick", 0),
                "color": FACTION_COLORS.get(faction_id, "#9e9e9e"),
                "stances": {},
            }
            try:
                stance_data = r.hgetall(f"faction_stances:{faction_id}")
                for target_fid, stance_raw in stance_data.items():
                    stance_parsed = _safe_json_parse(stance_raw)
                    if stance_parsed is not None:
                        faction_entry["stances"][target_fid] = stance_parsed
            except Exception:
                logger.debug(f"Faction stance parsing failed for {faction_id}")
            factions[faction_id] = faction_entry

        result["factions"] = factions
    except Exception:
        logger.warning("Faction section failed; factions may be incomplete in map data")

    # --- Events (latest 50) ---
    try:
        raw_events = r.zrevrange("npc_world_events", 0, 49)
        events: List[Dict] = []
        for item in raw_events:
            parsed = _safe_json_parse(item)
            if parsed is not None:
                events.append(parsed)
        result["events"] = events
    except Exception:
        logger.warning("Events section failed; events may be incomplete in map data")

    # --- Broadcast Events (latest 20) ---
    try:
        raw_broadcasts = r.zrevrange("npc_broadcast_events", 0, 19)
        broadcasts: List[Dict] = []
        for item in raw_broadcasts:
            parsed = _safe_json_parse(item)
            if parsed is not None:
                broadcasts.append(parsed)
        result["broadcasts"] = broadcasts
    except Exception:
        logger.warning(
            "Broadcast events section failed; broadcasts may be incomplete in map data"
        )

    # --- Worker Status ---
    try:
        result["worker"] = r.hgetall("worker:status")
    except Exception:
        pass  # Worker status unavailable; omit from map data

    # --- History State ---
    try:
        history_raw = r.get("world_state_history")
        if history_raw:
            result["history"] = _safe_json_parse(history_raw)
    except Exception:
        pass  # History state unavailable; omit from map data

    return result
