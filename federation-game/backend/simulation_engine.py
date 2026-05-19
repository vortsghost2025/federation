#!/usr/bin/env python3
"""
FEDERATION GAME — Autonomous Simulation Engine

The cross-pollination layer that wires NPC decisions → world effects,
faction context → NPC decisions, world state → game_state_v2.

This is the AUTONOMOUS SIMULATION CORE — the single most important module
that bridges 4 independent subsystems (NPC autonomy, faction dynamics,
political engine, history arc) so they cross-pollinate.
"""

import hashlib
import json
import logging
import os
import random
import time
from typing import Dict, List, Optional, Tuple

import redis

from faction_dynamics import get_faction_context_for_npc
from npc_autonomy import _get_redis as _get_npc_redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


WORLD_CONDITIONS = [
    "tension_level",
    "resource_abundance",
    "threat_level",
    "stability",
    "morale",
    "anomaly_activity",
]

WORLD_DEFAULTS = {
    "tension_level": 50,
    "resource_abundance": 60,
    "threat_level": 30,
    "stability": 65,
    "morale": 55,
    "anomaly_activity": 20,
}

VALID_CATEGORIES = {
    "seek_resources",
    "confront_rival",
    "investigate",
    "help_ally",
    "advance_goal",
    "socialize",
    "react_to_events",
    "explore",
    "rest",
    "self_improve",
}

SIM_EFFECTS_TTL = 7 * 86400
FACTION_METRIC_TTL = 86400
NPC_FACTION_CONTEXT_TTL = 300
TICK_LOG_TTL = 30 * 86400
LAST_TICK_TTL = 86400

CROSS_POLLINATION_SCALE = 0.3
GAME_STATE_DELTA_SCALE = 10

# Natural decay: exponential rubber-band model.
# Base rate closes a % of the gap per tick, but an ACCELERATION factor
# makes the pull stronger the further the value is from default.
# This prevents 39 NPCs from runaway-pushing values to 0 or 100.
WORLD_DECAY_RATE = {
    "tension_level": 0.15,
    "resource_abundance": 0.08,
    "threat_level": 0.12,
    "stability": 0.05,
    "morale": 0.10,
    "anomaly_activity": 0.20,
}
DECAY_ACCELERATION = 3.0  # exponent for distance-from-default scaling


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _apply_natural_decay(world: Dict[str, float]) -> Dict[str, float]:
    """Mean-revert each world state toward its default.
    Uses exponential rubber-band: pull strength grows with distance.
    A value at 100 with default 30 gets pulled MUCH harder than one at 60.
    Called once per autonomous tick, BEFORE NPC effects are applied."""
    for key in WORLD_CONDITIONS:
        default = WORLD_DEFAULTS[key]
        rate = WORLD_DECAY_RATE.get(key, 0.03)
        delta = default - world[key]
        # Normalized distance: 0.0 = at default, 1.0 = at extreme (0 or 100)
        distance = abs(delta) / 100.0
        # Accelerated rate: grows exponentially with distance
        effective_rate = rate * (1.0 + (distance**DECAY_ACCELERATION) * 10.0)
        world[key] = _clamp(world[key] + delta * effective_rate)
    return world


def _seeded_random(char_id: str, salt: str = "") -> random.Random:
    seed_str = f"{char_id}:{salt}:{time.time():.0f}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed_int)


def _read_world_state(r: redis.Redis) -> Dict[str, float]:
    raw = r.hgetall("world_state")
    state = {}
    for key in WORLD_CONDITIONS:
        try:
            state[key] = float(raw.get(key, WORLD_DEFAULTS[key]))
        except (ValueError, TypeError):
            state[key] = float(WORLD_DEFAULTS[key])
    return state


def _write_world_state(r: redis.Redis, state: Dict[str, float]) -> None:
    pipe = r.pipeline()
    for key, value in state.items():
        # Store as int string for compatibility with npc_autonomy readers
        # which use int(val) and int(float(val)) — decimals cause ValueError
        pipe.hset("world_state", key, str(int(round(value))))
    pipe.set("world_state_updated", str(int(time.time())), ex=86400 * 30)
    pipe.execute()


def _store_effect(r: redis.Redis, effect: Dict, ts: float) -> None:
    key = f"sim_effects:{int(ts)}"
    r.zadd(key, {json.dumps(effect): ts})
    r.expire(key, SIM_EFFECTS_TTL)


