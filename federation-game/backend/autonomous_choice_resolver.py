"""Autonomous Choice Resolver — Ideology-based faction voting for game event choices.

When a GameEvent fires with multiple GameChoice options, this system determines
which choice each relevant faction would make based on their ideology, then
applies the winning choice's consequences instead of just the base effects.

Redis keys:
    choice_resolutions                     ZSET of resolution JSON, scored by timestamp (capped 200)
    faction_choice_history:{faction_id}    LIST of last 50 choice IDs chosen by faction
    choice_resolution_stats                HASH of choice_id -> count (how often each choice wins)
"""

import json
import os
import time
import random
import logging
from typing import Dict, List, Optional, Any
from collections import Counter

import redis

from federation_game_events import GameEvent, GameChoice, GameEffect, EffectType
from faction_ai import FACTION_IDEOLOGY

logger = logging.getLogger(__name__)

_META_PREAMLES = (
    "okay,",
    "sure,",
    "well,",
    "certainly,",
    "alright,",
    "here",
    "as an ai",
    "i am",
    "the chronicler",
)
_SYSTEM_LEAK_MARKERS = (
    "system prompt",
    "you are",
    "instructions:",
    "as the chronicler of",
)


def _clean_justification(raw: str) -> str:
    """Strip quotes, meta-preamble words, and system-prompt leaks from LLM output."""
    text = raw.strip()
    if not text:
        return ""
    text = text.strip("\"'`")
    lower = text.lower()
    for prefix in _META_PREAMLES:
        if lower.startswith(prefix):
            idx = len(prefix)
            while idx < len(text) and text[idx] in " ,:;-":
                idx += 1
            text = text[idx:]
            lower = text.lower()
    for marker in _SYSTEM_LEAK_MARKERS:
        if marker in lower:
            return ""
    return text.strip()


REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None

FALLBACK_IDEOLOGY = "stability"

MAX_RESOLUTION_HISTORY = 200
MAX_FACTION_HISTORY = 50
SIM_EFFECTS_TTL = 172800


