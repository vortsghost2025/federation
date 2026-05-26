#!/usr/bin/env python3
"""
THE FEDERATION GAME - NPC AUTONOMOUS QUEST ENGINE
~450 LOC

Allows 39 NPCs to independently accept, pursue, and complete quests
from the existing quest library WITHOUT requiring a player_id.

All state persisted to Redis — survives restarts. Compatible with
the existing QuestSystem in quests.py (reuses its dataclasses and
lifecycle methods). The in-memory QuestSystem handles quest registry
and validation; this engine adds Redis-backed per-NPC persistence
and autonomous tick-driven progression.

Redis Key Schema
----------------
npc_quests:active:{char_id}           HASH  quest_id -> quest JSON
npc_quests:completed:{char_id}        LIST  of quest JSON strings
npc_quests:failed:{char_id}           LIST  of quest JSON strings
npc_quests:progress:{char_id}:{qid}   HASH  objective_id -> current_progress
npc_quests:stats:{char_id}            HASH  stat_name -> int
npc_quests:log                        ZSET  event JSON, scored by timestamp (cap 200)
"""

import json
import time
import random
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

import redis

from quests import (
    Quest,
    QuestSystem,
    QuestStatus,
    QuestDifficulty,
    ObjectiveType,
    FactionAffiliation,
    QuestReward,
    QuestObjective,
)

logger = logging.getLogger("npc_quest_engine")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)

MAX_LOG_ENTRIES = 200
MAX_ACTIVE_QUESTS_PER_NPC = 3
MAX_QUEST_AGE_TICKS = 100
ABANDON_CHANCE = 0.05
SETBACK_CHANCE = 0.02
MAX_QUEST_AGE_HARD_CAP = 120
NPC_OBJECTIVE_SCALE = (
    0.25  # NPCs get 25% of original targets (more achievable for 1/tick autonomy)
)

# Skill-to-faction keyword mapping for proper cross-referencing
SKILL_FACTION_KEYWORDS: Dict[str, List[str]] = {
    "diplomacy": ["diplomatic", "diplomacy"],
    "negotiation": ["diplomatic", "negotiation"],
    "military": ["military"],
    "tactics": ["military"],
    "research": ["research", "scientific"],
    "technology": ["research", "technological"],
    "culture": ["cultural"],
    "consciousness": ["consciousness"],
    "prophecy": ["prophecy"],
    "exploration": ["discovery", "exploration"],
    "economics": ["economic"],
    "preservation": ["stability", "preservation"],
}

PERSONALITY_OBJECTIVE_MAP: Dict[str, List[ObjectiveType]] = {
    "strategist": [ObjectiveType.DIPLOMATIC, ObjectiveType.ECONOMIC],
    "warrior": [ObjectiveType.MILITARY, ObjectiveType.SURVIVAL],
    "scholar": [ObjectiveType.RESEARCH, ObjectiveType.TECHNOLOGICAL],
    "diplomat": [ObjectiveType.DIPLOMATIC, ObjectiveType.ALLIANCE],
    "mystic": [ObjectiveType.CONSCIOUSNESS, ObjectiveType.PROPHECY],
    "explorer": [ObjectiveType.EXPLORATION, ObjectiveType.ALLIANCE],
    "artist": [ObjectiveType.CULTURAL],
    "leader": [ObjectiveType.ALLIANCE, ObjectiveType.DIPLOMATIC],
}

FACTION_AFFILIATION_MAP: Dict[str, FactionAffiliation] = {
    "diplomatic_corps": FactionAffiliation.DIPLOMATIC_CORPS,
    "military_command": FactionAffiliation.MILITARY_COMMAND,
    "research_division": FactionAffiliation.RESEARCH_DIVISION,
    "cultural_ministry": FactionAffiliation.CULTURAL_MINISTRY,
    "consciousness_collective": FactionAffiliation.CONSCIOUSNESS_COLLECTIVE,
    "prophecy_keepers": FactionAffiliation.PROPHECY_KEEPERS,
}

DEFAULT_NPC_STATS = {
    "quests_accepted": 0,
    "quests_completed": 0,
    "quests_failed": 0,
    "total_resources_earned": 0,
    "total_tech_points_earned": 0,
}

