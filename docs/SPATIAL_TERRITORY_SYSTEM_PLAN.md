# SPATIAL-00: Real Faction Territory and Sector Geography Layer

**Status:** DESIGN ONLY — no code, no migration, no frontend changes until operator approves  
**Date:** 2026-05-27  
**Scope:** Foundation architecture for real spatial simulation  

---

## 1. Current-State Confirmation

### 1.1 Files That Fake Starmap Positions

All spatial rendering in the starmap is a client-side illusion. No coordinates come from the backend.

| File | Lines | What It Does |
|------|-------|--------------|
| `frontend/starmap.html` — `hashStr()` | 877 | DJB-style string hash → deterministic seed |
| `frontend/starmap.html` — `seededRand()` | 882-884 | LCG pseudo-random from hash seed |
| `frontend/starmap.html` — `buildNodes()` | 1024+ | Master layout: 8 factions in a circle, NPCs orbit their faction center |
| `frontend/starmap.html` — `FACTION_ORDER` | 767-771 | Hardcoded 8-faction circular ordering |
| `frontend/starmap.html` — `FACTION_DISPLAY` | 774-783 | Hardcoded display names map |

**Placement algorithm:** 8 factions evenly spaced on a circle at `radius = min(W,H) * 0.35`. Each NPC orbits its faction center with seeded-random jitter. Rivals placed at 1.35× radius. Neutrals at 0.3-0.8×. Enigmas at 0.8-1.3×.

**Territory polygon pipeline:** `factionNodePositions → convexHull() → padPolygon() → smoothPoly(Chaikin, 2 iterations)`. Living deformation adds per-vertex wobble modulated by `activity + influence + cohesion`. Contested zones detected via `polygonsOverlap()`. Three view modes: Territory, Network, Crisis.

**None of this reflects simulation state.** It is deterministic visual decoration.

### 1.2 Backend Schema Fields — All Stubbed or Decorative

| Field | Model | Type | Status |
|-------|-------|------|--------|
| `Faction.influence_map` | federation_game_factions.py:166 | `Dict[str, float]` | **DEAD** — initialized `{}`, never read or written |
| `Faction.headquarters_location` | federation_game_factions.py:127,134 | `str` | **Flavor only** — "Research Tower", "Command Bunker" |
| `FederationCoreState.territory_size` | federation_game_state.py:53 | `float = 100.0` | **Scalar counter** — modified by history arc, not spatial |
| `Creature.habitat` | federation_game_npcs.py:369 | `str = ""` | **Flavor only** — "High altitude clouds" |
| `Creature.spotted_locations` | federation_game_npcs.py:381 | `List[str]` | **DEAD** — never populated |
| `GameState.discovered_sectors` | main.py:204 | `int = 1` | **Scalar counter** — incremented by quests, not spatial |
| `RivalFederation.territory` | federation_game_rival_simulator.py:119 | `int` | **Scalar counter** — e.g. 8, 12, 6 |
| `RivalFederation.domain` | federation_game_rival_simulator.py:122 | `str` | **Flavor only** — "Physical reality" |

**Redis dead key:** `npc_location:{cid}` — READ in `_build_sim_context()` (map_endpoints.py:1266) but NEVER WRITTEN. Always returns "?".

**NPC flavor templates:** `npc_autonomy.py:650-697` has `FILL_VALUES["sector"]` = `["7-Alpha", "12-Gamma", "3-Omega", "9-Delta", "the Veil"]` — text fillers for narrative, no spatial state.

**No database schema exists.** All state is in-memory dataclasses + Redis. No alembic, no SQLAlchemy, no migrations, no JSON seed files with spatial data.

### 1.3 APIs That Would Need to Change

| Endpoint | Current Shape | Missing |
|----------|---------------|---------|
| `/map/data` | `{world_state, npcs, factions, events, worker, broadcasts, history, crisis_readout}` | No x/y, no sector, no region, no territory geometry |
| `/simulation/factions` | Faction detail with cohesion, influence, standing, vigilance, moods, stances | No territory geometry, no region assignments, no home sector |
| `/simulation/npcs/activity` | NPC activity data | No location, no sector, no destination |
| `GET /factions` | Only endpoint exposing `headquarters_location` (flavor string) | No spatial coordinates |
| `POST /map/assistant` | Reads `npc_location:{cid}` (always "?") | Dead Redis key |

### 1.4 Simulation Mechanics — Zero Spatial Awareness

