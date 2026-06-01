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
from typing import Any, Dict, List, Optional, Tuple

import redis

from faction_dynamics import get_faction_context_for_npc, KNOWN_FACTIONS
from npc_autonomy import _get_redis as _get_npc_redis
from npc_quest_engine import NPCQuestEngine
from faction_tech_research import FactionTechBridge
from faction_diplomacy import FACTION_IDEOLOGY_AFFINITY, _get_diplomacy_engine
from faction_ai import FACTION_IDEOLOGY
from quests import (
    create_quest_library as _create_quest_library,
)

# LLM cognition and narration — guarded imports (graceful degradation if unavailable)
try:
    from npc_cognition import run_cognition

    COGNITION_AVAILABLE = True
except ImportError:
    COGNITION_AVAILABLE = False

try:
    from narrator import generate_narration

    NARRATOR_AVAILABLE = True
except ImportError:
    NARRATOR_AVAILABLE = False

try:
    from npc_memory import harvest_tick_memories

    NPC_MEMORY_AVAILABLE = True
except ImportError:
    NPC_MEMORY_AVAILABLE = False
from technology import (
    TechTree as _TechTree,
    create_technology_tree as _create_technology_tree,
)

logger = logging.getLogger(__name__)

_quest_system_singleton = None
_quest_engine_singleton = None
_tech_tree_singleton = None
_tech_bridge_singleton = None


def _get_quest_engine(redis_client):
    global _quest_system_singleton, _quest_engine_singleton
    if _quest_system_singleton is None:
        _quest_system_singleton = _create_quest_library()
    if (
        _quest_engine_singleton is None
        or _quest_engine_singleton.quest_system is not _quest_system_singleton
    ):
        _quest_engine_singleton = NPCQuestEngine(
            quest_system=_quest_system_singleton, redis_client=redis_client
        )
    return _quest_engine_singleton


def _get_tech_bridge(redis_client):
    """Lazy singleton for FactionTechBridge with its own TechTree."""
    global _tech_tree_singleton, _tech_bridge_singleton
    if _tech_tree_singleton is None:
        _tech_tree_singleton = _create_technology_tree()
    if _tech_bridge_singleton is None:
        _tech_bridge_singleton = FactionTechBridge(
            tech_tree=_tech_tree_singleton, redis_client=redis_client
        )
    return _tech_bridge_singleton


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


def generate_and_apply_events(max_events: int = 3) -> Dict:
    """Generate random game events and apply their effects to world_state + game_state.

    This bridges the EventSystem with the simulation engine by:
    1. Generating 1-3 random events per tick
    2. For events with choices: resolve via faction ideology voting (AutonomousChoiceResolver)
    3. For events without choices: apply base effects directly
    4. Storing applied effects in Redis for audit trail
    5. Writing event summaries to npc_world_events for cascade processing

    Returns:
    Dict with keys: events_generated, effects_applied, choice_resolutions, errors
    """
    r = _get_redis()
    ts = time.time()
    results = {
        "events_generated": [],
        "effects_applied": [],
        "choice_resolutions": [],
        "errors": [],
    }

    try:
        from federation_game_events import EventSystem, EventGenerator, EffectType
    except ImportError:
        results["errors"].append("federation_game_events not importable")
        return results

    choice_resolver = None
    try:
        from autonomous_choice_resolver import AutonomousChoiceResolver
        from faction_ai import FACTION_IDEOLOGY

        choice_resolver = AutonomousChoiceResolver(redis_client=r)
    except ImportError:
        logger.info("autonomous_choice_resolver not available, using base effects only")

    try:
        generator = EventGenerator()
        event_system = EventSystem(generator)

        num_events = random.randint(1, max_events)

        for _ in range(num_events):
            try:
                event = generator.generate_random_event()
                has_choices = bool(
                    getattr(event, "choices", None) and len(event.choices) > 0
                )

                if has_choices and choice_resolver is not None:
                    resolution = choice_resolver.resolve_and_apply(
                        event, FACTION_IDEOLOGY, redis_client=r
                    )
                    results["choice_resolutions"].append(
                        {
                            "event_name": event.name,
                            "event_id": event.id,
                            "chosen_choice_id": resolution.get("chosen_choice_id"),
                            "vote_count": len(resolution.get("faction_votes", {})),
                            "consequences_applied": len(
                                resolution.get("consequences_applied", [])
                            ),
                            "justification": resolution.get("justification", ""),
                        }
                    )
                    for ce in resolution.get("consequences_applied", []):
                        results["effects_applied"].append(ce)
                else:
                    for effect in event.effects:
                        applied = _apply_event_effect_to_world(r, effect, ts)
                        results["effects_applied"].append(applied)

                event_summary = {
                    "event_type": "game_event",
                    "game_event_type": event.event_type.value,
                    "name": event.name,
                    "severity": event.severity.name,
                    "description": event.description,
                    "source": "event_system",
                    "visibility": "public",
                    "significance": min(1.0, event.severity.value * 0.3),
                    "ts": int(ts),
                    "resolved_via": "faction_vote"
                    if (has_choices and choice_resolver)
                    else "base_effects",
                }
                r.zadd("npc_world_events", {json.dumps(event_summary): ts})

                r.zadd("game_events_log", {json.dumps(event.to_dict()): ts})
                r.zremrangebyrank("game_events_log", 0, -(101))

                results["events_generated"].append(
                    {
                        "name": event.name,
                        "type": event.event_type.value,
                        "severity": event.severity.name,
                        "effects_count": len(event.effects),
                        "choices_count": len(event.choices) if has_choices else 0,
                        "resolution": "faction_vote"
                        if (has_choices and choice_resolver)
                        else "base_only",
                    }
                )

            except Exception as exc:
                logger.error("Error generating/applying event: %s", exc)
                results["errors"].append(str(exc))

        r.zremrangebyrank("npc_world_events", 0, -(51))

    except Exception as exc:
        logger.error("Event system error: %s", exc)
        results["errors"].append(str(exc))

    return results


