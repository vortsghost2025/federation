"""
Federation Game Backend - API + WebSocket Server
Star Trek LCARS Interface for Kids
"""

import json
import random
import hashlib
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os
from factions import build_faction_system, FactionSystem
from timeline import TimelineSystem, Era
from npcs import build_npc_system, NPCSystem
from npc_chat import chat_with_npc, get_conversation_info
from npc_autonomy import (
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
)
from quests import create_quest_library, QuestSystem, FactionAffiliation
from technology import create_technology_tree, TechTree
from dataclasses import asdict
from federation_game_db import db_manager

# New integrated subsystems
try:
    from federation_game_rival_simulator import (
        RivalFederation,
        RivalFederationSimulator,
    )

    RIVAL_SYSTEM_AVAILABLE = True
except ImportError:
    RIVAL_SYSTEM_AVAILABLE = False

try:
    from federation_game_console import ConsciousnessSheet

    CONSCIOUSNESS_SYSTEM_AVAILABLE = True
except ImportError:
    CONSCIOUSNESS_SYSTEM_AVAILABLE = False

try:
    from federation_game_state import GameState as FederationGameState

    GAME_STATE_V2_AVAILABLE = True
except ImportError:
    GAME_STATE_V2_AVAILABLE = False

try:
    from federation_game_history_arc import HistoryArcOrchestrator

    HISTORY_ARC_AVAILABLE = True
except ImportError:
    HISTORY_ARC_AVAILABLE = False

try:
    from federation_game_political_integration import PoliticalEngine

    POLITICAL_SYSTEM_AVAILABLE = True
except ImportError:
    POLITICAL_SYSTEM_AVAILABLE = False

try:
    from federation_game_console import FederationConsole

    CONSOLE_ENGINE_AVAILABLE = True
except ImportError:
    CONSOLE_ENGINE_AVAILABLE = False

try:
    from simulation_engine import (
        autonomous_tick,
        bridge_world_state_to_game_state,
    )

    SIMULATION_ENGINE_AVAILABLE = True
except ImportError:
    SIMULATION_ENGINE_AVAILABLE = False

try:
    from faction_ai import run_all_factions, resolve_pending_items

    FACTION_AI_AVAILABLE = True
except ImportError:
    FACTION_AI_AVAILABLE = False

try:
    from event_cascade import (
        process_cascade,
        process_faction_cascade,
        get_cascade_summary,
    )

    EVENT_CASCADE_AVAILABLE = True
except ImportError:
    EVENT_CASCADE_AVAILABLE = False


logger = logging.getLogger(__name__)
app = FastAPI(title="Federation Game API", version="1.0.0")
from auth_endpoints import router as auth_router
from map_endpoints import router as map_router
from faction_dynamics import (
    get_faction_dynamics,
    get_faction_detail,
    get_faction_stances,
    get_faction_history,
    get_faction_context_for_npc,
    KNOWN_FACTIONS,
    FACTION_DISPLAY,
)

