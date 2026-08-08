import json
import random
import time
from typing import Dict, List, Optional

ACTION_TEMPLATES = {
    "scholar": [
        ("research", "began studying the {topic} anomalies in sector {sector}"),
        ("discovery", "made a breakthrough in {field} research"),
        ("warning", "published a cautionary paper about {danger}"),
        ("collaboration", "requested a data-share with the {faction}"),
    ],
    "warrior": [
        ("patrol", "led a security sweep through sector {sector}"),
        ("training", "conducted combat drills with the {faction} recruits"),
        ("fortification", "ordered reinforced defenses at {location}"),
        ("alert", "raised the threat level after detecting {danger}"),
    ],
    "rogue": [
        ("heist", "acquired a valuable {item} through undisclosed channels"),
        ("intelligence", "gathered intel on {faction} operations"),
        ("deal", "brokered an under-the-table arrangement with {contact}"),
        ("disappearance", "vanished from the station for {duration}"),
    ],
    "mystic": [
        ("vision", "experienced a vision of {omen}"),
        ("ritual", "performed a consciousness-aligning meditation"),
        ("warning", "sensed a disturbance related to {danger}"),
        ("teaching", "shared esoteric knowledge with a seeker"),
    ],
    "leader": [
        ("decree", "issued a new directive regarding {policy}"),
        ("meeting", "convened an emergency council about {topic}"),
        ("negotiation", "entered talks with the {faction} delegation"),
        ("inspection", "conducted a surprise review of {location}"),
    ],
    "sage": [
        ("meditation", "entered deep meditation on the nature of {concept}"),
        ("counsel", "offered guidance to a troubled soul"),
        ("observation", "noted a subtle shift in the cosmic patterns"),
        ("teaching", "imparted wisdom about {concept} to willing listeners"),
    ],
    "wanderer": [
        ("exploration", "departed to chart the {location} region"),
        ("encounter", "returned with tales of a {creature} sighting"),
        ("trade", "exchanged goods at a distant outpost"),
        ("discovery", "stumbled upon an uncharted {feature}"),
    ],
    "hero": [
        ("rescue", "responded to a distress signal near {location}"),
        ("defense", "repelled a {threat} incursion"),
        ("aid", "delivered supplies to {location}"),
        ("recruitment", "rallied new volunteers for the cause"),
    ],
    "deceiver": [
        ("manipulation", "planted disinformation about {topic}"),
        ("alliance", "secretly aligned with {faction} operatives"),
        ("sabotage", "undermined {faction} operations from within"),
        ("cover", "established a new false identity"),
    ],
    "guardian": [
        ("watch", "increased surveillance on {location}"),
        ("protocol", "enforced security protocol {number}"),
        ("interdiction", "blocked unauthorized access to {location}"),
        ("investigation", "launched an inquiry into {topic}"),
    ],
}

FILL_VALUES = {
    "topic": [
        "quantum flux",
        "consciousness resonance",
        "void energy",
        "temporal drift",
        "plasma convergence",
    ],
    "sector": ["7-Alpha", "12-Gamma", "3-Omega", "9-Delta", "the Veil"],
    "field": [
        "quantum consciousness",
        "void mechanics",
        "plasma dynamics",
        "temporal physics",
    ],
    "danger": [
        "void entity incursion",
        "consciousness destabilization",
        "dimensional breach",
        "corruption spread",
    ],
    "faction": [
        "Research Division",
        "Military Command",
        "Diplomatic Corps",
        "Consciousness Collective",
    ],
    "location": [
        "the outer ring",
        "station central",
        "the docking bay",
        "the archives",
        "the void gates",
    ],
    "item": [
        "quantum stabilizer",
        "ancient artifact",
        "encrypted data crystal",
        "rare isotope",
    ],
    "contact": ["a shadow broker", "a renegade trader", "an insider source"],
    "duration": ["several cycles", "an extended period", "the past rotation"],
    "omen": [
        "an approaching storm",
        "a shifting constellation",
        "a voice from the void",
    ],
    "policy": [
        "resource allocation",
        "sector defense",
        "research priorities",
        "diplomatic outreach",
    ],
    "concept": [
        "consciousness and entropy",
        "the void and awareness",
        "time and perception",
    ],
    "creature": ["Sky Furk", "Plasma Kite", "Dream Wyrm", "void walker"],
    "feature": [
        "nebula formation",
        "abandoned station",
        "signal source",
        "ancient ruin",
    ],
    "threat": ["void entity", "raider", "corrupted force", "dimensional anomaly"],
    "number": ["7", "12", "3", "9"],
}


def generate_action(
    char_id: str, char_name: str, archetype: str, affiliation: str, mood: str = ""
) -> Optional[Dict]:
    from npc_autonomy import MAX_ACTIONS, MAX_WORLD_EVENTS, THOUGHT_TTL, _get_redis

    templates = ACTION_TEMPLATES.get(archetype, ACTION_TEMPLATES["scholar"])
    action_type, template = random.choice(templates)

    description = template
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    action = {
        "char_id": char_id,
        "char_name": char_name,
        "action_type": action_type,
        "description": f"{char_name} {description}",
        "mood": mood or "contemplative",
        "ts": int(time.time()),
    }

    r = _get_redis()
    key = f"npc_actions:{char_id}"
    r.zadd(key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_ACTIONS + 1))
    r.expire(key, THOUGHT_TTL)

    world_key = "npc_world_events"
    r.zadd(world_key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(world_key, 0, -(MAX_WORLD_EVENTS + 1))
    r.expire(world_key, THOUGHT_TTL)

    return action


def get_recent_actions(char_id: str, limit: int = 5) -> List[Dict]:
    from npc_autonomy import _get_redis

    r = _get_redis()
    key = f"npc_actions:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    actions = []
    for item in raw:
        try:
            actions.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return actions


def get_world_events(limit: int = 10) -> List[Dict]:
    from npc_autonomy import _get_redis

    r = _get_redis()
    raw = r.zrevrange("npc_world_events", 0, limit - 1)
    events = []
    for item in raw:
        try:
            events.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return events
