"""
Faction Diplomacy Engine — P23c
Bilateral faction interactions: treaties, trade, non-aggression pacts, and conflicts.
Called as Step 8.5 in autonomous_tick() (after tech research, before narration).
"""

import json
import logging
import random
import time
from typing import Dict, List, Optional, Any
from nvidia_nim_client import _run_async

logger = logging.getLogger(__name__)

FACTION_DIPLOMACY_COOLDOWN = 300

FACTION_IDEOLOGY_AFFINITY = {
    ("diplomatic", "cultural"): 0.6,
    ("diplomatic", "spiritual"): 0.4,
    ("diplomatic", "economic"): 0.3,
    ("diplomatic", "scientific"): 0.2,
    ("diplomatic", "military"): -0.2,
    ("diplomatic", "stability"): 0.1,
    ("military", "stability"): 0.5,
    ("military", "economic"): 0.2,
    ("military", "scientific"): 0.1,
    ("military", "cultural"): -0.3,
    ("military", "spiritual"): -0.2,
    ("military", "discovery"): 0.0,
    ("cultural", "spiritual"): 0.7,
    ("cultural", "scientific"): 0.1,
    ("cultural", "economic"): 0.0,
    ("cultural", "stability"): -0.1,
    ("cultural", "discovery"): 0.3,
    ("scientific", "economic"): 0.5,
    ("scientific", "discovery"): 0.6,
    ("scientific", "stability"): 0.1,
    ("scientific", "spiritual"): -0.1,
    ("economic", "stability"): 0.4,
    ("economic", "discovery"): 0.2,
    ("economic", "spiritual"): 0.0,
    ("spiritual", "discovery"): 0.3,
    ("spiritual", "stability"): 0.2,
    ("discovery", "stability"): -0.1,
}

DIPLOMACY_TYPES = [
    {
        "type": "trade_agreement",
        "weight": 0.35,
        "effects": {"resource_abundance": 2.0, "morale": 1.0},
        "min_affinity": -0.2,
        "duration_ticks": 10,
        "description_template": "Trade agreement between {faction_a} and {faction_b}",
    },
    {
        "type": "non_aggression_pact",
        "weight": 0.25,
        "effects": {"stability": 2.0, "threat_level": -1.5},
        "min_affinity": -0.4,
        "duration_ticks": 15,
        "description_template": "Non-aggression pact between {faction_a} and {faction_b}",
    },
    {
        "type": "research_pact",
        "weight": 0.20,
        "effects": {"anomaly_activity": 1.5, "resource_abundance": 1.0},
        "min_affinity": 0.1,
        "duration_ticks": 12,
        "description_template": "Research cooperation between {faction_a} and {faction_b}",
    },
    {
        "type": "cultural_exchange",
        "weight": 0.15,
        "effects": {"morale": 2.5, "anomaly_activity": 0.5},
        "min_affinity": 0.0,
        "duration_ticks": 8,
        "description_template": "Cultural exchange program between {faction_a} and {faction_b}",
    },
    {
        "type": "military_alliance",
        "weight": 0.05,
        "effects": {"threat_level": -3.0, "stability": 1.5, "tension_level": 1.0},
        "min_affinity": 0.4,
        "duration_ticks": 20,
        "description_template": "Military alliance between {faction_a} and {faction_b}",
    },
]


