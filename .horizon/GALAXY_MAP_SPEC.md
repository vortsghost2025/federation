# Galaxy Map — Implementation Spec

**Status:** Approved for v1 build. See §13 for locked decisions.
**Scope:** New interactive 3D "Galaxy Map" page that exposes the existing
spatial simulation as an astronomical-looking universe, while preserving
the 2D strategic map (`starmap.html`) as the proven command-and-control view.
**Non-goals:** No backend changes in v1 (no helper endpoint, no model
additions). No replacement of `starmap.html` or `universe.html`.

---

## 1. Existing simulation data we can use today

From `/map/data` (backend `map_endpoints.py:1090`):

| Field | Shape | Used for |
|---|---|---|
| `sectors` | `[Sector]` with `id, name, x, y, region_type, resource_profile, danger_level, description, adjacent_sector_ids` | map units, positions, danger coloring, movement graph |
| `faction_territories` | `[FactionTerritory]` with `faction_id, sector_id, control_level, influence_level, claim_type, last_contested_tick` | territory influence volumes + contested overlap |
| `npc_locations` | `[NpcLocation]` with `npc_id, sector_id, x_offset, y_offset, current_task, destination_sector_id, movement_progress, patrol_route` | NPC markers + movement trails + destinations |
| `npcs` | NPC roster with `id, name, affiliation, category, mood, sector_id` (enriched) | NPC labels, faction coloring |
| `factions` | `{fid: {display_name, member_count, cohesion, influence, color, home_sector_id, stances}}` | faction metadata + home anchors |
| `discoveries` | `[WorldDiscovery]` with `faction_a_id, faction_b_id, state, discovery_method, *_tick` | faction-pair contact state (undiscovered → detected → contacted → relations_open). NOT per-sector explored/unexplored. |
| `world_state` | `tension_level, stability, morale, anomaly_activity, ...` | top gauges |
| `events` / `broadcasts` | recent activity stream | mode-time event markers |
| `worker.tick_count` | int | HUD tick readout |
| `spatial_rendering_enabled` | bool kill switch | respects backend flag |

**Existing simulation concepts that ARE real:**
- `Sector` — the **only** atomic spatial unit. Everything else derives from it.
- `FactionHome` (permanent home sector per faction)
- `FactionTerritory` (per-faction-per-sector control + influence)
- `NpcLocation` (sector + offset + destination + movement_progress + patrol_route)
- `SectorAdjacency` (movement graph)
- `WorldDiscovery` (faction-PAIR contact state — NOT per-sector exploration)

**What each zoom level actually is:**
- **Galaxy** = the whole map. There is only one galaxy; "Galaxy view" is
  just the wide camera of the entire simulation map.
- **Region** = derived grouping by `Sector.region_type` (core / inner /
  outer / frontier). **NOT a backend entity.** Region membership moves
  with sectors as the simulation changes.
- **Sector** = the authoritative atomic unit. All real per-unit data
  lives here (position, danger, resources, NPCs, territory, adjacency).
- **System / Local** = do NOT exist as backend models. They are NOT
  exposed in the v1 UI. The internal semantic-zoom architecture is
  designed so future true System/Local levels can be added without a
  renderer rewrite.

---

## 2. Zoom hierarchy — what each level maps to

**v1 ships exactly three semantic zoom levels.** No System, no Local in
the UI until the simulation actually models them.

| Level | What it is | Data source | Camera state | What shows |
|---|---|---|---|---|
| **Galaxy** | the whole map | all sectors | full extent, slow orbit | faction home anchors, broad influence volumes, faction-pair discovery state, tick + world state gauges |
| **Region** | derived grouping by `Sector.region_type` (NOT a backend entity) | `Sector.region_type` filtered | mid zoom, one region type focused | region ring, sector markers in that region, contested borders, NPC cluster heat |
| **Sector** | the only real atomic spatial unit | `Sector` + `FactionTerritory` + `NpcLocation` + `Sector.adjacent_sector_ids` | zoomed to single sector | sector name, danger, resource_profile, description, NPCs present with x_offset/y_offset, patrol_route as visible loop, per-faction control levels |

**Internal extensibility contract:** the semantic-zoom system is built
as a list of named levels, each with a `dataFilter`, `cameraPreset`, and
`layerEmphasis`. Adding a future `System` or `Local` level requires
only registering a new entry in this list — no camera or renderer
changes. This promise exists so v2 can add deeper levels when (and
only when) the backend gains real data for them.

