# SPATIAL MIGRATION PLAN

**Status:** DESIGN ONLY  
**Date:** 2026-05-27  
**Goal:** Introduce real spatial layer without breaking any existing functionality  

---

## Core Migration Principle

**Additive only. No breaking changes. No field removals. No API contract changes.**

Every new feature degrades gracefully to current behavior when spatial data is absent. This means:
- Old save states load without error
- Frontends that don't request spatial fields continue working
- The simulation runs identically if the spatial layer is disabled
- Every new API field has a default/absence behavior

---

## Phase 0: Design Only (Current)

**Status:** COMPLETE

Deliverables:
- `docs/SPATIAL_TERRITORY_SYSTEM_PLAN.md`
- `docs/SPATIAL_DATA_MODEL_SPEC.md`
- `docs/SPATIAL_MIGRATION_PLAN.md`

**No code changes. Wait for operator approval.**

---

## Phase 1: Backend Schema + Seed Data (SPATIAL-01)

**Branch:** `spatial-01-schema`  
**Scope:** Backend only. No frontend changes. No API changes.  

### 1.1 New Files to Create

| File | Purpose |
|------|---------|
| `backend/spatial_models.py` | Sector, FactionHome, FactionTerritory, NpcLocation, SectorAdjacency, WorldDiscovery dataclasses |
| `backend/spatial_seed.py` | `seed_spatial_system()` — creates the 21-sector map, faction homes, NPC locations, adjacency |
| `backend/spatial_queries.py` | Read/query functions for spatial state (get sector, get territory, get NPC location, etc.) |
| `backend/spatial_state.py` | Redis key management — read/write/serialize/deserialize for all spatial data |

### 1.2 Existing Files to Modify