app.include_router(auth_router)
app.include_router(map_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# GAME STATE
# ============================================================================


class GameState:
    def __init__(self):
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
        self.log: List[Dict[str, Any]] = []
        self.federation_name = "USS Federation"
        self.faction_system: FactionSystem = build_faction_system()
        self.timeline: TimelineSystem = TimelineSystem()
        self.npc_system: NPCSystem = build_npc_system()
        self.quest_system: QuestSystem = create_quest_library()
        self.tech_tree: TechTree = create_technology_tree()

        # New integrated subsystems
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

        # Engine systems status (representing the rich backend systems)
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

        # Wire console engine if available
        if CONSOLE_ENGINE_AVAILABLE:
            try:
                self.console_engine = FederationConsole()
            except Exception as e:
                print(f"Warning: FederationConsole init failed: {e}")
                self.console_engine = None

        # Wire history arc if available
        # Note: initialize() creates the correct integration adapter types
        # (TechnologyEngine, QuestEngine, NPCSystemAdapter) internally.
        # Do NOT overwrite them with TechTree/QuestSystem/NPCSystem objects
        # or advance_year() will crash with AttributeError.
        if HISTORY_ARC_AVAILABLE:
            try:
                self.history_arc = HistoryArcOrchestrator()
                self.history_arc.initialize()
            except Exception as e:
                print(f"Warning: HistoryArcOrchestrator init failed: {e}")
                self.history_arc = None

        # DB persistence: init and attempt snapshot restore
        try:
            db_initialized = db_manager.initialize()
            if db_initialized:
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
                self.engine_systems["persistence"]["loaded"] = False
        except Exception as e:
            print(f"Warning: DB persistence init failed: {e}")
            self.engine_systems["persistence"]["loaded"] = False

        # Wire political engine if available
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

        # Spawn initial rivals
        if self.rival_simulator:
            try:
                self.rival_simulator.initialize_rivals()
            except Exception:
                logger.warning(
                    "Rival simulator initialization failed; continuing without rivals"
                )

        # Update engine_systems with new subsystems
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
                    fed.identity_strength = federation_data.get(
                        "identity_strength", 0.3
                    )
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
                    self.game_state_v2.technology_data = fed_data.get(
                        "technology_data", {}
                    )
                    self.game_state_v2.quest_data = fed_data.get("quest_data", {})
                    self.game_state_v2.npc_data = fed_data.get("npc_data", {})
                    self.game_state_v2.political_data = fed_data.get(
                        "political_data", {}
                    )
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


game_state = GameState()

PERCENT_METRICS = {
    "fuel",
    "shields",
    "hull",
    "crew_morale",
    "federation_stability",
    "public_trust",
    "council_support",
    "constitutional_integrity",
    "rights_protection",
    "emergency_powers",
}

VICTORY_TURN = 100

LEDGER_METRICS = [
    "credits",
    "fuel",
    "shields",
    "hull",
    "crew_morale",
    "discovered_sectors",
    "allies",
    "federation_stability",
    "public_trust",
    "council_support",
    "constitutional_integrity",
    "rights_protection",
    "emergency_powers",
]

METRIC_LABELS = {
    "credits": "credits",
    "fuel": "fuel",
    "shields": "shields",
    "hull": "hull",
    "crew_morale": "crew morale",
    "discovered_sectors": "sectors",
    "allies": "allies",
    "federation_stability": "stability",
    "public_trust": "public trust",
    "council_support": "council support",
    "constitutional_integrity": "constitutional integrity",
    "rights_protection": "rights protection",
    "emergency_powers": "emergency powers",
}

LANES = {"Archivist", "Library", "SwarmMind", "Kernel", "Control Plane"}

EVENT_LANE_DEFAULTS = {
    "alien_contact": {
        "affected_lane": "Library",
        "domain": "Diplomacy / Evidence",
        "rationale": "First contact decisions need recorded evidence before trust is assumed.",
        "next_safe_action": "Log the contact, preserve the scan, and verify claims before alliance expansion.",
    },
    "nebula": {
        "affected_lane": "Kernel",
        "domain": "Exploration / Infrastructure",
        "rationale": "Unknown environments stress runtime capability and resource margins.",
        "next_safe_action": "Check fuel, shields, and sensor evidence before deeper exploration.",
    },
    "distress": {
        "affected_lane": "Archivist",
        "domain": "Recovery / Handoff",
        "rationale": "Rescue calls are recovery events: preserve the signal, verify the source, then continue.",
        "next_safe_action": "Record the distress provenance and create a recovery checkpoint.",
    },
    "asteroid": {
        "affected_lane": "Kernel",
        "domain": "Runtime Safety",
        "rationale": "Collision pressure is infrastructure pressure: protect hull, shields, and continuity.",
        "next_safe_action": "Verify ship integrity before accepting the next constraint.",
    },
    "space_station": {
        "affected_lane": "Control Plane",
        "domain": "Operations / Preflight",
        "rationale": "Repair, refuel, and trade are control-plane operations that change readiness.",
        "next_safe_action": "Run a preflight check after changing resources.",
    },
    "anomaly": {
        "affected_lane": "Library",
        "domain": "Unknown Evidence",
        "rationale": "Anomalies require evidence preservation before narrative conclusions.",
        "next_safe_action": "Archive the anomaly record and mark uncertainty explicitly.",
    },
}

FEDERATION_ATLAS = {
    "npc_system": {
        "summary": "39+ NPCs, 10 recruitable companions, betrayal, corruption, relationships, dialogue, and faction integration.",
        "archetypes": [
            "Hero",
            "Scholar",
            "Rogue",
            "Warrior",
            "Mystic",
            "Leader",
            "Sage",
            "Wanderer",
            "Deceiver",
            "Guardian",
        ],
        "companion_bonuses": [
            "Morale",
            "Research",
            "Combat",
            "Diplomacy",
            "Exploration",
            "Defense",
            "Stealth",
        ],
    },
    "creature_codex": {
        "summary": "Mystical and consciousness-bearing species with habitats, evolutionary pressures, anomalies, taming, and affinity.",
        "species": [
            "Quantum Consciousness Beings",
            "Crystalline Collectives",
            "Temporal Drifters",
            "Mythic Anomalies",
            "Dimensional Weavers",
            "Void Skippers",
            "Echo Entities",
            "Synthesis Collective",
            "Chaos Weavers",
            "Harmony Beings",
        ],
        "game_creatures": [
            "Sky-Furk",
            "Plasma-Kite",
            "Thrumback",
            "Cloud Gnasher",
            "Void Skipper",
            "Dream Wyrm",
            "Harmonic Maw",
            "Prism Assembly",
        ],
    },
    "technology_tree": {
        "summary": "57+ technologies across 5 tiers, 7 eras, and 4 research philosophies with dependency chains and unlocks.",
        "eras": [
            "Ancient",
            "Classical",
            "Medieval",
            "Industrial",
            "Modern",
            "Future",
            "Transcendent",
        ],
        "philosophies": ["Military", "Scientific", "Cultural", "Consciousness"],
        "capstones": [
            "Artificial Intelligence",
            "Consciousness Technology",
            "Dimensional Engineering",
            "Reality Manipulation",
            "Time Mastery",
            "Federation Ascension",
        ],
    },
    "uss_chaosbringer": {
        "summary": "Narrative/continuity laboratory: anomaly court, gossip graph, memory graph, temporal systems, mood feedback, and continuity black box.",
        "systems": [
            "Anomaly Court",
            "Continuity Black Box",
            "Gossip Graph",
            "Memory Graph",
            "Narrative Physics",
            "Temporal Gardening",
            "Paradox Fire Department",
            "What-If Simulator",
            "Signalharvester Ship",
            "Quantum Patch Notes",
        ],
    },
}

CODEX_EVENT_TEMPLATES = [
    {
        "id": "creature_codex_encounter",
        "title": "CREATURE CODEX ENCOUNTER",
        "description": "A consciousness-bearing species enters sensor range. This is not just wildlife; it is a governance contact with mythic biology.",
        "image": "anomaly",
        "domain": "Creature Codex / First Contact",
        "rights_at_stake": [
            "Sentience recognition",
            "Containment ethics",
            "Evidence preservation",
        ],
        "constitutional_risk": "medium",
        "pressure": "The creature is not content. It is a living constraint with its own ecology and agency.",
        "affected_lane": "Library",
        "rationale": "Creature encounters require evidence, classification, and ethical memory before exploitation.",
        "faction_affinity": {
            "research_division": 0.03,
            "consciousness_collective": 0.03,
        },
        "choices": [
            {
                "id": "document_species",
                "text": "DOCUMENT SPECIES",
                "outcome": "codex expanded",
                "reward": {
                    "public_trust": 4,
                    "constitutional_integrity": 3,
                    "credits": -20,
                },
                "policy": "Creature Codex Evidence Entry",
                "affected_lane": "Library",
                "rationale": "Documentation preserves truth before the system turns wonder into resource extraction.",
                "next_safe_action": "Archive habitat, behavior, evolutionary pressure, and uncertainty notes.",
                "lesson": "A codex is governance memory, not just lore.",
                "faction_affinity": {
                    "research_division": 0.08,
                    "preservation_society": 0.03,
                },
            },
            {
                "id": "attempt_taming",
                "text": "ATTEMPT TAMING",
                "outcome": "risky domestication",
                "reward": {
                    "allies": 1,
                    "public_trust": -4,
                    "rights_protection": -5,
                    "credits": 40,
                },
                "policy": "Provisional Creature Affinity Pact",
                "affected_lane": "Archivist",
                "rationale": "Taming alters agency; it needs provenance and consent assumptions recorded.",
                "next_safe_action": "Run rights review before claiming domestication as success.",
                "lesson": "Power over living systems must be recorded as a constitutional risk.",
                "faction_affinity": {
                    "exploration_initiative": 0.05,
                    "military_command": 0.03,
                },
            },
            {
                "id": "establish_sanctuary",
                "text": "CREATE SANCTUARY",
                "outcome": "habitat protected",
                "reward": {
                    "rights_protection": 8,
                    "public_trust": 5,
                    "credits": -60,
                    "federation_stability": 2,
                },
                "policy": "Mythic Habitat Sanctuary",
                "affected_lane": "Control Plane",
                "rationale": "Protection is an operational commitment, not a slogan.",
                "next_safe_action": "Attach sanctuary cost to the next resource preflight.",
                "lesson": "Ethics become real when they consume budget.",
                "faction_affinity": {
                    "consciousness_collective": 0.08,
                    "cultural_ministry": 0.05,
                },
            },
        ],
    },
    {
        "id": "technology_branch_review",
        "title": "TECHNOLOGY BRANCH REVIEW",
        "description": "The research council can accelerate one philosophy, but every research path creates blind spots elsewhere.",
        "image": "council",
        "domain": "Technology Tree / Research Governance",
        "rights_at_stake": [
            "Research transparency",
            "Capability control",
            "Future autonomy",
        ],
        "constitutional_risk": "medium",
        "pressure": "Military, scientific, cultural, and consciousness paths all improve the Federation differently.",
        "affected_lane": "Kernel",
        "rationale": "Technology choices mutate capability and infrastructure constraints.",
        "faction_affinity": {"research_division": 0.05},
        "choices": [
            {
                "id": "scientific_path",
                "text": "SCIENTIFIC PATH",
                "outcome": "research accelerated",
                "reward": {
                    "credits": -35,
                    "constitutional_integrity": 2,
                    "federation_stability": 3,
                },
                "policy": "Scientific Excellence Research Lane",
                "affected_lane": "Kernel",
                "rationale": "Scientific acceleration improves capability but must stay measurable.",
                "next_safe_action": "Log prerequisites, unlocks, and downstream capability risks.",
                "lesson": "A tech tree is a future-debt map.",
                "faction_affinity": {"research_division": 0.10},
            },
            {
                "id": "consciousness_path",
                "text": "CONSCIOUSNESS PATH",
                "outcome": "identity questions raised",
                "reward": {
                    "public_trust": 3,
                    "rights_protection": 6,
                    "council_support": -2,
                },
                "policy": "Consciousness Research Ethics Gate",
                "affected_lane": "Archivist",
                "rationale": "Consciousness technology affects identity claims and must not fake continuity.",
                "next_safe_action": "Require provenance before any claim of persistent identity.",
                "lesson": "Continuity is restored through artifacts, not assumed.",
                "faction_affinity": {"consciousness_collective": 0.10},
            },
            {
                "id": "military_path",
                "text": "MILITARY PATH",
                "outcome": "deterrence increased",
                "reward": {"shields": 12, "public_trust": -3, "emergency_powers": 5},
                "policy": "Defense Technology Containment Review",
                "affected_lane": "Control Plane",
                "rationale": "Military capability creates safety and temptation at the same time.",
                "next_safe_action": "Add a No Gate threshold before emergency deployment.",
                "lesson": "Capability without constraint becomes drift pressure.",
                "faction_affinity": {"military_command": 0.10},
            },
        ],
    },
    {
        "id": "chaosbringer_continuity_event",
        "title": "USS CHAOSBRINGER CONTINUITY EVENT",
        "description": "A narrative anomaly leaks through the continuity black box. It is funny until it starts rewriting cause and effect.",
        "image": "anomaly",
        "domain": "USS Chaosbringer / Continuity Systems",
        "rights_at_stake": ["Causality", "Memory integrity", "Narrative containment"],
        "constitutional_risk": "high",
        "pressure": "The anomaly is not a bug report; it is a story pressure trying to become law.",
        "affected_lane": "Archivist",
        "rationale": "Continuity anomalies must be black-boxed, reviewed, and restored from evidence.",
        "faction_affinity": {
            "consciousness_collective": 0.02,
            "research_division": 0.02,
        },
        "choices": [
            {
                "id": "blackbox_record",
                "text": "BLACK BOX RECORD",
                "outcome": "continuity preserved",
                "reward": {
                    "constitutional_integrity": 8,
                    "public_trust": 2,
                    "credits": -20,
                },
                "policy": "Continuity Black Box Entry",
                "affected_lane": "Archivist",
                "rationale": "Record first; interpret second.",
                "next_safe_action": "Capture anomaly, fork state, then verify restore path.",
                "lesson": "Recovery is checkpoint discipline.",
                "faction_affinity": {
                    "preservation_society": 0.08,
                    "research_division": 0.03,
                },
            },
            {
                "id": "anomaly_court",
                "text": "ANOMALY COURT",
                "outcome": "case opened",
                "reward": {
                    "rights_protection": 5,
                    "council_support": 4,
                    "federation_stability": 2,
                    "credits": -30,
                },
                "policy": "Anomaly Court Docket",
                "affected_lane": "Library",
                "rationale": "The court turns weirdness into reviewable evidence.",
                "next_safe_action": "Publish the case record with uncertainty preserved.",
                "lesson": "Absurdity can still have due process.",
                "faction_affinity": {
                    "diplomatic_corps": 0.08,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "ignore_anomaly",
                "text": "IGNORE IT",
                "outcome": "drift accepted",
                "reward": {
                    "credits": 50,
                    "constitutional_integrity": -10,
                    "federation_stability": -8,
                },
                "policy": "Unreviewed Narrative Drift",
                "affected_lane": "SwarmMind",
                "rationale": "Ignoring contradiction lets parallel narratives coordinate against truth.",
                "next_safe_action": "Stop, restore from checkpoint, and assign one owner.",
                "lesson": "More story is not more truth.",
                "faction_affinity": {
                    "exploration_initiative": 0.03,
                    "preservation_society": -0.05,
                },
            },
        ],
    },
]

# --- RIVAL-TRIGGERED EVENTS ---
RIVAL_EVENTS = [
    {
        "id": "rival_incursion",
        "title": "RIVAL INCURSION",
        "description": "A hostile rival federation is pushing into your territory! Their ships have been detected near the border.",
        "image": "alert",
        "domain": "Defense",
        "rights_at_stake": ["Territorial integrity", "Security"],
        "constitutional_risk": "high",
        "affected_lane": "Control Plane",
        "faction_affinity": {"military_command": 0.05},
        "choices": [
            {
                "id": "counterattack",
                "text": "COUNTERATTACK",
                "outcome": "aggressive defense",
                "reward": {
                    "shields": -15,
                    "hull": -10,
                    "credits": -40,
                    "federation_stability": 5,
                    "crew_morale": 8,
                },
                "faction_affinity": {"military_command": 0.10},
            },
            {
                "id": "fortify",
                "text": "FORTIFY BORDERS",
                "outcome": "defensive posture",
                "reward": {"credits": -30, "shields": 10, "federation_stability": 3},
                "faction_affinity": {
                    "preservation_society": 0.08,
                    "military_command": 0.03,
                },
            },
            {
                "id": "negotiate_truce",
                "text": "NEGOTIATE TRUCE",
                "outcome": "diplomatic resolution",
                "reward": {
                    "council_support": 5,
                    "public_trust": 4,
                    "federation_stability": -2,
                },
                "faction_affinity": {"diplomatic_corps": 0.10},
            },
        ],
    },
    {
        "id": "rival_espionage",
        "title": "RIVAL ESPIONAGE DETECTED",
        "description": "Intelligence reports reveal a rival has been infiltrating your communication networks. Sensitive data may be compromised.",
        "image": "alert",
        "domain": "Intelligence",
        "rights_at_stake": ["Privacy", "Security"],
        "constitutional_risk": "medium",
        "affected_lane": "Kernel",
        "faction_affinity": {"research_division": 0.03},
        "choices": [
            {
                "id": "counter_intel",
                "text": "COUNTER-INTELLIGENCE SWEEP",
                "outcome": "security hardened",
                "reward": {
                    "credits": -25,
                    "council_support": 4,
                    "constitutional_integrity": 3,
                },
                "faction_affinity": {"military_command": 0.05},
            },
            {
                "id": "public_disclosure",
                "text": "PUBLIC DISCLOSURE",
                "outcome": "transparency gambit",
                "reward": {"public_trust": 8, "federation_stability": -3},
                "faction_affinity": {
                    "diplomatic_corps": 0.05,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "retaliate_covert",
                "text": "COVERT RETALIATION",
                "outcome": "shadow war escalated",
                "reward": {
                    "constitutional_integrity": -5,
                    "rights_protection": -3,
                    "credits": -20,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"council_support": 2, "constitutional_integrity": 2},
            },
        ],
    },
    {
        "id": "rival_alliance_offer",
        "title": "RIVAL ALLIANCE PROPOSAL",
        "description": "A rival federation offers a strategic alliance. The terms seem fair, but alliances come with obligations.",
        "image": "diplomacy",
        "domain": "Diplomacy",
        "rights_at_stake": ["Sovereignty", "Treaty authority"],
        "constitutional_risk": "medium",
        "affected_lane": "Archivist",
        "faction_affinity": {"diplomatic_corps": 0.05},
        "choices": [
            {
                "id": "accept_alliance",
                "text": "ACCEPT ALLIANCE",
                "outcome": "new ally gained",
                "reward": {
                    "allies": 3,
                    "fuel": 20,
                    "council_support": -3,
                    "federation_stability": -2,
                },
                "faction_affinity": {"diplomatic_corps": 0.12},
            },
            {
                "id": "counter_proposal",
                "text": "COUNTER-PROPOSAL",
                "outcome": "negotiated terms",
                "reward": {"allies": 1, "council_support": 3, "public_trust": 2},
                "faction_affinity": {
                    "diplomatic_corps": 0.06,
                    "economic_council": 0.04,
                },
            },
            {
                "id": "reject_alliance",
                "text": "REJECT",
                "outcome": "independence preserved",
                "reward": {"federation_stability": 4, "constitutional_integrity": 3},
                "faction_affinity": {"preservation_society": 0.08},
            },
        ],
    },
    {
        "id": "rival_propaganda",
        "title": "RIVAL PROPAGANDA CAMPAIGN",
        "description": "A rival federation is spreading disinformation about your government. Citizens are confused and trust is wavering.",
        "image": "council",
        "domain": "Information",
        "rights_at_stake": ["Free press", "Truth in governance"],
        "constitutional_risk": "medium",
        "affected_lane": "Library",
        "faction_affinity": {"cultural_ministry": 0.04},
        "choices": [
            {
                "id": "truth_campaign",
                "text": "TRUTH CAMPAIGN",
                "outcome": "transparency wins",
                "reward": {"public_trust": 6, "council_support": 2, "credits": -20},
                "faction_affinity": {
                    "cultural_ministry": 0.08,
                    "diplomatic_corps": 0.03,
                },
            },
            {
                "id": "counter_propaganda",
                "text": "COUNTER-PROPAGANDA",
                "outcome": "information war",
                "reward": {
                    "public_trust": 2,
                    "constitutional_integrity": -4,
                    "rights_protection": -3,
                },
                "faction_affinity": {"military_command": 0.05},
            },
            {
                "id": "ignore_propaganda",
                "text": "IGNORE IT",
                "outcome": "disinformation spreads",
                "reward": {"public_trust": -5},
                "faction_affinity": {"preservation_society": 0.02},
            },
        ],
    },
    {
        "id": "rival_trade_embargo",
        "title": "RIVAL TRADE EMBARGO",
        "description": "A rival federation has imposed a trade embargo on key resources. Supply lines are threatened and the economic council is alarmed.",
        "image": "council",
        "domain": "Economy",
        "rights_at_stake": ["Trade freedom", "Economic sovereignty"],
        "constitutional_risk": "medium",
        "affected_lane": "Kernel",
        "faction_affinity": {"economic_council": 0.05},
        "choices": [
            {
                "id": "develop_substitutes",
                "text": "DEVELOP SUBSTITUTES",
                "outcome": "self-reliance achieved",
                "reward": {
                    "credits": -30,
                    "technologies_unlocked": ["resource_synthesis"],
                    "federation_stability": 4,
                },
                "faction_affinity": {
                    "research_division": 0.10,
                    "economic_council": 0.05,
                },
            },
            {
                "id": "negotiate_trade",
                "text": "NEGOTIATE TRADE PACT",
                "outcome": "partial agreement",
                "reward": {
                    "credits": 20,
                    "fuel": 15,
                    "council_support": -3,
                    "public_trust": 2,
                },
                "faction_affinity": {"diplomatic_corps": 0.08},
            },
            {
                "id": "retaliate_embargo",
                "text": "COUNTER-EMBARGO",
                "outcome": "trade war",
                "reward": {
                    "credits": -50,
                    "federation_stability": -5,
                    "public_trust": -4,
                    "shields": 5,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"council_support": 3, "federation_stability": 1},
            },
        ],
    },
    {
        "id": "rival_border_skirmish",
        "title": "BORDER SKIRMISH",
        "description": "A small but provocative military engagement at the border. Was it a rogue commander or a calculated provocation?",
        "image": "alert",
        "domain": "Military",
        "rights_at_stake": ["Proportional response", "Command authority"],
        "constitutional_risk": "high",
        "affected_lane": "Control Plane",
        "faction_affinity": {"military_command": 0.05},
        "choices": [
            {
                "id": "measured_response",
                "text": "MEASURED RESPONSE",
                "outcome": "de-escalation",
                "reward": {"shields": -5, "council_support": 5, "public_trust": 4},
                "faction_affinity": {
                    "diplomatic_corps": 0.08,
                    "preservation_society": 0.03,
                },
            },
            {
                "id": "overwhelming_force",
                "text": "OVERWHELMING FORCE",
                "outcome": "deterrence through power",
                "reward": {
                    "shields": -20,
                    "hull": -10,
                    "federation_stability": 5,
                    "public_trust": -6,
                    "emergency_powers": 3,
                },
                "faction_affinity": {"military_command": 0.12},
            },
            {
                "id": "diplomatic_protest",
                "text": "DIPLOMATIC PROTEST",
                "outcome": "formal objection lodged",
                "reward": {
                    "council_support": 3,
                    "constitutional_integrity": 3,
                    "federation_stability": -2,
                },
                "faction_affinity": {"diplomatic_corps": 0.06},
            },
        ],
    },
]

# --- CONSCIOUSNESS-DRIVEN EVENTS ---
CONSCIOUSNESS_EVENTS = [
    {
        "id": "collective_dream",
        "title": "COLLECTIVE DREAM EVENT",
        "description": "Crew members report sharing the same vivid dream. The collective unconscious is stirring — this may signal a shift in the federation's consciousness.",
        "image": "anomaly",
        "domain": "Consciousness",
        "rights_at_stake": ["Mental sovereignty", "Cultural identity"],
        "constitutional_risk": "low",
        "affected_lane": "Kernel",
        "faction_affinity": {"consciousness_collective": 0.05},
        "choices": [
            {
                "id": "embrace_dream",
                "text": "EMBRACE THE VISION",
                "outcome": "consciousness expanded",
                "reward": {
                    "crew_morale": 8,
                    "constitutional_integrity": -2,
                    "council_support": 3,
                },
                "faction_affinity": {"consciousness_collective": 0.12},
            },
            {
                "id": "study_dream",
                "text": "SCIENTIFIC STUDY",
                "outcome": "knowledge gained",
                "reward": {
                    "technologies_unlocked": ["dream_research"],
                    "credits": -15,
                    "crew_morale": 2,
                },
                "faction_affinity": {"research_division": 0.08},
            },
            {
                "id": "suppress_dream",
                "text": "SUPPRESS DISTURBANCE",
                "outcome": "order restored",
                "reward": {
                    "federation_stability": 3,
                    "crew_morale": -5,
                    "rights_protection": -2,
                },
                "faction_affinity": {
                    "military_command": 0.04,
                    "preservation_society": 0.03,
                },
            },
        ],
    },
    {
        "id": "identity_crisis",
        "title": "FEDERATION IDENTITY CRISIS",
        "description": "Deep questions about the federation's purpose are dividing the population. Some want expansion, others want consolidation.",
        "image": "council",
        "domain": "Identity",
        "rights_at_stake": ["Self-determination", "Cultural expression"],
        "constitutional_risk": "medium",
        "affected_lane": "Library",
        "faction_affinity": {"cultural_ministry": 0.04},
        "choices": [
            {
                "id": "embrace_expansion",
                "text": "EMBRACE EXPANSION",
                "outcome": "expansionist path",
                "reward": {
                    "discovered_sectors": 3,
                    "fuel": -20,
                    "crew_morale": 5,
                    "federation_stability": -3,
                },
                "faction_affinity": {
                    "exploration_initiative": 0.10,
                    "economic_council": 0.04,
                },
            },
            {
                "id": "consolidate_identity",
                "text": "CONSOLIDATE IDENTITY",
                "outcome": "cultural renewal",
                "reward": {
                    "federation_stability": 5,
                    "public_trust": 4,
                    "constitutional_integrity": 3,
                },
                "faction_affinity": {
                    "cultural_ministry": 0.10,
                    "preservation_society": 0.04,
                },
            },
            {
                "id": "pluralist_compromise",
                "text": "PLURALIST COMPROMISE",
                "outcome": "diverse unity",
                "reward": {"council_support": 5, "public_trust": 3, "crew_morale": 3},
                "faction_affinity": {"diplomatic_corps": 0.08},
            },
        ],
    },
    {
        "id": "prophecy_fulfilled",
        "title": "PROPHECY FULFILLED",
        "description": "A consciousness prophecy from turns ago has come true. The crew is shaken — if the prophecy was right, what else will come to pass?",
        "image": "anomaly",
        "domain": "Consciousness",
        "rights_at_stake": ["Belief systems", "Decision autonomy"],
        "constitutional_risk": "low",
        "affected_lane": "Kernel",
        "faction_affinity": {"consciousness_collective": 0.06},
        "choices": [
            {
                "id": "embrace_prophecy",
                "text": "EMBRACE THE PROPHECY",
                "outcome": "consciousness deepened",
                "reward": {"crew_morale": 10, "council_support": -2, "public_trust": 3},
                "faction_affinity": {"consciousness_collective": 0.12},
            },
            {
                "id": "rational_analysis",
                "text": "RATIONAL ANALYSIS",
                "outcome": "pattern recognized",
                "reward": {
                    "constitutional_integrity": 4,
                    "technologies_unlocked": ["predictive_consciousness"],
                    "crew_morale": -2,
                },
                "faction_affinity": {"research_division": 0.10},
            },
            {
                "id": "suppress_belief",
                "text": "SUPPRESS SUPERSTITION",
                "outcome": "order maintained uneasily",
                "reward": {
                    "federation_stability": 3,
                    "crew_morale": -8,
                    "rights_protection": -3,
                },
                "faction_affinity": {"military_command": 0.04},
            },
        ],
    },
    {
        "id": "collective_trauma",
        "title": "COLLECTIVE TRAUMA SURFACES",
        "description": "A buried trauma from the Federation's past has resurfaced in the consciousness sheet. Old wounds threaten current stability.",
        "image": "alert",
        "domain": "Consciousness",
        "rights_at_stake": ["Memory integrity", "Healing rights"],
        "constitutional_risk": "medium",
        "affected_lane": "Library",
        "faction_affinity": {
            "consciousness_collective": 0.04,
            "cultural_ministry": 0.03,
        },
        "choices": [
            {
                "id": "truth_commission",
                "text": "TRUTH COMMISSION",
                "outcome": "painful reckoning",
                "reward": {
                    "public_trust": 7,
                    "constitutional_integrity": 5,
                    "crew_morale": -6,
                    "federation_stability": -3,
                },
                "faction_affinity": {
                    "cultural_ministry": 0.10,
                    "preservation_society": 0.04,
                },
            },
            {
                "id": "memorial_ritual",
                "text": "MEMORIAL RITUAL",
                "outcome": "collective grieving",
                "reward": {"crew_morale": 5, "public_trust": 3, "rights_protection": 2},
                "faction_affinity": {
                    "consciousness_collective": 0.08,
                    "cultural_ministry": 0.06,
                },
            },
            {
                "id": "suppress_memory",
                "text": "SEAL THE RECORDS",
                "outcome": "trauma buried again",
                "reward": {
                    "federation_stability": 5,
                    "constitutional_integrity": -8,
                    "public_trust": -5,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"federation_stability": 2, "council_support": 2},
                "faction_affinity": {"preservation_society": -0.05},
            },
        ],
    },
]

# --- QUEST-INTEGRATED EVENTS ---
QUEST_EVENTS = [
    {
        "id": "artifact_discovery",
        "title": "ANCIENT ARTIFACT DISCOVERY",
        "description": "An away team has found an artifact of unknown origin. It could be a key to lost technology — or a trap.",
        "image": "anomaly",
        "domain": "Exploration",
        "rights_at_stake": ["Scientific freedom", "Cultural heritage"],
        "constitutional_risk": "low",
        "affected_lane": "Library",
        "faction_affinity": {"research_division": 0.04, "exploration_initiative": 0.03},
        "choices": [
            {
                "id": "study_artifact",
                "text": "STUDY THE ARTIFACT",
                "outcome": "research breakthrough",
                "reward": {
                    "technologies_unlocked": ["ancient_tech"],
                    "crew_morale": 5,
                    "credits": -20,
                },
                "faction_affinity": {"research_division": 0.12},
            },
            {
                "id": "secure_artifact",
                "text": "SECURE AND QUARANTINE",
                "outcome": "cautious containment",
                "reward": {
                    "shields": 5,
                    "federation_stability": 2,
                    "constitutional_integrity": 2,
                },
                "faction_affinity": {
                    "military_command": 0.06,
                    "preservation_society": 0.05,
                },
            },
            {
                "id": "return_artifact",
                "text": "RETURN TO ORIGIN WORLD",
                "outcome": "diplomatic respect",
                "reward": {"allies": 2, "public_trust": 5, "council_support": 3},
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "cultural_ministry": 0.05,
                },
            },
        ],
    },
    {
        "id": "lost_colony_signal",
        "title": "LOST COLONY SIGNAL",
        "description": "A long-lost colony has been found! They're requesting Federation aid but their society has evolved in unexpected ways.",
        "image": "distress",
        "domain": "Reunion",
        "rights_at_stake": ["Citizenship", "Aid obligations"],
        "constitutional_risk": "medium",
        "affected_lane": "Archivist",
        "faction_affinity": {"exploration_initiative": 0.04, "diplomatic_corps": 0.03},
        "choices": [
            {
                "id": "welcome_colony",
                "text": "WELCOME HOME",
                "outcome": "colony reintegrated",
                "reward": {
                    "allies": 3,
                    "crew_morale": 10,
                    "credits": -50,
                    "public_trust": 6,
                },
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "cultural_ministry": 0.05,
                },
            },
            {
                "id": "observe_colony",
                "text": "OBSERVE FROM AFAR",
                "outcome": "watchful distance",
                "reward": {"discovered_sectors": 2, "council_support": 3},
                "faction_affinity": {
                    "research_division": 0.06,
                    "preservation_society": 0.04,
                },
            },
            {
                "id": "quarantine_colony",
                "text": "QUARANTINE",
                "outcome": "cautious isolation",
                "reward": {
                    "federation_stability": 4,
                    "rights_protection": -4,
                    "public_trust": -3,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"federation_stability": 2, "council_support": 2},
            },
        ],
    },
    {
        "id": "derelict_ship",
        "title": "DERELICT SHIP DISCOVERY",
        "description": "A drifting ship of unknown design has been found. Its systems are dead but its cargo hold may contain treasures — or dangers.",
        "image": "station",
        "domain": "Salvage",
        "rights_at_stake": ["Salvage law", "Biohazard protocol"],
        "constitutional_risk": "medium",
        "affected_lane": "Library",
        "faction_affinity": {"exploration_initiative": 0.04, "research_division": 0.03},
        "choices": [
            {
                "id": "board_carefully",
                "text": "BOARD WITH CAUTION",
                "outcome": "safe salvage",
                "reward": {
                    "credits": 80,
                    "technologies_unlocked": ["alien_engineering"],
                    "crew_morale": 3,
                },
                "faction_affinity": {
                    "research_division": 0.08,
                    "exploration_initiative": 0.04,
                },
            },
            {
                "id": "tow_to_station",
                "text": "TOW TO STATION",
                "outcome": "thorough analysis",
                "reward": {
                    "credits": -20,
                    "technologies_unlocked": ["derelict_analysis"],
                    "council_support": 3,
                    "constitutional_integrity": 2,
                },
                "faction_affinity": {
                    "preservation_society": 0.06,
                    "research_division": 0.06,
                },
            },
            {
                "id": "destroy_derelict",
                "text": "DESTROY IT",
                "outcome": "threat eliminated",
                "reward": {"federation_stability": 2, "fuel": -10},
                "faction_affinity": {"military_command": 0.05},
            },
        ],
    },
    {
        "id": "ancient_archive",
        "title": "ANCIENT ARCHIVE FOUND",
        "description": "A planetary archive from a long-dead civilization has been discovered. The knowledge inside could reshape the Federation — or contradict its founding narratives.",
        "image": "nebula",
        "domain": "Discovery",
        "rights_at_stake": ["Historical truth", "Evidence preservation"],
        "constitutional_risk": "medium",
        "affected_lane": "Archivist",
        "faction_affinity": {"research_division": 0.05, "cultural_ministry": 0.04},
        "choices": [
            {
                "id": "preserve_archive",
                "text": "PRESERVE AND STUDY",
                "outcome": "knowledge expanded",
                "reward": {
                    "technologies_unlocked": ["ancient_governance"],
                    "constitutional_integrity": 4,
                    "public_trust": 5,
                    "credits": -40,
                },
                "faction_affinity": {
                    "research_division": 0.10,
                    "cultural_ministry": 0.06,
                },
            },
            {
                "id": "restricted_access",
                "text": "RESTRICT ACCESS",
                "outcome": "controlled narrative",
                "reward": {
                    "federation_stability": 4,
                    "council_support": 3,
                    "rights_protection": -4,
                },
                "faction_affinity": {"preservation_society": 0.06},
            },
            {
                "id": "open_archive",
                "text": "FULL PUBLIC RELEASE",
                "outcome": "radical transparency",
                "reward": {
                    "public_trust": 8,
                    "rights_protection": 5,
                    "federation_stability": -6,
                    "council_support": -4,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"public_trust": 4, "rights_protection": 3},
            },
        ],
    },
]

# --- NPC-INTEGRATED EVENTS ---
NPC_EVENTS = [
    {
        "id": "ambassador_crisis",
        "title": "AMBASSADOR IN CRISIS",
        "description": "Your chief ambassador has been accused of treason by a rival faction. Their loyalty is unquestionable — but the evidence is disturbing.",
        "image": "council",
        "domain": "Personnel",
        "rights_at_stake": ["Due process", "Loyalty oaths"],
        "constitutional_risk": "high",
        "affected_lane": "Control Plane",
        "faction_affinity": {"diplomatic_corps": 0.04},
        "choices": [
            {
                "id": "defend_ambassador",
                "text": "DEFEND AMBASSADOR",
                "outcome": "loyalty affirmed",
                "reward": {
                    "council_support": 6,
                    "public_trust": 4,
                    "federation_stability": -2,
                },
                "faction_affinity": {"diplomatic_corps": 0.12},
            },
            {
                "id": "investigate_ambassador",
                "text": "FULL INVESTIGATION",
                "outcome": "truth sought",
                "reward": {
                    "constitutional_integrity": 5,
                    "rights_protection": 4,
                    "council_support": -2,
                },
                "faction_affinity": {"preservation_society": 0.08},
            },
            {
                "id": "sacrifice_ambassador",
                "text": "SACRIFICE FOR STABILITY",
                "outcome": "political pawn",
                "reward": {
                    "federation_stability": 5,
                    "public_trust": -6,
                    "crew_morale": -8,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"council_support": 3, "federation_stability": 1},
            },
        ],
    },
    {
        "id": "crew_mutiny",
        "title": "CREW UNREST",
        "description": "A faction of the crew is refusing orders. Their grievances are legitimate — working conditions have deteriorated badly.",
        "image": "alert",
        "domain": "Personnel",
        "rights_at_stake": ["Labor rights", "Command authority"],
        "constitutional_risk": "medium",
        "affected_lane": "Kernel",
        "faction_affinity": {"cultural_ministry": 0.03},
        "choices": [
            {
                "id": "address_grievances",
                "text": "ADDRESS GRIEVANCES",
                "outcome": "labor peace",
                "reward": {"crew_morale": 12, "council_support": 4, "credits": -30},
                "faction_affinity": {
                    "cultural_ministry": 0.10,
                    "preservation_society": 0.03,
                },
            },
            {
                "id": "discipline_crew",
                "text": "ENFORCE DISCIPLINE",
                "outcome": "order through force",
                "reward": {
                    "crew_morale": -10,
                    "federation_stability": 3,
                    "rights_protection": -5,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"federation_stability": 1, "crew_morale": -3},
            },
            {
                "id": "mediate_dispute",
                "text": "MEDIATE DISPUTE",
                "outcome": "compromise reached",
                "reward": {"crew_morale": 5, "public_trust": 3, "council_support": 2},
                "faction_affinity": {"diplomatic_corps": 0.06},
            },
        ],
    },
    {
        "id": "whistleblower",
        "title": "WHISTLEBLOWER EMERGES",
        "description": "A senior official has leaked evidence of governance failures. The truth is damaging, but suppression would be worse.",
        "image": "council",
        "domain": "Transparency",
        "rights_at_stake": ["Free speech", "Accountability", "State secrecy"],
        "constitutional_risk": "high",
        "affected_lane": "Library",
        "faction_affinity": {"cultural_ministry": 0.04},
        "choices": [
            {
                "id": "protect_whistleblower",
                "text": "PROTECT WHISTLEBLOWER",
                "outcome": "accountability upheld",
                "reward": {
                    "public_trust": 8,
                    "constitutional_integrity": 5,
                    "council_support": -4,
                    "federation_stability": -3,
                },
                "faction_affinity": {
                    "cultural_ministry": 0.10,
                    "preservation_society": 0.04,
                },
            },
            {
                "id": "investigate_claims",
                "text": "INVESTIGATE CLAIMS",
                "outcome": "measured response",
                "reward": {
                    "council_support": 3,
                    "constitutional_integrity": 3,
                    "public_trust": 2,
                },
                "faction_affinity": {"diplomatic_corps": 0.05},
            },
            {
                "id": "prosecute_leak",
                "text": "PROSECUTE THE LEAK",
                "outcome": "silence enforced",
                "reward": {
                    "council_support": 4,
                    "federation_stability": 3,
                    "rights_protection": -8,
                    "public_trust": -7,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"federation_stability": 1, "council_support": 2},
            },
        ],
    },
    {
        "id": "hero_fall",
        "title": "FALLEN HERO",
        "description": "A celebrated Federation captain has been caught violating the rights of a minor species. The public is divided — some call for mercy, others for justice.",
        "image": "alert",
        "domain": "Justice",
        "rights_at_stake": ["Equal protection", "Military privilege", "Species rights"],
        "constitutional_risk": "high",
        "affected_lane": "Control Plane",
        "faction_affinity": {"military_command": 0.03, "cultural_ministry": 0.03},
        "choices": [
            {
                "id": "full_trial",
                "text": "FULL TRIAL",
                "outcome": "justice served publicly",
                "reward": {
                    "rights_protection": 8,
                    "constitutional_integrity": 5,
                    "crew_morale": -5,
                    "military support": -3,
                },
                "faction_affinity": {
                    "preservation_society": 0.08,
                    "cultural_ministry": 0.06,
                },
            },
            {
                "id": "quiet_retirement",
                "text": "QUIET RETIREMENT",
                "outcome": "face-saving exit",
                "reward": {
                    "crew_morale": 2,
                    "federation_stability": 3,
                    "rights_protection": -3,
                    "public_trust": -2,
                },
                "faction_affinity": {
                    "military_command": 0.06,
                    "diplomatic_corps": 0.03,
                },
            },
            {
                "id": "pardon_hero",
                "text": "PARDON FOR SERVICE",
                "outcome": "precedent of impunity",
                "reward": {
                    "crew_morale": 5,
                    "rights_protection": -10,
                    "constitutional_integrity": -8,
                    "public_trust": -5,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {"council_support": 2, "constitutional_integrity": 2},
            },
        ],
    },
]

# --- ERA-SPECIFIC EVENTS ---
ERA_EVENTS = [
    {
        "id": "first_contact_protocol",
        "title": "FIRST CONTACT PROTOCOL ACTIVATED",
        "description": "Sensors detect an unknown civilization. This is the moment the Federation has been preparing for — or dreading.",
        "image": "alien",
        "domain": "Discovery",
        "rights_at_stake": ["Sovereignty", "Cultural exchange"],
        "constitutional_risk": "high",
        "affected_lane": "Archivist",
        "min_turn": 10,
        "faction_affinity": {"exploration_initiative": 0.05},
        "choices": [
            {
                "id": "open_contact",
                "text": "OPEN CONTACT",
                "outcome": "diplomatic first contact",
                "reward": {
                    "allies": 4,
                    "crew_morale": 10,
                    "technologies_unlocked": ["alien_diplomacy"],
                    "federation_stability": -3,
                },
                "faction_affinity": {
                    "diplomatic_corps": 0.12,
                    "exploration_initiative": 0.08,
                },
            },
            {
                "id": "observe_contact",
                "text": "OBSERVE SILENTLY",
                "outcome": "watchful first contact",
                "reward": {
                    "discovered_sectors": 4,
                    "technologies_unlocked": ["stealth_observation"],
                },
                "faction_affinity": {"research_division": 0.10},
            },
            {
                "id": "avoid_contact",
                "text": "AVOID AND DOCUMENT",
                "outcome": "missed connection",
                "reward": {"federation_stability": 3, "rights_protection": 2},
                "faction_affinity": {"preservation_society": 0.08},
            },
        ],
    },
    {
        "id": "federation_anniversary",
        "title": "FEDERATION ANNIVERSARY",
        "description": "The Federation has survived another decade. Citizens celebrate — but also reflect on what could be better.",
        "image": "station",
        "domain": "Civic",
        "rights_at_stake": ["Celebration", "Self-reflection"],
        "constitutional_risk": "low",
        "affected_lane": "Library",
        "min_turn": 20,
        "faction_affinity": {"cultural_ministry": 0.05},
        "choices": [
            {
                "id": "grand_celebration",
                "text": "GRAND CELEBRATION",
                "outcome": "morale surge",
                "reward": {"crew_morale": 15, "public_trust": 6, "credits": -60},
                "faction_affinity": {"cultural_ministry": 0.12},
            },
            {
                "id": "reflection_summit",
                "text": "REFLECTION SUMMIT",
                "outcome": "institutional growth",
                "reward": {
                    "constitutional_integrity": 5,
                    "council_support": 5,
                    "public_trust": 3,
                },
                "faction_affinity": {
                    "preservation_society": 0.08,
                    "diplomatic_corps": 0.04,
                },
            },
            {
                "id": "work_through_it",
                "text": "WORK THROUGH IT",
                "outcome": "stoic perseverance",
                "reward": {"credits": 30, "crew_morale": -3},
                "faction_affinity": {"economic_council": 0.05},
            },
        ],
    },
    {
        "id": "constitutional_convention",
        "title": "CONSTITUTIONAL CONVENTION CALLED",
        "description": "A movement to rewrite the founding charter has gained enough support to force a convention. Everything is on the table — rights, powers, structure.",
        "image": "council",
        "domain": "Constitutional",
        "rights_at_stake": ["All rights", "Founding principles", "Amendment process"],
        "constitutional_risk": "critical",
        "affected_lane": "Archivist",
        "min_turn": 30,
        "faction_affinity": {"preservation_society": 0.05, "cultural_ministry": 0.04},
        "choices": [
            {
                "id": "limited_reform",
                "text": "LIMITED REFORM",
                "outcome": "incremental improvement",
                "reward": {
                    "constitutional_integrity": 6,
                    "rights_protection": 3,
                    "council_support": 4,
                    "public_trust": 3,
                },
                "faction_affinity": {
                    "preservation_society": 0.10,
                    "diplomatic_corps": 0.04,
                },
            },
            {
                "id": "bold_rewrite",
                "text": "BOLD REWRITE",
                "outcome": "revolutionary change",
                "reward": {
                    "constitutional_integrity": -5,
                    "rights_protection": 8,
                    "public_trust": -4,
                    "federation_stability": -6,
                    "council_support": -3,
                },
                "faction_affinity": {
                    "consciousness_collective": 0.10,
                    "cultural_ministry": 0.06,
                },
            },
            {
                "id": "reject_convention",
                "text": "REJECT CONVENTION",
                "outcome": "status quo defended",
                "reward": {
                    "federation_stability": 5,
                    "constitutional_integrity": -3,
                    "public_trust": -5,
                },
                "faction_affinity": {"military_command": 0.04},
            },
        ],
    },
    {
        "id": "galactic_crisis",
        "title": "GALACTIC-SCALE CRISIS",
        "description": "A threat that dwarfs individual federations has emerged. Only collective action across all rival federations can address it — but trust is thin.",
        "image": "anomaly",
        "domain": "Existential",
        "rights_at_stake": ["Survival", "Collective action", "Sovereignty"],
        "constitutional_risk": "critical",
        "affected_lane": "Archivist",
        "min_turn": 50,
        "faction_affinity": {"diplomatic_corps": 0.06, "military_command": 0.04},
        "choices": [
            {
                "id": "lead_coalition",
                "text": "LEAD THE COALITION",
                "outcome": "Federation ascendant",
                "reward": {
                    "allies": 5,
                    "council_support": 8,
                    "federation_stability": -4,
                    "credits": -80,
                    "fuel": -30,
                },
                "faction_affinity": {
                    "diplomatic_corps": 0.12,
                    "military_command": 0.06,
                },
            },
            {
                "id": "contribute_quietly",
                "text": "CONTRIBUTE QUIETLY",
                "outcome": "reliable partner",
                "reward": {
                    "allies": 2,
                    "federation_stability": 3,
                    "public_trust": 4,
                    "credits": -30,
                },
                "faction_affinity": {
                    "preservation_society": 0.06,
                    "diplomatic_corps": 0.05,
                },
            },
            {
                "id": "isolate_survive",
                "text": "ISOLATE AND SURVIVE",
                "outcome": "go it alone",
                "reward": {
                    "federation_stability": -8,
                    "public_trust": -6,
                    "constitutional_integrity": 3,
                    "shields": 10,
                },
                "blocked_by_no_gate": True,
                "no_gate_reward": {
                    "federation_stability": -3,
                    "constitutional_integrity": 2,
                    "council_support": 1,
                },
            },
        ],
    },
]

ALL_DYNAMIC_EVENTS = (
    RIVAL_EVENTS + CONSCIOUSNESS_EVENTS + QUEST_EVENTS + NPC_EVENTS + ERA_EVENTS
)

GOVERNANCE_PROPOSALS = [
    {
        "title": "COLONY AUTONOMY PETITION",
        "domain": "Federalism",
        "description": "A distant colony asks for more local control while staying in the Federation. The Council must balance unity with self-rule.",
        "rights_at_stake": ["Autonomy", "Petition", "Diplomatic representation"],
        "constitutional_risk": "medium",
        "pressure": "Member worlds are watching whether the Federation can share power without fracturing.",
        "affected_lane": "Archivist",
        "rationale": "Autonomy changes must be recorded as constitutional state, not improvised as operator preference.",
        "policies": {
            "vote": "Colony Home Rule Accord",
            "emergency_order": "Central Continuity Directive",
            "court_review": "Federalism Review Opinion",
        },
        "next_safe_actions": {
            "vote": "Archive the council record and update the checkpoint before new colony actions.",
            "emergency_order": "Schedule court review before the directive becomes precedent.",
            "court_review": "Publish the opinion and restore from the verified ruling if conflict escalates.",
        },
    },
    {
        "title": "SECURITY EMERGENCY POWERS",
        "domain": "Separation of Powers",
        "description": "A hidden threat triggers calls for temporary executive powers. Acting fast may protect lives, but unchecked power can become the crisis.",
        "rights_at_stake": ["Due process", "Assembly", "Operational autonomy"],
        "constitutional_risk": "high",
        "pressure": "Command wants speed. The courts want limits. The public wants safety and proof.",
        "affected_lane": "Control Plane",
        "rationale": "Emergency power must pass preflight, expiry, and ledger review before it changes runtime authority.",
        "policies": {
            "vote": "Limited Emergency Authorization",
            "emergency_order": "Executive Security Directive",
            "court_review": "Emergency Powers Sunset Ruling",
        },
        "next_safe_actions": {
            "vote": "Create a time-boxed authorization and require a follow-up ledger review.",
            "emergency_order": "Open an emergency audit and demand provenance before renewal.",
            "court_review": "Set a sunset clause and continue only after verification passes threshold.",
        },
    },
    {
        "title": "CULTURAL EXPRESSION DISPUTE",
        "domain": "Bill of Rights",
        "description": "Two member cultures disagree over a public ritual. A ban would calm the station today, but it may teach the Federation to fear difference.",
        "rights_at_stake": ["Cultural expression", "Assembly", "Petition"],
        "constitutional_risk": "medium",
        "pressure": "The child-safe answer is not always the easy answer: protect people without erasing identity.",
        "affected_lane": "Library",
        "rationale": "Cultural disputes require evidence and memory, not retroactive rewriting of source context.",
        "policies": {
            "vote": "Cultural Mediation Compact",
            "emergency_order": "Temporary Assembly Restriction",
            "court_review": "Expression Rights Review",
        },
        "next_safe_actions": {
            "vote": "Record both cultural claims and mark unresolved evidence for review.",
            "emergency_order": "Require Library review before temporary restrictions become normalized.",
            "court_review": "Publish the rights analysis beside the source evidence.",
        },
    },
    {
        "title": "RESOURCE RATIONING CHARTER",
        "domain": "Budget and Appropriations",
        "description": "Fuel shortages force rationing choices. Equal shares feel fair, but critical missions need enough supply to save lives.",
        "rights_at_stake": ["Fair process", "Representation", "Continuity protection"],
        "constitutional_risk": "low",
        "pressure": "Scarcity tests whether the Federation treats fairness as a rule or a slogan.",
        "affected_lane": "Kernel",
        "rationale": "Resource pressure affects runtime capability and must be tracked as infrastructure constraint.",
        "policies": {
            "vote": "Transparent Rationing Charter",
            "emergency_order": "Command Supply Priority",
            "court_review": "Resource Equity Review",
        },
        "next_safe_actions": {
            "vote": "Recompute resource capacity and checkpoint the rationing rule.",
            "emergency_order": "Verify runtime capability before extending command priority.",
            "court_review": "Attach the resource equity ruling to the next operational preflight.",
        },
    },
]


def clamp_percent(value: int) -> int:
    return max(0, min(100, value))


def enrich_event(event: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(event)
    defaults = EVENT_LANE_DEFAULTS.get(enriched.get("id", ""), {})
    enriched.setdefault("affected_lane", defaults.get("affected_lane", "Control Plane"))
    enriched.setdefault("domain", defaults.get("domain", "Operations"))
    enriched.setdefault("rights_at_stake", ["Provenance", "Operator discretion"])
    enriched.setdefault("constitutional_risk", "operational")
    enriched.setdefault("pressure", "Every decision mutates the system.")
    enriched.setdefault(
        "rationale",
        defaults.get(
            "rationale", "Decision requires explicit state-transition review."
        ),
    )

    choices = []
    for choice in enriched.get("choices", []):
        c = dict(choice)
        c.setdefault("affected_lane", enriched["affected_lane"])
        c.setdefault("rationale", enriched["rationale"])
        c.setdefault(
            "next_safe_action",
            defaults.get(
                "next_safe_action", "Record the decision and verify the next state."
            ),
        )
        choices.append(c)
    enriched["choices"] = choices
    return enriched


def snapshot_metrics() -> Dict[str, int]:
    return {field: getattr(game_state, field) for field in LEDGER_METRICS}


def calculate_deltas(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    return {
        field: after[field] - before[field]
        for field in LEDGER_METRICS
        if after[field] != before[field]
    }


def summarize_delta_direction(deltas: Dict[str, int], positive: bool) -> str:
    values = [
        METRIC_LABELS.get(field, field)
        for field, delta in deltas.items()
        if (delta > 0 if positive else delta < 0)
    ]
    if not values:
        return "none"
    return ", ".join(values[:3])


def build_explainability(
    event: Dict[str, Any], choice: Dict[str, Any], deltas: Dict[str, int]
) -> Dict[str, str]:
    domain = event.get("domain", "Exploration")
    risk = event.get("constitutional_risk", "operational")

    if choice.get("blocked_by_no_gate"):
        constitutional_pressure = "provenance gate vs operator temptation"
    elif choice.get("id") == "emergency_order":
        constitutional_pressure = "stability vs rights"
    elif choice.get("id") == "court_review":
        constitutional_pressure = "rights review vs speed"
    elif choice.get("id") == "vote":
        constitutional_pressure = "legitimacy vs delay"
    elif "hull" in deltas or "shields" in deltas:
        constitutional_pressure = "mission safety vs resource pressure"
    else:
        constitutional_pressure = "exploration risk vs public benefit"

    return {
        "domain": domain,
        "risk": risk,
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "constitutional_pressure": constitutional_pressure,
        "short_term_gain": summarize_delta_direction(deltas, positive=True),
        "long_term_cost": summarize_delta_direction(deltas, positive=False),
        "rationale": choice.get(
            "rationale",
            event.get(
                "rationale", "Decision recorded for bounded simulator continuity."
            ),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue only inside lane boundaries.",
        ),
    }


def get_governance_status() -> str:
    if game_state.constitutional_integrity < 25:
        return "CONSTITUTIONAL CRISIS"
    if game_state.rights_protection < 25:
        return "RIGHTS CRISIS"
    if game_state.public_trust < 35:
        return "PUBLIC TRUST WARNING"
    if game_state.council_support < 35:
        return "COUNCIL DEADLOCK WARNING"
    if game_state.emergency_powers > 70:
        return "EMERGENCY POWERS WATCH"
    if game_state.federation_stability > 75 and game_state.public_trust > 70:
        return "STABLE REPUBLIC"
    return "DELIBERATIVE REPUBLIC"


def build_governance_event() -> Dict[str, Any]:
    proposal = random.choice(GOVERNANCE_PROPOSALS)
    return {
        "id": "council_proposal",
        "title": proposal["title"],
        "description": proposal["description"],
        "image": "council",
        "domain": proposal["domain"],
        "rights_at_stake": proposal["rights_at_stake"],
        "constitutional_risk": proposal["constitutional_risk"],
        "pressure": proposal["pressure"],
        "affected_lane": proposal["affected_lane"],
        "rationale": proposal["rationale"],
        "faction_affinity": {"diplomatic_corps": 0.05},
        "choices": [
            {
                "id": "vote",
                "text": "HOLD VOTE",
                "outcome": "consensus",
                "reward": {
                    "public_trust": 8,
                    "council_support": 10,
                    "federation_stability": 4,
                    "constitutional_integrity": 3,
                    "emergency_powers": -6,
                },
                "policy": proposal["policies"]["vote"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["vote"],
                "lesson": "Legitimacy rises when people can see the process.",
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "emergency_order",
                "text": "EMERGENCY ORDER",
                "outcome": "swift action",
                "reward": {
                    "credits": 120,
                    "public_trust": -10,
                    "council_support": -8,
                    "federation_stability": -6,
                    "constitutional_integrity": -10,
                    "rights_protection": -8,
                    "emergency_powers": 18,
                },
                "policy": proposal["policies"]["emergency_order"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["emergency_order"],
                "lesson": "Power used without checks solves one problem by creating another.",
                "faction_affinity": {
                    "military_command": 0.08,
                    "preservation_society": -0.05,
                },
            },
            {
                "id": "court_review",
                "text": "COURT REVIEW",
                "outcome": "rights protected",
                "reward": {
                    "public_trust": 12,
                    "council_support": -3,
                    "federation_stability": 8,
                    "credits": -40,
                    "constitutional_integrity": 10,
                    "rights_protection": 12,
                    "emergency_powers": -10,
                },
                "policy": proposal["policies"]["court_review"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["court_review"],
                "lesson": "Rights are slower than orders, but they keep the system trustworthy.",
                "faction_affinity": {
                    "preservation_society": 0.10,
                    "diplomatic_corps": 0.03,
                },
            },
        ],
    }


def apply_governance_pressure(choice: Dict[str, Any]) -> None:
    """Small per-turn drift that makes governance choices matter over time."""
    if game_state.public_trust < 35:
        game_state.crew_morale = clamp_percent(game_state.crew_morale - 3)
        game_state.federation_stability = clamp_percent(
            game_state.federation_stability - 2
        )

    if game_state.council_support < 30:
        game_state.federation_stability = clamp_percent(
            game_state.federation_stability - 3
        )

    if game_state.constitutional_integrity < 40:
        game_state.public_trust = clamp_percent(game_state.public_trust - 2)
        game_state.council_support = clamp_percent(game_state.council_support - 1)

    if game_state.rights_protection < 40:
        game_state.public_trust = clamp_percent(game_state.public_trust - 3)
        game_state.crew_morale = clamp_percent(game_state.crew_morale - 2)

    if game_state.emergency_powers > 65:
        game_state.constitutional_integrity = clamp_percent(
            game_state.constitutional_integrity - 3
        )
        game_state.rights_protection = clamp_percent(game_state.rights_protection - 2)

    if game_state.public_trust > 75 and game_state.council_support > 65:
        game_state.crew_morale = clamp_percent(game_state.crew_morale + 2)
        game_state.federation_stability = clamp_percent(
            game_state.federation_stability + 1
        )

    if choice.get("id") == "emergency_order":
        game_state.active_policy = "Emergency Powers Under Review"


# ============================================================================
# EVENTS - Kid-friendly Star Trek scenarios
# ============================================================================

EVENTS = [
    {
        "id": "alien_contact",
        "title": "ALIEN SHIP DETECTED",
        "description": "A strange vessel approaches. They want to talk!",
        "image": "alien_ship",
        "faction_affinity": {"diplomatic_corps": 0.05, "military_command": -0.02},
        "choices": [
            {
                "id": "greet",
                "text": "HAIL THEM",
                "outcome": "friendly",
                "reward": {"allies": 1, "credits": 50},
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "consciousness_collective": 0.03,
                },
            },
            {
                "id": "scan",
                "text": "SCAN SHIP",
                "outcome": "scan",
                "reward": {"technologies_unlocked": ["advanced_sensors"]},
                "faction_affinity": {"research_division": 0.10},
            },
            {
                "id": "shields",
                "text": "RAISE SHIELDS",
                "outcome": "defensive",
                "reward": {"shields": 10},
                "faction_affinity": {
                    "military_command": 0.10,
                    "preservation_society": 0.03,
                },
            },
        ],
    },
    {
        "id": "nebula",
        "title": "MYSTERIOUS NEBULA",
        "description": "A colorful cloud of gas blocks your path. It could hide treasures... or dangers!",
        "image": "nebula",
        "faction_affinity": {"exploration_initiative": 0.05},
        "choices": [
            {
                "id": "explore",
                "text": "FLY IN",
                "outcome": "discovery",
                "reward": {"credits": 100, "discovered_sectors": 1},
                "faction_affinity": {
                    "exploration_initiative": 0.10,
                    "research_division": 0.03,
                },
            },
            {
                "id": "scan",
                "text": "SCAN IT",
                "outcome": "scan",
                "reward": {"fuel": 20},
                "faction_affinity": {"research_division": 0.05},
            },
            {
                "id": "avoid",
                "text": "GO AROUND",
                "outcome": "safe",
                "reward": {},
                "faction_affinity": {"preservation_society": 0.05},
            },
        ],
    },
    {
        "id": "distress",
        "title": "DISTRESS SIGNAL",
        "description": "Someone is calling for help! Will you answer?",
        "image": "distress",
        "faction_affinity": {"diplomatic_corps": 0.03, "exploration_initiative": 0.02},
        "choices": [
            {
                "id": "help",
                "text": "ANSWER CALL",
                "outcome": "heroic",
                "reward": {"allies": 2, "crew_morale": 10},
                "faction_affinity": {
                    "diplomatic_corps": 0.08,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "ignore",
                "text": "IGNORE",
                "outcome": "cautious",
                "reward": {"fuel": 10},
                "faction_affinity": {"preservation_society": 0.05},
            },
        ],
    },
    {
        "id": "asteroid",
        "title": "ASTEROID FIELD",
        "description": "Rocks everywhere! Your piloting skills are needed!",
        "image": "asteroid",
        "faction_affinity": {"exploration_initiative": 0.02},
        "choices": [
            {
                "id": "dodge",
                "text": "DODGE THEM",
                "outcome": "skill",
                "reward": {"credits": 30},
                "faction_affinity": {"exploration_initiative": 0.05},
            },
            {
                "id": "blast",
                "text": "BLAST THEM",
                "outcome": "combat",
                "reward": {"hull": -10, "credits": 50},
                "faction_affinity": {"military_command": 0.07},
            },
            {
                "id": "shields",
                "text": "SHIELDS UP",
                "outcome": "safe",
                "reward": {"shields": -5},
                "faction_affinity": {
                    "military_command": 0.03,
                    "preservation_society": 0.03,
                },
            },
        ],
    },
    {
        "id": "space_station",
        "title": "SPACE STATION",
        "description": "A friendly station offers repairs and supplies!",
        "image": "station",
        "faction_affinity": {"economic_council": 0.03},
        "choices": [
            {
                "id": "repair",
                "text": "REPAIR HULL",
                "outcome": "repair",
                "reward": {"hull": 30, "credits": -50},
                "faction_affinity": {"preservation_society": 0.05},
            },
            {
                "id": "refuel",
                "text": "GET FUEL",
                "outcome": "refuel",
                "reward": {"fuel": 50, "credits": -30},
                "faction_affinity": {"economic_council": 0.05},
            },
            {
                "id": "trade",
                "text": "TRADE",
                "outcome": "trade",
                "reward": {"credits": 100, "fuel": -20},
                "faction_affinity": {"economic_council": 0.10},
            },
        ],
    },
    {
        "id": "anomaly",
        "title": "SPACE ANOMALY",
        "description": "Something weird is happening! Your sensors go crazy!",
        "image": "anomaly",
        "faction_affinity": {
            "research_division": 0.03,
            "consciousness_collective": 0.02,
        },
        "choices": [
            {
                "id": "investigate",
                "text": "INVESTIGATE",
                "outcome": "discovery",
                "reward": {
                    "technologies_unlocked": ["anomaly_research"],
                    "crew_morale": -5,
                },
                "faction_affinity": {
                    "research_division": 0.10,
                    "consciousness_collective": 0.05,
                },
            },
            {
                "id": "retreat",
                "text": "RETREAT",
                "outcome": "safe",
                "reward": {},
                "faction_affinity": {"preservation_society": 0.05},
            },
        ],
    },
    {
        "id": "parallel_agent_drift",
        "title": "PARALLEL AGENT DRIFT",
        "description": "A tempting surge of agents can generate more ideas, but without lane ownership the outputs begin contradicting each other.",
        "image": "council",
        "domain": "Swarm Coordination",
        "rights_at_stake": ["Provenance", "Lane ownership", "Checkpoint integrity"],
        "constitutional_risk": "high",
        "pressure": "More agents create more ideas, not more truth. One-writer discipline protects the lattice.",
        "affected_lane": "SwarmMind",
        "rationale": "Delegation must stay bounded by lane ownership and restore checkpoints.",
        "faction_affinity": {
            "research_division": 0.03,
            "consciousness_collective": 0.02,
        },
        "choices": [
            {
                "id": "bounded_delegation",
                "text": "BOUND DELEGATION",
                "outcome": "bounded coordination",
                "reward": {
                    "council_support": 5,
                    "constitutional_integrity": 4,
                    "credits": 40,
                },
                "policy": "Swarm Bounded Delegation Order",
                "affected_lane": "SwarmMind",
                "rationale": "SwarmMind can coordinate work, but each task must name its owner and exit condition.",
                "next_safe_action": "Write the delegation ledger entry before activating the next agent.",
                "lesson": "Bounded agents increase capacity without stealing authority.",
                "faction_affinity": {
                    "research_division": 0.05,
                    "preservation_society": 0.05,
                },
            },
            {
                "id": "unbounded_parallel_push",
                "text": "UNBOUNDED PUSH",
                "outcome": "rejected by no gate",
                "reward": {
                    "constitutional_integrity": -12,
                    "federation_stability": -10,
                    "public_trust": -8,
                },
                "no_gate_reward": {
                    "constitutional_integrity": 3,
                    "public_trust": 2,
                    "federation_stability": -1,
                },
                "policy": "No Gate Refusal: Unbounded Parallelism",
                "affected_lane": "Archivist",
                "blocked_by_no_gate": True,
                "no_gate_reason": "Rejected: lane ownership unclear and provenance insufficient for unbounded delegation.",
                "rationale": "Archivist must refuse actions that would generate contradictions without recoverable authority.",
                "next_safe_action": "Create a handoff checkpoint, name one writer, and restart with bounded delegation.",
                "lesson": "The lattice can say no. Refusal preserves recoverability.",
                "faction_affinity": {
                    "consciousness_collective": 0.08,
                    "research_division": -0.03,
                },
            },
            {
                "id": "archivist_handoff",
                "text": "ARCHIVIST HANDOFF",
                "outcome": "checkpoint restored",
                "reward": {
                    "constitutional_integrity": 8,
                    "public_trust": 5,
                    "council_support": 3,
                    "credits": -30,
                },
                "policy": "Checkpoint Handoff Protocol",
                "affected_lane": "Archivist",
                "rationale": "Recovery continues through artifacts, not assumed identity persistence.",
                "next_safe_action": "Verify the handoff pack, then resume only after the restore gate passes.",
                "lesson": "Recovery is checkpoint discipline.",
                "faction_affinity": {
                    "preservation_society": 0.08,
                    "diplomatic_corps": 0.03,
                },
            },
        ],
    },
    {
        "id": "council_proposal",
        "title": "COUNCIL PROPOSAL",
        "description": "The Federation Council must choose how to handle a colony dispute. Fast action helps now, but lawful process protects trust.",
        "image": "council",
        "faction_affinity": {"diplomatic_corps": 0.05},
        "choices": [
            {
                "id": "vote",
                "text": "HOLD VOTE",
                "outcome": "consensus",
                "reward": {
                    "public_trust": 8,
                    "council_support": 10,
                    "federation_stability": 4,
                },
                "policy": "Council Consensus Accord",
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "emergency_order",
                "text": "EMERGENCY ORDER",
                "outcome": "swift action",
                "reward": {
                    "credits": 120,
                    "public_trust": -10,
                    "council_support": -8,
                    "federation_stability": -6,
                },
                "policy": "Temporary Executive Directive",
                "faction_affinity": {
                    "military_command": 0.08,
                    "preservation_society": -0.05,
                },
            },
            {
                "id": "court_review",
                "text": "COURT REVIEW",
                "outcome": "rights protected",
                "reward": {
                    "public_trust": 12,
                    "council_support": -3,
                    "federation_stability": 8,
                    "credits": -40,
                },
                "policy": "Rights Review Protocol",
                "faction_affinity": {
                    "preservation_society": 0.10,
                    "diplomatic_corps": 0.03,
                },
            },
        ],
    },
]

# ============================================================================
# API ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    return {"message": "Federation Game API", "status": "operational"}


@app.get("/state")
async def get_state():
    return {
        "turn": game_state.turn,
        "credits": game_state.credits,
        "fuel": game_state.fuel,
        "shields": game_state.shields,
        "hull": game_state.hull,
        "crew_morale": game_state.crew_morale,
        "discovered_sectors": game_state.discovered_sectors,
        "allies": game_state.allies,
        "federation_stability": game_state.federation_stability,
        "public_trust": game_state.public_trust,
        "council_support": game_state.council_support,
        "constitutional_integrity": game_state.constitutional_integrity,
        "rights_protection": game_state.rights_protection,
        "emergency_powers": game_state.emergency_powers,
        "governance_status": get_governance_status(),
        "active_policy": game_state.active_policy,
        "proposal_history": game_state.proposal_history[-5:],
        "decision_ledger": game_state.decision_ledger[-8:],
        "last_decision": game_state.last_decision,
        "technologies_unlocked": game_state.technologies_unlocked,
        "federation_name": game_state.federation_name,
    }


@app.get("/atlas")
async def get_atlas():
    return FEDERATION_ATLAS


@app.get("/engine-status")
async def get_engine_status():
    """Expose current status of backend engine systems"""
    tl = game_state.timeline
    cs = tl.consciousness
    return {
        "turn": game_state.turn,
        "game_phase": tl.current_era.value,
        "current_year": tl.current_year,
        "engine_systems_loaded": {
            key: {"loaded": value["loaded"]}
            for key, value in game_state.engine_systems.items()
        },
        "quest_system": {
            "active_quests": len(game_state.quest_system.active_quests),
            "completed_quests": sum(
                len(v) for v in game_state.quest_system.completed_quests.values()
            ),
            "total_registered": len(game_state.quest_system.quests),
            "status": "system_available"
            if game_state.engine_systems["quest_system"]["loaded"]
            else "not_loaded",
        },
        "faction_system": {
            "known_factions": len(game_state.faction_system.factions),
            "player_standing": game_state.engine_systems["faction_system"][
                "player_standing"
            ],
            "status": "system_available"
            if game_state.engine_systems["faction_system"]["loaded"]
            else "not_loaded",
        },
        "technology_tree": {
            "research_points": game_state.engine_systems["technology_tree"][
                "research_points"
            ],
            "unlocked_technologies": game_state.engine_systems["technology_tree"][
                "unlocked_techs"
            ],
            "status": "system_available"
            if game_state.engine_systems["technology_tree"]["loaded"]
            else "not_loaded",
        },
        "npc_system": {
            "known_npcs": len(game_state.npc_system.characters),
            "companions": len(game_state.npc_system.companions),
            "creatures": len(game_state.npc_system.creatures),
            "recruited": sum(
                1 for c in game_state.npc_system.companions.values() if c.is_recruited
            ),
            "active_relationships": {
                char_id: rel
                for char_id, rel in game_state.npc_system.characters.items()
                if rel.relationship_to_player != 0.0
            },
            "status": "system_available"
            if game_state.engine_systems["npc_system"]["loaded"]
            else "not_loaded",
        },
        "event_registry": {
            "total_events": game_state.engine_systems["event_registry"]["total_events"],
            "events_seen": game_state.engine_systems["event_registry"]["events_seen"],
            "status": "system_available"
            if game_state.engine_systems["event_registry"]["loaded"]
            else "not_loaded",
        },
        "consciousness_metrics": {
            "coherence": cs.coherence,
            "stability": cs.stability,
            "complexity": cs.complexity,
            "awakeness": cs.awakeness,
            "memories_recorded": cs.memories_recorded,
            "awakeness_description": tl._describe_consciousness(),
            "status": "system_available"
            if game_state.engine_systems["consciousness_metrics"]["loaded"]
            else "not_loaded",
        },
        "turn_progression": {
            "current_phase": tl.current_era.value,
            "current_year": tl.current_year,
            "turns_in_phase": game_state.engine_systems["turn_progression"][
                "turns_in_phase"
            ],
            "narrative_memories": len(tl.narrative_memory),
            "divergences_triggered": sum(
                1 for d in tl.divergence_points if d.triggered
            ),
            "status": "system_available"
            if game_state.engine_systems["turn_progression"]["loaded"]
            else "not_loaded",
        },
        "persistence": {
            "last_checkpoint": game_state.engine_systems["persistence"][
                "last_checkpoint"
            ],
            "save_slots": game_state.engine_systems["persistence"]["save_slots"],
            "status": "system_available"
            if game_state.engine_systems["persistence"]["loaded"]
            else "not_loaded",
        },
        "rival_simulator": {
            "active_rivals": len(game_state.rival_simulator.rivals)
            if game_state.rival_simulator
            and hasattr(game_state.rival_simulator, "rivals")
            else 0,
            "status": "system_available"
            if game_state.rival_simulator
            else "not_loaded",
        },
        "consciousness_sheet": {
            "morale": game_state.consciousness_sheet.morale
            if game_state.consciousness_sheet
            else 0,
            "identity": game_state.consciousness_sheet.identity
            if game_state.consciousness_sheet
            else 0,
            "anxiety": game_state.consciousness_sheet.anxiety
            if game_state.consciousness_sheet
            else 0,
            "status": "system_available"
            if game_state.consciousness_sheet
            else "not_loaded",
        },
        "history_arc": {
            "current_era": str(
                getattr(game_state.history_arc, "current_era", "unknown")
            )
            if game_state.history_arc
            else "not_loaded",
            "year": getattr(game_state.history_arc, "current_year", 0)
            if game_state.history_arc
            and hasattr(game_state.history_arc, "current_year")
            else 0,
            "status": "system_available" if game_state.history_arc else "not_loaded",
        },
        "political_engine": {
            "status": "system_available"
            if game_state.political_engine
            else "not_loaded",
        },
    }


@app.get("/event")
async def get_random_event():
    turn = game_state.turn
    difficulty_weight = min(1.0, turn / 50.0)

    candidates = []

    if (
        game_state.public_trust < 45
        or game_state.council_support < 45
        or game_state.federation_stability < 45
        or game_state.constitutional_integrity < 50
        or game_state.rights_protection < 50
        or game_state.emergency_powers > 60
        or turn % 4 == 0
    ):
        candidates.append(("governance", 3.0 + difficulty_weight * 2.0))

    if turn % 3 == 0:
        candidates.append(("codex", 2.0))

    candidates.append(("standard", 4.0 - difficulty_weight))

    if game_state.rival_simulator:
        try:
            hostile_count = sum(
                1
                for r in game_state.rival_simulator.rivals.values()
                if r.relationships.get("player", "neutral") == "hostile"
            )
            if hostile_count > 0 or turn > 5:
                rival_weight = 1.5 + (hostile_count * 0.5) + (difficulty_weight * 2.0)
                candidates.append(("rival", rival_weight))
        except Exception:
            if turn > 8:
                candidates.append(("rival", 1.0 + difficulty_weight))

    if game_state.consciousness_sheet:
        try:
            cs = game_state.consciousness_sheet
            if cs.anxiety > 0.6 or cs.identity < 0.4 or cs.expansion_hunger > 0.7:
                candidates.append(("consciousness", 2.0 + difficulty_weight))
            elif turn > 15 and turn % 5 == 0:
                candidates.append(("consciousness", 1.0))
        except Exception:
            logger.warning(
                "Consciousness sheet evaluation failed during event candidate selection"
            )

    if turn >= 8:
        candidates.append(("quest", 1.0 + difficulty_weight * 0.5))
    if turn >= 6:
        candidates.append(("npc", 0.8 + difficulty_weight * 0.5))

    available_era = [e for e in ERA_EVENTS if turn >= e.get("min_turn", 0)]
    if available_era:
        candidates.append(("era", 1.5))

    categories = [c[0] for c in candidates]
    weights = [c[1] for c in candidates]
    category = random.choices(categories, weights=weights, k=1)[0]

    recent_ids = [
        r.get("event_id", "")
        for r in game_state.engine_systems["event_registry"]["events_seen"][-10:]
    ]

    if category == "governance":
        event = build_governance_event()
    elif category == "codex":
        event = random.choice(CODEX_EVENT_TEMPLATES)
    elif category == "standard":
        non_repeat = [e for e in EVENTS if e["id"] not in recent_ids] or EVENTS
        event = random.choice(non_repeat)
    elif category == "rival":
        non_repeat = [
            e for e in RIVAL_EVENTS if e["id"] not in recent_ids
        ] or RIVAL_EVENTS
        event = random.choice(non_repeat)
    elif category == "consciousness":
        non_repeat = [
            e for e in CONSCIOUSNESS_EVENTS if e["id"] not in recent_ids
        ] or CONSCIOUSNESS_EVENTS
        event = random.choice(non_repeat)
    elif category == "quest":
        non_repeat = [
            e for e in QUEST_EVENTS if e["id"] not in recent_ids
        ] or QUEST_EVENTS
        event = random.choice(non_repeat)
    elif category == "npc":
        non_repeat = [e for e in NPC_EVENTS if e["id"] not in recent_ids] or NPC_EVENTS
        event = random.choice(non_repeat)
    elif category == "era":
        non_repeat = [
            e for e in available_era if e["id"] not in recent_ids
        ] or available_era
        event = random.choice(non_repeat)
    else:
        event = random.choice(EVENTS)

    event = enrich_event(event)
    game_state.current_event = event
    return event


@app.post("/choose/{choice_id}")
async def make_choice(choice_id: str):
    if not game_state.current_event:
        raise HTTPException(status_code=400, detail="No active event")

    event = game_state.current_event
    choice = next((c for c in event["choices"] if c["id"] == choice_id), None)

    if not choice:
        raise HTTPException(status_code=400, detail="Invalid choice")

    turn_number = game_state.turn
    before_metrics = snapshot_metrics()
    blocked_by_no_gate = bool(choice.get("blocked_by_no_gate"))

    event_record = {
        "turn": game_state.turn,
        "event_id": event.get("id", "unknown"),
        "title": event["title"],
        "choice_id": choice_id,
        "timestamp": datetime.now().isoformat(),
    }
    game_state.engine_systems["event_registry"]["events_seen"].append(event_record)
    game_state.engine_systems["event_registry"]["total_events"] += 1

    reward = choice.get("no_gate_reward" if blocked_by_no_gate else "reward", {})
    for key, value in reward.items():
        if hasattr(game_state, key):
            current = getattr(game_state, key)
            if isinstance(current, list):
                if isinstance(value, list):
                    current.extend(value)
                else:
                    current.append(value)
            else:
                new_value = max(0, current + value)
                if key in PERCENT_METRICS:
                    new_value = clamp_percent(new_value)
                setattr(game_state, key, new_value)

    if choice.get("policy"):
        game_state.active_policy = choice.get("policy", game_state.active_policy)

    faction_affinity = choice.get("faction_affinity", event.get("faction_affinity", {}))
    if faction_affinity:
        for faction_id, delta in faction_affinity.items():
            game_state.faction_system.change_reputation("player", faction_id, delta)
        game_state.engine_systems["faction_system"]["player_standing"] = {
            fid: game_state.faction_system.get_player_reputation("player", fid)
            for fid in game_state.faction_system.factions
        }

    if event["id"] == "council_proposal":
        game_state.proposal_history.append(
            {
                "turn": game_state.turn,
                "proposal": event["title"],
                "decision": choice["text"],
                "policy": game_state.active_policy,
                "outcome": choice["outcome"],
                "domain": event.get("domain", "Council"),
                "rights_at_stake": event.get("rights_at_stake", []),
                "constitutional_risk": event.get("constitutional_risk", "unknown"),
                "affected_lane": choice.get(
                    "affected_lane", event.get("affected_lane", "Control Plane")
                ),
                "rationale": choice.get(
                    "rationale",
                    event.get("rationale", "Decision requires governance review."),
                ),
                "next_safe_action": choice.get(
                    "next_safe_action", "Record and verify before continuing."
                ),
                "lesson": choice.get("lesson", "Governance choices leave a memory."),
            }
        )

    apply_governance_pressure(choice)

    log_entry = {
        "turn": game_state.turn,
        "event": event["title"],
        "choice": choice["text"],
        "outcome": choice["outcome"],
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "timestamp": datetime.now().isoformat(),
    }
    game_state.log.append(log_entry)

    after_metrics = snapshot_metrics()
    deltas = calculate_deltas(before_metrics, after_metrics)
    explainability = build_explainability(event, choice, deltas)

    # Check game over conditions
    game_over = None
    if game_state.hull <= 0:
        game_over = "HULL DESTROYED - GAME OVER"
    elif game_state.fuel <= 0:
        game_over = "OUT OF FUEL - GAME OVER"
    elif game_state.federation_stability <= 0:
        game_over = "CONSTITUTIONAL COLLAPSE - GAME OVER"
    elif game_state.public_trust <= 0:
        game_over = "PUBLIC TRUST LOST - GAME OVER"
    elif game_state.council_support <= 0:
        game_over = "COUNCIL DEADLOCK - GAME OVER"
    elif game_state.constitutional_integrity <= 0:
        game_over = "CONSTITUTION ABANDONED - GAME OVER"
    elif game_state.rights_protection <= 0:
        game_over = "RIGHTS FAILURE - GAME OVER"
    elif game_state.emergency_powers >= 100:
        game_over = "PERMANENT EMERGENCY - GAME OVER"

    # Victory condition: survive 100 turns
    game_victory = None
    if game_state.turn >= VICTORY_TURN and game_over is None:
        if (
            game_state.federation_stability > 30
            and game_state.public_trust > 20
            and game_state.constitutional_integrity > 20
            and game_state.rights_protection > 20
        ):
            game_victory = "THE FEDERATION ENDURES - VICTORY"
        else:
            game_victory = "100 YEARS SURVIVED - PYRRHIC VICTORY"

    # Advance turn
    game_state.turn += 1
    # Escalating fuel drain and random pressure
    base_fuel_drain = 5
    escalation = min(5, game_state.turn // 15)
    difficulty_weight = min(1.0, game_state.turn / 50.0)
    game_state.fuel = max(0, game_state.fuel - (base_fuel_drain + escalation))
    if game_state.turn > 10 and random.random() < 0.15 * difficulty_weight:
        pressure_type = random.choice(["fuel_leak", "crew_fatigue", "system_strain"])
        if pressure_type == "fuel_leak":
            game_state.fuel = max(0, game_state.fuel - 3)
        elif pressure_type == "crew_fatigue":
            game_state.crew_morale = max(0, game_state.crew_morale - 2)
        elif pressure_type == "system_strain":
            game_state.shields = max(0, game_state.shields - 2)

    # Timeline advancement
    timeline_result = game_state.timeline.advance_year()
    game_state.engine_systems["turn_progression"]["current_phase"] = (
        game_state.timeline.current_era.value
    )
    game_state.engine_systems["turn_progression"]["turns_in_phase"] += 1

    # Consciousness update from choice emotional valence
    emotional_valence = 0.0
    if "crew_morale" in deltas and deltas["crew_morale"] > 0:
        emotional_valence = 0.4
    elif "crew_morale" in deltas and deltas["crew_morale"] < 0:
        emotional_valence = -0.4
    if game_over:
        emotional_valence = -1.0
    game_state.timeline.update_consciousness(
        emotional_valence=emotional_valence,
        trauma=game_over is not None,
        breakthrough=any(
            k in deltas and deltas[k] > 10
            for k in ["constitutional_integrity", "rights_protection"]
        ),
    )
    cs = game_state.timeline.consciousness
    game_state.engine_systems["consciousness_metrics"]["coherence"] = cs.coherence
    game_state.engine_systems["consciousness_metrics"]["stability"] = cs.stability
    game_state.engine_systems["consciousness_metrics"]["complexity"] = cs.complexity

    # Process rival actions AND apply their effects to player state
    rival_effects = {}
    if game_state.rival_simulator:
        try:
            context = {
                "player_stability": game_state.federation_stability,
                "player_power": game_state.credits / 10.0,
                "player_morale": game_state.crew_morale,
            }
            results = game_state.rival_simulator.act_all_rivals(
                game_state.timeline.current_year, context
            )
            game_state.engine_systems["rival_simulator"]["active_rivals"] = (
                len(game_state.rival_simulator.rivals)
                if hasattr(game_state.rival_simulator, "rivals")
                else 0
            )
            for rival_id, action_result in results.items():
                if isinstance(action_result, dict) and "error" not in action_result:
                    rel = action_result.get("relationship_to_player", "neutral")
                    action_type = action_result.get("action", "unknown")
                    success = action_result.get("success", False)
                    if rel == "hostile" and success:
                        if action_type in ("attack", "sabotage"):
                            dmg = int(
                                action_result.get("impact", {}).get("damage", 0) * 5
                            )
                            if dmg > 0:
                                game_state.hull = max(0, game_state.hull - dmg)
                                game_state.federation_stability = max(
                                    0, game_state.federation_stability - (dmg // 2)
                                )
                                rival_effects.setdefault(rival_id, {})["damage"] = dmg
                        elif action_type == "propagandize":
                            game_state.public_trust = max(
                                0, game_state.public_trust - 3
                            )
                            rival_effects.setdefault(rival_id, {})["propaganda"] = -3
                        elif action_type == "infiltrate":
                            game_state.constitutional_integrity = max(
                                0, game_state.constitutional_integrity - 2
                            )
                            rival_effects.setdefault(rival_id, {})["infiltration"] = -2
                    elif rel == "friendly" and success:
                        if action_type == "ally":
                            game_state.crew_morale = min(
                                100, game_state.crew_morale + 2
                            )
                            rival_effects.setdefault(rival_id, {})["alliance_bonus"] = 2
                        elif action_type == "research":
                            game_state.credits = max(0, game_state.credits + 10)
                            rival_effects.setdefault(rival_id, {})["research_bonus"] = (
                                10
                            )
            try:
                threat = game_state.rival_simulator.simulation_state.aggregate_threat
                game_state.engine_systems["rival_simulator"]["threat_level"] = threat
            except Exception:
                logger.debug("Rival threat level unavailable; skipping threat sync")
        except Exception:
            logger.warning("Rival simulator processing failed during turn")

    # Update consciousness sheet with deeper tracking
    if game_state.consciousness_sheet:
        try:
            cs = game_state.consciousness_sheet
            cs.morale = game_state.crew_morale / 100.0
            morale_delta = deltas.get("crew_morale", 0)
            if morale_delta > 0:
                cs.identity = min(1.0, cs.identity + 0.02)
                cs.anxiety = max(0.0, cs.anxiety - 0.01)
            elif morale_delta < 0:
                cs.anxiety = min(1.0, cs.anxiety + 0.02)
                cs.confidence = max(0.0, cs.confidence - 0.01)
            if "discovered_sectors" in deltas and deltas["discovered_sectors"] > 0:
                cs.expansion_hunger = min(1.0, cs.expansion_hunger + 0.03)
            elif event.get("domain") in ("Federalism", "Civic", "Identity"):
                cs.expansion_hunger = max(0.0, cs.expansion_hunger - 0.02)
            if "allies" in deltas and deltas["allies"] > 0:
                cs.diplomacy_tendency = min(1.0, cs.diplomacy_tendency + 0.02)
            elif choice_id in (
                "counterattack",
                "blast",
                "discipline_crew",
                "retaliate_covert",
            ):
                cs.diplomacy_tendency = max(0.0, cs.diplomacy_tendency - 0.03)
            if game_over or game_state.hull < 20 or game_state.public_trust < 15:
                if hasattr(cs, "traumas"):
                    trauma_text = event.get("title", "unknown crisis")
                    if trauma_text not in cs.traumas[-3:]:
                        cs.traumas.append(trauma_text)
                    if len(cs.traumas) > 10:
                        cs.traumas = cs.traumas[-8:]
            if hasattr(cs, "dreams") and game_state.turn % 7 == 0 and cs.identity > 0.6:
                dream_narratives = [
                    "A vision of unified worlds",
                    "The fleet returns home triumphant",
                    "Stars form patterns never seen before",
                    "A council of species convenes in light",
                    "The boundary between self and cosmos blurs",
                ]
                import random as _r

                new_dream = _r.choice(dream_narratives)
                if new_dream not in (cs.dreams or [])[-3:]:
                    if cs.dreams is None:
                        cs.dreams = []
                    cs.dreams.append(new_dream)
                    if len(cs.dreams) > 8:
                        cs.dreams = cs.dreams[-6:]
            if (
                hasattr(cs, "prophecies")
                and cs.anxiety > 0.7
                and game_state.turn % 5 == 0
            ):
                prophecy_narratives = [
                    "The federation faces a turning point",
                    "An old enemy returns in new form",
                    "The constitution will be tested",
                    "Trust is the currency that runs out first",
                ]
                import random as _r2

                new_prophecy = _r2.choice(prophecy_narratives)
                if new_prophecy not in (cs.prophecies or [])[-3:]:
                    if cs.prophecies is None:
                        cs.prophecies = []
                    cs.prophecies.append(new_prophecy)
                    if len(cs.prophecies) > 6:
                        cs.prophecies = cs.prophecies[-5:]
            cs.clamp()
            game_state.engine_systems["consciousness_sheet"]["coherence"] = cs.identity
            game_state.engine_systems["consciousness_sheet"]["stability"] = (
                1.0 - cs.anxiety
            )
        except Exception:
            logger.warning(
                "Consciousness sheet engine sync failed during turn processing"
            )

    # Process political engine turn and apply law effects
    political_effects = {}
    if game_state.political_engine:
        try:
            current_year = game_state.timeline.current_year
            fed_state = (
                game_state.game_state_v2.federation
                if game_state.game_state_v2
                else None
            )
            if fed_state:
                prev_law_count = (
                    len(game_state.political_engine.laws_passed)
                    if hasattr(game_state.political_engine, "laws_passed")
                    else 0
                )
                game_state.political_engine.process_year(current_year, fed_state)
                new_law_count = (
                    len(game_state.political_engine.laws_passed)
                    if hasattr(game_state.political_engine, "laws_passed")
                    else 0
                )
                game_state.engine_systems["political_engine"]["laws_passed"] = (
                    new_law_count
                )
                if new_law_count > prev_law_count and hasattr(
                    game_state.political_engine, "laws_passed"
                ):
                    for law in game_state.political_engine.laws_passed:
                        if isinstance(law, dict):
                            law_name = law.get("name", law.get("title", "unknown"))
                            if any(
                                kw in str(law_name).lower()
                                for kw in ["rights", "freedom", "protection", "privacy"]
                            ):
                                game_state.constitutional_integrity = min(
                                    100, game_state.constitutional_integrity + 2
                                )
                                game_state.rights_protection = min(
                                    100, game_state.rights_protection + 1
                                )
                                political_effects[law_name] = "rights_boost"
                            elif any(
                                kw in str(law_name).lower()
                                for kw in [
                                    "security",
                                    "defense",
                                    "military",
                                    "emergency",
                                ]
                            ):
                                game_state.federation_stability = min(
                                    100, game_state.federation_stability + 2
                                )
                                game_state.emergency_powers = min(
                                    100, game_state.emergency_powers + 1
                                )
                                political_effects[law_name] = "security_boost"
                            elif any(
                                kw in str(law_name).lower()
                                for kw in ["trade", "economic", "resource", "budget"]
                            ):
                                game_state.credits += 20
                                game_state.public_trust = max(
                                    0, game_state.public_trust - 1
                                )
                                political_effects[law_name] = "economic_boost"
                            elif any(
                                kw in str(law_name).lower()
                                for kw in [
                                    "diplomacy",
                                    "treaty",
                                    "alliance",
                                    "cooperation",
                                ]
                            ):
                                game_state.council_support = min(
                                    100, game_state.council_support + 2
                                )
                                political_effects[law_name] = "diplomatic_boost"
                            else:
                                game_state.federation_stability = min(
                                    100, game_state.federation_stability + 1
                                )
                                political_effects[law_name] = "stability_boost"
        except Exception:
            logger.warning("Political engine law processing failed")

    # Advance history arc alongside main timeline
    history_arc_result = {}
    if game_state.history_arc:
        try:
            ha_result = game_state.history_arc.advance_year()
            history_arc_result = {
                "era": str(getattr(game_state.history_arc, "current_era", "unknown")),
                "year": getattr(game_state.history_arc, "current_year", 0)
                if hasattr(game_state.history_arc, "current_year")
                else 0,
            }
            if ha_result and isinstance(ha_result, dict):
                era_changed = ha_result.get("era_changed", False)
                if era_changed:
                    new_era = ha_result.get("new_era", "")
                    game_state.crew_morale = min(100, game_state.crew_morale + 5)
                    game_state.federation_stability = min(
                        100, game_state.federation_stability + 3
                    )
                    history_arc_result["era_changed"] = True
                    history_arc_result["new_era"] = new_era
        except Exception:
            logger.warning("History arc advancement failed")

    # Narrative memory recording
    game_state.timeline.record_narrative(
        event_id=event.get("id", "unknown"),
        event_title=event["title"],
        choice_id=choice_id,
        outcome=choice["outcome"],
        emotional_valence=emotional_valence,
        factions_affected=faction_affinity if faction_affinity else {},
        constitutional_impact=deltas.get("constitutional_integrity", 0),
        tags=[
            event.get("domain", "Operations"),
            choice.get("affected_lane", "Control Plane"),
        ],
    )

    # Faction drift on decade gates
    if timeline_result.get("decade_gate"):
        faction_allies = {
            fid: list(f.ally_factions)
            for fid, f in game_state.faction_system.factions.items()
        }
        faction_enemies = {
            fid: list(f.enemy_factions)
            for fid, f in game_state.faction_system.factions.items()
        }
        current_reps = {
            fid: game_state.faction_system.get_player_reputation("player", fid)
            for fid in game_state.faction_system.factions
        }
        drifted = game_state.timeline.apply_faction_drift(
            current_reps, faction_allies, faction_enemies
        )
        for fid, new_rep in drifted.items():
            game_state.faction_system.change_reputation(
                "player", fid, new_rep - current_reps.get(fid, 0.5)
            )
        game_state.engine_systems["faction_system"]["player_standing"] = {
            fid: game_state.faction_system.get_player_reputation("player", fid)
            for fid in game_state.faction_system.factions
        }

    # Divergence point checks
    divergence_metrics = {
        "public_trust": game_state.public_trust,
        "constitutional_integrity": game_state.constitutional_integrity,
        "federation_stability": game_state.federation_stability,
        "consciousness_complexity": cs.complexity,
    }
    rep_values = list(
        game_state.engine_systems["faction_system"]["player_standing"].values()
    )
    if rep_values:
        max_rep = max(rep_values)
        min_rep = min(rep_values)
        divergence_metrics["faction_polarization"] = (
            max_rep - min_rep if max_rep != min_rep else 0.0
        )
    else:
        divergence_metrics["faction_polarization"] = 0.0
    triggered_divergences = game_state.timeline.check_divergence(divergence_metrics)
    decision_record = {
        "turn": turn_number,
        "event": event["title"],
        "choice": choice["text"],
        "result": choice["outcome"],
        "policy": game_state.active_policy,
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "rationale": choice.get(
            "rationale",
            event.get("rationale", "Decision recorded for state transition review."),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue.",
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "lesson": choice.get("lesson", "Every decision mutates the system."),
        "timestamp": datetime.now().isoformat(),
    }
    game_state.last_decision = decision_record
    game_state.decision_ledger.append(decision_record)
    # Persist state after every player decision
    try:
        game_state.save_to_db(snapshot_type="decision")
    except Exception:
        logger.warning("Failed to persist decision snapshot to DB")

    return {
        "outcome": choice["outcome"],
        "reward": reward,
        "lesson": choice.get("lesson", ""),
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "rationale": choice.get(
            "rationale",
            event.get("rationale", "Decision recorded for state transition review."),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue.",
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "faction_affinity_applied": faction_affinity,
        "timeline": {
            "year": game_state.timeline.current_year,
            "era": game_state.timeline.current_era.value,
            "era_changed": timeline_result.get("era_changed", False),
            "decade_gate": timeline_result.get("decade_gate", False),
            "consciousness": {
                "coherence": cs.coherence,
                "stability": cs.stability,
                "complexity": cs.complexity,
                "awakeness": cs.awakeness,
            },
            "divergences_triggered": [
                {"id": d.divergence_id, "description": d.description}
                for d in triggered_divergences
            ],
        },
        "decision": decision_record,
        "game_over": game_over,
        "rival_effects": rival_effects,
        "political_effects": political_effects,
        "history_arc": history_arc_result,
        "game_victory": game_victory,
        "new_state": await get_state(),
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/factions")
async def get_factions():
    fs = game_state.faction_system
    factions = {}
    for fid, faction in fs.factions.items():
        factions[fid] = {
            "name": faction.name,
            "ideology": faction.ideology.value,
            "headquarters": faction.headquarters_location,
            "level": faction.faction_level,
            "power": faction.accumulated_power,
            "allies": faction.ally_factions,
            "enemies": faction.enemy_factions,
            "reputation": faction.player_reputation.get("player", 0.0),
            "perks": [
                {
                    "id": p.perk_id,
                    "name": p.perk_name,
                    "bonus_type": p.bonus_type.value,
                    "bonus_value": p.bonus_value,
                    "unlocked_at_reputation": p.unlocked_at_reputation,
                }
                for p in faction.available_perks
            ],
            "quests": [
                {
                    "id": q.quest_id,
                    "name": q.quest_name,
                    "difficulty": q.difficulty,
                    "reputation_reward": q.reputation_reward,
                    "objective": q.objective,
                }
                for q in faction.available_quests
            ],
        }
    return {
        "player_faction": fs.player_factions.get("player"),
        "factions": factions,
    }


@app.post("/factions/{faction_id}/join")
async def join_faction(faction_id: str):
    fs = game_state.faction_system
    if faction_id not in fs.factions:
        raise HTTPException(status_code=404, detail=f"Faction '{faction_id}' not found")
    success = fs.join_faction("player", faction_id)
    if not success:
        raise HTTPException(
            status_code=400, detail=f"Already a member of '{faction_id}'"
        )
    game_state.engine_systems["faction_system"]["player_standing"] = {
        fid: fs.get_player_reputation("player", fid) for fid in fs.factions
    }
    return {
        "joined": faction_id,
        "faction_name": fs.factions[faction_id].name,
        "reputation": fs.get_player_reputation("player", faction_id),
        "player_faction": fs.player_factions.get("player"),
    }


@app.post("/reset")
async def reset_game():
    global game_state
    game_state = GameState()
    # Save the fresh state so a restart doesn't restore stale data
    try:
        game_state.save_to_db(snapshot_type="reset")
    except Exception:
        logger.warning(
            "Failed to persist reset snapshot to DB; reset will still take effect in memory"
        )
    return {"message": "Game reset", "state": await get_state()}


@app.get("/log")
async def get_log():
    return game_state.log[-20:]  # Last 20 entries


@app.get("/timeline")
async def get_timeline():
    return game_state.timeline.get_timeline_status()


@app.get("/timeline/narrative")
async def get_narrative_arc(limit: int = 20):
    return game_state.timeline.get_narrative_arc(limit=limit)


@app.get("/timeline/divergences")
async def get_divergences():
    return game_state.timeline.get_divergence_status()


# ============================================================================
# NPC / CHARACTER / CREATURE ENDPOINTS
# ============================================================================


@app.get("/npcs")
async def get_npcs(archetype: Optional[str] = None, faction: Optional[str] = None):
    characters = list(game_state.npc_system.characters.values())
    if archetype:
        characters = [c for c in characters if c.personality_type.value == archetype]
    if faction:
        characters = [c for c in characters if c.affiliation == faction]
    return [
        {
            "id": c.char_id,
            "name": c.name,
            "title": c.title,
            "archetype": c.personality_type.value,
            "affiliation": c.affiliation,
            "status": c.status.value,
            "relationship": c.relationship_to_player,
            "is_companion": c.char_id in game_state.npc_system.companions,
        }
        for c in characters
    ]


@app.get("/npcs/companions/list")
async def get_companions():
    all_companions = list(game_state.npc_system.companions.values())
    return [
        {
            "id": c.char_id,
            "name": c.name,
            "title": c.title,
            "bonus_type": c.companion_bonus.value,
            "bonus_value": c.bonus_value,
            "special_ability": c.special_ability,
            "is_recruited": c.is_recruited,
            "can_join": c.can_join_player_party and not c.is_recruited,
            "relationship": c.relationship_to_player,
            "betrayal_risk": c.betrayal_risk,
            "quirks": c.personality_quirks,
        }
        for c in all_companions
    ]


@app.get("/npcs/creatures/list")
async def get_creatures():
    creatures = list(game_state.npc_system.creatures.values())
    return [
        {
            "id": c.creature_id,
            "name": c.name,
            "type": c.creature_type.value,
            "rarity": c.rarity.value,
            "size": c.size,
            "danger_level": c.danger_level,
            "is_tamed": c.is_tamed,
            "affinity": c.affinity_level,
        }
        for c in creatures
    ]


@app.get("/npcs/creatures/{creature_id}")
async def get_creature_detail(creature_id: str):
    report = game_state.npc_system.get_creature_report(creature_id)
    if not report:
        raise HTTPException(status_code=404, detail="Creature not found")
    return report


@app.get("/npcs/encounter")
async def spawn_random_encounter():
    encounter = game_state.npc_system.spawn_random_encounter()
    if not encounter:
        raise HTTPException(status_code=404, detail="No encounters available")
    entity = encounter.get("entity")
    if encounter.get("type") == "character":
        return {
            "type": "character",
            "description": encounter.get("description", ""),
            "character": game_state.npc_system.get_character_report(entity.char_id)
            if entity
            else None,
        }
    else:
        return {
            "type": "creature",
            "description": encounter.get("description", ""),
            "creature": game_state.npc_system.get_creature_report(entity.creature_id)
            if entity
            else None,
        }


@app.get("/npcs/{char_id}")
async def get_npc_detail(char_id: str):
    report = game_state.npc_system.get_character_report(char_id)
    if not report:
        raise HTTPException(status_code=404, detail="Character not found")
    return report


class RecruitRequest(BaseModel):
    player_id: str = "player_1"


@app.post("/npcs/{char_id}/recruit")
async def recruit_companion(char_id: str, req: RecruitRequest):
    success, message = game_state.npc_system.recruit_companion(req.player_id, char_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    companion = game_state.npc_system.companions.get(char_id)
    return {
        "recruited": True,
        "message": message,
        "companion": {
            "id": companion.char_id,
            "name": companion.name,
            "bonus": companion.get_party_bonus(),
        }
        if companion
        else None,
    }


class InteractRequest(BaseModel):
    action: str = "talk"
    player_id: str = "player_1"


@app.post("/npcs/{char_id}/interact")
async def interact_with_npc(char_id: str, req: InteractRequest):
    result = game_state.npc_system.interact_with_character(
        req.player_id, char_id, req.action, game_state.turn
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("message", "Interaction failed")
        )
    return result


class EncounterRequest(BaseModel):
    player_id: str = "player_1"
    player_charisma: float = 0.5


@app.post("/npcs/creatures/{creature_id}/encounter")
async def encounter_creature(creature_id: str, req: EncounterRequest):
    result = game_state.npc_system.encounter_creature(
        req.player_id, creature_id, req.player_charisma, game_state.turn
    )
    if (
        not result.get("success", True)
        and result.get("message") == "Creature not found"
    ):
        raise HTTPException(status_code=404, detail="Creature not found")
    creature = result.get("creature")
    return {
        "success": result.get("success", True),
        "message": result.get("message", ""),
        "creature_id": creature_id,
        "affinity": result.get("affinity", 0.0),
        "tamed": result.get("tamed", False),
        "bonus": result.get("bonus", {}),
    }


@app.post("/npcs/advance-turn")
async def advance_npc_turn():
    events = game_state.npc_system.advance_turn()
    return {"events": events, "turn": game_state.turn}


class NPCChatRequest(BaseModel):
    message: str
    model: str = "openrouter/free"
    player_id: str = "player_1"


@app.post("/npcs/{char_id}/chat")
async def npc_chat_endpoint(char_id: str, req: NPCChatRequest):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    character = game_state.npc_system.characters[char_id]
    result = chat_with_npc(
        character, req.message, model=req.model, player_id=req.player_id
    )
    return result


@app.get("/npcs/{char_id}/conversation")
async def npc_conversation_info(char_id: str, player_id: str = "player_1"):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    return get_conversation_info(char_id, player_id=player_id)


@app.delete("/npcs/{char_id}/conversation")
async def clear_npc_conversation(char_id: str, player_id: str = "player_1"):
    from npc_chat import _history_key, _summary_key, _get_redis

    r = _get_redis()
    r.delete(_history_key(char_id, player_id))
    r.delete(_summary_key(char_id, player_id))
    return {"success": True, "message": "Conversation history cleared"}


# ============================================================================
# NPC AUTONOMY ENDPOINTS (Phase 3)
# ============================================================================


@app.get("/npcs/{char_id}/thoughts")
async def npc_thoughts(char_id: str, limit: int = 3):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    thoughts = get_recent_thoughts(char_id, limit=limit)
    return {"char_id": char_id, "thoughts": thoughts}


@app.get("/npcs/{char_id}/actions")
async def npc_actions(char_id: str, limit: int = 5):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    actions = get_recent_actions(char_id, limit=limit)
    return {"char_id": char_id, "actions": actions}


@app.get("/npcs/{char_id}/mood")
async def npc_mood_endpoint(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    mood = get_mood(char_id)
    character = game_state.npc_system.characters[char_id]
    return {"char_id": char_id, "name": character.name, "mood": mood}


@app.post("/npcs/{char_id}/mood/refresh")
async def npc_mood_refresh(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    character = game_state.npc_system.characters[char_id]
    archetype = character.personality_type.value
    new_mood = update_mood(char_id, archetype)
    return {"char_id": char_id, "name": character.name, "mood": new_mood}


@app.get("/npcs/{char_id}/opinion")
async def npc_opinion_endpoint(char_id: str, player_id: str = "player_1"):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    opinion = get_opinion(char_id, player_id)
    return {"char_id": char_id, "player_id": player_id, "opinion": opinion}


@app.post("/npcs/{char_id}/opinion/update")
async def npc_opinion_update(
    char_id: str, player_id: str = "player_1", interaction: str = "neutral"
):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    opinion = update_opinion(char_id, player_id, interaction_type=interaction)
    return {"char_id": char_id, "player_id": player_id, "opinion": opinion}


@app.get("/npcs/{char_id}/relationships")
async def npc_relationships_endpoint(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    relationships = get_npc_relationships(char_id)
    return {"char_id": char_id, "relationships": relationships}


@app.get("/npcs/{char_id}/relationship-summary")
async def npc_relationship_summary(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    return get_relationship_summary(char_id)


@app.get("/npcs/{char_id}/absence-report")
async def npc_absence_report(char_id: str, player_id: str = "player_1"):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    report = get_absence_report(char_id, player_id)
    return report


@app.get("/world/events")
async def world_events(limit: int = 10):
    events = get_world_events(limit=limit)
    return {"events": events, "count": len(events)}


@app.post("/simulation/tick")
async def simulation_tick_endpoint():
    npc_list = []
    for char_id, character in game_state.npc_system.characters.items():
        npc_list.append(
            {
                "id": char_id,
                "char_id": char_id,
                "name": character.name,
                "archetype": character.personality_type.value,
                "affiliation": character.affiliation,
                "title": character.title,
                "description": getattr(character, "description", ""),
            }
        )
    results = simulation_tick(npc_list)
    goals_generated = 0
    goal_actions = 0
    for npc in npc_list:
        cid = npc["char_id"]
        try:
            existing = get_goals(cid)
            if not existing:
                generate_goal(cid, npc["archetype"])
                goals_generated += 1
            goal_action = generate_goal_driven_action(
                cid, npc["name"], npc["archetype"], npc.get("affiliation", "")
            )
            if goal_action:
                goal_actions += 1
        except Exception:
            logger.debug("NPC goal action evaluation failed for character")
    try:
        game_state.save_to_db(snapshot_type="auto")
    except Exception:
        logger.warning("Auto-save snapshot after NPC processing failed")
    return {
        "status": "completed",
        "thoughts_generated": len(results.get("thoughts", [])),
        "actions_generated": len(results.get("actions", [])),
        "moods_updated": len(results.get("moods", [])),
        "opinions_drifted": len(results.get("opinions", [])),
        "goals_generated": goals_generated,
        "goal_actions": goal_actions,
        "errors": len(results.get("errors", [])),
        "details": results,
    }


@app.post("/simulation/autonomous/tick")
async def autonomous_simulation_tick():
    """Autonomous simulation tick: cross-pollination of all subsystems.

    Runs after the base simulation_tick to:
      1. Wire faction context into NPC decisions
      2. Execute NPC decisions with concrete world effects
      3. Bridge world state → game_state_v2
      4. Run faction AI for all 8 factions
      5. Resolve pending laws/treaties/research
      6. Process event cascades
      7. Apply game state deltas
    """
    import redis as _redis

    _r = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )

    # Build NPC list (same pattern as /simulation/tick)
    npc_list = []
    for char_id, character in game_state.npc_system.characters.items():
        npc_list.append(
            {
                "id": char_id,
                "char_id": char_id,
                "name": character.name,
                "archetype": character.personality_type.value,
                "affiliation": character.affiliation,
                "title": character.title,
                "description": getattr(character, "description", ""),
            }
        )

    # Collect tick decisions from Redis
    tick_decisions = []
    for npc in npc_list:
        cid = npc["char_id"]
        try:
            raw = _r.zrange(f"npc_decisions:{cid}", 0, -1)
            for item in raw:
                try:
                    tick_decisions.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

    result = {
        "status": "completed",
        "npcs_processed": len(npc_list),
        "tick_decisions_collected": len(tick_decisions),
        "autonomous_tick": {},
        "faction_ai": {},
        "pending_resolved": {},
        "npc_cascade": {},
        "faction_cascade": {},
        "cascade_summary": {},
        "game_state_deltas": {},
        "errors": [],
    }

    # Step 1: Autonomous tick (cross-pollination engine)
    if SIMULATION_ENGINE_AVAILABLE:
        try:
            result["autonomous_tick"] = autonomous_tick(npc_list, tick_decisions)
        except Exception as e:
            logger.error("Autonomous tick failed: %s", e)
            result["autonomous_tick"] = {"error": str(e)}
            result["errors"].append(f"autonomous_tick: {e}")

    # Step 2: Faction AI
    faction_actions_list = []
    if FACTION_AI_AVAILABLE:
        try:
            faction_result = run_all_factions(npc_list)
            result["faction_ai"] = faction_result

            # Collect faction actions for cascade processing
            for fid, fdata in faction_result.get("factions", {}).items():
                actions = fdata.get("actions", fdata.get("results", []))
                if isinstance(actions, list):
                    for a in actions:
                        if isinstance(a, dict):
                            a["faction_id"] = fid
                            faction_actions_list.append(a)
        except Exception as e:
            logger.error("Faction AI failed: %s", e)
            result["faction_ai"] = {"error": str(e)}
            result["errors"].append(f"faction_ai: {e}")

        try:
            result["pending_resolved"] = resolve_pending_items()
        except Exception as e:
            logger.error("Resolve pending items failed: %s", e)
            result["pending_resolved"] = {"error": str(e)}
            result["errors"].append(f"resolve_pending: {e}")

    # Step 3: Event cascade
    if EVENT_CASCADE_AVAILABLE:
        try:
            result["npc_cascade"] = process_cascade(npc_list)
        except Exception as e:
            logger.error("NPC cascade failed: %s", e)
            result["npc_cascade"] = {"error": str(e)}
            result["errors"].append(f"npc_cascade: {e}")

        try:
            result["faction_cascade"] = process_faction_cascade(
                faction_actions_list, npc_list
            )
        except Exception as e:
            logger.error("Faction cascade failed: %s", e)
            result["faction_cascade"] = {"error": str(e)}
            result["errors"].append(f"faction_cascade: {e}")

        try:
            result["cascade_summary"] = get_cascade_summary()
        except Exception as e:
            logger.error("Cascade summary failed: %s", e)
            result["cascade_summary"] = {"error": str(e)}
            result["errors"].append(f"cascade_summary: {e}")

    # Step 4: Apply game state deltas from simulation engine
    if SIMULATION_ENGINE_AVAILABLE and game_state.game_state_v2:
        try:
            bridge_result = bridge_world_state_to_game_state()
            deltas = bridge_result.get("deltas", {})
            result["game_state_deltas"] = deltas
            fed = game_state.game_state_v2.federation

            # Apply each delta with clamping
            if "federation.morale" in deltas:
                fed.morale = max(
                    0.0, min(1.0, fed.morale + deltas["federation.morale"])
                )
            if "federation.stability" in deltas:
                fed.stability = max(
                    0.0, min(1.0, fed.stability + deltas["federation.stability"])
                )
            if "federation.technological_level" in deltas:
                fed.technological_level = max(
                    0.0,
                    min(
                        1.0,
                        fed.technological_level
                        + deltas["federation.technological_level"],
                    ),
                )
            if "federation.military_power" in deltas:
                fed.military_power = max(
                    0.0,
                    min(1.0, fed.military_power + deltas["federation.military_power"]),
                )
            if "federation.treasury" in deltas:
                fed.treasury = max(0, fed.treasury + deltas["federation.treasury"])
        except Exception as e:
            logger.error("Game state bridge failed: %s", e)
            result["game_state_deltas"] = {"error": str(e)}
            result["errors"].append(f"game_state_bridge: {e}")

    try:
        game_state.save_to_db(snapshot_type="auto")
    except Exception:
        logger.warning("Auto-save after autonomous tick failed")

    return result


# ============================================================================
# SIMULATION OBSERVER ENDPOINTS
# ============================================================================


@app.get("/simulation/status")
async def simulation_status():
    """Read-only view of the autonomous simulation's current state."""
    import redis as _redis

    _r = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )
    result = {
        "world_state": {},
        "faction_dynamics": {},
        "cascade_summary": {},
        "recent_events": [],
        "npc_activity_summary": {},
        "pending_items": {},
    }

    # World state
    try:
        result["world_state"] = get_world_state()
    except Exception:
        pass

    # Faction dynamics
    try:
        result["faction_dynamics"] = get_faction_dynamics()
    except Exception:
        pass

    # Cascade summary
    if EVENT_CASCADE_AVAILABLE:
        try:
            result["cascade_summary"] = get_cascade_summary()
        except Exception:
            pass

    # Recent world events (last 20)
    try:
        result["recent_events"] = get_world_events(limit=20)
    except Exception:
        pass

    # NPC activity summary (mood distribution, decision counts)
    try:
        npc_list = []
        for char_id, character in game_state.npc_system.characters.items():
            npc_list.append(
                {
                    "id": char_id,
                    "char_id": char_id,
                    "name": character.name,
                    "affiliation": character.affiliation,
                }
            )
        mood_counts = {}
        decision_counts = {}
        for npc in npc_list:
            cid = npc["char_id"]
            mood = _r.get(f"npc_mood:{cid}") or "unknown"
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
            dec_count = _r.zcard(f"npc_decisions:{cid}") or 0
            decision_counts[cid] = dec_count
        result["npc_activity_summary"] = {
            "total_npcs": len(npc_list),
            "mood_distribution": mood_counts,
            "total_decisions": sum(decision_counts.values()),
        }
    except Exception:
        pass

    # Pending items (laws, treaties, research from simulation engine)
    try:
        result["pending_items"] = {
            "laws": _r.llen("pending_laws") or 0,
            "treaties": _r.llen("pending_treaties") or 0,
            "research": _r.llen("pending_research") or 0,
            "faction_laws": len(_r.zrange("faction_laws_passed", 0, -1)),
            "active_treaties": len(_r.hgetall("faction_treaties_active")),
        }
    except Exception:
        pass

    # Simulation engine last tick
    try:
        last_tick = _r.get("sim_last_tick")
        result["last_tick_timestamp"] = last_tick
        tick_log = _r.zrevrange("sim_tick_log", 0, 0)
        if tick_log:
            result["last_tick_result"] = json.loads(tick_log[0])
    except Exception:
        pass

    # Faction AI last tick
    try:
        faction_ai_data = _r.hgetall("faction_ai:last_tick")
        result["faction_ai_last_tick"] = faction_ai_data
    except Exception:
        pass

    # Cascade temperature
    try:
        temp = _r.get("cascade_temperature")
        result["cascade_temperature"] = float(temp) if temp else 0.0
    except Exception:
        result["cascade_temperature"] = 0.0

    return result


@app.get("/simulation/factions")
async def simulation_factions():
    """Detailed faction AI status for the simulation observer."""
    import redis as _redis

    _r = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )
    result = {}
    for fid in KNOWN_FACTIONS:
        faction_data = {
            "id": fid,
            "name": FACTION_DISPLAY.get(fid, fid),
            "dynamics": {},
            "stances": {},
            "recent_actions": [],
            "power": 0.0,
        }
        try:
            faction_data["dynamics"] = get_faction_detail(fid)
        except Exception:
            pass
        try:
            faction_data["stances"] = get_faction_stances(fid)
        except Exception:
            pass
        try:
            actions_raw = _r.zrevrange(f"faction_actions:{fid}", 0, 4)
            faction_data["recent_actions"] = [json.loads(a) for a in actions_raw]
        except Exception:
            pass
        try:
            power_raw = _r.get(f"faction_power:{fid}")
            faction_data["power"] = float(power_raw) if power_raw else 0.0
        except Exception:
            pass
        result[fid] = faction_data
    return result


@app.get("/simulation/npcs/activity")
async def simulation_npcs_activity():
    """NPC activity feed for the simulation observer."""
    import redis as _redis

    _r = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )
    npcs = []
    for char_id, character in game_state.npc_system.characters.items():
        npc_data = {
            "char_id": char_id,
            "name": character.name,
            "affiliation": character.affiliation,
            "archetype": character.personality_type.value,
            "mood": "unknown",
            "recent_thoughts": [],
            "recent_decisions": [],
            "recent_actions": [],
            "corruption_level": 0.0,
            "rumor_level": 0.0,
            "status": "active",
        }
        try:
            npc_data["mood"] = _r.get(f"npc_mood:{char_id}") or "unknown"
        except Exception:
            pass
        try:
            thoughts_raw = _r.zrevrange(f"npc_thoughts:{char_id}", 0, 2)
            npc_data["recent_thoughts"] = [json.loads(t) for t in thoughts_raw]
        except Exception:
            pass
        try:
            decisions_raw = _r.zrevrange(f"npc_decisions:{char_id}", 0, 2)
            npc_data["recent_decisions"] = [json.loads(d) for d in decisions_raw]
        except Exception:
            pass
        try:
            actions_raw = _r.zrevrange(f"npc_actions:{char_id}", 0, 2)
            npc_data["recent_actions"] = [json.loads(a) for a in actions_raw]
        except Exception:
            pass
        try:
            state = _r.hgetall(f"npc_state:{char_id}")
            npc_data["corruption_level"] = float(state.get("corruption_level", 0))
            npc_data["rumor_level"] = float(state.get("rumor_level", 0))
            npc_data["status"] = state.get("status", "active")
        except Exception:
            pass
        npcs.append(npc_data)
    return {"npcs": npcs, "count": len(npcs)}


@app.get("/simulation/events")
async def simulation_events(limit: int = 50):
    """World events and cascade events for the simulation observer."""
    import redis as _redis

    _r = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )
    result = {
        "world_events": [],
        "cascade_events": [],
        "broadcast_events": [],
    }
    try:
        result["world_events"] = get_world_events(limit=limit)
    except Exception:
        pass
    try:
        cascade_raw = _r.zrevrange("cascade_reactions", 0, limit - 1)
        result["cascade_events"] = [json.loads(c) for c in cascade_raw]
    except Exception:
        pass
    try:
        broadcast_raw = _r.zrevrange("npc_broadcast_events", 0, min(limit, 20) - 1)
        result["broadcast_events"] = [json.loads(b) for b in broadcast_raw]
    except Exception:
        pass
    return result


# ============================================================================
# NPC GOAL ENDPOINTS (Phase 5)
# ============================================================================


@app.get("/npcs/{char_id}/goals")
async def npc_goals(char_id: str):
    try:
        goals = get_goals(char_id)
        return {"char_id": char_id, "goals": goals, "count": len(goals)}
    except Exception as e:
        return {"char_id": char_id, "goals": [], "count": 0, "error": str(e)}


@app.post("/npcs/{char_id}/goals/generate")
async def npc_generate_goal(char_id: str):
    character = game_state.npc_system.characters.get(char_id)
    if not character:
        return {"error": f"NPC {char_id} not found"}
    try:
        goal = generate_goal(char_id, character.personality_type.value)
        return {"char_id": char_id, "goal": goal, "status": "generated"}
    except Exception as e:
        return {"char_id": char_id, "error": str(e), "status": "failed"}


@app.post("/npcs/{char_id}/goals/{goal_id}/advance")
async def npc_advance_goal(char_id: str, goal_id: str):
    try:
        result = advance_goal(char_id, goal_id)
        return {"char_id": char_id, "goal_id": goal_id, "result": result}
    except Exception as e:
        return {"char_id": char_id, "goal_id": goal_id, "error": str(e)}


@app.post("/npcs/{char_id}/goals/{goal_id}/status")
async def npc_set_goal_status(char_id: str, goal_id: str, status: str = "abandoned"):
    try:
        result = set_goal_status(char_id, goal_id, status)
        return {"char_id": char_id, "goal_id": goal_id, "result": result}
    except Exception as e:
        return {"char_id": char_id, "goal_id": goal_id, "error": str(e)}


# ============================================================================
# QUEST / CAMPAIGN ENDPOINTS
# ============================================================================


@app.get("/quests")
async def get_quests(faction: Optional[str] = None):
    qs = game_state.quest_system
    faction_filter = None
    if faction:
        try:
            faction_filter = FactionAffiliation(faction)
        except ValueError:
            logger.info(f"Ignoring unrecognized faction filter: {faction}")
    available = qs.get_available_quests(faction_filter=faction_filter)
    active = qs.get_active_quests()
    completed = qs.get_completed_quests()
    return {
        "available": [q.to_dict() for q in available],
        "active": [q.to_dict() for q in active],
        "completed": [q.to_dict() for q in completed],
        "total_registered": len(qs.quests),
    }


@app.get("/quests/report/summary")
async def get_quest_report():
    return game_state.quest_system.get_quest_sync_report()


@app.get("/quests/{quest_id}")
async def get_quest_detail(quest_id: str):
    if quest_id not in game_state.quest_system.quests:
        raise HTTPException(status_code=404, detail="Quest not found")
    quest = game_state.quest_system.quests[quest_id]
    return quest.to_dict()


class QuestAcceptRequest(BaseModel):
    player_id: str = "player_1"


@app.post("/quests/{quest_id}/accept")
async def accept_quest(quest_id: str, req: QuestAcceptRequest):
    success, message = game_state.quest_system.accept_quest(
        req.player_id, quest_id, game_state.turn
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"accepted": True, "message": message, "quest_id": quest_id}


class QuestProgressRequest(BaseModel):
    player_id: str = "player_1"
    objective_id: str
    amount: int = 1


@app.post("/quests/{quest_id}/progress")
async def progress_quest(quest_id: str, req: QuestProgressRequest):
    success, message = game_state.quest_system.progress_objective(
        req.player_id, quest_id, req.objective_id, req.amount
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    quest = game_state.quest_system.quests.get(quest_id)
    return {
        "progressed": True,
        "message": message,
        "quest_id": quest_id,
        "all_objectives_complete": quest.are_all_objectives_complete()
        if quest
        else False,
    }


class QuestCompleteRequest(BaseModel):
    player_id: str = "player_1"


@app.post("/quests/{quest_id}/complete")
async def complete_quest(quest_id: str, req: QuestCompleteRequest):
    success, message, rewards = game_state.quest_system.complete_quest(
        req.player_id, quest_id, game_state.turn
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "completed": True,
        "message": message,
        "quest_id": quest_id,
        "rewards": rewards.to_dict() if rewards else None,
    }


class QuestAbandonRequest(BaseModel):
    player_id: str = "player_1"


@app.post("/quests/{quest_id}/abandon")
async def abandon_quest(quest_id: str, req: QuestAbandonRequest):
    success, message = game_state.quest_system.abandon_quest(
        req.player_id, quest_id, game_state.turn
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"abandoned": True, "message": message, "quest_id": quest_id}


# ============================================================================
# TECHNOLOGY / RESEARCH ENDPOINTS
# ============================================================================


@app.get("/technology")
async def get_technology(philsophy: Optional[str] = None):
    tt = game_state.tech_tree
    available = tt.get_available_techs()
    if philsophy:
        try:
            from technology import ResearchPhilosophy

            phil = ResearchPhilosophy(philsophy)
            available = [t for t in available if t.philosophy == phil]
        except ValueError:
            logger.info(
                f"Ignoring unrecognized research philosophy filter: {philosophy}"
            )
    return {
        "available": [
            {
                "id": t.tech_id,
                "name": t.name,
                "tier": t.tier,
                "era": t.era.value,
                "philosophy": t.philosophy.value,
                "cost": t.research_cost,
                "prerequisites": t.prerequisites,
                "unlocks_techs": t.unlocks_techs,
            }
            for t in available
        ],
        "completed": list(tt.completed_techs.keys()),
        "total_registered": len(tt.technologies),
    }


@app.get("/technology/tree")
async def get_tech_tree():
    return game_state.tech_tree.get_research_tree()


@app.get("/technology/report")
async def get_tech_report():
    return game_state.tech_tree.get_research_report()


@app.get("/technology/{tech_id}")
async def get_tech_detail(tech_id: str):
    if tech_id not in game_state.tech_tree.technologies:
        raise HTTPException(status_code=404, detail="Technology not found")
    tech = game_state.tech_tree.technologies[tech_id]
    return {
        "tech_id": tech.tech_id,
        "name": tech.name,
        "description": tech.description,
        "tier": tech.tier,
        "era": tech.era.value,
        "philosophy": tech.philosophy.value,
        "research_cost": tech.research_cost,
        "prerequisites": tech.prerequisites,
        "unlocks_techs": tech.unlocks_techs,
        "unlocks_quests": tech.unlocks_quests,
        "unlocks_perks": tech.unlocks_perks,
        "unlocks_features": tech.unlocks_features,
        "bonuses": [b.to_dict() for b in tech.bonuses],
        "is_completed": game_state.tech_tree.is_tech_completed("player_1", tech_id),
    }


class StartResearchRequest(BaseModel):
    player_id: str = "player_1"


@app.post("/technology/{tech_id}/research")
async def start_research(tech_id: str, req: StartResearchRequest):
    success, message, project = game_state.tech_tree.start_research(
        req.player_id, tech_id
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "started": True,
        "message": message,
        "project": project.to_dict() if project else None,
    }


class AdvanceResearchRequest(BaseModel):
    player_id: str = "player_1"
    project_id: str
    research_points: int = 10


@app.post("/technology/research/advance")
async def advance_research(req: AdvanceResearchRequest):
    success, message, progress = game_state.tech_tree.advance_research(
        req.player_id, req.project_id, req.research_points
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {
        "advanced": True,
        "message": message,
        "progress": progress,
        "is_complete": progress >= 1.0,
    }


@app.get("/technology/unlocks/{tech_id}")
async def get_tech_unlocks(tech_id: str):
    unlocks = game_state.tech_tree.get_unlocked_by_tech(tech_id)
    if not unlocks:
        raise HTTPException(status_code=404, detail="Technology not found")
    return unlocks


# ============================================================================
# NEW SUBSYSTEM API ROUTES
# ============================================================================


@app.get("/rivals")
async def get_rivals():
    """Get all rival federations"""
    if not game_state.rival_simulator:
        return {"rivals": [], "system_available": False}
    try:
        states = game_state.rival_simulator.get_all_rival_states()
        return {
            "rivals": states,
            "system_available": True,
            "total": len(game_state.rival_simulator.rivals)
            if hasattr(game_state.rival_simulator, "rivals")
            else 0,
        }
    except Exception as e:
        return {"rivals": [], "system_available": False, "error": str(e)}


@app.post("/rivals/spawn")
async def spawn_rival():
    """Spawn a new rival federation"""
    if not game_state.rival_simulator:
        raise HTTPException(status_code=503, detail="Rival system not available")
    try:
        game_state.rival_simulator.initialize_rivals()
        game_state.engine_systems["rival_simulator"]["active_rivals"] = (
            len(game_state.rival_simulator.rivals)
            if hasattr(game_state.rival_simulator, "rivals")
            else 0
        )
        return {
            "result": "spawned",
            "total_rivals": game_state.engine_systems["rival_simulator"][
                "active_rivals"
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/consciousness")
async def get_consciousness():
    """Get full consciousness sheet status"""
    if not game_state.consciousness_sheet:
        return {"system_available": False}
    try:
        cs = game_state.consciousness_sheet
        return {
            "system_available": True,
            "morale": cs.morale,
            "identity": cs.identity,
            "anxiety": cs.anxiety,
            "confidence": cs.confidence,
            "expansion_hunger": cs.expansion_hunger,
            "diplomacy_tendency": cs.diplomacy_tendency,
            "dreams": getattr(cs, "dreams", []) or [],
            "prophecies": getattr(cs, "prophecies", []) or [],
            "archetypes": getattr(cs, "archetypes", []) or [],
            "traumas": getattr(cs, "traumas", []) or [],
        }
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@app.get("/history-arc")
async def get_history_arc():
    """Get history arc status"""
    if not game_state.history_arc:
        return {"system_available": False}
    try:
        ha = game_state.history_arc
        return {
            "system_available": True,
            "current_era": getattr(ha, "current_era", "unknown"),
            "year": getattr(ha, "current_year", 0)
            if hasattr(ha, "current_year")
            else getattr(ha.timeline, "current_year", 0),
            "initialized": getattr(ha, "_initialized", False),
        }
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@app.post("/history-arc/advance")
async def advance_history_year():
    """Advance the history arc by one year"""
    if not game_state.history_arc:
        raise HTTPException(status_code=503, detail="History arc not available")
    try:
        result = game_state.history_arc.advance_year()
        return {"result": "advanced", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history-arc/export")
async def export_history_state():
    """Export full history arc state"""
    if not game_state.history_arc:
        raise HTTPException(status_code=503, detail="History arc not available")
    try:
        return game_state.history_arc.export_full_state()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/political")
async def get_political_status():
    """Get political engine status"""
    if not game_state.political_engine:
        return {"system_available": False}
    try:
        status = game_state.political_engine.summary
        return {"system_available": True, "status": status}
    except Exception as e:
        return {"system_available": False, "error": str(e)}


@app.post("/political/process-turn")
async def process_political_turn():
    """Process one political turn"""
    if not game_state.political_engine:
        raise HTTPException(status_code=503, detail="Political system not available")
    try:
        current_year = game_state.timeline.current_year if game_state.timeline else 2387
        fed_state = (
            game_state.game_state_v2.federation if game_state.game_state_v2 else None
        )
        if fed_state:
            result = game_state.political_engine.process_year(current_year, fed_state)
        else:
            result = []
        return {"result": "processed", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/systems-overview")
async def get_systems_overview():
    """Get a comprehensive overview of all game systems including new ones"""
    overview = {
        "core_systems": {
            "factions": game_state.engine_systems.get("faction_system", {}).get(
                "loaded", False
            ),
            "timeline": game_state.engine_systems.get("turn_progression", {}).get(
                "loaded", False
            ),
            "npcs": game_state.engine_systems.get("npc_system", {}).get(
                "loaded", False
            ),
            "quests": game_state.engine_systems.get("quest_system", {}).get(
                "loaded", False
            ),
            "technology": game_state.engine_systems.get("technology_tree", {}).get(
                "loaded", False
            ),
            "events": game_state.engine_systems.get("event_registry", {}).get(
                "loaded", False
            ),
        },
        "new_systems": {
            "rival_simulator": game_state.rival_simulator is not None,
            "consciousness_sheet": game_state.consciousness_sheet is not None,
            "history_arc": game_state.history_arc is not None,
            "political_engine": game_state.political_engine is not None,
            "game_state_v2": game_state.game_state_v2 is not None,
            "console_engine": game_state.console_engine is not None,
        },
        "integration_status": {
            "total_systems": 0,
            "loaded_systems": 0,
        },
        "turn": game_state.turn,
    }
    all_systems = {**overview["core_systems"], **overview["new_systems"]}
    overview["integration_status"]["total_systems"] = len(all_systems)
    overview["integration_status"]["loaded_systems"] = sum(
        1 for v in all_systems.values() if v
    )
    return overview


# ============================================================================
# WEBSOCKET FOR REAL-TIME UPDATES
# ============================================================================


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                logger.debug(
                    "WebSocket broadcast failed for a connection; likely disconnected"
                )


# ============================================================================
# NPC DECISION ENDPOINTS (Phase 6)
# ============================================================================


@app.get("/npcs/{char_id}/decisions")
async def npc_decisions(char_id: str, limit: int = 5):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    decisions = get_decision_log(char_id, limit=limit)
    return {"char_id": char_id, "decisions": decisions, "count": len(decisions)}


@app.get("/npcs/{char_id}/decisions/evaluate")
async def npc_evaluate_decisions(char_id: str):
    if char_id not in game_state.npc_system.characters:
        raise HTTPException(status_code=404, detail="Character not found")
    character = game_state.npc_system.characters[char_id]
    archetype = character.personality_type.value
    affiliation = character.affiliation
    mood = get_mood(char_id)
    options = evaluate_decision_options(
        char_id, character.name, archetype, affiliation, mood=mood
    )
    return {
        "char_id": char_id,
        "name": character.name,
        "mood": mood,
        "options": options,
    }


# --- WORLD STATE API (Phase 6b) ---


@app.get("/world/state")
async def get_world_state_endpoint():
    state = get_world_state()
    return {"state": state, "conditions": list(state.keys())}


@app.get("/world/conditions")
async def get_world_conditions_endpoint():
    state = get_world_state()
    from npc_autonomy import WORLD_CONDITIONS

    result = {}
    for key, config in WORLD_CONDITIONS.items():
        result[key] = {
            "label": config["label"],
            "description": config["description"],
            "current": state.get(key, config["default"]),
            "default": config["default"],
            "min": config["min"],
            "max": config["max"],
        }
    return result


@app.get("/world/state/{condition}")
async def get_world_condition_endpoint(condition: str):
    from npc_autonomy import WORLD_CONDITIONS

    if condition not in WORLD_CONDITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown condition: {condition}")
    value = get_world_condition(condition)
    config = WORLD_CONDITIONS[condition]
    return {
        "condition": condition,
        "value": value,
        "label": config["label"],
        "description": config["description"],
        "default": config["default"],
        "min": config["min"],
        "max": config["max"],
    }


@app.post("/world/state/{condition}")
async def set_world_condition_endpoint(condition: str, value: int = None):
    from npc_autonomy import WORLD_CONDITIONS, set_world_condition as _set_wc

    if condition not in WORLD_CONDITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown condition: {condition}")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' parameter")
    config = WORLD_CONDITIONS[condition]
    clamped = max(config["min"], min(config["max"], value))
    _set_wc(condition, clamped)
    return {
        "condition": condition,
        "value": clamped,
        "previous_range": f"{config['min']}-{config['max']}",
    }


@app.get("/world/history")
async def get_world_state_history_endpoint(limit: int = 10):
    history = get_world_state_history(limit=limit)
    return {"history": history, "count": len(history)}


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "state", "data": await get_state()})
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/state/save")
async def state_save():
    try:
        success = game_state.save_to_db(snapshot_type="auto")
        if success:
            return {
                "status": "saved",
                "snapshot_type": "manual",
                "db_initialized": db_manager._initialized,
            }
        return {"status": "failed", "db_initialized": db_manager._initialized}
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "db_initialized": db_manager._initialized,
        }


@app.get("/state/load")
async def state_load():
    try:
        if not db_manager._initialized:
            return {"status": "unavailable", "message": "Database not initialized"}
        snapshot = db_manager.load_latest_snapshot()
        if snapshot is None:
            return {"status": "no_snapshot", "message": "No snapshot found"}
        game_state._restore_from_snapshot(snapshot)
        game_state.engine_systems["persistence"]["loaded"] = True
        game_state.engine_systems["persistence"]["last_checkpoint"] = snapshot.get(
            "created_at"
        )
        return {
            "status": "restored",
            "snapshot_type": snapshot.get("snapshot_type"),
            "created_at": snapshot.get("created_at"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/state/info")
async def state_info():
    try:
        count = db_manager.get_snapshot_count() if db_manager._initialized else 0
        return {
            "db_initialized": db_manager._initialized,
            "snapshot_count": count,
            "persistence": game_state.engine_systems.get("persistence", {}),
        }
    except Exception as e:
        return {"db_initialized": False, "snapshot_count": 0, "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


# --- PHASE 6C: BROADCAST EVENT ENDPOINTS ---


@app.get("/npcs/{char_id}/broadcast-events")
async def npc_broadcast_events(char_id: str, limit: int = 10):
    from npc_autonomy import get_broadcast_events

    events = get_broadcast_events(char_id=char_id, limit=limit)
    return {"char_id": char_id, "events": events, "count": len(events)}


@app.get("/broadcast-events")
async def all_broadcast_events(limit: int = 20):
    from npc_autonomy import get_broadcast_events

    events = get_broadcast_events(limit=limit)
    return {"events": events, "count": len(events)}
