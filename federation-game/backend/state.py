"""
Federation Game State — extracted from main.py (Option B refactor)
Contains: constants, GameState class, helper functions, game_state singleton.
main.py imports game_state from here. Routes import game_state from here.
No circular dependency: state.py does NOT import from main.py.
"""

import json
import random
import hashlib
import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import asdict

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

from federation_game_db import db_manager

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
    from simulation_engine import autonomous_tick, bridge_world_state_to_game_state
    SIMULATION_ENGINE_AVAILABLE = True
except ImportError:
    SIMULATION_ENGINE_AVAILABLE = False

try:
    from faction_ai import run_all_factions, resolve_pending_items, FACTION_IDEOLOGY
    FACTION_AI_AVAILABLE = True
except ImportError:
    FACTION_AI_AVAILABLE = False

try:
    from event_cascade import process_cascade, process_faction_cascade, get_cascade_summary
    EVENT_CASCADE_AVAILABLE = True
except ImportError:
    EVENT_CASCADE_AVAILABLE = False

try:
    from npc_cognition import run_cognition, get_cognition_stats
    COGNITION_AVAILABLE = True
except ImportError:
    COGNITION_AVAILABLE = False

try:
    from narrator import generate_narration, get_narration_history
    NARRATOR_AVAILABLE = True
except ImportError:
    NARRATOR_AVAILABLE = False

try:
    from llm_router import get_router_stats
    LLM_ROUTER_AVAILABLE = True
except ImportError:
    LLM_ROUTER_AVAILABLE = False

try:
    from npc_memory import get_memories, get_memory_summary, generate_reflective_summary
    NPC_MEMORY_AVAILABLE = True
except ImportError:
    NPC_MEMORY_AVAILABLE = False

try:
    from spatial_seed import seed_spatial_system
    from spatial_queries import (
        get_spatial_status, get_all_sectors, get_sector_by_id,
        get_sector_summary, get_all_discoveries, get_faction_home,
        get_faction_territories, get_faction_discoveries, get_adjacent_sector_ids,
    )
    from spatial_state import is_spatial_enabled
    SPATIAL_SYSTEM_AVAILABLE = True
except ImportError:
    SPATIAL_SYSTEM_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# GAME STATE CONSTANTS
# ============================================================================

PERCENT_METRICS = {
    "fuel", "shields", "hull", "crew_morale",
    "federation_stability", "public_trust", "council_support",
    "constitutional_integrity", "rights_protection", "emergency_powers",
}

VICTORY_TURN = 100

LEDGER_METRICS = [
    "credits", "fuel", "shields", "hull", "crew_morale",
    "discovered_sectors", "allies", "federation_stability",
    "public_trust", "council_support", "constitutional_integrity",
    "rights_protection", "emergency_powers",
]

