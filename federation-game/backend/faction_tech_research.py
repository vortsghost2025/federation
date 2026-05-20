#!/usr/bin/env python3
"""Faction Tech Research Bridge — connects faction_ai.py to technology.py.

Enables factions to autonomously research and unlock real technologies from the
TechTree.  Each faction_id doubles as a player_id inside TechTree so no
refactoring of the technology module is required.  All durable state lives in
Redis so research survives process restarts.

Redis key schema
----------------
faction_tech:active:{faction_id}    STRING  JSON of current ResearchProject
faction_tech:completed:{faction_id} SET     completed tech_id strings
faction_tech:points:{faction_id}    STRING  float – accumulated research pts
faction_tech:log                    ZSET    research event JSON, score=ts (cap 100)
faction_tech:unlocks:{faction_id}   SET     unlocked feature / perk strings
"""

import json
import os
import time
import random
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

import redis
from technology import TechTree, Technology, ResearchProject, ResearchPhilosophy, Era
from faction_ai import FACTION_IDEOLOGY

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

LOG_CAP = 100

IDEOLOGY_PHILOSOPHY_MAP: Dict[str, ResearchPhilosophy] = {
    "diplomatic": ResearchPhilosophy.CULTURAL,
    "military": ResearchPhilosophy.MILITARY,
    "cultural": ResearchPhilosophy.CULTURAL,
    "scientific": ResearchPhilosophy.SCIENTIFIC,
    "spiritual": ResearchPhilosophy.CONSCIOUSNESS,
    "economic": ResearchPhilosophy.SCIENTIFIC,
    "discovery": ResearchPhilosophy.SCIENTIFIC,
    "stability": ResearchPhilosophy.MILITARY,
}

_BONUS_WORLD_MAP: Dict[str, Tuple[str, float]] = {
    "morale": ("morale", 2.0),
    "resources": ("resource_abundance", 3.0),
    "stability": ("stability", 2.0),
    "military_power": ("threat_level", 1.5),
    "research_speed": ("anomaly_activity", 1.5),
    "defense": ("stability", 2.0),
    "happiness": ("morale", 2.0),
}


def _now() -> float:
    return time.time()