def execute_npc_decisions(tick_decisions: List[Dict]) -> Dict:
    """
    Read NPC decisions from the current tick and EXECUTE concrete effects.

    Not just statistical drift — SPECIFIC outcomes per decision category:
    - seek_resources: reduce world resource_abundance, increase faction power
    - confront_rival: reduce target faction stability, increase world tension
    - investigate: increase anomaly_activity, chance of breakthrough event
    - help_ally: increase ally faction cohesion, increase world morale
    - advance_goal: fire world event when goal progress reaches 100%
    - socialize: chance to improve relationship, store interaction event
    - react_to_events: increase threat_level, consume broadcast events
    - explore: increase resource_abundance, chance of discovery event
    - rest: small morale increase
    - self_improve: increase faction power, small tech boost

    Returns:
    Dict with keys: effects_applied, world_state_changes,
    faction_updates, events_generated, errors
    """
    r = _get_redis()
    ts = time.time()
    results = {
        "effects_applied": 0,
        "world_state_changes": {},
        "faction_updates": {},
        "events_generated": [],
        "errors": [],
    }

    if not tick_decisions:
        return results

    world = _read_world_state(r)
    _apply_natural_decay(world)

    faction_power_delta: Dict[str, float] = {}
    faction_stability_delta: Dict[str, float] = {}
    faction_cohesion_delta: Dict[str, float] = {}

    for decision in tick_decisions:
        try:
            char_id = decision.get("char_id", "unknown")
            category = decision.get("category", "")
            affiliation = decision.get(
                "affiliation", decision.get("faction", "independent")
            )
            char_name = decision.get("char_name", "Unknown")

            if category not in VALID_CATEGORIES:
                continue

            rng = _seeded_random(char_id, category)

            effect = {
                "char_id": char_id,
                "char_name": char_name,
                "category": category,
                "affiliation": affiliation,
                "tick_ts": ts,
                "changes": {},
            }

            if category == "seek_resources":
                resource_drain = rng.uniform(0.1, 0.4)
                power_gain = rng.uniform(0.2, 1.0)
                anomaly_relief = rng.uniform(0.02, 0.08)
                world["resource_abundance"] = _clamp(
                    world["resource_abundance"] - resource_drain
                )
                world["anomaly_activity"] = _clamp(
                    world["anomaly_activity"] - anomaly_relief
                )
                faction_power_delta[affiliation] = (
                    faction_power_delta.get(affiliation, 0) + power_gain
                )
                effect["changes"] = {
                    "resource_abundance": -resource_drain,
                    "anomaly_activity": -anomaly_relief,
                    f"faction_power:{affiliation}": power_gain,
                }

            elif category == "confront_rival":
                tension_rise = rng.uniform(0.1, 0.4)
                stability_hit = rng.uniform(0.2, 0.6)
                morale_hit = rng.uniform(0.06, 0.24)
                target_faction = decision.get("target_faction", "unknown")
                world["tension_level"] = _clamp(world["tension_level"] + tension_rise)
                world["morale"] = _clamp(world["morale"] - morale_hit)
                if target_faction and target_faction != "independent":
                    faction_stability_delta[target_faction] = (
                        faction_stability_delta.get(target_faction, 0) - stability_hit
                    )
                effect["changes"] = {
                    "tension_level": tension_rise,
                    "morale": -morale_hit,
                    f"faction_stability:{target_faction}": -stability_hit,
                }

            elif category == "investigate":
                anomaly_rise = rng.uniform(0.1, 0.3)
                world["anomaly_activity"] = _clamp(
                    world["anomaly_activity"] + anomaly_rise
                )
                effect["changes"] = {"anomaly_activity": anomaly_rise}
                if rng.random() < 0.15:
                    breakthrough_event = {
                        "event_type": "investigation_breakthrough",
                        "source_char_id": char_id,
                        "source_char_name": char_name,
                        "source_affiliation": affiliation,
                        "decision_category": "investigate",
                        "description": f"{char_name} made a research breakthrough",
                        "visibility": "public",
                        "significance": 0.9,
                        "faction": affiliation,
                        "ts": int(ts),
                    }
                    r.zadd(
                        "npc_world_events",
                        {json.dumps(breakthrough_event): ts},
                    )
                    results["events_generated"].append(breakthrough_event)
                    effect["changes"]["breakthrough"] = True

            elif category == "help_ally":
                cohesion_gain = rng.uniform(0.2, 0.6)
                morale_gain = rng.uniform(0.06, 0.2)
                tension_relief = rng.uniform(0.04, 0.16)
                ally_faction = decision.get("target_faction", affiliation)
                world["morale"] = _clamp(world["morale"] + morale_gain)
                world["tension_level"] = _clamp(world["tension_level"] - tension_relief)
                if ally_faction and ally_faction != "independent":
                    faction_cohesion_delta[ally_faction] = (
                        faction_cohesion_delta.get(ally_faction, 0) + cohesion_gain
                    )
                effect["changes"] = {
                    "morale": morale_gain,
                    "tension_level": -tension_relief,
                    f"faction_cohesion:{ally_faction}": cohesion_gain,
                }

            elif category == "advance_goal":
                goal_progress = decision.get("goal_progress", 0)
                if goal_progress >= 100:
                    world_event = {
                        "event_type": "goal_completed",
                        "source_char_id": char_id,
                        "source_char_name": char_name,
                        "source_affiliation": affiliation,
                        "decision_category": "advance_goal",
                        "description": f"{char_name} achieved a major objective",
                        "visibility": "public",
                        "significance": 0.85,
                        "faction": affiliation,
                        "ts": int(ts),
                    }
                    r.zadd(
                        "npc_world_events",
                        {json.dumps(world_event): ts},
                    )
                    results["events_generated"].append(world_event)
                    stability_boost = rng.uniform(0.1, 0.4)
                    world["stability"] = _clamp(world["stability"] + stability_boost)
                    effect["changes"] = {
                        "goal_completed": True,
                        "stability": stability_boost,
                    }

            elif category == "socialize":
                tension_relief = rng.uniform(0.04, 0.12)
                world["tension_level"] = _clamp(world["tension_level"] - tension_relief)
                effect["changes"]["tension_level"] = -tension_relief
                if rng.random() < 0.20:
                    target_id = decision.get("target_char_id", "")
                    if target_id:
                        rel_key = f"npc_relationships:{char_id}"
                        try:
                            current = float(r.hget(rel_key, target_id) or 50)
                            improvement = rng.uniform(1, 5)
                            r.hset(
                                rel_key,
                                target_id,
                                str(
                                    round(
                                        _clamp(current + improvement, 0, 100),
                                        2,
                                    )
                                ),
                            )
                            effect["changes"] = {
                                "relationship_improved": target_id,
                                "improvement": improvement,
                            }
                        except (ValueError, TypeError):
                            pass
                    interaction_event = {
                        "event_type": "social_interaction",
                        "source_char_id": char_id,
                        "source_char_name": char_name,
                        "source_affiliation": affiliation,
                        "decision_category": "socialize",
                        "description": f"{char_name} strengthened social bonds",
                        "visibility": "faction",
                        "significance": 0.3,
                        "faction": affiliation,
                        "ts": int(ts),
                    }
                    r.zadd(
                        "npc_world_events",
                        {json.dumps(interaction_event): ts},
                    )
                    results["events_generated"].append(interaction_event)

            elif category == "react_to_events":
                threat_rise = rng.uniform(0.01, 0.05)
                morale_hit = rng.uniform(0.01, 0.04)
                world["threat_level"] = _clamp(world["threat_level"] + threat_rise)
                world["morale"] = _clamp(world["morale"] - morale_hit)
                effect["changes"] = {
                    "threat_level": threat_rise,
                    "morale": -morale_hit,
                }
                try:
                    broadcast_events = r.zrevrange(
                        "npc_broadcast_events", 0, 2, withscores=True
                    )
                    for event_json, _ in broadcast_events:
                        try:
                            evt = json.loads(event_json)
                            if evt.get("source_char_id") != char_id:
                                pass
                        except (json.JSONDecodeError, TypeError):
                            continue
                except Exception:
                    pass

            elif category == "explore":
                resource_gain = rng.uniform(0.06, 0.2)
                world["resource_abundance"] = _clamp(
                    world["resource_abundance"] + resource_gain
                )
                effect["changes"] = {"resource_abundance": resource_gain}
                if rng.random() < 0.10:
                    discovery_event = {
                        "event_type": "expedition_discovery",
                        "source_char_id": char_id,
                        "source_char_name": char_name,
                        "source_affiliation": affiliation,
                        "decision_category": "explore",
                        "description": f"{char_name} discovered new resources",
                        "visibility": "public",
                        "significance": 0.75,
                        "faction": affiliation,
                        "ts": int(ts),
                    }
                    r.zadd(
                        "npc_world_events",
                        {json.dumps(discovery_event): ts},
                    )
                    results["events_generated"].append(discovery_event)
                    effect["changes"]["discovery"] = True

            elif category == "rest":
                morale_gain = rng.uniform(0.02, 0.1)
                threat_relief = rng.uniform(0.04, 0.14)
                world["morale"] = _clamp(world["morale"] + morale_gain)
                world["threat_level"] = _clamp(world["threat_level"] - threat_relief)
                effect["changes"] = {
                    "morale": morale_gain,
                    "threat_level": -threat_relief,
                }

            elif category == "self_improve":
                power_gain = rng.uniform(0.1, 0.4)
                faction_power_delta[affiliation] = (
                    faction_power_delta.get(affiliation, 0) + power_gain
                )
                anomaly_rise = rng.uniform(0.02, 0.1)
                world["anomaly_activity"] = _clamp(
                    world["anomaly_activity"] + anomaly_rise
                )
                effect["changes"] = {
                    f"faction_power:{affiliation}": power_gain,
                    "anomaly_activity": anomaly_rise,
                }

                _store_effect(r, effect, ts)
                results["effects_applied"] += 1

        except Exception as exc:
            logger.error(
                "Error executing decision %s: %s",
                decision.get("char_id", "?"),
                exc,
            )
            results["errors"].append(str(exc))

    try:
        _write_world_state(r, world)
        results["world_state_changes"] = {
            k: round(world[k] - float(WORLD_DEFAULTS.get(k, 0)), 2)
            for k in WORLD_CONDITIONS
            if abs(world[k] - float(WORLD_DEFAULTS.get(k, 0))) > 0.01
        }
    except Exception as exc:
        logger.error("Error writing world state: %s", exc)
        results["errors"].append(str(exc))

    # Fix: faction_power must be CUMULATIVE — read existing, add delta, write back
    # (previously was overwriting with raw delta, destroying accumulated power)
    pipe = r.pipeline()
    for faction, delta in faction_power_delta.items():
        if faction and faction != "independent":
            key = f"faction_power:{faction}"
            current = 0.0
            try:
                existing = r.get(key)
                if existing is not None:
                    current = float(existing)
            except (ValueError, TypeError):
                pass
            new_total = round(current + delta, 2)
            pipe.set(key, str(new_total), ex=FACTION_METRIC_TTL)
            results["faction_updates"][key] = delta
    for faction, delta in faction_stability_delta.items():
        if faction and faction != "independent":
            key = f"faction_stability:{faction}"
            current = 100.0
            try:
                existing = r.get(key)
                if existing is not None:
                    current = float(existing)
            except (ValueError, TypeError):
                pass
            pipe.set(key, str(round(_clamp(current + delta), 2)), ex=FACTION_METRIC_TTL)
            results["faction_updates"][key] = delta
    for faction, delta in faction_cohesion_delta.items():
        if faction and faction != "independent":
            key = f"faction_cohesion:{faction}"
            current = 50.0
            try:
                existing = r.get(key)
                if existing is not None:
                    current = float(existing)
            except (ValueError, TypeError):
                pass
            pipe.set(key, str(round(_clamp(current + delta), 2)), ex=FACTION_METRIC_TTL)
            results["faction_updates"][key] = delta
    try:
        pipe.execute()
    except Exception as exc:
        logger.error("Error writing faction metrics: %s", exc)
        results["errors"].append(str(exc))

    return results