METRIC_LABELS = {
    "credits": "credits", "fuel": "fuel", "shields": "shields",
    "hull": "hull", "crew_morale": "crew morale",
    "discovered_sectors": "sectors", "allies": "allies",
    "federation_stability": "stability", "public_trust": "public trust",
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
        "archetypes": ["Hero", "Scholar", "Rogue", "Warrior", "Mystic", "Leader", "Sage", "Wanderer", "Deceiver", "Guardian"],
        "companion_bonuses": ["Morale", "Research", "Combat", "Diplomacy", "Exploration", "Defense", "Stealth"],
    },
    "creature_codex": {
        "summary": "Mystical and consciousness-bearing species with habitats, evolutionary pressures, anomalies, taming, and affinity.",
        "species": ["Quantum Consciousness Beings", "Crystalline Collectives", "Temporal Drifters", "Mythic Anomalies",
                    "Dimensional Weavers", "Void Skippers", "Echo Entities", "Synthesis Collective", "Chaos Weavers", "Harmony Beings"],
        "game_creatures": ["Sky-Furk", "Plasma-Kite", "Thrumback", "Cloud Gnasher", "Void Skipper", "Dream Wyrm",
                           "Harmonic Maw", "Prism Assembly"],
    },
    "technology_tree": {
        "summary": "57+ technologies across 5 tiers, 7 eras, and 4 research philosophies with dependency chains and unlocks.",
        "eras": ["Ancient", "Classical", "Medieval", "Industrial", "Modern", "Future", "Transcendent"],
        "philosophies": ["Military", "Scientific", "Cultural", "Consciousness"],
        "capstones": ["Artificial Intelligence", "Consciousness Technology", "Dimensional Engineering",
                      "Reality Manipulation", "Time Mastery", "Federation Ascension"],
    },
    "uss_chaosbringer": {
        "summary": "Narrative/continuity laboratory: anomaly court, gossip graph, memory graph, temporal systems, mood feedback, and continuity black box.",
        "systems": ["Anomaly Court", "Continuity Black Box", "Gossip Graph", "Memory Graph", "Narrative Physics",
                    "Temporal Gardening", "Paradox Fire Department", "What-If Simulator", "Signalharvester Ship",
                    "Quantum Patch Notes"],
    },
}

