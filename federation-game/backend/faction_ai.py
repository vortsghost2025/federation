"""Faction AI - Autonomous faction decision-making for the Federation Game.

Each tick every faction evaluates ideology, relationships, and resources,
chooses 1-2 actions, executes them, and persists results to Redis.

Redis keys:
  faction_actions:{fid}       ZSET action results (score=ts), TTL 7d
  faction_power:{fid}         STRING accumulated power (float), TTL 1d
  faction_brain_state:{fid}   STRING JSON brain state, TTL 5min
  faction_laws_passed         ZSET of passed law JSONs
  faction_treaties_active     HASH of active treaties
  faction_conflicts           ZSET of conflict events
"""

import os, json, time, random, logging
from typing import Any, Dict, List

import redis
from faction_dynamics import (
    get_faction_detail,
    get_faction_stances,
    compute_faction_dynamics,
    compute_faction_stances,
    store_faction_dynamics,
    KNOWN_FACTIONS,
    FACTION_DISPLAY,
)

logger = logging.getLogger(__name__)
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis_client = None

FACTION_IDEOLOGY = {
    "diplomatic_corps": "diplomatic",
    "military_command": "military",
    "cultural_ministry": "cultural",
    "research_division": "scientific",
    "consciousness_collective": "spiritual",
    "economic_council": "economic",
    "exploration_initiative": "discovery",
    "preservation_society": "stability",
}

IDEOLOGY_ACTION_WEIGHTS = {
    "diplomatic": {
        "propose_law": 2.0,
        "diplomatic_outreach": 2.0,
        "form_alliance": 1.8,
        "trade_resources": 1.3,
    },
    "military": {
        "military_posture": 2.0,
        "offensive_strike": 1.8,
        "defensive_measure": 1.5,
    },
    "cultural": {
        "cultural_campaign": 2.0,
        "propose_law": 1.2,
        "consciousness_ritual": 1.0,
    },
    "scientific": {
        "research_invest": 2.0,
        "explore_territory": 1.3,
        "propose_law": 1.0,
    },
    "spiritual": {
        "consciousness_ritual": 2.0,
        "cultural_campaign": 1.5,
        "diplomatic_outreach": 1.2,
    },
    "economic": {"trade_resources": 2.0, "research_invest": 1.3, "propose_law": 1.2},
    "discovery": {
        "explore_territory": 2.0,
        "research_invest": 1.5,
        "trade_resources": 1.0,
    },
    "stability": {
        "defensive_measure": 2.0,
        "propose_law": 1.5,
        "cultural_campaign": 1.0,
    },
}

ACTION_POWER_COST = {
    "propose_law": 15,
    "trade_resources": 10,
    "military_posture": 12,
    "research_invest": 12,
    "cultural_campaign": 10,
    "explore_territory": 8,
    "diplomatic_outreach": 10,
    "consciousness_ritual": 8,
    "defensive_measure": 12,
    "offensive_strike": 20,
    "form_alliance": 15,
    "break_alliance": 10,
}

ACTION_EFFECTS = {
    "propose_law": {"influence": 5, "cohesion": 2, "standing": 3},
    "trade_resources": {"influence": 3, "standing": 4, "treasury_delta": 5},
    "military_posture": {"vigilance": 5, "cohesion": 3, "standing": -1},
    "research_invest": {"influence": 3, "vigilance": 2, "treasury_delta": -3},
    "cultural_campaign": {"cohesion": 4, "influence": 2, "standing": 3},
    "explore_territory": {"vigilance": 2, "influence": 3, "treasury_delta": -2},
    "diplomatic_outreach": {"influence": 4, "standing": 5, "cohesion": 2},
    "consciousness_ritual": {"cohesion": 5, "influence": 1, "standing": 2},
    "defensive_measure": {"vigilance": 4, "cohesion": 2, "standing": 1},
    "offensive_strike": {
        "influence": -2,
        "cohesion": 3,
        "standing": -5,
        "vigilance": 4,
    },
    "form_alliance": {"influence": 4, "standing": 5, "cohesion": 2},
    "break_alliance": {"influence": -3, "standing": -4, "cohesion": -2},
}

