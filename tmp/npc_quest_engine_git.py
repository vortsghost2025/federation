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
MAX_QUEST_AGE_TICKS = 15
ABANDON_CHANCE = 0.30
SETBACK_CHANCE = 0.05

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

        preferred_types = PERSONALITY_OBJECTIVE_MAP.get(personality_type.lower(), [])

        npc_faction = FACTION_AFFILIATION_MAP.get(
            affiliation.lower(), FactionAffiliation.NONE
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

    def accept_quest(self, char_id: str, quest_id: str) -> Tuple[bool, str]:
        """
        Accept a quest on behalf of an NPC and persist to Redis.

        Returns (success, message).
        """
        success, message = self.quest_system.accept_quest(
            char_id, quest_id, current_turn=0
        )
        if not success:
            return False, message

        quest = self.quest_system.quests.get(quest_id)
        if quest is None:
            return False, f"Quest {quest_id} vanished after accept"

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            quest_json = json.dumps(self._quest_to_dict(quest), default=str)

            r.hset(active_key, quest_id, quest_json)

            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"
            pipe = r.pipeline()
            for obj in quest.objectives:
                pipe.hset(progress_key, obj.objective_id, 0)
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

        return True, message

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
        success, message, rewards = self.quest_system.complete_quest(
            char_id, quest_id, current_turn=0
        )
        if not success:
            return False, message, None

        rewards_dict = rewards.to_dict() if rewards else {}

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            completed_key = f"npc_quests:completed:{char_id}"
            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"

            quest_json = r.hget(active_key, quest_id)
            if quest_json:
                r.lpush(completed_key, quest_json)
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

        except redis.RedisError as exc:
            logger.error(
                "Redis error completing quest %s for %s: %s", quest_id, char_id, exc
            )

        return True, message, rewards_dict

    def abandon_quest(
        self, char_id: str, quest_id: str, reason: str = "timeout"
    ) -> Tuple[bool, str]:
        """
        Abandon an NPC quest — move from active to failed list in Redis.

        Returns (success, message).
        """
        success, message = self.quest_system.abandon_quest(
            char_id, quest_id, current_turn=0
        )
        if not success:
            return False, message

        try:
            r = self._get_redis()
            active_key = f"npc_quests:active:{char_id}"
            failed_key = f"npc_quests:failed:{char_id}"
            progress_key = f"npc_quests:progress:{char_id}:{quest_id}"

            quest_json = r.hget(active_key, quest_id)
            if quest_json:
                r.lpush(failed_key, quest_json)
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

        return True, message

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

            affiliation = npc.get("affiliation", "none")
            personality = npc.get("personality_type", "default")
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

                    # Setback check
                    if random.random() < SETBACK_CHANCE:
                        continue

                    # Calculate progress amount
                    progress_amount = 1
                    quest_faction_str = quest_data.get("faction_affiliation", "none")
                    if any(
                        skill.lower() in quest_faction_str.lower() for skill in skills
                    ):
                        progress_amount += 1

                    # Ambition bonus: chance of extra progress proportional to ambition
                    if ambition > 0.7 and random.random() < ambition * 0.4:
                        progress_amount += 1

                    # Progress each objective type present in the quest
                    objective_types_seen = set()
                    for obj_data in quest_data.get("objectives", []):
                        obj_type_val = obj_data.get("objective_type", "")
                        if obj_type_val and obj_type_val not in objective_types_seen:
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