def bridge_world_state_to_game_state() -> Dict:
    """
    Read the world_state hash from Redis and produce recommended deltas
    for FederationGameState.

    NPC actions produce SMALLER deltas than player actions — scaled by 0.3.
    The game_state fields map from world_state as:
    - morale → federation.morale
    - stability → federation.stability
    - resource_abundance → federation.treasury
    - threat_level → federation.military_power
    - anomaly_activity → federation.technological_level

    Returns:
        Dict with keys: deltas, world_state_snapshot, warnings
        The `deltas` dict contains the recommended changes for main.py to apply.
    """
    r = _get_redis()
    ts = time.time()

    result = {
        "deltas": {
            "federation.morale": 0.0,
            "federation.stability": 0.0,
            "federation.technological_level": 0.0,
            "federation.military_power": 0.0,
            "federation.treasury": 0,
        },
        "world_state_snapshot": {},
        "warnings": [],
    }

    try:
        world = _read_world_state(r)
        result["world_state_snapshot"] = {k: round(v, 2) for k, v in world.items()}
    except Exception as exc:
        logger.error("Error reading world state for game state bridge: %s", exc)
        result["warnings"].append(f"world_state_read_failed: {exc}")
        return result

    morale_delta = (world.get("morale", 55) - 55) / 100.0
    stability_delta = (world.get("stability", 65) - 65) / 100.0
    resource_delta = world.get("resource_abundance", 60) - 60
    threat_delta = (world.get("threat_level", 30) - 30) / 100.0
    anomaly_delta = (world.get("anomaly_activity", 20) - 20) / 100.0

    result["deltas"]["federation.morale"] = round(
        morale_delta * CROSS_POLLINATION_SCALE, 4
    )
    result["deltas"]["federation.stability"] = round(
        stability_delta * CROSS_POLLINATION_SCALE, 4
    )
    result["deltas"]["federation.technological_level"] = round(
        anomaly_delta * CROSS_POLLINATION_SCALE * 0.5, 4
    )
    result["deltas"]["federation.military_power"] = round(
        threat_delta * CROSS_POLLINATION_SCALE * 0.1, 4
    )
    result["deltas"]["federation.treasury"] = int(
        resource_delta * GAME_STATE_DELTA_SCALE * CROSS_POLLINATION_SCALE
    )

    for field, value in result["deltas"].items():
        if isinstance(value, float):
            result["deltas"][field] = _clamp(value, -1.0, 1.0)

    try:
        bridge_record = {
            "ts": int(ts),
            "world_state": result["world_state_snapshot"],
            "deltas": result["deltas"],
        }
        _store_effect(
            r, {"type": "world_to_game_state_bridge", "deltas": result["deltas"]}, ts
        )
    except Exception as exc:
        logger.error("Error storing bridge effect: %s", exc)

    return result