GOVERNANCE_PROPOSALS = [
    {
        "title": "EMERGENCY ECONOMIC STIMULUS",
        "description": "The treasury proposes a direct credit injection to stimulate economic activity.",
        "domain": "Economy",
        "rights_at_stake": ["Fiscal transparency", "Resource allocation fairness"],
        "constitutional_risk": "low",
        "pressure": "Stimulus spending can boost morale and stability short-term but may erode long-term credit.",
        "affected_lane": "Control Plane",
        "rationale": "Credits flow through governance; unchecked spending creates debt without constraint.",
        "policies": {
            "vote": "Economic Transparency Act",
            "emergency_order": "Central Bank Override",
            "court_review": "Fiscal Accountability Review",
        },
        "next_safe_actions": {
            "vote": "Audit the treasury ledger and publish the spending record.",
            "emergency_order": "Monitor credit flow and check for inflationary pressure.",
            "court_review": "Publish the court ruling and archive the fiscal record.",
        },
    },
    {
        "title": "MILITARY EXPANSION AUTHORIZATION",
        "description": "Military Command requests authority to expand fleet capacity and patrol range.",
        "domain": "Military",
        "rights_at_stake": ["Civilian oversight", "Peaceful coexistence"],
        "constitutional_risk": "medium",
        "pressure": "Military expansion improves safety and stability but shifts the balance toward force.",
        "affected_lane": "Control Plane",
        "rationale": "Security and liberty exist in tension; unchecked military growth risks constitutional drift.",
        "policies": {
            "vote": "Demilitarization Accord",
            "emergency_order": "Fleet Expansion Initiative",
            "court_review": "Military Oversight Charter",
        },
        "next_safe_actions": {
            "vote": "Record the demilitarization commitment and monitor neighbor relations.",
            "emergency_order": "Log fleet positions and track public trust for signs of militarization drift.",
            "court_review": "Publish the charter and set up civilian review board.",
        },
    },
    {
        "title": "FREEDOM OF INFORMATION ACT",
        "description": "The Council proposes opening historical archives and research records to all citizens.",
        "domain": "Civic",
        "rights_at_stake": ["Access to information", "Privacy rights"],
        "constitutional_risk": "medium",
        "pressure": "Transparency builds trust but may expose sensitive data and compromise operational security.",
        "affected_lane": "Library",
        "rationale": "Transparency is governance's proof of integrity, but access without context can mislead.",
        "policies": {
            "vote": "Open Records Mandate",
            "emergency_order": "Classified Archives Lockdown",
            "court_review": "Balanced Disclosure Framework",
        },
        "next_safe_actions": {
            "vote": "Publish the archive index and set up public access terminals.",
            "emergency_order": "Audit the classification system for over-classification.",
            "court_review": "Implement redaction standards and publish the review process.",
        },
    },
    {
        "title": "ALIEN CITIZENSHIP EXPANSION",
        "description": "A proposal to extend full citizenship rights to registered non-human residents.",
        "domain": "Identity",
        "rights_at_stake": ["Sentient rights", "Cultural preservation"],
        "constitutional_risk": "high",
        "pressure": "Expanding rights builds alliance and diversity but may face cultural resistance.",
        "affected_lane": "Control Plane",
        "rationale": "Rights expansion tests constitutional elasticity; too fast destabilizes, too slow calcifies.",
        "policies": {
            "vote": "Universal Sentience Rights Act",
            "emergency_order": "Citizenship Moratorium",
            "court_review": "Gradual Integration Framework",
        },
        "next_safe_actions": {
            "vote": "Register new citizens and update the rights ledger.",
            "emergency_order": "Conduct a social impact study before the next expansion vote.",
            "court_review": "Publish integration guidelines and establish cultural support programs.",
        },
    },
    {
        "title": "AI GOVERNANCE INTEGRATION",
        "description": "Proposal to grant AI systems formal advisory status in the legislative process.",
        "domain": "Governance",
        "rights_at_stake": ["Human decision authority", "AI autonomy"],
        "constitutional_risk": "high",
        "pressure": "AI integration improves decision quality but raises questions about who governs.",
        "affected_lane": "Archivist",
        "rationale": "AI advice is governance amplification — it multiplies both wisdom and error at scale.",
        "policies": {
            "vote": "AI Advisory Charter",
            "emergency_order": "AI Decision Authority",
            "court_review": "AI Accountability Framework",
        },
        "next_safe_actions": {
            "vote": "Publish the AI charter and set up audit logs for AI advice.",
            "emergency_order": "Review all AI-generated decisions for the last quarter.",
            "court_review": "Establish AI audit trails and accountability reviews.",
        },
    },
    {
        "title": "COLONY SELF-DETERMINATION ACT",
        "description": "Proposes granting sector-level colonies the right to draft local constitutions.",
        "domain": "Federalism",
        "rights_at_stake": ["Self-governance", "Federal unity"],
        "constitutional_risk": "medium",
        "pressure": "Decentralization empowers local populations but risks fragmentation of federation authority.",
        "affected_lane": "Control Plane",
        "rationale": "Federations survive by balancing local autonomy against collective strength.",
        "policies": {
            "vote": "Colony Governance Charter",
            "emergency_order": "Federal Oversight Directive",
            "court_review": "Balanced Federalism Framework",
        },
        "next_safe_actions": {
            "vote": "Accreditation process for colony constitutions and monitor compliance.",
            "emergency_order": "Audit colony governance for rights violations.",
            "court_review": "Establish an appeals process for colony constitution disputes.",
        },
    },
    {
        "title": "EMERGENCY POWERS RENEWAL",
        "description": "Annual vote to renew or terminate the Council's emergency executive powers.",
        "domain": "Constitutional",
        "rights_at_stake": ["Executive oversight", "Rights preservation"],
        "constitutional_risk": "critical",
        "pressure": "Emergency powers enable swift action but erode constitutional norms the longer they persist.",
        "affected_lane": "Control Plane",
        "rationale": "Emergency powers are governance's steroids; short-term performance at long-term cost.",
        "policies": {
            "vote": "Emergency Powers Sunset Clause",
            "emergency_order": "Emergency Powers Continuation",
            "court_review": "Emergency Powers Review Act",
        },
        "next_safe_actions": {
            "vote": "Archive the renewal vote and log the sunset timeline.",
            "emergency_order": "Document all emergency power usages this period for next review.",
            "court_review": "Publish the rights audit and set up ongoing monitoring.",
        },
    },
]


