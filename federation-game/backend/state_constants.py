"""
Federation Game State Constants — extracted from state.py
Contains: availability flags, game config, constant dicts, metric definitions.
"""

import logging
from typing import Dict, List, Set, Any

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
    from event_cascade import (
        process_cascade,
        process_faction_cascade,
        get_cascade_summary,
    )

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
        get_spatial_status,
        get_all_sectors,
        get_sector_by_id,
        get_sector_summary,
        get_all_discoveries,
        get_faction_home,
        get_faction_territories,
        get_faction_discoveries,
        get_adjacent_sector_ids,
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
PENDING_CHOICE_TTL_SECONDS = 300

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