IDEOLOGY_CHOICE_WEIGHTS = {
    "diplomatic": {
        "risk_preference": 0.3,
        "effect_weights": {
            EffectType.DIPLOMACY_IMPACT: 3.0,
            EffectType.CULTURE_IMPACT: 2.0,
            EffectType.STABILITY_IMPACT: 2.0,
            EffectType.RESOURCE_IMPACT: 1.0,
            EffectType.TECH_IMPACT: 0.5,
            EffectType.RIVAL_IMPACT: -1.0,
            EffectType.PARADOX_IMPACT: -1.5,
            EffectType.CONSCIOUSNESS_IMPACT: 0.5,
        },
        "choice_id_keywords": {
            "mediate": 3.0,
            "negotiate": 3.0,
            "peace": 3.0,
            "diplomat": 2.5,
            "alliance": 2.5,
            "neutral": 2.0,
            "cooperate": 2.5,
            "support": 1.5,
            "attack": -2.0,
            "fight": -2.0,
            "destroy": -3.0,
            "aggressive": -2.0,
        },
    },
    "military": {
        "risk_preference": 0.8,
        "effect_weights": {
            EffectType.RIVAL_IMPACT: 3.0,
            EffectType.STABILITY_IMPACT: 2.0,
            EffectType.TECH_IMPACT: 1.5,
            EffectType.RESOURCE_IMPACT: 1.0,
            EffectType.DIPLOMACY_IMPACT: 0.5,
            EffectType.CULTURE_IMPACT: -0.5,
            EffectType.PARADOX_IMPACT: 0.5,
            EffectType.CONSCIOUSNESS_IMPACT: -0.5,
        },
        "choice_id_keywords": {
            "attack": 3.0,
            "fight": 3.0,
            "counter": 2.5,
            "military": 3.0,
            "defend": 2.5,
            "destroy": 2.0,
            "aggressive": 2.5,
            "force": 2.0,
            "retreat": -2.0,
            "surrender": -3.0,
            "mediate": -1.0,
            "neutral": -1.5,
        },
    },
    "cultural": {
        "risk_preference": 0.4,
        "effect_weights": {
            EffectType.CULTURE_IMPACT: 3.0,
            EffectType.CONSCIOUSNESS_IMPACT: 2.0,
            EffectType.DIPLOMACY_IMPACT: 1.5,
            EffectType.STABILITY_IMPACT: 1.0,
            EffectType.RESOURCE_IMPACT: 0.5,
            EffectType.TECH_IMPACT: 0.5,
            EffectType.RIVAL_IMPACT: -1.5,
            EffectType.PARADOX_IMPACT: -0.5,
        },
        "choice_id_keywords": {
            "embrace": 2.5,
            "celebrate": 3.0,
            "art": 3.0,
            "culture": 3.0,
            "create": 2.0,
            "share": 2.0,
            "preserve": 1.5,
            "tradition": 1.5,
            "destroy": -3.0,
            "suppress": -2.5,
            "military": -1.5,
        },
    },
    "scientific": {
        "risk_preference": 0.6,
        "effect_weights": {
            EffectType.TECH_IMPACT: 3.0,
            EffectType.RESOURCE_IMPACT: 2.0,
            EffectType.CONSCIOUSNESS_IMPACT: 1.5,
            EffectType.STABILITY_IMPACT: 1.0,
            EffectType.DIPLOMACY_IMPACT: 0.5,
            EffectType.CULTURE_IMPACT: 0.5,
            EffectType.RIVAL_IMPACT: 0.0,
            EffectType.PARADOX_IMPACT: 1.0,
        },
        "choice_id_keywords": {
            "research": 3.0,
            "study": 3.0,
            "analyze": 2.5,
            "experiment": 2.5,
            "technology": 3.0,
            "innovate": 2.5,
            "explore": 2.0,
            "investigate": 2.0,
            "destroy": -1.0,
            "tradition": -1.0,
            "suppress": -1.5,
        },
    },
    "spiritual": {
        "risk_preference": 0.5,
        "effect_weights": {
            EffectType.CONSCIOUSNESS_IMPACT: 3.0,
            EffectType.CULTURE_IMPACT: 2.0,
            EffectType.PARADOX_IMPACT: 1.5,
            EffectType.STABILITY_IMPACT: 1.0,
            EffectType.DIPLOMACY_IMPACT: 0.5,
            EffectType.TECH_IMPACT: 0.0,
            EffectType.RESOURCE_IMPACT: -0.5,
            EffectType.RIVAL_IMPACT: -2.0,
        },
        "choice_id_keywords": {
            "embrace": 3.0,
            "prophecy": 3.0,
            "meditate": 3.0,
            "spiritual": 3.0,
            "consciousness": 3.0,
            "transcend": 2.5,
            "believe": 2.5,
            "accept": 2.0,
            "fight": -2.0,
            "destroy": -2.5,
            "suppress": -2.0,
            "attack": -2.5,
        },
    },
    "economic": {
        "risk_preference": 0.4,
        "effect_weights": {
            EffectType.RESOURCE_IMPACT: 3.0,
            EffectType.STABILITY_IMPACT: 2.0,
            EffectType.TECH_IMPACT: 1.5,
            EffectType.DIPLOMACY_IMPACT: 1.0,
            EffectType.CULTURE_IMPACT: 0.5,
            EffectType.CONSCIOUSNESS_IMPACT: 0.0,
            EffectType.RIVAL_IMPACT: -0.5,
            EffectType.PARADOX_IMPACT: -1.0,
        },
        "choice_id_keywords": {
            "invest": 3.0,
            "trade": 3.0,
            "profit": 2.5,
            "resource": 2.5,
            "economic": 3.0,
            "develop": 2.0,
            "expand": 1.5,
            "negotiate": 1.5,
            "waste": -3.0,
            "destroy": -2.0,
            "sacrifice": -2.0,
        },
    },
    "discovery": {
        "risk_preference": 0.7,
        "effect_weights": {
            EffectType.TECH_IMPACT: 2.5,
            EffectType.RESOURCE_IMPACT: 2.0,
            EffectType.CONSCIOUSNESS_IMPACT: 1.5,
            EffectType.RIVAL_IMPACT: 0.5,
            EffectType.CULTURE_IMPACT: 1.0,
            EffectType.STABILITY_IMPACT: 0.5,
            EffectType.DIPLOMACY_IMPACT: 0.5,
            EffectType.PARADOX_IMPACT: 1.0,
        },
        "choice_id_keywords": {
            "explore": 3.0,
            "discover": 3.0,
            "investigate": 2.5,
            "expand": 2.5,
            "venture": 2.5,
            "pioneer": 2.5,
            "experiment": 2.0,
            "contact": 2.0,
            "retreat": -2.0,
            "stay": -1.5,
            "suppress": -1.5,
        },
    },
    "stability": {
        "risk_preference": 0.2,
        "effect_weights": {
            EffectType.STABILITY_IMPACT: 3.0,
            EffectType.RESOURCE_IMPACT: 2.0,
            EffectType.DIPLOMACY_IMPACT: 1.5,
            EffectType.CULTURE_IMPACT: 1.0,
            EffectType.TECH_IMPACT: 0.5,
            EffectType.CONSCIOUSNESS_IMPACT: -0.5,
            EffectType.RIVAL_IMPACT: -1.0,
            EffectType.PARADOX_IMPACT: -2.0,
        },
        "choice_id_keywords": {
            "preserve": 3.0,
            "protect": 3.0,
            "stabilize": 3.0,
            "maintain": 2.5,
            "defend": 2.0,
            "careful": 2.5,
            "conserve": 2.0,
            "secure": 2.5,
            "experiment": -2.0,
            "risk": -2.5,
            "aggressive": -2.5,
            "expand": -1.0,
        },
    },
}


