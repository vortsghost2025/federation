"""
_mock_map_data.py — Strict integration fixture for Galaxy Map development.

Purpose: Let us prove the Galaxy Map renderer turns valid Federation data
into a usable spatial map WITHOUT touching the real backend.

This fixture uses the EXACT field names and shapes from the live /map/data
endpoint (backend/map_endpoints.py:1090) and the dataclasses in
backend/spatial_models.py. Nothing invented. Nothing renamed.

It is mounted by _mock_server.py (a wrapper around the Python static server)
which intercepts /map/data and returns this JSON. The Galaxy Map page
detects the `mock: true` envelope and displays a prominent "MOCK DATA"
banner so this can never be confused with live Federation state.

Coverage (what the fixture must exercise):
  - sectors with real x/y separation, adjacency, danger, region_type
  - faction_territories: at least one 'home', one 'colony', one 'contested'
  - npc_locations: one stationary, one moving (destination + progress),
    one with a patrol_route, one on expedition
  - factions: 4 factions with distinct home_sector_ids, colors, stances
  - discoveries: at least one of each state
    (undiscovered, detected, contacted, relations_open)
  - world_state: tension/stability/morale/anomaly with non-zero values

Re-running this fixture is deterministic (no randomness in positions).
"""

import json
import time

# ---------------------------------------------------------------------------
# Sectors — 8 sectors with real spatial separation (mirrors the layout in
# universe.html's SECTORS array, but smaller and explicit). Coordinates
# follow the backend convention: canvas-centered (0,0 = map center),
# x and y in sector-map units. Galaxy Map will scale by SCALE=0.05.
# ---------------------------------------------------------------------------
SECTORS = [
    {"id": "sol-prime", "name": "Sol Prime", "x": 0,    "y": 0,
     "region_type": "core", "resource_profile": "research",
     "danger_level": 1, "description": "Federation capital. Home of the Council.",
     "adjacent_sector_ids": ["helix", "kepler", "vega"]},
    {"id": "helix", "name": "Helix", "x": 80,   "y": -40,
     "region_type": "core", "resource_profile": "research",
     "danger_level": 2, "description": "Research Division home sector.",
     "adjacent_sector_ids": ["sol-prime", "orion", "andromeda"]},
    {"id": "kepler", "name": "Kepler", "x": -70, "y": 30,
     "region_type": "core", "resource_profile": "diplomatic",
     "danger_level": 2, "description": "Diplomatic Corps home sector.",
     "adjacent_sector_ids": ["sol-prime", "shadow"]},
    {"id": "orion", "name": "Orion", "x": 130, "y": 50,
     "region_type": "inner", "resource_profile": "economic",
     "danger_level": 3, "description": "Economic Council home sector.",
     "adjacent_sector_ids": ["helix", "vega", "sirius"]},
    {"id": "vega", "name": "Vega", "x": 40, "y": 100,
     "region_type": "inner", "resource_profile": "military",
     "danger_level": 4, "description": "Military Command home sector.",
     "adjacent_sector_ids": ["sol-prime", "orion", "abyss"]},
    {"id": "sirius", "name": "Sirius", "x": 200, "y": 100,
     "region_type": "outer", "resource_profile": "mixed",
     "danger_level": 5, "description": "Outer-ring trade hub.",
     "adjacent_sector_ids": ["orion", "frontier-edge"]},
    {"id": "shadow", "name": "Shadow", "x": -150, "y": 110,
     "region_type": "outer", "resource_profile": "espionage",
     "danger_level": 6, "description": "Contested border zone.",
     "adjacent_sector_ids": ["kepler", "frontier-edge"]},
    {"id": "abyss", "name": "Abyss", "x": 110, "y": 200,
     "region_type": "frontier", "resource_profile": "mixed",
     "danger_level": 9, "description": "Frontier sector. Almost unmapped.",
     "adjacent_sector_ids": ["vega", "frontier-edge"]},
    {"id": "andromeda", "name": "Andromeda", "x": -40, "y": -120,
     "region_type": "outer", "resource_profile": "research",
     "danger_level": 5, "description": "Outer-ring research outpost.",
     "adjacent_sector_ids": ["helix", "shadow"]},
    {"id": "frontier-edge", "name": "Frontier Edge", "x": 250, "y": 220,
     "region_type": "frontier", "resource_profile": "mixed",
     "danger_level": 10, "description": "Edge of Federation space.",
     "adjacent_sector_ids": ["sirius", "shadow", "abyss"]},
]

