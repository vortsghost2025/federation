"""
Spatial territory system — tick engine.
Implements the core spatial simulation that runs every tick.
"""

import os
import json
import random
import logging
from typing import Dict, List, Optional
from datetime import datetime

from spatial_state import (
    get_redis,
    save_faction_territory,
    get_faction_territories,
    get_sector_territories,
    get_all_territories,
    save_npc_location,
    get_npc_location,
    get_all_npc_locations,
    save_discovery,
    get_discovery,
    get_all_discoveries,
    get_all_sectors,
)
from spatial_queries import (
    get_faction_home,
    get_faction_sphere_of_influence,
    get_sector_by_id,
    get_adjacent_sector_ids,
    get_path_between_sectors,
    get_faction_discoveries,
)
from spatial_models import FactionTerritory, NpcLocation, WorldDiscovery
from map_endpoints import STATIC_FACTION_MAP

logger = logging.getLogger(__name__)
# Ensure spatial_tick logs are visible at INFO level
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(asctime)s [worker] %(levelname)s %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Constants for spatial tick mechanics
# Power values are floats (see faction_ai.py): 0-15 typical range, growing ~1-2.5 per NPC per tick
# Cohesion values: 0-100 scale (50 is neutral baseline)
EXPANSION_POWER_THRESHOLD = 8.0
EXPANSION_COHESION_THRESHOLD = 45
CONTRACTION_POWER_THRESHOLD = 3.0
CONTRACTION_COHESION_THRESHOLD = 25
BORDER_FRICTION_REDUCTION = 2
PATROL_TASK_CHANCE = 0.15  # 15% chance to start new task when idle
DISCOVERY_UNDISCOVERED_BASE_CHANCE = 0.02  # 2%
DISCOVERY_UNDISCOVERED_ADJACENT_CHANCE = 0.05  # 5%
DISCOVERY_DETECTED_TO_CONTACTED_CHANCE = 0.08  # 8%
DISCOVERY_CONTACTED_TO_OPEN_CHANCE = 0.10  # 10%
RESOURCE_DISCOVERY_CHANCE = 0.03  # 3%
RESOURCE_INFLUENCE_BONUS = 5
MAX_SPATIAL_EVENTS_PER_TICK = 2


# ---------------------------------------------------------------------------
# Auto-seed: ensure every known NPC has a spatial location entry
# ---------------------------------------------------------------------------

# Static faction→home sector map (matches spatial_seed.py FACTION_HOME_MAP)
_FACTION_HOME_SECTORS = {
    "diplomatic_corps": "prism",
    "military_command": "bastion",
    "cultural_ministry": "shroud",
    "research_division": "archive",
    "consciousness_collective": "harbor",
    "economic_council": "forge",
    "exploration_initiative": "reach",
    "preservation_society": "helix",
}

_auto_seed_done = False  # Only run once per process lifetime


def _resolve_npc_faction(npc_id: str, r=None) -> Optional[str]:
    """Resolve an NPC's faction using a consistent fallback chain.

    Order: STATIC_FACTION_MAP → npc_state:{id} hash → npc_faction_context:{id}
           → npc_profiles blob → None
    """
    # 1. Static map (canonical, no Redis needed)
    faction = STATIC_FACTION_MAP.get(npc_id)
    if faction:
        return faction

    # Lazy-init Redis if caller didn't pass it
    if r is None:
        try:
            r = get_redis()
        except Exception:
            return None

    # 2. npc_state hash
    try:
        faction = r.hget(f"npc_state:{npc_id}", "faction")
        if faction:
            return faction if isinstance(faction, str) else faction.decode()
    except Exception:
        pass

    # 3. npc_faction_context key
    try:
        fc_raw = r.get(f"npc_faction_context:{npc_id}")
        if fc_raw:
            fc_data = json.loads(fc_raw)
            faction = fc_data.get("faction")
            if faction:
                return faction
    except Exception:
        pass

    # 4. npc_profiles blob
    try:
        profiles_raw = r.get("npc_profiles")
        if profiles_raw:
            profiles = json.loads(profiles_raw)
            if isinstance(profiles, list):
                for p in profiles:
                    if p.get("id") == npc_id:
                        return p.get("faction_affiliation") or p.get("affiliation") or p.get("faction")
            elif isinstance(profiles, dict):
                pdata = profiles.get(npc_id, {})
                return pdata.get("faction_affiliation") or pdata.get("affiliation") or pdata.get("faction")
    except Exception:
        pass

    return None


