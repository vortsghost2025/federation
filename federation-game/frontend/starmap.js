const API = '/map/data';
const POLL_MS = 5000;

/* ═══ Utility: HTML escape + Markdown renderer for AI chat ═══ */
function esc(s){if(s==null)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function md(text){
if(text==null)return '';
var s=String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
s=s.replace(/\*(.+?)\*/g,'<em>$1</em>');
s=s.replace(/`(.+?)`/g,'<code>$1</code>');
s=s.replace(/^### (.+)$/gm,'<h3>$1</h3>');
s=s.replace(/^## (.+)$/gm,'<h2>$1</h2>');
s=s.replace(/^# (.+)$/gm,'<h1>$1</h1>');
s=s.replace(/^-{3,}$/gm,'<hr>');
s=s.replace(/^&gt; (.+)$/gm,'<blockquote>$1</blockquote>');
s=s.replace(/^- (.+)$/gm,'<li>$1</li>');
s=s.replace(/^\d+\.\s(.+)$/gm,'<li>$1</li>');
s=s.replace(/((?:<li>.*?<\/li>\s*)+)/g,'<ul>$1</ul>');
s=s.replace(/((?:\|.*\|(?:\s|$)\s*)+)/g,function(m){
var rows=m.trim().split('\n');var html='<table>';for(var r=0;r<rows.length;r++){var row=rows[r].trim();if(row.match(/^\|[-: ]+\|$/))continue;var cells=row.split('|').slice(1,-1);var isHead=(r===0&&rows.length>1&&rows[1].match(/^\|[-: ]+\|$/));var tag=isHead?'th':'td';html+='<tr>';for(var c=0;c<cells.length;c++){html+='<'+tag+'>'+cells[c].trim()+'</'+tag+'>'}html+='</tr>'}html+='</table>';return html});
s=s.replace(/\n/g,'<br>');
s=s.replace(/<\/(h[1-3]|blockquote|ul|table)>\s*<br>/g,'</$1>');
s=s.replace(/(<br>\s*){3,}/g,'<br><br>');
return s}

// --- State ---
let mapData = null;
let nodes = [];
let factions = {}; // {fid: {color, name, ...}}

// Faction banner tooltips + icons
const FACTION_ICONS = {
  research_division: 'M32 12 L45 30 L68 30 L55 48 L45 66 L32 54 L18 66 L6 48 L19 31 L32 12 Z',
  military_command: 'M20 15 L35 35 L50 20 L65 35 L80 15 L80 50 L65 70 L50 55 L35 70 L20 50 Z',
  diplomatic_corps: 'M45 12 L60 35 L45 58 L30 35 Z',
  consciousness_collective: 'M15 35 A20 20 0 1 1 55 35 A20 20 0 1 1 15 35 M25 35 A10 10 0 1 1 45 35 A10 10 0 1 1 25 35 M50 35 L70 35',
  cultural_ministry: 'M30 12 A5 5 0 0 1 40 20 L50 35 L40 50 A5 5 0 0 1 30 58 L30 42 L20 42 L20 28 L30 28 Z',
  economic_council: 'M20 45 C30 20 50 20 60 45 C50 70 30 70 20 45 Z',
  exploration_initiative: 'M50 10 L65 45 L35 45 Z',
  preservation_society: 'M35 15 L45 15 L45 25 L60 25 L60 50 L35 50 Z'
};

// Tooltip utility
let factionZones = []; // {fid, fcx, fcy, zoneR, color, fdata, groupSize, polygon:[], labelX, labelY}
let stars = [];
// --- Spatial state (SPATIAL-03) ---
let spatialMode = false; // true when spatial data is available and rendering is enabled
let spatialSectors = {}; // sectorId -> {cx, cy, data} (canvas coords + raw sector data)
let spatialAdjacencies = []; // [{from, to, fromX, fromY, toX, toY}]
let spatialSectorNodes = []; // sector center markers for click/hover
let spatialBounds = null; // {minPx, maxPx, minPy, maxPy, sectorScale, midX, midY} — computed world-to-screen transform for FIT button
let voronoiCells = []; // SPATIAL-03B: Voronoi territory cells [{factionId, polygon, centroid}]
const SPATIAL_FILL_RATIO = 0.65; // fraction of viewport that spatial map should fill
const NETWORK_HIGH_CONTRAST = 1.8; // multiplier for network-view relationship line visibility
// SPATIAL-03A: Selected faction for isolation/fade behavior
let selectedFaction = null; // faction_id or null — when set, fade all other factions
// Kill switch: URL params or env can force legacy layout
// SPATIAL-03A visual review failed — spatial frontend is opt-in until visual quality passes operator review
// Default: spatial layout. Use ?spatial=false to force legacy layout.
const _urlParams = new URLSearchParams(window.location.search);
const _forceLegacy = (_urlParams.has('spatial') && _urlParams.get('spatial') === 'false')
|| (_urlParams.has('debug') && _urlParams.get('debug') === 'legacy-layout');
// SPATIAL_RENDERING_ENABLED checked from API response — if backend sets it false, respect that
const REGION_COLORS = { core: '#4fc3f7', inner: '#66bb6a', outer: '#ffa726', frontier: '#ef5350' };
// Track if spatial mode was ever successfully activated (sticky)
let _spatialModeEverActivated = false;
let zoom = 1;
let panX = 0, panY = 0;
let dragging = false, dragStartX, dragStartY, panStartX, panStartY;
let hoveredNode = null;
let selectedNode = null;
let hoveredFaction = null;
let canvas, ctx;
let W, H;
let sidebarW = 420;
let lastUpdate = 0;

// Faction banner tooltips
function showFactionTooltip(fid, event) {
  const factions = mapData.factions || {};
  const fdata = factions[fid];
  if (!fdata) return;
  
  let tooltip = document.getElementById(`faction-tooltip-${fid}`);
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.id = `faction-tooltip-${fid}`;
    tooltip.className = 'faction-tooltip';
    
    // Use assets from /photos/, fallback to SVG icon
    const bannerImage = 'url("./photos/Helix-Nebula-Chandra-Archive-7f9c730.webp")';
    tooltip.innerHTML = `
      <div class="faction-tooltip-inner">
        <div style="position: relative; z-index: 1;">
          <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
            <div style="width:32px;height:32px;background:${fdata.color};border-radius:4px;display:flex;align-items:center;justify-content:center;">
              <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cpath d='${FACTION_ICONS[fid] || 'M50 25 L70 45 L50 90 L30 45 Z'}' fill='%23ffffff'/%3E%3C/svg%3E" alt="${fid} logo" style="width:20px;height:20px;" />
            </div>
            <h3>${fdata.display_name || fid}</h3>
          </div>
          <div class="faction-slogan">${fdata.slogan || 'Motivational faction slogan'}</div>
        </div>
        <div style="margin-top:12px; font-size:0.875rem; border-top:1px solid rgba(255,255,255,0.2); padding-top:6px;">
          <!-- Stats placeholder -->
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
            <div><span style="opacity:0.7">Cohesion:</span> ?</div>
            <div><span style="opacity:0.7">Morale:</span> ?</div>
            <div><span style="opacity:0.7">Territory:</span> ?</div>
            <div><span style="opacity:0.7">Key NPCs:</span> ?</div>
          </div>
        </div>
        <div style="position: absolute; inset: 0; background-image: ${bannerImage}; background-size: cover; background-position: center; opacity: 0.15; border-radius: 6px; z-index: 0;"></div>
      </div>
    `;
    document.getElementById('faction-tooltip-container').appendChild(tooltip);
  }
  
  // Dynamic positioning
  tooltip.style.opacity = '1';
  tooltip.style.left = `${Math.min(event.clientX + 24, window.innerWidth - 340)}px`;
  tooltip.style.top = `${Math.min(event.clientY + 16, window.innerHeight - 200)}px`;
}

function hideFactionTooltip(fid) {
  const tooltip = document.getElementById(`faction-tooltip-${fid}`);
  if (tooltip) tooltip.style.opacity = '0';
}
let currentView = 'territory'; // 'territory' | 'network' | 'crisis'
let labelMode = 'important'; // 'factions' | 'important' | 'all' — label display priority
let readableSpatialMode = false; // dedicated readable spatial mode toggle
let astroMode = true; // Galaxy View toggle — use nebula backdrop

// Faction layout angles (8 factions in a circle)
const FACTION_ORDER = [
  'research_division', 'military_command', 'diplomatic_corps',
  'consciousness_collective', 'cultural_ministry', 'economic_council',
  'exploration_initiative', 'preservation_society'
];

// Faction display names for tooltips
const FACTION_DISPLAY = {
  research_division: 'Research Division',
  military_command: 'Military Command',
  diplomatic_corps: 'Diplomatic Corps',
  consciousness_collective: 'Consciousness Collective',
  cultural_ministry: 'Cultural Ministry',
  economic_council: 'Economic Council',
  exploration_initiative: 'Exploration Initiative',
  preservation_society: 'Preservation Society'
};

// Category colors for unaffiliated NPCs
const CATEGORY_COLORS = {
  companion: '#ffd700',
  rival: '#ef5350',
  neutral: '#78909c',
  enigma: '#ab47bc',
  unknown: '#546e7a'
};

function init() {
  canvas = document.getElementById('starmap');
  ctx = canvas.getContext('2d');
  resize();
  window.addEventListener('resize', resize);
  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mousedown', onMouseDown);
  canvas.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('wheel', onWheel);
  canvas.addEventListener('click', onClick);
        canvas.addEventListener('dblclick', onDblClick);
// SPATIAL-03A: Escape key deselects faction
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    selectedFaction = null;
    selectedNode = null;
    showDetail(null);
  }
});

// SPATIAL-03A: Force spatial mode on first load if ?spatial=true is present
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.has('spatial') && urlParams.get('spatial') === 'true') {
  spatialMode = true;
  spatialSectors = {};
  spatialAdjacencies = [];
  spatialSectorNodes = [];
  buildNodesSpatial();
  draw();
  document.getElementById('readable-spatial-btn').classList.add('active');
}
  document.getElementById('search-input').addEventListener('input', onSearch);

  for (let i = 0; i < 400; i++) {
    stars.push({
      x: Math.random() * 3000 - 500,
      y: Math.random() * 2000 - 200,
      r: Math.random() * 1.5 + 0.3,
      brightness: Math.random() * 0.6 + 0.2,
      twinkleSpeed: Math.random() * 0.003 + 0.001,
      twinklePhase: Math.random() * Math.PI * 2
    });
  }

  initStarmapReadableMode();
  fetchData();
  setInterval(fetchData, POLL_MS);
  requestAnimationFrame(draw);
}

function resize() {
  W = window.innerWidth - sidebarW;
  H = window.innerHeight;
  canvas.width = W * devicePixelRatio;
  canvas.height = H * devicePixelRatio;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
}

// --- View toggle ---
function setView(v) {
currentView = v;
document.querySelectorAll('.vt-btn').forEach(b => {
b.classList.toggle('active', b.dataset.view === v);
});
// Auto-set label mode defaults per view — only upgrade, never downgrade
if (v === 'network' && labelMode === 'factions') setLabelMode('important');
else if (v === 'crisis' && labelMode === 'factions') setLabelMode('important');
buildMapRead(); // update panel when mode changes
}

// --- Label mode toggle ---
function setLabelMode(mode) {
  labelMode = mode;
  document.querySelectorAll('.lt-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.labels === mode);
  });
  draw();
}
function toggleReadableSpatialMode() {
  readableSpatialMode = !readableSpatialMode;
  const btn = document.getElementById('readable-spatial-btn');
  if (readableSpatialMode) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
  // Trigger redraw to apply changes immediately
  draw();
}

// --- Data fetch ---
      async function fetchData() {
    const data = await fedFetch('mapData', API);
    if (!data) return;
    mapData = data;
    lastUpdate = Date.now();
    _sectorOwnerCache = {}; // SPATIAL-03A: clear sector owner cache on data refresh
    buildNodes();
    updateUI();
  }