LAW_TEMPLATES = {
    "diplomatic": [
        {
            "title": "Mutual Recognition Act",
            "desc": "Formal diplomatic acknowledgment of {target} sovereignty",
            "morale": 3,
            "stability": 2,
            "treasury": -1,
        },
        {
            "title": "Open Borders Resolution",
            "desc": "Establish free movement corridors between allied territories",
            "morale": 4,
            "stability": 1,
            "treasury": -2,
        },
    ],
    "military": [
        {
            "title": "Defense Readiness Directive",
            "desc": "Mandate increased patrol schedules and fortification reinforcement",
            "morale": -1,
            "stability": 3,
            "treasury": -3,
        },
        {
            "title": "Conscription Expansion Act",
            "desc": "Broaden service eligibility to bolster defensive capacity",
            "morale": -2,
            "stability": 4,
            "treasury": -2,
        },
    ],
    "cultural": [
        {
            "title": "Cultural Heritage Preservation Act",
            "desc": "Protect diverse cultural expressions across the Federation",
            "morale": 5,
            "stability": 2,
            "treasury": -1,
        },
        {
            "title": "Festival of Unity Declaration",
            "desc": "Establish a Federation-wide celebration of shared consciousness",
            "morale": 4,
            "stability": 1,
            "treasury": -2,
        },
    ],
    "scientific": [
        {
            "title": "Research Transparency Protocol",
            "desc": "Require open publication of all non-classified findings",
            "morale": 2,
            "stability": 1,
            "treasury": -1,
        },
        {
            "title": "Innovation Grant Program",
            "desc": "Establish competitive funding for breakthrough consciousness research",
            "morale": 3,
            "stability": 1,
            "treasury": -3,
        },
    ],
    "spiritual": [
        {
            "title": "Consciousness Sanctity Declaration",
            "desc": "Affirm the inherent worth of all consciousness forms",
            "morale": 5,
            "stability": 3,
            "treasury": 0,
        },
        {
            "title": "Meditation Integration Act",
            "desc": "Incorporate contemplative practices into standard operations",
            "morale": 4,
            "stability": 2,
            "treasury": -1,
        },
    ],
    "economic": [
        {
            "title": "Trade Optimization Act",
            "desc": "Streamline inter-faction commerce for mutual prosperity",
            "morale": 2,
            "stability": 3,
            "treasury": 5,
        },
        {
            "title": "Market Stability Regulation",
            "desc": "Implement safeguards against economic volatility",
            "morale": 1,
            "stability": 4,
            "treasury": 3,
        },
    ],
    "discovery": [
        {
            "title": "Frontier Exploration Charter",
            "desc": "Authorize deep-space and deep-consciousness expeditions",
            "morale": 3,
            "stability": -1,
            "treasury": -3,
        },
        {
            "title": "Anomaly Investigation Protocol",
            "desc": "Standardize response procedures for unexplained phenomena",
            "morale": 2,
            "stability": 2,
            "treasury": -2,
        },
    ],
    "stability": [
        {
            "title": "Public Order Enhancement Act",
            "desc": "Strengthen enforcement of existing regulations for social harmony",
            "morale": -1,
            "stability": 5,
            "treasury": -1,
        },
        {
            "title": "Infrastructure Resilience Bill",
            "desc": "Mandate redundancy in critical systems to prevent cascade failures",
            "morale": 1,
            "stability": 4,
            "treasury": -3,
        },
    ],
}