def _apply_event_effect_to_world(r, effect, ts: float) -> Dict:
    """Apply a GameEffect directly to Redis world_state.

    This is the autonomous-mode equivalent of EventSystem._apply_effect().
    It doesn't need a FederationGameState instance — it modifies Redis directly,
    which the bridge_world_state_to_game_state() function will pick up.
    """
    result = {
        "effect_type": effect.effect_type.value,
        "target": effect.target,
        "magnitude": effect.magnitude,
        "applied": False,
        "timestamp": ts,
    }

    try:
        mag = effect.magnitude

        # Map effect types to world_state keys
        world_key_map = {
            "diplomacy_impact": "tension_level",
            "consciousness_impact": "anomaly_activity",
            "rival_impact": "threat_level",
            "resource_impact": "resource_abundance",
            "stability_impact": "stability",
            "tech_impact": "anomaly_activity",
            "culture_impact": "morale",
            "paradox_impact": "stability",
        }

        effect_key = (
            effect.effect_type.value
            if hasattr(effect.effect_type, "value")
            else str(effect.effect_type)
        )
        world_key = world_key_map.get(effect_key)

        if world_key:
            # Direction mapping:
            # diplomacy_impact positive = less tension (invert)
            # resource_impact positive = more abundance (same)
            # stability_impact positive = more stability (same)
            # culture_impact positive = more morale (same)
            # rival_impact positive = more threat (same)
            # paradox_impact negative = less stability (same direction, negative magnitude = less stability)
            # tech_impact positive = more anomaly/research activity (same)
            # consciousness_impact positive = more anomaly (same)
            if effect_key == "diplomacy_impact":
                delta = -mag * 5.0  # Good diplomacy reduces tension
            elif effect_key == "rival_impact":
                delta = mag * 3.0  # Rival gaining power increases threat
            else:
                delta = mag * 5.0  # Direct mapping

            current = 50.0
            try:
                raw = r.hget("world_state", world_key)
                if raw is not None:
                    current = float(raw)
            except (ValueError, TypeError):
                pass

            new_val = max(0.0, min(100.0, current + delta))
            r.hset("world_state", world_key, str(round(new_val, 2)))

            result["applied"] = True
            result["world_key"] = world_key
            result["delta"] = round(delta, 4)
            result["new_value"] = round(new_val, 2)

            # Store effect for audit
            effect_record = {
                "type": "event_effect",
                "effect_type": effect_key,
                "target": effect.target,
                "magnitude": mag,
                "world_key": world_key,
                "delta": round(delta, 4),
                "ts": int(ts),
            }
            r.zadd(f"sim_effects:{int(ts)}", {json.dumps(effect_record): ts})

    except Exception as exc:
        result["error"] = str(exc)

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
    Read npc_broadcast_events, npc_world_events, and faction_actions:* to
    produce political consequences:
    - Adaptive-threshold confront_rival events from same faction → propose "sanctions" law
    - Adaptive-threshold help_ally events between two factions → create "alliance_proposal"
    - Any investigate breakthrough → create "research_initiative"

    Thresholds are now ADAPTIVE based on NPC count per faction:
    - confront_rival: max(2, ceil(npcs_in_faction / 4))  (was hardcoded 3)
    - help_ally:      max(2, ceil(npcs_in_pair / 6))     (was hardcoded 5)

    Data sources expanded from npc_broadcast_events only to also include
    npc_world_events and faction_actions:* for richer signal.

    Stores results in Redis lists: pending_laws, pending_treaties, pending_research.
    Also writes directly to faction_laws_passed and faction_treaties_active so that
    resolve_pending_items() in faction_ai can process them.

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

    # ── Count NPCs per faction for adaptive thresholds ──────────────────
    faction_npc_counts: Dict[str, int] = {}
    for npc in npc_list:
        fid = npc.get("affiliation", "")
        if fid and fid != "independent":
            faction_npc_counts[fid] = faction_npc_counts.get(fid, 0) + 1

    # ── Collect events from ALL three data sources ──────────────────────
    confront_by_faction: Dict[str, List[Dict]] = {}
    ally_pairs: Dict[str, int] = {}
    breakthroughs: List[Dict] = []

    def _process_event(evt: Dict):
        """Classify a single event into confront/ally/breakthrough buckets."""
        category = evt.get("decision_category", "")
        faction = evt.get("source_affiliation", evt.get("faction", ""))

        # Also detect political signals from faction_actions
        action_type = evt.get("action", evt.get("type", ""))
        if not category and action_type in ("confront", "hostile_act", "sanction"):
            category = "confront_rival"
            if not faction:
                faction = evt.get("from", evt.get("faction_id", ""))
        if not category and action_type in ("aid", "trade", "alliance", "help_ally"):
            category = "help_ally"
            if not faction:
                faction = evt.get("from", evt.get("faction_id", ""))

        if category == "confront_rival":
            if faction and faction != "independent":
                confront_by_faction.setdefault(faction, []).append(evt)

        elif category == "help_ally":
            target = evt.get("target_faction", evt.get("to", ""))
            if (
                faction
                and target
                and faction != "independent"
                and target != "independent"
                and faction != target
            ):
                pair = tuple(sorted([faction, target]))
                ally_pairs[str(pair)] = ally_pairs.get(str(pair), 0) + 1

        elif category == "investigate":
            if evt.get("event_type") == "investigation_breakthrough":
                breakthroughs.append(evt)

    # Source 1: npc_broadcast_events (the original source — last 100)
    try:
        raw_events = r.zrevrange("npc_broadcast_events", 0, 99, withscores=True)
        for event_json, score in raw_events:
            try:
                evt = json.loads(event_json)
                _process_event(evt)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as exc:
        logger.error("Error reading broadcast events: %s", exc)
        results["errors"].append(str(exc))

    # Source 2: npc_world_events (last 50 — contains cascade summaries)
    try:
        world_events = r.zrevrange("npc_world_events", 0, 49, withscores=True)
        for event_json, score in world_events:
            try:
                evt = json.loads(event_json)
                _process_event(evt)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as exc:
        logger.error("Error reading world events: %s", exc)
        results["errors"].append(str(exc))

    # Source 3: faction_actions:* for each known faction (last 10 per faction)
    for fid in KNOWN_FACTIONS:
        try:
            faction_actions = r.zrevrange(
                f"faction_actions:{fid}", 0, 9, withscores=True
            )
            for action_json, score in faction_actions:
                try:
                    action = json.loads(action_json)
                    # Inject faction context if missing
                    if "source_affiliation" not in action and "faction" not in action:
                        action["source_affiliation"] = fid
                    _process_event(action)
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception:
            continue

    # ── Adaptive threshold calculation ──────────────────────────────────
    import math

    def _confront_threshold(faction: str) -> int:
        """Adaptive: max(2, ceil(npcs_in_faction / 4)). With ~5 NPCs/faction, yields 2."""
        count = faction_npc_counts.get(faction, 5)
        return max(2, math.ceil(count / 4))

    def _treaty_threshold(pair_str: str) -> int:
        """Adaptive: max(2, ceil(total_npcs_in_pair / 6)). With ~10 NPCs/pair, yields 2."""
        try:
            parts = (
                pair_str.replace("(", "").replace(")", "").replace("'", "").split(", ")
            )
            parts = [p.strip() for p in parts if p.strip()]
            total = sum(faction_npc_counts.get(p, 5) for p in parts)
        except Exception:
            total = 10
        return max(2, math.ceil(total / 6))

    # ── Propose laws (with adaptive thresholds) ─────────────────────────
    try:
        for faction, events in confront_by_faction.items():
            threshold = _confront_threshold(faction)
            if len(events) >= threshold:
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
                    "threshold_used": threshold,
                    "description": f"{faction} demands sanctions after {len(events)} confrontations (threshold: {threshold})",
                    "severity": min(len(events) / 5.0, 1.0),
                    "ts": int(ts),
                }
                # Write to pending_laws (original path)
                r.lpush("pending_laws", json.dumps(law))
                # ALSO write to faction_laws_passed so resolve_pending_items() processes it
                law_for_faction_ai = {
                    "title": f"Sanctions vs {', '.join(target_list)}",
                    "proposed_by": faction,
                    "ideology": FACTION_IDEOLOGY.get(faction, "diplomatic"),
                    "description": law["description"],
                    "morale_delta": round(-0.05 * law["severity"], 3),
                    "stability_delta": round(0.02 * law["severity"], 3),
                    "treasury_delta": 0,
                    "timestamp": int(ts),
                    "status": "pending",
                    "source": "political_bridge",
                }
                r.zadd("faction_laws_passed", {json.dumps(law_for_faction_ai): int(ts)})
                results["laws_proposed"] += 1
                logger.info(
                    "Political bridge: law proposed by %s (%d confronts, threshold %d)",
                    faction,
                    len(events),
                    threshold,
                )

    except Exception as exc:
        logger.error("Error proposing laws: %s", exc)
        results["errors"].append(str(exc))

    # ── Propose treaties (with adaptive thresholds) ─────────────────────
    try:
        for pair_str, count in ally_pairs.items():
            threshold = _treaty_threshold(pair_str)
            if count >= threshold:
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
                        "threshold_used": threshold,
                        "description": f"Alliance proposed between {pair[0]} and {pair[1]} after {count} mutual aid events (threshold: {threshold})",
                        "strength": min(count / 10.0, 1.0),
                        "ts": int(ts),
                    }
                    # Write to pending_treaties (original path)
                    r.lpush("pending_treaties", json.dumps(treaty))
                    # ALSO write to faction_treaties_active so resolve_pending_items() processes it
                    treaty_key = f"{pair[0]}:{pair[1]}:alliance"
                    treaty_for_faction_ai = {
                        "type": "alliance",
                        "from": pair[0],
                        "to": pair[1],
                        "strength": treaty["strength"],
                        "ts": int(ts),
                        "status": "proposed",
                        "description": treaty["description"],
                        "source": "political_bridge",
                    }
                    r.hset(
                        "faction_treaties_active",
                        treaty_key,
                        json.dumps(treaty_for_faction_ai),
                    )
                    results["treaties_proposed"] += 1
                    logger.info(
                        "Political bridge: treaty proposed between %s and %s (%d aid events, threshold %d)",
                        pair[0],
                        pair[1],
                        count,
                        threshold,
                    )

    except Exception as exc:
        logger.error("Error proposing treaties: %s", exc)
        results["errors"].append(str(exc))

    # ── Research initiatives (unchanged logic) ──────────────────────────
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