---

## 3. Map modes — what each one emphasizes

**v1 ships four modes.** Conflict and Network are deferred to v2 (their
data sources are too thin or absent today — see §11).

| Mode | Primary layers (visible) | Faded layers | Data source |
|---|---|---|---|
| **Universe** | starfield, nebulae, sector markers (small), faction home labels | territories faint, NPC dots small | backdrop + sectors + homes |
| **Territory** | influence volumes per faction (strong), contested overlays, faction labels | NPC dots small | `FactionTerritory.control_level + influence_level` |
| **NPC** | NPC markers (large), faction ring per sector, name labels | territory faint | `NpcLocation` + `npcs.affiliation` |
| **Exploration** | faction-pair discovery/contact state, territory-derived frontier extent, expedition/patrol movement, known vs not-yet-contacted factions | NPC faint, non-frontier territory | `WorldDiscovery` + `FactionTerritory` + `NpcLocation.current_task` |

**Exploration mode is honest to current backend:**
- `WorldDiscovery` is faction-PAIR contact state, not per-sector
  explored/unexplored state.
- V1 does NOT mark individual sectors as "unexplored." The simulation
  has no such field.
- What v1 DOES show: dotted lines between faction homes colored by
  discovery state (undiscovered → detected → contacted → relations_open);
  per-faction "explored frontier" derived from the convex hull of
  sectors where that faction has any territory; expedition/patrol
  movement paths from `NpcLocation.current_task`.
- When the backend later gains true per-faction sector discovery state,
  Exploration can become a real fog-of-war / explored-space view without
  changing the mode's wiring.

Mode + zoom combine: e.g. "Territory mode at Galaxy zoom" = broad
influence overview; "NPC mode at Sector zoom" = NPCs in this one sector
in detail. The mode system is built generically (named modes, each
with `primaryLayers` + `fadedLayers` + `dataFilter`) so v2 adds Conflict
and Network by registering new entries — no renderer changes.

---

## 4. Visual layers — data source each one reads

### Backdrop (always visible)
- Static: starfield (procedural seeded, 8–12K points, redshift depth
  coloring by Z — REUSE `starVert` / `starFrag` shaders from
  `universe.html`).
- Dynamic: 4–6 large nebula planes at scene depth (REUSE `nebVert` /
  `nebFrag`). No procedural animation per NPC.
- Milky-Way band: one curved plane with fbm noise, dim, no per-pixel
  simulation data.

### Sectors
- Sphere mesh per sector. Position from `Sector.x, Sector.y` → world XYZ
  via a coordinate transform: `(x, 0, -y)` with `SCALE` (start 0.05).
  This means we DO NOT use the universe.html `RING_Z` constant that
  shoves sectors into hardcoded Z bands — sectors live on one Z plane
  (the map plane) and Z is reserved for camera depth/danger emphasis.
- Sphere size scales with `danger_level` (0.4–1.2).
- Color: hue from `region_type` (core=blue, inner=teal, outer=amber,
  frontier=red). Saturation from `danger_level`.
- Inner emissive intensity per `claim_type`: home=0.6, colony=0.4,
  contested=0.9 (pulsing), occupied=0.5, neutral=0.2.

### Faction influence volumes
- Soft volumetric cloud per faction, anchored to the faction's
  `home_sector_id`.
- Render: a `THREE.Mesh` with custom `ShaderMaterial` that takes a
  list of `sector_id → control_level` and blends Gaussian-like density
  falloffs at each controlled sector. Cloud extends roughly one
  adjacency hop beyond the highest-influence sector.
- **No artificial polygon plate.** Cloud is a true influence field.
- Contested overlap: when two factions both have `control_level > 30`
  in the same sector, their volumes blend additively (the contested
  sectors flash brighter at Sector zoom).

### Adjacency edges
- One `LineSegments` (or `TubeGeometry` for thickness on hover) per
  adjacency. Color: blue for `route_type="standard"`, magenta for
  `"wormhole"`, green for `"gate"`, red for `"hazardous"`.
- Animated dash offset to show flow direction.

### NPC markers
- One small instanced mesh per NPC (REUSE `InstancedMesh` pattern).
- Position = `NpcLocation.sector_id` → sector XYZ + `(x_offset, y_offset, 0)`.
- Color = faction color or `CATEGORY_COLORS` (companion/rival/neutral/enigma/unknown).
- Size = 0.15 (constant — readability over distance).
- Pulse rate tied to NPC `current_task` (garrison=slow, patrol=medium, expedition=fast).