def _resolve_all_npc_factions(r=None) -> Dict[str, str]:
    """Build a dict of {npc_id: faction} for all NPCs found in Redis + static map.

    More efficient than calling _resolve_npc_faction per-NPC when you need
    the full mapping (e.g. for discovery progression).
    """
    if r is None:
        try:
            r = get_redis()
        except Exception:
            return dict(STATIC_FACTION_MAP)

    result: Dict[str, str] = {}

    # Seed from static map first (fastest, no I/O)
    result.update(STATIC_FACTION_MAP)

    # Layer on npc_profiles blob (covers all NPCs in one read)
    try:
        profiles_raw = r.get("npc_profiles")
        if profiles_raw:
            profiles = json.loads(profiles_raw)
            if isinstance(profiles, list):
                for p in profiles:
                    pid = p.get("id")
                    if pid:
                        fac = p.get("faction_affiliation") or p.get("affiliation") or p.get("faction")
                        if fac:
                            result[pid] = fac
            elif isinstance(profiles, dict):
                for pid, pdata in profiles.items():
                    fac = pdata.get("faction_affiliation") or pdata.get("affiliation") or pdata.get("faction")
                    if fac:
                        result[pid] = fac
    except Exception:
        pass

    # Layer on npc_state:* hashes (most authoritative per-NPC)
    try:
        for key in r.keys("npc_state:*"):
            parts = key.split(":")
            if len(parts) == 2:
                npc_id = parts[1]
                fac = r.hget(key, "faction")
                if fac:
                    result[npc_id] = fac if isinstance(fac, str) else fac.decode()
    except Exception:
        pass

    return result


def _auto_seed_npc_locations() -> int:
    """Create NpcLocation entries for any known NPC missing from spatial system.

    Checks Redis npc_state:* keys and the static faction map for NPC IDs
    that don't yet have a npc_location:{id} entry, and creates them placed
    at their faction's home sector.
    """
    global _auto_seed_done
    if _auto_seed_done:
        return 0

    _auto_seed_done = True
    r = get_redis()
    seeded = 0

    try:
        # Collect all known NPC IDs from Redis
        npc_ids = set()

        # Source 1: npc_state:{id} keys
        state_keys = r.keys("npc_state:*")
        for key in state_keys:
            parts = key.split(":")
            if len(parts) == 2:
                npc_ids.add(parts[1])

        # Source 2: npc_faction_context:{id} keys
        fc_keys = r.keys("npc_faction_context:*")
        for key in fc_keys:
            parts = key.split(":")
            if len(parts) == 2:
                npc_ids.add(parts[1])

        # Source 3: static known NPCs
        npc_ids.update(STATIC_FACTION_MAP.keys())

        # Source 4: npc_profiles blob (list of dicts with "id" field)
        try:
            profiles_raw = r.get("npc_profiles")
            if profiles_raw:
                profiles = json.loads(profiles_raw)
                if isinstance(profiles, list):
                    for p in profiles:
                        pid = p.get("id")
                        if pid:
                            npc_ids.add(pid)
                elif isinstance(profiles, dict):
                    npc_ids.update(profiles.keys())
        except Exception:
            pass

        # Filter: only seed NPCs that don't already have a spatial location
        missing = []
        for npc_id in npc_ids:
            # Skip placeholder faction home reps (already seeded)
            if npc_id.startswith("faction_home_rep:"):
                continue
            existing = r.get(f"npc_location:{npc_id}")
            if existing is None:
                missing.append(npc_id)

        if not missing:
            return 0

        # Resolve faction for each missing NPC
        for npc_id in missing:
            faction = _resolve_npc_faction(npc_id, r)

            # Determine home sector
            if faction and faction in _FACTION_HOME_SECTORS:
                home_sector = _FACTION_HOME_SECTORS[faction]
            else:
                # No faction or unknown faction — assign to a random sector
                all_sectors = get_all_sectors()
                home_sector = random.choice([s.id for s in all_sectors]) if all_sectors else "alpha_prime"

            npc_loc = NpcLocation(
                npc_id=npc_id,
                sector_id=home_sector,
                current_task="garrison",
                movement_progress=0.0,
            )
            save_npc_location(npc_loc)
            seeded += 1

        if seeded > 0:
            logger.info(f"Auto-seeded {seeded} NPC locations into spatial system")

    except Exception as e:
        logger.warning(f"Auto-seed NPC locations failed: {e}", exc_info=True)

    return seeded


