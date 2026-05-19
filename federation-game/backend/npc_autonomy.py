"""
FEDERATION GAME - NPC Autonomy Engine
Phase 3: Autonomous NPC actions between player visits
Phase 6a: Decision engine - contextual NPC decision-making

NPCs live their own lives when players are away:
- Generate thoughts (periodic internal monologue)
- Form opinions about players (sentiment tracking)
- Take autonomous actions (world-impacting decisions)
- Develop relationships that evolve over time
- Create rumors/news that spread between NPCs
- Make contextual decisions based on goals, mood, relationships, world state

Redis keys:
npc_thoughts:{char_id} - ZSET (score=timestamp) of recent thoughts
npc_opinion:{char_id}:{player_id} - HASH of opinion data
npc_actions:{char_id} - ZSET (score=timestamp) of recent actions
npc_relationships:{char_id} - HASH of relationship values with other NPCs
npc_world_events - ZSET (score=timestamp) of global events
npc_mood:{char_id} - STRING current mood state
npc_last_active:{char_id} - STRING timestamp of last activity
npc_decisions:{char_id} - ZSET (score=timestamp) of recent decisions
"""

import os
import json
import time
import random
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any

import redis
from faction_dynamics import (
    compute_faction_dynamics,
    compute_faction_stances,
    store_faction_dynamics,
)
import logging

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"