### NPC movement trails
- Per-NPC `BufferGeometry` line, last N positions (rolling buffer).
- Populated from `destination_sector_id` + `movement_progress` lerp:
  each poll, append `current_xyz + (dest_xyz - current_xyz) * movement_progress`.
- Render: thin glowing line in faction color, fades from full opacity
  at head to 0 at tail.
- Patrol routes: when `current_task == "patrol"`, draw a closed loop
  through all sectors in `patrol_route`. Same shader.

### Discovery overlay (Exploration mode)
- For each `WorldDiscovery`, draw a line between the two factions'
  home sectors. Style by `state`:
  - `undiscovered` — invisible (no contact yet, no line drawn)
  - `detected` — dim dotted
  - `contacted` — solid, faint
  - `relations_open` — solid, bright
- Per-faction "explored frontier": the convex hull of sectors where
  this faction has any `FactionTerritory` record. Faint colored ring
  around the hull. This is honest — it derives from actual territory,
  not invented per-sector explored/unexplored state.
- Expedition / patrol paths: NPCs whose `current_task ∈ {expedition,
  patrol}` get their patrol_route or destination path drawn in
  Exploration mode. Same shader as NPC trails.

### Event markers
- Deferred to v2. `events` in `/map/data` have no `sector_id` field
  today, so pinning them spatially would require fabrication. The
  Conflict mode (which would use these) is itself deferred. The mode
  system is wired so adding a `Conflict` mode in v2 can populate
  event markers once the backend gains per-event spatial context.

### World vitals (always in HUD)
- Tension / Stability / Morale / Anomaly gauges from `world_state`.
- Tick counter from `worker.tick_count`.

---

## 5. Coordinate transform — sector map → 3D world

```
worldX =  sector.x  * SCALE              // SCALE = 0.05
worldY =  0                             // map plane
worldZ = -sector.y  * SCALE              // mirror Y so +Y in sector = -Z in world
```

`Sector.x` ranges roughly -300 to +300 → worldX ±15 units. Fits comfortably
in the existing camera frustum (camera at `(0, 25, 40)` looks at origin).

`adjacent_sector_ids` edges map directly to line segments between these
world positions.

No home-pushing / centroid expansion like `starmap.js:1112-1176` does —
in 3D we have real depth budget. Faction homes stay at their true
coordinates. Conflict / contested highlights come from the territory
overlay, not from layout tricks.

---

## 6. Interaction handlers

| Gesture | Action |
|---|---|
| Mouse drag | OrbitControls rotate around map center (REUSE `OrbitControls` from universe.html) |
| Scroll wheel | Zoom in/out (clamped 5–120 units) |
| Click empty space | If a sector is under the cursor, select it; else clear selection |
| Click NPC | Select NPC, populate detail panel, lock camera to follow |
| Click sector | Select sector, populate panel with: name, danger, resource_profile, NPCs here, patrol_route waypoints |
| Double-click sector | Animate camera to sector (ease-out, 800ms), set zoom level to Sector |
| Hover sector | Highlight emissive intensity, fade nearby labels up |
| Hover NPC | Show name tooltip; highlight patrol route |
| ESC | Deselect, exit follow mode |
| F | Fit all (frame the entire map) |
| 1–4 keys | Switch mode (1=Universe, 2=Territory, 3=NPC, 4=Exploration) |
| G / R / S keys | Jump to zoom level (G=Galaxy, R=Region, S=Sector) |
| +/- keys | Zoom step |

Detail panel (right side, existing universe.html pattern) shows:
- For sector: name, region_type, danger, resource_profile, description,
  list of NPCs here, faction control level per faction.
- For NPC: name, affiliation, current_task, destination (if any),
  movement_progress, patrol_route, mood.

---

## 7. Reuse from existing code

| Reuse | From | Why |
|---|---|---|
| Star shader + nebula shader | `universe.html:225-258` | Same depth-coloring logic; we just rewire positions |
| Post-processing pipeline | `universe.html:199-213` | Bloom + film grain + OutputPass; tune bloom to be subtle (strength 0.6, threshold 0.9) so HUD text stays readable |
| `TubeGeometry` + `CatmullRomCurve3` for adjacency edges | `universe.html` (lines 230+ already use this pattern) | |
| OrbitControls | universe.html | |
| Bloom-pass tuning already applied (strength 0.8, threshold 0.85) | applied earlier this session | |
| `redshiftColor()` helper | universe.html:261 | reused for sector hue modulation |
| Error-state tick UI (`tick-dot` red/orange/green) | universe.html:594-622 (applied this session) | same pattern in new page |