def get_faction_decision_modifier(faction_context: Optional[Dict]) -> Dict[str, float]:
    """
    Return score multipliers for each decision category based on faction context.

    Rules:
    - High cohesion (>0.7): boost help_ally and advance_goal by 1.2
    - Under threat (standing <0.3): boost confront_rival and react_to_events by 1.3
    - High influence (>0.7): boost seek_resources and explore by 1.2

    Args:
        faction_context: Output of get_faction_context_for_npc, or None.

    Returns:
        Dict mapping decision categories to multiplier floats (default 1.0).
    """
    modifiers = {cat: 1.0 for cat in VALID_CATEGORIES}

    if not faction_context:
        return modifiers

    try:
        cohesion_raw = faction_context.get("cohesion", 50)
        cohesion_norm = (
            float(cohesion_raw) / 100.0 if cohesion_raw > 1.0 else float(cohesion_raw)
        )
        standing_raw = faction_context.get("standing", 50)
        standing_norm = (
            float(standing_raw) / 100.0 if standing_raw > 1.0 else float(standing_raw)
        )
        influence_raw = faction_context.get("influence", 50)
        influence_norm = (
            float(influence_raw) / 100.0
            if influence_raw > 1.0
            else float(influence_raw)
        )

        if cohesion_norm > 0.7:
            modifiers["help_ally"] = 1.2
            modifiers["advance_goal"] = 1.2

        if standing_norm < 0.3:
            modifiers["confront_rival"] = 1.3
            modifiers["react_to_events"] = 1.3

        if influence_norm > 0.7:
            modifiers["seek_resources"] = 1.2
            modifiers["explore"] = 1.2

    except (ValueError, TypeError) as exc:
        logger.error("Error computing faction decision modifier: %s", exc)

    return modifiers


