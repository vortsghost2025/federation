"""Decree and broadcast system -- councilor decrees, event broadcasting, directives.

Extracted from npc_autonomy.py [2.3] on 2026-06-30.
"""

import json
import logging
import os
import threading
import time

import redis

from npc_world import (
    WORLD_CONDITIONS,
    WORLD_STATE_KEY,
    WORLD_STATE_TTL,
    get_world_condition,
    get_world_state,
    set_world_condition,
)

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
    return _redis_client


# --- DECISION EVENT BROADCASTING ---

DECISION_EVENT_MAP = {
    "investigate": ("investigation_started", "public", 0.7),
    "socialize": ("social_gathering", "public", 0.5),
    "advance_goal": ("goal_pursuit", "public", 0.6),
    "confront_rival": ("conflict_erupted", "public", 0.9),
    "help_ally": ("alliance_formed", "public", 0.6),
    "seek_resources": ("resource_acquisition", "public", 0.6),
    "self_improve": ("training_undertaken", "faction", 0.4),
    "rest": ("rest_period", "private", 0.1),
    "explore": ("expedition_launched", "public", 0.8),
    "react_to_events": ("event_reaction", "public", 0.5),
    "negotiate": ("negotiation_initiated", "public", 0.7),
    "trade": ("trade_conducted", "public", 0.5),
    "patrol": ("patrol_dispatched", "faction", 0.6),
    "research": ("research_breakthrough", "public", 0.8),
    "diplomacy": ("diplomatic_mission", "public", 0.7),
    "sabotage": ("sabotage_detected", "public", 0.9),
}

