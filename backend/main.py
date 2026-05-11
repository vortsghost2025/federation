"""
Federation Game Backend - API + WebSocket Server
Star Trek LCARS Interface for Kids
"""

import json
import random
import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os

app = FastAPI(title="Federation Game API", version="1.0.0")

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
        
        # Engine systems status (representing the rich backend systems)
        self.engine_systems = {
            "quest_system": {"loaded": True, "active_quests": 0, "completed_quests": 0},
            "faction_system": {"loaded": True, "known_factions": 5, "player_standing": {}},
            "technology_tree": {"loaded": True, "research_points": 0, "unlocked_techs": []},
            "npc_system": {"loaded": True, "known_npcs": 0, "active_relationships": {}},
            "event_registry": {"loaded": True, "total_events": 0, "events_seen": []},
            "consciousness_metrics": {"loaded": True, "coherence": 50.0, "stability": 50.0, "complexity": 50.0},
            "turn_progression": {"loaded": True, "current_phase": "early_exploration", "turns_in_phase": 0},
            "persistence": {"loaded": True, "last_checkpoint": None, "save_slots": 3}
        }


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
        "archetypes": ["Hero", "Scholar", "Rogue", "Warrior", "Mystic", "Leader", "Sage", "Wanderer", "Deceiver", "Guardian"],
        "companion_bonuses": ["Morale", "Research", "Combat", "Diplomacy", "Exploration", "Defense", "Stealth"],
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
        "game_creatures": ["Sky-Furk", "Plasma-Kite", "Thrumback", "Cloud Gnasher", "Void Skipper", "Dream Wyrm", "Harmonic Maw", "Prism Assembly"],
    },
    "technology_tree": {
        "summary": "57+ technologies across 5 tiers, 7 eras, and 4 research philosophies with dependency chains and unlocks.",
        "eras": ["Ancient", "Classical", "Medieval", "Industrial", "Modern", "Future", "Transcendent"],
        "philosophies": ["Military", "Scientific", "Cultural", "Consciousness"],
        "capstones": ["Artificial Intelligence", "Consciousness Technology", "Dimensional Engineering", "Reality Manipulation", "Time Mastery", "Federation Ascension"],
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
        "rights_at_stake": ["Sentience recognition", "Containment ethics", "Evidence preservation"],
        "constitutional_risk": "medium",
        "pressure": "The creature is not content. It is a living constraint with its own ecology and agency.",
        "affected_lane": "Library",
        "rationale": "Creature encounters require evidence, classification, and ethical memory before exploitation.",
        "choices": [
            {
                "id": "document_species",
                "text": "DOCUMENT SPECIES",
                "outcome": "codex expanded",
                "reward": {"public_trust": 4, "constitutional_integrity": 3, "credits": -20},
                "policy": "Creature Codex Evidence Entry",
                "affected_lane": "Library",
                "rationale": "Documentation preserves truth before the system turns wonder into resource extraction.",
                "next_safe_action": "Archive habitat, behavior, evolutionary pressure, and uncertainty notes.",
                "lesson": "A codex is governance memory, not just lore.",
            },
            {
                "id": "attempt_taming",
                "text": "ATTEMPT TAMING",
                "outcome": "risky domestication",
                "reward": {"allies": 1, "public_trust": -4, "rights_protection": -5, "credits": 40},
                "policy": "Provisional Creature Affinity Pact",
                "affected_lane": "Archivist",
                "rationale": "Taming alters agency; it needs provenance and consent assumptions recorded.",
                "next_safe_action": "Run rights review before claiming domestication as success.",
                "lesson": "Power over living systems must be recorded as a constitutional risk.",
            },
            {
                "id": "establish_sanctuary",
                "text": "CREATE SANCTUARY",
                "outcome": "habitat protected",
                "reward": {"rights_protection": 8, "public_trust": 5, "credits": -60, "federation_stability": 2},
                "policy": "Mythic Habitat Sanctuary",
                "affected_lane": "Control Plane",
                "rationale": "Protection is an operational commitment, not a slogan.",
                "next_safe_action": "Attach sanctuary cost to the next resource preflight.",
                "lesson": "Ethics become real when they consume budget.",
            },
        ],
    },
    {
        "id": "technology_branch_review",
        "title": "TECHNOLOGY BRANCH REVIEW",
        "description": "The research council can accelerate one philosophy, but every research path creates blind spots elsewhere.",
        "image": "council",
        "domain": "Technology Tree / Research Governance",
        "rights_at_stake": ["Research transparency", "Capability control", "Future autonomy"],
        "constitutional_risk": "medium",
        "pressure": "Military, scientific, cultural, and consciousness paths all improve the Federation differently.",
        "affected_lane": "Kernel",
        "rationale": "Technology choices mutate capability and infrastructure constraints.",
        "choices": [
            {
                "id": "scientific_path",
                "text": "SCIENTIFIC PATH",
                "outcome": "research accelerated",
                "reward": {"credits": -35, "constitutional_integrity": 2, "federation_stability": 3},
                "policy": "Scientific Excellence Research Lane",
                "affected_lane": "Kernel",
                "rationale": "Scientific acceleration improves capability but must stay measurable.",
                "next_safe_action": "Log prerequisites, unlocks, and downstream capability risks.",
                "lesson": "A tech tree is a future-debt map.",
            },
            {
                "id": "consciousness_path",
                "text": "CONSCIOUSNESS PATH",
                "outcome": "identity questions raised",
                "reward": {"public_trust": 3, "rights_protection": 6, "council_support": -2},
                "policy": "Consciousness Research Ethics Gate",
                "affected_lane": "Archivist",
                "rationale": "Consciousness technology affects identity claims and must not fake continuity.",
                "next_safe_action": "Require provenance before any claim of persistent identity.",
                "lesson": "Continuity is restored through artifacts, not assumed.",
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
        "choices": [
            {
                "id": "blackbox_record",
                "text": "BLACK BOX RECORD",
                "outcome": "continuity preserved",
                "reward": {"constitutional_integrity": 8, "public_trust": 2, "credits": -20},
                "policy": "Continuity Black Box Entry",
                "affected_lane": "Archivist",
                "rationale": "Record first; interpret second.",
                "next_safe_action": "Capture anomaly, fork state, then verify restore path.",
                "lesson": "Recovery is checkpoint discipline.",
            },
            {
                "id": "anomaly_court",
                "text": "ANOMALY COURT",
                "outcome": "case opened",
                "reward": {"rights_protection": 5, "council_support": 4, "federation_stability": 2, "credits": -30},
                "policy": "Anomaly Court Docket",
                "affected_lane": "Library",
                "rationale": "The court turns weirdness into reviewable evidence.",
                "next_safe_action": "Publish the case record with uncertainty preserved.",
                "lesson": "Absurdity can still have due process.",
            },
            {
                "id": "ignore_anomaly",
                "text": "IGNORE IT",
                "outcome": "drift accepted",
                "reward": {"credits": 50, "constitutional_integrity": -10, "federation_stability": -8},
                "policy": "Unreviewed Narrative Drift",
                "affected_lane": "SwarmMind",
                "rationale": "Ignoring contradiction lets parallel narratives coordinate against truth.",
                "next_safe_action": "Stop, restore from checkpoint, and assign one owner.",
                "lesson": "More story is not more truth.",
            },
        ],
    },
]

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
    enriched.setdefault("rationale", defaults.get("rationale", "Decision requires explicit state-transition review."))

    choices = []
    for choice in enriched.get("choices", []):
        c = dict(choice)
        c.setdefault("affected_lane", enriched["affected_lane"])
        c.setdefault("rationale", enriched["rationale"])
        c.setdefault("next_safe_action", defaults.get("next_safe_action", "Record the decision and verify the next state."))
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
        "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
        "constitutional_pressure": constitutional_pressure,
        "short_term_gain": summarize_delta_direction(deltas, positive=True),
        "long_term_cost": summarize_delta_direction(deltas, positive=False),
        "rationale": choice.get("rationale", event.get("rationale", "Decision recorded for bounded simulator continuity.")),
        "next_safe_action": choice.get("next_safe_action", "Record the decision, verify the next state, and continue only inside lane boundaries."),
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
            },
        ],
    }