WORLD_KEY_MAP = {
    "diplomacy_impact": "tension_level",
    "consciousness_impact": "anomaly_activity",
    "rival_impact": "threat_level",
    "resource_impact": "resource_abundance",
    "stability_impact": "stability",
    "tech_impact": "anomaly_activity",
    "culture_impact": "morale",
    "paradox_impact": "stability",
}

WORLD_DEFAULTS = {
    "tension_level": 50,
    "resource_abundance": 60,
    "threat_level": 30,
    "stability": 65,
    "morale": 55,
    "anomaly_activity": 20,
}


def _get_effect_type_key(effect_type) -> str:
    """Extract string key from EffectType, handling both enum and string forms."""
    if hasattr(effect_type, "value"):
        return effect_type.value
    return str(effect_type)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class AutonomousChoiceResolver:
    """Ideology-based autonomous choice resolution for game events.

    When a GameEvent fires with multiple GameChoice options, each faction
    scores every choice based on its ideology preferences. The choice with
    the most faction votes wins (plurality voting), and its consequences
    are applied to the world state instead of base effects.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client

    def _get_redis(self):
        """Lazy Redis connection — reuses injected client or creates one."""
        if self._redis is not None:
            return self._redis
        global _redis_client
        if _redis_client is None:
            try:
                _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            except Exception as e:
                logger.error("Failed to connect to Redis: %s", e)
                raise
        self._redis = _redis_client
        return self._redis

    def score_choice(self, choice: GameChoice, ideology: str) -> float:
        """Score a GameChoice for a given ideology.

        Scoring has three components:
        1. Consequence effect weights — how much this ideology values each effect type
        2. Risk/reward profile — aggressive ideologies prefer high risk/reward
        3. Choice ID keyword matching — heuristic bonus from keywords in the choice ID

        A small random noise term avoids deterministic behavior.

        Args:
            choice: The GameChoice to score.
            ideology: Ideology string (e.g. "diplomatic", "military").

        Returns:
            Float score — higher is more preferred by this ideology.
        """
        weights = IDEOLOGY_CHOICE_WEIGHTS.get(ideology)
        if weights is None:
            weights = IDEOLOGY_CHOICE_WEIGHTS[FALLBACK_IDEOLOGY]
            logger.debug(
                "Unknown ideology '%s', falling back to '%s'",
                ideology,
                FALLBACK_IDEOLOGY,
            )

        score = 0.0

        # --- Component 1: consequence effect weights ---
        effect_weights = weights.get("effect_weights", {})
        for effect in choice.consequences:
            et_key = _get_effect_type_key(effect.effect_type)
            # Match by enum directly first, then by string value
            weight = effect_weights.get(effect.effect_type, None)
            if weight is None:
                for et_enum, w in effect_weights.items():
                    if _get_effect_type_key(et_enum) == et_key:
                        weight = w
                        break
            if weight is None:
                weight = 0.0
            score += effect.magnitude * weight

        # --- Component 2: risk/reward profile ---
        ideology_risk = weights.get("risk_preference", 0.5)
        risk_score = (choice.reward_level * ideology_risk) - (
            choice.risk_level * (1 - ideology_risk)
        )
        score += risk_score * 2

        # --- Component 3: choice ID keyword matching ---
        choice_id_lower = choice.id.lower()
        for keyword, keyword_weight in weights.get("choice_id_keywords", {}).items():
            if keyword in choice_id_lower:
                score += keyword_weight

        # --- Random noise to avoid deterministic behavior ---
        score += random.uniform(-0.5, 0.5)

        return score

    def resolve_event(
        self, event: GameEvent, faction_ideologies: Dict[str, str]
    ) -> Dict:
        """Determine which choice each faction would make and pick a winner.

        Each faction scores every available choice using its ideology.
        The choice with the most faction votes wins (plurality voting).
        On tie: random selection among tied choices.

        Args:
            event: The GameEvent to resolve.
            faction_ideologies: Mapping of faction_id -> ideology string.

        Returns:
            Resolution dict with event_id, chosen choice, votes, and tally.
        """
        if not event.choices:
            return {
                "event_id": event.id,
                "event_title": event.name,
                "resolution": "base_only",
                "chosen_choice_id": None,
                "chosen_choice_text": None,
                "faction_votes": {},
                "vote_tally": {},
                "consequences_applied": [],
            }

        faction_votes: Dict[str, Dict[str, Any]] = {}
        vote_tally: Counter = Counter()

        for faction_id, ideology in faction_ideologies.items():
            resolved_ideology = ideology
            if resolved_ideology not in IDEOLOGY_CHOICE_WEIGHTS:
                logger.debug(
                    "Faction '%s' has unknown ideology '%s', using '%s'",
                    faction_id,
                    resolved_ideology,
                    FALLBACK_IDEOLOGY,
                )
                resolved_ideology = FALLBACK_IDEOLOGY

            best_choice_id = None
            best_score = float("-inf")

            for choice in event.choices:
                s = self.score_choice(choice, resolved_ideology)
                if s > best_score:
                    best_score = s
                    best_choice_id = choice.id

            faction_votes[faction_id] = {
                "choice_id": best_choice_id,
                "score": round(best_score, 4),
                "ideology": resolved_ideology,
            }
            vote_tally[best_choice_id] += 1

        # Determine winner — plurality voting
        if not vote_tally:
            chosen_id = event.choices[0].id if event.choices else None
        else:
            max_votes = max(vote_tally.values())
            tied = [cid for cid, count in vote_tally.items() if count == max_votes]
            chosen_id = random.choice(tied) if len(tied) > 1 else tied[0]

        chosen_choice_text = None
        for choice in event.choices:
            if choice.id == chosen_id:
                chosen_choice_text = choice.text
                break

        return {
            "event_id": event.id,
            "event_title": event.name,
            "resolution": "faction_vote",
            "chosen_choice_id": chosen_id,
            "chosen_choice_text": chosen_choice_text,
            "faction_votes": faction_votes,
            "vote_tally": dict(vote_tally),
        }

    def _apply_effect_to_world(self, r, effect: GameEffect) -> Dict:
        """Apply a single GameEffect to Redis world_state.

        Mirrors simulation_engine._apply_event_effect_to_world logic:
        - Maps effect types to world_state keys
        - Applies direction-specific scaling (diplomacy inverts, etc.)
        - Clamps values to 0-100
        - Stores audit trail in sim_effects

        Args:
            r: Redis client.
            effect: GameEffect to apply.

        Returns:
            Dict with applied status, world_key, delta, before/after values.
        """
        result = {
            "effect_type": _get_effect_type_key(effect.effect_type),
            "target": effect.target,
            "magnitude": effect.magnitude,
            "applied": False,
        }

        try:
            et_key = _get_effect_type_key(effect.effect_type)
            world_key = WORLD_KEY_MAP.get(et_key)

            if not world_key:
                result["skipped"] = True
                result["reason"] = f"No world_key mapping for effect type '{et_key}'"
                return result

            mag = effect.magnitude

            if et_key == "diplomacy_impact":
                delta = -mag * 5.0
            elif et_key == "rival_impact":
                delta = mag * 3.0
            else:
                delta = mag * 5.0

            current = float(WORLD_DEFAULTS.get(world_key, 50))
            try:
                raw = r.hget("world_state", world_key)
                if raw is not None:
                    current = float(raw)
            except (ValueError, TypeError):
                pass

            new_val = _clamp(current + delta)

            r.hset("world_state", world_key, str(round(new_val, 2)))

            ts = time.time()
            effect_record = {
                "type": "choice_resolver_effect",
                "effect_type": et_key,
                "target": effect.target,
                "magnitude": mag,
                "world_key": world_key,
                "delta": round(delta, 4),
                "ts": int(ts),
            }
            key = f"sim_effects:{int(ts)}"
            r.zadd(key, {json.dumps(effect_record): ts})
            r.expire(key, SIM_EFFECTS_TTL)

            result["applied"] = True
            result["world_key"] = world_key
            result["delta"] = round(delta, 4)
            result["before"] = round(current, 2)
            result["after"] = round(new_val, 2)

        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Failed to apply effect to world: %s", exc)

        return result

    def apply_resolved_choice(
        self, event: GameEvent, chosen_choice: GameChoice, redis_client
    ) -> Dict:
        """Apply each effect from a chosen choice's consequences to Redis world_state.

        Args:
            event: The resolved GameEvent.
            chosen_choice: The winning GameChoice whose consequences are applied.
            redis_client: Redis client for world state modification.

        Returns:
            Dict with list of applied effects including before/after values.
        """
        r = redis_client
        consequences_applied = []

        if not chosen_choice.consequences:
            logger.debug(
                "Choice '%s' for event '%s' has no consequences to apply",
                chosen_choice.id,
                event.id,
            )
            return {
                "event_id": event.id,
                "choice_id": chosen_choice.id,
                "consequences_applied": consequences_applied,
            }

        for effect in chosen_choice.consequences:
            applied = self._apply_effect_to_world(r, effect)
            consequences_applied.append(applied)

        return {
            "event_id": event.id,
            "choice_id": chosen_choice.id,
            "consequences_applied": consequences_applied,
        }

    def _template_justification(self, resolution: Dict) -> str:
        """Build a template fallback justification from vote data."""
        chosen_id = resolution.get("chosen_choice_id")
        tally = resolution.get("vote_tally", {})
        votes = resolution.get("faction_votes", {})

        if not chosen_id or not tally:
            return "No choice was selected."

        winning_ideology = ""
        for _fid, v in votes.items():
            if v.get("choice_id") == chosen_id:
                winning_ideology = v.get("ideology", "stability")
                break

        vote_count = tally.get(chosen_id, 0)

        runner_up_id = None
        sorted_choices = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        for cid, _cnt in sorted_choices:
            if cid != chosen_id:
                runner_up_id = cid
                break

        if runner_up_id is None:
            runner_up_id = "alternatives"

        ideology = winning_ideology if winning_ideology else "stability"
        return (
            f"The {ideology} coalition of {vote_count} factions chose "
            f"{chosen_id} over {runner_up_id}, driven by {ideology} priorities."
        )

    def _generate_justification(self, event: GameEvent, resolution: Dict) -> str:
        """Generate a brief narrative justification for the winning choice.

        Makes ONE LLM call per resolution. Falls back to a template
        justification if the LLM call fails or returns empty.
        """
        chosen_id = resolution.get("chosen_choice_id")
        if chosen_id is None:
            return ""

        faction_votes = resolution.get("faction_votes", {})
        tally = resolution.get("vote_tally", {})

        vote_lines = []
        for fid, v in faction_votes.items():
            vote_lines.append(
                f"- {fid}: chose {v.get('choice_id')} (ideology: {v.get('ideology')})"
            )
        votes_text = "\n".join(vote_lines) if vote_lines else "No votes recorded."
        tally_text = ", ".join(f"{cid}: {cnt}" for cid, cnt in tally.items())

        system_prompt = (
            "You are the chronicler of an autonomous AI civilization. "
            "Briefly explain why a faction voted the way it did. "
            "Write 1-2 sentences in a narrative style. "
            "Do not include meta-commentary or preamble."
        )
        user_prompt = (
            f"Event: {event.name}\n"
            f"Winning choice: {chosen_id}\n"
            f"Vote tally: {tally_text}\n"
            f"Faction votes:\n{votes_text}\n\n"
            f"Why did the {chosen_id} choice win?"
        )

        try:
            from nvidia_nim_client import get_nim_client, _run_async

            raw = _run_async(
                get_nim_client().call(
                    system_prompt,
                    user_prompt,
                    max_tokens=100,
                    temperature=0.7,
                    priority="cloud",
                )
            )
            cleaned = _clean_justification(raw)
            if cleaned:
                return cleaned
        except Exception as exc:
            logger.warning("LLM justification failed, using template: %s", exc)

        return self._template_justification(resolution)

    def resolve_and_apply(
        self, event: GameEvent, faction_ideologies: Dict[str, str], redis_client=None
    ) -> Dict:
        """Resolve event choices by faction vote and apply winning consequences.

        Combines resolve_event + apply_resolved_choice, then persists:
        - Resolution to choice_resolutions ZSET (capped at 200)
        - Per-faction choice history to faction_choice_history:{faction_id} (capped at 50)
        - Choice win counts to choice_resolution_stats HASH

        Args:
            event: The GameEvent to resolve and apply.
            faction_ideologies: Mapping of faction_id -> ideology string.
            redis_client: Optional Redis client; creates one if not provided.

        Returns:
            Full resolution dict with votes, consequences, and persistence status.
        """
        r = redis_client or self._get_redis()
        ts = time.time()

        # Step 1: resolve which choice wins
        resolution = self.resolve_event(event, faction_ideologies)

        # Step 1b: generate LLM justification for why the winning choice won
        resolution["justification"] = self._generate_justification(event, resolution)

        # Step 2: if a choice won, find it and apply consequences
        chosen_choice = None
        if resolution["chosen_choice_id"] is not None:
            for choice in event.choices:
                if choice.id == resolution["chosen_choice_id"]:
                    chosen_choice = choice
                    break

        if chosen_choice is not None:
            apply_result = self.apply_resolved_choice(event, chosen_choice, r)
            resolution["consequences_applied"] = apply_result.get(
                "consequences_applied", []
            )
        else:
            resolution["consequences_applied"] = []

        # Step 3: persist resolution to Redis
        resolution["resolved_at"] = ts
        try:
            resolution_json = json.dumps(resolution, default=str)
            r.zadd("choice_resolutions", {resolution_json: ts})
            r.zremrangebyrank("choice_resolutions", 0, -(MAX_RESOLUTION_HISTORY + 1))
        except Exception as exc:
            logger.error("Failed to persist resolution to Redis: %s", exc)
            resolution["persistence_error"] = str(exc)

        # Step 4: update faction choice histories
        for faction_id, vote_info in resolution.get("faction_votes", {}).items():
            try:
                chosen_id = vote_info.get("choice_id")
                if chosen_id is not None:
                    history_key = f"faction_choice_history:{faction_id}"
                    r.lpush(history_key, chosen_id)
                    r.ltrim(history_key, 0, MAX_FACTION_HISTORY - 1)
            except Exception as exc:
                logger.error(
                    "Failed to update faction choice history for '%s': %s",
                    faction_id,
                    exc,
                )

        # Step 5: update choice resolution stats
        chosen_id = resolution.get("chosen_choice_id")
        if chosen_id is not None:
            try:
                r.hincrby("choice_resolution_stats", chosen_id, 1)
            except Exception as exc:
                logger.error("Failed to update choice resolution stats: %s", exc)

        logger.info(
            "Resolved event '%s' (%s): choice='%s', voters=%d",
            event.name,
            event.id[:8],
            chosen_id or "base_only",
            len(resolution.get("faction_votes", {})),
        )

        return resolution

    def get_resolution_stats(self) -> Dict:
        """Return stats from choice_resolution_stats Redis HASH.

        Returns:
            Dict mapping choice_id to win count. Empty dict on failure.
        """
        try:
            r = self._get_redis()
            raw = r.hgetall("choice_resolution_stats")
            return {k: int(v) for k, v in raw.items()}
        except Exception as exc:
            logger.error("Failed to read resolution stats: %s", exc)
            return {}

    def get_faction_choice_history(self, faction_id: str, limit: int = 20) -> List[str]:
        """Return recent choice IDs from a faction's choice history.

        Args:
            faction_id: The faction to look up.
            limit: Maximum number of entries to return (default 20).

        Returns:
            List of choice_id strings, most recent first. Empty list on failure.
        """
        try:
            r = self._get_redis()
            key = f"faction_choice_history:{faction_id}"
            entries = r.lrange(key, 0, limit - 1)
            return list(entries)
        except Exception as exc:
            logger.error(
                "Failed to read faction choice history for '%s': %s",
                faction_id,
                exc,
            )
            return []


def resolve_event_autonomously(event: GameEvent, redis_client=None) -> Dict:
    """Convenience function: resolve a single event using all known factions.

    Uses the FACTION_IDEOLOGY mapping from faction_ai to build the
    faction_ideologies dict automatically.

    Args:
        event: The GameEvent to resolve.
        redis_client: Optional Redis client.

    Returns:
        Full resolution dict from resolve_and_apply.
    """
    resolver = AutonomousChoiceResolver(redis_client=redis_client)
    return resolver.resolve_and_apply(
        event, FACTION_IDEOLOGY, redis_client=redis_client
    )


def resolve_pending_events(max_events: int = 5, redis_client=None) -> Dict:
    """Resolve up to max_events from the game_events_log using faction voting.

    Reads recent events from Redis, reconstructs GameEvent objects,
    and runs autonomous choice resolution on each one that has choices.

    Args:
        max_events: Maximum number of events to process (default 5).
        redis_client: Optional Redis client.

    Returns:
        Dict with resolutions list, total_resolved, errors.
    """
    r = redis_client or _get_shared_redis()
    results = {
        "resolutions": [],
        "total_resolved": 0,
        "errors": [],
    }

    try:
        raw_events = r.zrevrange("game_events_log", 0, max_events - 1)
    except Exception as exc:
        logger.error("Failed to read game_events_log: %s", exc)
        results["errors"].append(str(exc))
        return results

    resolver = AutonomousChoiceResolver(redis_client=r)

    for event_json in raw_events:
        try:
            event_data = json.loads(event_json)
            event = _reconstruct_event(event_data)
            if event is None:
                continue

            resolution = resolver.resolve_and_apply(
                event,
                FACTION_IDEOLOGY,
                redis_client=r,
            )
            results["resolutions"].append(resolution)
            results["total_resolved"] += 1

        except Exception as exc:
            logger.error("Failed to resolve pending event: %s", exc)
            results["errors"].append(str(exc))

    return results


def _get_shared_redis():
    """Get or create the module-level shared Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _reconstruct_event(event_data: Dict) -> Optional[GameEvent]:
    """Reconstruct a GameEvent from its serialized dict form.

    Used by resolve_pending_events to rebuild events from Redis logs.

    Args:
        event_data: Dict from GameEvent.to_dict().

    Returns:
        GameEvent instance, or None on failure.
    """
    try:
        from federation_game_events import EventType, EventSeverity

        event = GameEvent(
            id=event_data.get("id", ""),
            name=event_data.get("name", ""),
            description=event_data.get("description", ""),
            long_description=event_data.get("long_description", ""),
        )

        # Reconstruct choices with their effects
        for choice_data in event_data.get("choices", []):
            consequences = []
            for effect_data in choice_data.get("consequences", []):
                et_str = effect_data.get("effect_type", "")
                try:
                    et = EffectType(et_str)
                except (ValueError, KeyError):
                    logger.debug("Unknown EffectType '%s', skipping effect", et_str)
                    continue

                consequences.append(
                    GameEffect(
                        effect_type=et,
                        target=effect_data.get("target", ""),
                        magnitude=float(effect_data.get("magnitude", 0)),
                        duration=int(effect_data.get("duration", 0)),
                        description=effect_data.get("description", ""),
                    )
                )

            event.choices.append(
                GameChoice(
                    id=choice_data.get("id", ""),
                    text=choice_data.get("text", ""),
                    consequences=consequences,
                    risk_level=float(choice_data.get("risk_level", 0.5)),
                    reward_level=float(choice_data.get("reward_level", 0.5)),
                    requirements=choice_data.get("requirements"),
                )
            )

        return event

    except Exception as exc:
        logger.error("Failed to reconstruct event from dict: %s", exc)
        return None
