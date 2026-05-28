"""
Spatial seed — populates Redis with the canonical 21-sector map, faction homes,
NPC placeholders, adjacency edges, and world-discovery pairs.

Idempotent: if the system is disabled or sectors already exist, returns early.
Uses the canonical sector data from SPATIAL_DATA_MODEL_SPEC §9.
"""

import logging
from itertools import combinations
from typing import Dict, List, Set, Tuple

from spatial_models import (
    FactionHome,
    FactionTerritory,
    NpcLocation,
    Sector,
    SectorAdjacency,
    WorldDiscovery,
)
from spatial_state import (
    is_spatial_enabled,
    save_adjacency,
    save_discovery,
    save_faction_home,
    save_faction_territory,
    save_npc_location,
    save_sector,
    sector_exists,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical 21-sector definitions (from SPEC §9)
# ---------------------------------------------------------------------------

SECTOR_DEFS = [
    # --- Core (3) ---
    {
        "id": "sol-prime",
        "name": "Sol Prime",
        "x": 0,
        "y": 0,
        "region_type": "core",
        "resource_profile": "mixed",
        "danger_level": 1,
        "description": "The heart of the Federation. All roads lead here.",
    },
    {
        "id": "meridian",
        "name": "Meridian",
        "x": -60,
        "y": 35,
        "region_type": "core",
        "resource_profile": "diplomatic",
        "danger_level": 2,
        "description": "Where treaties are forged and alliances balanced.",
    },
    {
        "id": "crucible",
        "name": "Crucible",
        "x": 60,
        "y": 35,
        "region_type": "core",
        "resource_profile": "economic",
        "danger_level": 2,
        "description": "The proving ground of commerce and competition.",
    },
    # --- Inner (6) ---
    {
        "id": "helix",
        "name": "Helix",
        "x": -110,
        "y": -65,
        "region_type": "inner",
        "resource_profile": "research",
        "danger_level": 3,
        "description": "Spiral archives of forgotten knowledge, decoded endlessly.",
    },
    {
        "id": "forge",
        "name": "Forge",
        "x": -130,
        "y": 40,
        "region_type": "inner",
        "resource_profile": "economic",
        "danger_level": 3,
        "description": "Foundries that never cool. Production without pause.",
    },
    {
        "id": "bastion",
        "name": "Bastion",
        "x": -50,
        "y": 100,
        "region_type": "inner",
        "resource_profile": "military",
        "danger_level": 3,
        "description": "The shield that never sleeps. Garrison of the watchful.",
    },
    {
        "id": "archive",
        "name": "Archive",
        "x": 50,
        "y": 100,
        "region_type": "inner",
        "resource_profile": "research",
        "danger_level": 3,
        "description": "Libraries that remember what the living cannot.",
    },
    {
        "id": "prism",
        "name": "Prism",
        "x": 130,
        "y": 40,
        "region_type": "inner",
        "resource_profile": "diplomatic",
        "danger_level": 3,
        "description": "Where every perspective refracts into understanding.",
    },
    {
        "id": "harbor",
        "name": "Harbor",
        "x": 110,
        "y": -65,
        "region_type": "inner",
        "resource_profile": "mixed",
        "danger_level": 3,
        "description": "The port of call for wanderers, seekers, and refugees.",
    },
    # --- Outer (6) ---
    {
        "id": "reach",
        "name": "The Reach",
        "x": -170,
        "y": -100,
        "region_type": "outer",
        "resource_profile": "research",
        "danger_level": 5,
        "description": "The far hand of curiosity, grasping past the known.",
    },
    {
        "id": "shroud",
        "name": "The Shroud",
        "x": -200,
        "y": 60,
        "region_type": "outer",
        "resource_profile": "mixed",
        "danger_level": 6,
        "description": "Mists that conceal more than they reveal.",
    },
    {
        "id": "drift",
        "name": "The Drift",
        "x": -100,
        "y": 180,
        "region_type": "outer",
        "resource_profile": "economic",
        "danger_level": 5,
        "description": "Currents of trade flowing through uncertain space.",
    },
    {
        "id": "pinnacle",
        "name": "Pinnacle",
        "x": 100,
        "y": 180,
        "region_type": "outer",
        "resource_profile": "military",
        "danger_level": 5,
        "description": "The high ground, fought over since the first war.",
    },
    {
        "id": "veil",
        "name": "The Veil",
        "x": 200,
        "y": 60,
        "region_type": "outer",
        "resource_profile": "diplomatic",
        "danger_level": 5,
        "description": "A thin curtain between what is known and what is whispered.",
    },
    {
        "id": "expanse",
        "name": "The Expanse",
        "x": 170,
        "y": -100,
        "region_type": "outer",
        "resource_profile": "research",
        "danger_level": 5,
        "description": "Open void where signals stretch thin and strange.",
    },
    # --- Frontier (6) ---
    {
        "id": "abyss",
        "name": "The Abyss",
        "x": -240,
        "y": -160,
        "region_type": "frontier",
        "resource_profile": "research",
        "danger_level": 8,
        "description": "Where light gives up. Where the simulation questions itself.",
    },
    {
        "id": "fracture",
        "name": "Fracture",
        "x": -270,
        "y": 100,
        "region_type": "frontier",
        "resource_profile": "military",
        "danger_level": 8,
        "description": "Broken space. Splintered reality. War without fronts.",
    },
    {
        "id": "signal",
        "name": "Signal",
        "x": -160,
        "y": 280,
        "region_type": "frontier",
        "resource_profile": "diplomatic",
        "danger_level": 7,
        "description": "A repeating pattern in the noise. Something is calling.",
    },
    {
        "id": "ghost",
        "name": "Ghost",
        "x": 160,
        "y": 280,
        "region_type": "frontier",
        "resource_profile": "mixed",
        "danger_level": 7,
        "description": "Echoes of what was. Shadows of what could be.",
    },
    {
        "id": "threshold",
        "name": "Threshold",
        "x": 270,
        "y": 100,
        "region_type": "frontier",
        "resource_profile": "economic",
        "danger_level": 7,
        "description": "The edge of everything. Where profit meets the unknown.",
    },
    {
        "id": "beyond",
        "name": "Beyond",
        "x": 240,
        "y": -160,
        "region_type": "frontier",
        "resource_profile": "research",
        "danger_level": 9,
        "description": "Past the map. Past the rules. Past the reason.",
    },
]

# ---------------------------------------------------------------------------
# Faction home assignments — maps KNOWN_FACTIONS IDs to home sectors
# (positional mapping per user decision, §9.1)
# ---------------------------------------------------------------------------

FACTION_HOME_MAP: Dict[str, Dict[str, str]] = {
    "research_division": {"home_sector": "archive", "expansion_policy": "moderate"},
    "military_command": {"home_sector": "bastion", "expansion_policy": "aggressive"},
    "diplomatic_corps": {"home_sector": "prism", "expansion_policy": "moderate"},
    "economic_council": {"home_sector": "forge", "expansion_policy": "moderate"},
    "exploration_initiative": {
        "home_sector": "reach",
        "expansion_policy": "aggressive",
    },
    "cultural_ministry": {"home_sector": "shroud", "expansion_policy": "isolationist"},
    "preservation_society": {"home_sector": "helix", "expansion_policy": "cautious"},
    "consciousness_collective": {
        "home_sector": "harbor",
        "expansion_policy": "cautious",
    },
}

# ---------------------------------------------------------------------------
# Adjacency edges — the movement graph (from SPEC §9.3)
# ---------------------------------------------------------------------------

ADJACENCY_EDGES: List[Tuple[str, str]] = [
    # Core ring
    ("meridian", "sol-prime"),
    ("sol-prime", "crucible"),
    # Core → Inner
    ("sol-prime", "helix"),
    ("sol-prime", "forge"),
    ("sol-prime", "bastion"),
    ("sol-prime", "archive"),
    ("sol-prime", "prism"),
    ("sol-prime", "harbor"),
    ("meridian", "helix"),
    ("meridian", "forge"),
    ("meridian", "bastion"),
    ("crucible", "archive"),
    ("crucible", "prism"),
    ("crucible", "harbor"),
    # Inner → Outer
    ("helix", "reach"),
    ("helix", "shroud"),
    ("forge", "shroud"),
    ("forge", "drift"),
    ("bastion", "drift"),
    ("archive", "pinnacle"),
    ("prism", "pinnacle"),
    ("prism", "veil"),
    ("harbor", "veil"),
    ("harbor", "expanse"),
    # Outer ring (partial)
    ("reach", "shroud"),
    ("shroud", "drift"),
    ("drift", "pinnacle"),
    ("pinnacle", "veil"),
    ("veil", "expanse"),
    # Outer → Frontier
    ("reach", "abyss"),
    ("shroud", "fracture"),
    ("drift", "signal"),
    ("pinnacle", "ghost"),
    ("veil", "threshold"),
    ("expanse", "beyond"),
    # Frontier ring (partial)
    ("abyss", "fracture"),
    ("fracture", "signal"),
    ("signal", "ghost"),
    ("ghost", "threshold"),
    ("threshold", "beyond"),
]

ALL_FACTION_IDS = sorted(FACTION_HOME_MAP.keys())


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------


def seed_spatial_system() -> dict:
    """Populate Redis with the canonical 21-sector spatial world data.

    Returns:
        dict: ``{"disabled": True}`` if spatial system is disabled,
        ``{"already_seeded": True}`` if sectors already exist,
        or a counts dict on success.
    """
    if not is_spatial_enabled():
        logger.warning("Spatial system is disabled — skipping seed")
        return {"disabled": True}

    if sector_exists():
        logger.info("Spatial data already seeded — skipping")
        return {"already_seeded": True}

    logger.info("Beginning spatial seed …")

    # Build adjacency lookup before constructing sectors
    adjacency_lookup: Dict[str, List[str]] = {}
    for sector_a, sector_b in ADJACENCY_EDGES:
        adjacency_lookup.setdefault(sector_a, []).append(sector_b)
        adjacency_lookup.setdefault(sector_b, []).append(sector_a)

    # --- Sectors (21) -------------------------------------------------------
    sector_count = 0
    for sdef in SECTOR_DEFS:
        sector = Sector(
            id=sdef["id"],
            name=sdef["name"],
            x=sdef["x"],
            y=sdef["y"],
            region_type=sdef["region_type"],
            resource_profile=sdef["resource_profile"],
            danger_level=sdef["danger_level"],
            description=sdef["description"],
            adjacent_sector_ids=adjacency_lookup.get(sdef["id"], []),
        )
        save_sector(sector)
        sector_count += 1
    logger.info("Seeded %d sectors", sector_count)

    # --- Adjacency edges -----------------------------------------------------
    adj_count = 0
    for sector_a, sector_b in ADJACENCY_EDGES:
        adj = SectorAdjacency(
            sector_a_id=sector_a,
            sector_b_id=sector_b,
            route_type="standard",
            travel_cost=1.0,
        )
        save_adjacency(adj)
        adj_count += 1
    logger.info("Seeded %d adjacency edges", adj_count)

    # --- Faction homes (8), territories (8), NPC placeholders (8) -----------
    home_count = 0
    territory_count = 0
    npc_count = 0
    for faction_id, info in FACTION_HOME_MAP.items():
        home = FactionHome(
            faction_id=faction_id,
            home_sector_id=info["home_sector"],
            expansion_policy=info["expansion_policy"],
        )
        save_faction_home(home)
        home_count += 1

        territory = FactionTerritory(
            faction_id=faction_id,
            sector_id=info["home_sector"],
            control_level=100.0,
            influence_level=100.0,
            claim_type="home",
        )
        save_faction_territory(territory)
        territory_count += 1

        npc = NpcLocation(
            npc_id=f"faction_home_rep:{faction_id}",
            sector_id=info["home_sector"],
            current_task="garrison",
        )
        save_npc_location(npc)
        npc_count += 1

    logger.info("Seeded %d faction homes", home_count)
    logger.info("Seeded %d faction territories", territory_count)
    logger.info("Seeded %d NPC placeholders", npc_count)

    # --- World discovery pairs (28) -----------------------------------------
    # Build set of adjacent sector pairs for territory-adjacency detection
    adjacent_pairs: Set[Tuple[str, str]] = set()
    for a, b in ADJACENCY_EDGES:
        ak, bk = sorted([a, b])
        adjacent_pairs.add((ak, bk))

    # Map each faction to its home sector for adjacency check
    faction_sector = {
        fid: info["home_sector"] for fid, info in FACTION_HOME_MAP.items()
    }

    discovery_count = 0
    for fa, fb in combinations(ALL_FACTION_IDS, 2):
        sa = faction_sector[fa]
        sb = faction_sector[fb]
        sa_key, sb_key = sorted([sa, sb])
        pair_key = (sa_key, sb_key)
        is_adjacent = pair_key in adjacent_pairs

        disc = WorldDiscovery(
            faction_a_id=fa,
            faction_b_id=fb,
            state="detected" if is_adjacent else "undiscovered",
            discovery_method="territory_adjacency" if is_adjacent else "",
        )
        save_discovery(disc)
        discovery_count += 1

    logger.info("Seeded %d world discovery pairs", discovery_count)

    result = {
        "sectors": sector_count,
        "adjacencies": adj_count,
        "faction_homes": home_count,
        "territories": territory_count,
        "npcs": npc_count,
        "discoveries": discovery_count,
    }
    logger.info("Spatial seed complete — %s", result)
    return result