class FactionTechBridge:
    """Bridge between FactionAI and TechTree for autonomous faction research.

    Args:
        tech_tree: An initialised TechTree (created via create_technology_tree()).
        redis_client: Optional pre-connected Redis client.  If *None* a lazy
            connection is created on first use via :meth:`_get_redis`.
    """

    def __init__(
        self, tech_tree: TechTree, redis_client: redis.Redis | None = None
    ) -> None:
        self.tech_tree = tech_tree
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _get_redis(self) -> redis.Redis:
        """Lazy Redis connection (singleton per bridge instance)."""
        if self._redis is None:
            try:
                self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            except Exception as exc:
                logger.error("Redis connection failed: %s", exc)
                raise
        return self._redis

    def _log_event(self, event: Dict) -> None:
        """Append *event* to the capped research log ZSET."""
        try:
            r = self._get_redis()
            r.zadd("faction_tech:log", {json.dumps(event): _now()})
            r.zremrangebyrank("faction_tech:log", 0, -(LOG_CAP + 1))
        except Exception as exc:
            logger.error("_log_event failed: %s", exc)

    # ------------------------------------------------------------------
    # Ideology helper
    # ------------------------------------------------------------------

    @staticmethod
    def _get_faction_ideology(faction_id: str) -> str:
        """Return the ideology string for *faction_id* from FACTION_IDEOLOGY."""
        return FACTION_IDEOLOGY.get(faction_id, "diplomatic")

    # ------------------------------------------------------------------
    # 1. Select tech for faction
    # ------------------------------------------------------------------

    def select_tech_for_faction(self, faction_id: str, ideology: str) -> Optional[str]:
        """Pick the best available tech for a faction to research next.

        Scoring:
            a) Philosophy match      +5
            b) Lower tier preferred   +(6 − tier)
            c) Cheaper preferred      +(1.0 / (cost / 50))
            d) Random exploration     +random(0, 2)

        Only techs whose **prerequisites** are all in the Redis completed set
        are considered.  Returns the highest-scoring tech_id, or *None*.
        """
        try:
            r = self._get_redis()
            completed = r.smembers(f"faction_tech:completed:{faction_id}") or set()

            self.sync_tech_tree_from_redis(faction_id)

            available = self.tech_tree.get_available_techs(faction_id)
            if not available:
                logger.info("No available techs for %s", faction_id)
                return None

            target_phil = IDEOLOGY_PHILOSOPHY_MAP.get(
                ideology, ResearchPhilosophy.SCIENTIFIC
            )

            scored: List[Tuple[float, str]] = []
            for tech in available:
                if not all(p in completed for p in tech.prerequisites):
                    continue

                score = 0.0
                if tech.philosophy == target_phil:
                    score += 5.0
                score += 6 - tech.tier
                score += 1.0 / (tech.research_cost / 50.0)
                score += random.uniform(0, 2)
                scored.append((score, tech.tech_id))

            if not scored:
                return None

            scored.sort(key=lambda pair: pair[0], reverse=True)
            best_id = scored[0][1]
            logger.info(
                "Selected tech %s for %s (ideology=%s, score=%.2f)",
                best_id,
                faction_id,
                ideology,
                scored[0][0],
            )
            return best_id
        except Exception as exc:
            logger.error("select_tech_for_faction failed for %s: %s", faction_id, exc)
            return None

    # ------------------------------------------------------------------
    # 2. Start faction research
    # ------------------------------------------------------------------

    def start_faction_research(self, faction_id: str, tech_id: str) -> Tuple[bool, str]:
        """Begin researching *tech_id* for *faction_id*.

        Delegates to :meth:`TechTree.start_research` and mirrors the project
        into Redis.  Returns ``(success, message)``.
        """
        try:
            self.sync_tech_tree_from_redis(faction_id)

            success, message, project = self.tech_tree.start_research(
                faction_id, tech_id
            )
            if not success or project is None:
                logger.warning(
                    "start_research denied for %s → %s: %s",
                    faction_id,
                    tech_id,
                    message,
                )
                return False, message

            r = self._get_redis()
            r.set(
                f"faction_tech:active:{faction_id}",
                json.dumps(project.to_dict()),
            )

            self._log_event(
                {
                    "event": "research_started",
                    "faction_id": faction_id,
                    "tech_id": tech_id,
                    "project_id": project.project_id,
                    "timestamp": _now(),
                }
            )

            logger.info("Faction %s started researching %s", faction_id, tech_id)
            return True, message
        except Exception as exc:
            logger.error("start_faction_research failed for %s: %s", faction_id, exc)
            return False, str(exc)

    # ------------------------------------------------------------------
    # 3. Advance faction research
    # ------------------------------------------------------------------

    def advance_faction_research(self, faction_id: str, research_points: int) -> Dict:
        """Invest *research_points* into the faction's active project.

        If the faction has no active project this method attempts to select
        and start one automatically using the faction's ideology.

        Returns a dict with faction_id, tech_id, progress, completed, and
        bonuses_applied.
        """
        result: Dict[str, Any] = {
            "faction_id": faction_id,
            "tech_id": None,
            "progress": 0.0,
            "completed": False,
            "bonuses_applied": {},
        }
        try:
            r = self._get_redis()

            raw = r.get(f"faction_tech:active:{faction_id}")
            if not raw:
                ideology = self._get_faction_ideology(faction_id)
                tech_id = self.select_tech_for_faction(faction_id, ideology)
                if tech_id is None:
                    logger.info("No tech to research for %s", faction_id)
                    return result
                ok, msg = self.start_faction_research(faction_id, tech_id)
                if not ok:
                    logger.warning("Auto-start failed for %s: %s", faction_id, msg)
                    return result
                raw = r.get(f"faction_tech:active:{faction_id}")

            project_data = json.loads(raw)
            project_id = project_data["project_id"]
            tech_id = project_data["technology"]
            result["tech_id"] = tech_id

            ok, msg, progress = self.tech_tree.advance_research(
                faction_id,
                project_id,
                research_points,
            )

            result["progress"] = progress

            if progress >= 1.0:
                tech = self.tech_tree.technologies.get(tech_id)
                result["completed"] = True
                r.sadd(f"faction_tech:completed:{faction_id}", tech_id)

                if tech:
                    for perk in tech.unlocks_perks:
                        r.sadd(f"faction_tech:unlocks:{faction_id}", perk)
                    for feat in tech.unlocks_features:
                        r.sadd(f"faction_tech:unlocks:{faction_id}", feat)

                    result["bonuses_applied"] = self._apply_tech_bonuses_to_world(tech)

                r.delete(f"faction_tech:active:{faction_id}")

                self._log_event(
                    {
                        "event": "research_completed",
                        "faction_id": faction_id,
                        "tech_id": tech_id,
                        "bonuses": list(result["bonuses_applied"].keys())
                        if result["bonuses_applied"]
                        else [],
                        "timestamp": _now(),
                    }
                )
                logger.info("Faction %s completed research on %s", faction_id, tech_id)
            else:
                updated_proj = self.tech_tree.projects.get(project_id)
                if updated_proj:
                    r.set(
                        f"faction_tech:active:{faction_id}",
                        json.dumps(updated_proj.to_dict()),
                    )

            pts_key = f"faction_tech:points:{faction_id}"
            r.incrbyfloat(pts_key, float(research_points))

            return result
        except Exception as exc:
            logger.error("advance_faction_research failed for %s: %s", faction_id, exc)
            result["error"] = str(exc)
            return result

    # ------------------------------------------------------------------
    # 4. Tick all factions
    # ------------------------------------------------------------------

    def tick_faction_research(self, faction_data: Dict) -> Dict:
        """Autonomous research tick — processes all 8 factions.

        *faction_data* maps ``faction_id → {ideology, power, influence}``.

        Research-point budget per faction:
            base = 5
            power_bonus = power * 0.1   (power on 0-100 scale)
            influence_mod = influence * 0.05

        Returns summary with factions_processed, research_advanced,
        techs_completed, total_points_spent, errors.
        """
        summary: Dict[str, Any] = {
            "factions_processed": 0,
            "research_advanced": 0,
            "techs_completed": 0,
            "total_points_spent": 0,
            "errors": 0,
        }
        for faction_id, data in faction_data.items():
            try:
                ideology = data.get("ideology", self._get_faction_ideology(faction_id))
                power = float(data.get("power", 50))
                influence = float(data.get("influence", 5))

                base = 5
                power_bonus = power * 0.1
                influence_mod = influence * 0.05
                budget = int(base + power_bonus + influence_mod)

                self.sync_tech_tree_from_redis(faction_id)

                r = self._get_redis()
                has_active = r.exists(f"faction_tech:active:{faction_id}")
                if not has_active:
                    tech_id = self.select_tech_for_faction(faction_id, ideology)
                    if tech_id:
                        self.start_faction_research(faction_id, tech_id)

                adv = self.advance_faction_research(faction_id, budget)

                summary["factions_processed"] += 1
                summary["total_points_spent"] += budget

                if adv.get("progress", 0) > 0:
                    summary["research_advanced"] += 1
                if adv.get("completed"):
                    summary["techs_completed"] += 1

            except Exception as exc:
                logger.error("tick_faction_research error for %s: %s", faction_id, exc)
                summary["errors"] += 1

        return summary

    # ------------------------------------------------------------------
    # 5. Get faction tech summary
    # ------------------------------------------------------------------

    def get_faction_tech_summary(self, faction_id: str) -> Dict:
        """Return current research state for *faction_id* from Redis."""
        summary: Dict[str, Any] = {
            "active_research": None,
            "completed_techs": [],
            "research_points": 0.0,
            "unlocks": [],
            "progress_percent": 0.0,
        }
        try:
            r = self._get_redis()

            raw = r.get(f"faction_tech:active:{faction_id}")
            if raw:
                proj = json.loads(raw)
                summary["active_research"] = proj
                summary["progress_percent"] = proj.get("progress_percentage", 0.0)

            completed = r.smembers(f"faction_tech:completed:{faction_id}")
            if completed:
                summary["completed_techs"] = list(completed)

            pts = r.get(f"faction_tech:points:{faction_id}")
            if pts:
                summary["research_points"] = float(pts)

            unlocks = r.smembers(f"faction_tech:unlocks:{faction_id}")
            if unlocks:
                summary["unlocks"] = list(unlocks)

        except Exception as exc:
            logger.error("get_faction_tech_summary failed for %s: %s", faction_id, exc)
        return summary

    # ------------------------------------------------------------------
    # 6. Research log
    # ------------------------------------------------------------------

    def get_research_log(self, limit: int = 20) -> List[Dict]:
        """Return the latest *limit* entries from the research log ZSET."""
        try:
            r = self._get_redis()
            entries = r.zrevrange("faction_tech:log", 0, limit - 1)
            return [json.loads(e) for e in entries if e]
        except Exception as exc:
            logger.error("get_research_log failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 7. Sync TechTree from Redis (restart recovery)
    # ------------------------------------------------------------------

    def sync_tech_tree_from_redis(self, faction_id: str) -> None:
        """Ensure TechTree's ``player_research`` matches Redis completed set.

        On a fresh start TechTree is in-memory with empty history while Redis
        may contain previously completed techs.  This method backfills the
        TechTree so prerequisite chains resolve correctly.
        """
        try:
            r = self._get_redis()
            completed = r.smembers(f"faction_tech:completed:{faction_id}")
            if not completed:
                return

            if faction_id not in self.tech_tree.player_research:
                self.tech_tree.player_research[faction_id] = []

            known = set(self.tech_tree.player_research[faction_id])
            for tech_id in completed:
                if tech_id not in known:
                    self.tech_tree.player_research[faction_id].append(tech_id)
                    if tech_id in self.tech_tree.technologies:
                        self.tech_tree.completed_techs[tech_id] = (
                            self.tech_tree.technologies[tech_id]
                        )
                    logger.debug(
                        "Synced tech %s for faction %s from Redis",
                        tech_id,
                        faction_id,
                    )
        except Exception as exc:
            logger.error("sync_tech_tree_from_redis failed for %s: %s", faction_id, exc)

    # ------------------------------------------------------------------
    # Internal: apply tech bonuses to world state
    # ------------------------------------------------------------------

    def _apply_tech_bonuses_to_world(self, tech: Technology) -> Dict:
        """Map TechBonus entries to Redis ``world_state`` deltas.

        Bonus-type → world-state mapping:
            morale          → morale              (delta = value × 2)
            resources       → resource_abundance   (delta = value × 3)
            stability       → stability            (delta = value × 2)
            military_power  → threat_level         (delta = value × 1.5, inverted)
            research_speed  → anomaly_activity     (delta = value × 1.5)
            defense         → stability            (delta = value × 2)
            happiness       → morale               (delta = value × 2)

        Unmapped bonus types are logged and skipped.

        Returns a dict of ``{world_key: delta_applied}``.
        """
        applied: Dict[str, float] = {}
        try:
            r = self._get_redis()
            for bonus in tech.bonuses:
                mapping = _BONUS_WORLD_MAP.get(bonus.bonus_type)
                if mapping is None:
                    logger.warning(
                        "Unmapped bonus_type '%s' on tech %s — skipping",
                        bonus.bonus_type,
                        tech.tech_id,
                    )
                    continue

                world_key, multiplier = mapping
                delta = bonus.value * multiplier

                if bonus.bonus_type == "military_power":
                    delta = -delta

                try:
                    current = r.hget("world_state", world_key)
                    current_val = float(current) if current else 0.0
                    new_val = current_val + delta
                    r.hset("world_state", world_key, str(round(new_val, 4)))
                    applied[world_key] = delta
                except Exception as exc:
                    logger.error(
                        "Failed to apply bonus %s→%s for tech %s: %s",
                        bonus.bonus_type,
                        world_key,
                        tech.tech_id,
                        exc,
                    )

        except Exception as exc:
            logger.error(
                "_apply_tech_bonuses_to_world failed for %s: %s", tech.tech_id, exc
            )
        return applied
