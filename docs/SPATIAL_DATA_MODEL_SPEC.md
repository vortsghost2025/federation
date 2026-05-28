# SPATIAL DATA MODEL SPEC

**Status:** DESIGN ONLY  
**Date:** 2026-05-27  
**Architecture:** In-memory dataclasses + Redis (consistent with existing Federation backend)  
**No database migration required — persistence via Redis snapshots**  

---

## Design Principle

The Federation backend uses **in-memory dataclasses + Redis**, not SQLAlchemy, not a relational database. This spec follows that pattern. All new spatial structures are Python dataclasses with corresponding Redis keys. State is persisted through the existing snapshot mechanism.

---

## 1. Sector

The fundamental spatial unit. A named region of the map with fixed coordinates and adjacency.

### Dataclass

```python
@dataclass
class Sector:
    id: str                    # slug: "sol-prime", "helix", "the-veil"
    name: str                  # display: "Sol Prime", "Helix", "The Veil"
    x: float                   # map coordinate (canvas-centered, 0,0 = center)
    y: float                   # map coordinate
    region_type: str           # "core" | "inner" | "outer" | "frontier"
    resource_profile: str      # "research" | "military" | "economic" | "diplomatic" | "mixed"
    danger_level: int          # 0-10 (0 = safe core, 10 = hostile frontier)
    description: str           # flavor text for narrative generation
    adjacent_sector_ids: List[str]  # sectors reachable in 1 hop
```

### Redis Key

```
sector:{id}              → JSON of full Sector dataclass
sector:all               → SET of all sector IDs
sector:adjacency:{id}    → LIST of adjacent sector IDs (redundant with field, for fast lookup)
```

### Constraints

- `id` is immutable after creation
- `x`, `y` are fixed — sectors don't move
- `adjacent_sector_ids` must be symmetric: if A lists B, B lists A
- `danger_level` range: 0-10
- `resource_profile` affects what factions can extract — but is a static property of the sector itself

---

## 2. FactionHome

Permanent assignment of a faction to its home sector. Created at seed, never changed.

### Dataclass

```python
@dataclass
class FactionHome:
    faction_id: str            # references existing faction.id
    home_sector_id: str        # references Sector.id
    expansion_policy: str      # "aggressive" | "moderate" | "cautious" | "isolationist"
```

### Redis Key

```
faction_home:{faction_id}  → JSON of FactionHome dataclass
```

### Constraints

- One home per faction. One faction per home sector (for MVP).
- `home_sector_id` is immutable — a faction cannot lose its home.
- `expansion_policy` can be modified by AI decisions during simulation.
- Home sector always has `control_level = 100` and `influence_level = 100` for the home faction.

---

## 3. FactionTerritory

The core ownership/influence tracking structure. One record per faction per sector where they have any presence.

### Dataclass

```python
@dataclass
class FactionTerritory:
    faction_id: str            # references faction.id
    sector_id: str             # references Sector.id
    control_level: float       # 0-100: hard ownership (100 = sovereign, 50+ = majority, 0 = none)
    influence_level: float     # 0-100: soft influence (decays with distance from home)
    claim_type: str            # "home" | "colony" | "contested" | "occupied" | "neutral"
    last_contested_tick: int   # tick when contestation last occurred (0 = never)
```

### Redis Key

```
territory:{faction_id}:{sector_id}  → JSON of FactionTerritory dataclass
territory:sector:{sector_id}        → SET of faction_ids with any presence in this sector
territory:faction:{faction_id}      → SET of sector_ids where faction has any presence
```

### Ownership Rules

| Condition | Sector Status |
|-----------|---------------|
| Single faction control_level ≥ 50 | "Controlled by {faction}" |
| Two+ factions control_level ≥ 25 | "Contested" |
| All factions control_level < 25 | "Unclaimed" |
| Faction has claim_type = "home" | Always "Controlled" regardless of other values |

### Influence Decay

Influence decays with distance from home sector:

```
base_influence = 100
distance = shortest_path_hop_count(home_sector, target_sector)
distance_decay = 0.6 ^ distance   # 60% per hop
max_possible_influence = base_influence * distance_decay
```

So:
- Home sector: influence up to 100
- 1 hop away: influence up to 60
- 2 hops away: influence up to 36
- 3 hops away: influence up to 21.6
- 4 hops away: influence up to ~13

This naturally creates a "sphere of influence" that fades with distance.

### Control Level Changes

