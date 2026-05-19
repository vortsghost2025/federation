"""FEDERATION GAME - Event Cascade Engine

Feedback loop where NPC actions become world events that other NPCs react to,
producing cascading effects across the simulation.

Redis keys:
  cascade_reactions           - ZSET (score=timestamp) TTL 7 days
  cascade_last_processed      - STRING (timestamp)
  npc_decision_bias:{char_id} - STRING (JSON) TTL 5 min
  cascade_chains              - ZSET (score=timestamp) TTL 7 days
  faction_cascade_events      - ZSET (score=timestamp) TTL 7 days
  cascade_temperature         - STRING (float 0.0-1.0)
  cascade_summary             - STRING (JSON) TTL 1 min
"""

import os
import json
import time
import random
import math
import logging
from typing import Dict, List, Optional, Any

import redis
from npc_autonomy import get_broadcast_events, get_world_events
from npc_autonomy import update_npc_relationship, broadcast_decision_event

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis_client = None

CASCADE_REACTIONS_TTL = 86400 * 7
CASCADE_CHAINS_TTL = 86400 * 7
FACTION_CASCADE_TTL = 86400 * 7
DECISION_BIAS_TTL = 300
CASCADE_SUMMARY_TTL = 60
MAX_CASCADE_REACTIONS = 500
MAX_REACTIVE_NPCS = 5
CASCADE_BUDGET_SECONDS = 5

_CRITICAL_KEYWORDS = frozenset(
    {
        "conflict_erupted",
        "investigation_started",
        "expedition_launched",
        "attack",
        "death",
        "betrayal",
        "crisis",
    }
)
_MAJOR_KEYWORDS = frozenset(
    {
        "alliance_formed",
        "resource_acquisition",
        "goal_pursuit",
        "coup",
        "breakthrough",
        "defection",
        "raid",
    }
)
_MODERATE_KEYWORDS = frozenset(
    {
        "social_gathering",
        "event_reaction",
        "trade",
        "negotiation",
        "promotion",
        "assignment",
        "discovery",
    }
)
_MINOR_KEYWORDS = frozenset(
    {
        "training_undertaken",
        "rest_period",
        "routine",
        "patrol",
        "observation",
        "report",
    }
)
_TRIVIAL_KEYWORDS = frozenset(
    {
        "idle",
        "grooming",
        "chatter",
        "minor_task",
    }
)

_ARCHETYPE_REACT_BONUS = {
    "diplomat": 0.15,
    "soldier": 0.10,
    "scholar": 0.12,
    "explorer": 0.08,
    "leader": 0.20,
    "medic": 0.10,
    "engineer": 0.05,
    "spy": 0.18,
}

_ALLY_REACTIONS = [
    "celebration",
    "satisfaction",
    "support",
    "cooperation",
    "endorsement",
]
_RIVAL_REACTIONS = [
    "concern",
    "opposition",
    "defensive_posture",
    "counter_move",
    "protest",
]
_NEUTRAL_REACTIONS = [
    "curiosity",
    "observation",
    "cautious_interest",
    "indifference",
    "diplomatic",
]

_REL_DELTA_MAP = {
    "celebration": 3.0,
    "satisfaction": 2.0,
    "support": 4.0,
    "cooperation": 3.0,
    "endorsement": 2.0,
    "concern": -2.0,
    "opposition": -3.0,
    "defensive_posture": -1.0,
    "counter_move": -4.0,
    "protest": -3.0,
    "curiosity": 0.5,
    "observation": 0.0,
    "cautious_interest": 1.0,
    "indifference": 0.0,
    "diplomatic": 0.5,
}

_MOOD_DELTA_MAP = {
    "celebration": 0.15,
    "satisfaction": 0.10,
    "support": 0.10,
    "cooperation": 0.12,
    "endorsement": 0.08,
    "concern": -0.08,
    "opposition": -0.10,
    "defensive_posture": -0.05,
    "counter_move": -0.12,
    "protest": -0.10,
    "curiosity": 0.05,
    "observation": 0.0,
    "cautious_interest": 0.03,
    "indifference": 0.0,
    "diplomatic": 0.02,
}

