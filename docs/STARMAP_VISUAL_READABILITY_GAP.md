# STARMAP VISUAL READABILITY GAP DIAGNOSIS

**Created:** 2026-05-28  
**Status:** PENDING OPERATOR APPROVAL  
**Blocks:** SPATIAL-03B — no rendering code changes until this plan is approved  
**Reference image:** `docs/7ba76425-c0ba-4c30-82e1-985053cbce19.jpg`

---

## 1. PURPOSE

This document compares the **current** spatial starmap rendering against the operator's visual requirements and the reference territory map image. It identifies exact rendering gaps, diagnoses root causes in the code, proposes a proper rendering architecture, and defines a visual acceptance checklist.

**No code changes will be made until the operator approves this plan.**

---

## 2. WHAT THE OPERATOR NEEDS (FROM EXPLICIT FEEDBACK)

| # | Requirement | Current State | Gap |
|---|-------------|---------------|-----|
| 1 | Large translucent filled faction territories | Tiny convex hulls with 55px padding — barely visible | **CRITICAL** |
| 2 | Strong colored borders around territory regions | 3.5px border at 50% alpha — thin and faint | **CRITICAL** |
| 3 | Readable boxed sector labels | 12px Courier, 50% alpha, no background box — illegible at default zoom | **CRITICAL** |
| 4 | Sector/star systems distributed inside faction regions | Sectors clustered as point markers, not visually "inside" any region | **CRITICAL** |
| 5 | NPC dots secondary and decluttered | NPCs orbit-ring around sectors, still form dense clusters at home sectors | **MAJOR** |
| 6 | Territory mode hides most network lines by default | Adjacency lines hidden, but relationship lines still drawn (0.25 alpha) | **MINOR** |
| 7 | Network mode can show links separately | Works — adjacency lines visible in network mode | **OK** |
| 8 | No central NPC pile | Most NPCs still pile at their faction's home sector | **MAJOR** |
| 9 | All 8 faction territories visible and understandable at default zoom | Territories are small circles/hulls near center — 8 zones exist but aren't readable as territory regions | **CRITICAL** |
| 10 | Instant visual comprehension: "who owns what, where" | Requires zooming + clicking to understand — fails at default zoom | **CRITICAL** |

---

## 3. CURRENT RENDERING — DETAILED CODE ANALYSIS

### 3.1 Territory Polygon Construction (the root cause)

**File:** `frontend/starmap.html`, `buildNodesSpatial()`, lines ~1543–1611

```
Current algorithm:
1. Collect sector positions owned by each faction
2. Compute convex hull of those positions
3. Pad hull by 55px outward
4. Smooth with 2 Chaikin iterations
5. If <3 sectors, use circle fallback (zoneR = max(60, groupSize*10+40))
```

**Why this produces tiny territories:**

- Sectors are **point markers** (radius 8–14px) placed by `sectorToCanvas()`
- The convex hull of 2–3 nearby points creates a **triangle that is only slightly larger than the triangle formed by the points themselves**
- 55px padding adds 55px in each direction — on a ~1020×900 canvas, this is ~5–6% of the width
- The `smoothPoly()` call shrinks the hull slightly (Chaikin corner-cutting pulls vertices inward)
- Result: territories are **small decorative outlines** around sector points, not **large filled regions** that fill the canvas

**Numerical example — Research Division:**
- Owns sectors: archive (inner), meridian (inner), prism (inner), sol-prime (core)
- Archive is at canvas position ~center-left, the others nearby
- Convex hull of 4 nearby points ≈ a ~120×100px quadrilateral
- After 55px padding ≈ ~230×210px polygon
- On a 1020×900 canvas = **23% × 23%** — not a territory, a small box

**What it SHOULD be:** Each faction territory should cover **25–40% of the canvas** in one dimension, with territories collectively covering **80–90% of the map area** (with slight gaps between them).

### 3.2 Territory Fill Alpha

**File:** `frontend/starmap.html`, `getViewParams()`, line 2200

```
Territory view: zoneFillAlpha = 0.12
```