function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h;
}
function seededRand(seed) {
  let s = seed | 0;
  return function() { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
}

// --- Convex hull & polygon algorithms ---

// Gift-wrapping convex hull. Input: [{x,y},...], returns ordered hull vertices.
function convexHull(points) {
  if (points.length < 3) return points.slice();
  // Find leftmost point
  let start = 0;
  for (let i = 1; i < points.length; i++) {
    if (points[i].x < points[start].x || (points[i].x === points[start].x && points[i].y < points[start].y)) start = i;
  }
  const hull = [];
  let current = start;
  do {
    hull.push(points[current]);
    let next = 0;
    for (let i = 1; i < points.length; i++) {
      if (i === current) continue;
      const cross = crossProduct(points[current], points[next], points[i]);
      if (next === current || cross > 0 || (cross === 0 && dist2(points[current], points[i]) > dist2(points[current], points[next]))) {
        next = i;
      }
    }
    current = next;
    if (hull.length > points.length) break; // safety
  } while (current !== start);
  return hull;
}

function crossProduct(o, a, b) {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

function dist2(a, b) {
  const dx = a.x - b.x, dy = a.y - b.y;
  return dx*dx + dy*dy;
}

// Expand hull outward by N pixels. Offsets each vertex along the average outward normal of its adjacent edges.
function padPolygon(polygon, padding) {
  if (polygon.length < 3) return polygon.slice();
  const n = polygon.length;
  const result = [];
  for (let i = 0; i < n; i++) {
    const prev = polygon[(i - 1 + n) % n];
    const curr = polygon[i];
    const next = polygon[(i + 1) % n];
    // Edge normals: rotate edge 90° counter-clockwise for outward normal on CCW polygons
    const e1x = curr.x - prev.x, e1y = curr.y - prev.y;
    const len1 = Math.sqrt(e1x*e1x + e1y*e1y) || 1;
    const n1x = -e1y / len1, n1y = e1x / len1;
    const e2x = next.x - curr.x, e2y = next.y - curr.y;
    const len2 = Math.sqrt(e2x*e2x + e2y*e2y) || 1;
    const n2x = -e2y / len2, n2y = e2x / len2;
    // Average normal
    let nx = (n1x + n2x) / 2, ny = (n1y + n2y) / 2;
    const nlen = Math.sqrt(nx*nx + ny*ny) || 1;
    nx /= nlen; ny /= nlen;
    result.push({ x: curr.x + nx * padding, y: curr.y + ny * padding });
  }
  return result;
}

// Chaikin corner-cutting smoothing: inserts midpoints along each edge, rounds corners.
function smoothPoly(polygon, iterations) {
  if (polygon.length < 3 || iterations <= 0) return polygon;
  let pts = polygon;
  for (let iter = 0; iter < iterations; iter++) {
    const next = [];
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const curr = pts[i];
      const nxt = pts[(i + 1) % n];
      next.push({ x: curr.x * 0.75 + nxt.x * 0.25, y: curr.y * 0.75 + nxt.y * 0.25 });
      next.push({ x: curr.x * 0.25 + nxt.x * 0.75, y: curr.y * 0.25 + nxt.y * 0.75 });
    }
    pts = next;
  }
  return pts;
}

// Ray-casting point-in-polygon test
function pointInPolygon(px, py, polygon) {
  if (!polygon || polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x, yi = polygon[i].y;
    const xj = polygon[j].x, yj = polygon[j].y;
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

// Bounding-box overlap check for faction polygons (fast, conservative)
function polygonsOverlap(poly1, poly2) {
  if (!poly1 || !poly2 || poly1.length < 3 || poly2.length < 3) return false;
  const b1 = polyBounds(poly1), b2 = polyBounds(poly2);
  if (b1.maxX < b2.minX || b2.maxX < b1.minX || b1.maxY < b2.minY || b2.maxY < b1.minY) return false;
  // Sample test: check if any vertex of poly2 is inside poly1 (or vice versa)
  for (let i = 0; i < poly2.length; i += Math.max(1, Math.floor(poly2.length / 8))) {
    if (pointInPolygon(poly2[i].x, poly2[i].y, poly1)) return true;
  }
  for (let i = 0; i < poly1.length; i += Math.max(1, Math.floor(poly1.length / 8))) {
    if (pointInPolygon(poly1[i].x, poly1[i].y, poly2)) return true;
  }
  return false;
}

// --- SPATIAL-03B: Voronoi territory partition ---
// Compute Voronoi cells for faction territories using half-plane intersection.
// For N seeds, each cell is built by starting with the canvas rectangle and
// clipping it against the perpendicular bisector of every other seed (keeping
// the half-plane closer to this seed). O(N²) per cell but N≤9 so trivially fast.

function computeVoronoiCells(seeds, bounds) {
  // seeds: [{x, y, factionId}]
  // bounds: {minX, minY, maxX, maxY}
  // returns: [{factionId, polygon: [{x,y}...], centroid: {x,y}}]
  const cells = [];
  const canvasRect = [
    { x: bounds.minX, y: bounds.minY },
    { x: bounds.maxX, y: bounds.minY },
    { x: bounds.maxX, y: bounds.maxY },
    { x: bounds.minX, y: bounds.maxY }
  ];
  for (let i = 0; i < seeds.length; i++) {
    let cell = canvasRect.slice(); // start with full canvas
    const si = seeds[i];
    for (let j = 0; j < seeds.length; j++) {
      if (i === j) continue;
      const sj = seeds[j];
      // Perpendicular bisector of si–sj: the line where distance to si == distance to sj
      // Midpoint
      const mx = (si.x + sj.x) / 2;
      const my = (si.y + sj.y) / 2;
      // Direction of bisector (perpendicular to si→sj)
      const dx = sj.x - si.x;
      const dy = sj.y - si.y;
      // The bisector passes through (mx, my) with direction (dy, -dx)
      // We want the half-plane containing si: points P where (P - midpoint) · (si - sj) > 0
      // i.e., (px - mx)*(-dx) + (py - my)*(-dy) > 0  →  (px - mx)*dx + (py - my)*dy < 0
      // Clip the cell polygon to keep only the side where dot < 0 (closer to si)
      cell = clipPolygonByLine(cell, mx, my, dx, dy, false);
      if (cell.length < 3) break; // cell fully consumed, degenerate
    }
    const centroid = polyCentroid(cell);
    cells.push({ factionId: si.factionId, polygon: cell, centroid });
  }
  return cells;
}

// Clip a convex polygon against an infinite line defined by point (lx, ly) and direction (dx, dy).
// The line passes through (lx, ly) with direction vector (dx, dy).
// keepSide=false: keep points where (P-linePoint)·direction < 0
// keepSide=true: keep points where (P-linePoint)·direction >= 0
// Uses Sutherland-Hodgman-style clipping for convex polygon × half-plane.
function clipPolygonByLine(polygon, lx, ly, dx, dy, keepSide) {
  if (polygon.length < 3) return polygon.slice();
  const output = [];
  const n = polygon.length;
  for (let i = 0; i < n; i++) {
    const curr = polygon[i];
    const next = polygon[(i + 1) % n];
    const currDot = (curr.x - lx) * dx + (curr.y - ly) * dy;
    const nextDot = (next.x - lx) * dx + (next.y - ly) * dy;
    const currInside = keepSide ? (currDot >= 0) : (currDot < 0);
    const nextInside = keepSide ? (nextDot >= 0) : (nextDot < 0);
    if (currInside) {
      output.push(curr);
      if (!nextInside) {
        // Edge crosses from inside to outside — add intersection
        const inter = lineIntersect(curr.x, curr.y, next.x, next.y, lx, ly, lx + dy, ly - dx);
        if (inter) output.push(inter);
      }
    } else if (nextInside) {
      // Edge crosses from outside to inside — add intersection then next
      const inter = lineIntersect(curr.x, curr.y, next.x, next.y, lx, ly, lx + dy, ly - dx);
      if (inter) output.push(inter);
    }
    // If both outside, add nothing
  }
  return output;
}

// Find intersection of line segment (x1,y1)→(x2,y2) with infinite line through (lx1,ly1)→(lx2,ly2)
// Returns {x, y} or null if parallel
function lineIntersect(x1, y1, x2, y2, lx1, ly1, lx2, ly2) {
  const denom = (x1 - x2) * (ly1 - ly2) - (y1 - y2) * (lx1 - lx2);
  if (Math.abs(denom) < 1e-10) return null; // parallel
  const t = ((x1 - lx1) * (ly1 - ly2) - (y1 - ly1) * (lx1 - lx2)) / denom;
  return { x: x1 + t * (x2 - x1), y: y1 + t * (y2 - y1) };
}

function polyBounds(poly) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of poly) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

function polyCentroid(poly) {
  if (!poly || poly.length === 0) return { x: 0, y: 0 };
  let sx = 0, sy = 0;
  for (const p of poly) { sx += p.x; sy += p.y; }
  return { x: sx / poly.length, y: sy / poly.length };
}

// Draw a polygon path on ctx (does not stroke/fill — caller does that)
function tracePolygonPath(ctx, poly) {
  if (!poly || poly.length < 3) return;
  ctx.beginPath();
  ctx.moveTo(poly[0].x, poly[0].y);
  for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i].x, poly[i].y);
  ctx.closePath();
}

// --- Build node positions ---
function buildNodes() {
  if (!mapData) return;
  // SPATIAL-02.5: Check kill switches before entering spatial mode
  // 1. URL params: ?spatial=false or ?debug=legacy-layout → force legacy
  // 2. Backend flag: mapData.spatial_rendering_enabled === false → force legacy
  // 3. Minimum visible-size: if computed scale would be too tiny, fall back
  // 4. Sticky spatial mode: if spatial mode was ever successfully activated, stay in spatial mode
  const sectors = mapData.sectors;
  const forceSpatial = _spatialModeEverActivated && !_forceLegacy;
  if ((sectors && sectors.length > 0 && !_forceLegacy && mapData.spatial_rendering_enabled !== false) || forceSpatial) {
    // Pre-check: would the spatial map be meaningfully visible?
    let mnX=Infinity, mxX=-Infinity, mnY=Infinity, mxY=-Infinity;
    for (const s of sectors) { if(s.x<mnX)mnX=s.x; if(s.x>mxX)mxX=s.x; if(s.y<mnY)mnY=s.y; if(s.y>mxY)mxY=s.y; }
    const rX=Math.max(1,mxX-mnX), rY=Math.max(1,mxY-mnY);
    const preScale = Math.min((W*SPATIAL_FILL_RATIO)/rX, (H*SPATIAL_FILL_RATIO)/rY);
    // If scale < 0.3, the map is too compressed to be readable — fall back (unless sticky)
    if (preScale >= 0.3 || forceSpatial) {
      buildNodesSpatial();
      return;
    }
    // Scale too small — fall through to legacy layout (unless sticky)
    if (!forceSpatial) {
      console.warn('[SPATIAL] Computed scale', preScale.toFixed(3), 'is below minimum 0.3 — falling back to legacy layout');
    }
  }
  if (!forceSpatial) {
    console.log('[SPATIAL] Falling back to legacy layout (kill switch or small scale)');
    spatialMode = false; // fallback to cosmetic layout
    spatialSectors = {};
    spatialAdjacencies = [];
    spatialSectorNodes = [];
  }
  let npcs = mapData.npcs || [];
  const npcLocations = mapData.npc_locations || [];
  // Merge npcs with npc_locations: add missing NPCs from locations, and add position data to existing NPCs
  if (npcLocations.length > 0) {
    const npcMap = new Map(npcs.map(n => [n.id, n]));
    for (const loc of npcLocations) {
      // Check direct match or faction_home_rep prefix match
      let matchedId = loc.npc_id;
      if (!npcMap.has(matchedId) && loc.npc_id.startsWith('faction_home_rep:')) {
        const baseId = loc.npc_id.replace('faction_home_rep:', '');
        if (npcMap.has(baseId)) matchedId = baseId;
      }
      if (!npcMap.has(matchedId)) {
        // Add new NPC from location
        npcMap.set(loc.npc_id, {
          id: loc.npc_id,
          name: loc.npc_id,
          affiliation: null,
          category: 'unknown',
          last_active: Date.now() / 1000 - 100
        });
      } else if (matchedId !== loc.npc_id) {
        // Add sector_id to existing faction NPC from its home rep location
        const existing = npcMap.get(matchedId);
        if (!existing.sector_id) existing.sector_id = loc.sector_id;
      }
    }
    npcs = Array.from(npcMap.values());
  }
        factions = mapData.factions || {};
  const now = Date.now() / 1000;
  const cx = W / 2;
  const cy = H / 2;
  const factionRadius = Math.min(W, H) * 0.35;
  const npcLocalRadius = 80;

  const factionGroups = {};
  FACTION_ORDER.forEach(f => factionGroups[f] = []);
  const rivalGroup = [], neutralGroup = [], enigmaGroup = [], companionGroup = [], unknownGroup = [];

  for (const npc of npcs) {
    const aff = npc.affiliation;
    if (aff && factionGroups[aff]) {
      factionGroups[aff].push(npc);
    } else if (npc.category === 'rival') { rivalGroup.push(npc); }
    else if (npc.category === 'neutral') { neutralGroup.push(npc); }
    else if (npc.category === 'enigma') { enigmaGroup.push(npc); }
    else if (npc.category === 'companion') { companionGroup.push(npc); }
    else { unknownGroup.push(npc); }
  }

  nodes = [];
  factionZones = [];

  FACTION_ORDER.forEach((fid, i) => {
    const angle = (i / FACTION_ORDER.length) * Math.PI * 2 - Math.PI / 2;
    const fcx = cx + Math.cos(angle) * factionRadius;
    const fcy = cy + Math.sin(angle) * factionRadius;
    const group = factionGroups[fid];
    const spread = Math.max(npcLocalRadius, group.length * 14);
    const fdata = factions[fid] || {};
    const color = fdata.color || '#333';

    // Place faction NPCs first, collect their positions for polygon
    const factionNodePositions = [{ x: fcx, y: fcy }]; // anchor = faction center
    const factionNodes = [];

    group.forEach((npc, j) => {
      const rng = seededRand(hashStr(npc.id || npc.name || (fid + j)));
      // Add per-NPC jitter to break collinearity (especially for 2-NPC factions where
      // NPCs would otherwise be placed at exactly 0° and 180°, making center+NPCs collinear)
      const angleJitter = seededRand(hashStr(fid + '_jitter_' + j))() * 0.4 - 0.2;
      const subAngle = (j / group.length) * Math.PI * 2 + angleJitter;
      const subR = spread * (0.3 + rng() * 0.7);
      const x = fcx + Math.cos(subAngle) * subR;
      const y = fcy + Math.sin(subAngle) * subR;
      const age = npc.last_active ? (now - npc.last_active) : 9999;
      const activity = Math.max(0.2, 1 - age / 3600);
      const radius = 8 + activity * 12;
      factionNodePositions.push({ x, y });

      const node = {
        id: npc.id, name: npc.name || npc.id, x, y, radius,
        color: npc.mood_color || '#9e9e9e',
        npc, category: npc.category || 'unknown', faction: fid,
        activity, age,
        factionColor: color
      };
      factionNodes.push(node);
      nodes.push(node);
    });

    // Build territory polygon from NPC positions
    let polygon = [];
    let labelX = fcx, labelY = fcy;
    let zoneR = Math.max(npcLocalRadius, group.length * 14) + 20; // fallback

    // For factions with fewer than 3 points, generate synthetic boundary points
    // around the anchor so they always get a real polygon, not a circle
    let polyPoints = factionNodePositions.slice();
    if (polyPoints.length < 3) {
      const infl = fdata.influence || 20;
      const baseR = Math.max(80, npcLocalRadius * (0.6 + (infl / 100) * 0.6));
      const numPts = Math.max(4, 6 + Math.floor(infl / 15));
      for (let pi = 0; pi < numPts; pi++) {
        const pa = (pi / numPts) * Math.PI * 2 + (i * 0.3); // offset per faction for irregularity
        const pr = baseR * (0.7 + seededRand(hashStr(fid + 'b' + pi))() * 0.6);
        polyPoints.push({ x: fcx + Math.cos(pa) * pr, y: fcy + Math.sin(pa) * pr });
      }
      // Recompute zoneR from generated points for fallback safety
      zoneR = baseR * 1.2;
    }

    if (polyPoints.length >= 3) {
      // 3+ points: convex hull → pad → smooth
      let hull = convexHull(polyPoints);
      // Fix: if hull returned < 3 points (colinear input), generate irregular polygon
      if (hull.length < 3) {
        hull = [];
        const infl = fdata.influence || 20;
        const baseR = Math.max(80, spread * (0.8 + (infl / 100) * 0.4));
        const numPts = Math.max(6, 8 + Math.floor(infl / 10));
        for (let pi = 0; pi < numPts; pi++) {
          const pa = (pi / numPts) * Math.PI * 2 + (i * 0.17 + pi * 0.03);
          const pr = baseR * (0.55 + seededRand(hashStr(fid + 'h' + pi))() * 0.6);
          hull.push({ x: fcx + Math.cos(pa) * pr, y: fcy + Math.sin(pa) * pr });
        }
      }
      // Fix flat triangles: when a hull has only 3 points with extreme aspect ratio
      // (all NPCs nearly collinear), outward normals at the vertices don't push
      // the edges far enough in the narrow axis. Augment with synthetic perimeter
      // points around the faction center to ensure all NPCs are enclosed.
      if (hull.length === 3) {
        const hB = polyBounds(hull);
        const hW = hB.maxX - hB.minX, hH = hB.maxY - hB.minY;
        const large = Math.max(hW, hH), small = Math.min(hW, hH);
        if (small > 0 && large / small > 4) {
          const infl = fdata.influence || 20;
          const baseR = Math.max(large * 0.6, spread * (0.8 + (infl / 100) * 0.4));
          const numPts = Math.max(6, 8 + Math.floor(infl / 10));
          for (let pi = 0; pi < numPts; pi++) {
            const pa = (pi / numPts) * Math.PI * 2 + (i * 0.17 + pi * 0.03);
            const pr = baseR * (0.55 + seededRand(hashStr(fid + 'h2_' + pi))() * 0.6);
            hull.push({ x: fcx + Math.cos(pa) * pr, y: fcy + Math.sin(pa) * pr });
          }
          hull = convexHull(hull);
        }
      }
      let padAmt = Math.max(30, 50 * (1 + ((fdata.influence||20) - 20) / 100));
      let padded = padPolygon(hull, padAmt);
      polygon = smoothPoly(padded, 2);
      const centroid = polyCentroid(polygon);
      const bounds = polyBounds(polygon);
      labelX = centroid.x;
      labelY = bounds.maxY + 16;
    }

    factionZones.push({
      fid, fcx, fcy, zoneR, color, fdata,
      groupSize: group.length,
      polygon,     // array of {x,y} if hull computed, [] if fallback
      labelX, labelY,
      zonePulse: Math.random() * Math.PI * 2,
      historicalInfluence: fdata.influence || 20,
      historicalCohesion: fdata.cohesion || 50
    });
  });

  // Rivals
  const rivalAngle = -Math.PI * 0.15;
  const rivalDist = factionRadius * 1.35;
  rivalGroup.forEach((npc, j) => {
    const spread = Math.max(30, rivalGroup.length * 10);
    const rng = seededRand(hashStr(npc.id || npc.name || ('rival' + j)));
    const a = rivalAngle + (j - rivalGroup.length/2) * 0.2;
    const r = rivalDist + (rng() - 0.5) * spread;
    nodes.push({
      id: npc.id, name: npc.name || npc.id,
      x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r,
      radius: 11, color: npc.mood_color || '#ef5350',
      npc, category: 'rival', faction: null,
      activity: 0.5, age: 999,
      factionColor: CATEGORY_COLORS.rival
    });
  });

  // Neutrals
  neutralGroup.forEach((npc, j) => {
    const rng = seededRand(hashStr(npc.id || npc.name || ('neutral' + j)));
    const a = rng() * Math.PI * 2;
    const r = factionRadius * (0.3 + rng() * 0.5);
    nodes.push({
      id: npc.id, name: npc.name || npc.id,
      x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r,
      radius: 6, color: npc.mood_color || '#78909c',
      npc, category: 'neutral', faction: null,
      activity: 0.3, age: 999,
      factionColor: CATEGORY_COLORS.neutral
    });
  });

  // Enigmas
  enigmaGroup.forEach((npc, j) => {
    const rng = seededRand(hashStr(npc.id || npc.name || ('enigma' + j)));
    const a = rng() * Math.PI * 2;
    const r = factionRadius * (0.8 + rng() * 0.5);
    nodes.push({
      id: npc.id, name: npc.name || npc.id,
      x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r,
      radius: 8, color: npc.mood_color || '#ab47bc',
      npc, category: 'enigma', faction: null,
      activity: 0.4, age: 999,
      factionColor: CATEGORY_COLORS.enigma
    });
  });

  // Companions
  companionGroup.forEach((npc, j) => {
    const rng = seededRand(hashStr(npc.id || npc.name || ('comp' + j)));
    const a = (j / Math.max(1, companionGroup.length)) * Math.PI * 2;
    const r = 40 + rng() * 60;
    nodes.push({
      id: npc.id, name: npc.name || npc.id,
      x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r,
      radius: 9, color: npc.mood_color || '#ffd700',
      npc, category: 'companion', faction: null,
      activity: 0.7, age: 999,
      factionColor: CATEGORY_COLORS.companion
    });
  });

  // Unknowns
  unknownGroup.forEach((npc, j) => {
    const rng = seededRand(hashStr(npc.id || npc.name || ('unk' + j)));
    const a = rng() * Math.PI * 2;
    const r = factionRadius * (0.15 + rng() * 0.4);
    nodes.push({
      id: npc.id, name: npc.name || npc.id,
      x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r,
      radius: 6, color: '#9e9e9e',
      npc, category: 'unknown', faction: null,
      activity: 0.2, age: 999,
      factionColor: CATEGORY_COLORS.unknown
    });
  });
}