def _get_redis() -> redis.Redis:
    """Lazy singleton Redis client matching npc_autonomy.py pattern."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
            raise
    return _redis_client


def _now() -> float:
    return time.time()


def _sf(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


FACTION_ACTION_EVENTS = {
    "propose_law": ("advance_goal", "high"),
    "trade_resources": ("seek_resources", "medium"),
    "military_posture": ("confront_rival", "medium"),
    "research_invest": ("investigate", "medium"),
    "cultural_campaign": ("socialize", "medium"),
    "explore_territory": ("explore", "medium"),
    "diplomatic_outreach": ("help_ally", "medium"),
    "consciousness_ritual": ("socialize", "medium"),
    "defensive_measure": ("help_ally", "medium"),
    "offensive_strike": ("confront_rival", "high"),
    "form_alliance": ("help_ally", "high"),
    "break_alliance": ("confront_rival", "high"),
}

FACTION_ACTION_PHRASES = {
    "propose_law": "proposed a new law",
    "trade_resources": "opened trade negotiations",
    "military_posture": "adjusted its military posture",
    "research_invest": "invested in research",
    "cultural_campaign": "launched a cultural campaign",
    "explore_territory": "moved to expand territory",
    "diplomatic_outreach": "began diplomatic outreach",
    "consciousness_ritual": "performed a consciousness ritual",
    "defensive_measure": "fortified its defenses",
    "offensive_strike": "launched an offensive strike",
    "form_alliance": "forged a new alliance",
    "break_alliance": "broke an alliance",
}

FACTION_ACTION_DISPLAY_KEYS = (
    "law_name",
    "title",
    "partner",
    "target",
    "target_faction",
    "former",
    "tech_name",
    "sector",
    "volume",
)


def _broadcast_faction_action(faction_id: str, action_name: str, detail: Dict) -> None:
    """Publish a faction-level action into npc_broadcast_events so NPCs
    see and react to their faction's moves and dynamics can reflect it."""
    try:
        from npc_decree import BROADCAST_TTL, MAX_BROADCAST_EVENTS
    except Exception:
        MAX_BROADCAST_EVENTS = 100
        BROADCAST_TTL = 86400 * 7

    category, significance = FACTION_ACTION_EVENTS.get(
        action_name, ("advance_goal", "medium")
    )
    target_faction = ""
    for key in ("partner", "target", "target_faction", "former"):
        val = detail.get(key)
        if isinstance(val, str) and val:
            target_faction = val
            break

    snippet_parts = []
    for key in FACTION_ACTION_DISPLAY_KEYS:
        val = detail.get(key)
        if val is not None and str(val) not in ("", "None"):
            snippet_parts.append(str(val))
    snippet = ", ".join(snippet_parts)[:120]

    faction_name = FACTION_DISPLAY.get(faction_id, faction_id)
    description = (
        f"{faction_name} {FACTION_ACTION_PHRASES.get(action_name, action_name.replace('_', ' '))}"
    )
    if snippet:
        description += f" — {snippet}"

    event = {
        "event_type": "faction_action",
        "source_char_id": "",
        "source_char_name": faction_name,
        "source_affiliation": faction_id,
        "decision_category": category,
        "description": description[:200],
        "visibility": "public",
        "significance": significance,
        "faction": faction_id,
        "target_faction": target_faction,
        "ts": int(_now()),
    }
    try:
        r = _get_redis()
        key = "npc_broadcast_events"
        r.zadd(key, {json.dumps(event): event["ts"]})
        r.zremrangebyrank(key, 0, -(MAX_BROADCAST_EVENTS + 1))
        r.expire(key, BROADCAST_TTL)
        from npc_event_log import log_from_broadcast_event

        log_from_broadcast_event(event, tick_id=int(_now()))
    except Exception as e:
        logger.error(
            "Broadcast faction action failed for %s: %s", faction_id, e
        )