class FactionDiplomacyEngine:
    """Manages bilateral faction diplomacy during the autonomous tick."""

    def __init__(self, nim_client=None):
        self.nim_client = nim_client
        self.faction_ideologies = {}
        self.faction_names = {}
        self._registered = False

    def register_factions(self, faction_data: Dict[str, Any]):
        for fid, fdata in faction_data.items():
            self.faction_ideologies[fid] = fdata.get("ideology", "diplomatic")
            self.faction_names[fid] = fdata.get("name", fid)
        self._registered = True

    def _get_affinity(self, fid_a: str, fid_b: str) -> float:
        ideo_a = self.faction_ideologies.get(fid_a, "diplomatic")
        ideo_b = self.faction_ideologies.get(fid_b, "diplomatic")
        key = (ideo_a, ideo_b)
        key_rev = (ideo_b, ideo_a)
        if key in FACTION_IDEOLOGY_AFFINITY:
            return FACTION_IDEOLOGY_AFFINITY[key]
        elif key_rev in FACTION_IDEOLOGY_AFFINITY:
            return FACTION_IDEOLOGY_AFFINITY[key_rev]
        return 0.0

    def run_diplomacy_cycle(self, r, world_state: Dict[str, float]) -> Dict[str, Any]:
        result = {
            "proposals": [],
            "expirations": [],
            "rejections": [],
            "narratives": [],
        }

        faction_ids = list(self.faction_ideologies.keys())
        if len(faction_ids) < 2:
            return result

        expired = self._expire_treaties(r)
        result["expirations"] = expired

        pairs = self._get_eligible_pairs(faction_ids, r)
        for fid_a, fid_b in pairs:
            proposal = self._attempt_diplomacy(fid_a, fid_b, r, world_state)
            if proposal:
                if proposal.get("accepted"):
                    result["proposals"].append(proposal)
                    narrative = self._generate_narrative(proposal)
                    if narrative:
                        result["narratives"].append(narrative)
                else:
                    result["rejections"].append(proposal)

        self._apply_treaty_effects(r, world_state)

        logger.info(
            "[Diplomacy] Proposals: %d, Expirations: %d, Rejections: %d",
            len(result["proposals"]),
            len(result["expirations"]),
            len(result["rejections"]),
        )
        return result

    def _expire_treaties(self, r) -> List[Dict]:
        expired = []
        current_tick = int(r.get("autonomous_tick_count") or 0)
        all_treaties = r.hgetall("faction_treaties_active")
        for treaty_key, treaty_json in all_treaties.items():
            try:
                if isinstance(treaty_key, bytes):
                    treaty_key = treaty_key.decode()
                if isinstance(treaty_json, bytes):
                    treaty_json = treaty_json.decode()
                treaty = json.loads(treaty_json)
                created_tick = treaty.get("created_tick", 0)
                duration = treaty.get("duration_ticks", 10)
                if current_tick - created_tick >= duration:
                    r.hdel("faction_treaties_active", treaty_key)
                    expired.append(
                        {
                            "key": treaty_key,
                            "type": treaty.get("type", "unknown"),
                            "factions": treaty.get("factions", []),
                            "expired_after": duration,
                        }
                    )
                    logger.debug("[Diplomacy] Expired treaty: %s", treaty_key)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("[Diplomacy] Bad treaty data for %s: %s", treaty_key, e)
        return expired

    def _get_eligible_pairs(self, faction_ids: List[str], r) -> List[tuple]:
        pairs = []
        current_time = time.time()

        # Read treaties ONCE before the loop — O(1) Redis call instead of O(n²)
        all_treaties = r.hgetall("faction_treaties_active")
        active_pair_set = set()
        for tkey in all_treaties.keys():
            if isinstance(tkey, bytes):
                tkey = tkey.decode()
            parts = tkey.replace("treaty_", "").split("_")
            if len(parts) >= 2:
                active_pair_set.add(tuple(sorted([parts[0], parts[1]])))

        for i, fid_a in enumerate(faction_ids):
            for fid_b in faction_ids[i + 1 :]:
                cooldown_key = f"diplomacy_cooldown:{fid_a}:{fid_b}"
                last_attempt = r.get(cooldown_key)
                if last_attempt:
                    if isinstance(last_attempt, bytes):
                        last_attempt = last_attempt.decode()
                    if current_time - float(last_attempt) < FACTION_DIPLOMACY_COOLDOWN:
                        continue

                if tuple(sorted([fid_a, fid_b])) in active_pair_set:
                    continue

                pairs.append((fid_a, fid_b))

        max_attempts = min(len(pairs), 3)
        if len(pairs) > max_attempts:
            pairs = random.sample(pairs, max_attempts)
        return pairs

    def _attempt_diplomacy(
        self, fid_a: str, fid_b: str, r, world_state: Dict
    ) -> Optional[Dict]:
        base_affinity = self._get_affinity(fid_a, fid_b)

        stability = float(world_state.get("stability", 50))
        tension = float(world_state.get("tension_level", 50))
        morale = float(world_state.get("morale", 50))

        affinity_modifier = (
            (stability - 50) / 100 + (50 - tension) / 100 + (morale - 50) / 200
        )
        effective_affinity = base_affinity + affinity_modifier

        eligible_types = [
            dt for dt in DIPLOMACY_TYPES if effective_affinity >= dt["min_affinity"]
        ]
        if not eligible_types:
            return None

        total_weight = sum(dt["weight"] for dt in eligible_types)
        roll = random.uniform(0, total_weight)
        cumulative = 0
        chosen = eligible_types[0]
        for dt in eligible_types:
            cumulative += dt["weight"]
            if roll <= cumulative:
                chosen = dt
                break

        acceptance_prob = 0.3 + effective_affinity * 0.4
        acceptance_prob = max(0.1, min(0.8, acceptance_prob))
        accepted = random.random() < acceptance_prob

        cooldown_key_a = f"diplomacy_cooldown:{fid_a}:{fid_b}"
        cooldown_key_b = f"diplomacy_cooldown:{fid_b}:{fid_a}"
        current_time = time.time()
        pipe = r.pipeline()
        pipe.set(cooldown_key_a, str(current_time), ex=FACTION_DIPLOMACY_COOLDOWN * 2)
        pipe.set(cooldown_key_b, str(current_time), ex=FACTION_DIPLOMACY_COOLDOWN * 2)
        pipe.execute()

        current_tick = int(r.get("autonomous_tick_count") or 0)

        proposal = {
            "faction_a": fid_a,
            "faction_b": fid_b,
            "type": chosen["type"],
            "effects": chosen["effects"],
            "duration_ticks": chosen["duration_ticks"],
            "accepted": accepted,
            "effective_affinity": round(effective_affinity, 3),
            "tick": current_tick,
        }

        if accepted:
            treaty_key = f"{fid_a}:{fid_b}:{chosen['type']}"
            treaty_data = {
                "type": chosen["type"],
                "factions": [fid_a, fid_b],
                "effects": chosen["effects"],
                "created_tick": current_tick,
                "duration_ticks": chosen["duration_ticks"],
                "description": chosen["description_template"].format(
                    faction_a=self.faction_names.get(fid_a, fid_a),
                    faction_b=self.faction_names.get(fid_b, fid_b),
                ),
            }
            r.hset("faction_treaties_active", treaty_key, json.dumps(treaty_data))

            r.lpush(
                "pending_treaties",
                json.dumps(
                    {
                        "type": chosen["type"],
                        "factions": [fid_a, fid_b],
                        "effects": chosen["effects"],
                        "source": "faction_diplomacy_engine",
                        "tick": current_tick,
                    }
                ),
            )

            r.zadd(
                "diplomacy_history",
                {
                    json.dumps(
                        {
                            "faction_a": fid_a,
                            "faction_b": fid_b,
                            "type": chosen["type"],
                            "accepted": True,
                            "tick": current_tick,
                            "affinity": round(effective_affinity, 3),
                        }
                    ): current_tick
                },
            )
            r.zremrangebyrank("diplomacy_history", 0, -201)

        return proposal

    def _apply_treaty_effects(self, r, world_state: Dict):
        all_treaties = r.hgetall("faction_treaties_active")
        total_effects = {}
        for treaty_json in all_treaties.values():
            try:
                if isinstance(treaty_json, bytes):
                    treaty_json = treaty_json.decode()
                treaty = json.loads(treaty_json)
                effects = treaty.get("effects", {})
                for key, value in effects.items():
                    total_effects[key] = total_effects.get(key, 0) + value * 0.1
            except (json.JSONDecodeError, KeyError):
                pass

        for key, delta in total_effects.items():
            if key in world_state:
                world_state[key] = float(world_state[key]) + delta

    def _generate_narrative(self, proposal: Dict) -> Optional[str]:
        if not self.nim_client:
            return self._template_narrative(proposal)
        try:
            faction_a = self.faction_names.get(
                proposal["faction_a"], proposal["faction_a"]
            )
            faction_b = self.faction_names.get(
                proposal["faction_b"], proposal["faction_b"]
            )
            dtype = proposal["type"].replace("_", " ")
            prompt = (
                f"In the Federation, the {faction_a} and {faction_b} have signed a {dtype}. "
                f"Write a 1-2 sentence in-universe news announcement about this diplomatic development. "
                f"Be specific about what this means for the factions involved. "
                f"No preamble, no quotes, just the announcement."
            )
            response = _run_async(
                self.nim_client.call(
                    system_prompt="You are a Federation news announcer. Write brief, formal announcements.",
                    user_prompt=prompt,
                    max_tokens=120,
                    temperature=0.8,
                    priority="cloud",
                )
            )
            if response and len(response.strip()) > 10:
                cleaned = response.strip()
                for prefix in ["Okay, ", "Sure, ", "Well, ", "Alright, "]:
                    if cleaned.startswith(prefix):
                        cleaned = cleaned[len(prefix) :]
                return cleaned
        except Exception as e:
            logger.debug("[Diplomacy] LLM narrative failed: %s", e)
        return self._template_narrative(proposal)

    def _template_narrative(self, proposal: Dict) -> str:
        faction_a = self.faction_names.get(proposal["faction_a"], proposal["faction_a"])
        faction_b = self.faction_names.get(proposal["faction_b"], proposal["faction_b"])
        dtype = proposal["type"].replace("_", " ")
        return f"The {faction_a} and {faction_b} have formalized a {dtype}, strengthening their bilateral ties."

    def get_diplomacy_summary(self, r) -> Dict[str, Any]:
        active_treaties = []
        all_treaties = r.hgetall("faction_treaties_active")
        current_tick = int(r.get("autonomous_tick_count") or 0)
        for tkey, tjson in all_treaties.items():
            try:
                if isinstance(tkey, bytes):
                    tkey = tkey.decode()
                if isinstance(tjson, bytes):
                    tjson = tjson.decode()
                treaty = json.loads(tjson)
                created = treaty.get("created_tick", 0)
                duration = treaty.get("duration_ticks", 10)
                remaining = max(0, duration - (current_tick - created))
                active_treaties.append(
                    {
                        "key": tkey,
                        "type": treaty.get("type"),
                        "factions": treaty.get("factions", []),
                        "remaining_ticks": remaining,
                        "description": treaty.get("description", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                pass

        recent = r.zrevrange("diplomacy_history", 0, 19, withscores=True)
        history = []
        for item, score in recent:
            try:
                if isinstance(item, bytes):
                    item = item.decode()
                history.append(json.loads(item))
            except json.JSONDecodeError:
                pass

        ideology_affinities = {}
        fids = list(self.faction_ideologies)
        for i, fid_a in enumerate(fids):
            for fid_b in fids[i + 1 :]:
                ideology_affinities[f"{fid_a}-{fid_b}"] = self._get_affinity(
                    fid_a, fid_b
                )

        return {
            "active_treaties": active_treaties,
            "treaty_count": len(active_treaties),
            "recent_history": history,
            "ideology_affinities": ideology_affinities,
        }


_diplomacy_engine = None


def _get_diplomacy_engine(redis_client=None):
    global _diplomacy_engine
    if _diplomacy_engine is None:
        try:
            from nvidia_nim_client import get_nim_client, _run_async

            nim = get_nim_client()
        except Exception:
            nim = None
        _diplomacy_engine = FactionDiplomacyEngine(nim_client=nim)

        from faction_ai import FACTION_IDEOLOGY
        from faction_dynamics import FACTION_DISPLAY

        faction_data = {}
        for fid, ideology in FACTION_IDEOLOGY.items():
            faction_data[fid] = {
                "ideology": ideology,
                "name": FACTION_DISPLAY.get(fid, fid),
            }
        _diplomacy_engine.register_factions(faction_data)
    return _diplomacy_engine