def wire_faction_context_into_decisions(npc_list: List[Dict]) -> Dict:
    """
    For each NPC, fetch faction context from faction_dynamics and store it
    in Redis with a 5-minute TTL so npc_autonomy._score_decision_option()
    can access it.

    Also creates a score modifier per NPC based on faction context.

    Args:
        npc_list: List of NPC dicts, each with 'char_id' and 'affiliation'.

    Returns:
        Dict with keys: npcs_updated, contexts_stored, modifiers, errors
    """
    r = _get_redis()
    results = {
        "npcs_updated": 0,
        "contexts_stored": 0,
        "modifiers": {},
        "errors": [],
    }

    if not npc_list:
        return results

    pipe = r.pipeline()

    for npc in npc_list:
        try:
            char_id = npc.get("char_id", "")
            affiliation = npc.get("affiliation", "independent")

            if not char_id or affiliation == "independent":
                continue

            context = get_faction_context_for_npc(affiliation)

            if context is None:
                continue

            context_json = json.dumps(context)
            key = f"npc_faction_context:{char_id}"
            pipe.set(key, context_json, ex=NPC_FACTION_CONTEXT_TTL)

            modifiers = get_faction_decision_modifier(context)
            results["modifiers"][char_id] = modifiers

            modifier_key = f"npc_faction_modifier:{char_id}"
            pipe.set(modifier_key, json.dumps(modifiers), ex=NPC_FACTION_CONTEXT_TTL)

            results["contexts_stored"] += 1
            results["npcs_updated"] += 1

        except Exception as exc:
            logger.error(
                "Error wiring faction context for NPC %s: %s",
                npc.get("char_id", "?"),
                exc,
            )
            results["errors"].append(str(exc))

    try:
        pipe.execute()
    except Exception as exc:
        logger.error("Error storing faction contexts: %s", exc)
        results["errors"].append(str(exc))

    return results