# ---------------------------------------------------------------------------
# Factions — 4 factions with distinct home_sector_ids + colors
# ---------------------------------------------------------------------------
FACTIONS = {
    "research_division": {
        "display_name": "Research Division", "member_count": 12,
        "cohesion": 78, "influence": 65, "standing": 70, "vigilance": 55,
        "avg_mood": 0.62, "activity_rate": 0.7,
        "decisions_this_tick": 3, "events_this_tick": 1,
        "color": "#4fc3f7", "stances": {},
        "home_sector_id": "helix",
    },
    "military_command": {
        "display_name": "Military Command", "member_count": 18,
        "cohesion": 82, "influence": 75, "standing": 65, "vigilance": 90,
        "avg_mood": 0.55, "activity_rate": 0.85,
        "decisions_this_tick": 5, "events_this_tick": 2,
        "color": "#ef5350", "stances": {},
        "home_sector_id": "vega",
    },
    "diplomatic_corps": {
        "display_name": "Diplomatic Corps", "member_count": 9,
        "cohesion": 71, "influence": 60, "standing": 85, "vigilance": 50,
        "avg_mood": 0.70, "activity_rate": 0.6,
        "decisions_this_tick": 2, "events_this_tick": 1,
        "color": "#66bb6a", "stances": {},
        "home_sector_id": "kepler",
    },
    "exploration_initiative": {
        "display_name": "Exploration Initiative", "member_count": 7,
        "cohesion": 65, "influence": 45, "standing": 60, "vigilance": 80,
        "avg_mood": 0.75, "activity_rate": 0.9,
        "decisions_this_tick": 4, "events_this_tick": 3,
        "color": "#26a69a", "stances": {},
        "home_sector_id": "abyss",
    },
}

# ---------------------------------------------------------------------------
# FactionTerritories — covers home, colony, contested
# ---------------------------------------------------------------------------
TERRITORIES = [
    # Research Division: home at helix, colonies at sol-prime and andromeda
    {"faction_id": "research_division", "sector_id": "helix",
     "control_level": 95.0, "influence_level": 100.0,
     "claim_type": "home", "last_contested_tick": 0},
    {"faction_id": "research_division", "sector_id": "sol-prime",
     "control_level": 60.0, "influence_level": 80.0,
     "claim_type": "colony", "last_contested_tick": 0},
    {"faction_id": "research_division", "sector_id": "andromeda",
     "control_level": 45.0, "influence_level": 55.0,
     "claim_type": "colony", "last_contested_tick": 0},

    # Military Command: home at vega, contested with Diplomatic Corps at shadow
    {"faction_id": "military_command", "sector_id": "vega",
     "control_level": 92.0, "influence_level": 100.0,
     "claim_type": "home", "last_contested_tick": 0},
    {"faction_id": "military_command", "sector_id": "abyss",
     "control_level": 55.0, "influence_level": 70.0,
     "claim_type": "colony", "last_contested_tick": 0},

    # Diplomatic Corps: home at kepler, contested at shadow
    {"faction_id": "diplomatic_corps", "sector_id": "kepler",
     "control_level": 88.0, "influence_level": 100.0,
     "claim_type": "home", "last_contested_tick": 0},
    {"faction_id": "diplomatic_corps", "sector_id": "sirius",
     "control_level": 50.0, "influence_level": 60.0,
     "claim_type": "colony", "last_contested_tick": 0},
    {"faction_id": "diplomatic_corps", "sector_id": "orion",
     "control_level": 40.0, "influence_level": 50.0,
     "claim_type": "colony", "last_contested_tick": 0},

    # Contested: shadow has both Military and Diplomatic presence
    {"faction_id": "military_command", "sector_id": "shadow",
     "control_level": 35.0, "influence_level": 45.0,
     "claim_type": "contested", "last_contested_tick": 110},
    {"faction_id": "diplomatic_corps", "sector_id": "shadow",
     "control_level": 30.0, "influence_level": 40.0,
     "claim_type": "contested", "last_contested_tick": 108},

    # Exploration Initiative: home at abyss
    {"faction_id": "exploration_initiative", "sector_id": "abyss",
     "control_level": 70.0, "influence_level": 85.0,
     "claim_type": "home", "last_contested_tick": 0},
    {"faction_id": "exploration_initiative", "sector_id": "frontier-edge",
     "control_level": 25.0, "influence_level": 40.0,
     "claim_type": "neutral", "last_contested_tick": 0},
]