| Event | Control Change |
|-------|----------------|
| Faction NPC garrisons in sector | +2 per tick per garrison NPC |
| Faction NPC patrols through sector | +1 per tick per patrol NPC |
| Faction expansion action succeeds | +30 (one-time) |
| Rival faction espionage succeeds | -5 to target |
| Border skirmish lost | -10 |
| Colony established | +40 (one-time, then decays if ungarrisoned) |
| No faction NPC present in sector | -1 per tick (attrition, only below 50) |
| Contested sector conflict | Both sides lose -3 per tick |

---

## 4. NpcLocation

Tracks where each NPC is and where they're going.

### Dataclass

```python
@dataclass
class NpcLocation:
    npc_id: str                    # references existing Creature/NPC id
    sector_id: str                 # current sector
    x_offset: float                # visual position within sector (±25px from sector center)
    y_offset: float                # visual position within sector
    current_task: str              # "garrison" | "patrol" | "expedition" | "diplomacy" | "research" | "espionage"
    destination_sector_id: str     # null if stationary, target sector if moving
    movement_progress: float       # 0.0-1.0 (0 = just left, 1 = arrived)
    patrol_route: List[str]        # ordered sector IDs for patrol loop (empty if not patrolling)
```

### Redis Key

```
npc_location:{npc_id}         → JSON of NpcLocation dataclass
npc_location:sector:{sector_id}  → SET of npc_ids currently in this sector
```

### Task Definitions

| Task | Movement | Effect on Territory |
|------|----------|---------------------|
| `garrison` | Stationary in current sector | +2 control_level/tick for faction |
| `patrol` | Cycles through `patrol_route` sectors, 1 hop/tick | +1 influence_level/tick per sector visited |
| `expedition` | Moves toward unclaimed/frontier sector, 1 hop/tick | Discovers sector, may trigger discovery events |
| `diplomacy` | Moves toward target faction's home sector | Triggers contact/discovery when arrives |
| `research` | Stationary in current sector | Boosts sector resource output, no territory effect |
| `espionage` | Moves toward adjacent rival sector | -5 control_level to target faction on success (1/tick chance) |

### Movement Rules

- NPCs move 1 sector per tick
- Movement is along adjacency edges only
- `movement_progress` goes from 0.0 → 1.0 over 1 tick (for visual interpolation on frontend)
- When `movement_progress` reaches 1.0, NPC arrives: `sector_id = destination_sector_id`, `destination_sector_id = null`, `movement_progress = 0.0`
- NPCs cannot enter sectors with `danger_level > 8` unless on `expedition` task
- NPCs on `patrol` loop their route indefinitely

---

## 5. SectorAdjacency

The movement graph. Defines which sectors connect to which.

### Dataclass

```python
@dataclass
class SectorAdjacency:
    sector_a_id: str
    sector_b_id: str
    route_type: str           # "standard" | "wormhole" | "gate" | "hazardous"
    travel_cost: float        # multiplier on base movement cost (1.0 = standard, 2.0 = slow, 0.5 = fast/gate)
```

### Redis Key

```
adjacency:{sector_a_id}:{sector_b_id}  → JSON of SectorAdjacency dataclass
adjacency:all                           → SET of all "a:b" pairs
```

### Constraints

- Adjacency is symmetric — if A→B exists, B→A exists (same record)
- `route_type` affects narrative flavor and movement cost
- `travel_cost` modifies resource expenditure for expansion/NPC movement through this edge
- The adjacency graph must be connected (no isolated sectors)
- No self-loops

---

## 6. WorldDiscovery

Tracks contact state between faction pairs. Starts as `undiscovered` for all pairs, evolves through proximity and actions.

### Dataclass

```python
@dataclass
class WorldDiscovery:
    faction_a_id: str         # lower-ordered faction id (alphabetical for consistency)
    faction_b_id: str         # higher-ordered faction id
    state: str                # "undiscovered" | "detected" | "contacted" | "relations_open"
    discovered_tick: int      # tick when first detected
    contacted_tick: int       # tick when first contact made (0 if not yet)
    relations_open_tick: int  # tick when full relations established (0 if not yet)
    discovery_method: str     # "territory_adjacency" | "npc_encounter" | "broadcast" | "expedition"
```

### Redis Key

```
discovery:{faction_a_id}:{faction_b_id}  → JSON of WorldDiscovery dataclass
discovery:faction:{faction_id}           → SET of "other_faction_id:state" pairs
```

### State Transitions

```
undiscovered → detected     (territories become adjacent, or broadcast received)
detected → contacted        (NPC encounter in same/adjacent sector, or diplomacy mission arrives)
contacted → relations_open  (successful diplomatic interaction, or 5+ ticks of peaceful coexistence)
```

