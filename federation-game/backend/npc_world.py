"""World state system — conditions, get/set/update/history, decision modifier.

Extracted from npc_autonomy.py [2.2] on 2026-06-30.
"""

import json
import logging
import os
import random
import threading
import time

import redis

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


# --- WORLD STATE CONSTANTS ---

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


# --- WORLD STATE FUNCTIONS ---


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
        )
    return WORLD_CONDITIONS[condition]["default"]


def set_world_condition(condition, value):
    if condition not in WORLD_CONDITIONS:
        return None
    config = WORLD_CONDITIONS[condition]
    value = max(config["min"], min(config["max"], value))
    r = _get_redis()
    r.hset(WORLD_STATE_KEY, condition, str(value))
    r.set("world_state_updated", str(int(time.time())), ex=WORLD_STATE_TTL)
    return value


def update_world_state(npc_list, tick_decisions):
    """DEPRECATED: No longer called from simulation_tick().
    world_state writes are now handled exclusively by simulation_engine.py
    which applies per-decision effects instead of coarse aggregate formulas.
    This function is retained for reference but should not be called.
    Faction dynamics are now computed directly in simulation_tick().
    """
    tick_result = {}
    try:
        from npc_autonomy import get_broadcast_events
        from faction_dynamics import (
            compute_faction_dynamics,
            compute_faction_stances,
            store_faction_dynamics,
        )

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

    _sim_last = r.get("sim_last_tick")
    if _sim_last:
        try:
            _elapsed = int(time.time()) - int(float(_sim_last))
            if _elapsed < 120:
                logger.info(
                    "update_world_state: skipping — sim_engine ran %ds ago",
                    _elapsed,
                )
                tick_result["world_state_write_skipped"] = True
                tick_result["world_state_skip_reason"] = (
                    f"sim_engine ran {_elapsed}s ago"
                )
                return tick_result
        except (ValueError, TypeError):
            pass

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
        + (explore_rate * 8)
        - (seek_rate * 6)
        - (num_npcs * 0.02)
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
    new_morale += advance_rate * 3

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