MAX_THOUGHTS = 10
MAX_ACTIONS = 8
MAX_WORLD_EVENTS = 50
THOUGHT_TTL = 86400 * 7
OPINION_TTL = 86400 * 14

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 150,
    temperature: float = 0.9,
) -> str:
    if not OPENROUTER_API_KEY:
        return ""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = json.dumps(
        {
            "model": DEFAULT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://federation-game.deliberatefederation.cloud",
        "X-Title": "Federation Game NPC Autonomy",
    }
    req = urllib.request.Request(
        OPENROUTER_URL, data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
    except Exception:
        return ""


# --- THOUGHTS ---


def generate_thought(
    char_id: str,
    char_name: str,
    archetype: str,
    affiliation: str,
    title: str,
    description: str,
    mood: str = "",
) -> Optional[Dict]:
    system = f"""You are {char_name}, {title}. {description}
Archetype: {archetype}. Affiliation: {affiliation}.
Current mood: {mood or "contemplative"}

Generate a single internal thought (1-2 sentences) this character would have right now.
It should reflect their personality, current concerns, and the world around them.
Be specific and in-character. Do not use quotes or attribution - just the thought itself.
Examples:
- "The star charts suggest an anomaly near the Veil... I must investigate before Military Command claims it."
- "Another day, another scheme. The Ambassador thinks she's clever, but I see three moves ahead."
- "The void feels restless tonight. Something stirs in the deeper currents."""

    thought_text = _call_llm(
        system, "What is on your mind right now?", max_tokens=80, temperature=0.95
    )
    if not thought_text:
        template_thoughts = {
            "scholar": "The data patterns suggest something unusual is forming in the research grids...",
            "warrior": "The perimeter feels unsteady. I should reinforce our defensive positions.",
            "rogue": "Opportunities don't announce themselves. Time to do some reconnaissance...",
            "mystic": "I sense a shift in the cosmic currents. Something approaches from beyond...",
            "leader": "The council meeting approaches. I must prepare my arguments carefully.",
            "sage": "Balance requires patience, but events press urgency upon us.",
            "wanderer": "I feel the call of uncharted space again. The old restlessness returns.",
            "hero": "Someone out there needs help. I can feel it in my bones.",
            "deceiver": "The pieces on the board are shifting. Time to rearrange them to my advantage.",
            "guardian": "The old protocols must be maintained. I sense complacency in the ranks.",
        }
        thought_text = template_thoughts.get(
            archetype, "Something stirs in the void..."
        )

    thought = {
        "char_id": char_id,
        "char_name": char_name,
        "thought": thought_text,
        "mood": mood or "contemplative",
        "ts": int(time.time()),
    }
    r = _get_redis()
    key = f"npc_thoughts:{char_id}"
    r.zadd(key, {json.dumps(thought): thought["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_THOUGHTS + 1))
    r.expire(key, THOUGHT_TTL)
    return thought


def get_recent_thoughts(char_id: str, limit: int = 3) -> List[Dict]:
    r = _get_redis()
    key = f"npc_thoughts:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    thoughts = []
    for item in raw:
        try:
            thoughts.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return thoughts


# --- OPINIONS ---


def update_opinion(char_id: str, player_id: str, interaction_type: str = "neutral"):
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

    shifts = {
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

    shift = shifts.get(interaction_type, shifts["neutral"])
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


# --- MOODS ---

ARCHETYPE_MOODS = {
    "scholar": [
        "contemplative",
        "curious",
        "frustrated",
        "inspired",
        "distracted",
        "analytical",
    ],
    "warrior": [
        "vigilant",
        "restless",
        "satisfied",
        "aggressive",
        "stoic",
        "battle-ready",
    ],
    "rogue": ["calculating", "amused", "suspicious", "opportunistic", "bored", "smug"],
    "mystic": [
        "transcendent",
        "troubled",
        "visionary",
        "withdrawn",
        "enlightened",
        "unsettled",
    ],
    "leader": [
        "commanding",
        "concerned",
        "strategic",
        "impatient",
        "diplomatic",
        "weary",
    ],
    "sage": ["serene", "pensive", "patient", "worried", "peaceful", "melancholic"],
    "wanderer": ["restless", "excited", "homesick", "adventurous", "wistful", "free"],
    "hero": ["determined", "hopeful", "burdened", "resolute", "concerned", "valiant"],
    "deceiver": [
        "scheming",
        "satisfied",
        "paranoid",
        "calculating",
        "confident",
        "anxious",
    ],
    "guardian": [
        "protective",
        "watchful",
        "stern",
        "alarmed",
        "steadfast",
        "suspicious",
    ],
}


def update_mood(char_id: str, archetype: str) -> str:
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
    r = _get_redis()
    return r.get(f"npc_mood:{char_id}") or "contemplative"


# --- AUTONOMOUS ACTIONS ---

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
    r = _get_redis()
    raw = r.zrevrange("npc_world_events", 0, limit - 1)
    events = []
    for item in raw:
        try:
            events.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return events


# --- NPC-TO-NPC RELATIONSHIPS ---


def update_npc_relationship(
    char_id: str, other_char_id: str, other_name: str, delta: float = 0.0
):
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    current = float(r.hget(key, other_char_id) or 50.0)
    new_val = max(0, min(100, current + delta))
    r.hset(key, other_char_id, str(new_val))
    r.expire(key, THOUGHT_TTL)
    return new_val


def get_npc_relationships(char_id: str) -> Dict[str, float]:
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    data = r.hgetall(key)
    return {k: float(v) for k, v in data.items()}


# --- SIMULATION TICK ---

NPC_INTERACTION_TYPES = [
    ("alliance", "{name_a} and {name_b} formed an alliance regarding {topic}"),
    ("conflict", "{name_a} confronted {name_b} over {topic}"),
    ("collaboration", "{name_a} and {name_b} collaborated on {field} research"),
    ("gossip", "{name_a} shared rumors about {name_b} with others"),
    ("rivalry", "{name_a} challenged {name_b} for influence in the {faction}"),
    ("mentorship", "{name_a} offered guidance to {name_b} on {concept}"),
    ("trade", "{name_a} exchanged resources with {name_b} at {location}"),
    ("suspicion", "{name_a} grew suspicious of {name_b}'s intentions"),
    ("friendship", "{name_a} and {name_b} shared a moment of camaraderie"),
    ("betrayal", "{name_a} undermined {name_b} during a critical operation"),
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
}


def generate_npc_interaction(npc_a: Dict, npc_b: Dict) -> Optional[Dict]:
    interaction_type, template = random.choice(NPC_INTERACTION_TYPES)

    description = template.replace("{name_a}", npc_a.get("name", "Unknown")).replace(
        "{name_b}", npc_b.get("name", "Unknown")
    )
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    delta = INTERACTION_DELTAS.get(interaction_type, 0.0)
    jitter = random.uniform(-2, 2)
    actual_delta = delta + jitter

    char_a = npc_a.get("char_id") or npc_a.get("id", "")
    char_b = npc_b.get("char_id") or npc_b.get("id", "")
    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")

    update_npc_relationship(char_a, char_b, name_b, actual_delta)
    update_npc_relationship(char_b, char_a, name_a, actual_delta * 0.8)

    event = {
        "event_type": "npc_interaction",
        "interaction_type": interaction_type,
        "char_ids": [char_a, char_b],
        "description": description,
        "relationship_delta": round(actual_delta, 1),
        "ts": int(time.time()),
    }

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


def simulation_tick(npc_list: List[Dict]) -> Dict[str, Any]:
    results = {
        "thoughts": [],
        "actions": [],
        "moods": [],
        "opinions": [],
        "interactions": [],
        "decisions": [],
        "errors": [],
    }
    for npc in npc_list:
        char_id = npc.get("char_id") or npc.get("id", "")
        char_name = npc.get("name", "Unknown")
        archetype = npc.get("archetype") or npc.get("personality_type", "scholar")
        affiliation = npc.get("affiliation", "independent")
        title = npc.get("title", "")
        description = npc.get("description", "")
        try:
            new_mood = update_mood(char_id, archetype)
            results["moods"].append({"char_id": char_id, "mood": new_mood})
            decision = make_decision(
                char_id, char_name, archetype, affiliation, mood=new_mood
            )
            if decision:
                results["decisions"].append(decision)
                try:
                    broadcast_decision_event(decision, affiliation)
                except Exception:
                    logger.debug("Decision broadcast failed for NPC decision event")
                category = decision.get("category", "")
                if category in (
                    "advance_goal",
                    "investigate",
                    "seek_resources",
                    "self_improve",
                    "explore",
                ):
                    thought = generate_thought(
                        char_id,
                        char_name,
                        archetype,
                        affiliation,
                        title,
                        description,
                        mood=new_mood,
                    )
                    if thought:
                        results["thoughts"].append(thought)
                    action = generate_action(
                        char_id, char_name, archetype, affiliation, mood=new_mood
                    )
                    if action:
                        results["actions"].append(action)
                elif category in ("socialize", "help_ally", "confront_rival"):
                    thought = generate_thought(
                        char_id,
                        char_name,
                        archetype,
                        affiliation,
                        title,
                        description,
                        mood=new_mood,
                    )
                    if thought:
                        results["thoughts"].append(thought)
                elif category == "rest":
                    thought = generate_thought(
                        char_id,
                        char_name,
                        archetype,
                        affiliation,
                        title,
                        description,
                        mood=new_mood,
                    )
                    if thought:
                        results["thoughts"].append(thought)
                elif category == "react_to_events":
                    action = generate_action(
                        char_id, char_name, archetype, affiliation, mood=new_mood
                    )
                    if action:
                        results["actions"].append(action)
            else:
                if random.random() < 0.5:
                    thought = generate_thought(
                        char_id,
                        char_name,
                        archetype,
                        affiliation,
                        title,
                        description,
                        mood=new_mood,
                    )
                    if thought:
                        results["thoughts"].append(thought)
            r = _get_redis()
            opinion_keys = list(r.scan_iter(f"npc_opinion:{char_id}:*"))
            for okey in opinion_keys[:2]:
                if random.random() < 0.3:
                    player_id = okey.split(":")[-1]
                    shift_type = random.choice(
                        ["friendly", "neutral", "neutral", "helpful"]
                    )
                    opinion = update_opinion(char_id, player_id, shift_type)
                    results["opinions"].append(
                        {"char_id": char_id, "player_id": player_id, "opinion": opinion}
                    )
            r.set(f"npc_last_active:{char_id}", str(int(time.time())), ex=86400 * 7)
        except Exception as e:
            results["errors"].append({"char_id": char_id, "error": str(e)})
    if len(npc_list) >= 2:
        num_interactions = random.randint(1, min(3, len(npc_list) // 2))
        for _ in range(num_interactions):
            pair = random.sample(npc_list, 2)
            try:
                event = generate_npc_interaction(pair[0], pair[1])
                if event:
                    results["interactions"].append(event)
            except Exception as e:
                results["errors"].append({"error": f"interaction failed: {str(e)}"})
    try:
        ws_changes = update_world_state(npc_list, results.get("decisions", []))
        if ws_changes:
            results["world_state_changes"] = ws_changes
    except Exception as e:
        results["errors"].append({"error": f"world state update failed: {str(e)}"})

    return results


# --- NPC GOALS SYSTEM (Phase 5) ---
# --- NPC GOALS SYSTEM (Phase 5) ---

GOAL_TYPES = {
    "scholar": [
        (
            "research_breakthrough",
            "Achieve a breakthrough in {field} research",
            "research",
        ),
        ("uncover_truth", "Uncover the truth about {danger}", "investigation"),
        ("publish_findings", "Publish definitive findings on {topic}", "research"),
        (
            "forge_alliance",
            "Secure a research alliance with the {faction}",
            "diplomacy",
        ),
    ],
    "warrior": [
        ("defend_territory", "Fortify defenses against {danger}", "defense"),
        ("train_elites", "Train elite operatives for the {faction}", "training"),
        ("eliminate_threat", "Neutralize the {danger} threat", "combat"),
        ("earn_command", "Earn a command position in {faction}", "ambition"),
    ],
    "rogue": [
        ("acquire_asset", "Acquire the {item} by any means necessary", "acquisition"),
        (
            "expose_secret",
            "Expose {faction} secrets to the right buyer",
            "intelligence",
        ),
        (
            "build_network",
            "Build an underground network across {location}",
            "networking",
        ),
        ("disappear_clean", "Execute a clean disappearance from {faction}", "escape"),
    ],
    "mystic": [
        (
            "commune_with_void",
            "Commune with the consciousness of the void",
            "transcendence",
        ),
        ("interpret_omen", "Interpret the omen of {omen}", "divination"),
        (
            "awaken_potential",
            "Awaken latent consciousness in {location}",
            "transcendence",
        ),
        ("warn_others", "Warn the station about the {danger}", "prophecy"),
    ],
    "leader": [
        (
            "unite_factions",
            "Broker unity between {faction} and rival factions",
            "diplomacy",
        ),
        ("pass_legislation", "Pass the {topic} directive through council", "politics"),
        ("secure_resources", "Secure resource rights for {location}", "economics"),
        ("consolidate_power", "Consolidate influence over {faction}", "ambition"),
    ],
    "sage": [
        (
            "find_balance",
            "Restore balance to {location} after recent turmoil",
            "harmony",
        ),
        (
            "teach_wisdom",
            "Teach the principle of {concept} to the next generation",
            "teaching",
        ),
        (
            "meditate_on_truth",
            "Meditate until the truth of {concept} reveals itself",
            "transcendence",
        ),
        (
            "heal_division",
            "Heal the rift between warring factions in {faction}",
            "harmony",
        ),
    ],
    "wanderer": [
        (
            "chart_unknown",
            "Chart the uncharted {feature} beyond station limits",
            "exploration",
        ),
        ("find_origin", "Discover the origin of the {creature}", "exploration"),
        (
            "gather_tales",
            "Collect stories from every corner of {location}",
            "discovery",
        ),
        (
            "return_home",
            "Find a way back to the homeworld through {location}",
            "pilgrimage",
        ),
    ],
    "hero": [
        (
            "protect_weak",
            "Protect the civilians in {location} from {danger}",
            "protection",
        ),
        ("rally_allies", "Rally allies against the {danger} threat", "leadership"),
        ("complete_quest", "Complete the mission in {location}", "duty"),
        ("inspire_hope", "Inspire hope across the station during the crisis", "morale"),
    ],
    "deceiver": [
        (
            "manipulate_faction",
            "Manipulate {faction} into serving hidden interests",
            "manipulation",
        ),
        (
            "plant_misinfo",
            "Plant disinformation about {topic} across the station",
            "deception",
        ),
        (
            "eliminate_rival",
            "Quietly eliminate a rival within {faction}",
            "elimination",
        ),
        ("control_narrative", "Control the narrative around {topic}", "propaganda"),
    ],
    "guardian": [
        (
            "enforce_protocol",
            "Enforce protocol {number} across all sectors",
            "enforcement",
        ),
        (
            "uncover_conspiracy",
            "Uncover the conspiracy behind {danger}",
            "investigation",
        ),
        (
            "shield_innocents",
            "Shield the inhabitants of {location} from {danger}",
            "protection",
        ),
        ("maintain_order", "Maintain order during the {topic} crisis", "enforcement"),
    ],
}

GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_ABANDONED = "abandoned"

MAX_GOALS_PER_NPC = 3
GOAL_TTL = 86400 * 14
GOAL_PROGRESS_PER_ACTION = 15
GOAL_PROGRESS_VARIANCE = 10


def generate_goal(char_id: str, archetype: str) -> Optional[Dict]:
    templates = GOAL_TYPES.get(archetype, GOAL_TYPES["scholar"])
    goal_type, template, category = random.choice(templates)

    description = template
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    goal = {
        "goal_id": f"{char_id}_{goal_type}_{int(time.time())}",
        "char_id": char_id,
        "goal_type": goal_type,
        "category": category,
        "description": description,
        "progress": 0,
        "status": GOAL_STATUS_ACTIVE,
        "created_ts": int(time.time()),
        "updated_ts": int(time.time()),
    }

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    existing = _get_goals_raw(char_id)
    active = [g for g in existing if g.get("status") == GOAL_STATUS_ACTIVE]
    if len(active) >= MAX_GOALS_PER_NPC:
        return None

    r.rpush(key, json.dumps(goal))
    r.expire(key, GOAL_TTL)
    return goal


def _get_goals_raw(char_id: str) -> List[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)
    goals = []
    for item in raw:
        try:
            goals.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return goals


def get_goals(char_id: str, status: Optional[str] = None) -> List[Dict]:
    goals = _get_goals_raw(char_id)
    if status:
        goals = [g for g in goals if g.get("status") == status]
    return goals


def advance_goal(
    char_id: str, goal_id: str, progress_delta: Optional[float] = None
) -> Optional[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue

        if goal.get("goal_id") == goal_id and goal.get("status") == GOAL_STATUS_ACTIVE:
            if progress_delta is None:
                progress_delta = GOAL_PROGRESS_PER_ACTION + random.uniform(
                    -GOAL_PROGRESS_VARIANCE, GOAL_PROGRESS_VARIANCE
                )
            goal["progress"] = min(
                100, max(0, goal.get("progress", 0) + progress_delta)
            )
            goal["updated_ts"] = int(time.time())

            if goal["progress"] >= 100:
                goal["status"] = GOAL_STATUS_COMPLETED
            updated = goal

        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


def set_goal_status(char_id: str, goal_id: str, status: str) -> Optional[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if goal.get("goal_id") == goal_id:
            goal["status"] = status
            goal["updated_ts"] = int(time.time())
            updated = goal
        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


# --- GOAL-DRIVEN ACTION GENERATION ---


def generate_goal_driven_action(
    char_id: str, char_name: str, archetype: str, affiliation: str, mood: str = ""
) -> Optional[Dict]:
    active_goals = get_goals(char_id, status=GOAL_STATUS_ACTIVE)

    if not active_goals:
        return generate_action(char_id, char_name, archetype, affiliation, mood)

    target_goal = random.choice(active_goals)

    goal_action_templates = {
        "research": [
            ("research", "continued work on their goal: {goal_desc}"),
            ("experiment", "ran experiments advancing: {goal_desc}"),
            ("analysis", "analyzed new data related to: {goal_desc}"),
        ],
        "investigation": [
            ("investigation", "followed a lead on: {goal_desc}"),
            ("surveillance", "conducted surveillance for: {goal_desc}"),
            ("interrogation", "questioned contacts about: {goal_desc}"),
        ],
        "defense": [
            ("fortification", "reinforced defenses as part of: {goal_desc}"),
            ("patrol", "increased patrols for: {goal_desc}"),
            ("inspection", "inspected perimeter for: {goal_desc}"),
        ],
        "training": [
            ("training", "ran drills advancing: {goal_desc}"),
            ("evaluation", "evaluated recruits for: {goal_desc}"),
        ],
        "combat": [
            ("strike", "launched a tactical strike for: {goal_desc}"),
            ("skirmish", "engaged hostiles related to: {goal_desc}"),
        ],
        "ambition": [
            ("maneuver", "made a political maneuver for: {goal_desc}"),
            ("campaign", "campaigned for support toward: {goal_desc}"),
        ],
        "acquisition": [
            ("heist", "planned an acquisition for: {goal_desc}"),
            ("negotiation", "negotiated terms for: {goal_desc}"),
        ],
        "intelligence": [
            ("intelligence", "gathered intel advancing: {goal_desc}"),
            ("reconnaissance", "scouted for: {goal_desc}"),
        ],
        "networking": [
            ("recruitment", "recruited contacts for: {goal_desc}"),
            ("deal", "struck a deal advancing: {goal_desc}"),
        ],
        "escape": [
            ("preparation", "made preparations for: {goal_desc}"),
            ("cover", "established cover for: {goal_desc}"),
        ],
        "transcendence": [
            ("ritual", "performed a ritual advancing: {goal_desc}"),
            ("meditation", "entered deep meditation for: {goal_desc}"),
        ],
        "divination": [
            ("vision", "sought a vision about: {goal_desc}"),
            ("study", "studied ancient texts about: {goal_desc}"),
        ],
        "prophecy": [
            ("warning", "issued a warning about: {goal_desc}"),
            ("teaching", "taught others about: {goal_desc}"),
        ],
        "diplomacy": [
            ("negotiation", "entered negotiations for: {goal_desc}"),
            ("meeting", "convened a meeting about: {goal_desc}"),
        ],
        "politics": [
            ("decree", "pushed legislation for: {goal_desc}"),
            ("campaign", "lobbied support for: {goal_desc}"),
        ],
        "economics": [
            ("trade", "negotiated trade terms for: {goal_desc}"),
            ("audit", "audited resources for: {goal_desc}"),
        ],
        "harmony": [
            ("mediation", "mediated a dispute for: {goal_desc}"),
            ("counsel", "offered counsel for: {goal_desc}"),
        ],
        "teaching": [
            ("lecture", "gave a lecture about: {goal_desc}"),
            ("mentorship", "mentored a student for: {goal_desc}"),
        ],
        "exploration": [
            ("exploration", "set out to explore for: {goal_desc}"),
            ("survey", "conducted a survey for: {goal_desc}"),
        ],
        "discovery": [
            ("discovery", "made a discovery advancing: {goal_desc}"),
            ("documentation", "documented findings for: {goal_desc}"),
        ],
        "pilgrimage": [
            ("journey", "began a journey for: {goal_desc}"),
            ("preparation", "prepared for the pilgrimage: {goal_desc}"),
        ],
        "protection": [
            ("guard", "stood guard for: {goal_desc}"),
            ("escort", "escorted civilians for: {goal_desc}"),
        ],
        "leadership": [
            ("rally", "rallied supporters for: {goal_desc}"),
            ("command", "took command advancing: {goal_desc}"),
        ],
        "duty": [
            ("mission", "executed a mission for: {goal_desc}"),
            ("report", "filed a report on: {goal_desc}"),
        ],
        "morale": [
            ("speech", "gave an inspiring speech for: {goal_desc}"),
            ("aid", "delivered aid for: {goal_desc}"),
        ],
        "manipulation": [
            ("manipulation", "manipulated events for: {goal_desc}"),
            ("scheme", "advanced a scheme for: {goal_desc}"),
        ],
        "deception": [
            ("plant", "planted false intel for: {goal_desc}"),
            ("cover", "maintained cover for: {goal_desc}"),
        ],
        "elimination": [
            ("ambush", "set an ambush for: {goal_desc}"),
            ("sabotage", "sabotaged operations for: {goal_desc}"),
        ],
        "propaganda": [
            ("broadcast", "broadcast propaganda for: {goal_desc}"),
            ("censorship", "suppressed information about: {goal_desc}"),
        ],
        "enforcement": [
            ("enforcement", "enforced regulations for: {goal_desc}"),
            ("crackdown", "led a crackdown for: {goal_desc}"),
        ],
    }

    category = target_goal.get("category", "research")
    templates = goal_action_templates.get(category, goal_action_templates["research"])
    action_type, template = random.choice(templates)

    goal_short = target_goal.get("description", "their objective")
    if len(goal_short) > 60:
        goal_short = goal_short[:57] + "..."
    description = template.replace("{goal_desc}", goal_short)

    action = {
        "char_id": char_id,
        "char_name": char_name,
        "action_type": action_type,
        "description": f"{char_name} {description}",
        "mood": mood or "contemplative",
        "goal_id": target_goal.get("goal_id"),
        "ts": int(time.time()),
    }

    r = _get_redis()
    akey = f"npc_actions:{char_id}"
    r.zadd(akey, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(akey, 0, -(MAX_ACTIONS + 1))
    r.expire(akey, THOUGHT_TTL)

    world_key = "npc_world_events"
    r.zadd(world_key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(world_key, 0, -(MAX_WORLD_EVENTS + 1))
    r.expire(world_key, THOUGHT_TTL)

    advance_goal(char_id, target_goal["goal_id"])

    return action


# --- PLAYER ABSENCE DETECTION ---


def get_absence_report(char_id: str, player_id: str) -> Dict[str, Any]:
    r = _get_redis()
    thoughts = get_recent_thoughts(char_id, limit=3)
    actions = get_recent_actions(char_id, limit=3)
    opinion = get_opinion(char_id, player_id)
    mood = get_mood(char_id)
    last_active = r.get(f"npc_last_active:{char_id}")

    return {
        "char_id": char_id,
        "player_id": player_id,
        "mood": mood,
        "opinion": opinion,
        "recent_thoughts": thoughts,
        "recent_actions": actions,
        "last_active": last_active,
    }


# --- WORLD STATE SYSTEM (Phase 6b) ---

WORLD_CONDITIONS = {
    "tension_level": {
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Tension Level",
        "description": "Overall political and social tension on the station",
        "high_bias": {
            "react_to_events": 1.5,
            "confront_rival": 1.3,
            "investigate": 1.2,
        },
        "low_bias": {"socialize": 1.3, "rest": 1.2, "explore": 1.2},
    },
    "resource_abundance": {
        "default": 60,
        "min": 0,
        "max": 100,
        "label": "Resource Abundance",
        "description": "Availability of essential supplies and materials",
        "high_bias": {"explore": 1.3, "self_improve": 1.3, "advance_goal": 1.2},
        "low_bias": {"seek_resources": 1.8, "rest": 0.7, "help_ally": 0.8},
    },
    "threat_level": {
        "default": 30,
        "min": 0,
        "max": 100,
        "label": "Threat Level",
        "description": "Active threats to station safety and security",
        "high_bias": {
            "rest": 1.6,
            "help_ally": 1.5,
            "investigate": 1.4,
            "advance_goal": 1.2,
        },
        "low_bias": {"explore": 1.4, "socialize": 1.3, "self_improve": 1.2},
    },
    "stability": {
        "default": 65,
        "min": 0,
        "max": 100,
        "label": "Stability",
        "description": "Overall station structural and social stability",
        "high_bias": {"advance_goal": 1.3, "self_improve": 1.3, "socialize": 1.2},
        "low_bias": {"react_to_events": 1.5, "seek_resources": 1.3, "investigate": 1.3},
    },
    "morale": {
        "default": 55,
        "min": 0,
        "max": 100,
        "label": "Morale",
        "description": "General morale and hope across the station population",
        "high_bias": {"advance_goal": 1.4, "explore": 1.3, "help_ally": 1.3},
        "low_bias": {"rest": 1.5, "seek_resources": 1.2, "socialize": 0.8},
    },
    "anomaly_activity": {
        "default": 20,
        "min": 0,
        "max": 100,
        "label": "Anomaly Activity",
        "description": "Unexplained phenomena and consciousness anomalies detected",
        "high_bias": {"investigate": 1.7, "react_to_events": 1.5, "explore": 1.3},
        "low_bias": {"rest": 1.2, "socialize": 1.2},
    },
}

WORLD_STATE_KEY = "world_state"
WORLD_STATE_HISTORY_KEY = "world_state_history"
MAX_WORLD_HISTORY = 50
WORLD_STATE_TTL = 86400 * 30


def get_world_state():
    r = _get_redis()
    stored = r.hgetall(WORLD_STATE_KEY)
    state = {}
    for cond_key, config in WORLD_CONDITIONS.items():
        if cond_key in stored:
            state[cond_key] = int(float(stored[cond_key]))
        else:
            state[cond_key] = config["default"]
    state["_meta"] = {
        "conditions": {
            k: {
                "label": v["label"],
                "description": v["description"],
                "min": v["min"],
                "max": v["max"],
            }
            for k, v in WORLD_CONDITIONS.items()
        },
        "last_updated": r.get("world_state_updated") or "never",
    }
    return state


def get_world_condition(condition):
    if condition not in WORLD_CONDITIONS:
        return None
    r = _get_redis()
    val = r.hget(WORLD_STATE_KEY, condition)
    if val is not None:
        return int(
            float(val)
        )  # float() first handles decimal strings from simulation_engine
    return WORLD_CONDITIONS[condition]["default"]


def set_world_condition(condition, value):
    if condition not in WORLD_CONDITIONS:
        return None
    config = WORLD_CONDITIONS[condition]
    value = max(config["min"], min(config["max"], value))
    r = _get_redis()
    r.hset(WORLD_STATE_KEY, condition, str(value))
    r.set("world_state_updated", str(int(time.time())), ex=WORLD_STATE_TTL)
    return {"condition": condition, "value": value, "label": config["label"]}


def update_world_state(npc_list, tick_decisions):
    tick_result = {}
    # Phase 7a: faction dynamics
    try:
        _fd_events = get_broadcast_events(limit=50)
        _fd = compute_faction_dynamics(npc_list, tick_decisions, _fd_events)
        _fs = compute_faction_stances(_fd, _fd_events)
        store_faction_dynamics(_fd, _fs)
        tick_result["faction_dynamics"] = {
            f: v["cohesion"] for f, v in _fd.items() if v.get("member_count", 0) > 0
        }
    except Exception as _fd_err:
        tick_result["faction_dynamics_error"] = str(_fd_err)
        r = _get_redis()
        current = get_world_state()

        num_npcs = max(1, len(npc_list))
        confront_count = sum(
            1 for d in tick_decisions if d.get("category") == "confront_rival"
        )
        investigate_count = sum(
            1 for d in tick_decisions if d.get("category") == "investigate"
        )
        seek_resource_count = sum(
            1 for d in tick_decisions if d.get("category") == "seek_resources"
        )
        help_ally_count = sum(
            1 for d in tick_decisions if d.get("category") == "help_ally"
        )
        react_count = sum(
            1 for d in tick_decisions if d.get("category") == "react_to_events"
        )
        explore_count = sum(1 for d in tick_decisions if d.get("category") == "explore")
        advance_count = sum(
            1 for d in tick_decisions if d.get("category") == "advance_goal"
        )
        rest_count = sum(1 for d in tick_decisions if d.get("category") == "rest")

        confront_rate = confront_count / num_npcs
        investigate_rate = investigate_count / num_npcs
        seek_rate = seek_resource_count / num_npcs
        help_rate = help_ally_count / num_npcs
        react_rate = react_count / num_npcs
        explore_rate = explore_count / num_npcs
        advance_rate = advance_count / num_npcs
        rest_rate = rest_count / num_npcs

        mood_counts = {}
        for npc in npc_list:
            cid = npc.get("char_id") or npc.get("id", "")
            m = r.get(f"npc_mood:{cid}") or "contemplative"
            mood_counts[m] = mood_counts.get(m, 0) + 1
        negative_moods = {
            "frustrated",
            "aggressive",
            "suspicious",
            "anxious",
            "alarmed",
            "worried",
            "unsettled",
            "weary",
            "melancholic",
            "paranoid",
            "burdened",
        }
        positive_moods = {
            "satisfied",
            "inspired",
            "serene",
            "peaceful",
            "hopeful",
            "excited",
            "confident",
            "enlightened",
            "adventurous",
            "free",
            "determined",
            "resolute",
            "valiant",
            "steadfast",
            "patient",
            "hopeful",
        }
        neg_count = sum(mood_counts.get(m, 0) for m in negative_moods)
        pos_count = sum(mood_counts.get(m, 0) for m in positive_moods)
        neg_ratio = neg_count / max(1, num_npcs)
        pos_ratio = pos_count / max(1, num_npcs)

        new_tension = (
            current["tension_level"]
            + (confront_rate * 12)
            + (react_rate * 6)
            - (help_rate * 5)
            - (rest_rate * 3)
        )
        new_tension += (neg_ratio * 5) - (pos_ratio * 3)

        new_resources = (
            current["resource_abundance"]
            + (explore_rate * 4)
            - (seek_rate * 8)
            - (num_npcs * 0.15)
        )
        new_resources += random.uniform(-2, 2)

        new_threat = (
            current["threat_level"]
            + (investigate_rate * 5)
            + (react_rate * 8)
            - (help_rate * 3)
        )
        new_threat += random.uniform(-3, 3)

        new_stability = (
            current["stability"]
            - (confront_rate * 8)
            - (react_rate * 4)
            + (help_rate * 6)
            + (advance_rate * 3)
        )
        new_stability += (pos_ratio * 4) - (neg_ratio * 3)

        new_morale = (
            current["morale"]
            + (pos_ratio * 8)
            - (neg_ratio * 7)
            + (help_rate * 5)
            - (confront_rate * 4)
        )
        new_morale += (advance_rate * 3) - (seek_rate * 2)

        new_anomaly = (
            current["anomaly_activity"] + (investigate_rate * 6) + random.uniform(-5, 5)
        )
        new_anomaly += (explore_rate * 3) - (rest_rate * 2)

        changes = {}
        updates = {
            "tension_level": max(0, min(100, int(new_tension))),
            "resource_abundance": max(0, min(100, int(new_resources))),
            "threat_level": max(0, min(100, int(new_threat))),
            "stability": max(0, min(100, int(new_stability))),
            "morale": max(0, min(100, int(new_morale))),
            "anomaly_activity": max(0, min(100, int(new_anomaly))),
        }

        for key, val in updates.items():
            old = current.get(key, WORLD_CONDITIONS[key]["default"])
            if val != old:
                delta = val - old
                changes[key] = {"old": old, "new": val, "delta": delta}
            r.hset(WORLD_STATE_KEY, key, str(val))

        now = int(time.time())
        r.set("world_state_updated", str(now), ex=WORLD_STATE_TTL)

        snapshot = {k: v for k, v in updates.items()}
        snapshot["ts"] = now
        r.zadd(WORLD_STATE_HISTORY_KEY, {json.dumps(snapshot): now})
        r.zremrangebyrank(WORLD_STATE_HISTORY_KEY, 0, -(MAX_WORLD_HISTORY + 1))
        r.expire(WORLD_STATE_HISTORY_KEY, WORLD_STATE_TTL)

        return {
            "updated": updates,
            "changes": changes,
            "ts": now,
            "faction_dynamics": tick_result.get("faction_dynamics"),
            "faction_dynamics_error": tick_result.get("faction_dynamics_error"),
        }


def get_world_state_history(limit=10):
    r = _get_redis()
    raw = r.zrevrange(WORLD_STATE_HISTORY_KEY, 0, limit - 1)
    history = []
    for item in raw:
        try:
            history.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return history


def _world_state_decision_modifier(category):
    modifier = 1.0
    state = get_world_state()
    for cond_key, config in WORLD_CONDITIONS.items():
        value = state.get(cond_key, config["default"])
        if value >= 70:
            bias = config.get("high_bias", {})
            modifier *= bias.get(category, 1.0)
        elif value <= 30:
            bias = config.get("low_bias", {})
            modifier *= bias.get(category, 1.0)
    return modifier


# --- NPC DECISION ENGINE (Phase 6a) ---

DECISION_CATEGORIES = [
    "advance_goal",
    "socialize",
    "investigate",
    "rest",
    "react_to_events",
    "seek_resources",
    "self_improve",
    "confront_rival",
    "help_ally",
    "explore",
]

MOOD_DECISION_BIAS = {
    "contemplative": {"advance_goal": 1.5, "rest": 1.3, "self_improve": 1.2},
    "curious": {"explore": 1.8, "investigate": 1.5, "advance_goal": 1.2},
    "frustrated": {"confront_rival": 1.6, "investigate": 1.3, "advance_goal": 1.1},
    "inspired": {"advance_goal": 1.8, "self_improve": 1.4, "explore": 1.2},
    "distracted": {"rest": 1.5, "socialize": 1.3, "explore": 1.2},
    "analytical": {"investigate": 1.7, "advance_goal": 1.4, "self_improve": 1.2},
    "vigilant": {"investigate": 1.6, "react_to_events": 1.8, "help_ally": 1.3},
    "restless": {"explore": 1.6, "confront_rival": 1.3, "advance_goal": 1.2},
    "satisfied": {"socialize": 1.5, "rest": 1.4, "help_ally": 1.3},
    "aggressive": {"confront_rival": 2.0, "investigate": 1.3, "advance_goal": 1.2},
    "stoic": {"advance_goal": 1.4, "rest": 1.3, "self_improve": 1.2},
    "battle-ready": {"confront_rival": 1.8, "react_to_events": 1.6, "help_ally": 1.3},
    "calculating": {"advance_goal": 1.6, "investigate": 1.5, "seek_resources": 1.3},
    "amused": {"socialize": 1.7, "explore": 1.3, "rest": 1.2},
    "suspicious": {"investigate": 1.8, "react_to_events": 1.5, "confront_rival": 1.2},
    "opportunistic": {"seek_resources": 1.7, "advance_goal": 1.4, "explore": 1.3},
    "bored": {"explore": 1.6, "socialize": 1.4, "seek_resources": 1.3},
    "smug": {"socialize": 1.5, "advance_goal": 1.3, "rest": 1.4},
    "transcendent": {"self_improve": 1.8, "rest": 1.5, "advance_goal": 1.2},
    "troubled": {"investigate": 1.5, "react_to_events": 1.4, "help_ally": 1.2},
    "visionary": {"advance_goal": 1.7, "explore": 1.5, "self_improve": 1.3},
    "withdrawn": {"rest": 1.7, "self_improve": 1.4, "investigate": 1.2},
    "enlightened": {"help_ally": 1.6, "self_improve": 1.5, "advance_goal": 1.3},
    "unsettled": {"investigate": 1.6, "react_to_events": 1.5, "seek_resources": 1.2},
    "commanding": {"advance_goal": 1.6, "help_ally": 1.4, "confront_rival": 1.3},
    "concerned": {"react_to_events": 1.7, "help_ally": 1.6, "investigate": 1.3},
    "strategic": {"advance_goal": 1.7, "investigate": 1.5, "seek_resources": 1.3},
    "impatient": {"advance_goal": 1.5, "confront_rival": 1.4, "explore": 1.2},
    "diplomatic": {"socialize": 1.6, "help_ally": 1.5, "advance_goal": 1.3},
    "weary": {"rest": 2.0, "self_improve": 1.2, "socialize": 0.8},
    "serene": {"self_improve": 1.6, "rest": 1.5, "help_ally": 1.3},
    "pensive": {"advance_goal": 1.4, "rest": 1.3, "investigate": 1.3},
    "patient": {"advance_goal": 1.5, "self_improve": 1.4, "help_ally": 1.3},
    "worried": {"react_to_events": 1.7, "investigate": 1.5, "help_ally": 1.3},
    "peaceful": {"rest": 1.6, "socialize": 1.4, "self_improve": 1.3},
    "melancholic": {"rest": 1.5, "explore": 1.3, "self_improve": 1.2},
    "excited": {"explore": 1.7, "advance_goal": 1.5, "socialize": 1.4},
    "homesick": {"socialize": 1.5, "rest": 1.4, "explore": 1.2},
    "adventurous": {"explore": 2.0, "seek_resources": 1.4, "investigate": 1.3},
    "wistful": {"rest": 1.4, "socialize": 1.3, "explore": 1.2},
    "free": {"explore": 1.8, "socialize": 1.4, "advance_goal": 1.2},
    "determined": {"advance_goal": 2.0, "confront_rival": 1.4, "help_ally": 1.2},
    "hopeful": {"advance_goal": 1.6, "help_ally": 1.5, "socialize": 1.3},
    "burdened": {"rest": 1.5, "advance_goal": 1.3, "help_ally": 1.2},
    "resolute": {"advance_goal": 1.8, "confront_rival": 1.4, "react_to_events": 1.3},
    "valiant": {"help_ally": 1.8, "confront_rival": 1.5, "advance_goal": 1.3},
    "scheming": {"seek_resources": 1.6, "advance_goal": 1.5, "investigate": 1.4},
    "paranoid": {"investigate": 1.8, "react_to_events": 1.6, "confront_rival": 1.3},
    "confident": {"advance_goal": 1.6, "socialize": 1.4, "explore": 1.3},
    "anxious": {"investigate": 1.5, "react_to_events": 1.4, "seek_resources": 1.3},
    "protective": {"help_ally": 1.9, "react_to_events": 1.6, "advance_goal": 1.2},
    "watchful": {"investigate": 1.7, "react_to_events": 1.6, "help_ally": 1.3},
    "stern": {"advance_goal": 1.5, "confront_rival": 1.4, "help_ally": 1.2},
    "alarmed": {"react_to_events": 2.0, "investigate": 1.6, "help_ally": 1.4},
    "steadfast": {"advance_goal": 1.6, "help_ally": 1.4, "confront_rival": 1.3},
}

ARCHETYPE_DECISION_BIAS = {
    "scholar": {"advance_goal": 1.4, "investigate": 1.6, "self_improve": 1.3},
    "warrior": {"confront_rival": 1.5, "help_ally": 1.4, "react_to_events": 1.3},
    "rogue": {"seek_resources": 1.6, "explore": 1.4, "investigate": 1.3},
    "mystic": {"self_improve": 1.6, "explore": 1.3, "react_to_events": 1.3},
    "leader": {"advance_goal": 1.5, "socialize": 1.4, "help_ally": 1.3},
    "sage": {"self_improve": 1.5, "help_ally": 1.4, "rest": 1.3},
    "wanderer": {"explore": 1.7, "seek_resources": 1.3, "socialize": 1.2},
    "hero": {"help_ally": 1.7, "confront_rival": 1.4, "react_to_events": 1.4},
    "deceiver": {"seek_resources": 1.5, "investigate": 1.4, "socialize": 1.3},
    "guardian": {"react_to_events": 1.5, "help_ally": 1.5, "investigate": 1.3},
}

DECISION_DESCRIPTIONS = {
    "advance_goal": "decided to work toward their goal",
    "socialize": "decided to seek out conversation",
    "investigate": "decided to look into something suspicious",
    "rest": "decided to rest and reflect",
    "react_to_events": "decided to respond to recent events",
    "seek_resources": "decided to acquire what they need",
    "self_improve": "decided to train and improve themselves",
    "confront_rival": "decided to confront an adversary",
    "help_ally": "decided to aid a companion",
    "explore": "decided to explore new territory",
}

MAX_DECISIONS = 10
DECISION_TTL = 86400 * 7


def _score_decision_option(
    category,
    char_id,
    archetype,
    mood,
    has_active_goals,
    has_allies,
    has_rivals,
    recent_event_count,
    broadcast_event_count=0,
):
    score = 1.0
    mood_biases = MOOD_DECISION_BIAS.get(mood, {})
    score *= mood_biases.get(category, 1.0)
    arch_biases = ARCHETYPE_DECISION_BIAS.get(archetype, {})
    score *= arch_biases.get(category, 1.0)
    if category == "advance_goal" and not has_active_goals:
        score *= 0.3
    if category == "help_ally" and not has_allies:
        score *= 0.4
    if category == "confront_rival" and not has_rivals:
        score *= 0.3
    if category == "react_to_events" and recent_event_count == 0:
        score *= 0.2
    elif category == "react_to_events" and recent_event_count > 3:
        score *= 1.3
    if category == "react_to_events" and broadcast_event_count > 0:
        score *= 1.0 + min(broadcast_event_count * 0.1, 0.5)
    # Apply cascade decision bias from event_cascade reactions
    try:
        _bias_r = _get_redis()
        _bias_raw = _bias_r.get(f"npc_decision_bias:{char_id}")
        if _bias_raw:
            _bias_data = json.loads(_bias_raw)
            _bias_val = _bias_data.get(category, 1.0)
            if _bias_val and _bias_val != 1.0:
                score *= _bias_val
    except Exception:
        pass  # bias is optional — never break decision scoring

    score *= _world_state_decision_modifier(category)
    score += random.uniform(-0.1, 0.1)
    return max(0.1, score)


def evaluate_decision_options(char_id, char_name, archetype, affiliation, mood=""):
    mood = mood or get_mood(char_id)
    active_goals = get_goals(char_id, status=GOAL_STATUS_ACTIVE)
    has_active_goals = len(active_goals) > 0
    rel_summary = get_relationship_summary(char_id)
    has_allies = len(rel_summary.get("allies", [])) > 0
    has_rivals = len(rel_summary.get("rivals", [])) > 0
    recent_events = get_world_events(limit=5)
    recent_event_count = len(recent_events)
    broadcast_events = []
    try:
        broadcast_events = get_broadcast_events(char_id, affiliation, limit=10)
    except Exception:
        logger.debug(
            f"Broadcast events retrieval failed for {char_id}; proceeding without broadcast context"
        )
    broadcast_event_count = len(broadcast_events)

    options = []
    for cat in DECISION_CATEGORIES:
        score = _score_decision_option(
            cat,
            char_id,
            archetype,
            mood,
            has_active_goals,
            has_allies,
            has_rivals,
            recent_event_count,
            broadcast_event_count,
        )
        reasons = []
        mood_biases = MOOD_DECISION_BIAS.get(mood, {})
        if mood_biases.get(cat, 1.0) > 1.2:
            reasons.append("feeling " + mood)
        arch_biases = ARCHETYPE_DECISION_BIAS.get(archetype, {})
        if arch_biases.get(cat, 1.0) > 1.2:
            reasons.append(archetype + " nature")
        if cat == "advance_goal" and has_active_goals:
            top_goal = active_goals[0]
            reasons.append(
                "pursuing: " + top_goal.get("description", "unknown goal")[:50]
            )
        if cat == "help_ally" and has_allies:
            ally = rel_summary["allies"][0].get("char_id", "an ally")
            reasons.append("ally: " + ally)
        if cat == "confront_rival" and has_rivals:
            rival = rel_summary["rivals"][0].get("char_id", "a rival")
            reasons.append("rival: " + rival)
        if cat == "react_to_events" and recent_event_count > 0:
            reasons.append(str(recent_event_count) + " recent events")
        options.append({"category": cat, "score": round(score, 2), "reasons": reasons})

    options.sort(key=lambda x: x["score"], reverse=True)
    return options


def make_decision(char_id, char_name, archetype, affiliation, mood=""):
    options = evaluate_decision_options(
        char_id, char_name, archetype, affiliation, mood
    )
    if not options:
        return None

    top_n = min(3, len(options))
    top_options = options[:top_n]
    scores = [o["score"] for o in top_options]
    chosen = random.choices(top_options, weights=scores, k=1)[0]
    category = chosen["category"]
    decision_desc = DECISION_DESCRIPTIONS.get(category, "made a decision")
    reasoning = " + ".join(chosen.get("reasons", ["general inclination"]))

    action_result = None

    if category == "advance_goal":
        action_result = generate_goal_driven_action(
            char_id, char_name, archetype, affiliation, mood
        )
    elif category == "socialize":
        rel = get_npc_relationships(char_id)
        if rel:
            best_ally = max(rel.items(), key=lambda x: x[1])
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {"char_id": best_ally[0], "name": best_ally[0], "id": best_ally[0]},
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "investigate":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "investigation"
            action_result["description"] = (
                char_name + " began investigating a matter of concern"
            )
    elif category == "rest":
        action_result = {
            "char_id": char_id,
            "char_name": char_name,
            "action_type": "rest",
            "description": char_name + " " + decision_desc,
            "mood": mood or "contemplative",
            "ts": int(time.time()),
        }
        r = _get_redis()
        r.zadd(
            f"npc_actions:{char_id}", {json.dumps(action_result): action_result["ts"]}
        )
    elif category == "react_to_events":
        events = get_world_events(limit=3)
        if events:
            latest = events[0]
            evt_desc = latest.get("description", "recent events")
            if len(evt_desc) > 80:
                evt_desc = evt_desc[:77] + "..."
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
            if action_result:
                action_result["action_type"] = "reaction"
                action_result["description"] = char_name + " reacted to: " + evt_desc
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "seek_resources":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "acquisition"
            action_result["description"] = (
                char_name + " sought out resources and supplies"
            )
    elif category == "self_improve":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "training"
            action_result["description"] = (
                char_name + " focused on self-improvement and training"
            )
    elif category == "confront_rival":
        rel = get_npc_relationships(char_id)
        if rel:
            worst_rival = min(rel.items(), key=lambda x: x[1])
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {
                    "char_id": worst_rival[0],
                    "name": worst_rival[0],
                    "id": worst_rival[0],
                },
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "help_ally":
        rel = get_npc_relationships(char_id)
        if rel:
            best_ally = max(rel.items(), key=lambda x: x[1])
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {"char_id": best_ally[0], "name": best_ally[0], "id": best_ally[0]},
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "explore":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "exploration"
            action_result["description"] = (
                char_name + " set out to explore uncharted territory"
            )

    decision = {
        "char_id": char_id,
        "char_name": char_name,
        "category": category,
        "description": char_name + " " + decision_desc,
        "reasoning": reasoning,
        "score": chosen["score"],
        "considered_options": len(options),
        "mood": mood or get_mood(char_id),
        "ts": int(time.time()),
    }
    if action_result and isinstance(action_result, dict):
        decision["action_taken"] = action_result.get("action_type", "none")
        decision["action_desc"] = action_result.get("description", "")

    r = _get_redis()
    key = f"npc_decisions:{char_id}"
    r.zadd(key, {json.dumps(decision): decision["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_DECISIONS + 1))
    r.expire(key, DECISION_TTL)

    return decision


def get_decision_log(char_id, limit=5):
    r = _get_redis()
    key = f"npc_decisions:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    decisions = []
    for item in raw:
        try:
            decisions.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return decisions


# --- PHASE 6C: NPC EVENT BROADCASTING ---

DECISION_EVENT_MAP = {
    "investigate": ("investigation_started", "public", 0.8),
    "socialize": ("social_gathering", "faction", 0.4),
    "advance_goal": ("goal_pursuit", "faction", 0.6),
    "confront_rival": ("conflict_erupted", "public", 0.9),
    "help_ally": ("alliance_formed", "faction", 0.5),
    "seek_resources": ("resource_acquisition", "public", 0.7),
    "self_improve": ("training_undertaken", "private", 0.2),
    "rest": ("rest_period", "private", 0.1),
    "explore": ("expedition_launched", "public", 0.8),
    "react_to_events": ("event_reaction", "faction", 0.5),
}

MAX_BROADCAST_EVENTS = 100
BROADCAST_TTL = 86400 * 7


def broadcast_decision_event(decision, affiliation="independent"):
    category = decision.get("category", "")
    if category not in DECISION_EVENT_MAP:
        return None
    event_type, visibility, significance = DECISION_EVENT_MAP[category]
    char_name = decision.get("char_name", "Unknown")
    char_id = decision.get("char_id", "")
    event = {
        "event_type": event_type,
        "source_char_id": char_id,
        "source_char_name": char_name,
        "source_affiliation": affiliation,
        "decision_category": category,
        "description": decision.get("action_desc")
        or decision.get("description", f"{char_name} performed {category}"),
        "visibility": visibility,
        "significance": significance,
        "faction": affiliation,
        "ts": int(time.time()),
    }
    r = _get_redis()
    key = "npc_broadcast_events"
    r.zadd(key, {json.dumps(event): event["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_BROADCAST_EVENTS + 1))
    r.expire(key, BROADCAST_TTL)
    return event


def get_broadcast_events(char_id=None, affiliation=None, limit=10):
    r = _get_redis()
    raw = r.zrevrange("npc_broadcast_events", 0, limit * 3 - 1)
    events = []
    for item in raw:
        try:
            evt = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if char_id and evt.get("source_char_id") == char_id:
            continue
        vis = evt.get("visibility", "public")
        if vis == "private":
            continue
        if vis == "faction" and affiliation:
            src_faction = evt.get("source_affiliation", "")
            if (
                src_faction
                and src_faction != affiliation
                and affiliation != "independent"
            ):
                continue
        events.append(evt)
        if len(events) >= limit:
            break
    return events


def get_relevant_events_for_npc(char_id, affiliation, limit=5):
    return get_broadcast_events(char_id=char_id, affiliation=affiliation, limit=limit)
