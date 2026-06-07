"""
Federation Game State — GameState class + singleton.
Constants and helpers live in state_constants and state_helpers.
This module re-exports all consumer-facing symbols for backward compatibility.
"""

import json
import hashlib
import time
import random
import asyncio
import threading
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from state_constants import (
    logger,
    PERCENT_METRICS,
    VICTORY_TURN,
    PENDING_CHOICE_TTL_SECONDS,
    LEDGER_METRICS,
    METRIC_LABELS,
    LANES,
    EVENT_LANE_DEFAULTS,
    FEDERATION_ATLAS,
    GOVERNANCE_PROPOSALS,
    RIVAL_SYSTEM_AVAILABLE,
    CONSCIOUSNESS_SYSTEM_AVAILABLE,
    GAME_STATE_V2_AVAILABLE,
    CONSOLE_ENGINE_AVAILABLE,
    HISTORY_ARC_AVAILABLE,
    POLITICAL_SYSTEM_AVAILABLE,
    SPATIAL_SYSTEM_AVAILABLE,
    EVENT_CASCADE_AVAILABLE,
    FACTION_AI_AVAILABLE,
    COGNITION_AVAILABLE,
    NARRATOR_AVAILABLE,
    LLM_ROUTER_AVAILABLE,
    NPC_MEMORY_AVAILABLE,
    SIMULATION_ENGINE_AVAILABLE,
    build_faction_system,
    FactionSystem,
    TimelineSystem,
    Era,
    build_npc_system,
    NPCSystem,
    chat_with_npc,
    get_conversation_info,
    generate_thought,
    get_recent_thoughts,
    update_opinion,
    get_opinion,
    update_mood,
    get_mood,
    generate_action,
    get_recent_actions,
    get_world_events,
    update_npc_relationship,
    get_npc_relationships,
    simulation_tick,
    get_absence_report,
    get_relationship_summary,
    generate_goal,
    get_goals,
    advance_goal,
    set_goal_status,
    generate_goal_driven_action,
    make_decision,
    evaluate_decision_options,
    get_decision_log,
    get_world_state,
    get_world_condition,
    set_world_condition,
    get_world_state_history,
    update_world_state,
    create_quest_library,
    QuestSystem,
    FactionAffiliation,
    create_technology_tree,
    TechTree,
    db_manager,
    RivalFederation,
    RivalFederationSimulator,
    ConsciousnessSheet,
    FederationGameState,
    HistoryArcOrchestrator,
    PoliticalEngine,
    FederationConsole,
    seed_spatial_system,
    get_spatial_status,
    get_all_sectors,
    get_sector_by_id,
    get_sector_summary,
    get_all_discoveries,
    get_faction_home,
    get_faction_territories,
    get_faction_discoveries,
    get_adjacent_sector_ids,
    is_spatial_enabled,
)

try:
    from event_cascade import get_cascade_summary
except ImportError:
    get_cascade_summary = None

from state_helpers import (
    clamp_percent,
    enrich_event,
    snapshot_metrics,
    calculate_deltas,
    summarize_delta_direction,
    build_explainability,
    get_governance_status,
    build_governance_event,
    apply_governance_pressure,
)


# ============================================================================
# GAME STATE CLASS
# ============================================================================