def consume_pending_political_items() -> Dict:
    """
    Consume pending_laws, pending_treaties, and pending_research from Redis
    and apply their effects to the world state and faction systems.

    This is the MISSING PIPE that was causing Step 4 to produce 0 laws/treaties
    in practice — bridge_npc_events_to_political() was writing to pending_laws
    and pending_treaties, but nothing was reading them to apply effects.

    What this function does:
    1. RPOPLPUSH each item from pending_laws → applies morale/stability effects
       to Redis world state keys, then records the law in history and discards it.
    2. RPOPLPUSH each item from pending_treaties → applies alliance effects
       (diplomacy boost between factions), records in history, discards.
    3. RPOPLPUSH each item from pending_research → applies tech progress
       to the proposing faction, records in history, discards.

    Returns:
        Dict with keys: laws_applied, treaties_applied, research_applied, errors
    """
    r = _get_redis()
    now = int(time.time())

    results = {
        "laws_applied": 0,
        "treaties_applied": 0,
        "research_applied": 0,
        "errors": [],
    }

    # ── Consume pending_laws ────────────────────────────────────────────
    try:
        while True:
            raw = r.rpop("pending_laws")
            if not raw:
                break
            try:
                law = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            proposing = law.get("proposing_faction", "")
            targets = law.get("target_factions", [])
            severity = law.get("severity", 0.5)

            # Apply stability effect: proposing faction gains stability, targets lose
            try:
                current_stability = float(r.get("world:stability") or 60)
                r.set(
                    "world:stability",
                    str(round(current_stability + 0.02 * severity, 2)),
                )

                # Apply morale dip to target factions via faction_power
                for tf in targets:
                    power_key = f"faction_power:{tf}"
                    current_power = float(r.get(power_key) or 50)
                    r.set(power_key, str(round(current_power - 1.5 * severity, 2)))
            except Exception as exc:
                logger.error("Error applying law effects: %s", exc)
                results["errors"].append(str(exc))

            # Record in history for the timeline
            try:
                history_entry = {
                    "event_type": "law_enacted",
                    "proposing_faction": proposing,
                    "target_factions": targets,
                    "description": law.get("description", "Unknown law"),
                    "severity": severity,
                    "ts": now,
                    "source": "political_bridge",
                }
                r.zadd("npc_world_events", {json.dumps(history_entry): now})
            except Exception as exc:
                logger.error("Error recording law history: %s", exc)

            results["laws_applied"] += 1
            logger.info(
                "Consumed pending law from %s (severity %.2f)",
                proposing,
                severity,
            )

    except Exception as exc:
        logger.error("Error consuming pending laws: %s", exc)
        results["errors"].append(str(exc))

    # ── Consume pending_treaties ────────────────────────────────────────
    try:
        while True:
            raw = r.rpop("pending_treaties")
            if not raw:
                break
            try:
                treaty = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            factions = treaty.get("factions", [])
            strength = treaty.get("strength", 0.5)

            if len(factions) >= 2:
                # Apply diplomacy boost between the two factions
                try:
                    for f1, f2 in [(factions[0], factions[1])]:
                        stance_key = f"faction_stance:{f1}:{f2}"
                        current_stance = float(r.get(stance_key) or 0.5)
                        r.set(
                            stance_key,
                            str(round(min(current_stance + 0.1 * strength, 1.0), 2)),
                        )
                        # Reverse direction too
                        stance_key_rev = f"faction_stance:{f2}:{f1}"
                        current_stance_rev = float(r.get(stance_key_rev) or 0.5)
                        r.set(
                            stance_key_rev,
                            str(
                                round(min(current_stance_rev + 0.1 * strength, 1.0), 2)
                            ),
                        )
                except Exception as exc:
                    logger.error("Error applying treaty effects: %s", exc)
                    results["errors"].append(str(exc))

            # Record in history
            try:
                history_entry = {
                    "event_type": "treaty_signed",
                    "factions": factions,
                    "description": treaty.get("description", "Unknown treaty"),
                    "strength": strength,
                    "ts": now,
                    "source": "political_bridge",
                }
                r.zadd("npc_world_events", {json.dumps(history_entry): now})
            except Exception as exc:
                logger.error("Error recording treaty history: %s", exc)

            results["treaties_applied"] += 1
            logger.info(
                "Consumed pending treaty between %s (strength %.2f)",
                " & ".join(factions),
                strength,
            )

    except Exception as exc:
        logger.error("Error consuming pending treaties: %s", exc)
        results["errors"].append(str(exc))

    # ── Consume pending_research ────────────────────────────────────────
    try:
        while True:
            raw = r.rpop("pending_research")
            if not raw:
                break
            try:
                research = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            faction = research.get("proposing_faction", "independent")
            potential = research.get("potential", 0.5)

            # Apply tech progress to faction
            try:
                tech_key = f"faction_tech_progress:{faction}"
                current_progress = float(r.get(tech_key) or 0.0)
                r.set(tech_key, str(round(current_progress + potential * 5.0, 2)))

                # Also boost world technological_level slightly
                current_tech = float(r.get("world:technological_level") or 0.2)
                r.set(
                    "world:technological_level",
                    str(round(min(current_tech + 0.005 * potential, 1.0), 3)),
                )
            except Exception as exc:
                logger.error("Error applying research effects: %s", exc)
                results["errors"].append(str(exc))

            # Record in history
            try:
                history_entry = {
                    "event_type": "research_breakthrough",
                    "proposing_faction": faction,
                    "description": research.get("description", "Unknown research"),
                    "potential": potential,
                    "ts": now,
                    "source": "political_bridge",
                }
                r.zadd("npc_world_events", {json.dumps(history_entry): now})
            except Exception as exc:
                logger.error("Error recording research history: %s", exc)

            results["research_applied"] += 1
            logger.info(
                "Consumed pending research from %s (potential %.2f)",
                faction,
                potential,
            )

    except Exception as exc:
        logger.error("Error consuming pending research: %s", exc)
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


