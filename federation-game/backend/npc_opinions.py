import random
import time
from typing import Dict

OPINION_TTL = 86400 * 14

ARCHETYPE_MOODS = {
    "scholar": [
        "contemplative", "curious", "frustrated", "inspired", "distracted", "analytical",
    ],
    "warrior": [
        "vigilant", "restless", "satisfied", "aggressive", "stoic", "battle-ready",
    ],
    "rogue": ["calculating", "amused", "suspicious", "opportunistic", "bored", "smug"],
    "mystic": [
        "transcendent", "troubled", "visionary", "withdrawn", "enlightened", "unsettled",
    ],
    "leader": [
        "commanding", "concerned", "strategic", "impatient", "diplomatic", "weary",
    ],
    "sage": ["serene", "pensive", "patient", "worried", "peaceful", "melancholic"],
    "wanderer": ["restless", "excited", "homesick", "adventurous", "wistful", "free"],
    "hero": ["determined", "hopeful", "burdened", "resolute", "concerned", "valiant"],
    "deceiver": [
        "scheming", "satisfied", "paranoid", "calculating", "confident", "anxious",
    ],
    "guardian": [
        "protective", "watchful", "stern", "alarmed", "steadfast", "suspicious",
    ],
}

OPINION_SHIFTS = {
    "friendly": {"trust": 5, "respect": 3, "fondness": 7},
    "hostile": {"trust": -8, "respect": -3, "fondness": -10},
    "helpful": {"trust": 8, "respect": 10, "fondness": 5},
    "deceptive": {"trust": -12, "respect": -2, "fondness": -5},
    "neutral": {"trust": 1, "respect": 1, "fondness": 1},
    "quest_given": {"trust": 5, "respect": 5, "fondness": 3},
    "quest_completed": {"trust": 10, "respect": 15, "fondness": 8},
    "quest_failed": {"trust": -5, "respect": -10, "fondness": -3},
    "gift": {"trust": 3, "respect": 2, "fondness": 10},
    "betrayal": {"trust": -20, "respect": -15, "fondness": -20},
}


def update_opinion(char_id: str, player_id: str, interaction_type: str = "neutral"):
    from npc_autonomy import _get_redis
    r = _get_redis()
    key = f"npc_opinion:{char_id}:{player_id}"
    existing = r.hgetall(key)
    if not existing:
        existing = {
            "trust": 50.0,
            "respect": 50.0,
            "fondness": 50.0,
            "interactions": 0,
            "last_interaction": "",
            "dominant_impression": "stranger",
        }
    else:
        for k in ["trust", "respect", "fondness"]:
            existing[k] = float(existing.get(k, 50.0))
        existing["interactions"] = int(existing.get("interactions", 0))

    shift = OPINION_SHIFTS.get(interaction_type, OPINION_SHIFTS["neutral"])
    for attr in ["trust", "respect", "fondness"]:
        existing[attr] = max(0, min(100, existing[attr] + shift.get(attr, 0)))

    existing["interactions"] += 1
    existing["last_interaction"] = interaction_type
    existing["last_seen"] = str(int(time.time()))

    trust = existing["trust"]
    respect = existing["respect"]
    fondness = existing["fondness"]
    if trust > 70 and fondness > 60:
        existing["dominant_impression"] = "trusted ally"
    elif trust > 60:
        existing["dominant_impression"] = "reliable acquaintance"
    elif trust < 25 or fondness < 20:
        existing["dominant_impression"] = "dangerous adversary"
    elif trust < 40:
        existing["dominant_impression"] = "unreliable stranger"
    elif respect > 70:
        existing["dominant_impression"] = "respected figure"
    else:
        existing["dominant_impression"] = "casual acquaintance"

    r.hset(key, mapping=existing)
    r.expire(key, OPINION_TTL)
    return existing


def get_opinion(char_id: str, player_id: str) -> Dict:
    from npc_autonomy import _get_redis
    r = _get_redis()
    key = f"npc_opinion:{char_id}:{player_id}"
    data = r.hgetall(key)
    if not data:
        return {
            "trust": 50,
            "respect": 50,
            "fondness": 50,
            "interactions": 0,
            "dominant_impression": "stranger",
        }
    for k in ["trust", "respect", "fondness"]:
        data[k] = float(data.get(k, 50))
    data["interactions"] = int(data.get("interactions", 0))
    return data


def update_mood(char_id: str, archetype: str) -> str:
    from npc_autonomy import _get_redis
    r = _get_redis()
    key = f"npc_mood:{char_id}"
    moods = ARCHETYPE_MOODS.get(archetype, ["contemplative", "alert", "curious"])
    current = r.get(key)
    if current and current in moods:
        weights = []
        for m in moods:
            if m == current:
                weights.append(3)
            else:
                weights.append(1)
        new_mood = random.choices(moods, weights=weights, k=1)[0]
    else:
        new_mood = random.choice(moods)
    r.set(key, new_mood, ex=86400 * 3)
    return new_mood


def get_mood(char_id: str) -> str:
    from npc_autonomy import _get_redis
    r = _get_redis()
    return r.get(f"npc_mood:{char_id}") or "contemplative"
