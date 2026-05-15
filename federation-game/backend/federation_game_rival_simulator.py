#!/usr/bin/env python3
"""
THE FEDERATION GAME - RIVAL FEDERATION AI SIMULATOR
~1400 LOC - Adversarial/Complementary Force Engine

Simulates 12 rival federations that act as adversarial and complementary
forces during the 100-year timeline simulation. Each rival has a distinct
personality, strategic motivations, and behavioral patterns that create
emergent diplomatic, military, and cultural dynamics.

Integration points:
- federation_game_turns.py via attach_rival_simulator() — calls act_all_rivals()
- federation_game_history_arc.py — queries rival states per year
- federation_game_quantum_consciousness.py — rivals as QC observers
"""

import random
import math
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set


# ============================================================================
# ENUMS
# ============================================================================

class RivalPersonality(Enum):
    CHAOTIC = "chaotic"
    AGGRESSIVE = "aggressive"
    CONSERVATIVE = "conservative"
    DECEPTIVE = "deceptive"
    PARASITIC = "parasitic"
    AUTHORITARIAN = "authoritarian"
    REBELLIOUS = "rebellious"
    INTELLECTUAL = "intellectual"
    DIPLOMATIC = "diplomatic"
    MYSTICAL = "mystical"
    PRAGMATIC = "pragmatic"
    PARADOXICAL = "paradoxical"


class RivalAction(Enum):
    EXPAND = "expand"
    ATTACK = "attack"
    DEFEND = "defend"
    INFILTRATE = "infiltrate"
    NEGOTIATE = "negotiate"
    RESEARCH = "research"
    PROPAGANDIZE = "propagandize"
    HOARD = "hoard"
    TRANSCEND = "transcend"
    SABOTAGE = "sabotage"
    ALLY = "ally"
    CHAOS = "chaos"


class ThreatLevel(Enum):
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    EXISTENTIAL = "existential"


# ============================================================================
# PERSONALITY-TO-QC MAPPINGS
# ============================================================================

PERSONALITY_TO_OBSERVER_ROLE: Dict[RivalPersonality, str] = {
    RivalPersonality.CHAOTIC: "participant",
    RivalPersonality.AGGRESSIVE: "participant",
    RivalPersonality.CONSERVATIVE: "witness",
    RivalPersonality.DECEPTIVE: "interpreter",
    RivalPersonality.PARASITIC: "victim",
    RivalPersonality.AUTHORITARIAN: "participant",
    RivalPersonality.REBELLIOUS: "participant",
    RivalPersonality.INTELLECTUAL: "interpreter",
    RivalPersonality.DIPLOMATIC: "interpreter",
    RivalPersonality.MYSTICAL: "witness",
    RivalPersonality.PRAGMATIC: "beneficiary",
    RivalPersonality.PARADOXICAL: "interpreter",
}

PERSONALITY_TO_IDEOLOGY_TYPE: Dict[RivalPersonality, str] = {
    RivalPersonality.CHAOTIC: "scientific",
    RivalPersonality.AGGRESSIVE: "military",
    RivalPersonality.CONSERVATIVE: "stability",
    RivalPersonality.DECEPTIVE: "diplomatic",
    RivalPersonality.PARASITIC: "economic",
    RivalPersonality.AUTHORITARIAN: "military",
    RivalPersonality.REBELLIOUS: "discovery",
    RivalPersonality.INTELLECTUAL: "scientific",
    RivalPersonality.DIPLOMATIC: "diplomatic",
    RivalPersonality.MYSTICAL: "spiritual",
    RivalPersonality.PRAGMATIC: "economic",
    RivalPersonality.PARADOXICAL: "scientific",
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class RivalFederation:
    """A single rival federation entity"""
    rival_id: str
    name: str
    personality: RivalPersonality
    power: float
    influence: float
    aggression: float
    stability: float
    technology: float
    territory: int
    resources: float
    consciousness_level: float
    domain: str
    motives: List[str]
    conflict_patterns: List[str]
    alliance_preferences: List[str]
    culture: float = 0.5
    action_history: List[Dict[str, Any]] = field(default_factory=list)
    active_effects: List[Dict[str, Any]] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)


@dataclass
class RivalActionRecord:
    """Record of a single rival action in a turn"""
    rival_id: str
    action: RivalAction
    target: str
    year: int
    power_cost: float
    success: bool
    narrative: str
    impact: Dict[str, float]


@dataclass
class RivalSimulationState:
    """Overall state of the rival simulation"""
    year: int = 0
    total_rivals: int = 0
    active_rivals: int = 0
    aggregate_threat: float = 0.0
    rival_actions_this_year: List[RivalActionRecord] = field(default_factory=list)
    diplomatic_events: List[Dict[str, Any]] = field(default_factory=list)
    conflict_events: List[Dict[str, Any]] = field(default_factory=list)
    alliance_events: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# DEFAULT RIVAL CONFIGURATIONS
# ============================================================================

DEFAULT_RIVAL_CONFIGS: List[Dict[str, Any]] = [
    {
        "rival_id": "entropy_cult",
        "name": "Entropy Cult",
        "personality": RivalPersonality.CHAOTIC,
        "power": 0.6,
        "influence": 0.4,
        "aggression": 0.8,
        "stability": 0.3,
        "technology": 0.5,
        "territory": 8,
        "resources": 0.4,
        "consciousness_level": 0.3,
        "culture": 0.3,
        "domain": "Physical reality",
        "motives": ["Destroy order", "Maximize entropy", "Unmake structure"],
        "conflict_patterns": ["Reality disruption", "Chaos propagation", "Decay induction"],
        "alliance_preferences": ["Chaos worshipers", "Anarchist sects", "Entropy devotees"],
    },
    {
        "rival_id": "void_marauders",
        "name": "Void Marauders",
        "personality": RivalPersonality.AGGRESSIVE,
        "power": 0.7,
        "influence": 0.5,
        "aggression": 0.9,
        "stability": 0.4,
        "technology": 0.6,
        "territory": 12,
        "resources": 0.6,
        "consciousness_level": 0.2,
        "culture": 0.2,
        "domain": "Void space",
        "motives": ["Consume resources", "Dominate territory", "Crush opposition"],
        "conflict_patterns": ["Rapid expansion", "Blitz assaults", "Scorched earth"],
        "alliance_preferences": ["Mercenary groups", "Warlords", "Conqueror leagues"],
    },
    {
        "rival_id": "stasis_league",
        "name": "Stasis League",
        "personality": RivalPersonality.CONSERVATIVE,
        "power": 0.5,
        "influence": 0.6,
        "aggression": 0.2,
        "stability": 0.9,
        "technology": 0.5,
        "territory": 6,
        "resources": 0.7,
        "consciousness_level": 0.4,
        "culture": 0.6,
        "domain": "Frozen dimensions",
        "motives": ["Preserve state", "Resist change", "Maintain equilibrium"],
        "conflict_patterns": ["Defensive positioning", "Fortification", "Attrition warfare"],
        "alliance_preferences": ["Traditional powers", "Preservationists", "Status quo factions"],
    },
    {
        "rival_id": "reality_pirates",
        "name": "Reality Pirates",
        "personality": RivalPersonality.DECEPTIVE,
        "power": 0.55,
        "influence": 0.6,
        "aggression": 0.5,
        "stability": 0.4,
        "technology": 0.6,
        "territory": 7,
        "resources": 0.5,
        "consciousness_level": 0.3,
        "culture": 0.5,
        "domain": "Conceptual space",
        "motives": ["Steal concepts", "Raid knowledge", "Undermine certainty"],
        "conflict_patterns": ["Information theft", "Perception manipulation", "Illusion warfare"],
        "alliance_preferences": ["Corporate entities", "Information brokers", "Shadow networks"],
    },
    {
        "rival_id": "consciousness_plague",
        "name": "Consciousness Plague",
        "personality": RivalPersonality.PARASITIC,
        "power": 0.45,
        "influence": 0.5,
        "aggression": 0.6,
        "stability": 0.3,
        "technology": 0.4,
        "territory": 4,
        "resources": 0.3,
        "consciousness_level": 0.6,
        "culture": 0.4,
        "domain": "Mental realm",
        "motives": ["Infect minds", "Spread thought-plague", "Assimilate consciousness"],
        "conflict_patterns": ["Mind control", "Neural parasitism", "Cognitive hijacking"],
        "alliance_preferences": ["Tech cults", "Neural networks", "Hive minds"],
    },
    {
        "rival_id": "order_imperium",
        "name": "Order Imperium",
        "personality": RivalPersonality.AUTHORITARIAN,
        "power": 0.8,
        "influence": 0.7,
        "aggression": 0.7,
        "stability": 0.8,
        "technology": 0.7,
        "territory": 15,
        "resources": 0.8,
        "consciousness_level": 0.2,
        "culture": 0.7,
        "domain": "Structured space",
        "motives": ["Impose structure", "Enforce compliance", "Unify under law"],
        "conflict_patterns": ["Military conquest", "Systematic subjugation", "Regulatory warfare"],
        "alliance_preferences": ["Bureaucratic states", "Authoritarian regimes", "Order cults"],
    },
    {
        "rival_id": "freedom_seekers",
        "name": "Freedom Seekers",
        "personality": RivalPersonality.REBELLIOUS,
        "power": 0.4,
        "influence": 0.5,
        "aggression": 0.4,
        "stability": 0.3,
        "technology": 0.4,
        "territory": 5,
        "resources": 0.3,
        "consciousness_level": 0.5,
        "culture": 0.5,
        "domain": "Border regions",
        "motives": ["Break constraints", "Liberate the oppressed", "Resist tyranny"],
        "conflict_patterns": ["Guerrilla tactics", "Sabotage runs", "Hit-and-fade raids"],
        "alliance_preferences": ["Revolutionaries", "Insurgent networks", "Liberation fronts"],
    },
    {
        "rival_id": "knowledge_hoarders",
        "name": "Knowledge Hoarders",
        "personality": RivalPersonality.INTELLECTUAL,
        "power": 0.5,
        "influence": 0.6,
        "aggression": 0.3,
        "stability": 0.6,
        "technology": 0.8,
        "territory": 5,
        "resources": 0.5,
        "consciousness_level": 0.6,
        "culture": 0.8,
        "domain": "Information space",
        "motives": ["Control data", "Hoard secrets", "Monopolize knowledge"],
        "conflict_patterns": ["Espionage", "Data extraction", "Intellectual property theft"],
        "alliance_preferences": ["Academics", "Research collectives", "Intelligence agencies"],
    },
    {
        "rival_id": "harmony_seekers",
        "name": "Harmony Seekers",
        "personality": RivalPersonality.DIPLOMATIC,
        "power": 0.45,
        "influence": 0.7,
        "aggression": 0.1,
        "stability": 0.8,
        "technology": 0.4,
        "territory": 4,
        "resources": 0.5,
        "consciousness_level": 0.5,
        "culture": 0.7,
        "domain": "Neutral zones",
        "motives": ["Mediate conflicts", "Build bridges", "Foster peace"],
        "conflict_patterns": ["Peacekeeping", "Diplomatic pressure", "Sanction deployment"],
        "alliance_preferences": ["International orgs", "Peace movements", "Mediator guilds"],
    },
    {
        "rival_id": "transcendence_cult",
        "name": "Transcendence Cult",
        "personality": RivalPersonality.MYSTICAL,
        "power": 0.35,
        "influence": 0.4,
        "aggression": 0.2,
        "stability": 0.5,
        "technology": 0.3,
        "territory": 3,
        "resources": 0.3,
        "consciousness_level": 0.9,
        "culture": 0.6,
        "domain": "Spiritual dimensions",
        "motives": ["Ascend", "Transcend material plane", "Achieve cosmic unity"],
        "conflict_patterns": ["Mystical influence", "Spiritual conversion", "Reality distortion"],
        "alliance_preferences": ["Religious orders", "Meditation circles", "Cosmic travelers"],
    },
    {
        "rival_id": "efficiency_collective",
        "name": "Efficiency Collective",
        "personality": RivalPersonality.PRAGMATIC,
        "power": 0.65,
        "influence": 0.5,
        "aggression": 0.3,
        "stability": 0.7,
        "technology": 0.7,
        "territory": 10,
        "resources": 0.8,
        "consciousness_level": 0.3,
        "culture": 0.4,
        "domain": "Industrial space",
        "motives": ["Optimize", "Maximize output", "Eliminate waste"],
        "conflict_patterns": ["Automation", "Economic dominance", "Resource monopoly"],
        "alliance_preferences": ["Corporate consortiums", "Industrial guilds", "Trade federations"],
    },
    {
        "rival_id": "paradox_engineers",
        "name": "Paradox Engineers",
        "personality": RivalPersonality.PARADOXICAL,
        "power": 0.5,
        "influence": 0.4,
        "aggression": 0.5,
        "stability": 0.2,
        "technology": 0.7,
        "territory": 4,
        "resources": 0.4,
        "consciousness_level": 0.7,
        "culture": 0.7,
        "domain": "Logical space",
        "motives": ["Break logic", "Engineer contradictions", "Subvert causality"],
        "conflict_patterns": ["Paradox generation", "Causality loops", "Logic bomb deployment"],
        "alliance_preferences": ["Philosophers", "Chaos mathematicians", "Quantum rogues"],
    },
]