def evolve_npc_relationships(npc_list: List[Dict], r) -> int:
    """Evolve NPC-to-NPC relationships based on quests, faction voting, treaties, and decay.

    Steps:
        a) Quest completion effects — same-faction bond, cross-faction hostility
        b) Faction voting alignment — same vote = bond, different = friction
        c) Faction stance propagation — treaties = bond, conflicts = hostility
        d) Natural decay — all scores drift toward 50.0 (neutral)
        e) Persistence — write to npc_relationships:{char_id} HASH via pipeline

    Returns:
        Number of relationship pairs updated.
    """
    if not npc_list:
        return 0

    REL_KEY_PREFIX = "npc_relationships:"
    QUEST_KEY_PREFIX = "npc_quests:completed:"
    DECAY_TOWARD = 50.0
    DECAY_RATE = 0.02
    MIN_VAL = 0.0
    MAX_VAL = 100.0

    char_ids = [n["char_id"] for n in npc_list if n.get("char_id")]
    faction_map = {
        n["char_id"]: n.get("affiliation", "") for n in npc_list if n.get("char_id")
    }

    existing_rels: Dict[str, Dict[str, float]] = {}
    for cid in char_ids:
        raw = r.hgetall(f"{REL_KEY_PREFIX}{cid}")
        if raw:
            existing_rels[cid] = {k: float(v) for k, v in raw.items()}
        else:
            existing_rels[cid] = {}

    delta: Dict[str, Dict[str, float]] = {cid: {} for cid in char_ids}

    # a) Quest completion effects
    for npc in npc_list:
        cid = npc.get("char_id", "")
        faction = npc.get("affiliation", "")
        if not cid:
            continue
        try:
            completed_raw = r.lrange(f"{QUEST_KEY_PREFIX}{cid}", 0, 1)
            for entry in completed_raw:
                quest = json.loads(entry)
                qtype = quest.get("quest_type", "")
                qfaction = quest.get("faction_id", faction)
                for other_cid in char_ids:
                    if other_cid == cid:
                        continue
                    other_faction = faction_map.get(other_cid, "")
                    if other_faction == qfaction:
                        delta[cid].setdefault(other_cid, 0.0)
                        delta[cid][other_cid] += 0.1
                    elif qtype in ("confront_rival", "investigate"):
                        delta[cid].setdefault(other_cid, 0.0)
                        delta[cid][other_cid] -= 0.1
        except (json.JSONDecodeError, TypeError):
            pass

    # b) Faction voting alignment
    try:
        resolutions_raw = r.zrevrange("choice_resolutions", 0, 2)
        faction_votes_by_res: List[Dict[str, str]] = []
        for entry in resolutions_raw:
            res = json.loads(entry)
            fv = res.get("faction_votes", {})
            faction_choice: Dict[str, str] = {}
            for fid, fdata in fv.items():
                choice_id = (
                    fdata.get("choice_id", "") if isinstance(fdata, dict) else ""
                )
                if choice_id:
                    faction_choice[fid] = choice_id
            if faction_choice:
                faction_votes_by_res.append(faction_choice)
    except (json.JSONDecodeError, TypeError):
        faction_votes_by_res = []

    processed_pairs: set = set()
    for npc_a in npc_list:
        cid_a = npc_a.get("char_id", "")
        fac_a = npc_a.get("affiliation", "")
        if not cid_a or not fac_a:
            continue
        for npc_b in npc_list:
            cid_b = npc_b.get("char_id", "")
            fac_b = npc_b.get("affiliation", "")
            if not cid_b or not fac_b or cid_a == cid_b:
                continue
            pair_key = tuple(sorted([cid_a, cid_b]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)
            for fv_map in faction_votes_by_res:
                choice_a = fv_map.get(fac_a)
                choice_b = fv_map.get(fac_b)
                if choice_a and choice_b:
                    if choice_a == choice_b:
                        delta[cid_a].setdefault(cid_b, 0.0)
                        delta[cid_b].setdefault(cid_a, 0.0)
                        delta[cid_a][cid_b] += 0.15
                        delta[cid_b][cid_a] += 0.15
                    else:
                        delta[cid_a].setdefault(cid_b, 0.0)
                        delta[cid_b].setdefault(cid_a, 0.0)
                        delta[cid_a][cid_b] -= 0.05
                        delta[cid_b][cid_a] -= 0.05

    # c) Faction stance propagation
    treaties_raw = r.hgetall("faction_treaties_active") or {}
    treaty_pairs: set = set()
    for tkey in treaties_raw:
        parts = tkey.split(":")
        if len(parts) >= 2:
            treaty_pairs.add(tuple(sorted([parts[0], parts[1]])))

    conflict_pairs: set = set()
    try:
        conflicts_raw = r.zrevrange("faction_conflicts", 0, 49)
        for entry in conflicts_raw:
            cdata = json.loads(entry)
            fa = cdata.get("faction_a", "") or cdata.get("attacker", "")
            fb = cdata.get("faction_b", "") or cdata.get("defender", "")
            if fa and fb:
                conflict_pairs.add(tuple(sorted([fa, fb])))
    except (json.JSONDecodeError, TypeError):
        pass

    stance_processed: set = set()
    for npc_a in npc_list:
        cid_a = npc_a.get("char_id", "")
        fac_a = npc_a.get("affiliation", "")
        if not cid_a or not fac_a:
            continue
        for npc_b in npc_list:
            cid_b = npc_b.get("char_id", "")
            fac_b = npc_b.get("affiliation", "")
            if not cid_b or not fac_b or cid_a == cid_b:
                continue
            pair_key = tuple(sorted([cid_a, cid_b]))
            if pair_key in stance_processed:
                continue
            stance_processed.add(pair_key)
            fac_pair = tuple(sorted([fac_a, fac_b]))
            if fac_pair in treaty_pairs:
                delta[cid_a].setdefault(cid_b, 0.0)
                delta[cid_b].setdefault(cid_a, 0.0)
                delta[cid_a][cid_b] += 0.05
                delta[cid_b][cid_a] += 0.05
            if fac_pair in conflict_pairs:
                delta[cid_a].setdefault(cid_b, 0.0)
                delta[cid_b].setdefault(cid_a, 0.0)
                delta[cid_a][cid_b] -= 0.1
                delta[cid_b][cid_a] -= 0.1

    # d) Natural decay toward neutral
    for cid in char_ids:
        for target_id, current_val in existing_rels[cid].items():
            if target_id not in char_ids:
                continue
            if current_val > DECAY_TOWARD:
                delta[cid].setdefault(target_id, 0.0)
                delta[cid][target_id] -= DECAY_RATE
            elif current_val < DECAY_TOWARD:
                delta[cid].setdefault(target_id, 0.0)
                delta[cid][target_id] += DECAY_RATE

    # e) Persistence
    updated_pairs = 0
    pipe = r.pipeline(transaction=False)
    for cid in char_ids:
        rel_key = f"{REL_KEY_PREFIX}{cid}"
        merged = dict(existing_rels[cid])
        has_changes = False
        for target_id, d in delta[cid].items():
            if target_id not in char_ids:
                continue
            old = merged.get(target_id, DECAY_TOWARD)
            new_val = max(MIN_VAL, min(MAX_VAL, round(old + d, 2)))
            if (
                abs(new_val - DECAY_TOWARD) < 0.01
                and target_id not in existing_rels[cid]
            ):
                continue
            merged[target_id] = new_val
            pipe.hset(rel_key, target_id, str(new_val))
            has_changes = True
            updated_pairs += 1
        if has_changes:
            pipe.expire(rel_key, 604800)
    if updated_pairs > 0:
        pipe.execute()

    logger.info(
        "[Relationship Evolution] Updated %d relationship pairs across %d NPCs",
        updated_pairs,
        len(npc_list),
    )
    return updated_pairs




# P24b: Cross-Layer Relationship Bridge
# Treaty type -> NPC relationship impact weights
TREATY_IMPACT_WEIGHTS = {
    "military_alliance": {"sign": 3.0, "expire": -2.5, "reject": -1.5},
    "non_aggression_pact": {"sign": 1.5, "expire": -1.0, "reject": -0.5},
    "research_pact": {"sign": 1.0, "expire": -0.5, "reject": -0.3},
    "trade_agreement": {"sign": 0.8, "expire": -0.3, "reject": -0.2},
    "trade": {"sign": 0.8, "expire": -0.3, "reject": -0.2},
    "cultural_exchange": {"sign": 0.5, "expire": -0.2, "reject": -0.1},
}
THIRD_PARTY_RIPPLE_FRACTION = 0.25


def propagate_diplomacy_events_to_npcs(
    r, diplomacy_result: Dict[str, Any], npc_list: List[Dict]
) -> Dict[str, Any]:
    """P24b: Propagate faction diplomacy events to NPC relationships.
    Event-driven shock that complements Step 7.5(c) passive drift.
    Called after Step 8.5 in autonomous_tick().
    """
    bridge_result = {"impacts_applied": 0, "events_processed": 0}

    # Build faction -> [char_id] mapping
    faction_members = {}
    faction_ideologies = {}
    for npc in npc_list:
        cid = npc.get("char_id", "")
        fid = npc.get("affiliation", "")
        if cid and fid:
            faction_members.setdefault(fid, []).append(cid)
            faction_ideologies[fid] = npc.get("ideology", "diplomatic")

    if len(faction_members) < 2:
        logger.warning(
            "[Diplomacy->NPC Bridge] Insufficient faction members: %d factions, %d total NPCs",
            len(faction_members), len(npc_list),
        )
        return bridge_result
    
    logger.info(
        "[Diplomacy->NPC Bridge] Faction members map: %s",
        {fid: len(members) for fid, members in faction_members.items()},
    )

    # Collect all diplomacy events
    events = []

    # Accepted proposals (treaty signed)
    for proposal in diplomacy_result.get("proposals", []):
        fac_a = proposal.get("faction_a", "")
        fac_b = proposal.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = proposal.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = proposal.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "sign",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    # Expirations (treaty expired)
    for exp in diplomacy_result.get("expirations", []):
        fac_a = exp.get("faction_a", "")
        fac_b = exp.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = exp.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = exp.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "expire",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    # Rejections (proposal rejected)
    for rej in diplomacy_result.get("rejections", []):
        fac_a = rej.get("faction_a", "")
        fac_b = rej.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = rej.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = rej.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "reject",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    if not events:
        logger.info(
            "[Diplomacy->NPC Bridge] No events to process. diplo_result keys: %s, proposals: %d, expirations: %d, rejections: %d",
            list(diplomacy_result.keys()) if isinstance(diplomacy_result, dict) else type(diplomacy_result).__name__,
            len(diplomacy_result.get("proposals", [])) if isinstance(diplomacy_result, dict) else -1,
            len(diplomacy_result.get("expirations", [])) if isinstance(diplomacy_result, dict) else -1,
            len(diplomacy_result.get("rejections", [])) if isinstance(diplomacy_result, dict) else -1,
        )
        return bridge_result
    
    logger.info(
        "[Diplomacy->NPC Bridge] Processing %d events: %s",
        len(events),
        [f"{e['type']}:{e['faction_a']}-{e['faction_b']}:{e['treaty_type']}" for e in events],
    )

    bridge_result["events_processed"] = len(events)

    # Apply impacts to NPC relationships
    impact_delta = {}  # char_id -> {target_id -> delta}

    for event in events:
        event_type = event["type"]
        fac_a = event["faction_a"]
        fac_b = event["faction_b"]
        treaty_type = event["treaty_type"]

        weights = TREATY_IMPACT_WEIGHTS.get(
            treaty_type, TREATY_IMPACT_WEIGHTS["cultural_exchange"]
        )
        delta_val = weights.get(event_type, 0.0)

        if delta_val == 0.0:
            continue

        # Primary impact: members of the two involved factions
        members_a = faction_members.get(fac_a, [])
        members_b = faction_members.get(fac_b, [])

        for cid_a in members_a:
            for cid_b in members_b:
                if cid_a == cid_b:
                    continue
                impact_delta.setdefault(cid_a, {}).setdefault(cid_b, 0.0)
                impact_delta[cid_a][cid_b] += delta_val
                impact_delta.setdefault(cid_b, {}).setdefault(cid_a, 0.0)
                impact_delta[cid_b][cid_a] += delta_val

        # Third-party ripple: NPCs in OTHER factions
        ideo_a = faction_ideologies.get(fac_a, "diplomatic")
        ideo_b = faction_ideologies.get(fac_b, "diplomatic")

        for other_fid, other_members in faction_members.items():
            if other_fid in (fac_a, fac_b):
                continue
            ideo_other = faction_ideologies.get(other_fid, "diplomatic")

            aff_a = FACTION_IDEOLOGY_AFFINITY.get(
                tuple(sorted([ideo_a, ideo_other])), 0.0
            )
            aff_b = FACTION_IDEOLOGY_AFFINITY.get(
                tuple(sorted([ideo_b, ideo_other])), 0.0
            )

            for cid_other in other_members:
                for cid_a in members_a:
                    if aff_a < 0:
                        ripple = -1.0 * delta_val * THIRD_PARTY_RIPPLE_FRACTION * abs(aff_a)
                        impact_delta.setdefault(cid_other, {}).setdefault(cid_a, 0.0)
                        impact_delta[cid_other][cid_a] += ripple
                        impact_delta.setdefault(cid_a, {}).setdefault(cid_other, 0.0)
                        impact_delta[cid_a][cid_other] += ripple

                for cid_b in members_b:
                    if aff_b < 0:
                        ripple = -1.0 * delta_val * THIRD_PARTY_RIPPLE_FRACTION * abs(aff_b)
                        impact_delta.setdefault(cid_other, {}).setdefault(cid_b, 0.0)
                        impact_delta[cid_other][cid_b] += ripple
                        impact_delta.setdefault(cid_b, {}).setdefault(cid_other, 0.0)
                        impact_delta[cid_b][cid_other] += ripple

    # Write to Redis in batch
    if impact_delta:
        pipe = r.pipeline()
        for cid, targets in impact_delta.items():
            rel_key = f"npc_relationships:{cid}"
            current_rels = r.hgetall(rel_key) or {}
            updates = {}
            for target_id, delta in targets.items():
                current = float(current_rels.get(target_id, 50.0))
                if isinstance(current, bytes):
                    current = float(current.decode())
                new_val = max(0.0, min(100.0, current + delta))
                updates[target_id] = str(round(new_val, 2))
            if updates:
                pipe.hmset(rel_key, updates)
                bridge_result["impacts_applied"] += len(updates)
        pipe.execute()

    logger.info(
        "[Diplomacy->NPC Bridge] %d events -> %d NPC relationship impacts",
        len(events), bridge_result["impacts_applied"],
    )
    return bridge_result

def autonomous_tick(npc_list: List[Dict], tick_decisions: List[Dict]) -> Dict:
    """
    THE MASTER FUNCTION. Runs all simulation subsystems in the correct
    cross-pollination order:

    1. Wire faction context into NPC decisions
    1.5. LLM Cognition — leaders/specialists get LLM reasoning (if available)
         LLM proposals are injected into tick_decisions before Step 2
    2. Execute NPC decisions with concrete effects
    3. Bridge world state to game state
    4. Bridge NPC events to political engine
    5. Check era advancement
    6. Generate and apply game events
    7. NPC autonomous quest progression
    8. Faction autonomous tech research
    9. Narration — generate dramatic prose summarizing the tick (if available)

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
        "step1_5_cognition": {},
        "step2_decision_effects": {},
        "step3_game_state_bridge": {},
        "step4_political_bridge": {},
        "step4b_consume_pending": {},
        "step5_era_check": {},
        "step9_5_memory_harvest": {},
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

    # Step 1.5: LLM Cognition — leaders and specialists get LLM reasoning
    # if triggered events demand it. LLM proposals are merged into
    # tick_decisions BEFORE Step 2 executes them.
    # "LLMs PROPOSE, deterministic engine DISPOSES."
    world_state = None
    if COGNITION_AVAILABLE:
        try:
            step_start = time.time()
            world_state = _read_world_state(r)
            cog_result = run_cognition(npc_list, world_state)
            result["step1_5_cognition"] = cog_result
            result["step1_5_cognition"]["duration_ms"] = round(
                (time.time() - step_start) * 1000, 1
            )
            # Merge LLM proposals into tick_decisions so Step 2 executes them
            llm_decisions = cog_result.get("decisions", [])
            if llm_decisions:
                tick_decisions.extend(llm_decisions)
                logger.info(
                    "Cognition injected %d LLM decisions into tick pipeline",
                    len(llm_decisions),
                )
        except Exception as exc:
            logger.error("Step 1.5 (LLM cognition) failed: %s", exc)
            result["step1_5_cognition"] = {"errors": [str(exc)]}
            result["errors"].append(f"step1_5: {exc}")
    else:
        result["step1_5_cognition"] = {"status": "unavailable", "skipped": True}

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

    # Step 4b: Consume pending political items (apply effects)
    try:
        step_start = time.time()
        result["step4b_consume_pending"] = consume_pending_political_items()
        result["step4b_consume_pending"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 4b (consume pending political) failed: %s", exc)
        result["step4b_consume_pending"] = {"errors": [str(exc)]}
        result["errors"].append(f"step4b: {exc}")

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

    # Step 6: Generate and apply game events
    try:
        result["step6_game_events"] = generate_and_apply_events(max_events=3)
    except Exception as exc:
        logger.error("Game events step failed: %s", exc)
        result["step6_game_events"] = {"error": str(exc)}
        result["errors"].append(f"game_events: {exc}")

    # Step 7: NPC autonomous quest progression
    try:
        step_start = time.time()
        quest_engine = _get_quest_engine(r)
        result["step7_npc_quests"] = quest_engine.tick_npc_quests(npc_list)
        result["step7_npc_quests"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 7 (NPC quest tick) failed: %s", exc)
        result["step7_npc_quests"] = {"errors": [str(exc)]}
        result["errors"].append(f"step7: {exc}")

    # Step 7.5: Evolve NPC relationships
    try:
        step_start = time.time()
        rel_count = evolve_npc_relationships(npc_list, r)
        result["step7_5_relationship_evolution"] = {
            "pairs_updated": rel_count,
            "duration_ms": round((time.time() - step_start) * 1000, 1),
        }
        logger.info(
            "[Tick Step 7.5] Relationship evolution: %d pairs updated", rel_count
        )
    except Exception as exc:
        logger.error("Step 7.5 (relationship evolution) failed: %s", exc)
        result["step7_5_relationship_evolution"] = {"errors": [str(exc)]}
        result["errors"].append(f"step7_5: {exc}")

    # Step 8: Faction autonomous tech research
    try:
        step_start = time.time()
        tech_bridge = _get_tech_bridge(r)
        faction_data = {}
        for fid, ideology in FACTION_IDEOLOGY.items():
            power_raw = r.get(f"faction_power:{fid}")
            power = float(power_raw) if power_raw else 50.0
            fd_raw = r.hgetall(f"faction_dynamics")
            influence = 0.5
            try:
                fd_key = f"{fid}_influence"
                if fd_key in (fd_raw or {}):
                    influence = float(fd_raw[fd_key])
            except (ValueError, TypeError):
                pass
            faction_data[fid] = {
                "ideology": ideology,
                "power": power,
                "influence": influence,
            }
        result["step8_faction_tech"] = tech_bridge.tick_faction_research(faction_data)
        result["step8_faction_tech"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 8 (faction tech research) failed: %s", exc)
        result["step8_faction_tech"] = {"errors": [str(exc)]}
        result["errors"].append(f"step8: {exc}")

    # Step 8.5: Faction diplomacy cycle
    try:
        step_start = time.time()
        diplomacy_engine = _get_diplomacy_engine(r)
        if world_state is None:
            world_state = _read_world_state(r)
        result["step8_5_diplomacy"] = diplomacy_engine.run_diplomacy_cycle(
            r, world_state
        )
        result["step8_5_diplomacy"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 8.5 (faction diplomacy) failed: %s", exc)
        result["step8_5_diplomacy"] = {"errors": [str(exc)]}
        result["errors"].append(f"step8_5: {exc}")


    # Step 8.6: Cross-Layer Relationship Bridge (P24b)
    # Propagate diplomacy events to NPC relationships
    try:
        step_start = time.time()
        diplo_result = result.get('step8_5_diplomacy', {})
        bridge_result = propagate_diplomacy_events_to_npcs(
            r, diplo_result, npc_list
        )
        result["step8_6_diplomacy_bridge"] = bridge_result
        result["step8_6_diplomacy_bridge"]["duration_ms"] = round(
            (time.time() - step_start) * 1000, 1
        )
    except Exception as exc:
        logger.error("Step 8.6 (diplomacy->NPC bridge) failed: %s", exc)
        result['step8_6_diplomacy_bridge'] = {'errors': [str(exc)]}
        result["errors"].append(f"step8_6: {exc}")


    # Step 9: Narration — generate dramatic prose summarizing this tick
    # Runs AFTER all world state changes so it can narrate what actually happened.
    # Has built-in cooldown (120s) and deterministic fallback if LLM is down.
    if NARRATOR_AVAILABLE:
        try:
            step_start = time.time()
            world_state = _read_world_state(r)
            # Collect faction actions from Step 4 if available
            faction_actions = []
            try:
                pol_bridge = result.get("step4_political_bridge", {})
                faction_actions = pol_bridge.get("faction_actions", [])
            except Exception:
                pass
            # Collect cascade events from Step 6 if available
            cascade_events = []
            try:
                game_events = result.get("step6_game_events", {})
                cascade_events = game_events.get(
                    "events", game_events.get("applied_events", [])
                )
            except Exception:
                pass
            narration = generate_narration(
                world_state=world_state,
                tick_decisions=tick_decisions,
                faction_actions=faction_actions,
                cascade_events=cascade_events,
            )
            result["step9_narration"] = narration
            result["step9_narration"]["duration_ms"] = round(
                (time.time() - step_start) * 1000, 1
            )
        except Exception as exc:
            logger.error("Step 9 (narration) failed: %s", exc)
            result["step9_narration"] = {"errors": [str(exc)]}
            result["errors"].append(f"step9: {exc}")
    else:
        result["step9_narration"] = {"status": "unavailable", "skipped": True}

    # ── Step 9.5: NPC Memory Harvest ──
    if NPC_MEMORY_AVAILABLE:
        try:
            step_start = time.time()
            result["step9_5_memory_harvest"] = harvest_tick_memories(
                npc_list, tick_decisions, tick_ts
            )
            result["step9_5_memory_harvest"]["duration_ms"] = round(
                (time.time() - step_start) * 1000, 1
            )
        except Exception as exc:
            logger.error("Step 9.5 (memory harvest) failed: %s", exc)
            result["step9_5_memory_harvest"] = {"errors": [str(exc)]}
            result["errors"].append(f"step9_5: {exc}")
    else:
        result["step9_5_memory_harvest"] = {"status": "unavailable", "skipped": True}

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
            "laws_applied": result["step4b_consume_pending"].get("laws_applied", 0),
            "treaties_applied": result["step4b_consume_pending"].get(
                "treaties_applied", 0
            ),
            "research_applied": result["step4b_consume_pending"].get(
                "research_applied", 0
            ),
            "era_recommendation": result["step5_era_check"].get("recommended_era", ""),
            "quests_completed": result.get("step7_npc_quests", {}).get(
                "quests_completed", 0
            ),
            "quests_accepted": result.get("step7_npc_quests", {}).get(
                "quests_accepted", 0
            ),
            "quests_abandoned": result.get("step7_npc_quests", {}).get(
                "quests_abandoned", 0
            ),
            "techs_completed": result.get("step8_faction_tech", {}).get(
                "techs_completed", 0
            ),
            "techs_researching": result.get("step8_faction_tech", {}).get(
                "research_advanced", 0
            ),
            "diplomacy_proposals": result.get("step8_5_diplomacy", {})
            .get("proposals", [])
            .__len__(),
            "diplomacy_expirations": result.get("step8_5_diplomacy", {})
            .get("expirations", [])
            .__len__(),
        "diplomacy_bridge_impacts": result.get("step8_6_diplomacy_bridge", {})
            .get("impacts_applied", 0),
            "cognition_leaders": result.get("step1_5_cognition", {}).get(
                "leaders_cognized", 0
            ),
            "cognition_specialists": result.get("step1_5_cognition", {}).get(
                "specialists_cognized", 0
            ),
            "cognition_triggers": result.get("step1_5_cognition", {}).get(
                "triggers_detected", 0
            ),
            "narration_source": result.get("step9_narration", {}).get(
                "source", "unavailable"
            ),
            "narration_headline": result.get("step9_narration", {}).get("headline", "")[
                :80
            ],
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
        "Autonomous tick %d complete: %d effects, %d laws, %d treaties, %dms, %d errors",
        tick_ts,
        result["step2_decision_effects"].get("effects_applied", 0),
        result.get("step4b_consume_pending", {}).get("laws_applied", 0),
        result.get("step4b_consume_pending", {}).get("treaties_applied", 0),
        result["duration_ms"],
        len(result["errors"]),
    )

    return result