The worker tick loop (worker.py:604-813) runs 7 steps per tick. **None reference spatial state.** The autonomous tick runs 13+ substeps. **None reference spatial state.**

Faction interactions are driven by:
- `FACTION_IDEOLOGY_AFFINITY` matrix (8×8 ideology similarity) — not geography
- `affiliation` data property set at NPC creation — not location
- `explore_territory` action in `faction_ai.py:62,623` — exists but is a text stub
- `territory_size += pop_rep * 5.0` in history arc — scalar counter, not geometry

**Diagnosis:** Everyone is "near" everyone because space is fake. Distance doesn't affect diplomacy, trade, war, or events. Factions interact based on ideology alone, not proximity.

---

## 2. Spatial Model Options

### Option A: Discrete Sectors/Grid

```
Map = fixed set of named sectors
Sector = atomic unit of territory
NPC location = sector_id
Movement = hop from sector to adjacent sector
```

**Pros:** Simple to implement, easy to reason about, clear game mechanics (claim sector, defend sector), straightforward API, intuitive for players.  
**Cons:** Rigid, no intra-sector variation, visual rendering constrained to grid/sprite placement, expansion is binary (you own it or you don't).

### Option B: Continuous Coordinates

```
Map = 2D coordinate space
NPC location = (x, y)
Territory = polygon defined by influence thresholds
Movement = free navigation
```

**Pros:** Organic visuals, smooth territory borders, granular positioning.  
**Cons:** Complex pathfinding, hard to define "ownership" precisely, expensive computation for influence decay over distance, difficult to reason about for game mechanics, NPC navigation needs full pathfinding.

### Option C: Hybrid (Sector + Coordinate)

```
Map = named sectors with center coordinates
Sector = discrete game unit (ownership, control, resources)
Coordinate = visual placement within sector for rendering
Influence = soft layer (0-100) per faction per sector
NPC location = sector_id + (x_offset, y_offset) for rendering
Movement = sector-to-sector hops, with visual interpolation
```

**Pros:** Best of both — clean game mechanics from sectors, organic visuals from coordinates, influence gradient allows contested territory, easy to extend.  
**Cons:** More schema complexity than pure discrete, need to manage two levels of position.

---

### **RECOMMENDATION: Option C — Hybrid**

Rationale:
- Sectors give clean gameplay (claim, defend, expand, lose)
- Coordinates give organic starmap rendering (not a grid)
- Influence gradient gives contested borders (not binary ownership)
- The existing frontend territory rendering pipeline (convex hull → pad → smooth → breathe) can ingest real sector coordinates as polygon vertices instead of fake NPC positions
- Extensible: can add routes, adjacency, distance-based modifiers without re-architecting

---

## 3. Recommended MVP

### 3.1 Sectors/Regions

A Sol-system-inspired map with named sectors. Not Earth/Mars/Venus literally — but analogous regions with character.

**MVP: 21 sectors** (expandable to 24 in later phases by adding frontier sectors) arranged in 3 concentric rings + a deep frontier:

```
Ring 0 — Core (3 sectors):    Sol Prime, Meridian, Crucible
Ring 1 — Inner (6 sectors):   Helix, Forge, Bastion, Archive, Prism, Harbor
Ring 2 — Outer (6 sectors):   Reach, Shroud, Drift, Pinnacle, Veil, Expanse
Ring 3 — Frontier (6 sectors, expandable to 9): Abyss, Fracture, Signal, Ghost, Threshold, Beyond
```

Each sector has:
- `id` (slug), `name` (display), `x`, `y` (map coordinates)
- `region_type` (core, inner, outer, frontier)
- `resource_profile` (what it produces — research, military, economic, diplomatic)
- `danger_level` (0-10, affects NPC risk, event intensity)
- `adjacent_sectors` (list of sector_ids — for movement and expansion)

### 3.2 Faction Home Territories

Each of the 8 factions gets a home sector in Ring 0 or Ring 1:

| Faction | Home Sector | Region | Resource Match |
|---------|-------------|--------|----------------|
| Research Division | Archive | Inner | research |
| Military Command | Bastion | Inner | military |
| Diplomatic Corps | Prism | Inner | diplomatic |
| Economic Council | Forge | Inner | economic |
| Preservation Society | Helix | Inner | research |
| Signal Collective | Harbor | Inner | economic |
| Frontier Vanguard | Reach | Outer | mixed |
| Deep Watch | Shroud | Outer | research |

**Design principle:** Home sectors are permanent. A faction can never lose its home. Other territories are contestable.

### 3.3 NPC Location

Every NPC gets:
- `current_sector_id` — where they are now
- `x_offset`, `y_offset` — visual jitter within sector (for rendering)
- `current_task` — what they're doing (garrison, patrol, expedition, diplomacy, research)
- `destination_sector_id` — where they're heading (null if stationary)

NPCs start in their faction's home sector. Movement is sector-to-sector via adjacency.

### 3.4 Territory Ownership/Influence

**FactionTerritory** records per faction per sector:
- `control_level` (0-100): Hard ownership. 100 = sovereign, 50+ = majority, 1-49 = minority presence, 0 = none.
- `influence_level` (0-100): Soft influence. Decays with distance from home. Grows with NPC presence, buildings, quests.
- `claim_type`: `home` | `colony` | `contested` | `occupied` | `neutral`

A sector is "owned" by the faction with highest control_level ≥ 50.  
A sector is "contested" if two+ factions have control_level ≥ 25.

### 3.5 Contact/Discovery Rules

Factions start isolated. They discover each other through:

1. **Adjacent expansion** — when faction A claims a sector adjacent to faction B's territory, they make contact
2. **NPC expeditions** — an NPC sent on an `expedition` task may discover a new sector or encounter another faction's NPC
3. **Broadcast events** — high-power transmissions (from research or diplomacy actions) can reveal factions at range 2+
4. **Trade routes** — once contact established, a route opens between the two home sectors

**Discovery state tracked per faction pair:**
- `undiscovered` → `detected` (know they exist) → `contacted` (first communication) → `relations_open` (full diplomacy available)

### 3.6 Expansion Rules

- A faction can only claim sectors adjacent to territory it already controls (control_level ≥ 25)
- Expansion costs resources (fuel, credits, crew_morale)
- Expansion speed limited by: available NPCs, resource stockpile, danger_level of target sector
- Frontier sectors (Ring 3) are harder to claim — higher danger, lower resource yield initially
- Home sectors are inviolable — control_level always 100, influence always 100

---

## 4. Data Model

(See `docs/SPATIAL_DATA_MODEL_SPEC.md` for full field definitions)

**New data structures (in-memory dataclasses + Redis, consistent with existing architecture):**

1. **Sector** — the map itself
2. **FactionTerritory** — who controls what
3. **NpcLocation** — where NPCs are
4. **FactionHome** — permanent home assignments
5. **SectorAdjacency** — movement graph
6. **WorldDiscovery** — contact state between factions

---

## 5. Backend API Changes

### 5.1 `/map/data` — Before vs After

**Before:**
```json
{
  "world_state": { "turn": 1, "credits": 1000, ... },
  "npcs": [{ "id": "npc-1", "name": "Dr. Voss", "faction_id": "research", ... }],
  "factions": [{ "id": "research", "name": "Research Division", "cohesion": 0.7, ... }],
  "events": [],
  "worker": { "status": "running" },
  "broadcasts": []
}
```

**After:**
```json
{
  "world_state": { ... },
  "sectors": [
    { "id": "sol-prime", "name": "Sol Prime", "x": 0, "y": 0, "region_type": "core",
      "resource_profile": "research", "danger_level": 1,
      "adjacent": ["meridian", "crucible", "helix", "archive"] }
  ],
  "faction_territories": [
    { "faction_id": "research", "sector_id": "archive", "control_level": 100,
      "influence_level": 100, "claim_type": "home" }
  ],
  "npcs": [
    { "id": "npc-1", "name": "Dr. Voss", "faction_id": "research",
      "sector_id": "archive", "x_offset": 12, "y_offset": -8,
      "current_task": "garrison", "destination_sector_id": null }
  ],
  "factions": [{ "id": "research", "home_sector_id": "archive", ... }],
  "discoveries": [
    { "faction_a": "research", "faction_b": "military", "state": "relations_open" }
  ],
  "events": [],
  "worker": { "status": "running" },
  "broadcasts": []
}
```

### 5.2 `/simulation/factions` Changes

Add to each faction object:
- `home_sector_id`
- `territory` → list of `{sector_id, control_level, influence_level, claim_type}`
- `discovered_factions` → list of faction_ids they've made contact with
- `expansion_policy` → "aggressive" | "moderate" | "cautious" | "isolationist"

### 5.3 New Endpoints

| Endpoint | Purpose | Phase |
|----------|---------|-------|
| `GET /sectors` | Full sector map with adjacency | 2 (SPATIAL-02) |
| `GET /sectors/{id}` | Single sector detail + current territory state | 2 (SPATIAL-02) |
| `POST /simulation/expand` | Faction attempts to claim adjacent sector | 4 (SPATIAL-04) |
| `POST /simulation/expedition` | Send NPC on sector discovery mission | 4 (SPATIAL-04) |
| `GET /simulation/discoveries` | All faction contact states | 2 (SPATIAL-02) |
| `GET /spatial/status` | Whether spatial system is seeded, sector/territory counts | 1 (SPATIAL-01) |
| `POST /spatial/seed` | Admin-only: seed the spatial system into Redis | 1 (SPATIAL-01) |

### 5.4 Migration Compatibility Layer

- `/map/data` will include `sectors` and `faction_territories` fields — if missing (old state), frontend falls back to current behavior
- `npcs` in `/map/data` will include `sector_id` — if missing, frontend uses `hashStr(npc.id)` as before
- `/simulation/factions` will include `home_sector_id` — if missing, frontend doesn't render it
- All new fields are additive. No fields removed. No breaking changes.

### 5.5 Fallback Behavior

If spatial data is missing (pre-migration save, old state file):
- Frontend detects absence of `sectors` array → reverts to `buildNodes()` hash-based layout
- Backend returns `/map/data` without `sectors`/`faction_territories` if no sectors seeded
- Simulation runs exactly as before — no spatial ticks execute

---

## 6. Simulation Mechanics

### 6.1 How Factions Expand

Each autonomous tick, a faction with `expansion_policy != "isolationist"` evaluates:

1. **Adjacent unclaimed sectors** — if any, and resources sufficient, may attempt claim
2. **Adjacent low-control sectors** — if another faction holds a sector at control < 25, may attempt influence push
3. **Frontier sectors** — higher danger but higher reward; only aggressive/moderate policies attempt these
4. **Cost calculation:** `expansion_cost = base_cost * (1 + danger_level * 0.3) * distance_from_home`

Expansion attempt = LLM call for faction leader decision, modified by:
- Resource availability (credits, fuel, morale)
- Current threat level (are borders secure?)
- Ideological affinity with neighbors (friendly factions may trade instead of claim)

### 6.2 How They Discover Each Other

Discovery is proximity-driven:

1. **Territory adjacency** — when faction A controls a sector adjacent to B's territory → `detected`
2. **NPC encounter** — when faction A's NPC is in same sector as B's NPC → `contacted`
3. **Broadcast range** — research/diplomacy actions at high influence create "signals" detectable at range 2 → `detected` at distance
4. **First contact event** — generates a special narrative event when `detected` → `contacted`

### 6.3 How Conflicts Emerge at Borders

- When two factions have control_level ≥ 25 in the same sector → **contested**
- Contested sectors generate border tension events each tick
- If both factions are aggressive → skirmish events, control_level changes
- If one is aggressive and other is diplomatic → negotiation events, possible trade agreement
- If both are diplomatic → cooperative events, shared influence growth

### 6.4 How Distance Affects Interactions

| Distance | Effect |
|----------|--------|
| Same sector | Full interaction, combat possible, trade immediate |
| Adjacent sector | Diplomatic contact, trade with transit cost, limited combat (border skirmish) |
| 2 sectors away | Communication only, no direct trade, espionage possible |
| 3+ sectors away | No interaction until discovery mechanism bridges gap |

**Distance modifier:** `interaction_weight = 1.0 / (1 + hop_distance)`

This replaces the current system where all factions interact equally regardless of "where" they are.

### 6.5 How NPCs Move or Operate Inside Territories

NPC tasks become spatially meaningful:

| Task | Spatial Behavior |
|------|------------------|
| `garrison` | Stay in current sector, boost control_level |
| `patrol` | Move between adjacent owned sectors, boost influence |
| `expedition` | Move toward unexplored sector, discover new sectors |
| `diplomacy` | Travel to another faction's territory for negotiations |
| `research` | Stay in sector, boost sector's resource output |
| `espionage` | Infiltrate adjacent rival sector, reduce their control_level |

Movement: 1 sector per tick. NPC picks destination, moves one hop, arrives next tick.

---

## 7. Frontend Rendering

### 7.1 Starmap Renders Real Sectors/Territory from Backend

**Replace `buildNodes()` hash-based layout with:**

1. `/map/data` returns `sectors[]` with real `x`, `y` coordinates
2. Frontend places sector markers at those coordinates on the canvas
3. `faction_territories[]` tells the frontend which sectors each faction controls and at what level
4. Frontend draws territory polygons using sector positions (not NPC positions) as vertices
5. NPC positions are their `sector_id` + `(x_offset, y_offset)` — placed near their sector center

**Territory polygon construction (replaces current convex hull of NPC positions):**
- Group sectors by controlling faction
- For each faction, find the hull of their controlled sector coordinates
- Apply existing `padPolygon() → smoothPoly() → breathing deformation` pipeline
- Contested sectors render with dual-color overlay

### 7.2 Remove Fake Convex Hull as Authoritative Display

- Current `convexHull(factionNodePositions)` from fake NPC positions → **deprecated as fallback only**
- New authoritative path: territory polygon from sector coordinates + control levels
- Keep the rendering pipeline (pad, smooth, breathe) — it's visually excellent
- Change only the input data source

### 7.3 Legacy Fallback / Debug Mode

- If `/map/data` has no `sectors` array → fall back to current `buildNodes()` behavior
- Add a `?debug=legacy-layout` URL parameter to force hash-based layout for comparison
- Debug mode renders both: real territory (solid) + legacy positions (faded dots) for verification

### 7.4 New Visual Elements

- **Sector markers:** circles/diamonds at sector coordinates, sized by importance
- **Sector labels:** name displayed at sector position
- **Adjacency lines:** thin connections between adjacent sectors (visible in Network mode)
- **Control indicators:** sector fill color shows controlling faction, opacity = control_level
- **Movement arrows:** when NPC has `destination_sector_id`, show travel arrow

---

## 8. Migration Strategy

(See `docs/SPATIAL_MIGRATION_PLAN.md` for full phase details)

### 8.1 Seed Initial Map

Create a Sol-inspired sector map:
- 3 core sectors, 6 inner, 6 outer, 6 frontier = 21 sectors (expandable to 24)
- Assign coordinates in 3 concentric rings on the starmap canvas
- Define adjacency relationships (each sector connected to 2-4 neighbors)

### 8.2 Assign Each Faction a Home Sector

Map the 8 existing factions to home sectors: 6 in the Inner ring, 2 in the Outer ring. The 3 Core sectors (Sol Prime, Meridian, Crucible) remain unclaimed as a shared "neutral zone" — the first territory factions will contest as they expand inward.

### 8.3 Assign NPCs to Faction Home Regions

All existing NPCs get `current_sector_id = their_faction.home_sector_id`. Random `x_offset`, `y_offset` within ±20px of sector center. `current_task = "garrison"`.

### 8.4 Avoid Breaking Existing Pages

- simulation.html: no changes needed (doesn't render spatial data)
- bridge.html: no changes needed (displays `discovered_sectors` counter — still works)
- starmap.html: additive changes — new rendering path with fallback to current behavior
- index.html: no changes needed
- All existing API responses remain valid. New fields are additive.

---

## 9. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Schema complexity — adding 6 new data structures to an in-memory system | Medium | Start with Redis keys only (no DB migration needed — consistent with current architecture). Add persistence later. |
| Frontend regression — starmap breaks when new data format arrives | High | Fallback detection: if `sectors` array missing, use current `buildNodes()`. No breaking changes. |
| Simulation loop instability — spatial ticks add CPU/load to already tight memory | High | Spatial ticks are cheap (adjacency lookups, not pathfinding). Rate-limit to 1 spatial evaluation per faction per tick. Skip if memory pressure. |
| Too much scope — territory, expansion, contact, conflict, NPC movement, all at once | High | Phase strictly. MVP is sectors + home territories + NPC locations only. Expansion/contact come later. |
| Save/load compatibility — existing save states lack spatial data | Medium | On load, if no sector data, seed defaults. All new fields have sensible defaults. |
| LLM call budget increase — expansion decisions need extra cognition calls | Medium | Spatial decisions piggyback on existing faction cognition tick. No new LLM calls in MVP. |
| NPC movement creates "empty" sectors — factions look dead if NPCs cluster | Low | Garrison NPCs stay home. Only expedition/diplomacy NPCs move. Most NPCs stationary in MVP. |

---

## 10. Implementation Phases

### Phase 0: Design Only ← WE ARE HERE
- This document
- `docs/SPATIAL_DATA_MODEL_SPEC.md`
- `docs/SPATIAL_MIGRATION_PLAN.md`
- **No code changes. Wait for operator approval.**

### Phase 1: Backend Schema + Seed Data (SPATIAL-01)
- Add Sector, FactionTerritory, NpcLocation, FactionHome, SectorAdjacency, WorldDiscovery dataclasses
- Add Redis keys for all spatial state
- Create seed function: generates 21 sectors (expandable to 24) with coordinates, adjacency, resource profiles
- Assign faction homes
- Assign NPC initial locations
- No API changes yet — internal data only
- **Verify:** unit tests confirm sector graph, adjacency, territory initialization

### Phase 2: /map/data Real Spatial Output (SPATIAL-02)
- Add `sectors`, `faction_territories`, `npc_locations`, `discoveries` to `/map/data` response
- Add `/sectors` and `/sectors/{id}` endpoints
- Add spatial fields to `/simulation/factions` response
- Preserve all existing fields — no removals
- **Verify:** `curl /map/data | jq .sectors` returns sector array; frontend still works with fallback

### Phase 3: Starmap Renders Real Geography (SPATIAL-03)
- Add real-sector rendering path to starmap.html
- Territory polygons from sector coordinates (not NPC positions)
- NPC sprites at sector + offset coordinates
- Sector labels and adjacency lines
- Keep legacy fallback for when `sectors` array is missing
- Add `?debug=legacy-layout` mode
- **Verify:** starmap shows named sectors, faction territories rendered from backend data; legacy mode still works

### Phase 4: Expansion/Contact Mechanics (SPATIAL-04)
- Add expansion evaluation to autonomous tick (1 per faction per tick, no extra LLM calls)
- Add NPC movement: `garrison`, `patrol`, `expedition` tasks
- Add discovery system: adjacency-based contact, NPC encounters
- Add `POST /simulation/expand` and `POST /simulation/expedition` endpoints
- **Verify:** factions slowly expand from home sectors, discover neighbors, contested zones appear

### Phase 5: Conflict/Trade/Diplomacy Based on Territory (SPATIAL-05)
- Distance modifier on all faction interactions (replace ideology-only with ideology × proximity)
- Border conflict events when contested sectors exist
- Trade route bonuses for adjacent friendly factions
- Espionage mechanics for adjacent rival sectors
- Territory loss/gain in autonomous resolution
- **Verify:** faction behavior varies by proximity — distant factions interact less, border factions interact more

---

## 11. Kill Switch Hierarchy

The spatial system has three environment-variable kill switches, each controlling a different layer:

| Variable | Default | Controls | Affects |
|----------|---------|----------|---------|
| `SPATIAL_ENABLED` | `true` | Master switch — disables all spatial features | All phases: API fields return empty, ticks skip, frontend falls back |
| `SPATIAL_RENDERING_ENABLED` | `true` | Frontend rendering of real spatial data | Phase 3+: starmap ignores `sectors` array, uses `buildNodes()` fallback |
| `SPATIAL_MECHANICS_ENABLED` | `true` | Simulation mechanics (expansion, NPC movement, discovery) | Phase 4+: spatial tick sub-steps are skipped, factions don't expand or discover |

**Hierarchy:** `SPATIAL_ENABLED=false` overrides everything. If master is off, sub-switches are irrelevant. Sub-switches allow independent control — e.g., disable mechanics but keep rendering for debugging.

**Usage across phases:**

| Phase | Switches Active |
|-------|-----------------|
| Phase 1-2 | `SPATIAL_ENABLED` only |
| Phase 3+ | `SPATIAL_ENABLED` + `SPATIAL_RENDERING_ENABLED` |
| Phase 4+ | `SPATIAL_ENABLED` + `SPATIAL_RENDERING_ENABLED` + `SPATIAL_MECHANICS_ENABLED` |

---

## Appendix: Key Principle

**The current territory visualization pipeline is architecturally sound.** Convex hull → padding → Chaikin smoothing → breathing deformation → contested zone detection — all of this works. The problem is the **input**, not the **rendering**.

The spatial layer replaces the input from "fake NPC positions from hash functions" to "real sector coordinates from backend state." The rendering code largely stays the same — it just draws polygons from better data.