def run_spatial_tick(tick_count: int) -> Dict:
    """
    Run one tick of the spatial simulation.

    Args:
        tick_count: Current game tick number

    Returns:
        Dictionary with counts of what happened during the tick
    """
    if not _is_spatial_enabled():
        return {"events_generated": 0}

    # Initialize counters for return value
    result = {
        "territory_expansions": 0,
        "territory_contractions": 0,
        "border_clashes": 0,
        "npc_moves": 0,
        "npc_task_starts": 0,
        "discoveries_advanced": 0,
        "resource_discoveries": 0,
        "events_generated": 0
    }

    # Track events for spatial_events ZSET
    events_to_store = []

    try:
        # 0. Auto-seed NPC locations for any NPCs missing from spatial system
        seed_count = _auto_seed_npc_locations()
        if seed_count > 0:
            logger.info(f"Auto-seeded {seed_count} NPC spatial locations")

        # 1. Faction Territory Expansion/Contraction
        expansion_result = _process_faction_territory(tick_count)
        result["territory_expansions"] = expansion_result.get("expansions", 0)
        result["territory_contractions"] = expansion_result.get("contractions", 0)
        result["border_clashes"] = expansion_result.get("border_clashes", 0)
        events_to_store.extend(expansion_result.get("events", []))
        
        # 2. NPC Movement
        movement_result = _process_npc_movement(tick_count)
        result["npc_moves"] = movement_result.get("moves", 0)
        result["npc_task_starts"] = movement_result.get("task_starts", 0)
        events_to_store.extend(movement_result.get("events", []))
        
        # 3. Discovery Progression
        discovery_result = _process_discovery_progression(tick_count)
        result["discoveries_advanced"] = discovery_result.get("advanced", 0)
        events_to_store.extend(discovery_result.get("events", []))
        
        # 4. Resource Discovery
        resource_result = _process_resource_discovery(tick_count)
        result["resource_discoveries"] = resource_result.get("discoveries", 0)
        events_to_store.extend(resource_result.get("events", []))
        
        # 5. Spatial Events (store generated events)
        if events_to_store:
            # Limit to max events per tick
            events_to_store = events_to_store[:MAX_SPATIAL_EVENTS_PER_TICK]
            _store_spatial_events(events_to_store)
            result["events_generated"] = len(events_to_store)
            
            # Publish to federation:updates channel
            _publish_spatial_update(len(events_to_store))
        
        logger.info(
            f"Spatial tick {tick_count}: "
            f"{result['territory_expansions']} expansions, "
            f"{result['territory_contractions']} contractions, "
            f"{result['border_clashes']} border clashes, "
            f"{result['npc_moves']} NPC moves, "
            f"{result['npc_task_starts']} new NPC tasks, "
            f"{result['discoveries_advanced']} discoveries advanced, "
            f"{result['resource_discoveries']} resource discoveries, "
            f"{result['events_generated']} events generated"
        )
        
    except Exception as e:
        logger.warning(f"Spatial tick {tick_count} encountered error: {e}", exc_info=True)
    
    return result


def _is_spatial_enabled() -> bool:
    """Check if spatial features are enabled."""
    return os.getenv("SPATIAL_ENABLED", "true").lower() in ("true", "1", "yes")