// --- SPATIAL-03: Build nodes using real sector coordinates ---
function buildNodesSpatial() {
  if (!mapData || !mapData.sectors || mapData.sectors.length === 0) return;
  let npcs = mapData.npcs || [];
  const npcLocations = mapData.npc_locations || [];
  // Merge npcs with npc_locations: add missing NPCs from locations, match faction_home_rep prefix
  if (npcLocations.length > 0) {
    const npcMap = new Map(npcs.map(n => [n.id, n]));
    for (const loc of npcLocations) {
      let matchedId = loc.npc_id;
      if (!npcMap.has(matchedId) && loc.npc_id.startsWith('faction_home_rep:')) {
        const baseId = loc.npc_id.replace('faction_home_rep:', '');
        if (npcMap.has(baseId)) matchedId = baseId;
      }
      if (!npcMap.has(matchedId)) {
        npcMap.set(loc.npc_id, {
          id: loc.npc_id,
          name: loc.npc_id,
          affiliation: null,
          category: 'unknown',
          last_active: Date.now() / 1000 - 100
        });
      } else if (matchedId !== loc.npc_id) {
        const existing = npcMap.get(matchedId);
        if (!existing.sector_id) existing.sector_id = loc.sector_id;
      }
    }
    npcs = Array.from(npcMap.values());
  }
  const factions = mapData.factions || {};
  const territories = mapData.faction_territories || [];
  const sectors = mapData.sectors || [];
  const now = Date.now() / 1000;

  // Coordinate transform: map sector (x,y) to canvas pixels
  // SPATIAL-02.5: Use per-axis scaling so map fills ~65% of viewport, not a tiny clump
  const cx = W / 2;
  const cy = H / 2;
  // Find coordinate range
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const s of sectors) {
    if (s.x < minX) minX = s.x; if (s.x > maxX) maxX = s.x;
    if (s.y < minY) minY = s.y; if (s.y > maxY) maxY = s.y;
  }
  const rangeX = Math.max(1, maxX - minX);
  const rangeY = Math.max(1, maxY - minY);
  const midX = (minX + maxX) / 2;
  const midY = (minY + maxY) / 2;
  // Per-axis scale: fill SPATIAL_FILL_RATIO (65%) of viewport, use the smaller to preserve aspect ratio
  const scaleX = (W * SPATIAL_FILL_RATIO) / rangeX;
  const scaleY = (H * SPATIAL_FILL_RATIO) / rangeY;
  const sectorScale = Math.min(scaleX, scaleY);

  function sectorToCanvas(sx, sy) {
    return {
      x: cx + (sx - midX) * sectorScale,
      y: cy + (sy - midY) * sectorScale
    };
  }

  // Build initial sector canvas positions
  spatialSectors = {};
  for (const s of sectors) {
    const pos = sectorToCanvas(s.x, s.y);
    spatialSectors[s.id] = { cx: pos.x, cy: pos.y, data: s };
  }

  // SPATIAL-03A: Push faction home sectors outward for visual separation
  // Faction homes cluster near center because their raw coordinates are all inner/core.
  // Strategy: compute centroid of faction homes, then push each home away from that centroid
  // by a large expansion factor. Non-home sectors are repositioned relative to their nearest home.
  const homeSectorIds = {}; // factionId → homeSectorId
  for (const fid of FACTION_ORDER) {
    const fdata = factions[fid];
    if (fdata && fdata.home_sector_id) homeSectorIds[fid] = fdata.home_sector_id;
  }
  const homeIds = Object.values(homeSectorIds);

  // Build territory lookup: sectorId → factionId (used by home expansion and NPC placement)
  const sectorOwner = {};
  for (const t of territories) { sectorOwner[t.sector_id] = t.faction_id; }

  if (homeIds.length >= 2) {
    // Centroid of faction homes
    let hcx = 0, hcy = 0;
    for (const hid of homeIds) {
      const sp = spatialSectors[hid];
      if (sp) { hcx += sp.cx; hcy += sp.cy; }
    }
    hcx /= homeIds.length;
    hcy /= homeIds.length;

    // Push each faction home outward from the centroid
    const FACTION_HOME_EXPANSION = 2.8; // how much to multiply distance from centroid
    const maxR = Math.min(W, H) * 0.42; // cap: don't push off screen
    for (const [fid, hid] of Object.entries(homeSectorIds)) {
      const sp = spatialSectors[hid];
      if (!sp) continue;
      const dx = sp.cx - hcx;
      const dy = sp.cy - hcy;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const newDist = Math.min(dist * FACTION_HOME_EXPANSION, maxR);
      const scale = newDist / dist;
      sp.cx = hcx + dx * scale;
      sp.cy = hcy + dy * scale;
    }

    // Reposition non-home sectors: keep their offset from their owning faction's home,
    // but scale it down to create tight clusters around each home
    for (const s of sectors) {
      if (homeIds.includes(s.id)) continue; // already repositioned
      const sp = spatialSectors[s.id];
      if (!sp) continue;
      const ownerFid = sectorOwner[s.id];
      // Find nearest faction home to anchor this sector
      let anchorId = null, anchorDist = Infinity;
      for (const hid of homeIds) {
        const hp = spatialSectors[hid];
        if (!hp) continue;
        // Use ORIGINAL positions to determine nearest home (before expansion)
        const origPos = sectorToCanvas(s.x, s.y);
        const origHome = sectorToCanvas(spatialSectors[hid].data.x, spatialSectors[hid].data.y);
        const d = Math.sqrt((origPos.x - origHome.x) ** 2 + (origPos.y - origHome.y) ** 2);
        if (d < anchorDist) { anchorDist = d; anchorId = hid; }
      }
      if (anchorId && spatialSectors[anchorId]) {
        const anchor = spatialSectors[anchorId];
        // Original offset from the anchor home (before expansion)
        const origAnchor = sectorToCanvas(spatialSectors[anchorId].data.x, spatialSectors[anchorId].data.y);
        const origSelf = sectorToCanvas(s.x, s.y);
        const offX = origSelf.x - origAnchor.x;
        const offY = origSelf.y - origAnchor.y;
        // Place sector at: new anchor position + scaled offset (0.5x = tighter cluster)
        const CLUSTER_TIGHTNESS = 0.45;
        sp.cx = anchor.cx + offX * CLUSTER_TIGHTNESS;
        sp.cy = anchor.cy + offY * CLUSTER_TIGHTNESS;
      }
      // Sol-prime (unowned core): leave at its sectorToCanvas position, it stays central
    }
  }

  // Build adjacencies (deduplicated — only draw A→B once)
  spatialAdjacencies = [];
  const adjSeen = new Set();
  for (const s of sectors) {
    const adjIds = s.adjacent_sector_ids || [];
    for (const adjId of adjIds) {
      const key = [s.id, adjId].sort().join('|');
      if (adjSeen.has(key)) continue;
      adjSeen.add(key);
      const from = spatialSectors[s.id];
      const to = spatialSectors[adjId];
      if (from && to) {
        spatialAdjacencies.push({
          from: s.id, to: adjId,
          fromX: from.cx, fromY: from.cy,
          toX: to.cx, toY: to.cy
        });
      }
    }
  }

  // sectorOwner already declared above (faction home expansion block)

  // Build NPC location lookup: npc_id → sectorId
  const npcSector = {};
  for (const nl of npcLocations) {
    npcSector[nl.npc_id] = nl.sector_id;
  }

  nodes = [];
  factionZones = [];
  spatialSectorNodes = [];

  // Place sector markers (clickable/hoverable)
  for (const s of sectors) {
    const pos = spatialSectors[s.id];
    const ownerFid = sectorOwner[s.id];
    const ownerColor = ownerFid && factions[ownerFid] ? factions[ownerFid].color : null;
    const regionColor = REGION_COLORS[s.region_type] || '#78909c';
    spatialSectorNodes.push({
      id: 'sector:' + s.id,
      name: s.name || s.id,
      x: pos.cx, y: pos.cy,
      radius: s.region_type === 'core' ? 14 : (s.region_type === 'inner' ? 10 : 8),
      color: ownerColor || regionColor,
      sectorData: s,
      ownerFaction: ownerFid || null,
      regionType: s.region_type
    });
  }

  // Group NPCs by their sector (use npc_sector_id from API, then npcSector lookup, then affiliation→home_sector)
  const npcsBySector = {};
  for (const npc of npcs) {
    let secId = npc.sector_id || npcSector[npc.id] || null;
    // Fallback: if NPC is faction-affiliated and has no sector, place at faction home
    if (!secId && npc.affiliation) {
      const fac = factions[npc.affiliation];
      if (fac && fac.home_sector_id) secId = fac.home_sector_id;
    }
// Last resort: place at sol-prime
      if (!secId) secId = 'sol-prime';
    if (!npcsBySector[secId]) npcsBySector[secId] = [];
    npcsBySector[secId].push(npc);
  }

// Place NPCs inside their faction's Voronoi territory with orbit-ring packing
  // SPATIAL-04: Anchor NPCs to their AFFILIATION's Voronoi centroid, not sector position.
  // This keeps affiliated NPCs inside their faction's colored polygon.
  // Unaffiliated NPCs stay at their sector position (correct — they roam freely).
  const factionCentroidCache = {}; // factionId → {cx, cy}
  function getFactionCentroid(fid) {
    if (factionCentroidCache[fid]) return factionCentroidCache[fid];
    const cell = voronoiCells.find(c => c.factionId === fid);
    if (cell && cell.centroid) {
      factionCentroidCache[fid] = cell.centroid;
      return cell.centroid;
    }
    factionCentroidCache[fid] = null;
    return null;
  }

  for (const secId in npcsBySector) {
    const sectorNpcs = npcsBySector[secId];
    const count = sectorNpcs.length;
    const secPos = spatialSectors[secId];
    const baseRadius = 25;
    const ringSpacing = 20;
    sectorNpcs.forEach((npc, j) => {
      const rng = seededRand(hashStr(npc.id || npc.name || (secId + j)));
      // SPATIAL-04: Use affiliation's Voronoi centroid if available, else sector position
      const aff = npc.affiliation;
      const affCentroid = aff ? getFactionCentroid(aff) : null;
      const center = affCentroid || secPos;
      if (!center) return;
      // Small jitter so NPCs from same sector don't stack perfectly
      const jitterX = (rng() - 0.5) * 8;
      const jitterY = (rng() - 0.5) * 8;
      // Determine ring and angle
      let ring, slotInRing, slotsInRing;
      if (j < 4) { ring = 0; slotInRing = j; slotsInRing = Math.min(4, count); }
      else if (j < 10) { ring = 1; slotInRing = j - 4; slotsInRing = Math.min(6, count - 4); }
      else { ring = 2; slotInRing = j - 10; slotsInRing = Math.min(8, count - 10); }
      const ringR = baseRadius + ring * ringSpacing;
      const angleStep = (Math.PI * 2) / Math.max(1, slotsInRing);
      const subAngle = slotInRing * angleStep + rng() * angleStep * 0.4;
      const x = center.cx + jitterX + Math.cos(subAngle) * (ringR + rng() * 6);
      const y = center.cy + jitterY + Math.sin(subAngle) * (ringR + rng() * 6);
      const age = npc.last_active ? (now - npc.last_active) : 9999;
      const activity = Math.max(0.2, 1 - age / 3600);
      // SPATIAL-03C: Smaller NPC dots — was 3+activity*5, now 2+activity*3
      const radius = 2 + activity * 3;
      const fColor = aff && factions[aff] ? factions[aff].color : '#9e9e9e';
      nodes.push({
        id: npc.id, name: npc.name || npc.id, x, y, radius,
        color: npc.mood_color || '#9e9e9e',
        npc, category: npc.category || 'unknown',
        faction: aff || null,
        activity, age,
        factionColor: fColor,
        sectorId: secId
      });
    });
  }

  // SPATIAL-03B: Build faction territories using Voronoi partition
  // Instead of tiny convex hulls around sector points, divide the entire canvas
  // into large non-overlapping territory regions using Voronoi cells seeded by
  // faction home positions. This guarantees full canvas coverage and produces
  // the large colored territory regions the operator requires.
  const factionHomeSectors = {};
  for (const t of territories) {
    if (!factionHomeSectors[t.faction_id]) factionHomeSectors[t.faction_id] = [];
    factionHomeSectors[t.faction_id].push(t.sector_id);
  }

  // Build Voronoi seeds from faction home positions
  const voronoiSeeds = [];
  for (const fid of FACTION_ORDER) {
    const fdata = factions[fid] || {};
    const ownedSectors = factionHomeSectors[fid] || [];
    const homeSecId = fdata.home_sector_id || (ownedSectors.length > 0 ? ownedSectors[0] : 'sol-prime');
    const homePos = spatialSectors[homeSecId];
    if (!homePos) continue;
    voronoiSeeds.push({ x: homePos.cx, y: homePos.cy, factionId: fid });
  }
  // Add sol-prime as neutral seed at center (prevents gap in the middle)
  const solPos = spatialSectors['sol-prime'];
  if (solPos) {
    voronoiSeeds.push({ x: solPos.cx, y: solPos.cy, factionId: '_neutral' });
  }

  // Compute Voronoi cells — each faction gets a large territory region
  voronoiCells = computeVoronoiCells(voronoiSeeds, { minX: 0, minY: 0, maxX: W, maxY: H });

// Apply organic deformation to Voronoi cells
// SPATIAL-03C: Stronger deformation for nebula/organic feel instead of flat polygons
for (const cell of voronoiCells) {
if (cell.polygon.length >= 3) {
// Per-vertex jitter for organic edges
const fid = cell.factionId;
const fdata = factions[fid] || {};
const infl = (fdata.influence || 20) / 100;
const coh = (fdata.cohesion || 50) / 100;
const jitterAmp = 8 + (1 - coh) * 16; // SPATIAL-03C: was 3+(1-coh)*8, much more organic
const n = cell.polygon.length;
for (let i = 0; i < n; i++) {
const rng = seededRand(hashStr(fid + '_vcel_' + i));
cell.polygon[i].x += (rng() - 0.5) * jitterAmp * 2;
cell.polygon[i].y += (rng() - 0.5) * jitterAmp * 2;
}
// SPATIAL-03C: Two passes of smoothing for more natural curves
cell.polygon = smoothPoly(cell.polygon, 2);
// Recompute centroid after deformation
cell.centroid = polyCentroid(cell.polygon);
    }
  }

  // Build factionZones from Voronoi cells for compatibility with existing draw/click code
  for (const fid of FACTION_ORDER) {
    const fdata = factions[fid] || {};
    const color = fdata.color || '#333';
    const ownedSectors = factionHomeSectors[fid] || [];
    const homeSecId = fdata.home_sector_id || (ownedSectors.length > 0 ? ownedSectors[0] : 'sol-prime');
    const homePos = spatialSectors[homeSecId];
    if (!homePos) continue;
    const fcx = homePos.cx;
    const fcy = homePos.cy;

    // Find the Voronoi cell for this faction
    const cell = voronoiCells.find(c => c.factionId === fid);
    const polygon = cell && cell.polygon.length >= 3 ? cell.polygon : [];
    const labelX = cell ? cell.centroid.x : fcx;
    const labelY = cell ? cell.centroid.y : fcy;

    // Count NPCs in owned sectors
    let groupSize = 0;
    for (const secId of ownedSectors) {
      groupSize += (npcsBySector[secId] || []).length;
    }

    // zoneR no longer determines territory size — Voronoi cell does
    // Keep a minimal zoneR for circle fallback (shouldn't be used, but safety)
    const zoneR = 60;

    factionZones.push({
      fid, fcx, fcy, zoneR, color, fdata,
      groupSize,
      polygon,
      labelX, labelY,
      zonePulse: Math.random() * Math.PI * 2,
      historicalInfluence: fdata.influence || 20,
      historicalCohesion: fdata.cohesion || 50,
      ownedSectors,
      voronoiCell: cell || null // SPATIAL-03B: reference to Voronoi cell
    });
  }

  spatialMode = true;
  _spatialModeEverActivated = true; // sticky: once spatial mode works, stay in spatial mode
  try { localStorage.setItem('fed_smap_spatial', 'true'); } catch(e) {}

  // Store spatial bounds for FIT button and future reference
  spatialBounds = { midX, midY, sectorScale, rangeX, rangeY, minX, maxX, minY, maxY };
}

