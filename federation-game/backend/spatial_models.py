"""
Spatial territory system data models.

Defines the 6 core dataclasses for the Federation spatial layer:
- Sector: the fundamental map unit
- FactionHome: permanent faction-to-sector assignment
- FactionTerritory: per-faction per-sector ownership/influence tracking
- NpcLocation: where NPCs are and where they're going
- SectorAdjacency: the movement graph between sectors
- WorldDiscovery: contact state between faction pairs

All structures follow the existing pattern: plain @dataclass, no ORM,
persistence via Redis JSON keys. See docs/SPATIAL_DATA_MODEL_SPEC.md.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 1. Sector — the map itself
# ---------------------------------------------------------------------------


@dataclass
class Sector:
    """A named region of the map with fixed coordinates and adjacency."""

    id: str  # slug: "sol-prime", "helix", "the-veil"
    name: str  # display: "Sol Prime", "Helix", "The Veil"
    x: float  # map coordinate (canvas-centered, 0,0 = center)
    y: float  # map coordinate
    region_type: str  # "core" | "inner" | "outer" | "frontier"
    resource_profile: (
        str  # "research" | "military" | "economic" | "diplomatic" | "mixed"
    )
    danger_level: int  # 0-10 (0 = safe core, 10 = hostile frontier)
    description: str  # flavor text for narrative generation
    adjacent_sector_ids: List[str] = field(
        default_factory=list
    )  # sectors reachable in 1 hop

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "region_type": self.region_type,
            "resource_profile": self.resource_profile,
            "danger_level": self.danger_level,
            "description": self.description,
            "adjacent_sector_ids": list(self.adjacent_sector_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Sector":
        return cls(
            id=data["id"],
            name=data["name"],
            x=data["x"],
            y=data["y"],
            region_type=data["region_type"],
            resource_profile=data["resource_profile"],
            danger_level=data.get("danger_level", 0),
            description=data.get("description", ""),
            adjacent_sector_ids=data.get("adjacent_sector_ids", []),
        )


# ---------------------------------------------------------------------------
# 2. FactionHome — permanent assignment
# ---------------------------------------------------------------------------


@dataclass
class FactionHome:
    """Permanent assignment of a faction to its home sector. Created at seed, never changed."""

    faction_id: str  # references existing faction.id
    home_sector_id: str  # references Sector.id
    expansion_policy: str = (
        "moderate"  # "aggressive" | "moderate" | "cautious" | "isolationist"
    )

    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "home_sector_id": self.home_sector_id,
            "expansion_policy": self.expansion_policy,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactionHome":
        return cls(
            faction_id=data["faction_id"],
            home_sector_id=data["home_sector_id"],
            expansion_policy=data.get("expansion_policy", "moderate"),
        )


# ---------------------------------------------------------------------------
# 3. FactionTerritory — ownership/influence tracking
# ---------------------------------------------------------------------------


@dataclass
class FactionTerritory:
    """Per faction per sector ownership and influence. One record per faction per sector
    where they have any presence."""

    faction_id: str  # references faction.id
    sector_id: str  # references Sector.id
    control_level: float = 0.0  # 0-100: hard ownership
    influence_level: float = (
        0.0  # 0-100: soft influence (decays with distance from home)
    )
    claim_type: str = (
        "neutral"  # "home" | "colony" | "contested" | "occupied" | "neutral"
    )
    last_contested_tick: int = 0  # tick when contestation last occurred (0 = never)

    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "sector_id": self.sector_id,
            "control_level": self.control_level,
            "influence_level": self.influence_level,
            "claim_type": self.claim_type,
            "last_contested_tick": self.last_contested_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactionTerritory":
        return cls(
            faction_id=data["faction_id"],
            sector_id=data["sector_id"],
            control_level=data.get("control_level", 0.0),
            influence_level=data.get("influence_level", 0.0),
            claim_type=data.get("claim_type", "neutral"),
            last_contested_tick=data.get("last_contested_tick", 0),
        )


# ---------------------------------------------------------------------------
# 4. NpcLocation — where NPCs are and where they're going
# ---------------------------------------------------------------------------


@dataclass
class NpcLocation:
    """Tracks where each NPC is and where they're heading."""

    npc_id: str  # references existing Creature/NPC id
    sector_id: str  # current sector
    x_offset: float = 0.0  # visual position within sector (±25px from sector center)
    y_offset: float = 0.0  # visual position within sector
    current_task: str = "garrison"  # "garrison" | "patrol" | "expedition" | "diplomacy" | "research" | "espionage"
    destination_sector_id: str = ""  # empty if stationary, target sector if moving
    movement_progress: float = 0.0  # 0.0-1.0 (0 = just left, 1 = arrived)
    patrol_route: List[str] = field(
        default_factory=list
    )  # ordered sector IDs for patrol loop

    def to_dict(self) -> dict:
        return {
            "npc_id": self.npc_id,
            "sector_id": self.sector_id,
            "x_offset": self.x_offset,
            "y_offset": self.y_offset,
            "current_task": self.current_task,
            "destination_sector_id": self.destination_sector_id,
            "movement_progress": self.movement_progress,
            "patrol_route": list(self.patrol_route),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NpcLocation":
        return cls(
            npc_id=data["npc_id"],
            sector_id=data["sector_id"],
            x_offset=data.get("x_offset", 0.0),
            y_offset=data.get("y_offset", 0.0),
            current_task=data.get("current_task", "garrison"),
            destination_sector_id=data.get("destination_sector_id", ""),
            movement_progress=data.get("movement_progress", 0.0),
            patrol_route=data.get("patrol_route", []),
        )


# ---------------------------------------------------------------------------
# 5. SectorAdjacency — the movement graph
# ---------------------------------------------------------------------------


@dataclass
class SectorAdjacency:
    """Defines which sectors connect to which. The movement graph."""

    sector_a_id: str
    sector_b_id: str
    route_type: str = "standard"  # "standard" | "wormhole" | "gate" | "hazardous"
    travel_cost: float = 1.0  # multiplier on base movement cost

    def to_dict(self) -> dict:
        return {
            "sector_a_id": self.sector_a_id,
            "sector_b_id": self.sector_b_id,
            "route_type": self.route_type,
            "travel_cost": self.travel_cost,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SectorAdjacency":
        return cls(
            sector_a_id=data["sector_a_id"],
            sector_b_id=data["sector_b_id"],
            route_type=data.get("route_type", "standard"),
            travel_cost=data.get("travel_cost", 1.0),
        )


# ---------------------------------------------------------------------------
# 6. WorldDiscovery — contact state between faction pairs
# ---------------------------------------------------------------------------


@dataclass
class WorldDiscovery:
    """Tracks contact state between faction pairs. Starts as 'undiscovered' for all pairs,
    evolves through proximity and actions. Transitions are one-way."""

    faction_a_id: str  # lower-ordered faction id (alphabetical for consistency)
    faction_b_id: str  # higher-ordered faction id
    state: str = (
        "undiscovered"  # "undiscovered" | "detected" | "contacted" | "relations_open"
    )
    discovered_tick: int = 0  # tick when first detected
    contacted_tick: int = 0  # tick when first contact made (0 if not yet)
    relations_open_tick: int = 0  # tick when full relations established (0 if not yet)
    discovery_method: str = (
        ""  # "territory_adjacency" | "npc_encounter" | "broadcast" | "expedition"
    )

    def to_dict(self) -> dict:
        return {
            "faction_a_id": self.faction_a_id,
            "faction_b_id": self.faction_b_id,
            "state": self.state,
            "discovered_tick": self.discovered_tick,
            "contacted_tick": self.contacted_tick,
            "relations_open_tick": self.relations_open_tick,
            "discovery_method": self.discovery_method,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldDiscovery":
        return cls(
            faction_a_id=data["faction_a_id"],
            faction_b_id=data["faction_b_id"],
            state=data.get("state", "undiscovered"),
            discovered_tick=data.get("discovered_tick", 0),
            contacted_tick=data.get("contacted_tick", 0),
            relations_open_tick=data.get("relations_open_tick", 0),
            discovery_method=data.get("discovery_method", ""),
        )