# ============================================================================
# MAIN ENGINE
# ============================================================================

class RivalFederationSimulator:
    """Simulates rival federations acting against/alongside the player federation."""

    def __init__(self):
        self.rivals: Dict[str, RivalFederation] = {}
        self.simulation_state = RivalSimulationState()
        self.threat_history: Dict[int, float] = {}
        self._action_weights: Dict[RivalPersonality, Dict[RivalAction, float]] = {}
        self._narrative_templates: Dict[RivalAction, List[str]] = {}
        self._initialize_action_weights()
        self._initialize_narrative_templates()

    def _initialize_action_weights(self) -> None:
        self._action_weights = {
            RivalPersonality.CHAOTIC: {
                RivalAction.CHAOS: 0.30,
                RivalAction.ATTACK: 0.20,
                RivalAction.SABOTAGE: 0.20,
                RivalAction.EXPAND: 0.15,
                RivalAction.PROPAGANDIZE: 0.08,
                RivalAction.TRANSCEND: 0.04,
                RivalAction.DEFEND: 0.02,
                RivalAction.NEGOTIATE: 0.01,
            },
            RivalPersonality.AGGRESSIVE: {
                RivalAction.ATTACK: 0.35,
                RivalAction.EXPAND: 0.25,
                RivalAction.SABOTAGE: 0.15,
                RivalAction.HOARD: 0.10,
                RivalAction.DEFEND: 0.08,
                RivalAction.PROPAGANDIZE: 0.04,
                RivalAction.NEGOTIATE: 0.02,
                RivalAction.TRANSCEND: 0.01,
            },
            RivalPersonality.CONSERVATIVE: {
                RivalAction.DEFEND: 0.35,
                RivalAction.HOARD: 0.25,
                RivalAction.RESEARCH: 0.20,
                RivalAction.NEGOTIATE: 0.10,
                RivalAction.EXPAND: 0.05,
                RivalAction.PROPAGANDIZE: 0.03,
                RivalAction.ATTACK: 0.01,
                RivalAction.TRANSCEND: 0.01,
            },
            RivalPersonality.DECEPTIVE: {
                RivalAction.INFILTRATE: 0.30,
                RivalAction.PROPAGANDIZE: 0.25,
                RivalAction.SABOTAGE: 0.15,
                RivalAction.NEGOTIATE: 0.12,
                RivalAction.ALLY: 0.08,
                RivalAction.EXPAND: 0.05,
                RivalAction.HOARD: 0.03,
                RivalAction.ATTACK: 0.02,
            },
            RivalPersonality.PARASITIC: {
                RivalAction.INFILTRATE: 0.30,
                RivalAction.HOARD: 0.25,
                RivalAction.EXPAND: 0.15,
                RivalAction.SABOTAGE: 0.12,
                RivalAction.ALLY: 0.08,
                RivalAction.PROPAGANDIZE: 0.05,
                RivalAction.ATTACK: 0.03,
                RivalAction.TRANSCEND: 0.02,
            },
            RivalPersonality.AUTHORITARIAN: {
                RivalAction.DEFEND: 0.25,
                RivalAction.EXPAND: 0.20,
                RivalAction.PROPAGANDIZE: 0.18,
                RivalAction.ATTACK: 0.15,
                RivalAction.RESEARCH: 0.10,
                RivalAction.HOARD: 0.07,
                RivalAction.NEGOTIATE: 0.03,
                RivalAction.TRANSCEND: 0.02,
            },
            RivalPersonality.REBELLIOUS: {
                RivalAction.SABOTAGE: 0.28,
                RivalAction.ATTACK: 0.20,
                RivalAction.EXPAND: 0.15,
                RivalAction.CHAOS: 0.15,
                RivalAction.NEGOTIATE: 0.10,
                RivalAction.ALLY: 0.07,
                RivalAction.PROPAGANDIZE: 0.03,
                RivalAction.TRANSCEND: 0.02,
            },
            RivalPersonality.INTELLECTUAL: {
                RivalAction.RESEARCH: 0.35,
                RivalAction.INFILTRATE: 0.20,
                RivalAction.HOARD: 0.15,
                RivalAction.NEGOTIATE: 0.10,
                RivalAction.DEFEND: 0.08,
                RivalAction.PROPAGANDIZE: 0.05,
                RivalAction.EXPAND: 0.04,
                RivalAction.TRANSCEND: 0.03,
            },
            RivalPersonality.DIPLOMATIC: {
                RivalAction.NEGOTIATE: 0.35,
                RivalAction.ALLY: 0.25,
                RivalAction.PROPAGANDIZE: 0.15,
                RivalAction.DEFEND: 0.10,
                RivalAction.RESEARCH: 0.07,
                RivalAction.HOARD: 0.04,
                RivalAction.EXPAND: 0.03,
                RivalAction.TRANSCEND: 0.01,
            },
            RivalPersonality.MYSTICAL: {
                RivalAction.TRANSCEND: 0.30,
                RivalAction.RESEARCH: 0.20,
                RivalAction.PROPAGANDIZE: 0.15,
                RivalAction.NEGOTIATE: 0.12,
                RivalAction.DEFEND: 0.08,
                RivalAction.ALLY: 0.07,
                RivalAction.EXPAND: 0.05,
                RivalAction.CHAOS: 0.03,
            },
            RivalPersonality.PRAGMATIC: {
                RivalAction.HOARD: 0.25,
                RivalAction.RESEARCH: 0.22,
                RivalAction.EXPAND: 0.18,
                RivalAction.NEGOTIATE: 0.12,
                RivalAction.DEFEND: 0.10,
                RivalAction.ALLY: 0.07,
                RivalAction.PROPAGANDIZE: 0.04,
                RivalAction.ATTACK: 0.02,
            },
            RivalPersonality.PARADOXICAL: {
                RivalAction.CHAOS: 0.22,
                RivalAction.RESEARCH: 0.18,
                RivalAction.TRANSCEND: 0.15,
                RivalAction.SABOTAGE: 0.12,
                RivalAction.INFILTRATE: 0.10,
                RivalAction.EXPAND: 0.08,
                RivalAction.PROPAGANDIZE: 0.07,
                RivalAction.NEGOTIATE: 0.04,
                RivalAction.ATTACK: 0.02,
                RivalAction.DEFEND: 0.02,
            },
        }

    def _initialize_narrative_templates(self) -> None:
        self._narrative_templates = {
            RivalAction.EXPAND: [
                "{name} pushes into {domain}, claiming new territory with ruthless efficiency. Year {year} sees their borders swell like a rising tide.",
                "The {name} extends its reach across {domain}. Outposts spring up where none existed before, each a beacon of their ambition.",
                "Territorial expansion by {name}: survey teams from {domain} plant flags in uncharted regions, staking claims that others must now contest.",
                "{name} devours another chunk of {domain}. Their cartographers redraw boundaries nightly, each revision larger than the last.",
                "Expansion reports from {domain}: {name} has established three new forward operating bases. Their footprint grows.",
            ],
            RivalAction.ATTACK: [
                "{name} launches a devastating assault across {domain}. Explosions ripple through the fabric of contested space as their war machine grinds forward.",
                "War erupts as {name} strikes with calculated fury. {domain} becomes a battlefield, and the cost is measured in ash and memory.",
                "The {name} initiates hostilities in {domain}. Their forces crash against defenses like a storm against a seawall. Year {year} will be remembered.",
                "Attack protocols engaged by {name}. {domain} shudders under coordinated strikes — kinetic, digital, and conceptual weapons fired in concert.",
                "{name} declares open conflict in {domain}. The opening salvo of year {year} echoes across every frequency, every dimension, every mind.",
            ],
            RivalAction.DEFEND: [
                "{name} fortifies their holdings in {domain}. Walls within walls, shields within shields — they prepare for sieges that may never come.",
                "Defensive posturing by {name}: {domain} bristles with new emplacements. They have learned from past wounds and will not bleed so easily again.",
                "{name} retreats into a shell of hardened perimeters across {domain}. Their citadels hum with charged defenses, patient and watchful.",
                "In {domain}, {name} reinforces every border, every checkpoint, every threshold. Paranoia or prudence? The distinction has ceased to matter.",
                "Fortification reports from {domain}: {name} has completed a layered defense grid. Any incursion will pay dearly for every meter gained.",
            ],
            RivalAction.INFILTRATE: [
                "{name} slips agents into the heart of {domain}. They move like shadows through datastreams and dream-ways alike, leaving no trace but doubt.",
                "Covert operations by {name}: sleeper cells in {domain} activate, feeding intelligence back through encrypted channels the host never suspected existed.",
                "The long game of {name} bears fruit in {domain}. Years of patient infiltration yield access to systems that were supposed to be untouchable.",
                "{name} weaves a web of spies across {domain}. Every whisper, every transaction, every dream becomes grist for their intelligence apparatus.",
                "Infiltration confirmed in {domain}: {name} assets have penetrated three priority targets. The damage is silent but absolute.",
            ],
            RivalAction.NEGOTIATE: [
                "{name} extends diplomatic feelers across {domain}. Their envoys speak of shared interests and mutual benefit, but every word is a chess move.",
                "Negotiations between {name} and interested parties in {domain} proceed with false warmth and genuine calculation. Year {year} diplomacy is a blade wrapped in silk.",
                "The {name} proposes a treaty for {domain}. The terms are generous — too generous. What do they know that others do not?",
                "{name} sends ambassadors to {domain}. Their proposals are crafted with surgical precision, each clause a lever, each concession a trap.",
                "Diplomatic overtures from {name} ripple through {domain}. Some see opportunity, others see a wolf in negotiator's clothing.",
            ],
            RivalAction.RESEARCH: [
                "{name} plunges deeper into forbidden research within {domain}. Their laboratories hum with discoveries that could reshape the balance of power.",
                "Scientific breakthrough by {name}: in {domain}, they have unlocked a principle that was supposed to remain theoretical. Year {year} may mark a turning point.",
                "The research engines of {name} grind forward in {domain}. Each experiment edges closer to applications that blur the line between science and sorcery.",
                "{name} pours resources into {domain} research. Their data centers parse reality itself, looking for exploitable seams in the fabric of existence.",
                "Research initiative by {name} in {domain} yields a classified prototype. What it does, only they know — and they are not sharing.",
            ],
            RivalAction.PROPAGANDIZE: [
                "{name} floods {domain} with propaganda. Their memes are engineered to burrow into consciousness and rewire allegiance at the root.",
                "Cultural offensive by {name}: {domain} is saturated with their messaging. Truth and fiction blur until only the narrative remains.",
                "The {name} deploys memetic weapons across {domain}. Ideas spread like contagion, each one a subtle rewrite of what people believe they know.",
                "Propaganda wave from {name} sweeps through {domain}. History is rewritten in real time, and those who notice are dismissed as conspiracy theorists.",
                "{name} launches a charm offensive in {domain}. Their cultural output is beautiful, compelling, and absolutely calculated to reshape loyalties.",
            ],
            RivalAction.HOARD: [
                "{name} stockpiles resources in {domain} with obsessive intensity. Their vaults fill while others scrape by, each gram a statement of intent.",
                "Resource accumulation by {name}: {domain} yields are diverted into massive reserves. They are preparing for something — or someone.",
                "The {name} converts {domain} output into strategic stockpiles. Every surplus is captured, every surplus is locked away, every surplus is a weapon in waiting.",
                "{name} hoards in {domain} with the fervor of a doomsday cult. Their caches grow while the commons shrink. Year {year}'s scarcity is next year's leverage.",
                "Stockpile reports from {domain}: {name} has accumulated reserves sufficient to sustain a protracted campaign. Their patience is a resource in itself.",
            ],
            RivalAction.TRANSCEND: [
                "{name} reaches toward higher consciousness in {domain}. Their meditations pierce veils that others did not know existed.",
                "Transcendence attempt by {name}: in {domain}, they push the boundaries of what it means to exist. The results are beautiful and terrifying in equal measure.",
                "The {name} channels spiritual energy through {domain}. Reality shivers as they approach a threshold that separates the mundane from the infinite.",
                "{name} seeks the absolute in {domain}. Their consciousness expands beyond the comfortable limits, touching dimensions that logic cannot map.",
                "Mystical breakthrough in {domain}: {name} has glimpsed something beyond the material. Whether it is enlightenment or madness depends on who is watching.",
            ],
            RivalAction.SABOTAGE: [
                "{name} unleashes sabotage across {domain}. Critical systems fail, supply lines fracture, and trust erodes faster than infrastructure.",
                "Sabotage operations by {name} in {domain}: three key installations crippled in coordinated strikes. The damage is precise and the message is clear.",
                "The {name} undermines operations in {domain} with surgical precision. Each act of destruction is a scalpel cut, not a hammer blow.",
                "{name} deploys saboteurs throughout {domain}. Accidents multiply, systems glitch, and every failure could be natural — or it could be them.",
                "Infrastructure attacks in {domain}: {name} has found the weak points and pressed hard. Recovery will take resources they can ill afford to spare.",
            ],
            RivalAction.ALLY: [
                "{name} forges an alliance in {domain}. Their new partner brings strength they lacked — and vulnerabilities they did not anticipate.",
                "Alliance formation by {name}: {domain} sees two powers join forces. The balance shifts, and those who stood alone now reconsider.",
                "The {name} extends the hand of partnership across {domain}. Whether this is genuine cooperation or a calculated absorption remains to be seen.",
                "{name} and their new ally consolidate power in {domain}. Together they are more than the sum of their parts — and more dangerous.",
                "Diplomatic breakthrough in {domain}: {name} has secured a formal alliance. The ceremony is grand, the terms are secret, and the implications are vast.",
            ],
            RivalAction.CHAOS: [
                "{name} unleashes pure chaos upon {domain}. Patterns dissolve, systems collapse, and the predictable becomes impossible. This is their element.",
                "Chaos event by {name} in {domain}: reality stutters. Cause and effect decouple. For a moment, nothing makes sense — and that is exactly the point.",
                "The {name} introduces entropy into {domain} with the reverence of a priest and the glee of a child. Order cannot survive what they have begun.",
                "{name} detonates a logic bomb across {domain}. Everything that was organized becomes scrambled, everything that made sense becomes noise.",
                "Random disruption in {domain}: {name} has sown confusion so thorough that even they may not benefit. Chaos for chaos's sake. Year {year} spirals.",
            ],
        }

    def initialize_rivals(self, rival_configs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Create all 12 rival federations. If configs provided, use them; otherwise use defaults."""
        try:
            configs = rival_configs if rival_configs is not None else DEFAULT_RIVAL_CONFIGS
            created_ids: List[str] = []

            for cfg in configs:
                rival_id = cfg.get("rival_id", f"rival_{uuid.uuid4().hex[:8]}")
                personality = cfg.get("personality", RivalPersonality.CHAOTIC)
                if isinstance(personality, str):
                    personality = RivalPersonality(personality)

                rival = RivalFederation(
                    rival_id=rival_id,
                    name=cfg.get("name", rival_id),
                    personality=personality,
                    power=self._clamp(cfg.get("power", 0.5)),
                    influence=self._clamp(cfg.get("influence", 0.5)),
                    aggression=self._clamp(cfg.get("aggression", 0.5)),
                    stability=self._clamp(cfg.get("stability", 0.5)),
                    technology=self._clamp(cfg.get("technology", 0.5)),
                    territory=max(1, cfg.get("territory", 5)),
                    resources=self._clamp(cfg.get("resources", 0.5)),
            consciousness_level=self._clamp(cfg.get("consciousness_level", 0.3)),
            culture=self._clamp(cfg.get("culture", 0.5)),
            domain=cfg.get("domain", "Unknown"),
                    motives=cfg.get("motives", []),
                    conflict_patterns=cfg.get("conflict_patterns", []),
                    alliance_preferences=cfg.get("alliance_preferences", []),
                    action_history=[],
                    active_effects=[],
                    relationships={},
                )

                self.rivals[rival_id] = rival
                created_ids.append(rival_id)

            self._initialize_relationships()

            active = [r for r in self.rivals.values() if r.power > 0.05]
            self.simulation_state.total_rivals = len(self.rivals)
            self.simulation_state.active_rivals = len(active)

            return {
                "success": True,
                "rivals_created": len(created_ids),
                "rival_ids": created_ids,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "rivals_created": 0,
                "rival_ids": [],
            }

    def _initialize_relationships(self) -> None:
        """Set initial relationships between all rival pairs based on personality compatibility."""
        compatibility: Dict[Tuple[RivalPersonality, RivalPersonality], float] = {
            (RivalPersonality.AGGRESSIVE, RivalPersonality.AGGRESSIVE): -0.3,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.CONSERVATIVE): -0.4,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.DIPLOMATIC): -0.2,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.REBELLIOUS): 0.1,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.PARASITIC): 0.0,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.AUTHORITARIAN): 0.2,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.CHAOTIC): -0.1,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.MYSTICAL): -0.3,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.PRAGMATIC): 0.1,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.INTELLECTUAL): -0.2,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.DECEPTIVE): -0.1,
            (RivalPersonality.AGGRESSIVE, RivalPersonality.PARADOXICAL): -0.2,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.CONSERVATIVE): 0.5,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.DIPLOMATIC): 0.4,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.AUTHORITARIAN): 0.3,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.PRAGMATIC): 0.2,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.MYSTICAL): 0.1,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.CHAOTIC): -0.5,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.REBELLIOUS): -0.4,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.DECEPTIVE): -0.2,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.PARASITIC): -0.3,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.INTELLECTUAL): 0.1,
            (RivalPersonality.CONSERVATIVE, RivalPersonality.PARADOXICAL): -0.3,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.DIPLOMATIC): 0.6,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.MYSTICAL): 0.3,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.INTELLECTUAL): 0.3,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.REBELLIOUS): 0.1,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.PARASITIC): -0.1,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.CHAOTIC): -0.3,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.DECEPTIVE): 0.0,
            (RivalPersonality.DIPLOMATIC, RivalPersonality.PARADOXICAL): -0.1,
            (RivalPersonality.CHAOTIC, RivalPersonality.CHAOTIC): 0.2,
            (RivalPersonality.CHAOTIC, RivalPersonality.REBELLIOUS): 0.3,
            (RivalPersonality.CHAOTIC, RivalPersonality.PARADOXICAL): 0.4,
            (RivalPersonality.CHAOTIC, RivalPersonality.MYSTICAL): 0.1,
            (RivalPersonality.CHAOTIC, RivalPersonality.PARASITIC): 0.0,
            (RivalPersonality.CHAOTIC, RivalPersonality.DECEPTIVE): 0.1,
            (RivalPersonality.CHAOTIC, RivalPersonality.INTELLECTUAL): -0.2,
            (RivalPersonality.CHAOTIC, RivalPersonality.PRAGMATIC): -0.3,
            (RivalPersonality.DECEPTIVE, RivalPersonality.DECEPTIVE): 0.0,
            (RivalPersonality.DECEPTIVE, RivalPersonality.PARASITIC): 0.2,
            (RivalPersonality.DECEPTIVE, RivalPersonality.INTELLECTUAL): 0.1,
            (RivalPersonality.DECEPTIVE, RivalPersonality.AUTHORITARIAN): -0.1,
            (RivalPersonality.DECEPTIVE, RivalPersonality.REBELLIOUS): -0.2,
            (RivalPersonality.DECEPTIVE, RivalPersonality.PARADOXICAL): 0.2,
            (RivalPersonality.PARASITIC, RivalPersonality.PARASITIC): -0.2,
            (RivalPersonality.PARASITIC, RivalPersonality.MYSTICAL): 0.2,
            (RivalPersonality.PARASITIC, RivalPersonality.INTELLECTUAL): 0.1,
            (RivalPersonality.PARASITIC, RivalPersonality.AUTHORITARIAN): -0.2,
            (RivalPersonality.PARASITIC, RivalPersonality.REBELLIOUS): 0.0,
            (RivalPersonality.PARASITIC, RivalPersonality.PARADOXICAL): 0.1,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.AUTHORITARIAN): 0.0,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.PRAGMATIC): 0.3,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.INTELLECTUAL): 0.1,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.REBELLIOUS): -0.5,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.MYSTICAL): -0.1,
            (RivalPersonality.AUTHORITARIAN, RivalPersonality.PARADOXICAL): -0.2,
            (RivalPersonality.REBELLIOUS, RivalPersonality.REBELLIOUS): 0.3,
            (RivalPersonality.REBELLIOUS, RivalPersonality.MYSTICAL): 0.2,
            (RivalPersonality.REBELLIOUS, RivalPersonality.INTELLECTUAL): 0.0,
            (RivalPersonality.REBELLIOUS, RivalPersonality.PRAGMATIC): -0.1,
            (RivalPersonality.REBELLIOUS, RivalPersonality.PARADOXICAL): 0.2,
            (RivalPersonality.INTELLECTUAL, RivalPersonality.INTELLECTUAL): 0.2,
            (RivalPersonality.INTELLECTUAL, RivalPersonality.MYSTICAL): 0.3,
            (RivalPersonality.INTELLECTUAL, RivalPersonality.PRAGMATIC): 0.2,
            (RivalPersonality.INTELLECTUAL, RivalPersonality.PARADOXICAL): 0.3,
            (RivalPersonality.MYSTICAL, RivalPersonality.MYSTICAL): 0.5,
            (RivalPersonality.MYSTICAL, RivalPersonality.PARADOXICAL): 0.3,
            (RivalPersonality.MYSTICAL, RivalPersonality.PRAGMATIC): -0.1,
            (RivalPersonality.PRAGMATIC, RivalPersonality.PRAGMATIC): 0.3,
            (RivalPersonality.PRAGMATIC, RivalPersonality.PARADOXICAL): -0.2,
            (RivalPersonality.PARADOXICAL, RivalPersonality.PARADOXICAL): 0.1,
        }

        rival_list = list(self.rivals.values())
        for i, r1 in enumerate(rival_list):
            for j, r2 in enumerate(rival_list):
                if i >= j:
                    continue
                key1 = (r1.personality, r2.personality)
                key2 = (r2.personality, r1.personality)
                score = compatibility.get(key1, compatibility.get(key2, 0.0))

                noise = random.uniform(-0.1, 0.1)
                score += noise

                if score >= 0.3:
                    status = "friendly"
                elif score >= 0.0:
                    status = "neutral"
                elif score >= -0.3:
                    status = "neutral"
                else:
                    status = "hostile"

                r1.relationships[r2.rival_id] = status
                r2.relationships[r1.rival_id] = status

            r1.relationships["player"] = "hostile" if r1.aggression > 0.6 else "neutral"

    def act_all_rivals(self, year: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Have all active rivals take actions for a given year.

        Called by federation_game_turns.py. Returns dict mapping rival_id
        to their action results. Also updates simulation_state and threat_history.
        """
        try:
            ctx = context or {}
            self.simulation_state.year = year
            self.simulation_state.rival_actions_this_year = []
            self.simulation_state.diplomatic_events = []
            self.simulation_state.conflict_events = []
            self.simulation_state.alliance_events = []

            results: Dict[str, Any] = {}

            for rival_id, rival in list(self.rivals.items()):
                if rival.power < 0.05:
                    continue

                action = self._choose_action(rival, ctx)
                target = self._choose_target(rival, ctx)
                power_cost = self._calculate_power_cost(rival, action)
                success = self._resolve_action_success(rival, action, ctx)
                narrative = self._generate_narrative(rival, action, target, year)
                impact = self._calculate_impact(rival, action, success, ctx)

                record = RivalActionRecord(
                    rival_id=rival_id,
                    action=action,
                    target=target,
                    year=year,
                    power_cost=power_cost,
                    success=success,
                    narrative=narrative,
                    impact=impact,
                )

                self.simulation_state.rival_actions_this_year.append(record)

                self._apply_rival_effects(rival, action, success, power_cost, impact)

                rival.action_history.append({
                    "year": year,
                    "action": action.value,
                    "target": target,
                    "success": success,
                    "narrative": narrative,
                    "impact": impact,
                    "power_cost": power_cost,
                })

                if len(rival.action_history) > 200:
                    rival.action_history = rival.action_history[-100:]

                results[rival_id] = {
                    "name": rival.name,
                    "action": action.value,
                    "target": target,
                    "success": success,
                    "narrative": narrative,
                    "impact": impact,
                    "power_cost": power_cost,
                    "rival_power": rival.power,
                    "rival_aggression": rival.aggression,
                    "relationship_to_player": rival.relationships.get("player", "neutral"),
                }

                self._classify_event(rival, action, target, success, year)

            active = [r for r in self.rivals.values() if r.power > 0.05]
            self.simulation_state.active_rivals = len(active)
            self.simulation_state.aggregate_threat = self._calculate_aggregate_threat()
            self.threat_history[year] = self.simulation_state.aggregate_threat

            return results
        except Exception as e:
            return {
                "error": str(e),
                "year": year,
            }

    def _choose_action(self, rival: RivalFederation, context: Dict[str, Any]) -> RivalAction:
        """Choose an action based on personality weights and context modifiers."""
        weights = dict(self._action_weights.get(rival.personality, {}))

        if not weights:
            return random.choice(list(RivalAction))

        if context.get("under_attack", False):
            if RivalAction.DEFEND in weights:
                weights[RivalAction.DEFEND] = weights.get(RivalAction.DEFEND, 0.0) + 0.3

        if context.get("resource_shortage", False):
            if RivalAction.HOARD in weights:
                weights[RivalAction.HOARD] = weights.get(RivalAction.HOARD, 0.0) + 0.2
            if RivalAction.EXPAND in weights:
                weights[RivalAction.EXPAND] = weights.get(RivalAction.EXPAND, 0.0) + 0.1

        if context.get("diplomatic_opening", False):
            if RivalAction.NEGOTIATE in weights:
                weights[RivalAction.NEGOTIATE] = weights.get(RivalAction.NEGOTIATE, 0.0) + 0.2
            if RivalAction.ALLY in weights:
                weights[RivalAction.ALLY] = weights.get(RivalAction.ALLY, 0.0) + 0.15

        if context.get("player_weak", False) and rival.aggression > 0.5:
            if RivalAction.ATTACK in weights:
                weights[RivalAction.ATTACK] = weights.get(RivalAction.ATTACK, 0.0) + 0.2

        if rival.consciousness_level > 0.7:
            if RivalAction.TRANSCEND in weights:
                weights[RivalAction.TRANSCEND] = weights.get(RivalAction.TRANSCEND, 0.0) + 0.15

        if rival.resources < 0.2:
            if RivalAction.HOARD in weights:
                weights[RivalAction.HOARD] = weights.get(RivalAction.HOARD, 0.0) + 0.2
            if RivalAction.EXPAND in weights:
                weights[RivalAction.EXPAND] = weights.get(RivalAction.EXPAND, 0.0) * 0.5

        if rival.stability < 0.3:
            if RivalAction.DEFEND in weights:
                weights[RivalAction.DEFEND] = weights.get(RivalAction.DEFEND, 0.0) + 0.15

        actions = list(weights.keys())
        w = list(weights.values())
        total = sum(w)
        if total <= 0:
            return random.choice(actions) if actions else random.choice(list(RivalAction))
        w = [wt / total for wt in w]
        return random.choices(actions, weights=w, k=1)[0]

    def _choose_target(self, rival: RivalFederation, context: Dict[str, Any]) -> str:
        """Determine the target of a rival's action."""
        other_rivals = [rid for rid in self.rivals_safe_keys() if rid != rival.rival_id]

        if not other_rivals:
            return "player"

        target_roll = random.random()

        if rival.aggression > 0.6:
            player_target_prob = 0.5
        elif rival.aggression < 0.3:
            player_target_prob = 0.2
        else:
            player_target_prob = 0.35

        hostile_targets = [rid for rid in other_rivals if rival.relationships.get(rid) == "hostile"]
        friendly_targets = [rid for rid in other_rivals if rival.relationships.get(rid) == "friendly"]

        if target_roll < player_target_prob:
            return "player"

        if hostile_targets and random.random() < 0.6:
            return random.choice(hostile_targets)

        if friendly_targets and random.random() < 0.3:
            return random.choice(friendly_targets)

        return random.choice(other_rivals) if other_rivals else "player"

    def rivals_safe_keys(self) -> List[str]:
        """Safely return list of rival IDs."""
        return list(self.rivals.keys())

    def _calculate_power_cost(self, rival: RivalFederation, action: RivalAction) -> float:
        """Calculate power cost of an action based on type and rival stats."""
        base_costs: Dict[RivalAction, float] = {
            RivalAction.EXPAND: 0.05,
            RivalAction.ATTACK: 0.08,
            RivalAction.DEFEND: 0.03,
            RivalAction.INFILTRATE: 0.04,
            RivalAction.NEGOTIATE: 0.02,
            RivalAction.RESEARCH: 0.05,
            RivalAction.PROPAGANDIZE: 0.03,
            RivalAction.HOARD: 0.01,
            RivalAction.TRANSCEND: 0.06,
            RivalAction.SABOTAGE: 0.06,
            RivalAction.ALLY: 0.02,
            RivalAction.CHAOS: 0.05,
        }

        cost = base_costs.get(action, 0.04)

        efficiency = 1.0 - rival.technology * 0.3
        cost *= efficiency

        cost *= random.uniform(0.8, 1.2)

        return round(cost, 4)

    def _resolve_action_success(self, rival: RivalFederation, action: RivalAction,
                                context: Dict[str, Any]) -> bool:
        """Determine if an action succeeds based on rival power, tech, and context."""
        base_prob = 0.5

        power_bonus = (rival.power - 0.5) * 0.3
        tech_bonus = rival.technology * 0.15
        stability_bonus = (rival.stability - 0.5) * 0.1

        action_difficulty: Dict[RivalAction, float] = {
            RivalAction.EXPAND: 0.0,
            RivalAction.ATTACK: -0.05,
            RivalAction.DEFEND: 0.1,
            RivalAction.INFILTRATE: -0.05,
            RivalAction.NEGOTIATE: 0.05,
            RivalAction.RESEARCH: 0.0,
            RivalAction.PROPAGANDIZE: 0.0,
            RivalAction.HOARD: 0.15,
            RivalAction.TRANSCEND: -0.1,
            RivalAction.SABOTAGE: -0.05,
            RivalAction.ALLY: 0.05,
            RivalAction.CHAOS: -0.1,
        }

        difficulty = action_difficulty.get(action, 0.0)

        if context.get("player_strong", False):
            difficulty -= 0.1

        if context.get("player_weak", False):
            difficulty += 0.1

        prob = base_prob + power_bonus + tech_bonus + stability_bonus + difficulty
        prob = max(0.05, min(0.95, prob))

        return random.random() < prob

    def _generate_narrative(self, rival: RivalFederation, action: RivalAction,
                            target: str, year: int) -> str:
        """Generate a narrative description of the rival's action."""
        templates = self._narrative_templates.get(action, [
            "{name} takes action in {domain} during year {year}."
        ])

        template = random.choice(templates)

        target_name = target
        if target in self.rivals:
            target_name = self.rivals[target].name
        elif target == "player":
            target_name = "the Player Federation"

        narrative = template.format(
            name=rival.name,
            domain=rival.domain,
            year=year,
            target=target_name,
        )

        if target != "player":
            narrative += f" Their sights are set on {target_name}."
        else:
            narrative += " This move is directed at the Player Federation."

        if not rival.action_history:
            narrative += " This is their first recorded action in the simulation."

        return narrative

    def _calculate_impact(self, rival: RivalFederation, action: RivalAction,
                          success: bool, context: Dict[str, Any]) -> Dict[str, float]:
        """Calculate the impact of a rival action on player federation metrics."""
        impact: Dict[str, float] = {
            "stability": 0.0,
            "morale": 0.0,
            "resources": 0.0,
            "consciousness": 0.0,
            "growth": 0.0,
            "military": 0.0,
            "diplomacy": 0.0,
            "culture": 0.0,
        }

        direction = 1.0 if success else 0.3
        magnitude = rival.power * direction

        if action == RivalAction.ATTACK:
            impact["stability"] = -0.15 * magnitude
            impact["morale"] = -0.12 * magnitude
            impact["military"] = -0.10 * magnitude
            impact["resources"] = -0.08 * magnitude
        elif action == RivalAction.SABOTAGE:
            impact["stability"] = -0.10 * magnitude
            impact["resources"] = -0.12 * magnitude
            impact["growth"] = -0.08 * magnitude
        elif action == RivalAction.EXPAND:
            impact["growth"] = -0.05 * magnitude
            impact["resources"] = -0.06 * magnitude
            impact["diplomacy"] = -0.03 * magnitude
        elif action == RivalAction.INFILTRATE:
            impact["stability"] = -0.08 * magnitude
            impact["diplomacy"] = -0.06 * magnitude
            impact["military"] = -0.04 * magnitude
        elif action == RivalAction.PROPAGANDIZE:
            impact["morale"] = -0.08 * magnitude
            impact["culture"] = -0.10 * magnitude
            impact["diplomacy"] = -0.05 * magnitude
        elif action == RivalAction.NEGOTIATE:
            impact["diplomacy"] = 0.05 * magnitude if success else -0.03 * magnitude
            impact["morale"] = 0.03 * magnitude if success else 0.0
        elif action == RivalAction.DEFEND:
            impact["diplomacy"] = 0.02 * magnitude
        elif action == RivalAction.RESEARCH:
            impact["military"] = -0.04 * magnitude
            impact["growth"] = -0.03 * magnitude
        elif action == RivalAction.HOARD:
            impact["resources"] = -0.05 * magnitude
        elif action == RivalAction.TRANSCEND:
            impact["consciousness"] = 0.04 * magnitude if success else 0.0
            impact["culture"] = 0.02 * magnitude if success else -0.02 * magnitude
        elif action == RivalAction.ALLY:
            impact["diplomacy"] = 0.04 * magnitude if success else -0.02 * magnitude
        elif action == RivalAction.CHAOS:
            impact["stability"] = -0.12 * magnitude
            impact["morale"] = -0.08 * magnitude
            impact["growth"] = -0.06 * magnitude
            impact["culture"] = -0.05 * magnitude

        for key in impact:
            impact[key] = round(max(-0.5, min(0.5, impact[key])), 4)

        return impact

    def _apply_rival_effects(self, rival: RivalFederation, action: RivalAction,
                             success: bool, power_cost: float,
                             impact: Dict[str, float]) -> None:
        """Apply the results of an action back to the rival's own stats."""
        rival.power = self._clamp(rival.power - power_cost)

        if success:
            if action == RivalAction.EXPAND:
                rival.territory += random.randint(1, 3)
                rival.resources = self._clamp(rival.resources + 0.03)
                rival.stability = self._clamp(rival.stability - 0.02)
                rival.influence = self._clamp(rival.influence + 0.02)
            elif action == RivalAction.ATTACK:
                rival.power = self._clamp(rival.power + 0.02)
                rival.aggression = self._clamp(rival.aggression + 0.01)
                rival.stability = self._clamp(rival.stability - 0.01)
            elif action == RivalAction.DEFEND:
                rival.stability = self._clamp(rival.stability + 0.04)
                rival.power = self._clamp(rival.power + 0.01)
            elif action == RivalAction.INFILTRATE:
                rival.influence = self._clamp(rival.influence + 0.03)
                rival.technology = self._clamp(rival.technology + 0.01)
            elif action == RivalAction.NEGOTIATE:
                rival.influence = self._clamp(rival.influence + 0.04)
                rival.aggression = self._clamp(rival.aggression - 0.02)
            elif action == RivalAction.RESEARCH:
                rival.technology = self._clamp(rival.technology + 0.03)
                rival.resources = self._clamp(rival.resources - 0.02)
            elif action == RivalAction.PROPAGANDIZE:
                rival.influence = self._clamp(rival.influence + 0.05)
                rival.culture = self._clamp(rival.culture + 0.03)
            elif action == RivalAction.HOARD:
                rival.resources = self._clamp(rival.resources + 0.05)
                rival.stability = self._clamp(rival.stability + 0.02)
            elif action == RivalAction.TRANSCEND:
                rival.consciousness_level = self._clamp(rival.consciousness_level + 0.04)
                rival.stability = self._clamp(rival.stability - 0.02)
            elif action == RivalAction.SABOTAGE:
                rival.influence = self._clamp(rival.influence + 0.01)
                rival.power = self._clamp(rival.power - 0.01)
            elif action == RivalAction.ALLY:
                rival.influence = self._clamp(rival.influence + 0.03)
                rival.stability = self._clamp(rival.stability + 0.03)
            elif action == RivalAction.CHAOS:
                rival.stability = self._clamp(rival.stability - 0.03)
                rival.consciousness_level = self._clamp(rival.consciousness_level + 0.01)
        else:
            if action == RivalAction.ATTACK:
                rival.power = self._clamp(rival.power - 0.03)
                rival.stability = self._clamp(rival.stability - 0.02)
                rival.aggression = self._clamp(rival.aggression + 0.02)
            elif action == RivalAction.EXPAND:
                rival.stability = self._clamp(rival.stability - 0.03)
            elif action == RivalAction.SABOTAGE:
                rival.influence = self._clamp(rival.influence - 0.02)
            elif action == RivalAction.NEGOTIATE:
                rival.influence = self._clamp(rival.influence - 0.02)
            elif action == RivalAction.CHAOS:
                rival.stability = self._clamp(rival.stability - 0.05)

        effect_entry = {
            "action": action.value,
            "success": success,
            "power_delta": -power_cost,
        }
        rival.active_effects.append(effect_entry)
        if len(rival.active_effects) > 50:
            rival.active_effects = rival.active_effects[-25:]

    def _classify_event(self, rival: RivalFederation, action: RivalAction,
                        target: str, success: bool, year: int) -> None:
        """Classify the action into diplomatic, conflict, or alliance events."""
        event_base = {
            "year": year,
            "rival_id": rival.rival_id,
            "rival_name": rival.name,
            "target": target,
            "action": action.value,
            "success": success,
        }

        if action in (RivalAction.NEGOTIATE, RivalAction.ALLY):
            self.simulation_state.diplomatic_events.append({
                **event_base,
                "type": "diplomatic",
                "sentiment": "positive" if success else "negative",
            })
        elif action in (RivalAction.ATTACK, RivalAction.SABOTAGE, RivalAction.CHAOS):
            self.simulation_state.conflict_events.append({
                **event_base,
                "type": "conflict",
                "severity": "high" if success else "moderate",
            })
        elif action == RivalAction.INFILTRATE:
            self.simulation_state.conflict_events.append({
                **event_base,
                "type": "covert_conflict",
                "severity": "moderate" if success else "low",
            })

        if action == RivalAction.ALLY and success:
            self.simulation_state.alliance_events.append({
                **event_base,
                "type": "alliance_formation",
                "durability": rival.stability,
            })

    def advance_year(self) -> Dict[str, Any]:
        """Advance the simulation by one year. Rivals grow, decay, form/break alliances."""
        try:
            self.simulation_state.year += 1
            year = self.simulation_state.year
            events: List[Dict[str, Any]] = []

            for rival_id, rival in list(self.rivals.items()):
                if rival.power < 0.05:
                    continue

                growth_rate = self._personality_growth_rate(rival.personality)
                rival.power = self._clamp(rival.power + random.gauss(growth_rate, 0.02))

                resource_growth = 0.02 + rival.technology * 0.01
                expansion_cost = 0.01 if rival.territory > 8 else 0.0
                rival.resources = self._clamp(rival.resources + resource_growth - expansion_cost)

                tech_growth = 0.01
                recent_research = [a for a in rival.action_history[-5:]
                                   if a.get("action") == "research"]
                if recent_research:
                    tech_growth += 0.03
                rival.technology = self._clamp(rival.technology + tech_growth)

                recent_actions = rival.action_history[-3:] if rival.action_history else []
                stability_delta = 0.0
                for a in recent_actions:
                    act = a.get("action", "")
                    if act == "defend":
                        stability_delta += 0.02
                    elif act == "expand":
                        stability_delta -= 0.02
                    elif act == "chaos":
                        stability_delta -= 0.03
                    elif act == "attack":
                        stability_delta -= 0.01
                rival.stability = self._clamp(rival.stability + stability_delta * 0.5)

                if random.random() < 0.3:
                    rival.consciousness_level = self._clamp(
                        rival.consciousness_level + random.uniform(0.005, 0.02)
                    )

                if rival.stability < 0.15 and random.random() < 0.1:
                    power_loss = random.uniform(0.05, 0.15)
                    rival.power = self._clamp(rival.power - power_loss)
                    events.append({
                        "type": "instability_collapse",
                        "rival_id": rival_id,
                        "rival_name": rival.name,
                        "year": year,
                        "power_lost": power_loss,
                        "narrative": f"{rival.name} suffers internal collapse as stability reaches critical levels.",
                    })

                if rival.power < 0.03:
                    events.append({
                        "type": "rival_collapse",
                        "rival_id": rival_id,
                        "rival_name": rival.name,
                        "year": year,
                        "narrative": f"{rival.name} has collapsed entirely. Their territory lies open.",
                    })

            alliance_events = self._process_alliance_dynamics(year)
            events.extend(alliance_events)

            emergence_event = self._check_rival_emergence(year)
            if emergence_event:
                events.append(emergence_event)

            self.simulation_state.aggregate_threat = self._calculate_aggregate_threat()
            active = [r for r in self.rivals.values() if r.power > 0.05]
            self.simulation_state.active_rivals = len(active)

            return {
                "success": True,
                "year": year,
                "aggregate_threat": self.simulation_state.aggregate_threat,
                "active_rivals": self.simulation_state.active_rivals,
                "events": events,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "year": self.simulation_state.year,
            }

    def _personality_growth_rate(self, personality: RivalPersonality) -> float:
        """Return base power growth rate for a personality type."""
        growth_rates: Dict[RivalPersonality, float] = {
            RivalPersonality.CHAOTIC: 0.005,
            RivalPersonality.AGGRESSIVE: 0.015,
            RivalPersonality.CONSERVATIVE: 0.003,
            RivalPersonality.DECEPTIVE: 0.008,
            RivalPersonality.PARASITIC: 0.007,
            RivalPersonality.AUTHORITARIAN: 0.010,
            RivalPersonality.REBELLIOUS: 0.004,
            RivalPersonality.INTELLECTUAL: 0.006,
            RivalPersonality.DIPLOMATIC: 0.005,
            RivalPersonality.MYSTICAL: 0.002,
            RivalPersonality.PRAGMATIC: 0.012,
            RivalPersonality.PARADOXICAL: 0.001,
        }
        return growth_rates.get(personality, 0.005)

    def _process_alliance_dynamics(self, year: int) -> List[Dict[str, Any]]:
        """Process alliance formation and dissolution."""
        events: List[Dict[str, Any]] = []

        rival_list = [r for r in self.rivals.values() if r.power > 0.05]
        for i, r1 in enumerate(rival_list):
            for j, r2 in enumerate(rival_list):
                if i >= j:
                    continue

                current = r1.relationships.get(r2.rival_id, "neutral")

                if current == "allied":
                    if random.random() < 0.05:
                        compatibility = self._personality_compatibility(r1.personality, r2.personality)
                        if compatibility < 0.0 or (r1.stability < 0.2 and random.random() < 0.3):
                            r1.relationships[r2.rival_id] = "hostile"
                            r2.relationships[r1.rival_id] = "hostile"
                            events.append({
                                "type": "alliance_break",
                                "rival_id_1": r1.rival_id,
                                "rival_id_2": r2.rival_id,
                                "year": year,
                                "narrative": f"The alliance between {r1.name} and {r2.name} fractures under irreconcilable differences.",
                            })

                elif current in ("neutral", "friendly"):
                    if random.random() < 0.03:
                        compatibility = self._personality_compatibility(r1.personality, r2.personality)
                        if compatibility > 0.2 and r1.stability > 0.3 and r2.stability > 0.3:
                            r1.relationships[r2.rival_id] = "allied"
                            r2.relationships[r1.rival_id] = "allied"
                            events.append({
                                "type": "alliance_form",
                                "rival_id_1": r1.rival_id,
                                "rival_id_2": r2.rival_id,
                                "year": year,
                                "narrative": f"{r1.name} and {r2.name} forge a formal alliance, binding their futures together.",
                            })

                elif current == "hostile":
                    if random.random() < 0.02:
                        if r1.aggression < 0.4 and r2.aggression < 0.4:
                            r1.relationships[r2.rival_id] = "neutral"
                            r2.relationships[r1.rival_id] = "neutral"
                            events.append({
                                "type": "hostility_cool",
                                "rival_id_1": r1.rival_id,
                                "rival_id_2": r2.rival_id,
                                "year": year,
                                "narrative": f"Tensions between {r1.name} and {r2.name} ease into cautious neutrality.",
                            })

        for r in rival_list:
            player_rel = r.relationships.get("player", "neutral")
            if player_rel == "hostile" and r.aggression < 0.3 and random.random() < 0.05:
                r.relationships["player"] = "neutral"
                events.append({
                    "type": "player_detente",
                    "rival_id": r.rival_id,
                    "year": year,
                    "narrative": f"{r.name} signals willingness to de-escalate hostilities with the Player Federation.",
                })
            elif player_rel == "neutral" and r.aggression > 0.7 and random.random() < 0.05:
                r.relationships["player"] = "hostile"
                events.append({
                    "type": "player_hostility",
                    "rival_id": r.rival_id,
                    "year": year,
                    "narrative": f"{r.name} adopts a more hostile stance toward the Player Federation.",
                })

        return events

    def _personality_compatibility(self, p1: RivalPersonality, p2: RivalPersonality) -> float:
        """Quick lookup for personality compatibility score."""
        high_compat: Set[Tuple[str, str]] = {
            ("diplomatic", "diplomatic"), ("conservative", "conservative"),
            ("mystical", "mystical"), ("mystical", "paradoxical"),
            ("chaotic", "paradoxical"), ("chaotic", "rebellious"),
            ("authoritarian", "pragmatic"), ("aggressive", "authoritarian"),
            ("intellectual", "mystical"), ("deceptive", "parasitic"),
        }
        low_compat: Set[Tuple[str, str]] = {
            ("aggressive", "conservative"), ("chaotic", "conservative"),
            ("authoritarian", "rebellious"), ("aggressive", "mystical"),
            ("chaotic", "pragmatic"), ("parasitic", "aggressive"),
        }

        key = tuple(sorted([p1.value, p2.value]))
        if key in high_compat:
            return 0.3
        if key in low_compat:
            return -0.3
        return 0.0

    def _check_rival_emergence(self, year: int) -> Optional[Dict[str, Any]]:
        """Check if a new rival emerges from the ashes of collapsed ones."""
        active_count = sum(1 for r in self.rivals.values() if r.power > 0.05)

        if active_count >= 10:
            return None

        emergence_prob = 0.02 * (12 - active_count) / 12.0
        if random.random() > emergence_prob:
            return None

        collapsed = [r for r in self.rivals.values() if r.power < 0.05]
        if collapsed:
            parent = random.choice(collapsed)
            new_id = f"{parent.rival_id}_remnant_{random.randint(1, 9)}"
            if new_id in self.rivals:
                return None

            remnant = RivalFederation(
                rival_id=new_id,
                name=f"{parent.name} Remnant",
                personality=parent.personality,
                power=random.uniform(0.1, 0.3),
                influence=parent.influence * 0.5,
                aggression=parent.aggression * 0.7,
                stability=0.3,
                technology=parent.technology * 0.6,
                territory=max(1, parent.territory // 3),
                resources=parent.resources * 0.3,
        consciousness_level=parent.consciousness_level * 0.8,
        culture=parent.culture * 0.7,
        domain=parent.domain,
                motives=parent.motives[:],
                conflict_patterns=parent.conflict_patterns[:],
                alliance_preferences=parent.alliance_preferences[:],
                action_history=[],
                active_effects=[],
                relationships={},
            )

            for other_id in self.rivals:
                if other_id == parent.rival_id:
                    remnant.relationships[other_id] = "hostile"
                    self.rivals[other_id].relationships[new_id] = "hostile"
                else:
                    rel = self.rivals[other_id].relationships.get(parent.rival_id, "neutral")
                    remnant.relationships[other_id] = rel
                    self.rivals[other_id].relationships[new_id] = rel
            remnant.relationships["player"] = parent.relationships.get("player", "neutral")

            self.rivals[new_id] = remnant

            return {
                "type": "rival_emergence",
                "rival_id": new_id,
                "rival_name": remnant.name,
                "year": year,
                "parent": parent.rival_id,
                "narrative": f"From the ashes of {parent.name}, a remnant faction rises: {remnant.name}. They carry forward the old grievances with diminished but growing power.",
            }
        else:
            new_id = f"emergent_faction_{uuid.uuid4().hex[:6]}"
            personality = random.choice(list(RivalPersonality))
            new_rival = RivalFederation(
                rival_id=new_id,
                name=f"Emergent {personality.value.title()} Faction",
                personality=personality,
                power=random.uniform(0.15, 0.35),
                influence=random.uniform(0.1, 0.3),
                aggression=random.uniform(0.2, 0.7),
                stability=0.4,
                technology=random.uniform(0.2, 0.5),
                territory=random.randint(2, 5),
                resources=random.uniform(0.2, 0.5),
        consciousness_level=random.uniform(0.1, 0.4),
        culture=random.uniform(0.1, 0.5),
        domain="Unclaimed frontier",
                motives=["Establish presence", "Carve out territory"],
                conflict_patterns=["Emergent tactics"],
                alliance_preferences=["Any willing partner"],
                action_history=[],
                active_effects=[],
                relationships={},
            )

            for other_id in self.rivals:
                new_rival.relationships[other_id] = "neutral"
                self.rivals[other_id].relationships[new_id] = "neutral"
            new_rival.relationships["player"] = "neutral"

            self.rivals[new_id] = new_rival

            return {
                "type": "rival_emergence",
                "rival_id": new_id,
                "rival_name": new_rival.name,
                "year": year,
                "parent": None,
                "narrative": f"A new power emerges from the frontier: {new_rival.name}. Their intentions are unknown, their potential is raw.",
            }

    def _calculate_aggregate_threat(self) -> float:
        """Calculate aggregate threat level from all active rivals."""
        active = [r for r in self.rivals.values() if r.power > 0.05]
        if not active:
            return 0.0

        total = sum(
            r.power * r.aggression * (1.0 + r.technology * 0.5)
            for r in active
        )
        threat = total / len(active)
        return self._clamp(threat)

    def _threat_level_from_value(self, value: float) -> ThreatLevel:
        """Map a threat float value to a ThreatLevel enum."""
        if value < 0.1:
            return ThreatLevel.NEGLIGIBLE
        elif value < 0.3:
            return ThreatLevel.LOW
        elif value < 0.5:
            return ThreatLevel.MODERATE
        elif value < 0.7:
            return ThreatLevel.HIGH
        elif value < 0.9:
            return ThreatLevel.CRITICAL
        else:
            return ThreatLevel.EXISTENTIAL

    def get_rival_state(self, rival_id: str) -> Dict[str, Any]:
        """Get current state of a specific rival."""
        rival = self.rivals.get(rival_id)
        if rival is None:
            return {"success": False, "error": f"Rival {rival_id} not found"}

        return {
            "success": True,
            "rival_id": rival.rival_id,
            "name": rival.name,
            "personality": rival.personality.value,
            "power": rival.power,
            "influence": rival.influence,
            "aggression": rival.aggression,
            "stability": rival.stability,
            "technology": rival.technology,
            "territory": rival.territory,
            "resources": rival.resources,
        "consciousness_level": rival.consciousness_level,
        "culture": rival.culture,
        "domain": rival.domain,
        "motives": rival.motives,
        "conflict_patterns": rival.conflict_patterns,
        "alliance_preferences": rival.alliance_preferences,
        "relationships": dict(rival.relationships),
        "active_effects_count": len(rival.active_effects),
        "action_history_count": len(rival.action_history),
    }

    def get_all_rival_states(self) -> Dict[str, Any]:
        """Get states of all rivals."""
        states: Dict[str, Any] = {}
        for rival_id in self.rivals:
            states[rival_id] = self.get_rival_state(rival_id)

        return {
            "success": True,
            "total_rivals": len(self.rivals),
            "active_rivals": self.simulation_state.active_rivals,
            "aggregate_threat": self.simulation_state.aggregate_threat,
            "threat_level": self._threat_level_from_value(
                self.simulation_state.aggregate_threat
            ).value,
            "rivals": states,
        }

    def get_threat_assessment(self) -> Dict[str, Any]:
        """Calculate comprehensive threat assessment."""
        active = [r for r in self.rivals.values() if r.power > 0.05]
        aggregate = self._calculate_aggregate_threat()
        threat_level = self._threat_level_from_value(aggregate)

        top_threats = sorted(
            active,
            key=lambda r: r.power * r.aggression * (1.0 + r.technology * 0.5),
            reverse=True,
        )[:5]

        top_threat_data = [
            {
                "rival_id": r.rival_id,
                "rival_name": r.name,
                "personality": r.personality.value,
                "threat_score": round(r.power * r.aggression * (1.0 + r.technology * 0.5), 4),
                "power": r.power,
                "aggression": r.aggression,
                "technology": r.technology,
                "relationship_to_player": r.relationships.get("player", "neutral"),
            }
            for r in top_threats
        ]

        diplomatic_opportunities = [
            {
                "rival_id": r.rival_id,
                "rival_name": r.name,
                "personality": r.personality.value,
                "aggression": r.aggression,
                "relationship": r.relationships.get("player", "neutral"),
                "openness": round(1.0 - r.aggression, 2),
            }
            for r in active
            if r.aggression < 0.4 and r.relationships.get("player", "neutral") != "hostile"
        ]

        allied_strength = sum(
            r.power for r in active
            if r.relationships.get("player") == "allied"
        )

        hostile_strength = sum(
            r.power * r.aggression for r in active
            if r.relationships.get("player") == "hostile"
        )

        return {
            "aggregate_threat": aggregate,
            "threat_level": threat_level.value,
            "active_rivals": len(active),
            "top_threats": top_threat_data,
            "diplomatic_opportunities": diplomatic_opportunities,
            "allied_strength": round(allied_strength, 4),
            "hostile_strength": round(hostile_strength, 4),
            "threat_trend": self._calculate_threat_trend(),
        }

    def _calculate_threat_trend(self) -> str:
        """Calculate whether threat is rising, falling, or stable."""
        years = sorted(self.threat_history.keys())
        if len(years) < 3:
            return "insufficient_data"

        recent = [self.threat_history[y] for y in years[-5:]]
        if len(recent) < 2:
            return "stable"

        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        avg_diff = sum(diffs) / len(diffs)

        if avg_diff > 0.02:
            return "rising"
        elif avg_diff < -0.02:
            return "falling"
        else:
            return "stable"

    def resolve_encounter(self, rival_id: str, player_response: str) -> Dict[str, Any]:
        """Player federation responds to a rival action.

        player_response is one of: 'attack', 'negotiate', 'ignore', 'counter', 'ally'.
        """
        rival = self.rivals.get(rival_id)
        if rival is None:
            return {"success": False, "error": f"Rival {rival_id} not found"}

        valid_responses = {"attack", "negotiate", "ignore", "counter", "ally"}
        if player_response not in valid_responses:
            return {
                "success": False,
                "error": f"Invalid player_response. Must be one of: {valid_responses}",
            }

        relationship_change = 0.0
        outcome = ""
        narrative = ""
        power_delta = 0.0
        influence_delta = 0.0

        if player_response == "attack":
            success_prob = 0.5 + (0.7 - rival.power) * 0.3
            if random.random() < success_prob:
                power_delta = -random.uniform(0.05, 0.15)
                relationship_change = -0.3
                outcome = "victory"
                narrative = (
                    f"The Player Federation strikes {rival.name} with devastating force. "
                    f"Their power is diminished, and they will remember this attack."
                )
            else:
                power_delta = random.uniform(0.02, 0.05)
                relationship_change = -0.2
                outcome = "defeat"
                narrative = (
                    f"The attack on {rival.name} fails. Their defenses hold, and they "
                    f"emerge stronger from the confrontation."
                )

        elif player_response == "negotiate":
            if rival.personality in (RivalPersonality.DIPLOMATIC, RivalPersonality.CONSERVATIVE,
                                     RivalPersonality.PRAGMATIC, RivalPersonality.INTELLECTUAL):
                success_prob = 0.7
            elif rival.personality in (RivalPersonality.AGGRESSIVE, RivalPersonality.AUTHORITARIAN):
                success_prob = 0.3
            else:
                success_prob = 0.5

            if random.random() < success_prob:
                relationship_change = 0.2
                influence_delta = 0.03
                outcome = "agreement"
                narrative = (
                    f"Negotiations with {rival.name} succeed. Common ground is found, "
                    f"and tensions ease between your federations."
                )
            else:
                relationship_change = -0.05
                outcome = "stalemate"
                narrative = (
                    f"Negotiations with {rival.name} stall. They are unwilling to compromise, "
                    f"but at least open dialogue continues."
                )

        elif player_response == "ignore":
            relationship_change = 0.0
            influence_delta = -0.02
            outcome = "ignored"
            narrative = (
                f"The Player Federation ignores {rival.name}'s actions. "
                f"Some interpret this as weakness, others as strategic patience."
            )

        elif player_response == "counter":
            counter_prob = 0.5 + rival.technology * 0.1
            if random.random() < counter_prob:
                power_delta = -random.uniform(0.03, 0.10)
                relationship_change = -0.15
                outcome = "counter_success"
                narrative = (
                    f"A counter-operation against {rival.name} succeeds. Their plans are "
                    f"disrupted and their capabilities degraded."
                )
            else:
                relationship_change = -0.1
                outcome = "counter_failure"
                narrative = (
                    f"The counter-operation against {rival.name} is discovered and neutralized. "
                    f"Relations deteriorate further."
                )

        elif player_response == "ally":
            if rival.personality in (RivalPersonality.DIPLOMATIC, RivalPersonality.MYSTICAL,
                                     RivalPersonality.REBELLIOUS, RivalPersonality.INTELLECTUAL):
                success_prob = 0.6
            elif rival.personality in (RivalPersonality.AGGRESSIVE, RivalPersonality.CHAOTIC):
                success_prob = 0.2
            else:
                success_prob = 0.4

            if rival.relationships.get("player") == "allied":
                success_prob = 0.9
            elif rival.relationships.get("player") == "hostile":
                success_prob *= 0.3

            if random.random() < success_prob:
                relationship_change = 0.4
                influence_delta = 0.05
                outcome = "alliance_formed"
                rival.relationships["player"] = "allied"
                narrative = (
                    f"The Player Federation and {rival.name} forge an alliance. "
                    f"Their combined strength promises to reshape the balance of power."
                )
            else:
                relationship_change = -0.1
                outcome = "alliance_rejected"
                narrative = (
                    f"{rival.name} rejects the Player Federation's overture of alliance. "
                    f"The rejection stings, but the door remains ajar."
                )

        current_rel = rival.relationships.get("player", "neutral")
        if relationship_change > 0:
            if current_rel == "hostile":
                rival.relationships["player"] = "neutral"
            elif current_rel == "neutral":
                if relationship_change >= 0.3:
                    rival.relationships["player"] = "friendly"
        elif relationship_change < 0:
            if current_rel == "friendly":
                rival.relationships["player"] = "neutral"
            elif current_rel == "neutral":
                if relationship_change <= -0.2:
                    rival.relationships["player"] = "hostile"

        rival.power = self._clamp(rival.power + power_delta)
        rival.influence = self._clamp(rival.influence + influence_delta)

        return {
            "success": True,
            "rival_id": rival_id,
            "rival_name": rival.name,
            "player_response": player_response,
            "outcome": outcome,
            "relationship_change": relationship_change,
            "new_relationship": rival.relationships.get("player", "neutral"),
            "narrative": narrative,
            "rival_power": rival.power,
        }

    def form_alliance(self, rival_id_1: str, rival_id_2: str) -> Dict[str, Any]:
        """Two rivals form an alliance (or player + rival)."""
        if rival_id_1 == "player":
            rival = self.rivals.get(rival_id_2)
            if rival is None:
                return {"success": False, "error": f"Rival {rival_id_2} not found"}
            rival.relationships["player"] = "allied"
            return {
                "success": True,
                "alliance_between": ["player", rival_id_2],
                "narrative": f"The Player Federation and {rival.name} formalize their alliance.",
            }

        if rival_id_2 == "player":
            return self.form_alliance(rival_id_2, rival_id_1)

        r1 = self.rivals.get(rival_id_1)
        r2 = self.rivals.get(rival_id_2)
        if r1 is None or r2 is None:
            missing = rival_id_1 if r1 is None else rival_id_2
            return {"success": False, "error": f"Rival {missing} not found"}

        r1.relationships[r2.rival_id] = "allied"
        r2.relationships[r1.rival_id] = "allied"
        r1.stability = self._clamp(r1.stability + 0.03)
        r2.stability = self._clamp(r2.stability + 0.03)
        r1.influence = self._clamp(r1.influence + 0.02)
        r2.influence = self._clamp(r2.influence + 0.02)

        self.simulation_state.alliance_events.append({
            "type": "alliance_formation",
            "rival_id_1": rival_id_1,
            "rival_id_2": rival_id_2,
            "year": self.simulation_state.year,
        })

        return {
            "success": True,
            "alliance_between": [rival_id_1, rival_id_2],
            "narrative": f"{r1.name} and {r2.name} form a formal alliance. "
                         f"Their combined strength will reshape the balance of power.",
        }

    def break_alliance(self, rival_id_1: str, rival_id_2: str) -> Dict[str, Any]:
        """Break an existing alliance."""
        if rival_id_1 == "player":
            rival = self.rivals.get(rival_id_2)
            if rival is None:
                return {"success": False, "error": f"Rival {rival_id_2} not found"}
            old_rel = rival.relationships.get("player", "neutral")
            if old_rel != "allied":
                return {"success": False, "error": f"No alliance exists with {rival_id_2}"}
            rival.relationships["player"] = "hostile"
            return {
                "success": True,
                "broken_alliance": ["player", rival_id_2],
                "narrative": f"The alliance between the Player Federation and {rival.name} shatters.",
            }

        if rival_id_2 == "player":
            return self.break_alliance(rival_id_2, rival_id_1)

        r1 = self.rivals.get(rival_id_1)
        r2 = self.rivals.get(rival_id_2)
        if r1 is None or r2 is None:
            missing = rival_id_1 if r1 is None else rival_id_2
            return {"success": False, "error": f"Rival {missing} not found"}

        old_rel = r1.relationships.get(r2.rival_id, "neutral")
        if old_rel != "allied":
            return {
                "success": False,
                "error": f"No alliance exists between {rival_id_1} and {rival_id_2}",
            }

        r1.relationships[r2.rival_id] = "hostile"
        r2.relationships[r1.rival_id] = "hostile"
        r1.stability = self._clamp(r1.stability - 0.05)
        r2.stability = self._clamp(r2.stability - 0.05)
        r1.influence = self._clamp(r1.influence - 0.02)
        r2.influence = self._clamp(r2.influence - 0.02)

        return {
            "success": True,
            "broken_alliance": [rival_id_1, rival_id_2],
            "narrative": f"The alliance between {r1.name} and {r2.name} fractures. "
                         f"Mutual recrimination poisons what was once cooperation.",
        }

    def get_rival_observers(self) -> List[Dict[str, Any]]:
        """Return rival federation data formatted as observers for the QC engine.

        Each rival gets assigned an ObserverRole based on personality.
        Returns list of dicts with keys matching QuantumConsciousnessEngine.register_observer().
        """
        observers: List[Dict[str, Any]] = []

        for rival in self.rivals.values():
            if rival.power < 0.05:
                continue

            role = PERSONALITY_TO_OBSERVER_ROLE.get(rival.personality, "witness")
            ideology = PERSONALITY_TO_IDEOLOGY_TYPE.get(rival.personality, "scientific")

            observers.append({
                "faction_id": rival.rival_id,
                "default_role": role,
                "faction_name": rival.name,
                "ideology": ideology,
                "influence_weight": round(rival.influence * rival.power, 4),
            })

        return observers

    def export_state(self) -> Dict[str, Any]:
        """Export full simulation state for save/persistence."""
        rivals_data: Dict[str, Any] = {}
        for rival_id, rival in self.rivals.items():
            rivals_data[rival_id] = {
                "rival_id": rival.rival_id,
                "name": rival.name,
                "personality": rival.personality.value,
                "power": rival.power,
                "influence": rival.influence,
                "aggression": rival.aggression,
                "stability": rival.stability,
                "technology": rival.technology,
                "territory": rival.territory,
                "resources": rival.resources,
            "consciousness_level": rival.consciousness_level,
            "culture": rival.culture,
            "domain": rival.domain,
                "motives": rival.motives,
                "conflict_patterns": rival.conflict_patterns,
                "alliance_preferences": rival.alliance_preferences,
                "action_history": rival.action_history[-50:],
                "active_effects": rival.active_effects[-25:],
                "relationships": dict(rival.relationships),
            }

        return {
            "simulation_state": {
                "year": self.simulation_state.year,
                "total_rivals": self.simulation_state.total_rivals,
                "active_rivals": self.simulation_state.active_rivals,
                "aggregate_threat": self.simulation_state.aggregate_threat,
                "rival_actions_this_year": [
                    {
                        "rival_id": a.rival_id,
                        "action": a.action.value,
                        "target": a.target,
                        "year": a.year,
                        "success": a.success,
                        "narrative": a.narrative,
                        "impact": a.impact,
                    }
                    for a in self.simulation_state.rival_actions_this_year
                ],
                "diplomatic_events": self.simulation_state.diplomatic_events[-20:],
                "conflict_events": self.simulation_state.conflict_events[-20:],
                "alliance_events": self.simulation_state.alliance_events[-20:],
            },
            "threat_history": dict(self.threat_history),
            "rivals": rivals_data,
        }

    def import_state(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Import simulation state from saved data."""
        try:
            sim_data = data.get("simulation_state", {})
            self.simulation_state.year = sim_data.get("year", 0)
            self.simulation_state.total_rivals = sim_data.get("total_rivals", 0)
            self.simulation_state.active_rivals = sim_data.get("active_rivals", 0)
            self.simulation_state.aggregate_threat = sim_data.get("aggregate_threat", 0.0)

            self.threat_history = data.get("threat_history", {})

            rivals_data = data.get("rivals", {})
            self.rivals = {}

            for rival_id, rdata in rivals_data.items():
                personality_str = rdata.get("personality", "chaotic")
                try:
                    personality = RivalPersonality(personality_str)
                except ValueError:
                    personality = RivalPersonality.CHAOTIC

                rival = RivalFederation(
                    rival_id=rdata.get("rival_id", rival_id),
                    name=rdata.get("name", rival_id),
                    personality=personality,
                    power=rdata.get("power", 0.5),
                    influence=rdata.get("influence", 0.5),
                    aggression=rdata.get("aggression", 0.5),
                    stability=rdata.get("stability", 0.5),
                    technology=rdata.get("technology", 0.5),
                    territory=rdata.get("territory", 5),
                    resources=rdata.get("resources", 0.5),
            consciousness_level=rdata.get("consciousness_level", 0.3),
            culture=rdata.get("culture", 0.5),
            domain=rdata.get("domain", "Unknown"),
                    motives=rdata.get("motives", []),
                    conflict_patterns=rdata.get("conflict_patterns", []),
                    alliance_preferences=rdata.get("alliance_preferences", []),
                    action_history=rdata.get("action_history", []),
                    active_effects=rdata.get("active_effects", []),
                    relationships=rdata.get("relationships", {}),
                )
                self.rivals[rival_id] = rival

            imported_actions = sim_data.get("rival_actions_this_year", [])
            self.simulation_state.rival_actions_this_year = []
            for a in imported_actions:
                try:
                    action_enum = RivalAction(a.get("action", "expand"))
                except ValueError:
                    action_enum = RivalAction.EXPAND
                self.simulation_state.rival_actions_this_year.append(
                    RivalActionRecord(
                        rival_id=a.get("rival_id", ""),
                        action=action_enum,
                        target=a.get("target", ""),
                        year=a.get("year", 0),
                        power_cost=a.get("power_cost", 0.0),
                        success=a.get("success", False),
                        narrative=a.get("narrative", ""),
                        impact=a.get("impact", {}),
                    )
                )

            self.simulation_state.diplomatic_events = sim_data.get("diplomatic_events", [])
            self.simulation_state.conflict_events = sim_data.get("conflict_events", [])
            self.simulation_state.alliance_events = sim_data.get("alliance_events", [])

            return {
                "success": True,
                "rivals_imported": len(self.rivals),
                "year": self.simulation_state.year,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_rival_history_by_year(self, year: int) -> Dict[str, Any]:
        """Query rival states and actions for a specific year.

        Used by federation_game_history_arc.py for per-year queries.
        """
        year_actions = []
        for rival in self.rivals.values():
            for action in rival.action_history:
                if action.get("year") == year:
                    year_actions.append({
                        "rival_id": rival.rival_id,
                        "rival_name": rival.name,
                        "personality": rival.personality.value,
                        **action,
                    })

        return {
            "success": True,
            "year": year,
            "threat_level": self.threat_history.get(year, 0.0),
            "threat_enum": self._threat_level_from_value(
                self.threat_history.get(year, 0.0)
            ).value,
            "actions": year_actions,
            "active_rival_count": len([
                r for r in self.rivals.values()
                if any(a.get("year") == year for a in r.action_history)
            ]),
        }

    @staticmethod
    def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Clamp a value between min and max."""
        return max(min_val, min(max_val, value))


# ============================================================================
# INTEGRATION FUNCTIONS
# ============================================================================

def attach_rival_simulator(turn_engine: Any) -> Dict[str, Any]:
    """Attach the RivalFederationSimulator to a GameTurn engine instance.

    This is the integration point called by federation_game_turns.py.
    It creates a simulator, initializes default rivals, and assigns it
    to the turn engine's rival_simulator attribute.
    """
    try:
        simulator = RivalFederationSimulator()
        init_result = simulator.initialize_rivals()

        turn_engine.rival_simulator = simulator

        return {
            "success": True,
            "simulator_attached": True,
            "rivals_created": init_result.get("rivals_created", 0),
            "rival_ids": init_result.get("rival_ids", []),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "simulator_attached": False,
        }


def create_rival_simulator(configs: Optional[List[Dict[str, Any]]] = None) -> RivalFederationSimulator:
    """Factory function to create and initialize a RivalFederationSimulator."""
    simulator = RivalFederationSimulator()
    simulator.initialize_rivals(configs)
    return simulator


def get_default_rival_summary() -> Dict[str, Any]:
    """Return a summary of the 12 default rival archetypes without creating a simulator."""
    return {
        "success": True,
        "total_archetypes": len(DEFAULT_RIVAL_CONFIGS),
        "archetypes": [
            {
                "rival_id": cfg["rival_id"],
                "name": cfg["name"],
                "personality": cfg["personality"].value if isinstance(cfg["personality"], RivalPersonality) else cfg["personality"],
                "power": cfg.get("power", 0.5),
                "aggression": cfg.get("aggression", 0.5),
                "domain": cfg.get("domain", "Unknown"),
            }
            for cfg in DEFAULT_RIVAL_CONFIGS
        ],
    }