// --- Update UI panels ---
/* ═══ Fed UI Phenotype State (compact-restore pattern) ═══ */
const FED_SMAP_SCHEMA = '1.0.0';
const FED_SMAP_AUTH_FIELDS = ['event_buckets','crisis_collapsed'];
const FED_SMAP_MAX_AGE = 300000;

function _smapHash(s){var h=0;for(var i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h=h&h}return 'h'+Math.abs(h).toString(36)}

function fedStarmapSaveUI(changes) {
  try {
    var existing = fedStarmapLoadRaw();
    var state = {event_buckets:{exploration:true,defensive:true,covert:true,anomalies:false,other:false},crisis_collapsed:false};
    if(existing&&existing.payload){
      for(var k in existing.payload){
        if(k==='event_buckets'&&existing.payload[k]){state.event_buckets=JSON.parse(JSON.stringify(existing.payload[k]))}
        else{state[k]=existing.payload[k]}
      }
    }
    if(changes){for(var k in changes)state[k]=changes[k]}
    var packet={schema:FED_SMAP_SCHEMA,timestamp:Date.now(),source:'federation-starmap',
      authority:{fields_authoritative:FED_SMAP_AUTH_FIELDS,fields_advisory:[]},
      payload:state,hash:''};
    packet.hash=_smapHash(packet.schema+'|'+packet.timestamp+'|'+packet.source+'|'+JSON.stringify(packet.payload)+'|'+JSON.stringify(packet.authority));
    localStorage.setItem('fed_starmap_phenotype',JSON.stringify(packet));
    return true;
  }catch(e){return false}
}

function fedStarmapLoadRaw() {
  try{
    var raw=localStorage.getItem('fed_starmap_phenotype');if(!raw)return null;
    var p=JSON.parse(raw);if(!p.schema||!p.timestamp)return null;
    var ch=p.hash;p.hash='';
    var cmp=_smapHash(p.schema+'|'+p.timestamp+'|'+p.source+'|'+JSON.stringify(p.payload)+'|'+JSON.stringify(p.authority));
    if(ch!==cmp)return null;
    p.hash=ch;p._stale=(Date.now()-p.timestamp)>FED_SMAP_MAX_AGE;
    return p;
  }catch(e){return null}
}

function fedStarmapRestoreUI(){var p=fedStarmapLoadRaw();return p?p.payload:null}
/* ═══ End Phenotype State ═══ */

/* ═══ STARMAP QUICK STATUS ═══ */
function renderStarmapQuickStatus() {
  if (!mapData) return;
  var ws = mapData.world_state || {};
  var panel = document.getElementById('starmap-qs');
  var body = document.getElementById('sqs-body');
  var tickEl = document.getElementById('sqs-tick');
  if (!panel || !body) return;

  var morale = ws.morale != null ? ws.morale : 50;
  var stability = ws.stability != null ? ws.stability : 50;
  var resources = ws.resource_abundance != null ? ws.resource_abundance : 60;
  var threat = ws.threat_level != null ? ws.threat_level : 30;
  var tension = ws.tension_level != null ? ws.tension_level : 50;
  var anomaly = ws.anomaly_activity != null ? ws.anomaly_activity : 20;
  var worker = mapData.worker || {};
  var tickCount = worker.tick_count || 0;
  tickEl.textContent = 'Tick ' + tickCount;

  panel.style.display = 'block';
  var html = '';

  /* Vitals */
  var goodParts = [], badParts = [];
  if (morale >= 75) goodParts.push('Morale (' + Math.round(morale) + ') strong');
  else if (morale < 35) badParts.push('Morale collapsing (' + Math.round(morale) + ')');
  if (stability >= 70) goodParts.push('Stability (' + Math.round(stability) + ') solid');
  else if (stability < 40) badParts.push('Stability UNSTABLE (' + Math.round(stability) + ')');
  if (resources >= 70) goodParts.push('Resources (' + Math.round(resources) + ') abundant');
  else if (resources < 30) badParts.push('Resources scarce (' + Math.round(resources) + ')');
  if (threat <= 30) goodParts.push('Threat (' + Math.round(threat) + ') low');
  else if (threat > 70) badParts.push('Threat CRITICAL (' + Math.round(threat) + ')');
  if (tension <= 30) goodParts.push('Tension (' + Math.round(tension) + ') low');
  else if (tension > 70) badParts.push('Tension SEVERE (' + Math.round(tension) + ')');
  if (anomaly > 70) badParts.push('Anomaly elevated (' + Math.round(anomaly) + ')');

  if (goodParts.length > 0) {
    html += '<div class="sqs-section"><div class="sqs-section-title">&#x2713; The Good</div><div class="sqs-row sqs-good">' + goodParts.join('. ') + '.</div></div>';
  }
  if (badParts.length > 0) {
    html += '<div class="sqs-section"><div class="sqs-section-title">&#x26A0; The Bad</div><div class="sqs-row sqs-bad">' + badParts.join('. ') + '.</div></div>';
  }

  /* Under the Surface — from events */
  var events = mapData.events || [];
  var blackMarketNpcs = [], covertNpcs = [], disinfoNpcs = [];
  for (var si = 0; si < events.length; si++) {
    var ev = events[si];
    var desc = (ev.description || ev.name || '').toLowerCase();
    var src = ev.char_name || ev.source || '';
    if (desc.indexOf('black market') !== -1 || desc.indexOf('illicit') !== -1 || desc.indexOf('smuggl') !== -1) {
      if (src && blackMarketNpcs.indexOf(src) === -1) blackMarketNpcs.push(src);
    }
    if (desc.indexOf('covert') !== -1 || desc.indexOf('secret') !== -1 || desc.indexOf('vanish') !== -1) {
      if (src && covertNpcs.indexOf(src) === -1) covertNpcs.push(src);
    }
    if (desc.indexOf('disinformation') !== -1 || desc.indexOf('planted') !== -1) {
      if (src && disinfoNpcs.indexOf(src) === -1) disinfoNpcs.push(src);
    }
  }

  var surfaceItems = [];
  if (blackMarketNpcs.length > 0) surfaceItems.push('Black Markets: ' + blackMarketNpcs.join(', '));
  if (covertNpcs.length > 0) surfaceItems.push('Covert Ops: ' + covertNpcs.join(', '));
  if (disinfoNpcs.length > 0) surfaceItems.push('Disinformation: ' + disinfoNpcs.join(', '));
  if (surfaceItems.length > 0) {
    html += '<div class="sqs-section"><div class="sqs-section-title">&#x1F575; Under the Surface</div><div class="sqs-row sqs-dim">' + surfaceItems.join(' | ') + '</div></div>';
  }

  /* Major Catalysts */
  var catalysts = [];
  var cascadeEvents = events.filter(function(e){ return e.cascade || (e.event_type && e.event_type.toLowerCase() === 'cascade_reaction'); });
  if (cascadeEvents.length >= 3) {
    var catLabel = cascadeEvents[0].origin_event_type || 'Unknown';
    catLabel = catLabel.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase();});
    catalysts.push('<div class="sqs-cat"><span class="sqs-cat-label">&#x1F300; Cascade:</span> ' + cascadeEvents.length + ' reactions from ' + catLabel + '</div>');
  }
  if (anomaly > 70) {
    catalysts.push('<div class="sqs-cat"><span class="sqs-cat-label">&#x2728; Anomaly:</span> Activity at ' + Math.round(anomaly) + '<span class="sqs-badge bad">ELEVATED</span></div>');
  }
  if (stability < 40) {
    catalysts.push('<div class="sqs-cat"><span class="sqs-cat-label">&#x26A0; Stability:</span> At ' + Math.round(stability) + ' — factions may fragment<span class="sqs-badge bad">CRITICAL</span></div>');
  }

  if (catalysts.length > 0) {
    html += '<div class="sqs-section"><div class="sqs-section-title">&#x26A1; Catalysts</div>' + catalysts.join('') + '</div>';
  }

  body.innerHTML = html || '<div style="color:#78909c;font-size:0.875rem">No significant activity</div>';
  buildGalacticBulletin();
}

// Update radial gauges — inject current world-state values into the live SVG markup.
function updateRadialGauges() {
  if (!mapData) return;
  const ws = mapData.world_state || {};
  const gauges = {
    tension: { key: 'tension_level', color: '#ef5350' },
    stability: { key: 'stability', color: '#66bb6a' },
    morale: { key: 'morale', color: '#ffd700' },
    threat: { key: 'threat_level', color: '#f44336' },
    anomaly: { key: 'anomaly_activity', color: '#ab47bc' }
  };

  for (const [id, cfg] of Object.entries(gauges)) {
    const gaugeEl = document.getElementById(`gauge-${id}`);
    const valueEl = document.getElementById(`wv-${id}`);
    if (!gaugeEl || !valueEl) continue;
    const val = Math.max(0, Math.min(100, Number(ws[cfg.key] || 0)));
    valueEl.textContent = Math.round(val);
    valueEl.style.color = val >= 70 ? '#ef5350' : (val >= 50 ? '#ffd700' : '#66bb6a');
    gaugeEl.style.stroke = cfg.color;
    gaugeEl.style.strokeDashoffset = String(125.6 - (val * 1.256));
  }
}

function buildGalacticBulletin() {
  const feed = document.getElementById('bulletin-feed');
  if (!feed) return;
  feed.classList.add('narrative-feed');

  const allEvents = ((mapData && mapData.events) || []).slice(0, 12);
  const events = allEvents.filter(isSignificantEvent);
  const renderEvents = events.length > 0 ? events : allEvents.slice(0, 8);

  if (renderEvents.length === 0) {
    feed.innerHTML = '<div style="color:#78909c;font-size:0.9375rem;padding:12px">No active transmissions.</div>';
    return;
  }

  feed.innerHTML = renderEvents.map((ev, idx) => {
    const title = ev.name || ev.action_type || ev.event_type || 'Transmission';
    const description = ev.description || 'No narrative detail available yet.';
    const speaker = ev.char_name || ev.source || 'Federation Network';
    const severity = (ev.severity || '').toUpperCase();
    const actionType = (ev.action_type || ev.event_type || '').toLowerCase();
    const descLower = description.toLowerCase();

    let badgeClass = 'cosmic-info';
    let badgeLabel = title;
    if (/anomaly|void|dream|cosmic/.test(actionType) || /anomaly|void|dream|cosmic/.test(descLower)) {
      badgeClass = 'cosmic-anomaly';
      badgeLabel = 'Anomaly';
    } else if (severity === 'CRITICAL' || severity === 'MAJOR' || /crisis|collapse|breach|attack|severe/.test(descLower)) {
      badgeClass = 'cosmic-major';
      badgeLabel = severity || 'Major';
    } else if (severity === 'MINOR' || /routine|minor|idle/.test(descLower)) {
      badgeClass = 'cosmic-dim';
      badgeLabel = severity || 'Routine';
    }

    const shortTitle = badgeLabel.length > 22 ? badgeLabel.slice(0, 22) + '…' : badgeLabel;
    const astroAlert = badgeClass === 'cosmic-anomaly'
      ? '<div class="astro-alert"><span>✦</span><span>Unusual anomaly signature detected</span></div>'
      : '';

    return `<article class="event-card" data-event-index="${idx}">
      <div class="event-header">
        <span class="event-stamp">${speaker}</span>
        <span class="event-badge ${badgeClass}">${shortTitle}</span>
      </div>
      <div class="event-body">
        <p class="cosmic-text">${description}</p>
        ${astroAlert}
      </div>
    </article>`;
  }).join('');
}

function updateUI() {
  if (!mapData) return;
  const worker = mapData.worker || {};
  const tickCount = worker.tick_count || 0;
  const status = worker.status || 'unknown';
  const tickDot = document.getElementById('tick-dot');
  const tickLabel = document.getElementById('tick-label');

  updateRadialGauges();

  if (tickDot) tickDot.className = status === 'running' ? '' : 'stopped';
  if (tickLabel) tickLabel.textContent = `TICK ${tickCount} · ${status.toUpperCase()}`;

  buildLegend();
  buildMapRead();
  renderStarmapQuickStatus();
}

function buildLegend() {
  const factions = mapData.factions || {};
  const ml = document.getElementById('map-legend');
  if (!ml) return;

  let html = '<h3>Map Legend</h3>';

  html += '<div class="ml-section"><div class="ml-section-title">Factions</div>';
  for (const fid of FACTION_ORDER) {
    const fdata = factions[fid];
    if (!fdata) continue;
    html += `<div class="ml-row"><div class="ml-dot" style="background:${fdata.color}"></div><span class="ml-name">${fdata.display_name || fid}</span></div>`;
  }
  html += '</div>';

  html += '<div class="ml-section"><div class="ml-section-title">Zone Types</div>';
  html += '<div class="ml-row"><div class="ml-zone" style="background:rgba(79,195,247,0.15);border-color:rgba(79,195,247,0.5)"></div><span class="ml-name">Faction influence area</span></div>';
  html += '<div class="ml-row"><div class="ml-zone" style="background:rgba(120,144,156,0.08);border-color:rgba(120,144,156,0.3)"></div><span class="ml-name">Neutral / unclaimed</span></div>';
  html += '<div class="ml-row"><div class="ml-zone" style="background:rgba(255,152,0,0.12);border-color:rgba(255,152,0,0.4)"></div><span class="ml-name">Contested / overlap</span></div>';
  html += '</div>';

  html += '<div class="ml-section"><div class="ml-section-title">Relationship Lines</div>';
  html += '<div class="ml-row"><div class="ml-line" style="background:#66bb6a"></div><span class="ml-name">Support / alliance</span></div>';
  html += '<div class="ml-row"><div class="ml-line" style="background:#ef5350"></div><span class="ml-name">Conflict / hostility</span></div>';
  html += '</div>';

  html += '<div class="ml-section"><div class="ml-section-title">NPC Dot Borders</div>';
  html += '<div class="ml-row"><div class="ml-dot" style="background:#9e9e9e;border:2px solid #4fc3f7"></div><span class="ml-name">Faction member (border = faction color)</span></div>';
  html += '<div class="ml-row"><div class="ml-dot" style="background:#9e9e9e;border:2px solid #546e7a"></div><span class="ml-name">Unaffiliated (grey border)</span></div>';
  html += '</div>';

  if (spatialMode) {
    html += '<div class="ml-section"><div class="ml-section-title">Sector Regions</div>';
    html += '<div class="ml-row"><div class="ml-dot" style="background:#4fc3f7"></div><span class="ml-name">Core sector</span></div>';
    html += '<div class="ml-row"><div class="ml-dot" style="background:#66bb6a"></div><span class="ml-name">Inner sector</span></div>';
    html += '<div class="ml-row"><div class="ml-dot" style="background:#ffa726"></div><span class="ml-name">Outer sector</span></div>';
    html += '<div class="ml-row"><div class="ml-dot" style="background:#ef5350"></div><span class="ml-name">Frontier sector</span></div>';
    html += '</div>';
    html += '<div class="ml-section"><div class="ml-section-title">Spatial Lines</div>';
    html += '<div class="ml-row"><div class="ml-line" style="background:rgba(79,195,247,0.25)"></div><span class="ml-name">Sector adjacency</span></div>';
    html += '</div>';
  }

  ml.innerHTML = html;
}

// --- Crisis Readout: case-file panel ---
let crisisReadoutCollapsed = false;
(function() {
  var ps = fedStarmapRestoreUI();
  if (ps && ps.crisis_collapsed) crisisReadoutCollapsed = true;
})();
let crisisHighlightIds = [];