# ---------------------------------------------------------------------------
# NPC roster (enriched) — factions get listed under their home sector
# ---------------------------------------------------------------------------
NPCS = [
    {"id": "char_001", "name": "Captain Valor", "affiliation": "research_division",
     "category": "companion", "mood": "focused", "goal": "explore",
     "thought": "The Codex at Andromeda is close.", "sector_id": "andromeda"},
    {"id": "char_002", "name": "Admiral Vex", "affiliation": "military_command",
     "category": "companion", "mood": "tense", "goal": "defend",
     "thought": "Shadow is unstable. I need more patrols.", "sector_id": "vega"},
    {"id": "char_003", "name": "Lyra Swiftwind", "affiliation": "diplomatic_corps",
     "category": "companion", "mood": "calm", "goal": "negotiate",
     "thought": "Diplomatic channels with Sirian traders remain open.", "sector_id": "sirius"},
    {"id": "char_004", "name": "Shadowborn", "affiliation": "research_division",
     "category": "enigma", "mood": "watchful", "goal": "observe",
     "thought": "Two signals. Two flags. Which is real?", "sector_id": "shadow"},
    {"id": "char_005", "name": "Lord Malak", "affiliation": "diplomatic_corps",
     "category": "rival", "mood": "calculating", "goal": "expand",
     "thought": "Shadow will fall to me.", "sector_id": "shadow"},
    {"id": "char_306", "name": "Oracle", "affiliation": "consciousness_collective",
     "category": "enigma", "mood": "resonant", "goal": "understand",
     "thought": "The pattern repeats.", "sector_id": "helix"},
    {"id": "char_010", "name": "Brigadier Ember", "affiliation": "military_command",
     "category": "companion", "mood": "alert", "goal": "patrol",
     "thought": "Route check complete.", "sector_id": "abyss"},
    {"id": "char_011", "name": "Vega Scout", "affiliation": "military_command",
     "category": "neutral", "mood": "neutral", "goal": "patrol",
     "thought": "On station.", "sector_id": "orion"},
    {"id": "char_012", "name": "Dr. Mara Solis", "affiliation": "research_division",
     "category": "companion", "mood": "curious", "goal": "research",
     "thought": "Andromeda Codex is within reach.", "sector_id": "andromeda"},
]

# ---------------------------------------------------------------------------
# NpcLocations — one stationary, one moving (destination + progress),
# one with patrol_route, one on expedition
# ---------------------------------------------------------------------------
NPC_LOCATIONS = [
    # Stationary garrison
    {"npc_id": "char_002", "sector_id": "vega", "x_offset": 0, "y_offset": 0,
     "current_task": "garrison", "destination_sector_id": "",
     "movement_progress": 0.0, "patrol_route": []},

    # Moving from andromeda → sol-prime (in transit, mid-way)
    {"npc_id": "char_001", "sector_id": "andromeda", "x_offset": 0, "y_offset": 0,
     "current_task": "expedition", "destination_sector_id": "sol-prime",
     "movement_progress": 0.4, "patrol_route": []},

    # Patrol loop: sol-prime → helix → orion → back to sol-prime
    {"npc_id": "char_011", "sector_id": "orion", "x_offset": 0, "y_offset": 0,
     "current_task": "patrol", "destination_sector_id": "sol-prime",
     "movement_progress": 0.0,
     "patrol_route": ["sol-prime", "helix", "orion"]},

    # Patrol loop: shadow contested zone
    {"npc_id": "char_004", "sector_id": "shadow", "x_offset": 0, "y_offset": 0,
     "current_task": "patrol", "destination_sector_id": "",
     "movement_progress": 0.0,
     "patrol_route": ["kepler", "shadow", "andromeda"]},

    # Expedition to abyss
    {"npc_id": "char_010", "sector_id": "abyss", "x_offset": 0, "y_offset": 0,
     "current_task": "expedition", "destination_sector_id": "frontier-edge",
     "movement_progress": 0.6, "patrol_route": []},

    # Other NPCs (enriched but stationary)
    {"npc_id": "char_003", "sector_id": "sirius", "x_offset": 0, "y_offset": 0,
     "current_task": "diplomacy", "destination_sector_id": "",
     "movement_progress": 0.0, "patrol_route": []},
    {"npc_id": "char_005", "sector_id": "shadow", "x_offset": 0, "y_offset": 0,
     "current_task": "garrison", "destination_sector_id": "",
     "movement_progress": 0.0, "patrol_route": []},
    {"npc_id": "char_306", "sector_id": "helix", "x_offset": 0, "y_offset": 0,
     "current_task": "research", "destination_sector_id": "",
     "movement_progress": 0.0, "patrol_route": []},
    {"npc_id": "char_012", "sector_id": "andromeda", "x_offset": 0, "y_offset": 0,
     "current_task": "research", "destination_sector_id": "andromeda",
     "movement_progress": 0.0, "patrol_route": []},
]