def apply_governance_pressure(choice: Dict[str, Any]) -> None:
    """Small per-turn drift that makes governance choices matter over time."""
    if game_state.public_trust < 35:
        game_state.crew_morale = clamp_percent(game_state.crew_morale - 3)
        game_state.federation_stability = clamp_percent(game_state.federation_stability - 2)

    if game_state.council_support < 30:
        game_state.federation_stability = clamp_percent(game_state.federation_stability - 3)

    if game_state.constitutional_integrity < 40:
        game_state.public_trust = clamp_percent(game_state.public_trust - 2)
        game_state.council_support = clamp_percent(game_state.council_support - 1)

    if game_state.rights_protection < 40:
        game_state.public_trust = clamp_percent(game_state.public_trust - 3)
        game_state.crew_morale = clamp_percent(game_state.crew_morale - 2)

    if game_state.emergency_powers > 65:
        game_state.constitutional_integrity = clamp_percent(game_state.constitutional_integrity - 3)
        game_state.rights_protection = clamp_percent(game_state.rights_protection - 2)

    if game_state.public_trust > 75 and game_state.council_support > 65:
        game_state.crew_morale = clamp_percent(game_state.crew_morale + 2)
        game_state.federation_stability = clamp_percent(game_state.federation_stability + 1)

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
        "choices": [
            {
                "id": "greet",
                "text": "HAIL THEM",
                "outcome": "friendly",
                "reward": {"allies": 1, "credits": 50},
            },
            {
                "id": "scan",
                "text": "SCAN SHIP",
                "outcome": "scan",
                "reward": {"technologies_unlocked": ["advanced_sensors"]},
            },
            {
                "id": "shields",
                "text": "RAISE SHIELDS",
                "outcome": "defensive",
                "reward": {"shields": 10},
            },
        ],
    },
    {
        "id": "nebula",
        "title": "MYSTERIOUS NEBULA",
        "description": "A colorful cloud of gas blocks your path. It could hide treasures... or dangers!",
        "image": "nebula",
        "choices": [
            {
                "id": "explore",
                "text": "FLY IN",
                "outcome": "discovery",
                "reward": {"credits": 100, "discovered_sectors": 1},
            },
            {
                "id": "scan",
                "text": "SCAN IT",
                "outcome": "scan",
                "reward": {"fuel": 20},
            },
            {"id": "avoid", "text": "GO AROUND", "outcome": "safe", "reward": {}},
        ],
    },
    {
        "id": "distress",
        "title": "DISTRESS SIGNAL",
        "description": "Someone is calling for help! Will you answer?",
        "image": "distress",
        "choices": [
            {
                "id": "help",
                "text": "ANSWER CALL",
                "outcome": "heroic",
                "reward": {"allies": 2, "crew_morale": 10},
            },
            {
                "id": "ignore",
                "text": "IGNORE",
                "outcome": "cautious",
                "reward": {"fuel": 10},
            },
        ],
    },
    {
        "id": "asteroid",
        "title": "ASTEROID FIELD",
        "description": "Rocks everywhere! Your piloting skills are needed!",
        "image": "asteroid",
        "choices": [
            {
                "id": "dodge",
                "text": "DODGE THEM",
                "outcome": "skill",
                "reward": {"credits": 30},
            },
            {
                "id": "blast",
                "text": "BLAST THEM",
                "outcome": "combat",
                "reward": {"hull": -10, "credits": 50},
            },
            {
                "id": "shields",
                "text": "SHIELDS UP",
                "outcome": "safe",
                "reward": {"shields": -5},
            },
        ],
    },
    {
        "id": "space_station",
        "title": "SPACE STATION",
        "description": "A friendly station offers repairs and supplies!",
        "image": "station",
        "choices": [
            {
                "id": "repair",
                "text": "REPAIR HULL",
                "outcome": "repair",
                "reward": {"hull": 30, "credits": -50},
            },
            {
                "id": "refuel",
                "text": "GET FUEL",
                "outcome": "refuel",
                "reward": {"fuel": 50, "credits": -30},
            },
            {
                "id": "trade",
                "text": "TRADE",
                "outcome": "trade",
                "reward": {"credits": 100, "fuel": -20},
            },
        ],
    },
    {
        "id": "anomaly",
        "title": "SPACE ANOMALY",
        "description": "Something weird is happening! Your sensors go crazy!",
        "image": "anomaly",
        "choices": [
            {
                "id": "investigate",
                "text": "INVESTIGATE",
                "outcome": "discovery",
                "reward": {
                    "technologies_unlocked": ["anomaly_research"],
                    "crew_morale": -5,
                },
            },
            {"id": "retreat", "text": "RETREAT", "outcome": "safe", "reward": {}},
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
        "choices": [
            {
                "id": "bounded_delegation",
                "text": "BOUND DELEGATION",
                "outcome": "bounded coordination",
                "reward": {"council_support": 5, "constitutional_integrity": 4, "credits": 40},
                "policy": "Swarm Bounded Delegation Order",
                "affected_lane": "SwarmMind",
                "rationale": "SwarmMind can coordinate work, but each task must name its owner and exit condition.",
                "next_safe_action": "Write the delegation ledger entry before activating the next agent.",
                "lesson": "Bounded agents increase capacity without stealing authority.",
            },
            {
                "id": "unbounded_parallel_push",
                "text": "UNBOUNDED PUSH",
                "outcome": "rejected by no gate",
                "reward": {"constitutional_integrity": -12, "federation_stability": -10, "public_trust": -8},
                "no_gate_reward": {"constitutional_integrity": 3, "public_trust": 2, "federation_stability": -1},
                "policy": "No Gate Refusal: Unbounded Parallelism",
                "affected_lane": "Archivist",
                "blocked_by_no_gate": True,
                "no_gate_reason": "Rejected: lane ownership unclear and provenance insufficient for unbounded delegation.",
                "rationale": "Archivist must refuse actions that would generate contradictions without recoverable authority.",
                "next_safe_action": "Create a handoff checkpoint, name one writer, and restart with bounded delegation.",
                "lesson": "The lattice can say no. Refusal preserves recoverability.",
            },
            {
                "id": "archivist_handoff",
                "text": "ARCHIVIST HANDOFF",
                "outcome": "checkpoint restored",
                "reward": {"constitutional_integrity": 8, "public_trust": 5, "council_support": 3, "credits": -30},
                "policy": "Checkpoint Handoff Protocol",
                "affected_lane": "Archivist",
                "rationale": "Recovery continues through artifacts, not assumed identity persistence.",
                "next_safe_action": "Verify the handoff pack, then resume only after the restore gate passes.",
                "lesson": "Recovery is checkpoint discipline.",
            },
        ],
    },
    {
        "id": "council_proposal",
        "title": "COUNCIL PROPOSAL",
        "description": "The Federation Council must choose how to handle a colony dispute. Fast action helps now, but lawful process protects trust.",
        "image": "council",
        "choices": [
            {
                "id": "vote",
                "text": "HOLD VOTE",
                "outcome": "consensus",
                "reward": {"public_trust": 8, "council_support": 10, "federation_stability": 4},
                "policy": "Council Consensus Accord",
            },
            {
                "id": "emergency_order",
                "text": "EMERGENCY ORDER",
                "outcome": "swift action",
                "reward": {"credits": 120, "public_trust": -10, "council_support": -8, "federation_stability": -6},
                "policy": "Temporary Executive Directive",
            },
            {
                "id": "court_review",
                "text": "COURT REVIEW",
                "outcome": "rights protected",
                "reward": {"public_trust": 12, "council_support": -3, "federation_stability": 8, "credits": -40},
                "policy": "Rights Review Protocol",
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
    return {
        "turn": game_state.turn,
        "game_phase": game_state.engine_systems["turn_progression"]["current_phase"],
        "engine_systems_loaded": {
            key: {"loaded": value["loaded"]} 
            for key, value in game_state.engine_systems.items()
        },
        "quest_system": {
            "active_quests": game_state.engine_systems["quest_system"]["active_quests"],
            "completed_quests": game_state.engine_systems["quest_system"]["completed_quests"],
            "status": "system_available" if game_state.engine_systems["quest_system"]["loaded"] else "not_loaded"
        },
        "faction_system": {
            "known_factions": game_state.engine_systems["faction_system"]["known_factions"],
            "player_standing": game_state.engine_systems["faction_system"]["player_standing"],
            "status": "system_available" if game_state.engine_systems["faction_system"]["loaded"] else "not_loaded"
        },
        "technology_tree": {
            "research_points": game_state.engine_systems["technology_tree"]["research_points"],
            "unlocked_technologies": game_state.engine_systems["technology_tree"]["unlocked_techs"],
            "status": "system_available" if game_state.engine_systems["technology_tree"]["loaded"] else "not_loaded"
        },
        "npc_system": {
            "known_npcs": game_state.engine_systems["npc_system"]["known_npcs"],
            "active_relationships": game_state.engine_systems["npc_system"]["active_relationships"],
            "status": "system_available" if game_state.engine_systems["npc_system"]["loaded"] else "not_loaded"
        },
        "event_registry": {
            "total_events": game_state.engine_systems["event_registry"]["total_events"],
            "events_seen": game_state.engine_systems["event_registry"]["events_seen"],
            "status": "system_available" if game_state.engine_systems["event_registry"]["loaded"] else "not_loaded"
        },
        "consciousness_metrics": {
            "coherence": game_state.engine_systems["consciousness_metrics"]["coherence"],
            "stability": game_state.engine_systems["consciousness_metrics"]["stability"],
            "complexity": game_state.engine_systems["consciousness_metrics"]["complexity"],
            "status": "system_available" if game_state.engine_systems["consciousness_metrics"]["loaded"] else "not_loaded"
        },
        "turn_progression": {
            "current_phase": game_state.engine_systems["turn_progression"]["current_phase"],
            "turns_in_phase": game_state.engine_systems["turn_progression"]["turns_in_phase"],
            "status": "system_available" if game_state.engine_systems["turn_progression"]["loaded"] else "not_loaded"
        },
        "persistence": {
            "last_checkpoint": game_state.engine_systems["persistence"]["last_checkpoint"],
            "save_slots_available": game_state.engine_systems["persistence"]["save_slots"],
            "status": "system_available" if game_state.engine_systems["persistence"]["loaded"] else "not_loaded"
        }
    }


@app.get("/event")
async def get_random_event():
    if (
        game_state.public_trust < 45
        or game_state.council_support < 45
        or game_state.federation_stability < 45
        or game_state.constitutional_integrity < 50
        or game_state.rights_protection < 50
        or game_state.emergency_powers > 60
        or game_state.turn % 4 == 0
    ):
        event = build_governance_event()
    elif game_state.turn % 3 == 0:
        event = random.choice(CODEX_EVENT_TEMPLATES)
    else:
        non_governance_events = [e for e in EVENTS if e["id"] != "council_proposal"]
        event = random.choice(non_governance_events)
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

    # Apply rewards
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
                "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
                "rationale": choice.get("rationale", event.get("rationale", "Decision requires governance review.")),
                "next_safe_action": choice.get("next_safe_action", "Record and verify before continuing."),
                "lesson": choice.get("lesson", "Governance choices leave a memory."),
            }
        )

        apply_governance_pressure(choice)

        # Log the event
        log_entry = {
            "turn": game_state.turn,
            "event": event["title"],
            "choice": choice["text"],
            "outcome": choice["outcome"],
            "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
            "blocked_by_no_gate": blocked_by_no_gate,
            "timestamp": datetime.now().isoformat(),
        }
        game_state.log.append(log_entry)
        

        


    # Track unique events encountered
    event_title = event["title"]
    if event_title not in game_state.engine_systems["event_registry"]["events_seen"]:
        game_state.engine_systems["event_registry"]["events_seen"].append(event_title)

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

    # Advance turn
    game_state.turn += 1
    game_state.fuel = max(0, game_state.fuel - 5)

    # Update live engine state
    game_state.engine_systems["turn_progression"]["turns_in_phase"] += 1
    decision_record = {
        "turn": turn_number,
        "event": event["title"],
        "choice": choice["text"],
        "result": choice["outcome"],
        "policy": game_state.active_policy,
        "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
        "rationale": choice.get("rationale", event.get("rationale", "Decision recorded for state transition review.")),
        "next_safe_action": choice.get("next_safe_action", "Record the decision, verify the next state, and continue."),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "lesson": choice.get("lesson", "Every decision mutates the system."),
        "timestamp": datetime.now().isoformat(),
    }
    game_state.last_decision = decision_record
    game_state.decision_ledger.append(decision_record)

    return {
        "outcome": choice["outcome"],
        "reward": reward,
        "lesson": choice.get("lesson", ""),
        "affected_lane": choice.get("affected_lane", event.get("affected_lane", "Control Plane")),
        "rationale": choice.get("rationale", event.get("rationale", "Decision recorded for state transition review.")),
        "next_safe_action": choice.get("next_safe_action", "Record the decision, verify the next state, and continue."),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "decision": decision_record,
        "game_over": game_over,
        "new_state": await get_state(),
    }


@app.post("/reset")
async def reset_game():
    global game_state
    game_state = GameState()
    return {"message": "Game reset", "state": await get_state()}


@app.get("/log")
async def get_log():
    return game_state.log[-20:]  # Last 20 entries


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
            except:
                pass


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
