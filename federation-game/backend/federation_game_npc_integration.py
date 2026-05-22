#!/usr/bin/env python3
"""
NPC System Adapter for Federation Game History Arc Simulation

Provides advisor bonuses from notable characters.
Assigns up to 3 NPCs per faction based on trait suitability.
Each tick, NPCs contribute morale/identity deltas.

Supports dynamic deltas from the simulation engine via Redis:
  - Reads world_state before/after ticks to compute real deltas
  - Falls back to static trait-based deltas when Redis unavailable

Integration: In HistoryArcOrchestrator.initialize():
    if ENABLE_NPC_SYSTEM:
        self.npc_engine = NPCSystemAdapter(FACTION_IDS)
        self.npc_engine.initialize()
In advance_year() after _sync_game_state():
    if self.npc_engine:
        modifiers = self.npc_engine.process_tick(self.game_state, redis_client=redis)
        self.game_state.federation.morale = max(0.0, min(1.0,
            self.game_state.federation.morale + modifiers.get('morale_delta', 0.0)
        ))
        self.game_state.federation.identity_strength = max(0.0, min(1.0,
            self.game_state.federation.identity_strength + modifiers.get('identity_delta', 0.0)
        ))
Default: disabled (opt-in).
"""

import json
import logging
from typing import Dict, List, Any, Optional
from federation_game_npcs import (
    build_npc_system,
    Character,
    persist_npc_traits_to_redis,
)

logger = logging.getLogger(__name__)

WORLD_STATE_KEY = "world_state"
PREVIOUS_WORLD_STATE_KEY = "npc_adapter:prev_world_state"
FACTION_TECH_KEY_PREFIX = "faction_tech:points:"
NPC_QUEST_STATS_PREFIX = "npc_quests:stats:"