def bridge_npc_events_to_political(npc_list: List[Dict]) -> Dict:
    """
    Read npc_broadcast_events and produce political consequences:
    - 3+ confront_rival events from same faction → propose "sanctions" law
    - 5+ help_ally events between two factions → create "alliance_proposal"
    - Any investigate breakthrough → create "research_initiative"

    Stores results in Redis lists: pending_laws, pending_treaties, pending_research.

    Args:
        npc_list: List of NPC dicts with 'char_id' and 'affiliation'.

    Returns:
        Dict with keys: laws_proposed, treaties_proposed, research_initiated, errors
    """
    r = _get_redis()
    ts = time.time()

    results = {
        "laws_proposed": 0,
        "treaties_proposed": 0,
        "research_initiated": 0,
        "errors": [],
    }

    confront_by_faction: Dict[str, List[Dict]] = {}
    ally_pairs: Dict[str, int] = {}
    breakthroughs: List[Dict] = []

    try:
        raw_events = r.zrevrange("npc_broadcast_events", 0, 99, withscores=True)
    except Exception as exc:
        logger.error("Error reading broadcast events: %s", exc)
        results["errors"].append(str(exc))
        return results

    for event_json, score in raw_events:
        try:
            evt = json.loads(event_json)
        except (json.JSONDecodeError, TypeError):
            continue

        category = evt.get("decision_category", "")
        faction = evt.get("source_affiliation", evt.get("faction", ""))

        if category == "confront_rival":
            if faction and faction != "independent":
                confront_by_faction.setdefault(faction, []).append(evt)

        elif category == "help_ally":
            target = evt.get("target_faction", "")
            if (
                faction
                and target
                and faction != "independent"
                and target != "independent"
            ):
                pair = tuple(sorted([faction, target]))
                ally_pairs[str(pair)] = ally_pairs.get(str(pair), 0) + 1

        elif category == "investigate":
            if evt.get("event_type") == "investigation_breakthrough":
                breakthroughs.append(evt)

    try:
        for faction, events in confront_by_faction.items():
            if len(events) >= 3:
                target_factions = set()
                for evt in events:
                    tf = evt.get("target_faction", "unknown")
                    if tf and tf != "independent":
                        target_factions.add(tf)
                target_list = list(target_factions) if target_factions else ["unknown"]

                law = {
                    "type": "sanctions",
                    "proposing_faction": faction,
                    "target_factions": target_list,
                    "trigger_count": len(events),
                    "description": f"{faction} demands sanctions after {len(events)} confrontations",
                    "severity": min(len(events) / 5.0, 1.0),
                    "ts": int(ts),
                }
                r.lpush("pending_laws", json.dumps(law))
                results["laws_proposed"] += 1

    except Exception as exc:
        logger.error("Error proposing laws: %s", exc)
        results["errors"].append(str(exc))

    try:
        for pair_str, count in ally_pairs.items():
            if count >= 5:
                pair = (
                    pair_str.replace("(", "")
                    .replace(")", "")
                    .replace("'", "")
                    .split(", ")
                )
                pair = [p.strip() for p in pair if p.strip()]
                if len(pair) >= 2:
                    treaty = {
                        "type": "alliance_proposal",
                        "factions": pair,
                        "trigger_count": count,
                        "description": f"Alliance proposed between {pair[0]} and {pair[1]} after {count} mutual aid events",
                        "strength": min(count / 10.0, 1.0),
                        "ts": int(ts),
                    }
                    r.lpush("pending_treaties", json.dumps(treaty))
                    results["treaties_proposed"] += 1

    except Exception as exc:
        logger.error("Error proposing treaties: %s", exc)
        results["errors"].append(str(exc))

    try:
        for evt in breakthroughs:
            faction = evt.get("source_affiliation", evt.get("faction", "independent"))
            char_name = evt.get("source_char_name", "Unknown")
            research = {
                "type": "research_initiative",
                "proposing_faction": faction,
                "source_char": evt.get("source_char_id", ""),
                "source_char_name": char_name,
                "description": f"Research initiative from {char_name}'s breakthrough",
                "potential": round(random.uniform(0.3, 0.9), 2),
                "ts": int(ts),
            }
            r.lpush("pending_research", json.dumps(research))
            results["research_initiated"] += 1

    except Exception as exc:
        logger.error("Error creating research initiatives: %s", exc)
        results["errors"].append(str(exc))

    try:
        r.ltrim("pending_laws", 0, 49)
        r.ltrim("pending_treaties", 0, 49)
        r.ltrim("pending_research", 0, 49)
    except Exception as exc:
        logger.error("Error trimming pending lists: %s", exc)
        results["errors"].append(str(exc))

    return results