def _get_faction_power(faction_id: str) -> float:
    """Get faction power from Redis (stored as float by faction_ai.py)."""
    try:
        r = get_redis()
        power_str = r.get(f"faction_power:{faction_id}")
        return float(power_str) if power_str is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def _get_faction_cohesion(faction_id: str) -> int:
    """Get faction cohesion from Redis faction_dynamics hash."""
    try:
        r = get_redis()
        cohesion_str = r.hget("faction_dynamics", f"{faction_id}:cohesion")
        return int(float(cohesion_str)) if cohesion_str is not None else 50
    except (ValueError, TypeError):
        return 50


def _get_faction_stance(faction_id: str, target_faction_id: str) -> str:
    """Get stance between two factions from Redis."""
    try:
        r = get_redis()
        # Check both directions since stance might be stored either way
        stance = r.hget(f"faction_stances:{faction_id}", target_faction_id)
        if stance is None:
            stance = r.hget(f"faction_stances:{target_faction_id}", faction_id)
        return stance or "neutral"
    except Exception:
        return "neutral"


def _process_faction_territory(tick_count: int) -> Dict[str, int]:
    """Process faction territory expansion and contraction."""
    result = {
        "expansions": 0,
        "contractions": 0,
        "border_clashes": 0,
        "events": []
    }
    
    try:
        # Get all faction homes to know which factions to process
        from spatial_state import get_all_faction_homes
        faction_homes = get_all_faction_homes()
        
        for home in faction_homes:
            faction_id = home.faction_id
            power = _get_faction_power(faction_id)
            cohesion = _get_faction_cohesion(faction_id)
            
            # Get current territories for this faction
            territories = get_faction_territories(faction_id)
            territory_dict = {t.sector_id: t for t in territories}
            
            # Expansion logic
            if power > EXPANSION_POWER_THRESHOLD and cohesion > EXPANSION_COHESION_THRESHOLD:
                expansion_chance = min(0.1 + (power - EXPANSION_POWER_THRESHOLD) * 0.02, 0.3)  # Scales with power
                if random.random() < expansion_chance:
                    # Try to expand into adjacent sectors
                    home_sector = get_faction_home(faction_id)
                    if home_sector:
                        adjacent_ids = get_adjacent_sector_ids(home_sector.home_sector_id)
                        # Also check adjacency of current territories for expansion
                        for territory in territories:
                            adj_ids = get_adjacent_sector_ids(territory.sector_id)
                            adjacent_ids.extend(adj_ids)
                        adjacent_ids = list(set(adjacent_ids))  # Deduplicate
                        
                        for sector_id in adjacent_ids:
                            # Skip if already controlled by this faction
                            if sector_id in territory_dict:
                                continue
                                
                            # Check if sector is unclaimed or weakly held
                            sector_territories = get_sector_territories(sector_id)
                            max_control = max((t.control_level for t in sector_territories), default=0)
                            
                            if max_control < 20:  # Unclaimed or weakly held
                                # Create new territory
                                new_territory = FactionTerritory(
                                    faction_id=faction_id,
                                    sector_id=sector_id,
                                    control_level=15.0,
                                    influence_level=10.0,
                                    claim_type="contested" if len(sector_territories) > 0 else "colony",
                                    last_contested_tick=tick_count
                                )
                                save_faction_territory(new_territory)
                                result["expansions"] += 1
                                
                                # Add territory_gained event
                                result["events"].append({
                                    "type": "territory_gained",
                                    "faction_id": faction_id,
                                    "sector_id": sector_id,
                                    "tick": tick_count
                                })
                                break  # Only one expansion per faction per tick for now
            
            # Contraction logic
            if power < CONTRACTION_POWER_THRESHOLD or cohesion < CONTRACTION_COHESION_THRESHOLD:
                # Check frontier and outer sectors for contraction
                for territory in territories[:]:  # Copy list to allow modification during iteration
                    sector = get_sector_by_id(territory.sector_id)
                    if sector and sector.region_type in ["frontier", "outer"]:
                        # Reduce control by 5-10
                        reduction = random.uniform(5.0, 10.0)
                        territory.control_level = max(0.0, territory.control_level - reduction)
                        
                        if territory.control_level <= 0.0:
                            # Remove territory
                            r = get_redis()
                            key = f"territory:{faction_id}:{territory.sector_id}"
                            r.delete(key)
                            # Also update indices
                            r.srem(f"territory:sector:{territory.sector_id}", faction_id)
                            r.srem(f"territory:faction:{faction_id}", territory.sector_id)
                            result["contractions"] += 1
                            
                            # Add territory_lost event
                            result["events"].append({
                                "type": "territory_lost",
                                "faction_id": faction_id,
                                "sector_id": territory.sector_id,
                                "tick": tick_count
                            })
                        else:
                            # Save updated territory
                            save_faction_territory(territory)
            
            # Border friction: check for contested sectors with hostile/tense factions
            for territory in territories:
                sector_territories = get_sector_territories(territory.sector_id)
                if len(sector_territories) > 1:
                    # Multiple factions in same sector - check for hostilities
                    for other_territory in sector_territories:
                        if other_territory.faction_id != faction_id:
                            stance = _get_faction_stance(faction_id, other_territory.faction_id)
                            if stance in ["hostile", "tense"]:
                                # Reduce both control levels by border friction
                                territory.control_level = max(0.0, territory.control_level - BORDER_FRICTION_REDUCTION)
                                other_territory.control_level = max(0.0, other_territory.control_level - BORDER_FRICTION_REDUCTION)
                                
                                save_faction_territory(territory)
                                save_faction_territory(other_territory)
                                
                                result["border_clashes"] += 1
                                
                                # Add border_clash event (only add once per sector pair)
                                if faction_id < other_territory.faction_id:  # Avoid duplicates
                                    result["events"].append({
                                        "type": "border_clash",
                                        "faction_a_id": faction_id,
                                        "faction_b_id": other_territory.faction_id,
                                        "sector_id": territory.sector_id,
                                        "tick": tick_count
                                    })
                                break  # Only process one conflict per territory for now
        
    except Exception as e:
        logger.warning(f"Error in faction territory processing: {e}", exc_info=True)
    
    return result