`universe.html` itself is **not modified**. The new page is a sibling.

---

## 8. Performance strategy

- Sector count today: 16 (per universe.html's SECTORS array; same in
  spatial seed data). Trivial.
- NPC count: ~30 today (per starmap.js diagnostic). Instanced mesh is overkill but safe.
- Adjacency count: ~40 (per universe.html EDGES array). One LineSegments draw call.
- Faction influence volumes: 8 factions, each one ShaderMaterial mesh.
  Max draw calls ≈ 80. Well within budget.
- Starfield drift: move from CPU loop (current universe.html bug surface)
  to GPU vertex shader (REUSE the suggestion from the prior code review).
  ~12K particles at 60fps easy.

---

## 9. Map mode × zoom combinations — sanity matrix

|        | Galaxy | Region | Sector |
|---|---|---|---|
| Universe | starfield + small sector dots + faction home markers | one region ring + sector names | one sector + name + danger |
| Territory | broad influence volumes + faction labels | influence volumes + contested overlays | one sector's control per faction |
| NPC | NPC dots at home sectors | NPC dots per region | NPC dots + patrol routes in sector |
| Exploration | faction-pair discovery lines + faction frontier hulls | same, filtered to one region | per-faction control levels + expedition/patrol paths |
| Conflict | (deferred v2) | (deferred v2) | (deferred v2) |
| Network | (deferred v2) | (deferred v2) | (deferred v2) |

---

## 10. Deliverables

1. New file: `frontend/galaxy-map.html` — markup, HUD, navigation. Holds
   importmap + `<script type="module" src="galaxy-map.js"></script>`.
2. New file: `frontend/galaxy-map.js` — module script: data/state,
   coordinate transform, backdrop, sectors, territory influence,
   NPCs/trails, modes, semantic zoom, interaction, camera. Internal
   sections are clearly delineated so v2 can split into files without
   rewrite.
3. New file: `_check_galaxy_map.mjs` — same shape as `_check_universe.mjs`,
   with the same fixed clock-order check (delta before elapsed) and the
   same real-line-number reporting.
4. `starmap.html` — **NOT modified in v1**. The current live nav stays
   unchanged. After v1 is deployed and verified on the VPS, the spec
   approves replacing "3D UNIVERSE" with "GALAXY MAP" → `/galaxy-map.html`.
   That nav change is a separate deploy step.
5. `universe.html` — **NOT modified.** Remains a sibling/debug URL.
6. Backend — **NO changes** in v1. All visual data comes from existing
   `/map/data`. No new endpoints, no new models, no Redis key changes.
7. No VPS deploy in v1 build phase. Build is local-only; visual +
   checker verification happens against the local Python static server
   Sean already confirmed works (`http://127.0.0.1:8888/galaxy-map.html`).

---

## 11. What we are NOT doing (deferred to v2)

- **System and Local zoom levels.** They will be added only when the
  backend gains real per-system or per-locality models. The
  semantic-zoom architecture is extensible for that future, but no UI
  affordance for them exists in v1.
- **Conflict and Network modes.** Deferred. Conflict needs per-event
  spatial context (sector_id on events) which the backend doesn't have.
  Network needs adjacency-traffic data which isn't surfaced today.
  The mode system is extensible so v2 adds them by registration.
- **Per-sector fog-of-war / explored-unexplored state.** The backend
  has no such field. Exploration mode in v1 uses the legitimate
  sources only (faction-pair discovery, territory-derived frontier,
  expedition/patrol movement).
- **New faction influence model.** We use the existing
  `FactionTerritory.control_level + influence_level` field combination
  as the influence source. No new aggregation math.
- **Replacing `starmap.html`.** It stays as the proven 2D strategic
  view. Both maps will exist.
- **Touching `universe.html`.** It stays intact as a sibling.
- **Nav link change.** `starmap.html` nav is unchanged in v1. The
  "3D UNIVERSE → GALAXY MAP" replacement is a separate post-deploy step.

---

## 12. Decisions summary (also in §13)

All four design questions are resolved. The v1 build proceeds under
these constraints:

1. **Zoom levels** — Galaxy + Region + Sector only. Region is a derived
   grouping from `Sector.region_type` (NOT a backend entity). System and
   Local are deferred until the simulation actually models them.
   Semantic-zoom architecture is internally extensible.