def check_era_advancement(npc_list: List[Dict]) -> Dict:
    """
    Read NPC moods and world state. If conditions meet thresholds,
    recommend era advancement.

    Thresholds:
    - Crisis Era: 80%+ NPCs negative mood AND tension > 70 AND stability < 30
    - Golden Age: 70%+ NPCs positive mood AND resource_abundance > 60 AND stability > 60

    Args:
        npc_list: List of NPC dicts with 'char_id' keys.

    Returns:
        Dict with keys: should_advance, recommended_era, evidence, errors
    """
    r = _get_redis()

    result = {
        "should_advance": False,
        "recommended_era": "",
        "evidence": {
            "negative_mood_pct": 0.0,
            "positive_mood_pct": 0.0,
            "tension_level": 0.0,
            "stability": 0.0,
            "resource_abundance": 0.0,
            "npc_count": 0,
        },
        "errors": [],
    }

    try:
        world = _read_world_state(r)
        result["evidence"]["tension_level"] = round(world.get("tension_level", 50), 2)
        result["evidence"]["stability"] = round(world.get("stability", 65), 2)
        result["evidence"]["resource_abundance"] = round(
            world.get("resource_abundance", 60), 2
        )
    except Exception as exc:
        logger.error("Error reading world state for era check: %s", exc)
        result["errors"].append(str(exc))
        return result

    positive_moods = {
        "confident",
        "determined",
        "hopeful",
        "curious",
        "inspired",
        "calm",
        "focused",
    }
    negative_moods = {
        "anxious",
        "angry",
        "fearful",
        "suspicious",
        "desperate",
        "hostile",
        "resentful",
        "paranoid",
    }

    positive_count = 0
    negative_count = 0
    total = 0

    for npc in npc_list:
        try:
            char_id = npc.get("char_id", "")
            if not char_id:
                continue

            mood = r.get(f"npc_mood:{char_id}")
            if mood is None:
                mood = npc.get("mood", "")

            mood_lower = str(mood).lower()
            total += 1

            if any(neg in mood_lower for neg in negative_moods):
                negative_count += 1
            elif any(pos in mood_lower for pos in positive_moods):
                positive_count += 1

        except Exception as exc:
            logger.error("Error reading mood for era check: %s", exc)

    result["evidence"]["npc_count"] = total

    if total > 0:
        result["evidence"]["negative_mood_pct"] = round(negative_count / total, 4)
        result["evidence"]["positive_mood_pct"] = round(positive_count / total, 4)

    neg_pct = result["evidence"]["negative_mood_pct"]
    pos_pct = result["evidence"]["positive_mood_pct"]
    tension = world.get("tension_level", 50)
    stability = world.get("stability", 65)
    resources = world.get("resource_abundance", 60)

    if neg_pct >= 0.80 and tension > 70 and stability < 30:
        result["should_advance"] = True
        result["recommended_era"] = "Crisis Era"
    elif pos_pct >= 0.70 and resources > 60 and stability > 60:
        result["should_advance"] = True
        result["recommended_era"] = "Golden Age"

    return result