def _process_npc_movement(tick_count: int) -> Dict[str, int]:
    """Process NPC movement and task initiation."""
    result = {
        "moves": 0,
        "task_starts": 0,
        "events": []
    }
    
    try:
        npcs = get_all_npc_locations()

        for npc in npcs:
            # Look up the NPC's faction from Redis, then get faction home sector
            home_sector_id = None
            try:
                npc_faction = _resolve_npc_faction(npc.npc_id, get_redis())
                if npc_faction:
                    fh = get_faction_home(npc_faction)
                    if fh:
                        home_sector_id = fh.home_sector_id
            except Exception:
                pass

            # If we still don't have a home sector, use the NPC's current sector
            if not home_sector_id:
                home_sector_id = npc.sector_id

            # Handle patrol progress
            if npc.current_task == "patrol" and npc.patrol_route:
                progress_increment = random.uniform(0.15, 0.25)
                npc.movement_progress += progress_increment

            # Handle traveling progress
            elif npc.current_task == "traveling" and npc.destination_sector_id:
                progress_increment = random.uniform(0.1, 0.2)
                npc.movement_progress += progress_increment

            # Check if movement has completed (applies to both patrol and traveling)
            if npc.movement_progress >= 1.0 and npc.destination_sector_id:
                old_sector = npc.sector_id
                npc.sector_id = npc.destination_sector_id

                # Rotate patrol route: append origin, set next destination
                if npc.current_task == "patrol" and npc.patrol_route:
                    npc.patrol_route.append(old_sector)
                    next_dest = npc.patrol_route.pop(0)
                    npc.destination_sector_id = next_dest
                    npc.movement_progress = 0.0
                    # NPC stays on patrol duty
                else:
                    # Traveling/exploring NPC arrives — go idle
                    npc.destination_sector_id = ""
                    npc.movement_progress = 0.0
                    npc.current_task = "idle"

                # Update Redis sector index
                r = get_redis()
                r.srem(f"npc_location:sector:{old_sector}", npc.npc_id)
                r.sadd(f"npc_location:sector:{npc.sector_id}", npc.npc_id)
                result["moves"] += 1

            # Handle idle NPCs starting new tasks
            if npc.current_task in ["idle", "garrison"] or not npc.current_task:
                # 15% chance to start a new task
                if random.random() < PATROL_TASK_CHANCE and home_sector_id:
                    task_type = random.choice(["patrol", "traveling", "exploring"])

                    if task_type == "patrol":
                        # Pick 2-4 adjacent sectors from home as route
                        adjacent = get_adjacent_sector_ids(home_sector_id)
                        if len(adjacent) >= 2:
                            route_size = random.randint(2, min(4, len(adjacent)))
                            npc.patrol_route = random.sample(adjacent, route_size)
                            npc.current_task = "patrol"
                            npc.movement_progress = 0.0
                            # Set first sector as destination
                            if npc.patrol_route:
                                npc.destination_sector_id = npc.patrol_route[0]

                    elif task_type == "traveling":
                        # Pick a random adjacent sector as destination
                        adjacent = get_adjacent_sector_ids(home_sector_id)
                        if adjacent:
                            npc.destination_sector_id = random.choice(adjacent)
                            npc.current_task = "traveling"
                            npc.movement_progress = 0.0

                    elif task_type == "exploring":
                        # Pick a frontier sector as destination
                        all_sectors = [s.id for s in get_all_sectors() if s.region_type == "frontier"]
                        if not all_sectors:
                            all_sectors = [s.id for s in get_all_sectors()]
                        if all_sectors:
                            npc.destination_sector_id = random.choice(all_sectors)
                            npc.current_task = "traveling"
                            npc.movement_progress = 0.0

                    if npc.current_task != "idle":
                        result["task_starts"] += 1

            # Save NPC location (progress, sector, or task changes)
            save_npc_location(npc)

    except Exception as e:
        logger.warning(f"Error in NPC movement processing: {e}", exc_info=True)

    return result