function buildMapRead() {
  if (!mapData) return;
  const cr = mapData.crisis_readout;
  const ws = mapData.world_state || {};
  const factions = mapData.factions || {};
  const title = document.getElementById('mr-title');
  const body = document.getElementById('mr-body');
  if (!body) return;

  if (title) {
    title.textContent = currentView === 'network'
      ? 'Network Readout'
      : (currentView === 'territory' ? 'Territory Readout' : 'Crisis Readout');
  }

  if (!cr || !cr.classification) {
    const threat = ws.threat_level || 0;
    const morale = ws.morale || 50;
    const anomaly = ws.anomaly_activity || 0;
    const tension = ws.tension_level || 0;
    const stability = ws.stability || 50;
    const crisisScore = threat * 1.2 + (100 - morale) * 0.8 + anomaly * 0.9 + tension * 0.7 + (100 - stability) * 0.5;
    let crisisText = 'STABLE';
    let crisisClass = 'ok';
    if (crisisScore > 180) {
      crisisText = 'CRITICAL';
      crisisClass = '';
    } else if (crisisScore > 120) {
      crisisText = 'SEVERE';
      crisisClass = '';
    } else if (crisisScore > 70) {
      crisisText = 'ELEVATED';
      crisisClass = 'warn';
    } else if (crisisScore > 30) {
      crisisText = 'MODERATE';
      crisisClass = 'warn';
    }
    body.innerHTML = `<div id="mr-crisis" class="${crisisClass}">${crisisText}</div><div id="mr-line">Loading crisis data&hellip;</div>`;
    return;
  }

  const clsColors = {
    STABLE: '#66bb6a',
    MODERATE: '#ffa726',
    ELEVATED: '#ff7043',
    SEVERE: '#ef5350',
    CRITICAL: '#f44336'
  };
  const clsColor = clsColors[cr.classification] || '#4fc3f7';
  let html = '';

  html += `<div id="mr-crisis" style="color:${clsColor}">${cr.classification}</div>`;
  if (cr.headline) html += `<div id="mr-headline">${cr.headline}</div>`;
  if (cr.why_it_matters) html += `<div id="mr-why">${cr.why_it_matters}</div>`;

  const involvedNpcs = cr.involved_npcs || [];
  if (involvedNpcs.length > 0) {
    html += '<div id="mr-section"><div id="mr-section-title">Involved</div>';
    for (const npc of involvedNpcs.slice(0, 8)) {
      const facLabel = npc.faction ? (FACTION_DISPLAY[npc.faction] || npc.faction) : '';
      const facColor = factions[npc.faction]?.color || '#78909c';
      html += '<div id="mr-npc-row">';
      html += `<span id="mr-npc-name" onclick="crisisSelectNpc('${npc.id}')" title="Click to highlight on map">${npc.name}</span>`;
      if (facLabel) html += `<span style="color:${facColor};font-size:0.875rem">&middot; ${facLabel}</span>`;
      if (npc.role) html += `<span id="mr-npc-role">${npc.role}</span>`;
      html += '</div>';
    }
    html += '</div>';
  }

  const escalating = cr.escalating_factions || [];
  const helping = cr.helping_factions || [];
  const involvedFacs = cr.involved_factions || [];
  if (escalating.length > 0 || helping.length > 0 || involvedFacs.length > 0) {
    html += '<div id="mr-section"><div id="mr-section-title">Factions</div>';
    for (const fname of escalating) {
      const fid = Object.keys(FACTION_DISPLAY).find(k => FACTION_DISPLAY[k] === fname) || fname;
      const fColor = factions[fid]?.color || '#ef5350';
      html += `<div id="mr-fac-row"><span id="mr-fac-name" style="color:${fColor}">${fname}</span><span id="mr-fac-tag" class="escalating">Escalating</span></div>`;
    }
    for (const fname of helping) {
      const fid = Object.keys(FACTION_DISPLAY).find(k => FACTION_DISPLAY[k] === fname) || fname;
      const fColor = factions[fid]?.color || '#66bb6a';
      html += `<div id="mr-fac-row"><span id="mr-fac-name" style="color:${fColor}">${fname}</span><span id="mr-fac-tag" class="helping">Helping</span></div>`;
    }
    for (const fac of involvedFacs) {
      const fname = fac.name || fac;
      if (escalating.includes(fname) || helping.includes(fname)) continue;
      const fid = Object.keys(FACTION_DISPLAY).find(k => FACTION_DISPLAY[k] === fname) || fname;
      const fColor = factions[fid]?.color || '#4fc3f7';
      const tag = fac.role || 'Involved';
      html += `<div id="mr-fac-row"><span id="mr-fac-name" style="color:${fColor}">${fname}</span><span id="mr-fac-tag" class="involved">${tag}</span></div>`;
    }
    html += '</div>';
  }

  const cascadeChain = cr.cascade_chain || [];
  if (cascadeChain.length > 0) {
    html += '<div id="mr-section"><div id="mr-section-title">Cascade Chain</div>';
    for (const link of cascadeChain) {
      const reactors = (link.reactors || []).map(r => r.name).join(', ');
      html += `<div id="mr-cascade-row"><span id="mr-cascade-target">${link.target}</span> &larr; ${link.reaction_count} reactions`;
      if (reactors) html += `<div id="mr-cascade-reactors">&nbsp;&nbsp;Reactors: ${reactors}</div>`;
      html += '</div>';
    }
    html += '</div>';
  }

  const gameEvents = cr.recent_game_events || [];
  if (gameEvents.length > 0) {
    html += '<div id="mr-section"><div id="mr-section-title">Latest Events</div>';
    for (const ev of gameEvents.slice(0, 3)) {
      const sev = ev.severity || 'MAJOR';
      html += `<div id="mr-event-row"><span id="mr-event-name">${ev.name || 'Unknown event'}</span>`;
      html += `<span id="mr-event-sev" class="${sev}">${sev}</span>`;
      if (ev.description) html += `<div style="color:#78909c;font-size:0.875rem;margin-top:2px">${ev.description.substring(0, 150)}</div>`;
      html += '</div>';
    }
    html += '</div>';
  }

  if (cr.plain_english) html += `<div id="mr-plain">${cr.plain_english}</div>`;

  const actions = cr.actions || [];
  if (actions.length > 0) {
    html += '<div id="mr-actions">';
    if (involvedNpcs.length > 0) html += '<button id="mr-action-btn" onclick="crisisHighlightNpcs()">&#x1F50D; Highlight NPCs</button>';
    if (cascadeChain.length > 0) html += '<button id="mr-action-btn" onclick="crisisShowCrisisView()">&#x1F517; Crisis View</button>';
    if (escalating.length > 0 || involvedFacs.length > 0) html += '<button id="mr-action-btn" onclick="crisisShowTerritories()">&#x1F5FA; Territories</button>';
    html += '<button id="mr-action-btn" onclick="crisisOpenLiveSim()">&#x1F9EC; Live Sim</button>';
    html += '</div>';
  }

  html += `<div id="mr-collapse" onclick="toggleCrisisReadout()">${crisisReadoutCollapsed ? '&#x25BC; Expand' : '&#x25B2; Collapse'}</div>`;
  body.innerHTML = html;

  const panel = document.getElementById('map-read');
  if (panel) panel.style.maxHeight = crisisReadoutCollapsed ? '80px' : 'calc(100vh - 160px)';
}

// --- Crisis Readout interactive actions ---

function crisisSelectNpc(npcId) {
  const node = nodes.find(n => n.id === npcId);
  if (node) {
    selectedNode = node;
    showDetail(node);
    panX = W / 2 - node.x * zoom;
    panY = H / 2 - node.y * zoom;
  }
}

function crisisHighlightNpcs() {
  const cr = mapData && mapData.crisis_readout;
  if (!cr) return;
  const ids = (cr.involved_npcs || []).map(n => n.id);
  if (crisisHighlightIds.length > 0 && JSON.stringify(crisisHighlightIds) === JSON.stringify(ids)) {
    // Toggle off
    crisisHighlightIds = [];
  } else {
    crisisHighlightIds = ids;
  }
}

function crisisShowCrisisView() {
  setView('crisis');
}

function crisisShowTerritories() {
  setView('territory');
}

function crisisOpenLiveSim() {
  const cr = mapData && mapData.crisis_readout;
  const types = (cr && cr.crisis_types) || [];
  const url = '/simulation.html' + (types.length > 0 ? '?crisis=' + encodeURIComponent(types[0]) : '');
  window.open(url, '_blank');
}

function toggleCrisisReadout() {
  crisisReadoutCollapsed = !crisisReadoutCollapsed;
  fedStarmapSaveUI({crisis_collapsed:crisisReadoutCollapsed});
  const panel = document.getElementById('map-read');
  if (crisisReadoutCollapsed) {
    panel.style.maxHeight = '80px';
  } else {
    panel.style.maxHeight = 'calc(100vh - 160px)';
  }
}

function setBar(name, val, max, color) {
  const pct = Math.min(100, Math.max(0, ((val || 0) / max) * 100));
  const fill = document.getElementById('wb-' + name);
  const vl = document.getElementById('wv-' + name);
  if (fill) fill.style.width = pct + '%';
  if (vl) vl.textContent = val || 0;
}

      // --- Faction zone hover/click detection ---
// SPATIAL-03A: Use deformed polygon for hit testing when available (matches visual)
function getFactionZoneAt(sx, sy) {
  const {x, y} = screenToWorld(sx, sy);
  for (const z of factionZones) {
    // Prefer deformed polygon (what user actually sees)
    const hitPoly = (z._deformedPoly && z._deformedPoly.length >= 3) ? z._deformedPoly : z.polygon;
    if (hitPoly && hitPoly.length >= 3) {
      // Polygon hit-test
      if (pointInPolygon(x, y, hitPoly)) return z;
    } else {
      // Circle fallback for 0-1 NPC factions
      const dx = x - z.fcx, dy = y - z.fcy;
      if (dx*dx + dy*dy < z.zoneR * z.zoneR) return z;
    }
  }
  return null;
}

function showFactionTip(zone, mx, my) {
  const tip = document.getElementById('faction-tip');
  const fdata = zone.fdata;
  const cohesion = fdata.cohesion || 50;
  const statusLabel = cohesion < 40 ? 'contested' : 'influence';
  const statusClass = cohesion < 40 ? 'ft-contested' : 'ft-influence';

  document.getElementById('ft-name').textContent = FACTION_DISPLAY[zone.fid] || zone.fid;
  document.getElementById('ft-name').style.color = zone.color;

  let body = '';
  body += `<div id="ft-row"><span class="ftl">NPCs</span><span class="ftv">${zone.groupSize}</span></div>`;
  body += `<div id="ft-row"><span class="ftl">Cohesion</span><span class="ftv">${cohesion}</span></div>`;
  body += `<div id="ft-row"><span class="ftl">Influence</span><span class="ftv">${fdata.influence || 0}</span></div>`;
  body += `<div id="ft-row"><span class="ftl">Standing</span><span class="ftv">${fdata.standing || 0}</span></div>`;
  body += `<div id="ft-row"><span class="ftl">Vigilance</span><span class="ftv">${fdata.vigilance || 0}</span></div>`;

  // Stances toward other factions (show top 3)
  const stances = fdata.stances || {};
  const stanceEntries = Object.entries(stances).slice(0, 3);
  if (stanceEntries.length > 0) {
    body += '<div style="border-top:1px solid rgba(255,255,255,0.1);margin-top:6px;padding-top:6px">';
    body += '<div id="ft-row" style="color:#78909c;font-size:0.625rem;text-transform:uppercase;letter-spacing:1px">Key Stances</div>';
    for (const [targetId, stance] of stanceEntries) {
      const stanceLabel = stance.stance || stance.attitude || 'neutral';
      const stanceColor = stanceLabel === 'hostile' ? '#ef5350' : (stanceLabel === 'allied' || stanceLabel === 'friendly' ? '#66bb6a' : '#ffa726');
      body += `<div id="ft-row"><span class="ftl" style="font-size:0.625rem">${FACTION_DISPLAY[targetId] || targetId}</span><span class="ftv" style="color:${stanceColor};font-size:0.625rem">${stanceLabel}</span></div>`;
    }
    body += '</div>';
  }

  body += `<div style="margin-top:8px"><span id="ft-status" class="${statusClass}">${statusLabel} sector</span></div>`;

  document.getElementById('ft-body').innerHTML = body;

  // Position tooltip
  let tx = mx + 16, ty = my - 10;
  if (tx + 220 > W) tx = mx - 220;
  if (ty + 200 > H) ty = my - 200;
  if (ty < 0) ty = 10;
  tip.style.left = tx + 'px';
  tip.style.top = ty + 'px';
  tip.classList.add('show');
}

function hideFactionTip() {
  document.getElementById('faction-tip').classList.remove('show');
}

// --- View-dependent rendering params ---
// SPATIAL-03A: Lookup sector owner faction (uses territory data cached from buildNodesSpatial)
let _sectorOwnerCache = {};
function getSectorOwnerId(sectorId) {
  if (_sectorOwnerCache[sectorId]) return _sectorOwnerCache[sectorId];
  const territories = (mapData && mapData.faction_territories) || [];
  for (const t of territories) {
    if (t.sector_id === sectorId) { _sectorOwnerCache[sectorId] = t.faction_id; return t.faction_id; }
  }
  _sectorOwnerCache[sectorId] = null;
  return null;
}
function getViewParams() {
   if (currentView === 'territory') {
     if (spatialMode) {
       // Base values for readability pass
       let zoneFillAlpha = 0.12;
       let zoneBorderAlpha = 0.85;
       let zoneBorderWidth = 4.5;
       let labelSize = 24;
       let labelAlpha = 1.0;
       let sectorLabelSize = 16;
       let sectorLabelAlpha = 0.9;
       // Enhance for readable spatial mode
       if (readableSpatialMode) {
         zoneFillAlpha *= 0.6; // even more translucent
         labelSize += 4; // increase label size
         sectorLabelSize += 2;
         labelAlpha = 1.0;
         sectorLabelAlpha = 1.0;
       }
       return {
         zoneFillAlpha,
         zoneBorderAlpha,
         zoneBorderWidth,
         lineAlphaScale: 0,
         npcFactionBorder: 1.0,
         labelSize,
         labelAlpha,
         sectorLabelSize,
         sectorLabelAlpha
       };
     } else {
       // Original SPATIAL-03C values for legacy territory mode
       return {
         zoneFillAlpha: 0.22,
         zoneBorderAlpha: 0.85,
         zoneBorderWidth: 4.5,
         lineAlphaScale: 0,
         npcFactionBorder: 1.0,
         labelSize: 22,
         labelAlpha: 1.0,
         sectorLabelSize: 14,
         sectorLabelAlpha: 0.9
       };
     }
    } else if (currentView === 'network') {
      return {
        zoneFillAlpha: 0.01,
        zoneBorderAlpha: 0.08,
        zoneBorderWidth: 1,
        lineAlphaScale: 1.0,
        npcFactionBorder: 2.5,
        labelSize: 16,
        labelAlpha: 0.5
      };
    } else { // crisis
      return {
        zoneFillAlpha: 0.06,
        zoneBorderAlpha: 0.3,
        zoneBorderWidth: 2.5,
        lineAlphaScale: 0.6,
        npcFactionBorder: 3,
        labelSize: 16,
        labelAlpha: 0.6
      };
    }
  }

// --- Label priority system ---
// Priority levels: 0=hidden, 1=low(ordinary), 2=medium(crisis/event), 3=high(selected/important), 4=critical(hovered)
// SPATIAL-03A: In territory mode at default zoom, hide NPC labels to reduce clutter.
// Show only faction labels + sector names. NPC labels appear when zoomed >1.5x or faction is selected.
function getLabelPriority(node) {
  const isHovered = hoveredNode === node;
  const isSelected = selectedNode === node;
  if (isHovered || isSelected) return 4;

  // SPATIAL-03A: In territory mode at low zoom, hide NPC labels (but show sector labels always)
  if (currentView === 'territory' && spatialMode && !node.sectorData && zoom < 1.5 && !selectedFaction) {
    // Only show important/active NPCs even at low zoom
    if (isNodeImportant(node)) return 1; // low priority — may be culled by collision
    return 0; // hide ordinary NPC labels in territory mode at default zoom
  }
  // If a faction is selected, show that faction's NPC labels
  if (selectedFaction && node.faction === selectedFaction) {
    return isNodeImportant(node) ? 3 : 2;
  }
  // Fade out labels for non-selected faction NPCs when faction is selected
  if (selectedFaction && node.faction && node.faction !== selectedFaction) {
    return 0;
  }

  const hasFaction = !!node.faction;

  // Always show in 'all' mode
  if (labelMode === 'all') {
    if (isNodeImportant(node)) return 3;
    if (isNodeCrisisRelevant(node)) return 2;
    return hasFaction ? 2 : 1; // faction members get higher base priority
  }

  // 'important' mode: show faction members, faction leaders, active NPCs, crisis NPCs, extreme moods
  if (labelMode === 'important') {
    if (isNodeImportant(node)) return 3;
    if (hasFaction) return 2; // all faction members visible
    if (isNodeCrisisRelevant(node)) return 2;
    return 0; // hide unaffiliated ordinary NPCs (companions, neutrals, unknowns)
  }

  // 'factions' mode: only show hovered/selected (priority 4, already handled above)
  return 0;
}