Transitions are **one-way**. Once detected, a faction pair never goes back to undiscovered. Once in relations_open, they stay there (but relations can deteriorate — that's the existing diplomacy system).

### Initial State

At seed, all faction pairs start as `undiscovered`. Factions in adjacent home sectors start as `detected` (they can see each other's territory border). Factions in the same ring as home sectors start as `undiscovered` but will naturally discover neighbors within ~10-20 ticks as they expand.

---

## 7. Redis Key Summary

| Key Pattern | Type | Value |
|-------------|------|-------|
| `sector:{id}` | STRING | JSON Sector dataclass |
| `sector:all` | SET | All sector IDs |
| `sector:adjacency:{id}` | LIST | Adjacent sector IDs |
| `faction_home:{faction_id}` | STRING | JSON FactionHome dataclass |
| `territory:{faction_id}:{sector_id}` | STRING | JSON FactionTerritory dataclass |
| `territory:sector:{sector_id}` | SET | Faction IDs with presence |
| `territory:faction:{faction_id}` | SET | Sector IDs where faction has presence |
| `npc_location:{npc_id}` | STRING | JSON NpcLocation dataclass |
| `npc_location:sector:{sector_id}` | SET | NPC IDs currently in sector |
| `adjacency:{sector_a}:{sector_b}` | STRING | JSON SectorAdjacency dataclass |
| `adjacency:all` | SET | All "a:b" pair strings |
| `discovery:{faction_a}:{faction_b}` | STRING | JSON WorldDiscovery dataclass |
| `discovery:faction:{faction_id}` | SET | "other_id:state" strings |

**Total new Redis keys:** ~21 sectors + 8 homes + ~40 territories + ~100 NPC locations + ~35 adjacencies + ~28 discoveries = **~232 keys**. Negligible memory impact.

---

## 8. Integration with Existing State

### 8.1 Existing Fields to Populate (No Longer Dead)

| Existing Field | New Source |
|----------------|------------|
| `Faction.influence_map` | Populate from `territory:*` Redis keys: `{sector_id: influence_level}` |
| `Faction.headquarters_location` | Set from `faction_home.home_sector_id` → `Sector.name` |
| `Creature.habitat` | Set from `npc_location.sector_id` → `Sector.name` |
| `Creature.spotted_locations` | Append `Sector.name` when NPC enters new sector |
| `GameState.discovered_sectors` | Count of sectors where any faction has control ≥ 1 |
| `npc_location:{cid}` (Redis) | Write actual sector name instead of "?" |

### 8.2 Existing Fields to Deprecate (Not Remove)

| Field | Reason | Replacement |
|-------|--------|-------------|
| `FederationCoreState.territory_size` | Scalar counter, not spatial | Sum of faction territory control_levels, or count of controlled sectors |
| `RivalFederation.territory` | Scalar counter | Count of sectors rival controls (if rivals get spatial presence in later phase) |

**No fields removed.** Backward compatibility preserved.

---

## 9. Seed Data: Sol-Inspired Sector Map

### 9.1 Sector Definitions

**Core Ring (3 sectors):**

| ID | Name | x | y | Region | Resource | Danger |
|----|------|---|---|--------|----------|--------|
| `sol-prime` | Sol Prime | 0 | 0 | core | mixed | 0 |
| `meridian` | Meridian | -60 | 35 | core | diplomatic | 0 |
| `crucible` | Crucible | 60 | 35 | core | military | 1 |

**Inner Ring (6 sectors):**

| ID | Name | x | y | Region | Resource | Danger |
|----|------|---|---|--------|----------|--------|
| `helix` | Helix | -110 | -65 | inner | research | 1 |
| `forge` | Forge | -130 | 40 | inner | economic | 2 |
| `bastion` | Bastion | -50 | 100 | inner | military | 1 |
| `archive` | Archive | 50 | 100 | inner | research | 1 |
| `prism` | Prism | 130 | 40 | inner | diplomatic | 2 |
| `harbor` | Harbor | 110 | -65 | inner | economic | 1 |

**Outer Ring (6 sectors):**

| ID | Name | x | y | Region | Resource | Danger |
|----|------|---|---|--------|----------|--------|
| `reach` | Reach | -170 | -100 | outer | mixed | 3 |
| `shroud` | Shroud | -200 | 60 | outer | research | 4 |
| `drift` | Drift | -100 | 180 | outer | economic | 3 |
| `pinnacle` | Pinnacle | 100 | 180 | outer | military | 3 |
| `veil` | Veil | 200 | 60 | outer | diplomatic | 4 |
| `expanse` | Expanse | 170 | -100 | outer | mixed | 3 |

**Frontier Ring (6 sectors):**

| ID | Name | x | y | Region | Resource | Danger |
|----|------|---|---|--------|----------|--------|
| `abyss` | Abyss | -240 | -160 | frontier | research | 7 |
| `fracture` | Fracture | -270 | 100 | frontier | mixed | 8 |
| `signal` | Signal | -160 | 280 | frontier | diplomatic | 6 |
| `ghost` | Ghost | 160 | 280 | frontier | economic | 6 |
| `threshold` | Threshold | 270 | 100 | frontier | military | 7 |
| `beyond` | Beyond | 240 | -160 | frontier | mixed | 9 |

**Total: 21 sectors**

### 9.2 Faction Home Assignments

| Faction | Home Sector | Expansion Policy |
|---------|-------------|------------------|
| Research Division | archive | moderate |
| Military Command | bastion | aggressive |
| Diplomatic Corps | prism | moderate |
| Economic Council | forge | moderate |
| Preservation Society | helix | cautious |
| Signal Collective | harbor | cautious |
| Frontier Vanguard | reach | aggressive |
| Deep Watch | shroud | isolationist |

### 9.3 Adjacency Map

```
Core → Inner connections:
  sol-prime ↔ helix, forge, bastion, archive, prism, harbor
  meridian ↔ helix, forge, bastion
  crucible ↔ archive, prism, harbor

Inner → Outer connections:
  helix ↔ reach, shroud
  forge ↔ shroud, drift
  bastion ↔ drift
  archive ↔ pinnacle
  prism ↔ pinnacle, veil
  harbor ↔ veil, expanse

Outer → Frontier connections:
  reach ↔ abyss
  shroud ↔ fracture
  drift ↔ signal
  pinnacle ↔ ghost
  veil ↔ threshold
  expanse ↔ beyond

Cross-connections (lateral):
  meridian ↔ sol-prime ↔ crucible (core ring)
  reach ↔ shroud ↔ drift ↔ pinnacle ↔ veil ↔ expanse (outer ring, partial)
  abyss ↔ fracture ↔ signal ↔ ghost ↔ threshold ↔ beyond (frontier ring, partial)
```

Note: Not every outer sector connects to its outer neighbor. Gaps create natural chokepoints and exploration incentives. The exact adjacency graph should be tuned for gameplay balance during implementation.

---

## 10. JSON Examples

### Sector JSON

```json
{
  "id": "archive",
  "name": "Archive",
  "x": 50,
  "y": 100,
  "region_type": "inner",
  "resource_profile": "research",
  "danger_level": 1,
  "description": "The greatest repository of knowledge in known space. Ancient data cores hum beneath crystal domes.",
  "adjacent_sector_ids": ["sol-prime", "crucible", "pinnacle"]
}
```

### FactionTerritory JSON

```json
{
  "faction_id": "research",
  "sector_id": "archive",
  "control_level": 100,
  "influence_level": 100,
  "claim_type": "home",
  "last_contested_tick": 0
}
```

### NpcLocation JSON

```json
{
  "npc_id": "dr-elara-voss",
  "sector_id": "archive",
  "x_offset": 12.5,
  "y_offset": -8.3,
  "current_task": "research",
  "destination_sector_id": null,
  "movement_progress": 0.0,
  "patrol_route": []
}
```

### WorldDiscovery JSON

```json
{
  "faction_a_id": "diplomatic",
  "faction_b_id": "research",
  "state": "relations_open",
  "discovered_tick": 12,
  "contacted_tick": 18,
  "relations_open_tick": 25,
  "discovery_method": "territory_adjacency"
}
```

---

## 11. Kill Switch Hierarchy

Three environment variables control the spatial system. See `docs/SPATIAL_TERRITORY_SYSTEM_PLAN.md` §11 and `docs/SPATIAL_MIGRATION_PLAN.md` §Kill Switch Hierarchy for full behavioral details.

| Variable | Default | Controls |
|----------|---------|----------|
| `SPATIAL_ENABLED` | `true` | Master switch — all spatial features off when false |
| `SPATIAL_RENDERING_ENABLED` | `true` | Real-sector rendering on starmap (Phase 3+) |
| `SPATIAL_MECHANICS_ENABLED` | `true` | Expansion, NPC movement, discovery mechanics (Phase 4+) |

When `SPATIAL_ENABLED=false`: all spatial Redis keys are ignored, API endpoints return empty arrays, NPCs have no sector assignments, and the simulation runs without spatial awareness.