class NPCSystemAdapter:
    """Advisor NPC system that applies bonuses, with dynamic delta support."""

    def __init__(self, faction_ids: List[str]):
        self.npc_system = None
        self.faction_ids = faction_ids
        self.faction_advisors: Dict[str, List[Character]] = {}
        self.summary_data: Dict[str, Any] = {}
        self.enabled = True
        self._prev_world_snapshot: Optional[Dict[str, float]] = None

    def initialize(self):
        """Build NPC system and assign advisors to factions."""
        try:
            self.npc_system = build_npc_system()
        except Exception:
            self.enabled = False
            return

        # For each faction, pick up to 3 characters with suitable affiliation/traits
        for fid in self.faction_ids:
            candidates = []
            for char in self.npc_system.characters.values():
                if char.affiliation == fid:
                    candidates.append(char)
            if len(candidates) < 3:
                extra = [
                    c
                    for c in self.npc_system.characters.values()
                    if c not in candidates and c.loyalty >= 0.6 and c.charisma >= 0.6
                ]
                candidates.extend(extra[: 3 - len(candidates)])
            candidates.sort(
                key=lambda c: (c.loyalty + c.charisma + c.wisdom) / 3, reverse=True
            )
            advisors = candidates[:3]
            self.faction_advisors[fid] = advisors

        self.faction_advisor_ids: Dict[str, str] = {}
        for fid, advisors in self.faction_advisors.items():
            if advisors:
                self.faction_advisor_ids[fid] = advisors[0].char_id

        # Compute per-faction static morale delta from advisors (fallback)
        self.faction_morale_delta: Dict[str, float] = {}
        for fid, advisors in self.faction_advisors.items():
            delta = 0.0
            for adv in advisors:
                delta += ((adv.loyalty + adv.charisma) / 2) * 0.005
            self.faction_morale_delta[fid] = delta

        # Compute per-faction static identity strength delta (fallback)
        self.faction_identity_delta: Dict[str, float] = {}
        for fid, advisors in self.faction_advisors.items():
            delta = 0.0
            for adv in advisors:
                delta += adv.wisdom * 0.003
            self.faction_identity_delta[fid] = delta

        try:
            import redis as _redis

            _r = _redis.Redis(host="redis", port=6379, decode_responses=True)
            persist_npc_traits_to_redis(_r, self.npc_system)
        except Exception as exc:
            logger.debug("Could not persist NPC traits to Redis on init: %s", exc)

        self.summary_data = {
            "enabled": True,
            "total_advisors": sum(len(v) for v in self.faction_advisors.values()),
            "faction_counts": {
                fid: len(adv) for fid, adv in self.faction_advisors.items()
            },
            "dynamic_deltas": False,
        }

    def _read_trait_deltas_from_redis(self, r) -> bool:
        """Refresh faction_morale_delta / faction_identity_delta from Redis.

        For each faction, reads the primary advisor's trait HASH from Redis
        (key ``npc_traits:{char_id}``) and recomputes deltas:
          - morale_delta  = ((loyalty + charisma) / 2) * 0.005
          - identity_delta = wisdom * 0.003

        Returns True if any Redis trait data was found.
        """
        found_any = False
        for fid in self.faction_morale_delta:
            advisor_id = self.faction_advisor_ids.get(fid)
            if advisor_id is None:
                continue
            try:
                data = r.hgetall(f"npc_traits:{advisor_id}")
                if not data:
                    continue
                parsed = {}
                for k, v in data.items():
                    key = k if isinstance(k, str) else k.decode()
                    val = v if isinstance(v, str) else v.decode()
                    try:
                        parsed[key] = float(val)
                    except (ValueError, TypeError):
                        pass
                if not parsed:
                    continue
                loyalty = parsed.get("loyalty", 0.0)
                charisma = parsed.get("charisma", 0.0)
                wisdom = parsed.get("wisdom", 0.0)
                self.faction_morale_delta[fid] = ((loyalty + charisma) / 2) * 0.005
                self.faction_identity_delta[fid] = wisdom * 0.003
                found_any = True
            except Exception as exc:
                logger.debug(
                    "Failed to read traits for advisor %s: %s", advisor_id, exc
                )
        return found_any

    def _read_world_state(self, redis_client) -> Optional[Dict[str, Any]]:
        """Read the world_state hash from Redis. Returns None on failure."""
        try:
            data = redis_client.hgetall(WORLD_STATE_KEY)
            if not data:
                return None
            parsed = {}
            for k, v in data.items():
                key = k if isinstance(k, str) else k.decode()
                val = v if isinstance(v, str) else v.decode()
                try:
                    parsed[key] = float(val)
                except (ValueError, TypeError):
                    parsed[key] = val
            return parsed
        except Exception as exc:
            logger.debug("Failed to read world_state from Redis: %s", exc)
            return None

    def _cache_world_snapshot(self, redis_client) -> None:
        """Persist the current world_state snapshot to Redis for cross-tick delta."""
        if self._prev_world_snapshot is None:
            return
        try:
            redis_client.hset(
                PREVIOUS_WORLD_STATE_KEY,
                mapping={
                    k: str(v)
                    for k, v in self._prev_world_snapshot.items()
                    if isinstance(v, (int, float))
                },
            )
        except Exception as exc:
            logger.debug("Failed to cache world snapshot: %s", exc)

    def _load_cached_snapshot(self, redis_client) -> Optional[Dict[str, float]]:
        """Load a previously cached world snapshot from Redis."""
        try:
            data = redis_client.hgetall(PREVIOUS_WORLD_STATE_KEY)
            if not data:
                return None
            parsed = {}
            for k, v in data.items():
                key = k if isinstance(k, str) else k.decode()
                val = v if isinstance(v, str) else v.decode()
                try:
                    parsed[key] = float(val)
                except (ValueError, TypeError):
                    pass
            return parsed if parsed else None
        except Exception as exc:
            logger.debug("Failed to load cached snapshot: %s", exc)
            return None

    def _compute_deltas_from_snapshots(
        self,
        current: Dict[str, Any],
        previous: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute morale/identity deltas by diffing two world_state snapshots."""
        morale_delta = 0.0
        identity_delta = 0.0
        if "morale" in current and "morale" in previous:
            morale_delta = float(current["morale"]) - previous["morale"]
        if "stability" in current and "stability" in previous:
            stability_change = float(current["stability"]) - previous["stability"]
            identity_delta += stability_change * 0.5
        if "resource_abundance" in current and "resource_abundance" in previous:
            resource_change = (
                float(current["resource_abundance"]) - previous["resource_abundance"]
            )
            morale_delta += resource_change * 0.3
        return {"morale_delta": morale_delta, "identity_delta": identity_delta}

    def get_dynamic_modifiers(
        self,
        redis_client,
    ) -> Dict[str, Dict[str, float]]:
        """Read latest tick results from Redis and compute per-faction deltas.

        Returns:
            Dict mapping faction_id -> {'morale_delta': float, 'identity_delta': float}
            If Redis is unavailable, returns empty dict (caller should use static fallback).
        """
        if not self.enabled:
            return {}

        result: Dict[str, Dict[str, float]] = {}
        try:
            self._read_trait_deltas_from_redis(redis_client)

            world = self._read_world_state(redis_client)
            if world is None:
                return {}

            base_morale = float(world.get("morale", 0.5))
            base_stability = float(world.get("stability", 0.5))
            base_resources = float(world.get("resource_abundance", 0.5))

            prev = self._load_cached_snapshot(redis_client)

            for fid in self.faction_ids:
                tech_points = 0.0
                try:
                    raw = redis_client.get(f"{FACTION_TECH_KEY_PREFIX}{fid}")
                    if raw:
                        tech_points = float(
                            raw if isinstance(raw, str) else raw.decode()
                        )
                except Exception:
                    pass

                advisor_quest_bonus = 0.0
                advisors = self.faction_advisors.get(fid, [])
                for adv in advisors:
                    try:
                        stats = redis_client.hgetall(
                            f"{NPC_QUEST_STATS_PREFIX}{adv.char_id}"
                        )
                        if stats:
                            completed = stats.get(
                                "completed", stats.get(b"completed", "0")
                            )
                            val = (
                                completed if isinstance(completed, (int, float)) else 0
                            )
                            if isinstance(completed, str):
                                try:
                                    val = float(completed)
                                except ValueError:
                                    val = 0
                            elif isinstance(completed, bytes):
                                try:
                                    val = float(completed.decode())
                                except ValueError:
                                    val = 0
                            advisor_quest_bonus += val * 0.001
                    except Exception:
                        pass

                morale_delta = self.faction_morale_delta.get(fid, 0.0)
                identity_delta = self.faction_identity_delta.get(fid, 0.0)

                if prev is not None:
                    snap_deltas = self._compute_deltas_from_snapshots(world, prev)
                    morale_delta = snap_deltas["morale_delta"] / max(
                        len(self.faction_ids), 1
                    )
                    identity_delta = snap_deltas["identity_delta"] / max(
                        len(self.faction_ids), 1
                    )

                morale_delta += tech_points * 0.0001 + advisor_quest_bonus * 0.5
                identity_delta += tech_points * 0.00005 + advisor_quest_bonus * 0.3

                result[fid] = {
                    "morale_delta": morale_delta,
                    "identity_delta": identity_delta,
                }

            self._prev_world_snapshot = {
                "morale": base_morale,
                "stability": base_stability,
                "resource_abundance": base_resources,
            }
            self._cache_world_snapshot(redis_client)

        except Exception as exc:
            logger.warning("get_dynamic_modifiers failed, returning empty: %s", exc)
            return {}

        return result

    def process_tick(
        self,
        tick: int,
        game_state,
        redis_client: Optional[Any] = None,
    ) -> Dict[str, float]:
        """Compute modifiers for the given tick. Returns dict with keys:
        'morale_delta', 'identity_delta' (to add to federation state).

        When redis_client is provided, uses dynamic deltas from the
        simulation engine's world_state and per-faction data.
        Falls back to static trait-based deltas otherwise.
        """
        if not self.enabled or not self.faction_advisors:
            return {}

        if redis_client is not None:
            dynamic = self.get_dynamic_modifiers(redis_client)
            if dynamic:
                total_morale = sum(d.get("morale_delta", 0.0) for d in dynamic.values())
                total_identity = sum(
                    d.get("identity_delta", 0.0) for d in dynamic.values()
                )
                count = len(self.faction_ids)
                self.summary_data["dynamic_deltas"] = True
                return {
                    "morale_delta": total_morale / count if count else 0.0,
                    "identity_delta": total_identity / count if count else 0.0,
                }

        self.summary_data["dynamic_deltas"] = False
        total_morale = sum(self.faction_morale_delta.values())
        total_identity = sum(self.faction_identity_delta.values())
        count = len(self.faction_ids)
        return {
            "morale_delta": total_morale / count if count else 0.0,
            "identity_delta": total_identity / count if count else 0.0,
        }

    def process_year(self, year: int, game_state, **kwargs) -> Dict[str, float]:
        """Backward-compatible alias for process_tick."""
        return self.process_tick(
            year, game_state, redis_client=kwargs.get("redis_client")
        )

    @property
    def summary(self) -> Dict[str, Any]:
        return self.summary_data