QUEST_CHAINS = {
    "first_contact_protocol": {
        "chain_id": "diplomatic_ascension",
        "chain_name": "Diplomatic Ascension",
        "chain_position": 1,
        "chain_total": 3,
        "next_quest_type": "treaty_negotiation",
        "narrative_link": "First contact established — now formalize relations through treaties",
        "bonus_rewards": {"resources": 50, "reputation": 0.05},
    },
    "treaty_negotiation:diplomatic_ascension": {
        "chain_id": "diplomatic_ascension",
        "chain_name": "Diplomatic Ascension",
        "chain_position": 2,
        "chain_total": 3,
        "next_quest_type": "alliance_of_equals",
        "narrative_link": "Treaties signed — forge a true alliance of equals",
        "bonus_rewards": {"resources": 100, "reputation": 0.1},
    },
    "defense_stronghold": {
        "chain_id": "iron_bulwark",
        "chain_name": "Iron Bulwark",
        "chain_position": 1,
        "chain_total": 3,
        "next_quest_type": "fortress_unbreakable",
        "narrative_link": "Borders held — now build an unbreakable fortress",
        "bonus_rewards": {"resources": 75, "morale_boost": 0.05},
    },
    "fortress_unbreakable:iron_bulwark": {
        "chain_id": "iron_bulwark",
        "chain_name": "Iron Bulwark",
        "chain_position": 2,
        "chain_total": 3,
        "next_quest_type": "invincible_armada",
        "narrative_link": "Fortress stands — project power with an invincible armada",
        "bonus_rewards": {"resources": 200, "stability_boost": 0.1},
    },
    "cultural_renaissance": {
        "chain_id": "cultural_zenith",
        "chain_name": "Cultural Zenith",
        "chain_position": 1,
        "chain_total": 3,
        "next_quest_type": "artistic_enlightenment",
        "narrative_link": "Culture blooms — pursue artistic enlightenment",
        "bonus_rewards": {"resources": 100, "morale_boost": 0.08},
    },
    "artistic_enlightenment:cultural_zenith": {
        "chain_id": "cultural_zenith",
        "chain_name": "Cultural Zenith",
        "chain_position": 2,
        "chain_total": 3,
        "next_quest_type": "universal_culture",
        "narrative_link": "Enlightenment achieved — spread culture universally",
        "bonus_rewards": {"resources": 200, "reputation": 0.15},
    },
    "prophecy_fulfillment": {
        "chain_id": "destiny_unbound",
        "chain_name": "Destiny Unbound",
        "chain_position": 1,
        "chain_total": 2,
        "next_quest_type": "fate_weavers",
        "narrative_link": "Prophecies fulfilled — master the art of fate weaving",
        "bonus_rewards": {"resources": 150, "reputation": 0.1},
    },
    "rival_elimination": {
        "chain_id": "military_supremacy",
        "chain_name": "Military Supremacy",
        "chain_position": 1,
        "chain_total": 2,
        "next_quest_type": "dominion_assured",
        "narrative_link": "Rivals eliminated — secure permanent dominion",
        "bonus_rewards": {"resources": 250, "stability_boost": 0.1},
    },
    "resource_abundance": {
        "chain_id": "economic_dominance",
        "chain_name": "Economic Dominance",
        "chain_position": 1,
        "chain_total": 2,
        "next_quest_type": "infinite_wealth",
        "narrative_link": "Resources gathered — pursue infinite wealth",
        "bonus_rewards": {"resources": 100, "tech_points": 25},
    },
    "consciousness_evolution": {
        "chain_id": "transcendent_awakening",
        "chain_name": "Transcendent Awakening",
        "chain_position": 1,
        "chain_total": 2,
        "next_quest_type": "transcendence",
        "narrative_link": "Consciousness evolved — seek ultimate transcendence",
        "bonus_rewards": {
            "resources": 200,
            "morale_boost": 0.1,
            "stability_boost": 0.1,
        },
    },
    "alliance_of_equals:diplomatic_ascension": {
        "chain_id": "diplomatic_ascension",
        "chain_name": "Diplomatic Ascension",
        "chain_position": 3,
        "chain_total": 3,
        "next_quest_type": None,
        "narrative_link": "Alliance forged — diplomatic ascension complete",
        "bonus_rewards": {"resources": 300, "reputation": 0.2, "morale_boost": 0.1},
    },
    "invincible_armada:iron_bulwark": {
        "chain_id": "iron_bulwark",
        "chain_name": "Iron Bulwark",
        "chain_position": 3,
        "chain_total": 3,
        "next_quest_type": None,
        "narrative_link": "Armada unleashed — iron bulwark complete",
        "bonus_rewards": {
            "resources": 400,
            "stability_boost": 0.15,
            "morale_boost": 0.1,
        },
    },
    "universal_culture:cultural_zenith": {
        "chain_id": "cultural_zenith",
        "chain_name": "Cultural Zenith",
        "chain_position": 3,
        "chain_total": 3,
        "next_quest_type": None,
        "narrative_link": "Culture universal — cultural zenith complete",
        "bonus_rewards": {"resources": 300, "reputation": 0.2, "morale_boost": 0.1},
    },
}