# ============================================================================
# HELPER FUNCTIONS (used by route handlers)
# ============================================================================

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
        defaults.get("rationale", "Decision requires explicit state-transition review."),
    )
    choices = []
    for choice in enriched.get("choices", []):
        c = dict(choice)
        c.setdefault("affected_lane", enriched["affected_lane"])
        c.setdefault("rationale", enriched["rationale"])
        c.setdefault(
            "next_safe_action",
            defaults.get("next_safe_action", "Record the decision and verify the next state."),
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


def build_explainability(event: Dict[str, Any], choice: Dict[str, Any], deltas: Dict[str, int]) -> Dict[str, str]:
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
        "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
        "constitutional_pressure": constitutional_pressure,
        "short_term_gain": summarize_delta_direction(deltas, positive=True),
        "long_term_cost": summarize_delta_direction(deltas, positive=False),
        "rationale": choice.get("rationale", event.get("rationale", "Decision recorded for bounded simulator continuity.")),
        "next_safe_action": choice.get("next_safe_action", "Record the decision, verify the next state, and continue only inside lane boundaries."),
    }


def get_governance_status() -> str:
    gs = game_state
    if gs.constitutional_integrity < 25:
        return "CONSTITUTIONAL CRISIS"
    if gs.rights_protection < 25:
        return "RIGHTS CRISIS"
    if gs.public_trust < 35:
        return "PUBLIC TRUST WARNING"
    if gs.council_support < 35:
        return "COUNCIL DEADLOCK WARNING"
    if gs.emergency_powers > 70:
        return "EMERGENCY POWERS WATCH"
    if gs.federation_stability > 75 and gs.public_trust > 70:
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
                    "public_trust": 8, "council_support": 10, "federation_stability": 4,
                    "constitutional_integrity": 3, "emergency_powers": -6,
                },
                "policy": proposal["policies"]["vote"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["vote"],
                "lesson": "Legitimacy rises when people can see the process.",
                "faction_affinity": {"diplomatic_corps": 0.10, "cultural_ministry": 0.03},
            },
            {
                "id": "emergency_order",
                "text": "EMERGENCY ORDER",
                "outcome": "swift action",
                "reward": {
                    "credits": 120, "public_trust": -10, "council_support": -8,
                    "federation_stability": -6, "constitutional_integrity": -10,
                    "rights_protection": -8, "emergency_powers": 18,
                },
                "policy": proposal["policies"]["emergency_order"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["emergency_order"],
                "lesson": "Power used without checks solves one problem by creating another.",
                "faction_affinity": {"military_command": 0.08, "preservation_society": -0.05},
            },
            {
                "id": "court_review",
                "text": "COURT REVIEW",
                "outcome": "rights protected",
                "reward": {
                    "public_trust": 12, "council_support": -3, "federation_stability": 8,
                    "credits": -40, "constitutional_integrity": 10,
                    "rights_protection": 12, "emergency_powers": -10,
                },
                "policy": proposal["policies"]["court_review"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["court_review"],
                "lesson": "Rights are slower than orders, but they keep the system trustworthy.",
                "faction_affinity": {"preservation_society": 0.10, "diplomatic_corps": 0.03},
            },
        ],
    }


def apply_governance_pressure(choice: Dict[str, Any]) -> None:
    gs = game_state
    if gs.public_trust < 35:
        gs.crew_morale = clamp_percent(gs.crew_morale - 3)
        gs.federation_stability = clamp_percent(gs.federation_stability - 2)

    if gs.council_support < 30:
        gs.federation_stability = clamp_percent(gs.federation_stability - 1)
        gs.emergency_powers = clamp_percent(gs.emergency_powers + 1)

    if gs.emergency_powers > 80:
        gs.constitutional_integrity = clamp_percent(gs.constitutional_integrity - 2)
        gs.rights_protection = clamp_percent(gs.rights_protection - 1)

    if gs.federation_stability > 80:
        gs.public_trust = clamp_percent(gs.public_trust + 1)