MAX_BROADCAST_EVENTS = 100
BROADCAST_TTL = 86400 * 7


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
        "description": (decision.get("action_desc")
                        or decision.get("description", f"{char_name} performed {category}")),
        "visibility": visibility,
        "significance": significance,
        "faction": affiliation,
        "target_faction": decision.get("target_faction", ""),
        "ts": int(time.time()),
    }
    r = _get_redis()
    key = "npc_broadcast_events"
    r.zadd(key, {json.dumps(event): event["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_BROADCAST_EVENTS + 1))
    r.expire(key, BROADCAST_TTL)
    from npc_event_log import log_from_broadcast_event
    log_from_broadcast_event(event, tick_id=int(time.time()))
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
            if (src_faction and src_faction != affiliation
                    and affiliation != "independent"):
                continue
        events.append(evt)
        if len(events) >= limit:
            break
    return events


def get_relevant_events_for_npc(char_id, affiliation, limit=5):
    return get_broadcast_events(char_id=char_id, affiliation=affiliation, limit=limit)


# --- COUNCILOR DECREES ---

DECREES_ALLOWED_NPCS = [
    x.strip()
    for x in os.environ.get("EXTERNAL_AGENT_NPCS", "char_001,char_306").split(",")
    if x.strip()
]

DECREES_ALLOWED_METRICS = [
    "stability", "morale", "resource_abundance",
    "tension_level", "threat_level", "anomaly_activity",
]

DECREE_MAX_DELTA = 5
DECREE_COOLDOWN_SECONDS = 3600
DECREE_HISTORY_KEY = "councilor:decrees:history"
DECREE_COOLDOWN_KEY = "councilor:decrees:cooldown:{char_id}"
DECREE_MAX_HISTORY = 200
DECREE_HISTORY_TTL = 86400 * 30

DIRECTIVE_KEY = "councilor:directive:active"
DIRECTIVE_TTL = 600

DECREE_DIRECTIVE_BIAS = {
    "stability": {
        "same_faction": {"help_ally": 1.35, "advance_goal": 1.25,
                         "socialize": 1.15, "confront_rival": 0.65, "rest": 0.75},
        "allied_faction": {"help_ally": 1.2, "socialize": 1.1, "confront_rival": 0.8},
        "other_faction": {"confront_rival": 0.9},
    },
    "morale": {
        "same_faction": {"socialize": 1.4, "help_ally": 1.25, "advance_goal": 1.1,
                         "rest": 0.65, "self_improve": 0.85},
        "allied_faction": {"socialize": 1.2, "help_ally": 1.15, "rest": 0.8},
        "other_faction": {},
    },
    "resource_abundance": {
        "same_faction": {"seek_resources": 1.45, "advance_goal": 1.15,
                         "rest": 0.7, "socialize": 0.85},
        "allied_faction": {"seek_resources": 1.25, "advance_goal": 1.1},
        "other_faction": {"seek_resources": 1.1},
    },
    "tension_level": {
        "same_faction": {"socialize": 1.4, "help_ally": 1.25,
                         "confront_rival": 0.55, "investigate": 0.85},
        "allied_faction": {"socialize": 1.2, "confront_rival": 0.7},
        "other_faction": {"investigate": 1.15, "confront_rival": 1.1},
    },
    "threat_level": {
        "same_faction": {"self_improve": 1.35, "help_ally": 1.25,
                         "seek_resources": 1.15, "explore": 0.6, "socialize": 0.85},
        "allied_faction": {"self_improve": 1.2, "help_ally": 1.15},
        "other_faction": {"investigate": 1.15},
    },
    "anomaly_activity": {
        "same_faction": {"investigate": 1.4, "explore": 1.25,
                         "rest": 0.75, "seek_resources": 0.85},
        "allied_faction": {"investigate": 1.2, "explore": 1.15, "rest": 0.85},
        "other_faction": {"investigate": 1.1},
    },
}

COUNCILOR_AFFILIATIONS = {
    "char_001": "research_division",
    "char_306": "none",
}

FACTION_ALLIANCES = {
    "research_division": ["exploration_initiative"],
    "exploration_initiative": ["research_division"],
    "military_command": ["preservation_society"],
    "preservation_society": ["military_command"],
    "diplomatic_corps": ["cultural_ministry", "economic_council"],
    "cultural_ministry": ["diplomatic_corps", "consciousness_collective"],
    "economic_council": ["diplomatic_corps"],
    "consciousness_collective": ["cultural_ministry"],
}

DECREE_THRESHOLDS = {
    "stability": {"low": 50, "high": 85, "low_delta": 5, "high_delta": -2},
    "morale": {"low": 40, "high": 80, "low_delta": 4, "high_delta": -2},
    "resource_abundance": {"low": 35, "high": 90, "low_delta": 5, "high_delta": -2},
    "tension_level": {"low": 15, "high": 65, "low_delta": -2, "high_delta": -4},
    "threat_level": {"low": 10, "high": 60, "low_delta": -1, "high_delta": -4},
    "anomaly_activity": {"low": 5, "high": 70, "low_delta": -1, "high_delta": -3},
}

COUNCILOR_NAMES = {"char_001": "Archimedes Prime", "char_306": "The Oracle"}


def _is_allied_faction(npc_faction, issuer_faction):
    if not npc_faction or not issuer_faction:
        return False
    return npc_faction in FACTION_ALLIANCES.get(issuer_faction, [])


def _write_decree_directive(r, char_id, metric):
    issuer_faction = COUNCILOR_AFFILIATIONS.get(char_id, "")
    directive_data = json.dumps({
        "metric": metric,
        "issuer": char_id,
        "issuer_faction": issuer_faction,
        "ts": int(time.time()),
    })
    r.set(DIRECTIVE_KEY, directive_data, ex=DIRECTIVE_TTL)


def issue_decree(char_id, char_name, metric, delta, reasoning=""):
    if char_id not in DECREES_ALLOWED_NPCS:
        return {"ok": False, "error": f"{char_id} is not authorized to issue decrees"}
    if metric not in DECREES_ALLOWED_METRICS:
        return {"ok": False, "error": f"metric '{metric}' is not decreable"}
    if delta == 0:
        return {"ok": False, "error": "delta must be non-zero"}
    if abs(delta) > DECREE_MAX_DELTA:
        return {"ok": False, "error": f"delta {delta} exceeds max +/-{DECREE_MAX_DELTA}"}
    if metric not in WORLD_CONDITIONS:
        return {"ok": False, "error": f"unknown metric: {metric}"}
    r = _get_redis()
    cooldown_key = DECREE_COOLDOWN_KEY.format(char_id=char_id)
    ttl = r.ttl(cooldown_key)
    if ttl and ttl > 0:
        return {"ok": False, "error": f"cooldown active for {ttl}s",
                "cooldown_remaining": ttl}
    current = get_world_condition(metric)
    if current is None:
        return {"ok": False, "error": f"could not read current value for {metric}"}
    config = WORLD_CONDITIONS[metric]
    new_val = max(config["min"], min(config["max"], current + delta))
    actual_delta = new_val - current
    if actual_delta == 0:
        return {"ok": False, "error": "change would have no effect (value clamped)"}
    r.hset(WORLD_STATE_KEY, metric, str(int(round(new_val))))
    r.set("world_state_updated", str(int(time.time())), ex=WORLD_STATE_TTL)
    r.setex(cooldown_key, DECREE_COOLDOWN_SECONDS, "1")
    _write_decree_directive(r, char_id, metric)
    decree_record = {
        "decree_id": f"dcr_{char_id}_{int(time.time())}",
        "char_id": char_id,
        "char_name": char_name,
        "metric": metric,
        "previous_value": current,
        "new_value": int(round(new_val)),
        "delta": actual_delta,
        "reasoning": reasoning,
        "ts": int(time.time()),
    }
    r.zadd(DECREE_HISTORY_KEY, {json.dumps(decree_record): decree_record["ts"]})
    r.zremrangebyrank(DECREE_HISTORY_KEY, 0, -(DECREE_MAX_HISTORY + 1))
    r.expire(DECREE_HISTORY_KEY, DECREE_HISTORY_TTL)
    event_desc = (f"{char_name} issued a decree: {metric} {current}"
                  f"\u2192{int(round(new_val))}"
                  f" ({'+' if actual_delta > 0 else ''}{actual_delta})")
    if reasoning:
        event_desc += f" -- {reasoning[:120]}"
    try:
        from federation_game_events import add_event
        add_event("decree_issued", event_desc, significance=0.9)
    except Exception:
        pass
    return {"ok": True, "decree": decree_record}


def get_decree_history(char_id=None, limit=20):
    r = _get_redis()
    raw = r.zrevrange(DECREE_HISTORY_KEY, 0, limit * 2 - 1)
    decrees = []
    for item in raw:
        try:
            rec = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if char_id and rec.get("char_id") != char_id:
            continue
        decrees.append(rec)
        if len(decrees) >= limit:
            break
    return decrees


def evaluate_decree_opportunity(r=None):
    ws = get_world_state()
    if not ws:
        return None
    for char_id in DECREES_ALLOWED_NPCS:
        cooldown_key = DECREE_COOLDOWN_KEY.format(char_id=char_id)
        check_r = r or _get_redis()
        if check_r.ttl(cooldown_key) and check_r.ttl(cooldown_key) > 0:
            continue
        char_name = COUNCILOR_NAMES.get(char_id, char_id)
        for metric, cfg in DECREE_THRESHOLDS.items():
            val = ws.get(metric)
            if val is None:
                continue
            val = float(val)
            if val <= cfg["low"]:
                result = issue_decree(char_id, char_name, metric, cfg["low_delta"],
                                      f"{metric} critically low at {val:.0f}")
                if result.get("ok"):
                    return result.get("decree")
                break
            if val >= cfg["high"]:
                result = issue_decree(char_id, char_name, metric, cfg["high_delta"],
                                      f"{metric} critically high at {val:.0f}")
                if result.get("ok"):
                    return result.get("decree")
                break
    return None
