"""
Spatial territory system — higher-level read/query functions.

Provides query and traversal logic on top of spatial_state.py.
This module NEVER touches Redis directly — all data access goes
through spatial_state functions.

See docs/SPATIAL_DATA_MODEL_SPEC.md §8 for query API.
"""

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from spatial_models import (
    Sector,
    FactionHome,
    FactionTerritory,
    NpcLocation,
    SectorAdjacency,
    WorldDiscovery,
)
from spatial_state import (
    get_sector,
    get_all_sectors,
    get_all_sector_ids,
    get_adjacent_sector_ids,
    get_faction_home,
    get_all_faction_homes,
    get_faction_territory,
    get_faction_territories,
    get_sector_territories,
    get_all_territories,
    get_npc_location,
    get_npcs_in_sector,
    get_all_npc_locations,
    get_adjacency,
    get_all_adjacencies,
    get_discovery,
    get_faction_discoveries,
    get_all_discoveries,
    is_spatial_enabled,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Simple lookups
# ---------------------------------------------------------------------------


def get_sector_by_id(sector_id: str) -> Optional[Sector]:
    if not is_spatial_enabled():
        return None
    sector = get_sector(sector_id)
    if sector is None:
        logger.debug("Sector not found: %s", sector_id)
    return sector


def get_sectors_by_region(region_type: str) -> List[Sector]:
    if not is_spatial_enabled():
        return []
    all_sectors = get_all_sectors()
    matched = [s for s in all_sectors if s.region_type == region_type]
    logger.debug("Found %d sectors with region_type=%s", len(matched), region_type)
    return matched


# ---------------------------------------------------------------------------
# 2. Faction queries
# ---------------------------------------------------------------------------


def get_faction_home_sector(faction_id: str) -> Optional[Sector]:
    if not is_spatial_enabled():
        return None
    home = get_faction_home(faction_id)
    if home is None:
        logger.debug("No FactionHome for faction: %s", faction_id)
        return None
    sector = get_sector(home.home_sector_id)
    if sector is None:
        logger.warning("FactionHome references missing sector: %s", home.home_sector_id)
    return sector


def get_faction_sphere_of_influence(faction_id: str) -> Dict:
    empty = {
        "faction_id": faction_id,
        "home_sector_id": None,
        "territories": [],
        "total_control": 0.0,
        "total_influence": 0.0,
        "sector_count": 0,
        "discovered_factions": [],
    }
    if not is_spatial_enabled():
        return empty

    home = get_faction_home(faction_id)
    home_sector_id = home.home_sector_id if home else None

    territories = get_faction_territories(faction_id)
    total_control = sum(t.control_level for t in territories)
    total_influence = sum(t.influence_level for t in territories)
    sector_count = len(territories)

    discoveries = get_faction_discoveries(faction_id)
    discovered_factions = []
    for disc in discoveries:
        if disc.faction_a_id == faction_id:
            discovered_factions.append(disc.faction_b_id)
        else:
            discovered_factions.append(disc.faction_a_id)

    return {
        "faction_id": faction_id,
        "home_sector_id": home_sector_id,
        "territories": territories,
        "total_control": total_control,
        "total_influence": total_influence,
        "sector_count": sector_count,
        "discovered_factions": discovered_factions,
    }


# ---------------------------------------------------------------------------
# 3. Graph traversal
# ---------------------------------------------------------------------------


def are_sectors_adjacent(sector_a_id: str, sector_b_id: str) -> bool:
    if not is_spatial_enabled():
        return False
    adj = get_adjacency(sector_a_id, sector_b_id)
    if adj is not None:
        return True
    neighbors = get_adjacent_sector_ids(sector_a_id)
    return sector_b_id in neighbors


def get_path_between_sectors(start_id: str, end_id: str) -> List[str]:
    if not is_spatial_enabled():
        return []
    if start_id == end_id:
        return [start_id]

    all_ids = set(get_all_sector_ids())
    if start_id not in all_ids or end_id not in all_ids:
        logger.debug("Path request for unknown sector(s): %s -> %s", start_id, end_id)
        return []

    visited: Set[str] = {start_id}
    queue: deque[Tuple[str, List[str]]] = deque()
    queue.append((start_id, [start_id]))

    while queue:
        current, path = queue.popleft()
        neighbors = get_adjacent_sector_ids(current)
        for neighbor_id in neighbors:
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            new_path = path + [neighbor_id]
            if neighbor_id == end_id:
                return new_path
            queue.append((neighbor_id, new_path))

    logger.debug("No path found: %s -> %s", start_id, end_id)
    return []


def get_distance_between_sectors(start_id: str, end_id: str) -> int:
    path = get_path_between_sectors(start_id, end_id)
    if not path:
        return -1
    return len(path) - 1


# ---------------------------------------------------------------------------
# 4. Sector summaries
# ---------------------------------------------------------------------------


def get_sector_summary(sector_id: str) -> Optional[Dict]:
    if not is_spatial_enabled():
        return None
    sector = get_sector(sector_id)
    if sector is None:
        logger.debug("Sector not found for summary: %s", sector_id)
        return None

    territories = get_sector_territories(sector_id)
    npcs = get_npcs_in_sector(sector_id)
    adjacent_sectors = get_adjacent_sector_ids(sector_id)

    dominant_faction: Optional[str] = None
    if territories:
        dominant = max(territories, key=lambda t: t.control_level)
        dominant_faction = dominant.faction_id

    return {
        "sector": sector,
        "territories": territories,
        "npcs": npcs,
        "adjacent_sectors": adjacent_sectors,
        "dominant_faction": dominant_faction,
    }


# ---------------------------------------------------------------------------
# 5. System status
# ---------------------------------------------------------------------------


def get_spatial_status() -> Dict:
    enabled = is_spatial_enabled()
    sector_ids = get_all_sector_ids() if enabled else []
    adjacencies = get_all_adjacencies() if enabled else []
    homes = get_all_faction_homes() if enabled else []
    territories = get_all_territories() if enabled else []
    discoveries = get_all_discoveries() if enabled else []
    npc_locations = get_all_npc_locations() if enabled else []

    return {
        "enabled": enabled,
        "seeded": len(sector_ids) > 0,
        "sector_count": len(sector_ids),
        "adjacency_count": len(adjacencies),
        "faction_homes_count": len(homes),
        "territory_count": len(territories),
        "discovery_count": len(discoveries),
        "npc_location_count": len(npc_locations),
    }


def get_map_overview() -> Dict:
    if not is_spatial_enabled():
        return {"sectors": [], "faction_homes": [], "territories": []}

    sectors = get_all_sectors()
    sector_dicts = []
    for s in sectors:
        d = s.to_dict()
        d["adjacent_sector_ids"] = get_adjacent_sector_ids(s.id)
        sector_dicts.append(d)

    homes = get_all_faction_homes()
    home_dicts = [h.to_dict() for h in homes]

    territories = get_all_territories()
    territory_dicts = [t.to_dict() for t in territories]

    return {
        "sectors": sector_dicts,
        "faction_homes": home_dicts,
        "territories": territory_dicts,
    }