# ============================================================================
# GAME STATE CLASS
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

        self.rival_simulator = RivalFederationSimulator() if RIVAL_SYSTEM_AVAILABLE else None
        self.consciousness_sheet = ConsciousnessSheet() if CONSCIOUSNESS_SYSTEM_AVAILABLE else None
        self.game_state_v2 = FederationGameState() if GAME_STATE_V2_AVAILABLE else None
        self.history_arc = None
        self.political_engine = None
        self.console_engine = None

        self.engine_systems = {
            "quest_system": {"loaded": True, "active_quests": 0, "completed_quests": 0},
            "faction_system": {"loaded": True, "known_factions": len(self.faction_system.factions), "player_standing": {}},
            "technology_tree": {"loaded": True, "research_points": 0, "unlocked_techs": []},
            "npc_system": {"loaded": True, "known_npcs": 0, "active_relationships": {}},
            "event_registry": {"loaded": True, "total_events": 0, "events_seen": []},
            "consciousness_metrics": {"loaded": True, "coherence": 50.0, "stability": 50.0, "complexity": 50.0},
            "turn_progression": {"loaded": True, "current_phase": "early_exploration", "turns_in_phase": 0},
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
                snapshot = db_manager.load_latest_snapshot()
                if snapshot:
                    self._restore_from_snapshot(snapshot)
                    self.engine_systems["persistence"]["loaded"] = True
                    self.engine_systems["persistence"]["last_checkpoint"] = snapshot.get("created_at")
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
                fed_state = self.game_state_v2.federation if self.game_state_v2 else None
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
                logger.warning("Rival simulator initialization failed; continuing without rivals")

        self.engine_systems.update({
            "rival_simulator": {
                "loaded": self.rival_simulator is not None,
                "active_rivals": len(self.rival_simulator.rivals)
                if self.rival_simulator and hasattr(self.rival_simulator, "rivals") else 0,
            },
            "consciousness_sheet": {"loaded": self.consciousness_sheet is not None, "coherence": 0.0, "stability": 0.0},
            "history_arc": {"loaded": self.history_arc is not None, "current_era": "genesis", "year": 0},
            "political_engine": {"loaded": self.political_engine is not None, "laws_passed": 0},
            "game_state_v2": {"loaded": self.game_state_v2 is not None},
            "console_engine": {"loaded": self.console_engine is not None},
        })

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
                fed.technological_level = federation_data.get("technological_level", 0.2)
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
                    "turn": self.turn, "credits": self.credits, "fuel": self.fuel,
                    "shields": self.shields, "hull": self.hull, "crew_morale": self.crew_morale,
                    "discovered_sectors": self.discovered_sectors, "allies": self.allies,
                    "federation_stability": self.federation_stability, "public_trust": self.public_trust,
                    "council_support": self.council_support, "constitutional_integrity": self.constitutional_integrity,
                    "rights_protection": self.rights_protection, "emergency_powers": self.emergency_powers,
                    "active_policy": self.active_policy, "federation_name": self.federation_name,
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
                    "victory_type": self.game_state_v2.victory_type.value if self.game_state_v2.victory_type else None,
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
                history_arc_json = json.dumps(self.history_arc.export_full_state(), default=str)
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
                    "turn": self.turn, "credits": self.credits, "fuel": self.fuel,
                    "shields": self.shields, "hull": self.hull, "crew_morale": self.crew_morale,
                    "federation_stability": self.federation_stability, "public_trust": self.public_trust,
                    "council_support": self.council_support, "constitutional_integrity": self.constitutional_integrity,
                    "rights_protection": self.rights_protection, "emergency_powers": self.emergency_powers,
                    "active_policy": self.active_policy, "discovered_sectors": self.discovered_sectors, "allies": self.allies,
                },
                sort_keys=True,
            )
            state_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        except Exception:
            logger.warning("State hash computation failed; snapshot will proceed without hash")

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