function isNodeImportant(node) {
// Faction leaders (char_101-108) are always important
const id = node.id || '';
if (id.startsWith('char_1')) return true; // faction leaders
// Historical figures (char_001-005) are important
if (id.startsWith('char_0')) return true;
// High activity nodes
if (node.activity > 0.8) return true;
// Extreme mood — check mood value if available
const mood = node.npc && (node.npc.mood_score || node.npc.mood);
if (typeof mood === 'number') {
if (mood < 0.25 || mood > 0.85) return true;
}
return false;
}

function isNodeCrisisRelevant(node) {
if (currentView === 'crisis') {
// In crisis mode, rivals and enigmas are crisis-relevant
if (node.category === 'rival' || node.category === 'enigma') return true;
// NPCs with very low mood are crisis-relevant
const mood = node.npc && (node.npc.mood_score || node.npc.mood);
if (typeof mood === 'number' && mood < 0.3) return true;
// NPCs in factions with low cohesion
if (node.faction) {
const zone = factionZones.find(z => z.fid === node.faction);
if (zone && zone.fdata && (zone.fdata.cohesion || 50) < 40) return true;
}
}
// NPCs mentioned in recent events
const recentEvents = (mapData && mapData.events) || [];
const recentCharIds = recentEvents.slice(0, 10).map(e => e.char_id).filter(Boolean);
if (recentCharIds.includes(node.id)) return true;
return false;
}

function isSignificantEvent(ev) {
const severity = ev.severity || '';
const isHighSeverity = ['CRITICAL', 'MAJOR'].includes(severity);
// Check if involves a primary character (faction leader or historical figure)
const charId = ev.char_id || '';
const isPrimaryChar = charId.startsWith('char_1') || charId.startsWith('char_0');
return isHighSeverity || isPrimaryChar;
}

// Compute label bounding box for collision detection
function computeLabelBBox(node, fontSize) {
const textW = ctx.measureText(node.name).width;
const labelY = node.y + node.radius + 18;
return {
x: node.x - textW / 2,
y: labelY - fontSize,
w: textW,
h: fontSize + 4,
priority: getLabelPriority(node),
node: node
};
}