| File | Change | Risk |
|------|--------|------|
| `backend/main.py` | Add `POST /spatial/seed` endpoint (admin-only, seeds spatial system) | Low — new endpoint, no existing code touched |
| `backend/main.py` | Add `GET /spatial/status` endpoint (returns seeded state, sector/territory counts) | Low — new endpoint, read-only |
| `backend/main.py` | Add startup check: if no sectors exist in Redis, log warning (don't auto-seed) | Low — additive |
| `backend/worker.py` | Add `POST /spatial/tick` call in worker loop (no-op if spatial system not seeded) | Low — guarded by feature check |
| `backend/nvidia_nim_client.py` | No change | None |
| `backend/federation_game_npcs.py` | Add `current_sector_id` field to Creature (default `""` — empty = unassigned) | Low — default preserves existing behavior |

### 1.3 New Endpoints Added in Phase 1

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/spatial/seed` | POST | Admin-only: seed the spatial system into Redis (idempotent) |
| `/spatial/status` | GET | Whether spatial system is seeded, sector count, territory count |

### 1.3 Seed Function Specification

```python
def seed_spatial_system():
    """
    Creates the 21-sector Sol-inspired map.
    Idempotent — safe to call multiple times.
    Checks if sectors already exist before writing.
    """
    # 1. Create all 21 sectors with coordinates, adjacency, resource profiles
    # 2. Create faction home assignments (8 factions → 8 sectors)
    # 3. Set FactionTerritory: control_level=100, influence_level=100, claim_type="home" for each home
    # 4. Assign all existing NPCs to their faction's home sector
    # 5. Create initial WorldDiscovery entries (all "undiscovered")
    # 6. Populate dead fields: Faction.influence_map, Faction.headquarters_location, etc.
```

### 1.4 Verification Steps

After Phase 1 is deployed:

1. `POST /spatial/seed` → 200 OK
2. `redis-cli KEYS "sector:*" | wc -l` → 21
3. `redis-cli KEYS "faction_home:*" | wc -l` → 8
4. `redis-cli KEYS "territory:*" | wc -l` → 8 (one per home)
5. `redis-cli KEYS "npc_location:*" | wc -l` → matches NPC count
6. `curl /map/data | jq .` → no `sectors` field yet (API not changed in this phase)
7. Simulation still runs — worker tick unchanged, spatial tick is a no-op

### 1.5 Rollback

If Phase 1 causes issues:
- Delete all spatial Redis keys: `redis-cli KEYS "sector:*" | xargs redis-cli DEL` (and same for territory, faction_home, npc_location, adjacency, discovery)
- No existing functionality is affected — all changes are additive
- Remove `POST /spatial/seed` endpoint if needed

---

## Phase 2: /map/data Real Spatial Output (SPATIAL-02)

**Branch:** `spatial-02-api` (depends on Phase 1 being merged)  
**Scope:** Backend API changes. No frontend changes yet.  

### 2.1 API Response Changes

**`GET /map/data` — Additive fields:**

```json
{
  "world_state": { ... },
  "sectors": [ ... ],                    // NEW — array of Sector objects, empty [] if not seeded
  "faction_territories": [ ... ],        // NEW — array of FactionTerritory objects
  "npc_locations": [ ... ],              // NEW — array of NpcLocation objects
  "discoveries": [ ... ],                // NEW — array of WorldDiscovery objects
  "npcs": [ ... ],                       // UNCHANGED — but each NPC now has sector_id field added
  "factions": [ ... ],                   // UNCHANGED — but each faction now has home_sector_id field added
  "events": [ ... ],
  "worker": { ... },
  "broadcasts": [ ... ]
}
```

**Guard:** If spatial system not seeded (no sectors in Redis), these new arrays are empty `[]`. Frontend can detect this and fall back.

**`GET /simulation/factions` — Additive fields per faction:**

```json
{
  "id": "research",
  "home_sector_id": "archive",           // NEW — null if spatial not seeded
  "territory": [ ... ],                  // NEW — list of {sector_id, control_level, claim_type}
  "discovered_factions": [ ... ],        // NEW — list of faction_ids with state ≥ "detected"
  "expansion_policy": "moderate",        // NEW — null if spatial not seeded
  ...existing fields...
}
```

### 2.2 New Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sectors` | GET | Full sector map with adjacency |
| `/sectors/{id}` | GET | Single sector detail + current territory state |
| `/spatial/status` | GET | Whether spatial system is seeded, sector count, territory count (added in Phase 1, listed here for completeness) |
| `/simulation/discoveries` | GET | All faction contact states |

> Note: `POST /spatial/seed` and `GET /spatial/status` are added in Phase 1. `POST /simulation/expand` and `POST /simulation/expedition` are added in Phase 4.

### 2.3 Backward Compatibility

- All new fields have defaults: `sectors: []`, `home_sector_id: null`, `territory: []`
- Old clients that don't read new fields work identically
- `/map/data` response size increase: ~5-10KB for 21 sectors + territories. Negligible.
- No existing fields are removed or renamed

### 2.4 Verification Steps

1. `curl /map/data | jq '.sectors | length'` → 21
2. `curl /map/data | jq '.faction_territories | length'` → 8 (one per home)
3. `curl /map/data | jq '.npc_locations | length'` → matches NPC count
4. `curl /map/data | jq '.npcs[0].sector_id'` → valid sector ID
5. `curl /sectors | jq length` → 21
6. `curl /spatial/status` → `{"seeded": true, "sector_count": 21, "territory_count": 8}`
7. **Frontend still works** — no frontend changes yet, new fields ignored by current JS

### 2.5 Rollback

- New API fields are additive — old frontend ignores them
- If response size is problematic, add `?spatial=false` query param to omit spatial fields
- New endpoints can be removed without affecting existing ones

---

## Phase 3: Starmap Renders Real Geography (SPATIAL-03)

**Branch:** `spatial-03-frontend` (depends on Phase 2 being merged)  
**Scope:** Frontend starmap.html changes. Backend unchanged.  

### 3.1 Rendering Changes

**Current flow:**
```
buildNodes() → hashStr(npc.id) → fake positions → convexHull → pad → smooth → render
```

**New flow (when spatial data present):**
```
/map/data.sectors → place sector markers at real x,y
/map/data.faction_territories → group by faction → convex hull of sector coords → pad → smooth → render
/map/data.npc_locations → place NPC sprites at sector center + offset
```

### 3.2 Specific Code Changes in starmap.html

| Current Code | New Code | Change Type |
|--------------|----------|-------------|
| `buildNodes()` always runs | `buildNodes()` runs only if `sectors` array is empty | Conditional |
| `FACTION_ORDER` hardcoded | `FACTION_ORDER` used as fallback only | Fallback |
| Territory polygons from `factionNodePositions` | Territory polygons from sector coordinates grouped by controlling faction | Replace input |
| NPC sprites at `hashStr` positions | NPC sprites at `sector.x + x_offset, sector.y + y_offset` | Replace input |
| No sector labels | Sector name labels at sector coordinates | New |
| No adjacency lines | Thin lines between adjacent sectors (in Network view) | New |

**The rendering pipeline stays the same:** convex hull → pad → Chaikin smooth → breathing deformation → contested zone detection. Only the **input** changes.

### 3.3 Sector Visual Design

- **Sector marker:** Small circle (4-6px radius) at sector coordinates, colored by controlling faction
- **Unclaimed sectors:** Gray circle with thin border
- **Contested sectors:** Split-color fill or pulsing border
- **Sector label:** Name in small text below marker (hide when zoomed out)
- **Home sectors:** Larger marker (8px) with faction icon/emoji
- **Adjacency lines:** Thin gray lines between connected sectors (visible in Network view mode)
- **NPC movement arrows:** When `destination_sector_id` is set, draw a small arrow from current to destination

### 3.4 Fallback / Debug Mode

| Condition | Behavior |
|-----------|----------|
| `sectors` array is empty or missing | Fall back to current `buildNodes()` hash-based layout |
| `?debug=legacy-layout` URL param | Force legacy layout even when spatial data present |
| `?debug=spatial-overlay` URL param | Show both: real territory (solid) + legacy positions (faded dots) |

### 3.5 Verification Steps

1. Load starmap without spatial data seeded → looks exactly like current starmap
2. Seed spatial system → refresh starmap → see named sectors at real coordinates
3. Territory polygons drawn around sector positions, not NPC positions
4. NPCs appear near their sector center, not at hash-based positions
5. Sector labels visible
6. Switch to Network view → adjacency lines visible
7. `?debug=legacy-layout` → reverts to old layout
8. `?debug=spatial-overlay` → shows both for comparison

### 3.6 Rollback

- If new rendering breaks, the `sectors` array check automatically falls back to legacy
- Toggle: add `SPATIAL_RENDERING_ENABLED=false` to .env to disable real-sector rendering
- No backend changes needed for rollback — just frontend conditional

---

## Phase 4: Expansion/Contact Mechanics (SPATIAL-04)

**Branch:** `spatial-04-mechanics` (depends on Phase 3 being merged)  
**Scope:** Backend simulation mechanics. Frontend renders the results.  

### 4.1 New Backend Files

| File | Purpose |
|------|---------|
| `backend/spatial_engine.py` | Core spatial simulation: expansion, NPC movement, discovery evaluation |
| `backend/spatial_events.py` | Spatial event generation: border contact, NPC encounter, discovery events |

### 4.2 New Endpoints Added in Phase 4

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/simulation/expand` | POST | Faction attempts to claim an adjacent sector (costs resources, success based on danger) |
| `/simulation/expedition` | POST | Send an NPC on a sector discovery mission (assigns expedition task + destination) |

These endpoints are the player-facing actions for expansion and exploration. The autonomous tick also calls the same logic internally (expansion evaluation, expedition assignment) — these endpoints allow manual triggering.

### 4.2 Autonomous Tick Integration

Add a spatial sub-step to the existing autonomous tick (simulation_engine.py):

```
Existing tick:
  1. Faction context wiring
  2. LLM cognition calls
  3. Decision execution
  ...
  13. Memory harvest

New step (inserted after step 3):
  3.5. Spatial evaluation
    a. NPC movement (move NPCs with destinations, 1 hop/tick)
    b. Expansion evaluation (each faction decides whether to claim adjacent sector)
    c. Discovery evaluation (check for new territory adjacencies, NPC encounters)
    d. Territory attrition (ungarrisoned sectors lose control)
    e. Generate spatial events (border contact, NPC encounter, etc.)
```

**Budget:** 0 additional LLM calls in MVP. Expansion decisions piggyback on existing faction cognition. Movement and discovery are deterministic rule checks.

### 4.3 NPC Movement Implementation

```python
def spatial_tick_npcs():
    """Move all NPCs with destinations one hop closer."""
    for npc_id in get_all_npc_ids():
        loc = get_npc_location(npc_id)
        if loc.destination_sector_id:
            # Move one hop along shortest path
            next_sector = next_hop(loc.sector_id, loc.destination_sector_id)
            loc.sector_id = next_sector
            loc.movement_progress = 0.0
            if next_sector == loc.destination_sector_id:
                # Arrived
                loc.destination_sector_id = None
                loc.current_task = "garrison"  # default post-arrival task
        elif loc.current_task == "patrol" and loc.patrol_route:
            # Advance patrol
            current_idx = loc.patrol_route.index(loc.sector_id)
            next_idx = (current_idx + 1) % len(loc.patrol_route)
            loc.destination_sector_id = loc.patrol_route[next_idx]
            loc.movement_progress = 0.0
```

### 4.4 Expansion Evaluation

```python
def spatial_tick_expansion():
    """Each non-isolationist faction evaluates expansion."""
    for faction_id in get_all_faction_ids():
        home = get_faction_home(faction_id)
        if home.expansion_policy == "isolationist":
            continue
        
        owned_sectors = get_faction_territory_sectors(faction_id)
        adjacent_unclaimed = get_adjacent_unclaimed(owned_sectors)
        
        if not adjacent_unclaimed:
            continue
        
        # Pick highest-value adjacent sector
        target = max(adjacent_unclaimed, key=lambda s: sector_value(s, faction_id))
        
        # Cost check
        cost = expansion_cost(faction_id, target)
        resources = get_faction_resources(faction_id)
        if resources["credits"] >= cost and resources["fuel"] >= cost * 0.5:
            # Attempt expansion (success based on danger_level + random factor)
            success_chance = 0.8 - (target.danger_level * 0.05)
            if random.random() < success_chance:
                establish_territory(faction_id, target.id, claim_type="colony")
                # Generate expansion event
```

### 4.5 Discovery Evaluation

```python
def spatial_tick_discovery():
    """Check for new faction contacts."""
    for pair in get_all_faction_pairs():
        if pair.state != "undiscovered":
            continue
        
        # Territory adjacency check
        a_sectors = get_faction_territory_sectors(pair.faction_a_id)
        b_sectors = get_faction_territory_sectors(pair.faction_b_id)
        
        if are_adjacent_any(a_sectors, b_sectors):
            pair.state = "detected"
            pair.discovered_tick = current_tick()
            pair.discovery_method = "territory_adjacency"
            generate_discovery_event(pair)
        
        # NPC encounter check
        for sector_id in a_sectors & get_adjacent_all(b_sectors):
            a_npcs = get_npcs_in_sector(sector_id, pair.faction_a_id)
            b_npcs = get_npcs_in_sector(sector_id, pair.faction_b_id)
            if a_npcs and b_npcs:
                if pair.state == "detected":
                    pair.state = "contacted"
                    pair.contacted_tick = current_tick()
                    pair.discovery_method = "npc_encounter"
                    generate_first_contact_event(pair)
```

### 4.6 Verification Steps

1. Seed spatial system → all factions at home sectors, all pairs undiscovered
2. Run 10 ticks → factions begin expanding to adjacent sectors
3. Run 20 ticks → some factions discover neighbors via territory adjacency
4. Run 50 ticks → most factions in "detected" or "contacted" state
5. Check: expansion events appear in activity log
6. Check: discovery events appear in events
7. Check: NPC locations update (NPCs with expedition tasks move)
8. Check: starmap shows expanding territory polygons in real-time

### 4.7 Rollback

- Spatial tick is a no-op if spatial system not seeded
- Disable with `SPATIAL_MECHANICS_ENABLED=false` in .env
- All spatial events are tagged with `source: "spatial"` — can be filtered/excluded
- NPC locations revert to home sector if movement data corrupted

---

## Phase 5: Conflict/Trade/Diplomacy Based on Territory (SPATIAL-05)

**Branch:** `spatial-05-conflict` (depends on Phase 4 being merged)  
**Scope:** Modify existing faction interaction systems to use spatial proximity.  

### 5.1 Distance Modifier

Current: Faction interactions use `FACTION_IDEOLOGY_AFFINITY` matrix alone.  
New: `effective_affinity = ideology_affinity * distance_modifier`

```python
def distance_modifier(faction_a_id, faction_b_id):
    """
    Returns 0.0-1.0 based on shortest path between faction territories.
    Adjacent territories: 1.0 (full interaction)
    2 hops: 0.6
    3 hops: 0.36
    4+ hops: 0.2 (minimal interaction)
    Same sector: 1.0
    No path / undiscovered: 0.0
    """
    if not is_discovered(faction_a_id, faction_b_id):
        return 0.0
    
    dist = shortest_territory_distance(faction_a_id, faction_b_id)
    if dist == 0:  return 1.0   # same sector
    if dist == 1:  return 1.0   # adjacent
    if dist == 2:  return 0.6
    if dist == 3:  return 0.36
    return 0.2  # distant
```

### 5.2 Border Conflict Events

When sectors are contested, generate conflict events:

| Contest Level | Event Type | Frequency |
|---------------|------------|-----------|
| Both factions 25-49 control | "Border Tension" | Every 5 ticks |
| One faction 50+, other 25+ | "Border Skirmish" | Every 10 ticks |
| Both factions 50+ | "Territorial Dispute" | Every 3 ticks |
| One faction aggressive, other not | "Incursion" | Event-driven |

### 5.3 Trade Route Bonuses

Adjacent friendly factions (relations ≥ 0.5) get:
- Economic bonus: +5% credits per tick per trade route
- Research bonus: +2% research output per shared border sector
- Diplomatic bonus: relations improve +0.01 per tick per trade route

### 5.4 Espionage Mechanics

Adjacent rival factions (relations < -0.3) can:
- Send NPC on `espionage` task to rival sector
- Success: -5 control_level, steal resource info
- Failure: NPC captured, -0.05 relations

### 5.5 Verification Steps

1. Two factions with adjacent territory → interaction events more frequent than distant factions
2. Distant factions → fewer events, lower trade output
3. Contested sector → border conflict events appear
4. Friendly adjacent factions → trade bonuses visible in resource output
5. Espionage mission → control_level changes, events generated

### 5.6 Rollback

- Distance modifier can be disabled: `SPATIAL_DISTANCE_MODIFIER=false`
- Without the modifier, system reverts to ideology-only interactions
- Border events can be disabled independently
- Trade bonuses can be disabled independently

---

## Save/Load Compatibility

### Loading Old Saves (Pre-Spatial)

When loading a save file that has no spatial data:

1. **Detection:** Check if `sector:all` Redis key exists
2. **Behavior:** Don't auto-seed. Log warning: "Spatial system not initialized. Run POST /spatial/seed to enable."
3. **Fallback:** All spatial API fields return empty arrays. Frontend uses legacy layout.
4. **Simulation:** Worker tick skips spatial sub-steps. Everything works as before.

### Saving with Spatial Data

Spatial state is included in the existing snapshot mechanism:

```python
def save_snapshot():
    # Existing save logic
    data = {
        "world_state": ...,
        "npcs": ...,
        "factions": ...,
        # NEW:
        "sectors": get_all_sectors(),
        "territories": get_all_territories(),
        "npc_locations": get_all_npc_locations(),
        "discoveries": get_all_discoveries(),
    }
    save_to_redis(data)
```

### Loading Saves with Spatial Data

When loading a save that includes spatial data:

1. Restore all spatial Redis keys from snapshot
2. Verify sector count matches expected (21)
3. Verify adjacency graph is connected
4. If corruption detected, re-seed and log warning

---

## Memory Budget

| Data | Count | Approximate Size |
|------|-------|------------------|
| Sector JSON | 21 | ~15 KB |
| FactionHome JSON | 8 | ~1 KB |
| FactionTerritory JSON | ~40 (after expansion) | ~5 KB |
| NpcLocation JSON | ~100 | ~10 KB |
| SectorAdjacency JSON | ~35 | ~3 KB |
| WorldDiscovery JSON | ~28 | ~3 KB |
| Redis SET overhead | ~50 sets | ~5 KB |
| **Total** | | **~42 KB** |

Current Redis usage: ~2 MB. New spatial data: ~42 KB. **2% increase.** No concern.

---

## Timeline Estimate

| Phase | Scope | Estimated Effort |
|-------|-------|-----------------|
| Phase 0 | Design docs | DONE |
| Phase 1 | Backend schema + seed | 1-2 sessions |
| Phase 2 | API changes | 1 session |
| Phase 3 | Frontend rendering | 1-2 sessions |
| Phase 4 | Expansion/contact mechanics | 2-3 sessions |
| Phase 5 | Conflict/trade/diplomacy | 2-3 sessions |

**Total MVP (Phases 1-3):** 3-5 sessions  
**Full system (Phases 1-5):** 7-11 sessions  

---

## Kill Switch Hierarchy

The spatial system has three environment-variable kill switches. Each controls a different layer and can be toggled independently:

| Variable | Default | Controls | Active From Phase |
|----------|---------|----------|-------------------|
| `SPATIAL_ENABLED` | `true` | **Master switch** — disables all spatial features when false | Phase 1+ |
| `SPATIAL_RENDERING_ENABLED` | `true` | Frontend rendering of real spatial data (starmap sectors/territories) | Phase 3+ |
| `SPATIAL_MECHANICS_ENABLED` | `true` | Simulation mechanics — expansion, NPC movement, discovery, territory attrition | Phase 4+ |

**Hierarchy:**

- `SPATIAL_ENABLED=false` overrides everything — all spatial API fields return empty, all spatial ticks skip, frontend uses legacy layout
- `SPATIAL_RENDERING_ENABLED=false` only disables the real-sector rendering path; starmap falls back to `buildNodes()` hash-based layout even when spatial data is present
- `SPATIAL_MECHANICS_ENABLED=false` only disables the autonomous expansion/movement/discovery tick; factions don't expand or move NPCs spatially, but spatial data can still be viewed

**Rollback behavior at any phase:**

1. Set `SPATIAL_ENABLED=false` in `.env`
2. All spatial API fields return empty arrays
3. All spatial tick steps are skipped
4. Frontend falls back to legacy `buildNodes()` layout
5. Simulation runs exactly as it does today

**No spatial feature is hard-wired.** Everything degrades gracefully.