_BIAS_MAP = {
    "celebration": {"socialize": 0.2, "help_ally": 0.3},
    "satisfaction": {"advance_goal": 0.2, "socialize": 0.1},
    "support": {"help_ally": 0.3, "socialize": 0.2},
    "cooperation": {"help_ally": 0.2, "advance_goal": 0.2},
    "endorsement": {"socialize": 0.2, "advance_goal": 0.1},
    "concern": {"investigate": 0.3, "confront_rival": 0.1},
    "opposition": {"confront_rival": 0.3, "investigate": 0.2},
    "defensive_posture": {"seek_resources": 0.2, "self_improve": 0.2},
    "counter_move": {"confront_rival": 0.3, "advance_goal": 0.2},
    "protest": {"confront_rival": 0.2, "socialize": 0.1},
    "curiosity": {"investigate": 0.3, "explore": 0.2},
    "observation": {"investigate": 0.1},
    "cautious_interest": {"investigate": 0.2, "seek_resources": 0.1},
    "indifference": {},
    "diplomatic": {"socialize": 0.2, "help_ally": 0.1},
}


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _get_faction_stance_value(faction: str, other_faction: str) -> float:
    r = _get_redis()
    key = f"faction_stances:{faction}"
    raw = r.hget(key, other_faction)
    if raw is None:
        return 0.5
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return float(parsed.get("value", 0.5))
        return float(parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.5


def _get_relationship(char_id: str, other_id: str) -> float:
    r = _get_redis()
    raw = r.hget(f"npc_relationships:{char_id}", other_id)
    if raw is None:
        return 50.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 50.0


def _store_cascade_event(event: Dict, target_key: str):
    r = _get_redis()
    score = event.get("ts", time.time())
    r.zadd(target_key, {json.dumps(event): score})
    r.expire(target_key, CASCADE_REACTIONS_TTL)


def _apply_mood_shift(char_id: str, delta: float):
    r = _get_redis()
    key = f"npc_mood:{char_id}"
    raw = r.get(key)
    try:
        mood = float(raw) if raw else 0.5
    except (TypeError, ValueError):
        mood = 0.5
    mood = max(0.0, min(1.0, mood + delta))
    r.set(key, str(mood))


def _apply_decision_bias(char_id: str, bias_type: str):
    r = _get_redis()
    key = f"npc_decision_bias:{char_id}"
    raw = r.get(key)
    try:
        bias = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        bias = {}
    deltas = _BIAS_MAP.get(bias_type, {})
    for category, weight in deltas.items():
        bias[category] = round(bias.get(category, 0.0) + weight, 3)
    r.set(key, json.dumps(bias), ex=DECISION_BIAS_TTL)


def _is_allied_faction(faction_a: str, faction_b: str) -> bool:
    stance = _get_faction_stance_value(faction_a, faction_b)
    return stance >= 0.65


def _is_rival_faction(faction_a: str, faction_b: str) -> bool:
    stance = _get_faction_stance_value(faction_a, faction_b)
    return stance <= 0.35


def classify_event_significance(event: Dict) -> str:
    """Classify an event's significance as critical/major/moderate/minor/trivial.

    Uses keyword matching on event_type and decision_category fields against
    frozensets of known keywords. Falls back to numeric significance field.
    """
    et = event.get("event_type", "").lower()
    dc = event.get("decision_category", "").lower()
    check_set = frozenset({et, dc})

    if check_set & _CRITICAL_KEYWORDS:
        return "critical"
    if check_set & _MAJOR_KEYWORDS:
        return "major"
    if check_set & _MODERATE_KEYWORDS:
        return "moderate"
    if check_set & _MINOR_KEYWORDS:
        return "minor"
    if check_set & _TRIVIAL_KEYWORDS:
        return "trivial"

    sig = event.get("significance", 0.0)
    try:
        sig = float(sig)
    except (TypeError, ValueError):
        return "minor"

    if sig >= 0.8:
        return "critical"
    if sig >= 0.6:
        return "major"
    if sig >= 0.4:
        return "moderate"
    if sig >= 0.2:
        return "minor"
    return "trivial"


def find_reactive_npcs(event: Dict, npc_list: List[Dict]) -> List[Dict]:
    """Determine which NPCs react to an event based on faction, relationship, archetype.

    Returns up to MAX_REACTIVE_NPCS NPCs sorted by reaction probability descending.
    Each NPC dict is augmented with a _react_prob field.
    """
    source_faction = event.get("faction") or event.get("source_affiliation", "")
    source_id = event.get("source_char_id", "")
    results = []

    for npc in npc_list:
        npc_id = npc.get("char_id", "")
        if npc_id == source_id:
            continue

        prob = random.uniform(0.05, 0.15)
        npc_faction = npc.get("affiliation", npc.get("faction", ""))

        if npc_faction and source_faction and npc_faction == source_faction:
            prob += 0.80
        elif npc_faction and source_faction:
            if _is_allied_faction(npc_faction, source_faction):
                prob += 0.50
            elif _is_rival_faction(npc_faction, source_faction):
                prob += 0.60

        rel = _get_relationship(npc_id, source_id) if source_id else 50.0
        if rel > 70:
            prob += 0.70
        elif rel < 30:
            prob += 0.40

        archetype = npc.get("archetype", npc.get("role", ""))
        if archetype in _ARCHETYPE_REACT_BONUS:
            prob += _ARCHETYPE_REACT_BONUS[archetype]

        prob = min(1.0, prob)
        if random.random() < prob:
            npc_copy = dict(npc)
            npc_copy["_react_prob"] = prob
            results.append(npc_copy)

    results.sort(key=lambda n: n.get("_react_prob", 0.0), reverse=True)
    return results[:MAX_REACTIVE_NPCS]


def generate_reaction(event: Dict, reacting_npc: Dict) -> Optional[Dict]:
    """Generate a specific reaction from an NPC to an event.

    Produces: new cascade_reaction event, relationship delta, mood shift,
    and decision bias stored in npc_decision_bias:{char_id} (TTL 5 min).
    """
    source_id = event.get("source_char_id", "")
    source_name = event.get("source_char_name", "Unknown")
    npc_id = reacting_npc.get("char_id", "")
    npc_name = reacting_npc.get("char_name", reacting_npc.get("name", "Unknown"))
    npc_faction = reacting_npc.get("affiliation", reacting_npc.get("faction", ""))
    source_faction = event.get("faction") or event.get("source_affiliation", "")

    rel = _get_relationship(npc_id, source_id) if source_id else 50.0

    if rel > 65:
        pool = _ALLY_REACTIONS
    elif rel < 35:
        pool = _RIVAL_REACTIONS
    else:
        pool = _NEUTRAL_REACTIONS

    if npc_faction and source_faction and npc_faction != source_faction:
        if _is_rival_faction(npc_faction, source_faction) and rel >= 35:
            pool = _RIVAL_REACTIONS
        elif _is_allied_faction(npc_faction, source_faction) and rel <= 65:
            pool = _ALLY_REACTIONS

    reaction_type = random.choice(pool)
    rel_delta = _REL_DELTA_MAP.get(reaction_type, 0.0)
    mood_delta = _MOOD_DELTA_MAP.get(reaction_type, 0.0)

    now = time.time()
    reaction_event = {
        "event_type": "cascade_reaction",
        "reaction_to": event.get("event_type", "unknown"),
        "reaction_type": reaction_type,
        "source_char_id": npc_id,
        "source_char_name": npc_name,
        "source_affiliation": npc_faction,
        "target_char_id": source_id,
        "target_char_name": source_name,
        "faction": npc_faction,
        "description": (
            f"{npc_name} reacted with {reaction_type} to "
            f"{source_name}'s {event.get('event_type', 'event')}"
        ),
        "significance": min(0.9, event.get("significance", 0.5) * 0.7),
        "cascade_depth": event.get("cascade_depth", 0) + 1,
        "ts": now,
    }

    _store_cascade_event(reaction_event, "cascade_reactions")

    r = _get_redis()
    world_event = dict(reaction_event)
    r.zadd("npc_world_events", {json.dumps(world_event): now})
    r.zremrangebyrank("npc_world_events", 0, -(51))

    if source_id and rel_delta != 0.0:
        try:
            update_npc_relationship(npc_id, source_id, source_name, delta=rel_delta)
        except Exception as exc:
            logger.warning(
                "Failed to update relationship %s->%s: %s", npc_id, source_id, exc
            )

    _apply_mood_shift(npc_id, mood_delta)
    _apply_decision_bias(npc_id, reaction_type)

    return reaction_event


def process_cascade(npc_list: List[Dict], max_depth: int = 2) -> Dict:
    """Main cascade processor. Reads new events since last processed, finds
    reactive NPCs for events above 'minor' significance, generates reactions,
    and recurses on major/critical reactions up to max_depth.

    Enforces: max 50 total reactions, 5-second budget.
    """
    r = _get_redis()
    start = time.time()
    deadline = start + CASCADE_BUDGET_SECONDS

    last_ts_raw = r.get("cascade_last_processed")
    last_ts = float(last_ts_raw) if last_ts_raw else 0.0

    raw_events = r.zrangebyscore("npc_broadcast_events", last_ts, "+inf")
    new_events = []
    for item in raw_events:
        try:
            evt = json.loads(item)
            new_events.append(evt)
        except (json.JSONDecodeError, TypeError):
            continue

    raw_world = r.zrangebyscore("npc_world_events", last_ts, "+inf")
    for item in raw_world:
        try:
            evt = json.loads(item)
            if evt.get("event_type") != "cascade_reaction":
                new_events.append(evt)
        except (json.JSONDecodeError, TypeError):
            continue

    stats = {
        "events_processed": 0,
        "reactions_generated": 0,
        "chains": [],
        "most_reactive": {},
    }

    reaction_count = [0]

    def _cascade_recurse(evt: Dict, depth: int, chain: List[str]):
        if depth > max_depth:
            return
        if reaction_count[0] >= MAX_CASCADE_REACTIONS:
            return
        if time.time() > deadline:
            return

        sig = classify_event_significance(evt)
        if sig in ("trivial", "minor"):
            return

        reactives = find_reactive_npcs(evt, npc_list)
        for npc in reactives:
            if reaction_count[0] >= MAX_CASCADE_REACTIONS:
                return
            if time.time() > deadline:
                return
            try:
                reaction = generate_reaction(evt, npc)
            except Exception as exc:
                logger.warning("Cascade reaction failed: %s", exc)
                continue
            if reaction is None:
                continue

            reaction_count[0] += 1
            stats["reactions_generated"] += 1
            npc_id = npc.get("char_id", "unknown")
            stats["most_reactive"][npc_id] = stats["most_reactive"].get(npc_id, 0) + 1
            chain.append(reaction.get("reaction_type", "unknown"))

            if sig in ("critical", "major") and depth < max_depth:
                _cascade_recurse(reaction, depth + 1, chain)

    for evt in new_events:
        chain = []
        _cascade_recurse(evt, 0, chain)
        if chain:
            stats["chains"].append(chain)
            chain_record = {
                "source_event": evt.get("event_type", "unknown"),
                "source_char": evt.get("source_char_name", "unknown"),
                "chain": chain,
                "ts": time.time(),
            }
            _store_cascade_event(chain_record, "cascade_chains")
        stats["events_processed"] += 1

    now_ts = time.time()
    r.set("cascade_last_processed", str(now_ts))

    prev_temp = float(r.get("cascade_temperature") or 0.0)
    # Temperature tracks cascade intensity on a 0-1 scale.
    # Use a sigmoid-based formula: moderate reactions → ~0.4-0.6,
    # extreme spikes → approaches 1.0, quiet periods → approaches 0.
    # This avoids the problem where a fixed cap always produces ratio=1.0.
    reaction_count = stats["reactions_generated"]
    # Sigmoid midpoint at 300 reactions; steepness 0.008 for gradual rise
    # Typical tick produces 200-500 reactions, so midpoint=300 means
    # ~300 reactions => heat=0.5, 500 reactions => heat~0.8, 100 => heat~0.2
    SIGMOID_MIDPOINT = 300.0
    SIGMOID_STEEPNESS = 0.008
    new_heat = 1.0 / (
        1.0 + math.exp(-SIGMOID_STEEPNESS * (reaction_count - SIGMOID_MIDPOINT))
    )
    DAMPING_FACTOR = 0.6
    HEAT_GAIN = 0.4
    temperature = max(0.0, min(1.0, prev_temp * DAMPING_FACTOR + new_heat * HEAT_GAIN))
    r.set("cascade_temperature", str(round(temperature, 3)))

    r.delete("cascade_summary")
    summary = get_cascade_summary()
    r.set("cascade_summary", json.dumps(summary), ex=CASCADE_SUMMARY_TTL)

    logger.info(
        "Cascade processed %d events, %d reactions, %.2f temperature",
        stats["events_processed"],
        stats["reactions_generated"],
        temperature,
    )
    return stats


def process_faction_cascade(faction_actions: List[Dict], npc_list: List[Dict]) -> Dict:
    """Faction-level cascade with wider reach. All allied/rival faction members
    may react. Results stored in faction_cascade_events ZSET.
    """
    r = _get_redis()
    stats = {"actions_processed": 0, "reactions": 0, "faction_events": []}

    for action in faction_actions:
        faction_id = action.get("faction_id", action.get("faction", ""))
        if not faction_id:
            continue

        for npc in npc_list:
            npc_faction = npc.get("affiliation", npc.get("faction", ""))
            if not npc_faction:
                continue

            stance = _get_faction_stance_value(npc_faction, faction_id)
            if 0.35 <= stance <= 0.65:
                continue

            prob = 0.6 if stance < 0.35 else 0.5
            if random.random() > prob:
                continue

            npc_id = npc.get("char_id", "")
            if npc_id == action.get("source_char_id", ""):
                continue

            try:
                reaction = generate_reaction(action, npc)
            except Exception as exc:
                logger.warning("Faction cascade reaction failed: %s", exc)
                continue
            if reaction is None:
                continue

            faction_event = dict(reaction)
            faction_event["faction_cascade"] = True
            faction_event["triggering_faction"] = faction_id
            score = faction_event.get("ts", time.time())
            r.zadd(
                "faction_cascade_events",
                {json.dumps(faction_event): score},
            )
            r.expire("faction_cascade_events", FACTION_CASCADE_TTL)

            stats["reactions"] += 1
            stats["faction_events"].append(faction_event)

        stats["actions_processed"] += 1

    r.expire("faction_cascade_events", FACTION_CASCADE_TTL)
    logger.info(
        "Faction cascade: %d actions, %d reactions",
        stats["actions_processed"],
        stats["reactions"],
    )
    return stats


def get_cascade_summary() -> Dict:
    """Return cascade statistics: total events, chains, most reactive NPCs,
    faction cascade activity, and temperature (0.0-1.0).
    """
    r = _get_redis()

    cached = r.get("cascade_summary")
    if cached:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            pass

    total_reactions = r.zcard("cascade_reactions")
    total_chains = r.zcard("cascade_chains")
    faction_events = r.zcard("faction_cascade_events")

    most_reactive = {}
    raw = r.zrevrange("cascade_reactions", 0, 49)
    for item in raw:
        try:
            evt = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        cid = evt.get("source_char_id", "")
        if cid:
            most_reactive[cid] = most_reactive.get(cid, 0) + 1

    top_reactive = sorted(most_reactive.items(), key=lambda x: x[1], reverse=True)[:5]

    temp_raw = r.get("cascade_temperature")
    try:
        temperature = float(temp_raw) if temp_raw else 0.0
    except (TypeError, ValueError):
        temperature = 0.0
    temperature = max(0.0, min(1.0, temperature))

    summary = {
        "total_cascade_reactions": total_reactions,
        "total_chains": total_chains,
        "faction_cascade_events": faction_events,
        "most_reactive_npcs": [
            {"char_id": cid, "reaction_count": cnt} for cid, cnt in top_reactive
        ],
        "cascade_temperature": round(temperature, 3),
    }
    return summary