def _process_discovery_progression(tick_count: int) -> Dict[str, int]:
    """Process discovery state progression."""
    result = {
        "advanced": 0,
        "events": []
    }
    
    try:
        discoveries = get_all_discoveries()
        # Cache NPC locations once for all discovery checks
        all_npcs_cache = None
        
        for discovery in discoveries:
            advanced = False
            
            if discovery.state == "undiscovered":
                # Check if factions have territories in adjacent sectors
                faction_a_home = get_faction_home(discovery.faction_a_id)
                faction_b_home = get_faction_home(discovery.faction_b_id)
                
                adjacent = False
                if faction_a_home and faction_b_home:
                    a_adjacent = get_adjacent_sector_ids(faction_a_home.home_sector_id)
                    b_adjacent = get_adjacent_sector_ids(faction_b_home.home_sector_id)
                    
                    # Check if any sector in a's adjacency is in b's territories or vice versa
                    a_territories = get_faction_territories(discovery.faction_a_id)
                    b_territories = get_faction_territories(discovery.faction_b_id)
                    
                    a_sector_ids = {t.sector_id for t in a_territories}
                    b_sector_ids = {t.sector_id for t in b_territories}
                    
                    # Check adjacency between territories
                    for a_sector in a_sector_ids:
                        a_adj = get_adjacent_sector_ids(a_sector)
                        if any(sector in b_sector_ids for sector in a_adj):
                            adjacent = True
                            break
                    
                    if not adjacent:
                        for b_sector in b_sector_ids:
                            b_adj = get_adjacent_sector_ids(b_sector)
                            if any(sector in a_sector_ids for sector in b_adj):
                                adjacent = True
                                break
                
                chance = DISCOVERY_UNDISCOVERED_ADJACENT_CHANCE if adjacent else DISCOVERY_UNDISCOVERED_BASE_CHANCE
                if random.random() < chance:
                    discovery.state = "detected"
                    discovery.discovered_tick = tick_count
                    discovery.discovery_method = "territory_adjacency"
                    advanced = True

            elif discovery.state == "detected":
                # Check if any NPC from either faction is in a sector adjacent to the other faction's territory
                if all_npcs_cache is None:
                    all_npcs_cache = get_all_npc_locations()

                # Resolve NPC→faction mapping from Redis
                r = get_redis()
                npc_faction_map = _resolve_all_npc_factions(r)

                faction_a_npcs = [npc for npc in all_npcs_cache
                                if npc_faction_map.get(npc.npc_id) == discovery.faction_a_id]
                faction_b_npcs = [npc for npc in all_npcs_cache
                                if npc_faction_map.get(npc.npc_id) == discovery.faction_b_id]
                
                faction_a_territories = {t.sector_id for t in get_faction_territories(discovery.faction_a_id)}
                faction_b_territories = {t.sector_id for t in get_faction_territories(discovery.faction_b_id)}
                
                adjacent_found = False
                # Check A's NPCs near B's territory
                for npc in faction_a_npcs:
                    npc_adjacent = get_adjacent_sector_ids(npc.sector_id)
                    if any(sector in faction_b_territories for sector in npc_adjacent):
                        adjacent_found = True
                        break
                
                # Check B's NPCs near A's territory
                if not adjacent_found:
                    for npc in faction_b_npcs:
                        npc_adjacent = get_adjacent_sector_ids(npc.sector_id)
                        if any(sector in faction_a_territories for sector in npc_adjacent):
                            adjacent_found = True
                            break
                
                if adjacent_found and random.random() < DISCOVERY_DETECTED_TO_CONTACTED_CHANCE:
                    discovery.state = "contacted"
                    discovery.contacted_tick = tick_count
                    advanced = True

            if advanced:
                save_discovery(discovery)
                result["advanced"] += 1
                
                # Add discovery_made event
                result["events"].append({
                    "type": "discovery_made",
                    "faction_a_id": discovery.faction_a_id,
                    "faction_b_id": discovery.faction_b_id,
                    "new_state": discovery.state,
                    "tick": tick_count
                })
    except Exception as e:
            logger.warning(f"Error in discovery progression processing: {e}", exc_info=True)
    
    return result