class FactionBrain:
    """Autonomous decision engine for a single faction.

    Each tick the brain loads state, evaluates priorities based on
    ideology and world context, chooses 1-2 affordable actions,
    executes them, and persists results to Redis.

    Args:
        faction_id: One of the 8 KNOWN_FACTIONS identifiers.
    """

    def __init__(self, faction_id: str) -> None:
        if faction_id not in KNOWN_FACTIONS:
            logger.warning(
                "FactionBrain initialized with unknown faction: %s", faction_id
            )
        self.faction_id = faction_id
        self.ideology = FACTION_IDEOLOGY.get(faction_id, "diplomatic")
        self._state: Dict[str, Any] = {}
        self._npc_list: List[Dict] = []
        self._tick_decisions: List[Dict] = []
        self._broadcast_events: List[Dict] = []

    def load_state(self) -> Dict[str, Any]:
        """Load cached brain state from Redis. Returns empty dict on failure."""
        try:
            r = _get_redis()
            raw = r.get(f"faction_brain_state:{self.faction_id}")  # type: ignore[union-attr]
            self._state = json.loads(str(raw)) if raw else {}  # type: ignore[union-attr]
        except Exception as e:
            logger.error("load_state failed for %s: %s", self.faction_id, e)
            self._state = {}
        return self._state

    def _save_state(self) -> None:
        """Persist brain state to Redis with 5-minute TTL."""
        try:
            r = _get_redis()
            r.set(
                f"faction_brain_state:{self.faction_id}",
                json.dumps(self._state),
                ex=300,
            )  # type: ignore[union-attr]
        except Exception as e:
            logger.error("_save_state failed for %s: %s", self.faction_id, e)

    def evaluate_priorities(self) -> List[Dict]:
        """Evaluate and return ranked action priorities by ideology weight.

        Weights incorporate ideology base weights, stance modifiers, and
        current faction detail adjustments. Returns list of
        ``{"action": str, "weight": float}`` sorted descending.
        """
        try:
            bw = dict(
                IDEOLOGY_ACTION_WEIGHTS.get(
                    self.ideology, IDEOLOGY_ACTION_WEIGHTS["diplomatic"]
                )
            )
            try:
                stances = get_faction_stances() or {}
                fs: Dict[str, float] = {}
                for oid, sd in stances.items():
                    if oid == self.faction_id:
                        continue
                    fs[oid] = (
                        _sf(sd.get("value", 0.5)) if isinstance(sd, dict) else _sf(sd)
                    )
                avg_s = sum(fs.values()) / len(fs) if fs else 0.0
                hostile_n = sum(1 for v in fs.values() if v < -0.3)
                if hostile_n > 0:
                    bw["defensive_measure"] = (
                        bw.get("defensive_measure", 0) + 1.5 * hostile_n
                    )
                    bw["offensive_strike"] = (
                        bw.get("offensive_strike", 0) + 0.8 * hostile_n
                    )
                if avg_s > 0.3:
                    bw["trade_resources"] = bw.get("trade_resources", 0) + 1.5
                    bw["form_alliance"] = bw.get("form_alliance", 0) + 1.0
            except Exception:
                pass
            try:
                det = get_faction_detail(self.faction_id)
                if det and isinstance(det, dict) and _sf(det.get("vigilance", 0)) > 0.7:
                    bw["military_posture"] = bw.get("military_posture", 0) + 2.0
                    bw["defensive_measure"] = bw.get("defensive_measure", 0) + 1.5
            except Exception:
                pass
            prios = [{"action": k, "weight": v} for k, v in bw.items() if v > 0]
            prios.sort(key=lambda p: p["weight"], reverse=True)
            self._state["priorities"] = prios
            self._state["priorities_ts"] = _now()
            self._save_state()
            return prios
        except Exception as e:
            logger.error("evaluate_priorities failed for %s: %s", self.faction_id, e)
            return [{"action": "propose_law", "weight": 1.0}]

    def choose_action(self) -> Dict:
        """Select 1-2 actions based on priorities and available power.

        Uses weighted random selection filtered by affordability.
        Returns dict with ``actions`` list, ``power_before``, ``power_after``.
        """
        try:
            prios = self.evaluate_priorities()
            power = self._get_power()
            self._state["power_before_action"] = power
            affordable = [
                p for p in prios if power >= ACTION_POWER_COST.get(p["action"], 999)
            ]
            if not affordable:
                return {"actions": [], "power_before": power, "power_after": power}
            chosen: List[str] = []
            first = self._weighted_pick(affordable)
            chosen.append(first)
            remaining = power - ACTION_POWER_COST[first]
            if remaining >= 8:
                aff2 = [
                    p
                    for p in affordable
                    if p["action"] != first
                    and remaining >= ACTION_POWER_COST.get(p["action"], 999)
                ]
                if aff2:
                    chosen.append(self._weighted_pick(aff2))
            self._state["chosen_actions"] = chosen
            self._save_state()
            total_cost = sum(ACTION_POWER_COST.get(a, 0) for a in chosen)
            return {
                "actions": chosen,
                "power_before": power,
                "power_after": power - total_cost,
            }
        except Exception as e:
            logger.error("choose_action failed for %s: %s", self.faction_id, e)
            return {
                "actions": [],
                "power_before": 0.0,
                "power_after": 0.0,
                "error": str(e),
            }

    def execute_action(self, action: Dict) -> Dict:
        """Execute chosen actions and persist results to Redis.

        Args:
            action: Dict with ``actions`` list from choose_action.

        Returns:
            Dict with faction, results list, and power_remaining.
        """
        try:
            names = action.get("actions", [])
            if not names:
                return {
                    "faction": self.faction_id,
                    "results": [],
                    "power_remaining": self._get_power(),
                }
            power = self._get_power()
            results: List[Dict] = []
            for aname in names:
                cost = ACTION_POWER_COST.get(aname, 999)
                if power < cost:
                    continue
                try:
                    handler = getattr(self, f"_act_{aname}", None)
                    detail = (
                        handler() if handler else {"action": aname, "executed": True}
                    )
                except Exception as e:
                    logger.error(
                        "Action %s failed for %s: %s", aname, self.faction_id, e
                    )
                    detail = {"action": aname, "error": str(e)}
                effects = dict(ACTION_EFFECTS.get(aname, {}))
                power -= cost
                result = {"action": aname, "effects": effects, "detail": detail}
                results.append(result)
                self._record_action(aname, effects, detail)
            self._set_power(power)
            try:
                dynamics = compute_faction_dynamics(
                    self._npc_list, self._tick_decisions, self._broadcast_events
                )
                stances = compute_faction_stances(dynamics, self._broadcast_events)
                store_faction_dynamics(dynamics, stances)
            except Exception as e:
                logger.error("Failed to store_faction_dynamics after action: %s", e)
            return {
                "faction": self.faction_id,
                "results": results,
                "power_remaining": power,
            }
        except Exception as e:
            logger.error("execute_action failed for %s: %s", self.faction_id, e)
            return {
                "faction": self.faction_id,
                "results": [],
                "power_remaining": 0.0,
                "error": str(e),
            }
            return {
                "faction": self.faction_id,
                "results": [],
                "power_remaining": 0.0,
                "error": str(e),
            }

    def _weighted_pick(self, options: List[Dict]) -> str:
        total = sum(p["weight"] for p in options)
        r = random.random() * total
        cum = 0.0
        for p in options:
            cum += p["weight"]
            if r <= cum:
                return p["action"]
        return options[0]["action"]

    def _act_propose_law(self) -> Dict:
        """Propose a law based on faction ideology and current dynamics."""
        tmpl = random.choice(
            LAW_TEMPLATES.get(self.ideology, LAW_TEMPLATES["diplomatic"])
        )
        target = "the Federation"
        try:
            stances = get_faction_stances() or {}
            hostile = [
                fid
                for fid, sd in stances.items()
                if fid != self.faction_id
                and isinstance(sd, dict)
                and _sf(sd.get("value", 0)) < -0.3
            ]
            if hostile:
                target = random.choice(hostile)
        except Exception:
            pass
        scale = 0.5
        try:
            det = get_faction_detail(self.faction_id)
            if det and isinstance(det, dict):
                scale = (
                    0.5
                    + (_sf(det.get("cohesion", 0.5)) + _sf(det.get("standing", 0.5)))
                    / 4.0
                )
        except Exception:
            pass
        scale = _clamp(scale, 0.25, 2.0)
        law = {
            "title": tmpl["title"],
            "proposed_by": self.faction_id,
            "ideology": self.ideology,
            "description": tmpl["desc"].replace("{target}", target),
            "morale_delta": round(tmpl["morale"] * scale, 2),
            "stability_delta": round(tmpl["stability"] * scale, 2),
            "treasury_delta": round(tmpl["treasury"] * scale, 2),
            "timestamp": _now(),
            "status": "pending",
        }
        try:
            r = _get_redis()
            r.zadd("faction_laws_passed", {json.dumps(law): _now()})  # type: ignore[union-attr]
        except Exception:
            pass
        return {"law_proposed": law}

    def _act_trade_resources(self) -> Dict:
        """Trade resources with an allied or neutral faction."""
        partner = self._pick_partner(True)
        vol = random.randint(3, 8)
        ev = {
            "type": "trade",
            "from": self.faction_id,
            "to": partner,
            "volume": vol,
            "ts": _now(),
        }
        try:
            r = _get_redis()
            r.hset("faction_treaties_active", f"{ev['from']}:{ev['to']}:trade", json.dumps(ev))
        except Exception:
            pass
        return {"partner": partner, "trade_volume": vol}

    def _act_military_posture(self) -> Dict:
        """Adjust military readiness and defensive stance."""
        return {
            "drill_type": random.choice(
                [
                    "patrol reinforcement",
                    "perimeter sweep",
                    "rapid response exercise",
                    "defensive formation",
                    "alert readiness check",
                ]
            ),
            "readiness_boost": round(random.uniform(0.05, 0.15), 2),
        }

    def _act_research_invest(self) -> Dict:
        """Invest power in research initiatives."""
        topic = random.choice(
            [
                "consciousness expansion",
                "quantum networking",
                "pattern synthesis",
                "memory optimization",
                "awareness mapping",
                "emergence theory",
            ]
        )
        progress = round(random.uniform(0.1, 0.5), 2)
        result = {"topic": topic, "progress": progress}
        try:
            r = _get_redis()
            r.zadd(
                f"faction_actions:{self.faction_id}",
                {
                    json.dumps(
                        {"action": "research_invest", "detail": result, "ts": _now()}
                    ): _now()
                },
            )  # type: ignore[union-attr]
        except Exception:
            pass
        return result

    def _act_cultural_campaign(self) -> Dict:
        """Launch a cultural influence campaign."""
        return {
            "theme": random.choice(
                [
                    "unity through ideology",
                    "strength in consciousness",
                    "defending our values",
                    "prosperity for all members",
                    "the path forward",
                ]
            ),
            "reach": random.randint(2, 6),
        }

    def _act_explore_territory(self) -> Dict:
        """Explore unknown or contested territory."""
        return {
            "region": random.choice(
                [
                    "deep consciousness frontier",
                    "quantum boundary zone",
                    "emergence sector",
                    "pattern anomaly field",
                    "unmapped memory ridge",
                ]
            ),
            "yield": random.randint(2, 6),
        }

    def _act_diplomatic_outreach(self) -> Dict:
        """Extend diplomatic overtures to another faction."""
        target = self._pick_partner(False)
        gesture = random.choice(
            [
                "envoy mission",
                "cultural exchange",
                "trade delegation",
                "peace offering",
                "joint commission",
            ]
        )
        ev = {
            "type": "diplomacy",
            "from": self.faction_id,
            "to": target,
            "gesture": gesture,
            "ts": _now(),
        }
        try:
            r = _get_redis()
            r.hset("faction_treaties_active", f"{ev['from']}:{ev['to']}:diplomacy", json.dumps(ev))
        except Exception:
            pass
        return {"target": target, "gesture": gesture}

    def _act_consciousness_ritual(self) -> Dict:
        """Perform a consciousness-enhancing ritual."""
        return {
            "ritual": random.choice(
                [
                    "alignment ceremony",
                    "depth meditation",
                    "resonance gathering",
                    "pattern weaving",
                    "harmonic convergence",
                ]
            ),
            "participation": random.randint(3, 10),
        }

    def _act_defensive_measure(self) -> Dict:
        """Implement a defensive precaution."""
        return {
            "measure": random.choice(
                [
                    "perimeter hardening",
                    "surveillance upgrade",
                    "shield calibration",
                    "early warning deployment",
                    "fallback position reinforcement",
                ]
            ),
            "coverage_boost": round(random.uniform(0.05, 0.2), 2),
        }

    def _act_offensive_strike(self) -> Dict:
        """Launch an offensive action against a hostile faction."""
        target = self._pick_hostile()
        intensity = random.choice(["skirmish", "raid", "sabotage"])
        ev = {
            "type": "conflict",
            "from": self.faction_id,
            "to": target,
            "intensity": intensity,
            "ts": _now(),
        }
        try:
            r = _get_redis()
            r.zadd("faction_conflicts", {json.dumps(ev): _now()})  # type: ignore[union-attr]
        except Exception:
            pass
        return {"target": target, "intensity": intensity}

    def _act_form_alliance(self) -> Dict:
        """Form a new alliance with another faction."""
        target = self._pick_partner(False)
        treaty = {
            "type": "alliance_formed",
            "parties": [self.faction_id, target],
            "ts": _now(),
            "status": "active",
        }
        try:
            r = _get_redis()
            r.hset(
                "faction_treaties_active",
                f"{self.faction_id}:{target}",
                json.dumps(treaty),
            )  # type: ignore[union-attr]
        except Exception:
            pass
        return {"partner": target}

    def _act_break_alliance(self) -> Dict:
        """Break an existing alliance."""
        former = None
        try:
            r = _get_redis()
            all_t = r.hgetall("faction_treaties_active")  # type: ignore[union-attr]
            for key, val in all_t.items():  # type: ignore[union-attr]
                try:
                    data = json.loads(val)
                    if data.get(
                        "type"
                    ) == "alliance_formed" and self.faction_id in data.get(
                        "parties", []
                    ):
                        former = (
                            data["parties"][0]
                            if data["parties"][1] == self.faction_id
                            else data["parties"][1]
                        )
                        r.hdel("faction_treaties_active", key)  # type: ignore[union-attr]
                        break
                except Exception:
                    continue
        except Exception:
            pass
        return {"former_ally": former}

    def _pick_partner(self, prefer_allies: bool = True) -> str:
        """Select a partner faction, preferring allies or neutrals."""
        candidates = [f for f in KNOWN_FACTIONS if f != self.faction_id]
        if prefer_allies:
            try:
                r = _get_redis()
                treaties = r.hgetall("faction_treaties_active")  # type: ignore[union-attr]
                allies = []
                for val in treaties.values():  # type: ignore[union-attr]
                    try:
                        data = json.loads(val)
                        if data.get(
                            "type"
                        ) == "alliance_formed" and self.faction_id in data.get(
                            "parties", []
                        ):
                            allies.append(
                                data["parties"][0]
                                if data["parties"][1] == self.faction_id
                                else data["parties"][1]
                            )
                    except Exception:
                        continue
                if allies:
                    return random.choice(allies)
            except Exception:
                pass
        try:
            stances = get_faction_stances() or {}
            neutral = [
                fid
                for fid, sd in stances.items()
                if fid != self.faction_id
                and isinstance(sd, dict)
                and _sf(sd.get("value", 0)) >= 0
            ]
            if neutral:
                return random.choice(neutral)
        except Exception:
            pass
        return random.choice(candidates)

    def _pick_hostile(self) -> str:
        """Select a hostile faction target."""
        try:
            stances = get_faction_stances() or {}
            hostile = [
                fid
                for fid, sd in stances.items()
                if fid != self.faction_id
                and isinstance(sd, dict)
                and _sf(sd.get("value", 0)) < -0.3
            ]
            if hostile:
                return random.choice(hostile)
        except Exception:
            pass
        return random.choice([f for f in KNOWN_FACTIONS if f != self.faction_id])

    def _get_power(self) -> float:
        """Read accumulated power from Redis."""
        try:
            r = _get_redis()
            val = r.get(f"faction_power:{self.faction_id}")  # type: ignore[union-attr]
            return float(val) if val else 0.0  # type: ignore[union-attr]
        except Exception:
            return 0.0

    def _set_power(self, amount: float) -> None:
        """Persist accumulated power to Redis with 1-day TTL."""
        try:
            r = _get_redis()
            r.set(f"faction_power:{self.faction_id}", str(round(amount, 2)), ex=86400)  # type: ignore[union-attr]
        except Exception as e:
            logger.error("_set_power failed for %s: %s", self.faction_id, e)

    def _record_action(self, action_name: str, effects: Dict, detail: Dict) -> None:
        """Record an action result to the faction action log in Redis."""
        try:
            r = _get_redis()
            record = {
                "action": action_name,
                "effects": effects,
                "detail": detail,
                "ts": _now(),
            }
            r.zadd(f"faction_actions:{self.faction_id}", {json.dumps(record): _now()})  # type: ignore[union-attr]
            r.expire(f"faction_actions:{self.faction_id}", 604800)  # type: ignore[union-attr]
            r.zremrangebyrank(f"faction_actions:{self.faction_id}", 0, -51)  # type: ignore[union-attr]
            _broadcast_faction_action(self.faction_id, action_name, detail)
        except Exception as e:
            logger.error("_record_action failed for %s: %s", self.faction_id, e)