class GameState:
    def __init__(self, load_latest_snapshot: bool = True):
        self.turn = 1
        self.credits = 1000
        self.fuel = 100
        self.shields = 100
        self.hull = 100
        self.crew_morale = 80
        self.discovered_sectors = 1
        self.allies = 0
        self.federation_stability = 70
        self.public_trust = 65
        self.council_support = 55
        self.constitutional_integrity = 80
        self.rights_protection = 80
        self.emergency_powers = 0
        self.active_policy = "Exploration Charter"
        self.proposal_history: List[Dict[str, Any]] = []
        self.decision_ledger: List[Dict[str, Any]] = []
        self.last_decision: Optional[Dict[str, Any]] = None
        self.technologies_unlocked = []
        self.current_event = None
        self.pending_choices: Dict[str, Dict[str, Any]] = {}
        self.log: List[Dict[str, Any]] = []
        self.federation_name = "USS Federation"
        self.faction_system: FactionSystem = build_faction_system()
        self.timeline: TimelineSystem = TimelineSystem()
        self.npc_system: NPCSystem = build_npc_system()
        self.quest_system: QuestSystem = create_quest_library()
        self.tech_tree: TechTree = create_technology_tree()

        self.rival_simulator = (
            RivalFederationSimulator() if RIVAL_SYSTEM_AVAILABLE else None
        )
        self.consciousness_sheet = (
            ConsciousnessSheet() if CONSCIOUSNESS_SYSTEM_AVAILABLE else None
        )
        self.game_state_v2 = FederationGameState() if GAME_STATE_V2_AVAILABLE else None
        self.history_arc = None
        self.political_engine = None
        self.console_engine = None

        self.engine_systems = {
            "quest_system": {"loaded": True, "active_quests": 0, "completed_quests": 0},
            "faction_system": {
                "loaded": True,
                "known_factions": len(self.faction_system.factions),
                "player_standing": {},
            },
            "technology_tree": {
                "loaded": True,
                "research_points": 0,
                "unlocked_techs": [],
            },
            "npc_system": {"loaded": True, "known_npcs": 0, "active_relationships": {}},
            "event_registry": {"loaded": True, "total_events": 0, "events_seen": []},
            "consciousness_metrics": {
                "loaded": True,
                "coherence": 50.0,
                "stability": 50.0,
                "complexity": 50.0,
            },
            "turn_progression": {
                "loaded": True,
                "current_phase": "early_exploration",
                "turns_in_phase": 0,
            },
            "persistence": {"loaded": True, "last_checkpoint": None, "save_slots": 3},
        }

        if CONSOLE_ENGINE_AVAILABLE:
            try:
                self.console_engine = FederationConsole()
            except Exception as e:
                print(f"Warning: FederationConsole init failed: {e}")
                self.console_engine = None

        if HISTORY_ARC_AVAILABLE:
            try:
                self.history_arc = HistoryArcOrchestrator()
                self.history_arc.initialize()
            except Exception as e:
                print(f"Warning: HistoryArcOrchestrator init failed: {e}")
                self.history_arc = None

        try:
            db_initialized = db_manager.initialize()
            if db_initialized:
                if load_latest_snapshot:
                    snapshot = db_manager.load_latest_snapshot()
                    if snapshot:
                        self._restore_from_snapshot(snapshot)
                        self.engine_systems["persistence"]["loaded"] = True
                        self.engine_systems["persistence"]["last_checkpoint"] = (
                            snapshot.get("created_at")
                        )
                    else:
                        self.engine_systems["persistence"]["loaded"] = True
                else:
                    self.engine_systems["persistence"]["loaded"] = True
            else:
                self.engine_systems["persistence"]["loaded"] = False
        except Exception as e:
            print(f"Warning: DB persistence init failed: {e}")
            self.engine_systems["persistence"]["loaded"] = False

        if POLITICAL_SYSTEM_AVAILABLE:
            try:
                faction_ids = list(self.faction_system.factions.keys())
                fed_state = (
                    self.game_state_v2.federation if self.game_state_v2 else None
                )
                if fed_state:
                    self.political_engine = PoliticalEngine(faction_ids, fed_state)
                    self.political_engine.initialize()
            except Exception as e:
                print(f"Warning: PoliticalEngine init failed: {e}")
                self.political_engine = None

        if self.rival_simulator:
            try:
                self.rival_simulator.initialize_rivals()
            except Exception:
                logger.warning(
                    "Rival simulator initialization failed; continuing without rivals"
                )

        self.engine_systems.update(
            {
                "rival_simulator": {
                    "loaded": self.rival_simulator is not None,
                    "active_rivals": len(self.rival_simulator.rivals)
                    if self.rival_simulator and hasattr(self.rival_simulator, "rivals")
                    else 0,
                },
                "consciousness_sheet": {
                    "loaded": self.consciousness_sheet is not None,
                    "coherence": 0.0,
                    "stability": 0.0,
                },
                "history_arc": {
                    "loaded": self.history_arc is not None,
                    "current_era": "genesis",
                    "year": 0,
                },
                "political_engine": {
                    "loaded": self.political_engine is not None,
                    "laws_passed": 0,
                },
                "game_state_v2": {"loaded": self.game_state_v2 is not None},
                "console_engine": {"loaded": self.console_engine is not None},
            }
        )

    def sweep_expired_pending_choices(
        self,
        ttl_seconds: int = PENDING_CHOICE_TTL_SECONDS,
        now: Optional[float] = None,
    ) -> None:
        current_time = time.time() if now is None else now
        expired_tokens = [
            token
            for token, payload in self.pending_choices.items()
            if current_time - float(payload.get("created_at", current_time)) > ttl_seconds
        ]
        for token in expired_tokens:
            self.pending_choices.pop(token, None)

    def register_pending_choice(
        self, choice_token: str, event: Dict[str, Any], now: Optional[float] = None
    ) -> None:
        self.pending_choices[choice_token] = {
            "event": event,
            "created_at": time.time() if now is None else now,
        }

    def pop_pending_choice_event(self, choice_token: str) -> Optional[Dict[str, Any]]:
        payload = self.pending_choices.pop(choice_token, None)
        if not isinstance(payload, dict):
            return None
        event = payload.get("event")
        return event if isinstance(event, dict) else None

    def _restore_from_snapshot(self, snapshot: Dict[str, Any]) -> None:
        try:
            gs_json = snapshot.get("game_state_json")
            if gs_json:
                gs_data = json.loads(gs_json)
                for key, value in gs_data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
        except Exception as e:
            print(f"Warning: game_state restore failed: {e}")

        try:
            fed_json = snapshot.get("federation_state_json")
            if fed_json and self.game_state_v2:
                fed_data = json.loads(fed_json)
                federation_data = fed_data.get("federation", {})
                fed = self.game_state_v2.federation
                fed.morale = federation_data.get("morale", 0.5)
                fed.identity_strength = federation_data.get("identity_strength", 0.3)
                fed.stability = federation_data.get("stability", 0.6)
                fed.technological_level = federation_data.get(
                    "technological_level", 0.2
                )
                fed.military_power = federation_data.get("military_power", 0.3)
                fed.treasury = federation_data.get("treasury", 1000)
                fed.population = federation_data.get("population", 10000)
                fed.territory_size = federation_data.get("territory_size", 100.0)
                _lu = federation_data.get("last_updated")
                if _lu:
                    from datetime import datetime as _dt

                    fed.last_updated = _dt.fromisoformat(_lu)
                subsystems_data = fed_data.get("subsystems", {})
                self.game_state_v2._restore_subsystems(subsystems_data)
                stats_data = fed_data.get("statistics", {})
                if stats_data:
                    stats = self.game_state_v2.statistics
                    for key, val in stats_data.items():
                        if hasattr(stats, key):
                            setattr(stats, key, val)
                self.game_state_v2.technology_data = fed_data.get("technology_data", {})
                self.game_state_v2.quest_data = fed_data.get("quest_data", {})
                self.game_state_v2.npc_data = fed_data.get("npc_data", {})
                self.game_state_v2.political_data = fed_data.get("political_data", {})
                phase_str = fed_data.get("game_phase", "genesis")
                try:
                    from federation_game_state import GamePhase

                    self.game_state_v2.game_phase = GamePhase(phase_str)
                except Exception:
                    print(f"Warning: could not set game_phase to '{phase_str}'")
        except Exception as e:
            print(f"Warning: federation_state restore failed: {e}")

        try:
            arc_json = snapshot.get("history_arc_json")
            if arc_json and self.history_arc:
                arc_data = json.loads(arc_json)
                self.history_arc.import_full_state(arc_data)
        except Exception as e:
            print(f"Warning: history_arc restore failed: {e}")

        try:
            log_json = snapshot.get("turn_log_json")
            if log_json:
                self.log = json.loads(log_json)
        except Exception as e:
            print(f"Warning: turn_log restore failed: {e}")

    def save_to_db(self, snapshot_type: str = "auto") -> bool:
        try:
            game_state_json = json.dumps(
                {
                    "turn": self.turn,
                    "credits": self.credits,
                    "fuel": self.fuel,
                    "shields": self.shields,
                    "hull": self.hull,
                    "crew_morale": self.crew_morale,
                    "discovered_sectors": self.discovered_sectors,
                    "allies": self.allies,
                    "federation_stability": self.federation_stability,
                    "public_trust": self.public_trust,
                    "council_support": self.council_support,
                    "constitutional_integrity": self.constitutional_integrity,
                    "rights_protection": self.rights_protection,
                    "emergency_powers": self.emergency_powers,
                    "active_policy": self.active_policy,
                    "federation_name": self.federation_name,
                    "current_event": self.current_event,
                },
                default=str,
            )
        except Exception:
            game_state_json = None

        federation_state_json = None
        try:
            if self.game_state_v2:
                fed_data = {
                    "federation": asdict(self.game_state_v2.federation),
                    "subsystems": self.game_state_v2._serialize_subsystems(),
                    "statistics": asdict(self.game_state_v2.statistics),
                    "action_history": self.game_state_v2._serialize_action_history(),
                    "game_phase": self.game_state_v2.game_phase.value,
                    "victory_type": self.game_state_v2.victory_type.value
                    if self.game_state_v2.victory_type
                    else None,
                    "defeat_reason": self.game_state_v2.defeat_reason,
                    "is_game_over": self.game_state_v2.is_game_over,
                    "technology_data": self.game_state_v2.technology_data,
                    "quest_data": self.game_state_v2.quest_data,
                    "npc_data": self.game_state_v2.npc_data,
                    "political_data": self.game_state_v2.political_data,
                }
                federation_state_json = json.dumps(fed_data, default=str)
        except Exception:
            federation_state_json = None

        history_arc_json = None
        try:
            if self.history_arc:
                history_arc_json = json.dumps(
                    self.history_arc.export_full_state(), default=str
                )
        except Exception:
            history_arc_json = None

        turn_log_json = None
        try:
            recent_log = self.log[-100:] if self.log else []
            turn_log_json = json.dumps(recent_log, default=str)
        except Exception:
            turn_log_json = None

        state_hash = None
        try:
            raw = json.dumps(
                {
                    "turn": self.turn,
                    "credits": self.credits,
                    "fuel": self.fuel,
                    "shields": self.shields,
                    "hull": self.hull,
                    "crew_morale": self.crew_morale,
                    "federation_stability": self.federation_stability,
                    "public_trust": self.public_trust,
                    "council_support": self.council_support,
                    "constitutional_integrity": self.constitutional_integrity,
                    "rights_protection": self.rights_protection,
                    "emergency_powers": self.emergency_powers,
                    "active_policy": self.active_policy,
                    "discovered_sectors": self.discovered_sectors,
                    "allies": self.allies,
                },
                sort_keys=True,
            )
            state_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        except Exception:
            logger.warning(
                "State hash computation failed; snapshot will proceed without hash"
            )

        return db_manager.save_snapshot(
            game_state_json=game_state_json,
            federation_state_json=federation_state_json,
            history_arc_json=history_arc_json,
            turn_log_json=turn_log_json,
            state_hash=state_hash,
            snapshot_type=snapshot_type,
        )


# ============================================================================
# GAME STATE SINGLETON
# ============================================================================

game_state = GameState()
