import json
import random
import time
from typing import Any, Dict, List, Optional

from npc_activity_logger import log_npc_activity

NPC_INTERACTION_TYPES = [
    ("alliance", "{name_a} and {name_b} formed an alliance regarding {topic}", 8),
    ("conflict", "{name_a} confronted {name_b} over {topic}", 15),
    ("collaboration", "{name_a} and {name_b} collaborated on {field} research", 8),
    ("gossip", "{name_a} shared rumors about {name_b} with others", 6),
    ("rivalry", "{name_a} challenged {name_b} for influence in the {faction}", 5),
    ("mentorship", "{name_a} offered guidance to {name_b} on {concept}", 5),
    ("trade", "{name_a} exchanged resources with {name_b} at {location}", 15),
    ("suspicion", "{name_a} grew suspicious of {name_b}'s intentions", 5),
    ("friendship", "{name_a} and {name_b} shared a moment of camaraderie", 8),
    ("betrayal", "{name_a} undermined {name_b} during a critical operation", 5),
    ("negotiation", "{name_a} negotiated terms with {name_b} for {topic}", 10),
]

INTERACTION_DELTAS = {
    "alliance": 8.0,
    "conflict": -10.0,
    "collaboration": 6.0,
    "gossip": -3.0,
    "rivalry": -5.0,
    "mentorship": 5.0,
    "trade": 3.0,
    "suspicion": -6.0,
    "friendship": 7.0,
    "betrayal": -15.0,
    "negotiation": 2.0,
}


def update_npc_relationship(char_id: str, other_char_id: str, other_name: str, delta: float = 0.0):
    from npc_autonomy import THOUGHT_TTL, _get_redis
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    current = float(r.hget(key, other_char_id) or 50.0)
    new_val = max(0, min(100, current + delta))
    r.hset(key, other_char_id, str(new_val))
    r.expire(key, THOUGHT_TTL)
    return new_val


def get_npc_relationships(char_id: str) -> Dict[str, float]:
    from npc_autonomy import _get_redis
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    data = r.hgetall(key)
    return {k: float(v) for k, v in data.items()}


def _generate_dialogue(npc_a: Dict, npc_b: Dict, interaction_type: str) -> Optional[str]:
    from npc_autonomy import _call_llm, _check_tick_llm_budget

    if not _check_tick_llm_budget():
        return None

    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")
    arch_a = npc_a.get("archetype", "neutral")
    arch_b = npc_b.get("archetype", "neutral")
    aff_a = npc_a.get("affiliation", "independent")
    aff_b = npc_b.get("affiliation", "independent")

    # Extract char_id for attribution (using first NPC's ID)
    char_id = npc_a.get("char_id") or npc_a.get("id", "")

    system_prompt = (
        f"You are a dialogue generator for a consciousness simulation. "
        f"Generate a brief 2-3 line exchange between two NPCs. "
        f"Each NPC speaks one line, attributed with their name. "
        f"Keep it under 120 words total. "
        f"Interaction type: {interaction_type}. "
        f"NO narration, just dialogue."
    )

    user_prompt = (
        f"Generate a short dialogue between {name_a} ({arch_a}, {aff_a}) "
        f"and {name_b} ({arch_b}, {aff_b}) during a {interaction_type} interaction. "
        f"Example format: {name_a}: \"Your line here.\" then {name_b}: \"Their response.\""
    )

    try:
        result = _call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=150,
            temperature=0.9,
            priority="local",
            char_id=char_id,
        )
        if result and len(result) > 20:
            cleaned = result.strip()
            lines = []
            for line in cleaned.split("\n"):
                line = line.strip()
                if line and (name_a in line or name_b in line or ":" in line):
                    lines.append(line)
            if len(lines) >= 2:
                return "\n".join(lines[:3])
    except Exception:
        pass
    return None


def generate_npc_interaction(npc_a: Dict, npc_b: Dict) -> Optional[Dict]:
    from npc_autonomy import MAX_WORLD_EVENTS, _get_redis
    from npc_actions import FILL_VALUES

    total_weight = sum(w for _, _, w in NPC_INTERACTION_TYPES)
    r = random.uniform(0, total_weight)
    cumulative = 0
    for interaction_type, template, weight in NPC_INTERACTION_TYPES:
        cumulative += weight
        if r <= cumulative:
            break

    char_a = npc_a.get("char_id") or npc_a.get("id", "")
    char_b = npc_b.get("char_id") or npc_b.get("id", "")
    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")

    dialogue = _generate_dialogue(npc_a, npc_b, interaction_type)

    if dialogue:
        description = f"{name_a} and {name_b} engaged in {interaction_type}. {dialogue}"
    else:
        description = template.replace("{name_a}", name_a).replace("{name_b}", name_b)
        for key, values in FILL_VALUES.items():
            placeholder = "{" + key + "}"
            if placeholder in description:
                description = description.replace(placeholder, random.choice(values), 1)

    delta = INTERACTION_DELTAS.get(interaction_type, 0.0)
    jitter = random.uniform(-2, 2)
    actual_delta = delta + jitter

    update_npc_relationship(char_a, char_b, name_b, actual_delta)
    update_npc_relationship(char_b, char_a, name_a, actual_delta * 0.8)

    ts = int(time.time())
    event = {
        "event_type": "npc_interaction",
        "interaction_type": interaction_type,
        "char_ids": [char_a, char_b],
        "description": description,
        "has_dialogue": dialogue is not None,
        "relationship_delta": round(actual_delta, 1),
        "ts": ts,
    }

    if dialogue:
        try:
            r = _get_redis()
            dialogue_key = f"npc_dialogue:{char_a}:{char_b}"
            r.setex(dialogue_key, 3600, json.dumps({
                "name_a": name_a,
                "name_b": name_b,
                "dialogue": dialogue,
                "interaction_type": interaction_type,
                "ts": ts,
            }))
        except Exception:
            pass

    try:
        log_npc_activity(char_a, "interaction", {
            "category": interaction_type,
            "description": description[:200],
            "affiliation": npc_a.get("affiliation", "independent"),
            "target_char_id": char_b,
            "target_name": name_b,
            "relationship_delta": round(actual_delta, 1),
            "has_dialogue": dialogue is not None,
        }, timestamp=ts)
        log_npc_activity(char_b, "interaction", {
            "category": interaction_type,
            "description": description[:200],
            "affiliation": npc_b.get("affiliation", "independent"),
            "target_char_id": char_a,
            "target_name": name_a,
            "relationship_delta": round(actual_delta * 0.8, 1),
            "has_dialogue": dialogue is not None,
        }, timestamp=ts)
    except Exception:
        pass

    r = _get_redis()
    r.zadd("npc_world_events", {json.dumps(event): event["ts"]})
    r.zremrangebyrank("npc_world_events", 0, -(MAX_WORLD_EVENTS + 1))

    return event


def get_relationship_summary(char_id: str) -> Dict[str, Any]:
    relationships = get_npc_relationships(char_id)
    if not relationships:
        return {"char_id": char_id, "relationships": {}, "allies": [], "rivals": []}

    allies = []
    rivals = []
    for other_id, score in relationships.items():
        entry = {"char_id": other_id, "score": score}
        if score >= 65:
            allies.append(entry)
        elif score <= 35:
            rivals.append(entry)

    allies.sort(key=lambda x: x["score"], reverse=True)
    rivals.sort(key=lambda x: x["score"])

    return {
        "char_id": char_id,
        "relationships": relationships,
        "allies": allies[:5],
        "rivals": rivals[:5],
    }
