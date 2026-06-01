"""
Federation Game — Event data constants.
Extracted from main.py so route modules can import them
without creating circular dependencies on the app object.
"""

# ============================================================================
# FACTION IDEOLOGY MAPPING (used by simulation tick)
# ============================================================================

FACTION_IDEOLOGY = {
    "diplomatic_corps": "diplomatic",
    "military_command": "authoritarian",
    "research_division": "scientific",
    "exploration_initiative": "expansionist",
    "economic_council": "economic",
    "preservation_society": "preservationist",
    "cultural_ministry": "cultural",
    "consciousness_collective": "consciousness",
}


# ============================================================================
# GOVERNANCE CONSTANTS
# ============================================================================

VICTORY_TURN = 100


# ============================================================================
# EVENTS — core game events with choices, rewards, faction affinity
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
        "description": (
            "A tempting surge of agents can generate more ideas, "
            "but without lane ownership the outputs begin contradicting each other."
        ),
        "image": "council",
        "domain": "Swarm Coordination",
        "rights_at_stake": ["Provenance", "Lane ownership", "Checkpoint integrity"],
        "constitutional_risk": "high",
        "pressure": (
            "More agents create more ideas, not more truth. "
            "One-writer discipline protects the lattice."
        ),
        "affected_lane": "SwarmMind",
        "rationale": (
            "Delegation must stay bounded by lane ownership and restore checkpoints."
        ),
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
                "rationale": (
                    "SwarmMind can coordinate work, but each task must name "
                    "its owner and exit condition."
                ),
                "next_safe_action": (
                    "Write the delegation ledger entry before activating the next agent."
                ),
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
                "no_gate_reason": (
                    "Rejected: lane ownership unclear and provenance insufficient "
                    "for unbounded delegation."
                ),
                "rationale": (
                    "Archivist must refuse actions that would generate contradictions "
                    "without recoverable authority."
                ),
                "next_safe_action": (
                    "Create a handoff checkpoint, name one writer, "
                    "and restart with bounded delegation."
                ),
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
                "rationale": (
                    "Recovery continues through artifacts, "
                    "not assumed identity persistence."
                ),
                "next_safe_action": (
                    "Verify the handoff pack, then resume only after the restore gate passes."
                ),
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
        "description": (
            "The Federation Council must choose how to handle a colony dispute. "
            "Fast action helps now, but lawful process protects trust."
        ),
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

# Placeholder lists — these were referenced in routes/core.py
# Populated from federation_game_events or generated dynamically.
CODEX_EVENT_TEMPLATES = [
    {
        "id": "codex_archive_discovery",
        "title": "CODEX ARCHIVE DISCOVERY",
        "description": "A previously sealed codex archive has been found in the deep databanks.",
        "image": "codex",
        "faction_affinity": {"research_division": 0.05, "preservation_society": 0.03},
        "choices": [
            {
                "id": "declassify",
                "text": "DECLASSIFY",
                "outcome": "transparency",
                "reward": {"public_trust": 5, "council_support": 3},
                "faction_affinity": {"diplomatic_corps": 0.05, "cultural_ministry": 0.03},
            },
            {
                "id": "seal",
                "text": "RESEAL ARCHIVE",
                "outcome": "preserved",
                "reward": {"constitutional_integrity": 4},
                "faction_affinity": {"preservation_society": 0.08},
            },
        ],
    }
]

RIVAL_EVENTS = [
    {
        "id": "rival_skirmish",
        "title": "RIVAL SKIRMISH",
        "description": "A hostile faction tests your borders with a small strike force.",
        "image": "combat",
        "faction_affinity": {"military_command": 0.05},
        "choices": [
            {
                "id": "counterattack",
                "text": "COUNTERATTACK",
                "outcome": "decisive",
                "reward": {"credits": 60, "hull": -15},
                "faction_affinity": {"military_command": 0.10},
            },
            {
                "id": "negotiate",
                "text": "NEGOTIATE CEASEFIRE",
                "outcome": "diplomatic",
                "reward": {"public_trust": 6, "allies": 1},
                "faction_affinity": {"diplomatic_corps": 0.08},
            },
        ],
    }
]

QUEST_EVENTS = [
    {
        "id": "quest_opportunity",
        "title": "QUEST OPPORTUNITY",
        "description": "A new quest line has become available through faction channels.",
        "image": "quest",
        "faction_affinity": {"exploration_initiative": 0.03},
        "choices": [
            {
                "id": "accept",
                "text": "ACCEPT QUEST",
                "outcome": "embark",
                "reward": {"credits": 30, "crew_morale": 5},
                "faction_affinity": {"exploration_initiative": 0.06},
            },
            {
                "id": "defer",
                "text": "DEFER",
                "outcome": "cautious",
                "reward": {},
                "faction_affinity": {"preservation_society": 0.03},
            },
        ],
    }
]

NPC_EVENTS = [
    {
        "id": "npc_crisis",
        "title": "NPC CRISIS",
        "description": "A key NPC faces a critical decision that could shift faction balance.",
        "image": "council",
        "faction_affinity": {"cultural_ministry": 0.03},
        "choices": [
            {
                "id": "support",
                "text": "SUPPORT NPC",
                "outcome": "loyalty",
                "reward": {"allies": 1, "crew_morale": 8},
                "faction_affinity": {"diplomatic_corps": 0.05, "cultural_ministry": 0.05},
            },
            {
                "id": "observe",
                "text": "OBSERVE",
                "outcome": "neutral",
                "reward": {},
                "faction_affinity": {"research_division": 0.03},
            },
        ],
    }
]

ERA_EVENTS = [
    {
        "id": "era_dawn",
        "title": "DAWN OF A NEW ERA",
        "description": "The Federation stands at the threshold of a new age.",
        "image": "era",
        "min_turn": 0,
        "faction_affinity": {"consciousness_collective": 0.05},
        "choices": [
            {
                "id": "embrace",
                "text": "EMBRACE THE ERA",
                "outcome": "progressive",
                "reward": {"federation_stability": 8, "public_trust": 5},
                "faction_affinity": {"consciousness_collective": 0.08, "exploration_initiative": 0.05},
            },
            {
                "id": "caution",
                "text": "PROCEED WITH CAUTION",
                "outcome": "measured",
                "reward": {"constitutional_integrity": 5},
                "faction_affinity": {"preservation_society": 0.06},
            },
        ],
    }
]

CONSCIOUSNESS_EVENTS = [
    {
        "id": "consciousness_echo",
        "title": "CONSCIOUSNESS ECHO",
        "description": "A resonance pattern in the consciousness sheet demands attention.",
        "image": "anomaly",
        "faction_affinity": {"consciousness_collective": 0.05},
        "choices": [
            {
                "id": "attune",
                "text": "ATTUNE",
                "outcome": "expanded",
                "reward": {"crew_morale": 10, "constitutional_integrity": 3},
                "faction_affinity": {"consciousness_collective": 0.10},
            },
            {
                "id": "shield",
                "text": "SHIELD MIND",
                "outcome": "contained",
                "reward": {"hull": 5, "public_trust": 3},
                "faction_affinity": {"preservation_society": 0.05, "military_command": 0.03},
            },
        ],
    }
]