12% alpha on a dark background (#0a0a1a) makes the fill nearly invisible. The gradient (center 1.5× stronger → edge 0.4×) gives a max effective alpha of ~0.18 at center, ~0.05 at edges. **Functionally invisible.**

**What it SHOULD be:** 0.18–0.25 alpha (18–25%) for a visible but not overwhelming territory fill. The reference territory map shows clearly distinguishable colored regions.

### 3.3 Territory Border

**File:** `getViewParams()`, line 2202

```
Territory view: zoneBorderWidth = 3.5, zoneBorderAlpha = 0.5
```

3.5px at 50% alpha on small polygons = thin, faint lines that don't read as territory borders.

**What it SHOULD be:** 4–6px at 70–90% alpha on LARGE territories. The border must be clearly visible as a territory boundary, not a decorative outline.

### 3.4 Faction Home Expansion

**File:** `buildNodesSpatial()`, lines ~1382–1395

```
FACTION_HOME_EXPANSION = 2.8
maxR = Math.min(W, H) * 0.42
```

This pushes the 8 home sectors outward from their centroid by 2.8×. The problem:
- Home sectors start near center (all are "inner" or "core" type)
- Even at 2.8× expansion, 8 factions in a ring at 42% of canvas height = each faction gets ~45° of arc
- The homes are pushed apart, but the **territory polygons around them don't grow to fill the space**
- Non-home sectors are clustered at 0.45× tightness — making tiny sub-clusters

**What it SHOULD be:** The expansion is a reasonable idea but insufficient alone. Territories must be **computed as large regions** that fill the space between faction homes, not as small hulls of sector points.

### 3.5 NPC Layout

**File:** `buildNodesSpatial()`, lines ~1503–1541

```
baseRadius = 18, ringSpacing = 16
Inner ring: up to 6 NPCs, middle ring: up to 8, outer ring: up to 10
NPC dot radius = 3 + activity * 5 (max ~8px)
```

- 8 NPCs at a home sector create a ~50px diameter orbit cluster
- This is small but still visually dominant because the dots have bright colors and glow effects
- When a sector has many NPCs (some have 10+), the orbit cluster becomes a dense blob
- The NPC glow (3× radius radial gradient) creates a bright haze around each cluster

**What it SHOULD be:** In territory view at default zoom, NPCs should be **tiny dots** (2–3px radius max) with minimal glow. They are secondary information — the territory regions are the primary visual.

### 3.6 Sector Labels

**File:** `draw()`, lines ~2427–2437

```
Font: (rmLabelSize || 12)px Courier New
Alpha: 0.5 (unhovered), 0.9 (hovered)
No background box
Region type sub-label hidden unless zoom >= 1.3
```

12px Courier at 50% alpha on a dark background with no backing box = **unreadable at default zoom**. Sector names are critical for understanding territory geography.

**What it SHOULD be:** 13–14px bold font, 80%+ alpha, with a semi-transparent background box (dark rect behind text) for contrast. Faction name labels should be even larger (16–18px bold).

### 3.7 Faction Name Labels

**File:** `draw()`, lines ~2543–2563

```
Font: bold 18px Courier New (territory mode labelSize)
Alpha: 0.9 (territory mode labelAlpha)
Position: below polygon (labelY = bounds.maxY + 18)
Sub-label: sector list at 14px, 35% alpha
```

The label size and alpha are acceptable, but:
- The position is **below** the polygon — for tiny polygons, this pushes the label far from the territory center
- The "SECTORS: archive, meridian, prism, sol-prime" sub-label is clutter — listing sector names in a comma-separated string under each faction label is noisy
- No background box on the label

**What it SHOULD be:** Faction name centered **inside** the territory region (at the polygon centroid or faction home position). Sub-label replaced by a simple territory-type indicator. Background box for readability.

---

## 4. PROPOSED RENDERING ARCHITECTURE

### 4.1 Core Concept: Territory Regions, Not Zone Circles

The fundamental change is to compute **large territory regions** that fill the canvas, rather than small convex hulls of sector points. Two approaches:

#### Approach A: Voronoi Partition (Recommended)

Divide the entire canvas into territory regions using a **Voronoi diagram** seeded by faction home positions.

```
Algorithm:
1. Place 8 faction home positions on the canvas (using existing expansion logic)
2. Place sol-prime at center as a neutral seed
3. Compute Voronoi diagram of these 9 seeds
4. Clip each Voronoi cell to the canvas bounds
5. Each cell = one faction's territory region
6. Color each cell with the faction's color at 20% alpha
7. Draw thick borders along Voronoi edges (4px, 80% alpha)
8. Place faction name label at the centroid of each cell
9. Place sector markers INSIDE their owning faction's cell
10. NPC dots tiny and secondary
```

**Why Voronoi:**
- Guarantees full canvas coverage — no gaps
- Each faction gets a clear, non-overlapping region
- Regions are naturally large (12–15% of canvas area each)
- Borders are naturally defined by the diagram edges
- Well-understood algorithm, many JS implementations exist
- Visually matches territory maps in strategy games and the reference image

**Voronoi implementation:** Fortunate's algorithm is complex, but a **simpler approach** works for 9 seeds:
- For each pixel (or a grid of sample points), find the nearest seed
- Group pixels by nearest seed → defines each cell's boundary
- Or use a **brute-force polygon approach**: for each pair of adjacent seeds, compute the perpendicular bisector, clip it to canvas bounds, and intersect bisectors to form cell polygons

**Practical approach for 9 seeds:** Use a lightweight Voronoi library from CDN, or implement the **half-plane intersection** method for small N:
1. For each seed, start with the canvas rectangle as the initial cell polygon
2. For every other seed, cut the cell polygon along the perpendicular bisector of the line connecting the two seeds (keep the side closer to this seed)
3. The result is the Voronoi cell as a convex polygon

This is O(N²) per cell but N=9, so it's trivially fast.

#### Approach B: Expanded Convex Hulls (Incremental Fix)

Keep the current hull-based approach but dramatically increase padding and add inter-territory spacing.

```
Algorithm:
1. Compute convex hull of each faction's sector positions (as now)
2. Pad hull by 200–300px instead of 55px
3. Clip padded hulls to canvas bounds
4. Resolve overlaps by shrinking overlapping regions
5. Use higher fill alpha (0.20) and thicker borders (5px, 80% alpha)
```

**Why NOT recommended:**
- Overlap resolution between 8 large padded hulls is complex
- Some factions own nearby sectors → hulls will heavily overlap
- Padding a hull of 2–3 points by 300px creates a large shape but the shape is arbitrary (depends on hull geometry, not on which space "belongs" to which faction)
- Doesn't guarantee full canvas coverage
- Doesn't produce clean borders between territories

### 4.2 Recommended Architecture: Approach A (Voronoi Partition)

```
Layer stack (draw order, bottom to top):
┌─────────────────────────────────────────────┐
│ 1. Background (#0a0a1a)                     │
│ 2. Background stars (twinkle)                │
│ 3. Territory fills (Voronoi cells, 20% alpha)│
│ 4. Territory borders (Voronoi edges, 4px)    │
│ 5. Contested overlay (pulsing orange, if any)│
│ 6. Adjacency lines (faint, territory=hidden) │
│ 7. Relationship lines (faint, territory=off) │
│ 8. Sector markers (10–14px dots with labels) │
│ 9. NPC dots (2–3px, minimal glow)            │
│ 10. Faction name labels (centered in cell)   │
│ 11. Selection highlight (pulsing white border)│
└─────────────────────────────────────────────┘
```

### 4.3 Detailed Changes by Component

#### 4.3.1 New: Voronoi Cell Computation

**New function:** `computeVoronoiCells(seeds, canvasBounds)`

```
Input: 9 seeds [{x, y, factionId}] + canvas bounds {minX, minY, maxX, maxY}
Output: 9 cell polygons [{factionId, polygon: [{x,y}...]}]

Algorithm (half-plane intersection):
  for each seed S:
    cell = canvasBounds rectangle (as polygon)
    for each other seed T:
      bisector = perpendicular bisector of segment S-T
      cell = clipPolygon(cell, bisector half-plane closer to S)
    result.push({factionId: S.factionId, polygon: cell})
```

**Dependency:** Need a `clipPolygon(polygon, line)` function that cuts a convex polygon along a line. This is a standard computational geometry operation (Sutherland-Hodgman variant for convex polygon × half-plane).

**Implementation complexity:** ~80 lines of new code. No external library needed.

#### 4.3.2 Modified: Territory Fill

**Change:** Draw Voronoi cell polygons instead of convex hulls.

```
Before: padPolygon(convexHull(sectorPositions), 55)  → tiny hull
After:  voronoiCells[factionId].polygon               → large region filling canvas

Fill: hexToRgba(factionColor, 0.20)  (up from 0.12)
Gradient: optional — center slightly stronger (0.25) → edge (0.15)
```

#### 4.3.3 Modified: Territory Borders

**Change:** Draw Voronoi edges instead of hull outlines.

```
Before: 3.5px at 50% alpha on small hull
After:  4px at 80% alpha on large cell polygon

Neutral borders (between two faction cells): 4px, blend of both faction colors at 70% alpha
External borders (cell → canvas edge): 2px, faction color at 50% alpha
```

#### 4.3.4 Modified: Faction Name Labels

**Change:** Center label inside Voronoi cell, add background box.

```
Before: label below polygon, no box
After:  label at cell centroid, with dark background box

Box: fillStyle rgba(10,10,26,0.75), 4px padding around text
Font: bold 16px Courier New, faction color at 95% alpha
Sub-label: region type ("INNER RING", "OUTER RING", etc.) at 12px, 60% alpha
         OR: owned sector count ("3 SECTORS") — not a comma-separated name list
```

#### 4.3.5 Modified: Sector Labels

**Change:** Add background box, increase alpha.

```
Before: 12px Courier, 50% alpha, no box
After:  13px bold Courier, 80% alpha, with dark background box

Box: fillStyle rgba(10,10,26,0.65), 3px padding
Show always in territory mode (not just at zoom >= 1.3)
```

#### 4.3.6 Modified: NPC Rendering in Territory Mode

**Change:** Reduce NPC visual weight in territory view.

```
Before: radius 3+activity*5 (max ~8px), full glow (3× radius radial gradient)
After:  radius 2+activity*2 (max ~4px), reduced glow (1.5× radius, 0.1 alpha)

In territory mode at default zoom:
  - NPC dots: 2px base, no individual glow
  - NPC labels: hidden (already done by getLabelPriority returning 0)
  - Faction affiliation ring: 1px (down from 3.5px)
```

#### 4.3.7 Modified: Relationship Lines in Territory Mode

**Change:** Hide relationship lines by default in territory view.

```
Before: lineAlphaScale = 0.25 (still visible)
After:  lineAlphaScale = 0 in territory mode (fully hidden)

When faction selected: show only that faction's relationship lines at 0.3 alpha
When no faction selected: no relationship lines in territory mode
```

#### 4.3.8 Unchanged: Kill Switches and Fallback

- `?spatial=false` → legacy layout (already works)
- `?debug=legacy-layout` → legacy layout (already works)
- Default remains legacy until visual quality passes operator review
- `SPATIAL_RENDERING_ENABLED` from API respected

---

## 5. FILES TO MODIFY

| File | Change | Scope |
|------|--------|-------|
| `frontend/starmap.html` | All rendering changes | ~300 lines modified/added |
| `frontend/starmap.html` | New `computeVoronoiCells()` function | ~80 lines added |
| `frontend/starmap.html` | New `clipPolygonByHalfPlane()` function | ~40 lines added |
| `frontend/starmap.html` | Modified `buildNodesSpatial()` | Replace hull construction with Voronoi cell lookup |
| `frontend/starmap.html` | Modified `draw()` | New draw order, territory fills from Voronoi, label boxes |
| `frontend/starmap.html` | Modified `getViewParams()` | Updated alphas, sizes |
| `frontend/starmap.html` | Modified NPC rendering section | Reduced sizes in territory mode |

**No backend changes.** No `simulation.html` changes. No new files.

---

## 6. VISUAL ACCEPTANCE CHECKLIST

The operator will review a screenshot of the spatial starmap at default zoom (`?spatial=true`). The following must ALL pass:

### 6.1 Territory Regions (CRITICAL — must pass or SPATIAL-03B is rejected)

- [ ] **8 distinct colored regions** are immediately visible covering most of the canvas
- [ ] Each region has a **strong colored border** (clearly visible, not faint)
- [ ] Each region has a **visible fill** (colored area, not invisible)
- [ ] Regions are **non-overlapping** (no confusing double-color areas at default zoom)
- [ ] **No large gaps** between regions (canvas is mostly covered)
- [ ] Faction name is **readable inside its region** without zooming
- [ ] At a glance, the operator can say which colored region belongs to which faction

### 6.2 Sector Markers (CRITICAL)

- [ ] Sector names are **readable at default zoom** (background box + sufficient alpha)
- [ ] Sectors appear **inside** their owning faction's colored region
- [ ] Sector dots are visible but secondary to territory fills

### 6.3 NPC Dots (MAJOR)

- [ ] NPCs are **small and secondary** — not the dominant visual element
- [ ] No dense central pile of NPCs
- [ ] NPC dots don't obscure territory fills or sector labels

### 6.4 Interaction (MAJOR)

- [ ] Clicking inside a territory region selects that faction
- [ ] Clicking a sector marker shows sector info
- [ ] Clicking an NPC dot shows NPC info
- [ ] Escape deselects faction (already works)
- [ ] Zoom and pan work correctly on Voronoi-rendered territories

### 6.5 Mode Switching (MINOR)

- [ ] Territory mode: hides adjacency + relationship lines, shows large territories
- [ ] Network mode: shows adjacency lines, territories fade to background
- [ ] Crisis mode: highlights conflict areas, territories at medium opacity

### 6.6 Fallback (MUST)

- [ ] `?spatial=false` or no param → legacy layout (unchanged from current)
- [ ] `?spatial=true` → new Voronoi territory rendering

---

## 7. RISK ASSESSMENT

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Voronoi cells look too geometric / "gamey" | Medium | Medium | Add organic deformation (existing breath/wobble code can be reused on Voronoi cell polygons) |
| Sector positions fall outside their faction's Voronoi cell | Low | High | Verify sector→cell assignment against territory data; if a sector is in the wrong cell, expand that cell or adjust seed positions |
| Performance: Voronoi computation per frame | Very Low | Low | Compute Voronoi cells ONCE in `buildNodesSpatial()`, not in `draw()`. Only recompute when data changes. |
| Border between two factions is ambiguous | Low | Low | Draw borders as the shared edge of adjacent Voronoi cells with both faction colors blended |
| Fallback still works | Very Low | High | No changes to legacy code path — spatial mode is opt-in via `?spatial=true` |

---

## 8. IMPLEMENTATION ORDER

If the operator approves this plan, implementation proceeds in this order:

1. **Add Voronoi computation functions** (`computeVoronoiCells`, `clipPolygonByHalfPlane`)
2. **Modify `buildNodesSpatial()`** to compute Voronoi cells and store them as `voronoiCells[]`
3. **Modify `draw()` territory section** to render Voronoi cell fills + borders instead of hull circles
4. **Update `getViewParams()`** with new alphas and sizes
5. **Add label background boxes** for faction names and sector labels
6. **Reduce NPC visual weight** in territory mode
7. **Hide relationship lines** in territory mode (set `lineAlphaScale = 0`)
8. **Deploy to VPS** and take screenshot for operator review
9. **If operator approves:** change default from legacy to spatial (remove `?spatial=true` requirement)
10. **If operator rejects:** iterate on the specific visual problems identified

---

## 9. WHAT "DONE" LOOKS LIKE

A screenshot at `https://federation-game.deliberatefederationfederation.cloud/starmap.html?spatial=true` at default zoom (no zoom, no pan) shows:

- A dark starfield background
- 8 large, clearly colored territory regions filling the canvas
- Each region labeled with its faction name (readable, boxed)
- Sector dots and labels visible inside their regions
- NPC dots small and non-distracting
- No network clutter
- The operator can instantly say: "That blue region is Research Division, that red region is Military Command, that green region is Diplomatic Corps..."

Until that screenshot passes operator review, SPATIAL-03B is not complete.

---

## 10. APPROVAL

**Operator:** Review this document. If you approve, say "approved" and I will implement SPATIAL-03B per this plan. If you want changes to the plan, specify what to change.

- [ ] **APPROVED** — proceed with implementation
- [ ] **CHANGES REQUESTED** — specify below:
  _______________________________________________
  _______________________________________________
  _______________________________________________
