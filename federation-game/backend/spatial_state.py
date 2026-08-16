"""
Spatial territory system — Redis state management.

Provides read/write/serialize/deserialize for all spatial data in Redis.
Follows the existing pattern: JSON strings in Redis keys, lazy singleton
client, colon-separated key prefixes.

See docs/SPATIAL_DATA_MODEL_SPEC.md §7 for key schema.
"""

import json
import os
import threading
from typing import Dict, List, Optional, Set

import redis

from spatial_models import (
    Sector,
    FactionHome,
    FactionTerritory,
    NpcLocation,
    SectorAdjacency,
    WorldDiscovery,
)

# ---------------------------------------------------------------------------
# Redis client — thread-safe lazy singleton (matches npc_autonomy.py pattern)
# ---------------------------------------------------------------------------

_redis_client = None
_redis_lock = threading.Lock()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def is_spatial_enabled() -> bool:
    """Check master kill switch. Default True — spatial features on."""
    return os.environ.get("SPATIAL_ENABLED", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Key prefix constants
# ---------------------------------------------------------------------------

PREFIX_SECTOR = "sector:"
KEY_SECTOR_ALL = "sector:all"
PREFIX_SECTOR_ADJACENCY = "sector:adjacency:"

PREFIX_FACTION_HOME = "faction_home:"

PREFIX_TERRITORY = "territory:"
PREFIX_TERRITORY_SECTOR = "territory:sector:"
PREFIX_TERRITORY_FACTION = "territory:faction:"

PREFIX_NPC_LOCATION = "npc_location:"
PREFIX_NPC_LOCATION_SECTOR = "npc_location:sector:"

PREFIX_ADJACENCY = "adjacency:"
KEY_ADJACENCY_ALL = "adjacency:all"

PREFIX_DISCOVERY = "discovery:"
PREFIX_DISCOVERY_FACTION = "discovery:faction:"


# ---------------------------------------------------------------------------
# Sector operations
# ---------------------------------------------------------------------------


def save_sector(sector: Sector) -> None:
    r = get_redis()
    r.set(f"{PREFIX_SECTOR}{sector.id}", json.dumps(sector.to_dict()))
    r.sadd(KEY_SECTOR_ALL, sector.id)
    # Fast-lookup adjacency list (redundant with sector field, for Redis speed)
    r.delete(f"{PREFIX_SECTOR_ADJACENCY}{sector.id}")
    if sector.adjacent_sector_ids:
        r.rpush(f"{PREFIX_SECTOR_ADJACENCY}{sector.id}", *sector.adjacent_sector_ids)


def get_sector(sector_id: str) -> Optional[Sector]:
    r = get_redis()
    raw = r.get(f"{PREFIX_SECTOR}{sector_id}")
    if raw is None:
        return None
    return Sector.from_dict(json.loads(raw))


def get_all_sector_ids() -> List[str]:
    r = get_redis()
    return list(r.smembers(KEY_SECTOR_ALL))


def get_all_sectors() -> List[Sector]:
    ids = get_all_sector_ids()
    sectors = []
    for sid in ids:
        s = get_sector(sid)
        if s is not None:
            sectors.append(s)
    return sectors


def get_adjacent_sector_ids(sector_id: str) -> List[str]:
    r = get_redis()
    return r.lrange(f"{PREFIX_SECTOR_ADJACENCY}{sector_id}", 0, -1)


def sector_exists() -> bool:
    """Check if the spatial system has been seeded (at least one sector exists)."""
    r = get_redis()
    return r.scard(KEY_SECTOR_ALL) > 0


# ---------------------------------------------------------------------------
# FactionHome operations
# ---------------------------------------------------------------------------


def save_faction_home(home: FactionHome) -> None:
    r = get_redis()
    r.set(f"{PREFIX_FACTION_HOME}{home.faction_id}", json.dumps(home.to_dict()))


def get_faction_home(faction_id: str) -> Optional[FactionHome]:
    r = get_redis()
    raw = r.get(f"{PREFIX_FACTION_HOME}{faction_id}")
    if raw is None:
        return None
    return FactionHome.from_dict(json.loads(raw))


def get_all_faction_homes() -> List[FactionHome]:
    r = get_redis()
    keys = r.scan_iter(f"{PREFIX_FACTION_HOME}*", count=500)
    homes = []
    for key in keys:
        raw = r.get(key)
        if raw:
            homes.append(FactionHome.from_dict(json.loads(raw)))
    return homes


# ---------------------------------------------------------------------------
# FactionTerritory operations
# ---------------------------------------------------------------------------


def save_faction_territory(territory: FactionTerritory) -> None:
    r = get_redis()
    key = f"{PREFIX_TERRITORY}{territory.faction_id}:{territory.sector_id}"
    r.set(key, json.dumps(territory.to_dict()))
    # Index: which factions have presence in this sector
    r.sadd(f"{PREFIX_TERRITORY_SECTOR}{territory.sector_id}", territory.faction_id)
    # Index: which sectors does this faction have presence in
    r.sadd(f"{PREFIX_TERRITORY_FACTION}{territory.faction_id}", territory.sector_id)


def get_faction_territory(
    faction_id: str, sector_id: str
) -> Optional[FactionTerritory]:
    r = get_redis()
    raw = r.get(f"{PREFIX_TERRITORY}{faction_id}:{sector_id}")
    if raw is None:
        return None
    return FactionTerritory.from_dict(json.loads(raw))


def get_faction_territories(faction_id: str) -> List[FactionTerritory]:
    """Get all territory records for a faction."""
    r = get_redis()
    sector_ids = r.smembers(f"{PREFIX_TERRITORY_FACTION}{faction_id}")
    territories = []
    for sid in sector_ids:
        t = get_faction_territory(faction_id, sid)
        if t is not None:
            territories.append(t)
    return territories


def get_sector_territories(sector_id: str) -> List[FactionTerritory]:
    """Get all territory records for a sector (all factions present)."""
    r = get_redis()
    faction_ids = r.smembers(f"{PREFIX_TERRITORY_SECTOR}{sector_id}")
    territories = []
    for fid in faction_ids:
        t = get_faction_territory(fid, sector_id)
        if t is not None:
            territories.append(t)
    return territories


def get_all_territories() -> List[FactionTerritory]:
    """Get all territory records."""
    r = get_redis()
    keys = r.scan_iter(f"{PREFIX_TERRITORY}*", count=500)
    territories = []
    for key in keys:
        # Only parse keys that match "territory:{faction_id}:{sector_id}" pattern
        # Skip index keys: territory:sector:* and territory:faction:* (those are SETs, not strings)
        parts = key.split(":")
        if (
            len(parts) == 3
            and parts[0] == "territory"
            and parts[1] not in ("sector", "faction")
        ):
            raw = r.get(key)
            if raw:
                territories.append(FactionTerritory.from_dict(json.loads(raw)))
    return territories


# ---------------------------------------------------------------------------
# NpcLocation operations
# ---------------------------------------------------------------------------


def save_npc_location(loc: NpcLocation) -> None:
    r = get_redis()
    r.set(f"{PREFIX_NPC_LOCATION}{loc.npc_id}", json.dumps(loc.to_dict()))
    # Index: which NPCs are in this sector
    r.sadd(f"{PREFIX_NPC_LOCATION_SECTOR}{loc.sector_id}", loc.npc_id)


def get_npc_location(npc_id: str) -> Optional[NpcLocation]:
    r = get_redis()
    raw = r.get(f"{PREFIX_NPC_LOCATION}{npc_id}")
    if raw is None:
        return None
    return NpcLocation.from_dict(json.loads(raw))


def get_npcs_in_sector(sector_id: str) -> List[NpcLocation]:
    """Get all NPC locations for a given sector."""
    r = get_redis()
    npc_ids = r.smembers(f"{PREFIX_NPC_LOCATION_SECTOR}{sector_id}")
    locations = []
    for nid in npc_ids:
        loc = get_npc_location(nid)
        if loc is not None:
            locations.append(loc)
    return locations


def get_all_npc_locations() -> List[NpcLocation]:
    r = get_redis()
    keys = r.scan_iter(f"{PREFIX_NPC_LOCATION}*", count=500)
    locations = []
    for key in keys:
        # Only parse direct npc_location:{id} or npc_location:{type}:{id} keys
        # Skip index keys: npc_location:sector:* (those are SETs, not strings)
        parts = key.split(":")
        if len(parts) >= 2 and parts[0] == "npc_location" and parts[1] != "sector":
            raw = r.get(key)
            if raw:
                locations.append(NpcLocation.from_dict(json.loads(raw)))
    return locations


# ---------------------------------------------------------------------------
# SectorAdjacency operations
# ---------------------------------------------------------------------------


def save_adjacency(adj: SectorAdjacency) -> None:
    r = get_redis()
    # Store with canonical key (alphabetically ordered pair)
    a, b = sorted([adj.sector_a_id, adj.sector_b_id])
    key = f"{PREFIX_ADJACENCY}{a}:{b}"
    r.set(key, json.dumps(adj.to_dict()))
    r.sadd(KEY_ADJACENCY_ALL, f"{a}:{b}")


def get_adjacency(sector_a_id: str, sector_b_id: str) -> Optional[SectorAdjacency]:
    r = get_redis()
    a, b = sorted([sector_a_id, sector_b_id])
    raw = r.get(f"{PREFIX_ADJACENCY}{a}:{b}")
    if raw is None:
        return None
    return SectorAdjacency.from_dict(json.loads(raw))


def get_all_adjacencies() -> List[SectorAdjacency]:
    r = get_redis()
    pairs = r.smembers(KEY_ADJACENCY_ALL)
    adjs = []
    for pair_str in pairs:
        raw = r.get(f"{PREFIX_ADJACENCY}{pair_str}")
        if raw:
            adjs.append(SectorAdjacency.from_dict(json.loads(raw)))
    return adjs


# ---------------------------------------------------------------------------
# WorldDiscovery operations
# ---------------------------------------------------------------------------


def save_discovery(disc: WorldDiscovery) -> None:
    r = get_redis()
    key = f"{PREFIX_DISCOVERY}{disc.faction_a_id}:{disc.faction_b_id}"
    r.set(key, json.dumps(disc.to_dict()))
    # Per-faction index
    r.sadd(
        f"{PREFIX_DISCOVERY_FACTION}{disc.faction_a_id}",
        f"{disc.faction_b_id}:{disc.state}",
    )
    r.sadd(
        f"{PREFIX_DISCOVERY_FACTION}{disc.faction_b_id}",
        f"{disc.faction_a_id}:{disc.state}",
    )


def get_discovery(faction_a_id: str, faction_b_id: str) -> Optional[WorldDiscovery]:
    r = get_redis()
    a, b = sorted([faction_a_id, faction_b_id])
    raw = r.get(f"{PREFIX_DISCOVERY}{a}:{b}")
    if raw is None:
        return None
    return WorldDiscovery.from_dict(json.loads(raw))


def get_faction_discoveries(faction_id: str) -> List[WorldDiscovery]:
    """Get all discovery records involving a faction."""
    r = get_redis()
    entries = r.smembers(f"{PREFIX_DISCOVERY_FACTION}{faction_id}")
    discoveries = []
    for entry in entries:
        # entry format: "other_faction_id:state"
        other_id = entry.rsplit(":", 1)[0]
        disc = get_discovery(faction_id, other_id)
        if disc is not None:
            discoveries.append(disc)
    return discoveries


def get_all_discoveries() -> List[WorldDiscovery]:
    r = get_redis()
    keys = r.scan_iter(f"{PREFIX_DISCOVERY}*", count=500)
    discoveries = []
    for key in keys:
        # Only parse direct discovery:{a}:{b} keys
        # Skip index keys: discovery:faction:* (those are SETs, not strings)
        parts = key.split(":")
        if len(parts) == 3 and parts[0] == "discovery" and parts[1] != "faction":
            raw = r.get(key)
            if raw:
                discoveries.append(WorldDiscovery.from_dict(json.loads(raw)))
    return discoveries


# ---------------------------------------------------------------------------
# Bulk delete (for rollback / re-seed)
# ---------------------------------------------------------------------------


def delete_all_spatial_data() -> int:
    """Delete ALL spatial Redis keys. Returns count of keys deleted."""
    r = get_redis()
    patterns = [
        "sector:*",
        "faction_home:*",
        "territory:*",
        "npc_location:*",
        "adjacency:*",
        "discovery:*",
    ]
    deleted = 0
    for pattern in patterns:
        keys = list(r.scan_iter(pattern, count=500))
        if keys:
            deleted += r.delete(*keys)
    return deleted