2. **Map modes** — Universe + Territory + NPC + Exploration. Conflict and
   Network deferred. Mode system is internally extensible. Exploration
   uses only honest data sources (faction-pair discovery, territory
   frontier, expedition/patrol movement) — no per-sector fog-of-war.
3. **Nav link** — `starmap.html` is NOT modified in v1. The
   "3D UNIVERSE → GALAXY MAP" replacement happens as a separate post-deploy
   step, only after v1 is verified live on the VPS.
4. **Page structure** — `frontend/galaxy-map.html` (markup/HUD/nav) +
   `frontend/galaxy-map.js` (scene, data, modes, zoom, interaction).
   Reuse shaders/controls from `universe.html`; do not modify or rename it.
   `universe.html` stays as a sibling debug URL.
5. **Backend** — NO changes in v1. All data via existing `/map/data`.
   No helper endpoint, no model additions, no Redis key changes.

The previous "Open questions" section that preceded §13 is intentionally
removed; the questions and answers live in §13 below.

---

## 13. Decisions (Sean's answers, locked in for v1)

### Q1 — Zoom levels: **3 real levels, no System/Local UI**
- Ship only the 3 real levels: Galaxy → Region → Sector.
- Do NOT expose System or Local in the user-facing UI. The simulation
  does not model them, so pretending it does would violate the
  "live Federation state, not wallpaper" rule.
- The semantic-zoom architecture (camera + nav + state) must be
  internally extensible so future System/Local levels can be added
  without rewriting the renderer.
- Each of the three current levels represents a genuinely different
  simulation view:
  - **Galaxy:** overall Federation space, major faction influence,
    broad exploration state, major activity.
  - **Region:** grouped spatial areas with clearer faction boundaries,
    exploration fronts, routes, NPC activity.
  - **Sector:** the authoritative existing simulation unit — individual
    sectors, adjacency, NPC locations, movement, resources, danger,
    ownership/influence, inspect/select.

### Important clarification — Region is DERIVED, not a backend entity
`Region` is **not** a backend model. It is a derived grouping based on
`Sector.region_type` (core / inner / outer / frontier). This distinction
matters when NPCs explore and territory changes — Region membership
will move with sectors, not be a fixed static map.

### Q2 — Map modes in v1: **4 modes (Universe / Territory / NPC / Exploration)**
- Defer Conflict and Network until core map is stable.
- Exploration mode must be honest to current backend:
  - `WorldDiscovery` is faction-PAIR contact state, NOT per-sector
    explored/unexplored state.
  - Do NOT mark individual sectors "unexplored" unless the simulation
    actually tracks that.
  - For v1, Exploration mode shows: faction discovery/contact
    relationships, territory-derived frontier/influence extent,
    expedition/patrol movement, known vs not-yet-contacted factions.
- Later, when the backend gains true per-faction sector discovery
  state, Exploration can become a real fog-of-war / explored-space view.
- Build the mode system generically so Conflict and Network plug in
  later without reworking the renderer.

### Q3 — Nav link: **Defer change until Galaxy Map is live**
- Do not expose a broken live nav link.
- Keep the current live `starmap.html` navigation unchanged.
- After `/galaxy-map.html` is confirmed working live on the VPS:
  - Replace **3D UNIVERSE** in the primary nav with **GALAXY MAP**
  - Point it to `/galaxy-map.html`
  - Keep `universe.html` intact as a legacy/debug/cinematic URL, but
    not in the main navigation.
- Do NOT delete or modify `universe.html`.
- Sequence: **build → test locally → deploy → verify live → change nav.**

### Q4 — Page structure: **New galaxy-map.html + galaxy-map.js**
- Keep markup / HUD / navigation in the HTML.
- Put Three.js scene creation, live-data ingestion, rendering layers,
  interaction state, map modes, semantic-zoom logic in the JS module.
- Reuse proven pieces from `universe.html` (shaders, OrbitControls,
  post-processing, geometry patterns, helpers) — but do NOT evolve or
  rename `universe.html` itself.
- Structure `galaxy-map.js` internally by responsibility so it can
  later be split into modules without a rewrite:
  - data/state
  - coordinate transform
  - backdrop
  - sectors
  - territory influence
  - NPCs / trails
  - map modes
  - semantic zoom
  - interaction / selection
  - camera
- Do not over-engineer separate files for all of those in v1; just
  keep the boundaries clean inside `galaxy-map.js`.