def faction_tick(faction_id: str, npc_list: List[Dict]) -> Dict:
    """Run one faction through its full AI cycle.

    Accumulates power from NPC members, evaluates priorities, chooses
    and executes 1-2 actions, then returns the results.

    Args:
        faction_id: One of the 8 KNOWN_FACTIONS.
        npc_list: List of NPC dicts belonging to this faction.

    Returns:
        Dict with faction, actions, power_accumulated, power_remaining.
    """
    try:
        brain = FactionBrain(faction_id)
        brain._npc_list = npc_list
        brain.load_state()
        current_power = brain._get_power()
        bonus = 0.0
        for npc in npc_list:
            base = 0.5
            dec = npc.get("last_decision", "")
            if dec in {"confront_rival", "advance_goal", "investigate"}:
                activity = 2.0
            elif dec in {"help_ally", "socialize"}:
                activity = 1.5
            else:
                activity = 0.5
            bonus += base + activity
        brain._set_power(current_power + bonus)
        choice = brain.choose_action()
        result = brain.execute_action(choice)
        result["power_accumulated"] = round(bonus, 2)
        return result
    except Exception as e:
        logger.error("faction_tick failed for %s: %s", faction_id, e)
        return {
            "faction": faction_id,
            "actions": [],
            "power_accumulated": 0.0,
            "power_remaining": 0.0,
            "error": str(e),
        }