# ---------------------------------------------------------------------------
# WorldDiscovery — all 4 states represented
#   WorldDiscovery state per spatial_models.py:245-247:
#     "undiscovered" | "detected" | "contacted" | "relations_open"
# ---------------------------------------------------------------------------
DISCOVERIES = [
    {"faction_a_id": "research_division", "faction_b_id": "military_command",
     "state": "relations_open", "discovered_tick": 12, "contacted_tick": 18,
     "relations_open_tick": 35, "discovery_method": "broadcast"},
    {"faction_a_id": "research_division", "faction_b_id": "diplomatic_corps",
     "state": "relations_open", "discovered_tick": 8, "contacted_tick": 14,
     "relations_open_tick": 22, "discovery_method": "territory_adjacency"},
    {"faction_a_id": "military_command", "faction_b_id": "diplomatic_corps",
     "state": "contacted", "discovered_tick": 10, "contacted_tick": 45,
     "relations_open_tick": 0, "discovery_method": "npc_encounter"},
    {"faction_a_id": "exploration_initiative", "faction_b_id": "research_division",
     "state": "contacted", "discovered_tick": 28, "contacted_tick": 67,
     "relations_open_tick": 0, "discovery_method": "expedition"},
    {"faction_a_id": "exploration_initiative", "faction_b_id": "military_command",
     "state": "detected", "discovered_tick": 88, "contacted_tick": 0,
     "relations_open_tick": 0, "discovery_method": "broadcast"},
    {"faction_a_id": "exploration_initiative", "faction_b_id": "diplomatic_corps",
     "state": "undiscovered", "discovered_tick": 0, "contacted_tick": 0,
     "relations_open_tick": 0, "discovery_method": ""},
]

# ---------------------------------------------------------------------------
# World state (non-zero values to make gauges visible)
# ---------------------------------------------------------------------------
WORLD_STATE = {
    "tension_level": 58,
    "stability": 72,
    "morale": 64,
    "anomaly_activity": 31,
    "threat_level": 4,
    "resource_abundance": 67,
    "treasury": 12450,
}

WORKER = {"tick_count": 142, "status": "running", "pid": 99999}

SPATIAL_RENDERING_ENABLED = True

# ---------------------------------------------------------------------------
# Build /map/data response (exact envelope from map_endpoints.py:1090-1290)
# ---------------------------------------------------------------------------
def build_response():
    return {
        "world_state": WORLD_STATE,
        "npcs": NPCS,
        "factions": FACTIONS,
        "events": [],
        "broadcasts": [],
        "worker": WORKER,
        "sectors": SECTORS,
        "faction_territories": TERRITORIES,
        "npc_locations": NPC_LOCATIONS,
        "discoveries": DISCOVERIES,
        "spatial_rendering_enabled": SPATIAL_RENDERING_ENABLED,
        "crisis_readout": {"stable": True, "message": "All systems nominal."},
        "history": {"ticks": [142, 141, 140]},
        # Mock envelope marker — frontend MUST surface this in the UI
        # so the user can never mistake it for live Federation state.
        "_mock": {
            "active": True,
            "fixture_name": "galaxy-map-integration-v1",
            "fixture_built_at": "2026-08-20",
            "shape_verified_against": "backend/map_endpoints.py:1090",
        },
    }


if __name__ == "__main__":
    # Smoke test: build + print summary so we can verify the fixture
    # exercises every state the spec requires.
    r = build_response()
    print("FIXTURE SUMMARY")
    print(f"  sectors              : {len(r['sectors'])}")
    print(f"  factions             : {len(r['factions'])}")
    print(f"  faction_territories  : {len(r['faction_territories'])}")
    print(f"  npcs                 : {len(r['npcs'])}")
    print(f"  npc_locations        : {len(r['npc_locations'])}")
    print(f"  discoveries          : {len(r['discoveries'])}")
    states = sorted({d["state"] for d in r["discoveries"]})
    print(f"  discovery states     : {states}")
    claims = sorted({t["claim_type"] for t in r["faction_territories"]})
    print(f"  territory claim types: {claims}")
    tasks = sorted({l["current_task"] for l in r["npc_locations"]})
    print(f"  npc current_tasks    : {tasks}")
    moving = [l for l in r["npc_locations"]
              if l["destination_sector_id"] and l["movement_progress"] > 0]
    print(f"  npcs in motion       : {len(moving)}")
    patrolling = [l for l in r["npc_locations"] if l["patrol_route"]]
    print(f"  patrolling npcs      : {len(patrolling)}")
    on_expedition = [l for l in r["npc_locations"] if l["current_task"] == "expedition"]
    print(f"  npcs on expedition   : {len(on_expedition)}")
    print("  mock envelope        :", r["_mock"]["fixture_name"])
