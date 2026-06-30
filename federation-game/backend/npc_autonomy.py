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
npc:needs - LIST of structured need records (councilor capability requests)
npc:needs:{npc_id}:last - STRING timestamp of last need filed (dedup throttle)
"""

import os
import json
import time
import random
import hashlib
import urllib.request
import urllib.error
import concurrent.futures
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import redis
from faction_dynamics import (
    compute_faction_dynamics,
    compute_faction_stances,
    store_faction_dynamics,
)
from institutions import get_npc_outcome_history
from npc_activity_logger import log_npc_activity
from npc_event_log import log_decision_event
from npc_world import (
    WORLD_CONDITIONS,
    WORLD_STATE_KEY,
    WORLD_STATE_HISTORY_KEY,
    MAX_WORLD_HISTORY,
    WORLD_STATE_TTL,
    get_world_state,
    get_world_condition,
    set_world_condition,
    update_world_state,
    get_world_state_history,
    _world_state_decision_modifier,
)
import logging
from npc_decree import (
    DECISION_EVENT_MAP,
    MAX_BROADCAST_EVENTS,
    BROADCAST_TTL,
    get_decision_log,
    broadcast_decision_event,
    get_broadcast_events,
    get_relevant_events_for_npc,
    DECREES_ALLOWED_NPCS,
    DECREES_ALLOWED_METRICS,
    DECREE_MAX_DELTA,
    DECREE_COOLDOWN_SECONDS,
    DECREE_HISTORY_KEY,
    DECREE_COOLDOWN_KEY,
    DECREE_MAX_HISTORY,
    DECREE_HISTORY_TTL,
    DIRECTIVE_KEY,
    DIRECTIVE_TTL,
    DECREE_DIRECTIVE_BIAS,
    COUNCILOR_AFFILIATIONS,
    FACTION_ALLIANCES,
    _is_allied_faction,
    _write_decree_directive,
    issue_decree,
    get_decree_history,
    DECREE_THRESHOLDS,
    COUNCILOR_NAMES,
    evaluate_decree_opportunity,
)
from npc_reflection import (
    LOW_VALUE_CATEGORIES,
    MOOD_DECISION_BIAS,
    ARCHETYPE_DECISION_BIAS,
    _reflect_on_missing_context,
    _score_decision_option,
    evaluate_decision_options,
)
from npc_thoughts import (
    SIGNIFICANCE_PRIORITY,
    LOW_SIGNIFICANCE_CUTOFF,
    MEDIUM_SIG_LLM_PROBABILITY,
    MAX_THOUGHTS,
    THOUGHT_TTL,
    THOUGHT_CACHE_TTL,
    THOUGHT_CACHE_PREFIX,
    _cache_stats,
    _cache_stats_lock,
    _compute_thought_cache_key,
    _get_world_events_bucket,
    get_thought_cache_stats,
    _clean_llm_output,
    _is_leaked_prompt,
    _call_llm,
    generate_thought,
    LLM_USE_NIM,
)
from npc_opinions import (
    OPINION_TTL,
    ARCHETYPE_MOODS,
    update_opinion,
    get_opinion,
    update_mood,
    get_mood,
)

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"

# NPCs with their own dedicated long-lived agent runtime should not also
# receive deterministic autonomy decisions here, or they end up with split
# ownership of cognition/state.
EXTERNAL_AGENT_NPCS = {
    cid.strip()
    for cid in os.environ.get("EXTERNAL_AGENT_NPCS", "char_001,char_306").split(",")
    if cid.strip()
}

OPINION_TTL = 86400 * 14
MAX_WORLD_EVENTS = 50

from npc_needs import (  # [2.1] extracted
    file_npc_need,
    get_open_needs,
    consume_system_notifications,
    ALLOWED_NEED_TYPES,
    FORBIDDEN_NEED_TYPES,
    NPC_NEEDS_KEY,
    NPC_NEEDS_MAX,
    NPC_NEEDS_THROTTLE_SECONDS,
)


# LLM priority: NVIDIA NIM (free, fast) -> OpenRouter (free, fallback)

# --- THOUGHT SYSTEM + LLM CALLS --- extracted to npc_thoughts.py [3] ---

_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    return _redis_client


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

# --- OPINIONS + MOODS --- extracted to npc_opinions.py [4] ---
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

# Sum of weights = 90. Socialize-like (alliance, collaboration, gossip, friendship, betrayal) = 8+8+6+8+5=35 (39%)
# Trade/conflict/negotiation = 15+15+10=40 (44%)
# Others (rivalry, mentorship, suspicion) = 15 (17%)

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


def _generate_dialogue(npc_a: Dict, npc_b: Dict, interaction_type: str) -> Optional[str]:
    """Generate a brief 2-3 line dialogue exchange between two NPCs using LLM.
    Returns None if LLM budget exhausted or call fails."""
    if not _check_tick_llm_budget():
        return None

    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")
    arch_a = npc_a.get("archetype", "neutral")
    arch_b = npc_b.get("archetype", "neutral")
    aff_a = npc_a.get("affiliation", "independent")
    aff_b = npc_b.get("affiliation", "independent")

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
        )
        if result and len(result) > 20:
            # Clean up any template artifacts or meta-text
            cleaned = result.strip()
            # Remove lines that don't look like dialogue
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
    # Weighted random choice for interaction type
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

    # Try LLM dialogue first (adds depth), fall back to template
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

    # Store dialogue in Redis for frontend display
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

    # Log interaction for BOTH NPCs (source + target)
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
        pass  # Logging is best-effort

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


# --- PARALLEL NPC PROCESSING (P25b-4) ---
# Max concurrent NPC processing threads. 16 provides better parallelism
# for ~39 NPCs (reduces batches from 5→3). Ollama lane gates actual
# concurrent LLM calls to OLLAMA_MAX_ACTIVE=2, so higher thread count
# just means more NPCs can wait/progress in parallel without blocking
# each other on non-LLM work (mood, decisions, Redis writes).
_NPC_PARALLEL_WORKERS = 16

# Per-tick LLM call budget: caps total LLM calls across all NPCs in one tick.
# With ~39 NPCs, ~7 of 10 categories attempt LLM, ~40-60% cache hits:
#   39 NPCs × 0.7 LLM-worthy × 0.5 cache-miss = ~14 LLM calls per tick.
# Budget of 20 gives headroom for cache misses while preventing runaway
# LLM spending if cache is cold (first tick after restart).
_TICK_LLM_BUDGET = 20
_tick_llm_calls = 0
_tick_llm_lock = threading.Lock()


def _check_tick_llm_budget() -> bool:
    """Check if the per-tick LLM budget has remaining capacity. Thread-safe."""
    global _tick_llm_calls
    with _tick_llm_lock:
        if _tick_llm_calls >= _TICK_LLM_BUDGET:
            return False
        _tick_llm_calls += 1
        return True


def _reset_tick_llm_budget() -> None:
    """Reset the per-tick LLM budget at the start of each simulation tick."""
    global _tick_llm_calls
    with _tick_llm_lock:
        _tick_llm_calls = 0


def _process_single_npc(npc: Dict) -> Dict[str, Any]:
    """Process a single NPC through the full autonomy pipeline.

    Extracted from simulation_tick() to enable parallel execution via
    ThreadPoolExecutor. Each call is independent — Redis writes use
    per-NPC keys, and _call_llm uses _run_async() internally which
    is thread-safe.
    """
    char_id = npc.get("char_id") or npc.get("id", "")
    char_name = npc.get("name", "Unknown")
    archetype = npc.get("archetype") or npc.get("personality_type", "scholar")
    affiliation = npc.get("affiliation", "independent")
    title = npc.get("title", "")
    description = npc.get("description", "")

    npc_result: Dict[str, Any] = {
        "thoughts": [],
        "actions": [],
        "moods": [],
        "opinions": [],
        "decisions": [],
        "errors": [],
    }

    if char_id in EXTERNAL_AGENT_NPCS:
        logger.debug("Skipping npc_autonomy ownership for external-agent NPC %s", char_id)
        return npc_result

    try:
        new_mood = update_mood(char_id, archetype)
        npc_result["moods"].append({"char_id": char_id, "mood": new_mood})
        decision = make_decision(
            char_id, char_name, archetype, affiliation, mood=new_mood
        )
        if decision:
            npc_result["decisions"].append(decision)
            try:
                broadcast_decision_event(decision, affiliation)
            except Exception:
                logger.debug("Decision broadcast failed for NPC decision event")
            log_npc_activity(char_id, "interaction", {
                "category": decision.get("category", ""),
                "description": decision.get("description", ""),
                "affiliation": affiliation,
            })
            # Significance gate: prioritize LLM calls for meaningful moments
            category = decision.get("category", "")
            sig = SIGNIFICANCE_PRIORITY.get(category, "medium")
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
                significance=sig,
                decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
            action = generate_action(
                char_id, char_name, archetype, affiliation, mood=new_mood
            )
            if action:
                npc_result["actions"].append(action)
        elif category in ("socialize", "help_ally", "confront_rival"):
            thought = generate_thought(
                char_id,
                char_name,
                archetype,
                affiliation,
                title,
                description,
                mood=new_mood,
                significance=sig,
                decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
        elif category == "rest":
            thought = generate_thought(
                char_id,
                char_name,
                archetype,
                affiliation,
                title,
                description,
                mood=new_mood,
                significance=sig,
                decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
        elif category == "react_to_events":
            action = generate_action(
                char_id, char_name, archetype, affiliation, mood=new_mood
            )
            if action:
                npc_result["actions"].append(action)
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
                    significance=sig,
                    decision_category=category,
                )
                if thought:
                    npc_result["thoughts"].append(thought)
        r = _get_redis()
        opinion_keys = list(r.scan_iter(f"npc_opinion:{char_id}:*"))
        for okey in opinion_keys[:2]:
            if random.random() < 0.3:
                player_id = okey.split(":")[-1]
                shift_type = random.choice(
                    ["friendly", "neutral", "neutral", "helpful"]
                )
                opinion = update_opinion(char_id, player_id, shift_type)
                npc_result["opinions"].append(
                    {"char_id": char_id, "player_id": player_id, "opinion": opinion}
                )
        r.set(f"npc_last_active:{char_id}", str(int(time.time())), ex=86400 * 7)
    except Exception as e:
        npc_result["errors"].append({"char_id": char_id, "error": str(e)})

    return npc_result


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

    # --- Reset per-tick LLM budget ---
    _reset_tick_llm_budget()

    # --- Parallel NPC processing (P25b-4) ---
    # Process all NPCs concurrently using ThreadPoolExecutor.
    # Each NPC is independent — Redis writes use per-NPC keys,
    # and _call_llm() uses _run_async() which is thread-safe.
    tick_start = time.time()
    npc_results: List[Dict[str, Any]] = []
    active_npc_list = [
        npc for npc in npc_list if (npc.get("char_id") or npc.get("id", "")) not in EXTERNAL_AGENT_NPCS
    ]

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=_NPC_PARALLEL_WORKERS
    ) as executor:
        future_to_npc = {
            executor.submit(_process_single_npc, npc): npc for npc in active_npc_list
        }
        for future in concurrent.futures.as_completed(future_to_npc):
            npc = future_to_npc[future]
            try:
                npc_result = future.result(timeout=45)
                npc_results.append(npc_result)
            except Exception as exc:
                char_id = npc.get("char_id") or npc.get("id", "unknown")
                logger.warning("NPC %s parallel processing failed: %s", char_id, exc)
                results["errors"].append(
                    {"char_id": char_id, "error": f"parallel processing failed: {exc}"}
                )

    # Merge per-NPC results into aggregate results
    for nr in npc_results:
        for key in ("thoughts", "actions", "moods", "opinions", "decisions", "errors"):
            if nr.get(key):
                results[key].extend(nr[key])

    parallel_elapsed = time.time() - tick_start
    cache_stats = get_thought_cache_stats()
    total_cache_ops = cache_stats["hits"] + cache_stats["misses"]
    hit_rate = (
        (cache_stats["hits"] / total_cache_ops * 100) if total_cache_ops > 0 else 0.0
    )
    with _tick_llm_lock:
        llm_used = _tick_llm_calls
    logger.info(
        "Parallel NPC processing: %d NPCs in %.1fs (%d workers) | LLM budget: %d/%d | thought cache: %d hits/%d misses (%.0f%% hit rate, %d stored)",
        len(active_npc_list),
        parallel_elapsed,
        _NPC_PARALLEL_WORKERS,
        llm_used,
        _TICK_LLM_BUDGET,
        cache_stats["hits"],
        cache_stats["misses"],
        hit_rate,
        cache_stats["stores"],
    )
    # Reset per-tick cache stats so next log line shows only that tick's data
    with _cache_stats_lock:
        _cache_stats["hits"] = 0
        _cache_stats["misses"] = 0
        _cache_stats["stores"] = 0

    if len(active_npc_list) >= 2:
        num_interactions = random.randint(1, min(3, len(active_npc_list) // 2))
        for _ in range(num_interactions):
            pair = random.sample(active_npc_list, 2)
            try:
                event = generate_npc_interaction(pair[0], pair[1])
                if event:
                    results["interactions"].append(event)
            except Exception as e:
                results["errors"].append({"error": f"interaction failed: {str(e)}"})
    # --- Faction dynamics only (NO world_state hash writes) ---
    # world_state writes are now handled exclusively by simulation_engine.py
    # which applies per-decision effects instead of this coarse aggregate formula.
    # The old update_world_state() was overwriting simulation_engine's nuanced
    # values with destructive aggregate calculations every tick (double-write conflict).
    # Faction dynamics computation is preserved here since it's valuable data.
    try:
        _fd_events = get_broadcast_events(limit=50)
        _fd = compute_faction_dynamics(
            npc_list, results.get("decisions", []), _fd_events
        )
        _fs = compute_faction_stances(_fd, _fd_events)
        store_faction_dynamics(_fd, _fs)
        results["faction_dynamics"] = {
            f: v["cohesion"] for f, v in _fd.items() if v.get("member_count", 0) > 0
        }
    except Exception as e:
        results["errors"].append({"error": f"faction dynamics failed: {str(e)}"})

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


# --- WORLD STATE SYSTEM — extracted to npc_world.py [2.2] ---


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
    "request_capability",
]


def _get_institution_context():
    try:
        _r = _get_redis()
        inst_ids = _r.smembers("institution:index")
        if not inst_ids:
            return {"institutions": [], "active_workflow_count": 0}
        institutions = []
        total_active = 0
        for iid in inst_ids:
            data = _r.hgetall(iid)
            name = data.get("name", "")
            kind = data.get("kind", "")
            status = data.get("status", "")
            active_count = int(_r.get(f"{iid}:active_workflows") or 0)
            total_active += active_count
            members = _r.smembers(f"{iid}:members") or set()
            institutions.append({
                "id": iid,
                "name": name,
                "kind": kind,
                "status": status,
                "active_workflows": active_count,
                "members": list(members),
            })
        return {"institutions": institutions, "active_workflow_count": total_active}
    except Exception:
        return {"institutions": [], "active_workflow_count": 0}


def _get_npc_outcome_ctx(npc_id):
    try:
        _r = _get_redis()
        return get_npc_outcome_history(_r, npc_id)
    except Exception:
        return {"approved": 0, "rejected": 0, "total": 0, "consecutive_rejections": 0, "recent_rejected_types": set(), "recent": []}



# --- REFLECTION + SCORING --- extracted to npc_reflection.py [2.4] ---
def make_decision(char_id, char_name, archetype, affiliation, mood=""):
    r = _get_redis()
    notifications = consume_system_notifications(r, char_id)
    notification_context = ""
    fulfilled_need_types = set()
    if notifications:
        parts = []
        for n in notifications:
            parts.append(
                f"[System Notice: Your request for {n.get('need_type','')} has been "
                f"{n.get('resolution','').replace('closed_','')}. {n.get('message','')}]"
            )
            if n.get("resolution", "").startswith("closed_fulfilled"):
                fulfilled_need_types.add(n.get("need_type", ""))
        notification_context = " ".join(parts)

    options, need_reflection = evaluate_decision_options(
        char_id, char_name, archetype, affiliation, mood,
        fulfilled_need_types=fulfilled_need_types,
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
        target_faction = None  # track the rival's faction
        if rel:
            worst_rival = min(rel.items(), key=lambda x: x[1])
            # Look up the rival's faction
            rival_id = worst_rival[0]
            try:
                r = _get_redis()
                rival_data = r.hget(f"npc:{rival_id}", "affiliation")
                if rival_data:
                    target_faction = (
                        rival_data
                        if isinstance(rival_data, str)
                        else rival_data.decode("utf-8", errors="ignore")
                    )
            except Exception:
                pass
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

    elif category == "request_capability":
        need_type = "information_access"
        need_desc = "Context gap limiting effective action"
        if need_reflection:
            need_type = need_reflection.get("need_type", "information_access")
            need_desc = need_reflection.get("description", need_desc)
        r = _get_redis()
        related_inst = ""
        try:
            related_inst = r.get(f"councilor:{char_id}:institution") or ""
        except Exception:
            pass
        _snap_decisions = []
        try:
            for _sd in r.lrange(f"npc_decisions:{char_id}", 0, 2):
                try:
                    _snap_decisions.append(json.loads(_sd))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass
        need_result = file_npc_need(
            r, char_id, char_name, need_type, "medium",
            need_desc, reasoning, "context_enrichment", related_inst,
            context_snapshot={
                "world_state": get_world_state(),
                "recent_decisions": _snap_decisions,
                "trigger": need_reflection or {},
            },
        )
        action_result = {
            "char_id": char_id,
            "char_name": char_name,
            "action_type": "request_capability",
            "description": f"{char_name} filed a capability need: {need_type}",
            "need_filed": need_result.get("ok", False),
            "need_id": need_result.get("need_id", ""),
            "mood": mood or "reflective",
            "ts": int(time.time()),
        }

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
    if notification_context:
        decision["system_notifications"] = notification_context
    # Attach target_faction for confront_rival decisions
    if category == "confront_rival":
        decision["target_faction"] = target_faction or affiliation or "unknown"
    if action_result and isinstance(action_result, dict):
        decision["action_taken"] = action_result.get("action_type", "none")
        decision["action_desc"] = action_result.get("description", "")

    r = _get_redis()
    key = f"npc_decisions:{char_id}"
    r.zadd(key, {json.dumps(decision): decision["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_DECISIONS + 1))
    r.expire(key, DECISION_TTL)

    log_npc_activity(char_id, "decision", {
        "category": category,
        "description": decision.get("description", ""),
        "reasoning": decision.get("reasoning", ""),
        "score": decision.get("score", 0),
        "options_considered": decision.get("considered_options", 0),
        "action_taken": decision.get("action_taken", "none"),
        "action_desc": decision.get("action_desc", ""),
    })

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

# --- PHASE 6C + COUNCILOR DECREES --- extracted to npc_decree.py [2.3] ---