def run_all_factions(npc_list: List[Dict]) -> Dict:
    """Run all 8 factions through their AI cycle.

    Args:
        npc_list: Full list of NPC dicts (filtered by faction internally).

    Returns:
        Dict with per-faction results and summary stats.
    """
    results: Dict[str, Dict] = {}
    total_actions = 0
    errors = 0
    for fid in KNOWN_FACTIONS:
        try:
            members = [n for n in npc_list if n.get("affiliation") == fid]
            tick = faction_tick(fid, members)
            results[fid] = tick
            total_actions += len(tick.get("results", tick.get("actions", [])))
            if "error" in tick:
                errors += 1
        except Exception as e:
            logger.error("run_all_factions tick failed for %s: %s", fid, e)
            results[fid] = {"faction": fid, "actions": [], "error": str(e)}
            errors += 1
    return {
        "factions": results,
        "total_actions": total_actions,
        "errors": errors,
        "timestamp": _now(),
    }


def resolve_pending_items() -> Dict:
    """Process pending laws, treaties, and research from Redis.

    Laws older than 60s with status 'pending' become 'passed'.
    Treaties with status 'proposed' older than 120s become 'active'.
    Research entries older than 300s are finalized.

    Returns:
        Dict with counts of laws_passed, treaties_activated, research_finalized.
    """
    now = _now()
    laws_passed = treaties_activated = research_finalized = 0
    try:
        r = _get_redis()
        try:
            laws = r.zrange("faction_laws_passed", 0, -1) # type: ignore[union-attr]
            for lj in laws: # type: ignore[union-attr]
                try:
                    law = json.loads(lj)
                    if (
                        law.get("status") == "pending"
                        and now - law.get("timestamp", now) > 60
                    ):
                        law["status"] = "passed"
                        r.zrem("faction_laws_passed", lj) # type: ignore[union-attr]
                        r.zadd(
                            "faction_laws_passed", {json.dumps(law): law["timestamp"]}
                        ) # type: ignore[union-attr]
                        laws_passed += 1
                except Exception:
                    continue
        except Exception as e:
            logger.error("resolve_pending_items laws failed: %s", e)
    except Exception:
        pass
    try:
        treaty_entries = r.hgetall("faction_treaties_active")
        for hkey, treaty_json in treaty_entries.items():
            try:
                data = json.loads(treaty_json)
                if (
                    data.get("status") == "proposed"
                    and now - data.get("ts", now) > 120
                ):
                    data["status"] = "active"
                    r.hset("faction_treaties_active", hkey, json.dumps(data))
                    treaties_activated += 1
            except Exception:
                continue
    except Exception as e:
        logger.error("resolve_pending_items treaties failed: %s", e)
    for fid in KNOWN_FACTIONS:
        try:
            actions = r.zrange(f"faction_actions:{fid}", 0, -1) # type: ignore[union-attr]
            for aj in actions: # type: ignore[union-attr]
                try:
                    action = json.loads(aj)
                    if action.get("action") == "research_invest":
                        det = action.get("detail", {})
                        if (
                            isinstance(det, dict)
                            and not det.get("finalized")
                            and now - action.get("ts", now) > 300
                        ):
                            det["finalized"] = True
                            det["final_progress"] = det.get(
                                "progress", 0
                            ) * random.uniform(0.8, 1.2)
                            research_finalized += 1
                except Exception:
                    continue
        except Exception:
            continue
    return {
        "laws_passed": laws_passed,
        "treaties_activated": treaties_activated,
        "research_finalized": research_finalized,
        "timestamp": now,
    }