// Simple AABB overlap check
function labelsOverlap(a, b) {
return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

// --- Drawing ---
function draw() {
  const t = performance.now();
  const vp = getViewParams();
  ctx.clearRect(0, 0, W, H);

  ctx.fillStyle = '#0a0a1a';
  ctx.fillRect(0, 0, W, H);

  ctx.save();
  ctx.translate(panX, panY);
  ctx.scale(zoom, zoom);

  // Background stars
  for (const s of stars) {
    const twinkle = 0.5 + 0.5 * Math.sin(t * s.twinkleSpeed + s.twinklePhase);
    const alpha = s.brightness * twinkle;
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200,220,255,${alpha})`;
    ctx.fill();
  }

        // SPATIAL-03A: Adjacency lines — view-dependent rendering
      if (spatialMode && spatialAdjacencies.length > 0) {
        // Territory mode: hide adjacency lines by default (show only if faction selected)
        // Network mode: show all, fade non-selected
        // Crisis mode: show only crisis-adjacent
        const showAdj = currentView !== 'territory' || selectedFaction;
        if (showAdj) {
          for (const adj of spatialAdjacencies) {
            // Determine if this adjacency is relevant to selected faction
            let alpha = 0.08; // default very faint
            if (currentView === 'territory' && selectedFaction) {
              // Only show edges connected to selected faction's sectors
              const fromSec = spatialSectors[adj.from];
              const toSec = spatialSectors[adj.to];
              const fromOwner = fromSec ? getSectorOwnerId(adj.from) : null;
              const toOwner = toSec ? getSectorOwnerId(adj.to) : null;
              if (fromOwner === selectedFaction || toOwner === selectedFaction) {
                alpha = 0.25;
              } else {
                alpha = 0; // hide non-selected edges in territory mode
              }
            } else if (currentView === 'network') {
              if (selectedFaction) {
                const fromOwner = getSectorOwnerId(adj.from);
                const toOwner = getSectorOwnerId(adj.to);
                if (fromOwner === selectedFaction || toOwner === selectedFaction) {
                  alpha = 0.35;
                } else {
                  alpha = 0.03; // fade non-selected
                }
              }
            } else if (currentView === 'crisis') {
              alpha = 0.04; // minimal in crisis mode
            }
            if (alpha <= 0) continue;
            ctx.beginPath();
            ctx.moveTo(adj.fromX, adj.fromY);
            ctx.lineTo(adj.toX, adj.toY);
            ctx.strokeStyle = `rgba(79,195,247,${alpha})`;
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
// Draw sector markers
// SPATIAL-03C: In territory mode at default zoom, hide frontier/outer sector labels to reduce clutter.
// Only show core, inner, and home sectors as labeled. Others show as dots only.
for (const sn of spatialSectorNodes) {
const isHov = hoveredNode === sn;
const regionColor = REGION_COLORS[sn.regionType] || '#78909c';
// SPATIAL-03A: Fade sectors not in selected faction
const secOwnerFid = getSectorOwnerId(sn.id.replace('sector:', '') || (sn.sectorData && sn.sectorData.id));
const secFade = selectedFaction ? (secOwnerFid === selectedFaction || !secOwnerFid ? 1.0 : 0.2) : 1.0;
// SPATIAL-03C: Determine if this sector's label should be shown in territory mode
const isHomeSector = FACTION_ORDER.some(fid => {
  const f = factions[fid]; return f && f.home_sector_id === ((sn.sectorData && sn.sectorData.id) || sn.id.replace('sector:', ''));
});
const isCoreOrInner = sn.regionType === 'core' || sn.regionType === 'inner';
const showLabelInTerritory = currentView !== 'territory' || isCoreOrInner || isHomeSector || isHov || zoom >= 1.5;
// Sector dot
ctx.beginPath();
ctx.arc(sn.x, sn.y, sn.radius * (isHov ? 1.3 : 1), 0, Math.PI * 2);
const secGrad = ctx.createRadialGradient(sn.x, sn.y, 0, sn.x, sn.y, sn.radius);
secGrad.addColorStop(0, hexToRgba(sn.color, 0.6 * secFade));
secGrad.addColorStop(1, hexToRgba(sn.color, 0.15 * secFade));
ctx.fillStyle = secGrad;
ctx.fill();
// Region-type ring
ctx.beginPath();
ctx.arc(sn.x, sn.y, sn.radius + 2, 0, Math.PI * 2);
ctx.strokeStyle = hexToRgba(regionColor, 0.3 * secFade);
ctx.lineWidth = 1;
ctx.stroke();
// Sector name label — SPATIAL-03C: larger, higher contrast, boxed, with priority filtering
if (showLabelInTerritory) {
const secLabelText = sn.name.toUpperCase();
// SPATIAL-03C: Use vp.sectorLabelSize in territory mode (14px), fallback to rmLabelSize
const secFontSize = vp.sectorLabelSize || (rmLabelSize || 12);
ctx.font = (isHov || isHomeSector ? 'bold ' : '') + secFontSize + 'px Courier New';
ctx.textAlign = 'center';
const secLabelW = ctx.measureText(secLabelText).width + 10;
const secLabelH = secFontSize + 6;
const secLabelX = sn.x - secLabelW / 2;
const secLabelY = sn.y - sn.radius - 10 - secLabelH + 2;
// SPATIAL-03C: Darker box with border for more contrast
ctx.fillStyle = `rgba(8,8,22,${0.8 * secFade})`;
ctx.fillRect(secLabelX, secLabelY, secLabelW, secLabelH);
// Faction color accent at top if owned
if (secOwnerFid && factions[secOwnerFid]) {
  ctx.fillStyle = hexToRgba(factions[secOwnerFid].color, 0.6 * secFade);
  ctx.fillRect(secLabelX, secLabelY, secLabelW, 2);
}
// Thin box border
ctx.strokeStyle = hexToRgba(regionColor, 0.3 * secFade);
ctx.lineWidth = 0.5;
ctx.strokeRect(secLabelX, secLabelY, secLabelW, secLabelH);
// Text — SPATIAL-03C: high contrast (white or light, not region-muted)
ctx.fillStyle = `rgba(220,225,240,${(isHov ? 1.0 : (vp.sectorLabelAlpha || 0.7)) * secFade})`;
ctx.fillText(secLabelText, sn.x, sn.y - sn.radius - 10);
} else {
// Minor sector: tiny dot label or nothing
ctx.fillStyle = hexToRgba(regionColor, 0.25 * secFade);
ctx.font = '9px Courier New';
ctx.textAlign = 'center';
ctx.fillText(sn.name.toUpperCase().substring(0, 3), sn.x, sn.y - sn.radius - 6);
}
      }
  }

  // SPATIAL-03B: Faction territory zones — large Voronoi regions with strong fills
  // Voronoi cells fill the entire canvas with non-overlapping territory regions.
  // This replaces the old tiny convex hull approach that produced unreadable maps.
  for (const z of factionZones) {
    const fdata = z.fdata;
    const cohesion = fdata ? (fdata.cohesion || 50) : 50;
    const isHovered = hoveredFaction === z;
    const isSelectedFaction = selectedFaction === z.fid;
    const factionFade = selectedFaction ? (isSelectedFaction ? 1.0 : 0.15) : 1.0;

// Living territory deformation — SPATIAL-03C: more organic, more wobble for nebula feel
const infl = (fdata.influence || 20) / 100;
const coh = (fdata.cohesion || 50) / 100;
const act = fdata.activity_rate || 0;
// SPATIAL-03C: Increased amplitudes for more organic, less geometric look
const breathAmp = 4 + act * 6 + infl * 5;
const breathPhase = z.zonePulse + t * 0.001 * (0.6 + act * 0.6);
const breathOffset = Math.sin(breathPhase) * breathAmp;
const wobbleAmp = 3 + (1 - coh) * 8; // SPATIAL-03C: more wobble at low cohesion
const wobbleSpeed = 0.0008 + (1 - coh) * 0.001;

    let deformedPoly = [];
    if (z.polygon.length >= 3) {
      const n = z.polygon.length;
      for (let i = 0; i < n; i++) {
        const prev = z.polygon[(i - 1 + n) % n];
        const curr = z.polygon[i];
        const next = z.polygon[(i + 1) % n];
        const e1x = curr.x - prev.x, e1y = curr.y - prev.y;
        const len1 = Math.sqrt(e1x*e1x + e1y*e1y) || 1;
        const n1x = e1y / len1, n1y = -e1x / len1;
        const e2x = next.x - curr.x, e2y = next.y - curr.y;
        const len2 = Math.sqrt(e2x*e2x + e2y*e2y) || 1;
        const n2x = e2y / len2, n2y = -e2x / len2;
        let nx = (n1x + n2x) / 2, ny = (n1y + n2y) / 2;
        const nlen = Math.sqrt(nx*nx + ny*ny) || 1;
        nx /= nlen; ny /= nlen;
        const wobPhase = i * 2.7 + z.zonePulse + t * wobbleSpeed;
        const wobble = Math.sin(wobPhase) * wobbleAmp;
        const totalOffset = breathOffset + wobble;
        deformedPoly.push({ x: curr.x + nx * totalOffset, y: curr.y + ny * totalOffset });
      }
    }
    z._deformedPoly = deformedPoly;

    const fillAlpha = (isHovered ? Math.min(0.35, vp.zoneFillAlpha * 1.5) : vp.zoneFillAlpha) * factionFade;
    const borderAlpha = (isHovered ? Math.min(1, vp.zoneBorderAlpha * 1.3) : vp.zoneBorderAlpha) * factionFade;
    const borderW = isHovered ? vp.zoneBorderWidth + 1 : vp.zoneBorderWidth;

    const renderPoly = z._deformedPoly && z._deformedPoly.length >= 3 ? z._deformedPoly : z.polygon;
    if (renderPoly.length >= 3) {
// --- VORONOI TERRITORY FILL ---
// Use gradient from faction home position: stronger center, lighter edges
const bounds = polyBounds(renderPoly);
const gradRadius = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY) * 0.7;
const grad = ctx.createRadialGradient(z.fcx, z.fcy, 0, z.fcx, z.fcy, gradRadius);
grad.addColorStop(0, hexToRgba(z.color, fillAlpha * 1.4));
grad.addColorStop(1, hexToRgba(z.color, fillAlpha * 0.6));
tracePolygonPath(ctx, renderPoly);
ctx.fillStyle = grad;
ctx.fill();

// SPATIAL-03C: Inner nebula glow — second radial gradient at centroid for depth
// This prevents the "flat polygon" look by adding a luminous core
const nebulaR = Math.max(60, Math.min(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY) * 0.35);
const nebula = ctx.createRadialGradient(z.fcx, z.fcy, 0, z.fcx, z.fcy, nebulaR);
nebula.addColorStop(0, hexToRgba(z.color, fillAlpha * 0.8));
nebula.addColorStop(0.5, hexToRgba(z.color, fillAlpha * 0.3));
nebula.addColorStop(1, hexToRgba(z.color, 0));
tracePolygonPath(ctx, renderPoly);
ctx.fillStyle = nebula;
ctx.fill();

// SPATIAL-03C: Subtle edge vignette — darker at edges for depth
const edgeGrad = ctx.createRadialGradient(
  (bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2, gradRadius * 0.3,
  (bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2, gradRadius * 1.1
);
edgeGrad.addColorStop(0, 'rgba(0,0,0,0)');
edgeGrad.addColorStop(1, 'rgba(5,5,18,0.15)');
tracePolygonPath(ctx, renderPoly);
ctx.fillStyle = edgeGrad;
ctx.fill();

// --- TERRITORY BORDER — SPATIAL-03C: double-stroke for glow effect ---
if (cohesion < 40) {
ctx.setLineDash([8, 6]);
} else {
ctx.setLineDash([]);
}
// Outer glow border (wide, faint)
tracePolygonPath(ctx, renderPoly);
ctx.strokeStyle = hexToRgba(z.color, borderAlpha * 0.3);
ctx.lineWidth = borderW + 4;
ctx.stroke();
// Inner solid border
tracePolygonPath(ctx, renderPoly);
ctx.strokeStyle = hexToRgba(z.color, borderAlpha);
ctx.lineWidth = borderW;
ctx.stroke();
ctx.setLineDash([]);

      // Contested overlay
      if (z.voronoiCell) {
        // Voronoi cells don't overlap by construction, but we check
        // for contested status from territory data
        const isContested = (z.ownedSectors || []).some(sid => {
          const td = (mapData.faction_territories || []).find(tt => tt.sector_id === sid);
          return td && td.control_level < 60;
        });
        if (isContested) {
          const contestAlpha = 0.15 + 0.15 * (0.5 + 0.5 * Math.sin(t * 0.003 + z.zonePulse));
          tracePolygonPath(ctx, renderPoly);
          ctx.strokeStyle = `rgba(255,152,0,${contestAlpha})`;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

// --- FACTION LABEL — SPATIAL-03C: large, bold, bordered box for instant readability ---
const displayName = (fdata ? fdata.display_name : z.fid).toUpperCase();
const labelFontSize = vp.labelSize; // 22px in territory mode
ctx.font = `bold ${labelFontSize}px Courier New`;
ctx.textAlign = 'center';
const labelTextW = ctx.measureText(displayName).width;
const lx = z.labelX;
const ly = z.labelY - 6;

// SPATIAL-03C: Bordered background box with faction color accent line at top
const boxPad = 8;
const boxW = labelTextW + boxPad * 2;
const boxH = labelFontSize + boxPad * 2 + 16; // extra room for sub-label
const boxX = lx - boxW / 2;
const boxY = ly - labelFontSize - boxPad;
// Dark fill
ctx.fillStyle = `rgba(8,8,22,${0.85 * factionFade})`;
ctx.fillRect(boxX, boxY, boxW, boxH);
// Faction color accent line at top of box
ctx.fillStyle = hexToRgba(z.color, 0.9 * factionFade);
ctx.fillRect(boxX, boxY, boxW, 3);
// Thin border around box
ctx.strokeStyle = hexToRgba(z.color, 0.5 * factionFade);
ctx.lineWidth = 1;
ctx.strokeRect(boxX, boxY, boxW, boxH);

// Faction name — bright and clear
ctx.fillStyle = hexToRgba(z.color, (isHovered ? 1.0 : vp.labelAlpha) * factionFade);
ctx.fillText(displayName, lx, ly);

// Sub-label: owned sector count
const sectorCount = (z.ownedSectors || []).length;
const subLabel = sectorCount > 0 ? `${sectorCount} SECTOR${sectorCount !== 1 ? 'S' : ''}` : 'TERRITORY';
const subFontSize = Math.max(12, labelFontSize - 6);
ctx.font = `bold ${subFontSize}px Courier New`;
const subLabelW = ctx.measureText(subLabel).width;
// Sub-label background within the same box (slightly different shade)
ctx.fillStyle = `rgba(8,8,22,${0.6 * factionFade})`;
ctx.fillRect(lx - subLabelW / 2 - 4, ly + 4, subLabelW + 8, subFontSize + 6);
ctx.fillStyle = hexToRgba(z.color, (isHovered ? 0.8 : 0.6) * factionFade);
ctx.fillText(subLabel, lx, ly + 6 + subFontSize);
    } else {
      // --- CIRCLE FALLBACK (shouldn't happen with Voronoi, but safety) ---
      ctx.beginPath();
      ctx.arc(z.fcx, z.fcy, z.zoneR, 0, Math.PI * 2);
      ctx.fillStyle = hexToRgba(z.color, fillAlpha);
      ctx.fill();
      if (cohesion < 40) { ctx.setLineDash([8, 6]); } else { ctx.setLineDash([]); }
      ctx.beginPath();
      ctx.arc(z.fcx, z.fcy, z.zoneR, 0, Math.PI * 2);
      ctx.strokeStyle = hexToRgba(z.color, borderAlpha);
      ctx.lineWidth = borderW;
      ctx.stroke();
      ctx.setLineDash([]);
      // Circle fallback label with background box
      const cDisplayName = (fdata ? fdata.display_name : z.fid).toUpperCase();
      ctx.font = `bold ${vp.labelSize}px Courier New`;
      ctx.textAlign = 'center';
      const cLabelW = ctx.measureText(cDisplayName).width;
      const clx = z.fcx, cly = z.fcy + z.zoneR + 22;
      ctx.fillStyle = `rgba(10,10,26,0.75)`;
      ctx.fillRect(clx - cLabelW / 2 - 5, cly - vp.labelSize - 5, cLabelW + 10, vp.labelSize + 10);
      ctx.fillStyle = hexToRgba(z.color, (isHovered ? 1.0 : vp.labelAlpha) * factionFade);
      ctx.fillText(cDisplayName, clx, cly);
    }
  }

    // SPATIAL-03A: Selection highlight — bright pulsing ring around selected faction zone
    if (selectedFaction) {
      const sz = factionZones.find(z => z.fid === selectedFaction);
      if (sz) {
        const selPulse = 0.6 + 0.4 * Math.sin(t * 0.004);
        const selRenderPoly = (sz._deformedPoly && sz._deformedPoly.length >= 3) ? sz._deformedPoly : sz.polygon;
        if (selRenderPoly.length >= 3) {
          tracePolygonPath(ctx, selRenderPoly);
          ctx.strokeStyle = `rgba(255,255,255,${0.4 * selPulse})`;
          ctx.lineWidth = 3;
          ctx.stroke();
          // Outer glow
          const padded = padPolygon(selRenderPoly, 12);
          tracePolygonPath(ctx, padded);
          ctx.strokeStyle = `rgba(255,255,255,${0.1 * selPulse})`;
          ctx.lineWidth = 6;
          ctx.stroke();
        } else {
          ctx.beginPath();
          ctx.arc(sz.fcx, sz.fcy, sz.zoneR + 6, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(255,255,255,${0.4 * selPulse})`;
          ctx.lineWidth = 3;
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(sz.fcx, sz.fcy, sz.zoneR + 14, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(255,255,255,${0.1 * selPulse})`;
          ctx.lineWidth = 6;
          ctx.stroke();
        }
      }
    }

// Center zone — neutral / Federation core (skip in spatial mode, Sol Prime rendered as sector marker)
if (!spatialMode) {
  const cx = W / 2, cy = H / 2;
  const centerR = 70;
  ctx.beginPath();
  ctx.arc(cx, cy, centerR, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(120,144,156,0.04)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(120,144,156,0.12)';
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 4]);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(120,144,156,0.4)';
  ctx.font = (rmLabelSize || 14) + 'px Courier New';
  ctx.textAlign = 'center';
    ctx.fillText('NEUTRAL / FEDERATION CORE', cx, cy + centerR + 20);
}

      // Relationship lines
      if (mapData) {
        const nodeMap = {};
        nodes.forEach(n => nodeMap[n.id] = n);

        for (const node of nodes) {
          const rels = node.npc.relationships || {};
          for (const [otherId, score] of Object.entries(rels)) {
            const other = nodeMap[otherId];
            if (!other) continue;
            if (node.id > otherId) continue;

            const strength = Math.abs(score) / 100;
            if (strength < 0.1) continue;

            const dx = node.x - other.x, dy = node.y - other.y;
            const dist = Math.sqrt(dx*dx + dy*dy);
            const maxDist = Math.min(W, H) * 0.6;
            const distFade = dist > maxDist ? 0.3 : (dist > maxDist * 0.5 ? 0.6 : 1.0);

            const isPositive = score > 50;
            const isConflict = score < -30;

            // Crisis view: only show conflict lines
            if (currentView === 'crisis' && !isConflict && strength < 0.4) continue;

            // SPATIAL-03A: Fade relationship lines when a faction is selected
            let factionLineFade = 1.0;
            if (selectedFaction) {
              const nodeInFaction = node.faction === selectedFaction;
              const otherInFaction = other.faction === selectedFaction;
              if (!nodeInFaction && !otherInFaction) factionLineFade = 0.05;
              else if (nodeInFaction || otherInFaction) factionLineFade = 0.7;
            }

            const baseAlpha = strength * 0.4 * distFade * vp.lineAlphaScale * factionLineFade;

            // Network view: raise visibility floor and boost contrast for low-vision readability
            let effectiveAlpha = baseAlpha;
            let effectiveWidth = Math.max(1, strength * 3 * distFade);
            if (currentView === 'network') {
              effectiveAlpha = Math.max(0.18, effectiveAlpha * NETWORK_HIGH_CONTRAST);
              effectiveWidth = Math.max(1.8, effectiveWidth * 1.4);
            }
            // Clamp to valid range
            effectiveAlpha = Math.min(1, Math.max(0, effectiveAlpha));

        let lineColor;
        if (isPositive) {
          lineColor = currentView === 'network'
            ? `rgba(180,255,180,${effectiveAlpha})`
            : `rgba(102,187,106,${baseAlpha})`;
        } else if (isConflict) {
          // Crisis view makes conflict lines pulse
          const crisisPulse = currentView === 'crisis' ? (0.7 + 0.3 * Math.sin(t * 0.005)) : 1.0;
          lineColor = currentView === 'network'
            ? `rgba(255,120,120,${effectiveAlpha})`
            : `rgba(239,83,80,${baseAlpha * crisisPulse})`;
        } else {
          lineColor = currentView === 'network'
            ? `rgba(200,230,255,${effectiveAlpha})`
            : `rgba(255,152,0,${baseAlpha * 0.6})`;
        }

        ctx.beginPath();
        ctx.moveTo(node.x, node.y);
        ctx.lineTo(other.x, other.y);
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = currentView === 'network' ? effectiveWidth : Math.max(1, strength * 3 * distFade);
        ctx.stroke();
      }
    }
  }

      // NPC nodes
      const pulse = Math.sin(t * 0.003) * 0.3 + 0.7;
      for (const node of nodes) {
        const isHovered = hoveredNode === node;
        const isSelected = selectedNode === node;
        const r = node.radius * (isHovered ? 1.4 : 1);
// SPATIAL-03D: Adjust NPC scaling for readability in spatial territory mode
const spatialTerritoryMode = spatialMode && currentView === 'territory';
const rScale = spatialTerritoryMode ? (readableSpatialMode ? 0.9 : 0.7) : 1.0;
const adjR = r * rScale;
        // Guard: skip NPCs with non-finite coordinates (prevents createRadialGradient crash)
        if (!isFinite(node.x) || !isFinite(node.y) || !isFinite(adjR)) continue;
        // SPATIAL-03A: Fade NPCs not in selected faction
        const npcFade = selectedFaction ? (node.faction === selectedFaction ? 1.0 : 0.15) : 1.0;
        // Skip drawing very faded NPCs (optimization)
        if (npcFade < 0.1) continue;

    // Crisis view: highlight rivals and enigmas with pulse
    const isCrisisHighlight = currentView === 'crisis' && (node.category === 'rival' || node.category === 'enigma');

// High-activity NPC extra glow (pulses with faction breath)
// SPATIAL-03B: Reduce glow in territory mode
     if (node.activity > 0.7 && node.faction && npcFade > 0.5) {
      const zone = factionZones.find(z => z.fid === node.faction);
      if (zone) {
      const bp = zone.zonePulse + t * 0.001 * (0.8 + node.activity * 0.4);
       const glowSizeMult = spatialTerritoryMode ? (spatialMode ? (readableSpatialMode ? 2.5 : 2.0) : 1.5) : 3;
       const glowSize = Math.max(0, adjR * glowSizeMult + Math.sin(bp) * 4);
       const aglow = ctx.createRadialGradient(node.x, node.y, adjR * 0.5, node.x, node.y, glowSize);
       const innerMult = spatialTerritoryMode ? (spatialMode ? (readableSpatialMode ? 0.2 : 0.15) : 0.1) : 0.2;
      aglow.addColorStop(0, hexToRgba(node.color, innerMult * npcFade));
      aglow.addColorStop(1, hexToRgba(node.color, 0));
      ctx.beginPath();
      ctx.arc(node.x, node.y, glowSize, 0, Math.PI * 2);
      ctx.fillStyle = aglow;
      ctx.fill();
      }
      }

// Glow — SPATIAL-03A: apply npcFade; SPATIAL-03B: reduce in territory mode
// SPATIAL-03D: Adjust glow for readability in spatial territory mode
const glowRMult = spatialTerritoryMode ? (spatialMode ? (readableSpatialMode ? 2.5 : 2.0) : 1.5) : 3;
const glowR = adjR * glowRMult;
const glow = ctx.createRadialGradient(node.x, node.y, adjR * 0.5, node.x, node.y, glowR);
const innerGlowMult = spatialTerritoryMode ? (spatialMode ? (readableSpatialMode ? 0.22 : 0.18) : 0.12) : (isCrisisHighlight ? 0.4 : 0.27);
glow.addColorStop(0, hexToRgba(node.color, innerGlowMult * npcFade));
glow.addColorStop(1, hexToRgba(node.color, 0));
ctx.beginPath();
ctx.arc(node.x, node.y, glowR, 0, Math.PI * 2);
ctx.fillStyle = glow;
ctx.fill();

// Activity pulse ring
if ((node.activity > 0.5 || isCrisisHighlight) && npcFade > 0.3 && !spatialTerritoryMode) {
ctx.beginPath();
ctx.arc(node.x, node.y, adjR + 4 + pulse * 3, 0, Math.PI * 2);
ctx.strokeStyle = isCrisisHighlight ? 'rgba(239,83,80,0.5)' : (node.color + '44');
ctx.lineWidth = 1;
ctx.stroke();
}

// Main node — SPATIAL-03B: use adjR for territory mode
ctx.beginPath();
ctx.arc(node.x, node.y, adjR, 0, Math.PI * 2);
const grad = ctx.createRadialGradient(node.x - adjR*0.3, node.y - adjR*0.3, 0, node.x, node.y, adjR);
grad.addColorStop(0, lighten(node.color, 40));
grad.addColorStop(1, node.color);
ctx.fillStyle = grad;
ctx.fill();

// Faction affiliation border (colored ring around dot) — SPATIAL-03B: vp.npcFactionBorder handles territory thinness
if (node.faction && node.factionColor) {
ctx.strokeStyle = node.factionColor;
ctx.lineWidth = vp.npcFactionBorder;
ctx.stroke();
    } else {
      // Unaffiliated: grey ring, thicker for companions, thinner for others
      const catColor = CATEGORY_COLORS[node.category] || CATEGORY_COLORS.unknown;
      ctx.strokeStyle = currentView === 'crisis' && node.category === 'rival'
        ? '#ef5350' : catColor;
      ctx.lineWidth = node.category === 'companion' ? 2 : 1;
      ctx.stroke();
    }

  // Selected highlight — SPATIAL-03B: use adjR
  if (isSelected) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, adjR + 3, 0, Math.PI * 2);
    ctx.strokeStyle = '#4fc3f7';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // Crisis Readout highlight — gold ring for involved NPCs
  if (crisisHighlightIds.includes(node.id)) {
    const crPulse = Math.sin(t * 0.004) * 0.4 + 0.6;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 6 + crPulse * 3, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(255,215,0,${0.5 + crPulse * 0.3})`;
    ctx.lineWidth = 2;
    ctx.stroke();
    // Second outer glow
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 12 + crPulse * 4, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(255,215,0,${0.15 + crPulse * 0.1})`;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

// Name label — priority-based (replaces always-show)
{
const priority = getLabelPriority(node);
if (priority > 0) {
const baseLabelSize = (rmLabelSize || 14);
const fontSize = (isHovered || isSelected) ? Math.max(17, baseLabelSize) : (priority >= 3 ? Math.max(15, baseLabelSize) : Math.max(13, baseLabelSize));
ctx.font = `${fontSize}px Courier New`;
ctx.textAlign = 'center';
const labelY = node.y + r + 18;
// Store label for collision pass
node._labelBox = {
x: node.x - ctx.measureText(node.name).width / 2,
y: labelY - fontSize,
w: ctx.measureText(node.name).width,
h: fontSize + 4,
priority: priority
};
node._labelY = labelY;
node._labelFontSize = fontSize;
} else {
node._labelBox = null;
}
}
    } // end NPC node loop

    // --- Label collision resolution & drawing pass ---
    // Collect all visible labels
    const allLabels = [];
    for (const node of nodes) {
        if (node._labelBox) {
            allLabels.push({
                box: node._labelBox,
                node: node,
                fontSize: node._labelFontSize,
                y: node._labelY
            });
        }
    }
    // Sort by priority descending (highest priority first — gets drawn, blocks overlapping lower)
    allLabels.sort((a, b) => b.box.priority - a.box.priority);

    // Collision resolution: mark lower-priority labels that overlap higher-priority ones
    const visibleLabels = [];
    for (const lbl of allLabels) {
        let blocked = false;
        for (const placed of visibleLabels) {
            if (labelsOverlap(lbl.box, placed.box)) {
                blocked = true;
                break;
            }
        }
        if (!blocked) {
            visibleLabels.push(lbl);
        }
    }

    // Draw visible labels
    for (const lbl of visibleLabels) {
        const node = lbl.node;
        const isHov = hoveredNode === node;
        const isSel = selectedNode === node;
        const priority = lbl.box.priority;

        if (isHov) {
            ctx.fillStyle = '#ffffff';
        } else if (isSel) {
            ctx.fillStyle = '#4fc3f7';
        } else if (priority >= 3) {
            ctx.fillStyle = 'rgba(230,230,230,0.92)';
        } else if (priority >= 2) {
            ctx.fillStyle = 'rgba(200,200,200,0.75)';
        } else {
            ctx.fillStyle = 'rgba(180,180,180,0.55)';
        }
        ctx.font = `${lbl.fontSize}px Courier New`;
        ctx.textAlign = 'center';
        ctx.fillText(node.name, node.x, lbl.y);
    }

// Center marker (Federation core) — skip in spatial mode, Sol Prime rendered as sector marker
if (!spatialMode) {
    const cx = W / 2, cy = H / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
  ctx.fillStyle = '#4fc3f7';
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx, cy, 12 + pulse * 4, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(79,195,247,0.2)';
  ctx.lineWidth = 1;
  ctx.stroke();
}

  ctx.restore();
  requestAnimationFrame(draw);
}

// hex color to rgba string
function hexToRgba(hex, alpha) {
  let c = hex.replace('#', '');
  if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
  const num = parseInt(c, 16);
  const r = (num >> 16) & 0xff;
  const g = (num >> 8) & 0xff;
  const b = num & 0xff;
  return `rgba(${r},${g},${b},${alpha})`;
}

function lighten(hex, amt) {
  let c = hex.replace('#', '');
  if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
  const num = parseInt(c, 16);
  let r = Math.min(255, ((num >> 16) & 0xff) + amt);
  let g = Math.min(255, ((num >> 8) & 0xff) + amt);
  let b = Math.min(255, (num & 0xff) + amt);
  return `rgb(${r},${g},${b})`;
}

// --- Interaction ---
function screenToWorld(sx, sy) {
  return { x: (sx - panX) / zoom, y: (sy - panY) / zoom };
}

function getNodeAt(sx, sy) {
  const {x, y} = screenToWorld(sx, sy);
  // Check NPC nodes first (they're on top)
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const dx = x - n.x, dy = y - n.y;
    if (dx*dx + dy*dy < (n.radius + 10) * (n.radius + 10)) return n;
  }
  // SPATIAL-03: Also check sector markers
  if (spatialMode) {
    for (let i = spatialSectorNodes.length - 1; i >= 0; i--) {
      const sn = spatialSectorNodes[i];
      const dx = x - sn.x, dy = y - sn.y;
      if (dx*dx + dy*dy < (sn.radius + 12) * (sn.radius + 12)) return sn;
    }
  }
  return null;
}

      function onMouseMove(e) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (dragging) {
    panX = panStartX + (e.clientX - dragStartX);
    panY = panStartY + (e.clientY - dragStartY);
    return;
  }

  const node = getNodeAt(mx, my);
  hoveredNode = node;

  // Check faction zone hover (only if not hovering an NPC/sector)
  if (!node) {
    const zone = getFactionZoneAt(mx, my);
    hoveredFaction = zone ? zone.fid : null;
    if (zone) {
      showFactionTip(zone, mx, my);
      canvas.style.cursor = 'pointer';
    } else {
      hideFactionTip();
      canvas.style.cursor = 'grab';
    }
  } else {
    hoveredFaction = null;
    hideFactionTip();
    canvas.style.cursor = 'pointer';
  }
}

function onMouseDown(e) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const node = getNodeAt(mx, my);
  if (!node) {
    dragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    panStartX = panX;
    panStartY = panY;
    canvas.style.cursor = 'grabbing';
  }
}

function onMouseUp(e) {
  dragging = false;
  canvas.style.cursor = hoveredNode ? 'pointer' : 'grab';
}

function onWheel(e) {
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  zoom = Math.max(0.3, Math.min(4, zoom * delta));
}

      function onClick(e) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const node = getNodeAt(mx, my);
  if (node) {
    selectedNode = node;
    // SPATIAL-03A: If clicking an NPC, select their faction for isolation
    if (node.faction && spatialMode) {
      selectedFaction = node.faction;
    } else if (node.sectorData && node.ownerFaction && spatialMode) {
      // Clicking a sector node: select its owning faction
      selectedFaction = node.ownerFaction;
    }
    showDetail(node);
  } else {
    // SPATIAL-03A: Check if clicking a faction zone
    const zone = getFactionZoneAt(mx, my);
    if (zone && spatialMode) {
      // Select this faction — isolate it
      if (selectedFaction === zone.fid) {
        // Clicking same faction again: deselect
        selectedFaction = null;
        selectedNode = null;
      } else {
        selectedFaction = zone.fid;
        selectedNode = null;
      }
    } else {
      // Clicking empty space: deselect everything
      selectedFaction = null;
      selectedNode = null;
      showDetail(null);
    }
  }
}

function onDblClick(e) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const node = getNodeAt(mx, my);
  if (node) {
    panX = W/2 - node.x * zoom;
    panY = H/2 - node.y * zoom;
    zoom = 2;
  }
}

function showDetail(node) {
  const panel = document.getElementById('detail');
  if (!node) { panel.classList.remove('show'); return; }

  // SPATIAL-03: Handle sector node clicks
  if (node.sectorData) {
    panel.classList.add('show');
    document.getElementById('detail-name').textContent = node.name;
    document.getElementById('detail-cat').textContent = 'SECTOR · ' + node.regionType.toUpperCase();
    const sd = node.sectorData;
    let rows = '';
    if (node.ownerFaction) rows += `<div id="detail-row"><span class="dl">Faction</span><span class="dv" style="color:${node.color}">${FACTION_DISPLAY[node.ownerFaction] || node.ownerFaction}</span></div>`;
    rows += `<div id="detail-row"><span class="dl">Region</span><span class="dv">${sd.region_type || 'unknown'}</span></div>`;
    rows += `<div id="detail-row"><span class="dl">Resources</span><span class="dv">${sd.resource_profile || 'unknown'}</span></div>`;
    rows += `<div id="detail-row"><span class="dl">Danger</span><span class="dv">${sd.danger_level != null ? sd.danger_level : '?'}</span></div>`;
    if (sd.description) rows += `<div id="detail-row"><span class="dl">Info</span><span class="dv">${sd.description}</span></div>`;
    const adj = (sd.adjacent_sector_ids || []).join(', ');
    if (adj) rows += `<div id="detail-row"><span class="dl">Adjacent</span><span class="dv">${adj}</span></div>`;
    document.getElementById('detail-rows').innerHTML = rows;
    document.getElementById('detail-thought').textContent = '';
    document.getElementById('detail-lore-toggle').style.display = 'none';
    document.getElementById('detail-lore').style.display = 'none';
    return;
  }

  panel.classList.add('show');
  document.getElementById('detail-name').textContent = node.name;
  const factionLabel = node.faction ? ' · ' + (FACTION_DISPLAY[node.faction] || node.faction.replace(/_/g,' ')).toUpperCase() : '';
  // SPATIAL-03: Show sector info if available
  const sectorLabel = node.sectorId ? ' · ' + node.sectorId.toUpperCase() : '';
  document.getElementById('detail-cat').textContent = node.category.replace(/_/g,' ').toUpperCase() + factionLabel + sectorLabel;

    const npc = node.npc;
    let rows = '';
    if (npc.affiliation) rows += `<div id="detail-row"><span class="dl">Faction</span><span class="dv" style="color:${node.factionColor || '#4fc3f7'}">${FACTION_DISPLAY[npc.affiliation] || npc.affiliation}</span></div>`;
    if (npc.mood) rows += `<div id="detail-row"><span class="dl">Mood</span><span class="dv" style="color:${node.color}">${npc.mood}</span></div>`;
    if (npc.goal) rows += `<div id="detail-row"><span class="dl">Goal</span><span class="dv">${npc.goal}</span></div>`;
    if (npc.latest_decision) rows += `<div id="detail-row"><span class="dl">Decision</span><span class="dv">${npc.latest_decision}</span></div>`;
    if (npc.latest_action) rows += `<div id="detail-row"><span class="dl">Action</span><span class="dv">${npc.latest_action}</span></div>`;
    if (npc.action_type) rows += `<div id="detail-row"><span class="dl">Type</span><span class="dv">${npc.action_type}</span></div>`;
    document.getElementById('detail-rows').innerHTML = rows;
    document.getElementById('detail-thought').textContent = npc.latest_thought || '';

    // Lore section — expandable backstory
    const loreToggle = document.getElementById('detail-lore-toggle');
    const loreDiv = document.getElementById('detail-lore');
    if (npc.lore) {
        loreToggle.style.display = 'block';
        loreDiv.textContent = npc.lore;
        loreDiv.style.display = 'none';
        loreToggle.innerHTML = '&#x1F4D6; Lore &#x25B8;';
        loreOpen = false;
    } else {
        loreToggle.style.display = 'none';
        loreDiv.textContent = '';
        loreDiv.style.display = 'none';
        loreOpen = false;
    }

    // Live Sim link — opens simulation.html focused on this NPC's faction
    const liveSimLink = document.getElementById('detail-livesim');
    if (node.faction) {
        liveSimLink.href = `/simulation.html?faction=${encodeURIComponent(node.faction)}&npc=${encodeURIComponent(node.id)}`;
        liveSimLink.style.display = 'block';
    } else {
        liveSimLink.href = `/simulation.html?npc=${encodeURIComponent(node.id)}`;
        liveSimLink.style.display = 'block';
    }
}

let loreOpen = false;
function toggleLore() {
    const loreDiv = document.getElementById('detail-lore');
    const loreToggle = document.getElementById('detail-lore-toggle');
    loreOpen = !loreOpen;
    if (loreOpen) {
        loreDiv.style.display = 'block';
        loreToggle.innerHTML = '&#x1F4D6; Lore &#x25BE;';
    } else {
        loreDiv.style.display = 'none';
        loreToggle.innerHTML = '&#x1F4D6; Lore &#x25B8;';
    }
}

function onSearch(e) {
  const q = e.target.value.toLowerCase().trim();
  if (!q) { selectedNode = null; showDetail(null); return; }
  const found = nodes.find(n => n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
  if (found) {
    selectedNode = found;
    showDetail(found);
    panX = W/2 - found.x * zoom;
    panY = H/2 - found.y * zoom;
  }
}

// --- Audio toggle ---
let isMuted = localStorage.getItem('federation-muted') === 'true';

function toggleMute() {
  isMuted = !isMuted;
  localStorage.setItem('federation-muted', isMuted);
  const btn = document.getElementById('audio-toggle');
  if (isMuted) {
    btn.classList.add('muted');
    btn.setAttribute('aria-label', 'Audio muted — click to unmute');
  } else {
    btn.classList.remove('muted');
    btn.setAttribute('aria-label', 'Audio on — click to mute');
  }
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'm' || e.key === 'M') { toggleMute(); e.preventDefault(); }
});

const audioBtn = document.getElementById('audio-toggle');
if (isMuted) {
  audioBtn.classList.add('muted');
  audioBtn.setAttribute('aria-label', 'Audio muted — click to unmute');
} else {
  audioBtn.setAttribute('aria-label', 'Audio on — click to mute');
}
audioBtn.addEventListener('click', function(e) { e.stopPropagation(); toggleMute(); });

// --- Help overlay toggle ---
function toggleHelp() {
  const overlay = document.getElementById('help-overlay');
  overlay.classList.toggle('open');
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const overlay = document.getElementById('help-overlay');
    if (overlay) overlay.classList.remove('open');
  }
});

/* ═══ STARMAP READABILITY MODE ═══ */
var rmLabelSize = 14;
var rmFocusFactionId = null;

function toggleStarmapReadableMode() {
  var on = document.body.classList.toggle('readable-mode');
  var btn = document.getElementById('rm-smap-toggle');
  if (btn) btn.classList.toggle('on', on);

  var labelSizeDiv = document.getElementById('rm-label-size');
  var focusBtn = document.getElementById('rm-focus-faction');
  if (labelSizeDiv) labelSizeDiv.style.display = on ? 'flex' : 'none';
  if (focusBtn) focusBtn.style.display = on ? 'block' : 'none';

  if (on) {
    setLabelPreset('normal');
    if (labelMode !== 'important') setLabelMode('important');
  }
  draw();

  try { localStorage.setItem('fed_smap_readable', on ? 'true' : 'false'); } catch(e) {}
}

function setLabelPreset(preset) {
  var val = 14;
  if (preset === 'small') val = 10;
  else if (preset === 'normal') val = 14;
  else if (preset === 'large') val = 20;

  document.querySelectorAll('.rm-label-preset').forEach(function(b) {
    b.classList.toggle('active', b.dataset.preset === preset);
  });

  var range = document.getElementById('rm-label-range');
  if (range) range.value = val;

  setLabelSize(val);
}

function setLabelSize(val) {
  rmLabelSize = parseInt(val) || 14;
  draw();
}

function toggleFocusFaction() {
  if (!selectedNode) {
    var factions = mapData ? (mapData.factions || {}) : {};
    var keys = Object.keys(factions);
    if (keys.length > 0) {
      rmFocusFactionId = keys[0];
    } else {
      return;
    }
  } else {
    var node = mapData ? (mapData.nodes || []).find(function(n) { return n.id === selectedNode; }) : null;
    if (node && node.faction_id) {
      rmFocusFactionId = rmFocusFactionId === node.faction_id ? null : node.faction_id;
    } else {
      rmFocusFactionId = null;
    }
  }

  var btn = document.getElementById('rm-focus-faction');
  if (btn) {
    if (rmFocusFactionId) {
      btn.classList.add('active');
      btn.innerHTML = '&#x1F513; Focus: ' + (FACTION_DISPLAY[rmFocusFactionId] || rmFocusFactionId);
    } else {
      btn.classList.remove('active');
      btn.innerHTML = '&#x1F50D; Focus Selected Faction';
    }
  }

  draw();
}

function initStarmapReadableMode() {
  try {
    var spatialSaved = localStorage.getItem('fed_smap_spatial');
    if (spatialSaved === 'true') _spatialModeEverActivated = true;
    var saved = localStorage.getItem('fed_smap_readable');
    if (saved === 'true') {
      toggleStarmapReadableMode();
    }
  } catch(e) {}
}

// --- Start ---
init();

/* ═══ AI ASSISTANT CHAT ═══ */
var aiChatHistory = [];
var aiChatBusy = false;

function aiChatRender() {
  var el = document.getElementById("ai-chat-messages");
  if (!el) return;
  var html = "";
  for (var i = 0; i < aiChatHistory.length; i++) {
    var m = aiChatHistory[i];
    if (m.role === "user") {
      html += '<div class="ai-chat-msg user">' + esc(m.text) + '</div>';
    } else if (m.role === "thinking") {
      html += '<div class="ai-chat-msg thinking">Analyzing sector data...</div>';
    } else if (m.role === "assistant") {
      var prov = m.provider ? '<span class="ai-provider">' + esc(m.provider) + '</span>' : '';
      html += '<div class="ai-chat-msg assistant">' + md(m.text) + prov + '</div>';
    } else if (m.role === "error") {
      html += '<div class="ai-chat-msg error">' + esc(m.text) + '</div>';
    }
  }
  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

function aiChatAsk(text) {
  var input = document.getElementById("ai-chat-input");
  if (input) input.value = text;
  aiChatSend();
}

async function aiChatSend() {
  if (aiChatBusy) return;
  var input = document.getElementById("ai-chat-input");
  if (!input) return;
  var question = input.value.trim();
  if (!question) return;
  input.value = "";
  aiChatBusy = true;
  var btn = document.getElementById("ai-chat-send");
  if (btn) btn.disabled = true;

  aiChatHistory.push({role: "user", text: question});
  aiChatHistory.push({role: "thinking"});
  aiChatRender();

  try {
    const data = await fedFetch('mapAssistant', "/map/assistant", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify({question: question}),
      timeout: 15000
    });
    if (!data) return;

    aiChatHistory = aiChatHistory.filter(function(m){ return m.role !== "thinking"; });

    if (data.status === "ok") {
      aiChatHistory.push({
        role: "assistant",
        text: data.answer || "No answer returned.",
        provider: data.provider || ""
      });
    } else {
      aiChatHistory.push({
        role: "error",
        text: data.answer || "The intelligence systems are offline."
      });
    }
  } catch (e) {
    aiChatHistory = aiChatHistory.filter(function(m){ return m.role !== "thinking"; });
    aiChatHistory.push({
      role: "error",
      text: "Connection failed. The simulation may be offline."
    });
  }

  aiChatBusy = false;
  if (btn) btn.disabled = false;
  aiChatRender();
}

// Galaxy Narrative Feed — stub (orphaned block removed; needs proper function wrapper if re-implemented)

// Astral Mode Toggle
function toggleAstroMode() {
  astroMode = !astroMode;
  document.body.classList.toggle('galaxy-mode-astral', astroMode);
  const btn = document.getElementById('astro-mode-toggle');
  btn.style.opacity = astroMode ? '1' : '0.4';
}

// Ensure on-load defaults
if (astroMode) {
  document.body.classList.add('galaxy-mode-astral');
}

// Enter key to send
(function(){
  var input = document.getElementById("ai-chat-input");
  if (input) {
    input.addEventListener("keydown", function(e){
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); aiChatSend(); }
    });
  }
})();