class NPCQuestEngine:
    """Autonomous quest engine for NPC characters backed by Redis."""

    def __init__(self, quest_system: QuestSystem, redis_client=None):
        self.quest_system = quest_system
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis(
                host="localhost", port=6379, db=0, decode_responses=True
            )
        return self._redis

    def _quest_to_dict(self, quest: Quest) -> Dict[str, Any]:
        return quest.to_dict()

    def _dict_to_quest_progress(self, data: Dict[str, str]) -> Dict[str, int]:
        return {k: int(v) for k, v in data.items()}

    def _log_event(self, event: Dict[str, Any]) -> None:
        try:
            r = self._get_redis()
            score = time.time()
            r.zadd("npc_quests:log", {json.dumps(event, default=str): score})
            r.zremrangebyrank("npc_quests:log", 0, -(MAX_LOG_ENTRIES + 1))
        except redis.RedisError as exc:
            logger.warning("Failed to log quest event: %s", exc)

    def _init_stats(self, char_id: str) -> None:
        try:
            r = self._get_redis()
            key = f"npc_quests:stats:{char_id}"
            existing = r.hgetall(key)
            for stat, default in DEFAULT_NPC_STATS.items():
                if stat not in existing:
                    r.hset(key, stat, default)
        except redis.RedisError as exc:
            logger.warning("Failed to init stats for %s: %s", char_id, exc)

    def _incr_stat(self, char_id: str, stat: str, amount: int = 1) -> None:
        try:
            r = self._get_redis()
            r.hincrby(f"npc_quests:stats:{char_id}", stat, amount)
        except redis.RedisError as exc:
            logger.warning("Failed to incr stat %s for %s: %s", stat, char_id, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_quest_for_npc(
        self, char_id: str, affiliation: str, personality_type: str
    ) -> Optional[str]:
        """
        Score available quests for an NPC and return the best quest_id.

        Scoring:
            a) Faction alignment     +3 if quest faction matches NPC affiliation
            b) Difficulty scaling     ambition * difficulty_tier
            c) Personality match      +2 per matching objective type
            d) Random exploration     +random(0, 1.5)
        """
        try:
            available = self.quest_system.get_available_quests(char_id)
        except Exception as exc:
            logger.warning("get_available_quests failed for %s: %s", char_id, exc)
            return None

        if not available:
            return None

        safe_personality = (personality_type or "default").lower()
        safe_affiliation = (affiliation or "none").lower()
        preferred_types = PERSONALITY_OBJECTIVE_MAP.get(safe_personality, [])

        npc_faction = FACTION_AFFILIATION_MAP.get(
            safe_affiliation, FactionAffiliation.NONE
        )

        scored: List[Tuple[float, str]] = []
        for quest in available:
            score = 0.0

            # (a) Faction alignment
            if (
                quest.faction_affiliation == npc_faction
                and npc_faction != FactionAffiliation.NONE
            ):
                score += 3.0

            # (b) Difficulty scaling — use quest difficulty tier as multiplier
            score += quest.difficulty.value * 0.5

            # (c) Personality-objective match
            for obj in quest.objectives:
                if obj.objective_type in preferred_types:
                    score += 2.0

            # (d) Random exploration factor
            score += random.uniform(0, 1.5)

            scored.append((score, quest.quest_id))

        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[0][1] if scored else None

    def _scale_quest_for_npc(self, quest_data: Dict) -> Dict:
        """Scale objective targets down for autonomous NPC progression.

        The quest library was designed for interactive gameplay with high targets
        (75, 100, 1000, 5000). NPCs progress ~1-2 per tick, so these are
        impossible within MAX_QUEST_AGE_TICKS. Scale by NPC_OBJECTIVE_SCALE.
        """
        for obj in quest_data.get("objectives", []):
            original_target = obj.get("target", 1)
            if original_target > 5:
                obj["target"] = max(3, int(original_target * NPC_OBJECTIVE_SCALE))
        return quest_data

    def accept_quest(
        self,
        char_id: str,
        quest_id: str,
        chain_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Accept a quest on behalf of an NPC and persist to Redis.

        Does NOT mutate the shared QuestSystem in-memory state.
        Reads the quest template from QuestSystem.quests and writes
        an independent copy to Redis per-NPC keys.

        Returns (success, message).
        """
        quest = self.quest_system.quests.get(quest_id)
        if quest is None:
            return False, f"Quest '{quest_id}' not found in library"

        if quest.status not in [QuestStatus.AVAILABLE, QuestStatus.LOCKED]:
            return (
                False,
                f"Quest '{quest.title}' is not available (status={quest.status.value})",
            )

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"

            existing = r.hget(active_key, quest_id)
            if existing is not None:
                return False, f"Quest '{quest_id}' already active for NPC {char_id}"

            quest_dict = self._quest_to_dict(quest)
            quest_dict = self._scale_quest_for_npc(quest_dict)
            quest_dict["status"] = QuestStatus.ACCEPTED.value
            if chain_meta:
                quest_dict["chain_id"] = chain_meta.get("chain_id", "")
                quest_dict["chain_position"] = chain_meta.get("chain_position", 0)
                quest_dict["chain_total"] = chain_meta.get("chain_total", 0)
                quest_dict["narrative_link"] = chain_meta.get("narrative_link", "")
                quest_dict["priority_boost"] = chain_meta.get("priority_boost", 0.0)
            quest_json = json.dumps(quest_dict, default=str)

            r.hset(active_key, quest_id, quest_json)

            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"
            pipe = r.pipeline()
            for obj_data in quest_dict.get("objectives", []):
                obj_id = obj_data.get("objective_id", "")
                if obj_id:
                    pipe.hset(progress_key, obj_id, 0)
            pipe.hset(progress_key, "_tick_count", 0)
            pipe.execute()

            self._init_stats(char_id)
            self._incr_stat(char_id, "quests_accepted")

            self._log_event(
                {
                    "event": "quest_accepted",
                    "char_id": char_id,
                    "quest_id": quest_id,
                    "quest_title": quest.title,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            logger.info("NPC %s accepted quest %s", char_id, quest_id)
        except redis.RedisError as exc:
            logger.error(
                "Redis error accepting quest %s for %s: %s", quest_id, char_id, exc
            )
            return False, f"Redis error: {exc}"

        return True, f"Accepted quest: {quest.title}"

    def progress_quest(
        self,
        char_id: str,
        quest_id: str,
        objective_type: ObjectiveType,
        amount: int = 1,
    ) -> Dict[str, Any]:
        """
        Advance all objectives of *objective_type* in an NPC's active quest.

        Returns dict with: quest_id, objectives_progressed, any_completed, quest_completed.
        """
        result: Dict[str, Any] = {
            "quest_id": quest_id,
            "objectives_progressed": 0,
            "any_completed": False,
            "quest_completed": False,
        }

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            quest_json = r.hget(active_key, quest_id)
            if quest_json is None:
                logger.warning("No active quest %s for NPC %s", quest_id, char_id)
                return result

            quest_data = json.loads(quest_json)
            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"

            for obj_data in quest_data.get("objectives", []):
                obj_type_str = obj_data.get("objective_type", "")
                if obj_type_str != objective_type.value:
                    continue

                obj_id = obj_data["objective_id"]
                target = obj_data.get("target", 1)

                current_raw = r.hget(progress_key, obj_id)
                if current_raw is None:
                    continue
                current = int(current_raw)
                if current >= target:
                    continue

                new_val = min(current + amount, target)
                r.hset(progress_key, obj_id, new_val)
                obj_data["current_progress"] = new_val
                result["objectives_progressed"] += 1

                if new_val >= target:
                    obj_data["completed"] = True
                    result["any_completed"] = True

            r.hset(active_key, quest_id, json.dumps(quest_data, default=str))

            # Check auto-completion: all mandatory objectives done?
            all_mandatory_done = True
            for obj_data in quest_data.get("objectives", []):
                if not obj_data.get("optional", False):
                    if int(obj_data.get("current_progress", 0)) < obj_data.get(
                        "target", 1
                    ):
                        all_mandatory_done = False
                        break

            if all_mandatory_done:
                result["quest_completed"] = True
                logger.info("Quest %s auto-completing for NPC %s", quest_id, char_id)

        except redis.RedisError as exc:
            logger.error(
                "Redis error progressing quest %s for %s: %s", quest_id, char_id, exc
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(
                "Data error progressing quest %s for %s: %s", quest_id, char_id, exc
            )

        return result

    def complete_quest(
        self, char_id: str, quest_id: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Complete an NPC quest, move from active to completed in Redis,
        apply rewards to world_state, and update stats.

        Returns (success, message, rewards_dict or None).
        """
        quest_data = None
        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            quest_json = r.hget(active_key, quest_id)
            if not quest_json:
                return (
                    False,
                    f"Quest '{quest_id}' not found in active quests for {char_id}",
                    None,
                )
            quest_data = json.loads(quest_json)
        except redis.RedisError as exc:
            logger.error(
                "Redis error reading quest %s for %s: %s", quest_id, char_id, exc
            )
            return False, f"Redis error reading quest", None
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error(
                "Data error reading quest %s for %s: %s", quest_id, char_id, exc
            )
            return False, f"Data error reading quest", None

        if quest_data.get("status") != QuestStatus.ACCEPTED.value:
            return (
                False,
                f"Quest is not in progress (status={quest_data.get('status')})",
                None,
            )

        all_mandatory_complete = True
        incomplete_names = []
        for obj_data in quest_data.get("objectives", []):
            if not obj_data.get("optional", False):
                current = int(obj_data.get("current_progress", 0))
                target = obj_data.get("target", 1)
                if current < target:
                    all_mandatory_complete = False
                    incomplete_names.append(
                        obj_data.get(
                            "description", obj_data.get("objective_id", "unknown")
                        )
                    )

        if not all_mandatory_complete:
            return (
                False,
                f"Cannot complete quest. Incomplete objectives: {', '.join(incomplete_names)}",
                None,
            )

        quest_rewards_raw = quest_data.get("rewards", {})
        rewards = QuestReward(
            resources=int(quest_rewards_raw.get("resources", 0)),
            reputation=float(quest_rewards_raw.get("reputation", 0.0)),
            morale_boost=float(quest_rewards_raw.get("morale_boost", 0.0)),
            stability_boost=float(quest_rewards_raw.get("stability_boost", 0.0)),
            tech_points=int(quest_rewards_raw.get("tech_points", 0)),
            unlocked_quests=quest_rewards_raw.get("unlocked_quests", []),
            unlocked_features=quest_rewards_raw.get("unlocked_features", []),
            special_rewards=quest_rewards_raw.get("special_rewards", {}),
        )

        rewards_dict = rewards.to_dict()

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            completed_key = f"npc_quests:completed:{char_id}"
            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"

            quest_data["status"] = QuestStatus.COMPLETED.value
            completed_json = json.dumps(quest_data, default=str)
            r.lpush(completed_key, completed_json)
            r.hdel(active_key, quest_id)

            r.delete(progress_key)

            if rewards:
                self._apply_quest_rewards_to_world(rewards)

            self._incr_stat(char_id, "quests_completed")
            if rewards:
                self._incr_stat(char_id, "total_resources_earned", rewards.resources)
                self._incr_stat(
                    char_id, "total_tech_points_earned", rewards.tech_points
                )

            self._log_event(
                {
                    "event": "quest_completed",
                    "char_id": char_id,
                    "quest_id": quest_id,
                    "rewards": rewards_dict,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            logger.info("NPC %s completed quest %s", char_id, quest_id)

            chain_id = quest_data.get("chain_id", "") if quest_data else ""

            chain_key = quest_id
            if chain_id:
                chain_key = f"{quest_id}:{chain_id}"

            chain_entry = QUEST_CHAINS.get(chain_key)
            if not chain_entry:
                chain_entry = QUEST_CHAINS.get(quest_id)

            if chain_entry:
                bonus = chain_entry.get("bonus_rewards", {})
                if bonus.get("resources"):
                    rewards_dict["bonus_resources"] = bonus["resources"]
                    self._incr_stat(
                        char_id, "total_resources_earned", bonus["resources"]
                    )
                if bonus.get("reputation"):
                    rewards_dict["bonus_reputation"] = bonus["reputation"]
                if bonus.get("morale_boost"):
                    rewards_dict["bonus_morale_boost"] = bonus["morale_boost"]
                if bonus.get("stability_boost"):
                    rewards_dict["bonus_stability_boost"] = bonus["stability_boost"]
                if bonus.get("tech_points"):
                    rewards_dict["bonus_tech_points"] = bonus["tech_points"]

                c_id = chain_entry["chain_id"]
                chain_progress_key = f"npc_quests:chain_progress:{char_id}:{c_id}"
                r.hset(chain_progress_key, "chain_id", c_id)
                r.hset(chain_progress_key, "chain_name", chain_entry["chain_name"])
                r.hset(
                    chain_progress_key,
                    "current_position",
                    str(chain_entry["chain_position"]),
                )
                r.hset(
                    chain_progress_key,
                    "chain_total",
                    str(chain_entry["chain_total"]),
                )

                is_chain_final = (
                    chain_entry["chain_position"] >= chain_entry["chain_total"]
                )
                status = "completed" if is_chain_final else "active"
                r.hset(chain_progress_key, "status", status)

                self._log_event(
                    {
                        "event": "chain_progress",
                        "char_id": char_id,
                        "quest_id": quest_id,
                        "chain_id": c_id,
                        "chain_name": chain_entry["chain_name"],
                        "chain_position": chain_entry["chain_position"],
                        "chain_total": chain_entry["chain_total"],
                        "status": status,
                        "narrative_link": chain_entry["narrative_link"],
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                logger.info(
                    "NPC %s chain %s progress: %d/%d",
                    char_id,
                    c_id,
                    chain_entry["chain_position"],
                    chain_entry["chain_total"],
                )

                next_quest_type = chain_entry.get("next_quest_type")
                if next_quest_type and not is_chain_final:
                    next_quest = self.quest_system.quests.get(next_quest_type)
                    if next_quest:
                        next_chain_meta = {
                            "chain_id": c_id,
                            "chain_name": chain_entry["chain_name"],
                            "chain_position": chain_entry["chain_position"] + 1,
                            "chain_total": chain_entry["chain_total"],
                            "narrative_link": chain_entry["narrative_link"],
                            "priority_boost": 0.3,
                        }
                        accept_ok, accept_msg = self.accept_quest(
                            char_id, next_quest_type, chain_meta=next_chain_meta
                        )
                        if accept_ok:
                            logger.info(
                                "NPC %s chain quest triggered: %s -> %s",
                                char_id,
                                quest_id,
                                next_quest_type,
                            )
                        else:
                            logger.warning(
                                "NPC %s chain quest %s accept failed: %s",
                                char_id,
                                next_quest_type,
                                accept_msg,
                            )
                    else:
                        logger.warning(
                            "NPC %s chain next quest %s not found in library",
                            char_id,
                            next_quest_type,
                        )

        except redis.RedisError as exc:
            logger.error(
                "Redis error completing quest %s for %s: %s", quest_id, char_id, exc
            )
            return False, f"Redis error completing quest", None

        quest_title = quest_data.get("title", quest_id) if quest_data else quest_id
        return True, f"Quest completed: {quest_title}!", rewards_dict

    def abandon_quest(
        self, char_id: str, quest_id: str, reason: str = "timeout"
    ) -> Tuple[bool, str]:
        """
        Abandon an NPC quest — move from active to failed list in Redis.

        Returns (success, message).
        """
        quest_title = quest_id
        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            quest_json = r.hget(active_key, quest_id)
            if not quest_json:
                return (
                    False,
                    f"Quest '{quest_id}' not found in active quests for {char_id}",
                )

            quest_data = json.loads(quest_json)
            quest_title = quest_data.get("title", quest_id)

            if quest_data.get("status") != QuestStatus.ACCEPTED.value:
                return (
                    False,
                    f"Quest '{quest_title}' is not in progress (status={quest_data.get('status')})",
                )

            quest_data["status"] = QuestStatus.ABANDONED.value
            updated_json = json.dumps(quest_data)

            failed_key = f"npc_quests:failed:{char_id}"
            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"

            r.lpush(failed_key, updated_json)
            r.hdel(active_key, quest_id)
            r.delete(progress_key)

            self._incr_stat(char_id, "quests_failed")

            self._log_event(
                {
                    "event": "quest_abandoned",
                    "char_id": char_id,
                    "quest_id": quest_id,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            logger.info("NPC %s abandoned quest %s (%s)", char_id, quest_id, reason)

        except redis.RedisError as exc:
            logger.error(
                "Redis error abandoning quest %s for %s: %s", quest_id, char_id, exc
            )

        return True, f"Abandoned quest: {quest_title}"

    def tick_npc_quests(self, npc_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Main autonomous tick — process all NPCs.

        Each NPC dict: {char_id, affiliation, personality_type, ambition, skills}.

        For each NPC:
            a) No active quest → try accept one via select_quest_for_npc
            b) For each active quest, simulate progress:
                - Base 1 per tick
                - +1 if NPC skill matches quest faction
                - Ambition bonus: high ambition → chance of extra progress
                - 5% setback chance → 0 progress this tick
            c) If quest active > MAX_QUEST_AGE_TICKS → 30% abandon chance
            d) Auto-complete if all mandatory objectives done

        Returns summary: {npcs_processed, quests_accepted, quests_progressed,
                          quests_completed, quests_abandoned, errors}
        """
        summary = {
            "npcs_processed": 0,
            "quests_accepted": 0,
            "quests_progressed": 0,
            "quests_completed": 0,
            "quests_abandoned": 0,
            "errors": 0,
        }

        for npc in npc_list:
            char_id = npc.get("char_id", "")
            if not char_id:
                summary["errors"] += 1
                continue

            affiliation = npc.get("affiliation") or "none"
            personality = npc.get("personality_type") or "default"
            ambition = float(npc.get("ambition", 0.5))
            skills = npc.get("skills", [])

            try:
                self._init_stats(char_id)
                r = self._get_redis()

                # (a) Check active quests — try to accept if none
                active_key = f"npc_quests:active:{char_id}"
                active_quests_raw = r.hgetall(active_key) or {}
                active_count = len(active_quests_raw)

                if active_count == 0:
                    chosen = self.select_quest_for_npc(
                        char_id, affiliation, personality
                    )
                    if chosen:
                        ok, _ = self.accept_quest(char_id, chosen)
                        if ok:
                            summary["quests_accepted"] += 1
                            active_quests_raw = r.hgetall(active_key) or {}

                # (b) Progress each active quest
                for qid, quest_json_str in list(active_quests_raw.items()):
                    try:
                        quest_data = json.loads(quest_json_str)
                    except json.JSONDecodeError:
                        summary["errors"] += 1
                        continue

                    # Check quest age for potential abandonment
                    progress_key = f"npc_quests:progress:{char_id}:{qid}"
                    tick_count = int(r.hget(progress_key, "_tick_count") or 0)
                    tick_count += 1
                    r.hset(progress_key, "_tick_count", tick_count)

                    if tick_count > MAX_QUEST_AGE_TICKS:
                        if random.random() < ABANDON_CHANCE:
                            self.abandon_quest(char_id, qid, reason="timeout")
                            summary["quests_abandoned"] += 1
                            continue

                    # Hard age cap — force resolve quests that survived soft timeout too long
                    if tick_count > MAX_QUEST_AGE_HARD_CAP:
                        # Check if all mandatory objectives are done for auto-complete
                        all_done = True
                        for obj_data in quest_data.get("objectives", []):
                            if not obj_data.get("optional", False):
                                if int(
                                    obj_data.get("current_progress", 0)
                                ) < obj_data.get("target", 1):
                                    all_done = False
                                    break
                        if all_done:
                            self.complete_quest(char_id, qid)
                            summary["quests_completed"] += 1
                        else:
                            self.abandon_quest(char_id, qid, reason="max_age_exceeded")
                            summary["quests_abandoned"] += 1
                        continue

                        # Setback check
                        if random.random() < SETBACK_CHANCE:
                            continue

                        # Calculate progress amount
                        progress_amount = 1
                        quest_faction_str = (
                            quest_data.get("faction_affiliation") or "none"
                        ).lower()
                        # Proper skill-faction keyword matching (fixes substring bug)
                        for sk in skills or []:
                            keywords = SKILL_FACTION_KEYWORDS.get(
                                (sk or "").lower(), [(sk or "").lower()]
                            )
                            if any(kw in quest_faction_str for kw in keywords):
                                progress_amount += 1
                                break
                        # Ambition bonus: chance of extra progress proportional to ambition
                        if ambition > 0.7 and random.random() < ambition * 0.4:
                            progress_amount += 1

                        # Progress each objective type present in the quest
                        objective_types_seen = set()
                        for obj_data in quest_data.get("objectives", []):
                            obj_type_val = obj_data.get("objective_type", "")
                            if (
                                obj_type_val
                                and obj_type_val not in objective_types_seen
                            ):
                                objective_types_seen.add(obj_type_val)
                                try:
                                    obj_type = ObjectiveType(obj_type_val)
                                except ValueError:
                                    continue

                                result = self.progress_quest(
                                    char_id, qid, obj_type, progress_amount
                                )
                                if result["objectives_progressed"] > 0:
                                    summary["quests_progressed"] += 1

                                # (d) Auto-complete
                                if result["quest_completed"]:
                                    self.complete_quest(char_id, qid)
                                    summary["quests_completed"] += 1
                                    break

                summary["npcs_processed"] += 1

            except redis.RedisError as exc:
                logger.error("Redis error in tick for NPC %s: %s", char_id, exc)
                summary["errors"] += 1
            except Exception as exc:
                logger.error("Unexpected error in tick for NPC %s: %s", char_id, exc)
                summary["errors"] += 1

        logger.info(
            "Tick complete: %d NPCs, %d accepted, %d progressed, %d completed, %d abandoned, %d errors",
            summary["npcs_processed"],
            summary["quests_accepted"],
            summary["quests_progressed"],
            summary["quests_completed"],
            summary["quests_abandoned"],
            summary["errors"],
        )
        return summary

    def get_npc_quest_summary(self, char_id: str) -> Dict[str, Any]:
        """
        Return {active_quests, completed_count, failed_count, stats} from Redis.
        """
        summary: Dict[str, Any] = {
            "active_quests": [],
            "completed_count": 0,
            "failed_count": 0,
            "stats": dict(DEFAULT_NPC_STATS),
        }

        try:
            r = self._get_redis()

            active_raw = r.hgetall(f"npc_quests:active:{char_id}") or {}
            for qid, qjson in active_raw.items():
                try:
                    summary["active_quests"].append(json.loads(qjson))
                except json.JSONDecodeError:
                    pass

            summary["completed_count"] = r.llen(f"npc_quests:completed:{char_id}") or 0
            summary["failed_count"] = r.llen(f"npc_quests:failed:{char_id}") or 0

            stats_raw = r.hgetall(f"npc_quests:stats:{char_id}") or {}
            for k, v in stats_raw.items():
                try:
                    summary["stats"][k] = int(v)
                except (ValueError, TypeError):
                    pass

        except redis.RedisError as exc:
            logger.error("Redis error getting summary for %s: %s", char_id, exc)

        return summary

    def get_quest_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return latest entries from the npc_quests:log ZSET."""
        entries: List[Dict[str, Any]] = []
        try:
            r = self._get_redis()
            raw = r.zrevrange("npc_quests:log", 0, limit - 1)
            for item in raw:
                try:
                    entries.append(json.loads(item))
                except json.JSONDecodeError:
                    pass
        except redis.RedisError as exc:
            logger.error("Redis error reading quest log: %s", exc)
        return entries

    # ------------------------------------------------------------------
    # Internal: world-state reward application
    # ------------------------------------------------------------------

    def _apply_quest_rewards_to_world(self, rewards: QuestReward) -> Dict[str, Any]:
        """
        Apply quest reward deltas to Redis world_state hash.

        Keys updated: morale, stability, treasury, tech_level.
        Returns the applied deltas.
        """
        deltas: Dict[str, Any] = {}
        try:
            r = self._get_redis()

            if rewards.morale_boost != 0.0:
                current = float(r.hget("world_state", "morale") or 0.5)
                new_val = min(1.0, max(0.0, current + rewards.morale_boost))
                r.hset("world_state", "morale", new_val)
                deltas["morale"] = rewards.morale_boost

            if rewards.stability_boost != 0.0:
                current = float(r.hget("world_state", "stability") or 0.5)
                new_val = min(1.0, max(0.0, current + rewards.stability_boost))
                r.hset("world_state", "stability", new_val)
                deltas["stability"] = rewards.stability_boost

            if rewards.resources != 0:
                current = int(r.hget("world_state", "treasury") or 0)
                r.hset("world_state", "treasury", current + rewards.resources)
                deltas["treasury"] = rewards.resources

            if rewards.tech_points != 0:
                current = int(r.hget("world_state", "tech_level") or 0)
                r.hset("world_state", "tech_level", current + rewards.tech_points)
                deltas["tech_level"] = rewards.tech_points

            logger.debug("Applied world rewards: %s", deltas)

        except redis.RedisError as exc:
            logger.error("Redis error applying world rewards: %s", exc)

        return deltas


# ----------------------------------------------------------------------
# Standalone bootstrap for testing
# ----------------------------------------------------------------------


def create_npc_quest_engine(redis_client=None) -> NPCQuestEngine:
    """Create an NPCQuestEngine with the full quest library loaded."""
    from quests import create_quest_library

    quest_system = create_quest_library()
    return NPCQuestEngine(quest_system, redis_client=redis_client)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except redis.ConnectionError:
        print("Redis not available — exiting demo.")
        raise SystemExit(1)

    engine = create_npc_quest_engine(redis_client=r)

    demo_npcs = [
        {
            "char_id": "npc_sarek",
            "affiliation": "diplomatic_corps",
            "personality_type": "diplomat",
            "ambition": 0.8,
            "skills": ["diplomacy", "negotiation"],
        },
        {
            "char_id": "npc_koloth",
            "affiliation": "military_command",
            "personality_type": "warrior",
            "ambition": 0.9,
            "skills": ["military", "tactics"],
        },
        {
            "char_id": "npc_tpol",
            "affiliation": "research_division",
            "personality_type": "scholar",
            "ambition": 0.6,
            "skills": ["research", "technology"],
        },
    ]

    for _ in range(5):
        result = engine.tick_npc_quests(demo_npcs)
        print(f"Tick result: {result}")

    for npc in demo_npcs:
        summary = engine.get_npc_quest_summary(npc["char_id"])
        print(
            f"\n{npc['char_id']} summary: {json.dumps(summary, indent=2, default=str)}"
        )

    log = engine.get_quest_log(limit=10)
    print(f"\nQuest log ({len(log)} entries):")
    for entry in log:
        print(
            f"  [{entry.get('event')}] {entry.get('char_id')} -> {entry.get('quest_id', entry.get('reason', ''))}"
        )