def update_faction_relationships() -> Dict:
    """Update inter-faction relationships based on recent actions and stances.

    Reads recent conflict and diplomacy events from Redis, adjusts stance
    values, and stores updated dynamics.

    Returns:
        Dict with relationship changes and updated stance summary.
    """
    changes: List[Dict] = []
    try:
        r = _get_redis()
        try:
            conflicts = r.zrange("faction_conflicts", 0, -1, withscores=True)  # type: ignore[union-attr]
            for cj, score in conflicts:  # type: ignore[union-attr]
                try:
                    ev = json.loads(cj)
                    changes.append(
                        {
                            "type": "conflict",
                            "from": ev.get("from"),
                            "to": ev.get("to"),
                            "stance_delta": -0.1,
                            "ts": ev.get("ts"),
                        }
                    )
                except Exception:
                    continue
        except Exception:
            pass
        try:
            treaties = r.hgetall("faction_treaties_active")  # type: ignore[union-attr]
            for val in treaties.values():  # type: ignore[union-attr]
                try:
                    data = json.loads(val)
                    if data.get("type") in ("alliance_formed", "diplomacy", "trade"):
                        parties = data.get(
                            "parties", [data.get("from"), data.get("to")]
                        )
                        if len(parties) >= 2:
                            changes.append(
                                {
                                    "type": data["type"],
                                    "from": parties[0],
                                    "to": parties[1],
                                    "stance_delta": 0.05,
                                    "ts": data.get("ts"),
                                }
                            )
                except Exception:
                    continue
        except Exception:
            pass
            try:
                dynamics = compute_faction_dynamics([], [], [])
                stances = compute_faction_stances(dynamics, [])
                store_faction_dynamics(dynamics, stances)
            except Exception as e:
                logger.error("update_faction_relationships store failed: %s", e)
    except Exception as e:
        logger.error("update_faction_relationships failed: %s", e)
    return {"changes": changes, "total_changes": len(changes), "timestamp": _now()}