def _process_resource_discovery(tick_count: int) -> Dict[str, int]:
    """Process resource discovery events."""
    result = {
        "discoveries": 0,
        "events": []
    }
    
    try:
        # Get all territories with significant control (>30)
        territories = get_all_territories()
        significant_territories = [t for t in territories if t.control_level > 30]
        
        for territory in significant_territories:
            sector = get_sector_by_id(territory.sector_id)
            faction_home = get_faction_home(territory.faction_id)
            
            if sector and faction_home:
                # Check if resource profile matches faction interests
                # For simplicity, we'll assume all factions have interest in all resource types
                # In a real implementation, we'd check faction traits/policies
                if random.random() < RESOURCE_DISCOVERY_CHANCE:
                    # Increase influence level
                    territory.influence_level = min(100.0, territory.influence_level + RESOURCE_INFLUENCE_BONUS)
                    save_faction_territory(territory)
                    
                    result["discoveries"] += 1
                    
                    # Add resource_found event
                    result["events"].append({
                        "type": "resource_found",
                        "faction_id": territory.faction_id,
                        "sector_id": territory.sector_id,
                        "resource_type": sector.resource_profile,
                        "tick": tick_count
                    })
    
    except Exception as e:
        logger.warning(f"Error in resource discovery processing: {e}", exc_info=True)
    
    return result


def _store_spatial_events(events: List[Dict]) -> None:
    """Store spatial events in Redis ZSET."""
    try:
        r = get_redis()
        timestamp = datetime.utcnow().timestamp()
        
        for event in events:
            # Add to spatial_events ZSET with timestamp as score
            event_json = json.dumps(event)
            r.zadd("spatial_events", {event_json: timestamp})
            
            # Also keep only recent events (last 1000)
            r.zremrangebyrank("spatial_events", 0, -1001)
    
    except Exception as e:
        logger.warning(f"Failed to store spatial events: {e}")


def _publish_spatial_update(event_count: int) -> None:
    """Publish spatial update to federation:updates channel."""
    try:
        r = get_redis()
        message = json.dumps({
            "type": "spatial:update",
            "events": event_count,
            "timestamp": datetime.utcnow().isoformat()
        })
        r.publish("federation:updates", message)
    
    except Exception as e:
        logger.warning(f"Failed to publish spatial update: {e}")


if __name__ == "__main__":
    # For testing purposes
    logging.basicConfig(level=logging.DEBUG)
    result = run_spatial_tick(1)
    print(f"Spatial tick result: {result}")