def autonomous_tick(npc_list: List[Dict], tick_decisions: List[Dict]) -> Dict:
    """
    THE MASTER FUNCTION. Runs all simulation subsystems in the correct
    cross-pollination order:

    1. Wire faction context into NPC decisions
    2. Execute NPC decisions with concrete effects
    3. Bridge world state to game state
    4. Bridge NPC events to political engine
    5. Check era advancement

    Each sub-step is wrapped in try/except so failures are logged
    but don't stop the tick.

    Args:
        npc_list: List of NPC dicts with 'char_id', 'affiliation', etc.
        tick_decisions: List of decision dicts from the current tick.

    Returns:
        Comprehensive result dict with all sub-results plus timing info.
    """
    r = _get_redis()
    tick_start = time.time()
    tick_ts = int(tick_start)

    # Ensure world_state hash exists — seed with defaults if empty
    try:
        existing = r.hgetall("world_state")
        if not existing:
            seed_pipe = r.pipeline()
            for key, val in WORLD_DEFAULTS.items():
                seed_pipe.hset("world_state", key, str(int(val)))
            seed_pipe.set("world_state_updated", str(tick_ts), ex=86400 * 30)
            seed_pipe.execute()
            logger.info("Seeded world_state hash with defaults (was empty)")
    except Exception as exc:
        logger.warning("World state seed check failed: %s", exc)

    result = {
        "tick_ts": tick_ts,
        "step1_faction_context": {},
        "step2_decision_effects": {},
        "step3_game_state_bridge": {},
        "step4_political_bridge": {},
        "step5_era_check": {},
        "duration_ms": 0,
        "errors": [],
    }

    try:
        step_start = time.time()
        result["step1_faction_context"] = wire_faction_context_into_decisions(npc_list)
        result["step1_faction_context"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 1 (faction context wiring) failed: %s", exc)
        result["step1_faction_context"] = {"errors": [str(exc)]}
        result["errors"].append(f"step1: {exc}")

    try:
        step_start = time.time()
        result["step2_decision_effects"] = execute_npc_decisions(tick_decisions)
        result["step2_decision_effects"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 2 (decision execution) failed: %s", exc)
        result["step2_decision_effects"] = {"errors": [str(exc)]}
        result["errors"].append(f"step2: {exc}")

    try:
        step_start = time.time()
        result["step3_game_state_bridge"] = bridge_world_state_to_game_state()
        result["step3_game_state_bridge"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 3 (game state bridge) failed: %s", exc)
        result["step3_game_state_bridge"] = {"errors": [str(exc)]}
        result["errors"].append(f"step3: {exc}")

    try:
        step_start = time.time()
        result["step4_political_bridge"] = bridge_npc_events_to_political(npc_list)
        result["step4_political_bridge"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 4 (political bridge) failed: %s", exc)
        result["step4_political_bridge"] = {"errors": [str(exc)]}
        result["errors"].append(f"step4: {exc}")

    try:
        step_start = time.time()
        result["step5_era_check"] = check_era_advancement(npc_list)
        result["step5_era_check"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 5 (era check) failed: %s", exc)
        result["step5_era_check"] = {"errors": [str(exc)]}
        result["errors"].append(f"step5: {exc}")

    result["duration_ms"] = round((time.time() - tick_start) * 1000, 1)

    try:
        summary = {
            "tick_ts": tick_ts,
            "npcs": len(npc_list),
            "decisions": len(tick_decisions),
            "effects_applied": result["step2_decision_effects"].get(
                "effects_applied", 0
            ),
            "laws_proposed": result["step4_political_bridge"].get("laws_proposed", 0),
            "treaties_proposed": result["step4_political_bridge"].get(
                "treaties_proposed", 0
            ),
            "research_initiated": result["step4_political_bridge"].get(
                "research_initiated", 0
            ),
            "era_recommendation": result["step5_era_check"].get("recommended_era", ""),
            "duration_ms": result["duration_ms"],
            "errors": len(result["errors"]),
        }
        r.zadd("sim_tick_log", {json.dumps(summary): tick_start})
        r.expire("sim_tick_log", TICK_LOG_TTL)
        r.zremrangebyrank("sim_tick_log", 0, -501)

        r.set("sim_last_tick", str(tick_ts), ex=LAST_TICK_TTL)
    except Exception as exc:
        logger.error("Error storing tick log: %s", exc)
        result["errors"].append(f"tick_log: {exc}")

    logger.info(
        "Autonomous tick %d complete: %d effects, %dms, %d errors",
        tick_ts,
        result["step2_decision_effects"].get("effects_applied", 0),
        result["duration_ms"],
        len(result["errors"]),
    )

    return result
