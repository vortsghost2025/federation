// ════════════════════════════════════════════════════════════════════════════
// Federation Galaxy Map — frontend/galaxy-map.js
// ════════════════════════════════════════════════════════════════════════════
//
// Internal section structure (per spec §10 deliverable #2). Designed so v2
// can split each section into its own module file without rewriting.
//
//   §0  RUNTIME               scene/camera/renderer/lights (hoisted first)
//   §1  DATA / STATE          fetch /map/data, error tracking, world tick
//   §2  COORDINATE TRANSFORM  sector (x,y) → world XYZ
//   §3  BACKDROP              starfield (GPU drift) + nebulae + milky-way
//   §4  SECTORS               sphere meshes, region hue, danger scale
//   §5  TERRITORY INFLUENCE   per-faction influence volumes + contested blend
//   §6  NPCs / TRAILS         instanced markers, rolling trails, patrol loops
//   §7  MAP MODES             4 v1 modes (Universe/Territory/NPC/Exploration)
//   §8  SEMANTIC ZOOM         3 v1 levels (Galaxy/Region/Sector), extensible
//   §9  INTERACTION           raycaster, click, hover, detail panel
//   §10 CAMERA                OrbitControls + level transitions
//   §11 ANIMATION LOOP        fixed clock order (delta BEFORE elapsed)
// ════════════════════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ════════════════════════════════════════════════════════════════════════════
// §0  RUNTIME — scene/camera/renderer/lights (hoisted so §3-§6 can use them)
// ════════════════════════════════════════════════════════════════════════════
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x020510);
scene.fog = new THREE.FogExp2(0x030818, 0.0028);

const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 2000);
camera.position.set(0, 120, 180);
camera.lookAt(0, 0, 0);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.minDistance = 8;
controls.maxDistance = 600;
controls.target.set(0, 0, 0);

const ambient = new THREE.AmbientLight(0x334466, 0.6);
scene.add(ambient);
const keyLight = new THREE.DirectionalLight(0xffffff, 0.4);
keyLight.position.set(5, 10, 7);
scene.add(keyLight);

let cameraTargetAnim = null; // {pos, look, t}

// ═══ CONSTANTS ═════════════════════════════════════════════════════════════
// SCALE = 0.4 makes fixture sectors span ~100 world units, so the simulation
// occupies a huge navigable volume instead of a tiny knot. Faction homes are
// ~30-60 world units apart, travel distances feel meaningful, and new sectors
// can be added farther out without colliding.
const SCALE = 0.4;
const REGION_COLORS = {
  core:      '#4fc3f7',
  inner:     '#66bb6a',
  outer:     '#ffa726',
  frontier:  '#ef5350'
};
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
const CATEGORY_COLORS = {
  companion: '#ffd700',
  rival:     '#ef5350',
  neutral:   '#78909c',
  enigma:    '#ab47bc',
  unknown:   '#546e7a'
};

// Discovery state order (used for line opacity in Exploration mode)
const DISCOVERY_OPACITY = {
  undiscovered:    0.0,
  detected:        0.25,
  contacted:       0.55,
  relations_open:  1.0
};

// ════════════════════════════════════════════════════════════════════════════
// §1  DATA / STATE
// ════════════════════════════════════════════════════════════════════════════
const liveState = {
  raw: null,                       // last raw /map/data response
  worldState: {},                  // world_state hash
  sectors: [],                     // Sector[]
  sectorById: {},                  // id → Sector
  factions: {},                    // {fid: faction data}
  npcs: [],                        // enriched NPC roster
  npcById: {},                     // id → NPC entry
  territories: [],                 // FactionTerritory[]
  territoriesBySector: {},         // sectorId → FactionTerritory[]
  territoriesByFaction: {},        // fid → FactionTerritory[]
  npcLocations: [],                // NpcLocation[]
  npcLocByNpc: {},                 // npcId → NpcLocation
  discoveries: [],                 // WorldDiscovery[]
  worker: {},                      // worker:status
  tickCount: 0,
  consecutiveFailures: 0,
  spatialEnabled: false
};

const tickDot = document.getElementById('tick-dot');
const tickLabel = document.getElementById('tick-label');
function setTickStatus(state) {
  if (state === 'live') {
    tickDot.style.background = '#4caf50';
    tickDot.style.boxShadow = '0 0 6px #4caf50';
  } else if (state === 'reconnecting') {
    tickDot.style.background = '#ef5350';
    tickDot.style.boxShadow = '0 0 6px #ef5350';
  } else {
    tickDot.style.background = '#ffa726';
    tickDot.style.boxShadow = '0 0 6px #ffa726';
  }
}

async function pollData() {
  const url = '/map/data';
  try {
    const res = await fetch(url);
    updateDiag('status', res.ok ? 'OK ' + res.status : 'FAIL ' + res.status, res.ok);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const text = await res.text();
    updateDiag('bytes', String(text.length).toLocaleString(), true);
    const data = JSON.parse(text);

    // MOCK envelope detection — surface loud banner so this can never be
    // confused with live Federation state.
    if (data && data._mock && data._mock.active) {
      document.getElementById('mock-banner').classList.add('show');
    }

    ingest(data);
    updateDiagCounts(data);
    liveState.consecutiveFailures = 0;
    setTickStatus('live');
  } catch (e) {
    updateDiag('status', 'ERR ' + e.message, false);
    liveState.consecutiveFailures++;
    if (liveState.consecutiveFailures >= 3) {
      setTickStatus('reconnecting');
      tickLabel.textContent = 'RECONNECTING (' + liveState.consecutiveFailures + ')';
    } else if (liveState.consecutiveFailures === 1) {
      setTickStatus('connecting');
      tickLabel.textContent = 'RETRYING...';
    }
  }
}

function updateDiag(field, val, ok) {
  const el = document.getElementById('d-' + field);
  if (!el) return;
  el.textContent = val;
  el.classList.remove('good', 'bad');
  if (ok === true) el.classList.add('good');
  else if (ok === false) el.classList.add('bad');
}

function updateDiagCounts(d) {
  document.getElementById('d-sectors').textContent = (d.sectors || []).length;
  document.getElementById('d-factions').textContent = Object.keys(d.factions || {}).length;
  document.getElementById('d-terr').textContent = (d.faction_territories || []).length;
  document.getElementById('d-npcs').textContent = (d.npcs || []).length;
  document.getElementById('d-npclocs').textContent = (d.npc_locations || []).length;
  document.getElementById('d-disc').textContent = (d.discoveries || []).length;
  document.getElementById('d-tick').textContent = (d.worker || {}).tick_count || '—';
  document.getElementById('diag-panel').classList.add('show');
}

function ingest(data) {
  liveState.raw = data;
  liveState.worldState = data.world_state || {};
  liveState.worker = data.worker || {};
  liveState.tickCount = (data.worker && data.worker.tick_count) || liveState.tickCount;
  tickLabel.textContent = 'TICK ' + liveState.tickCount;

  // Spatial data
  liveState.spatialEnabled = data.spatial_rendering_enabled !== false;
  liveState.sectors = data.sectors || [];
  liveState.sectorById = {};
  for (const s of liveState.sectors) liveState.sectorById[s.id] = s;

  liveState.territories = data.faction_territories || [];
  liveState.territoriesBySector = {};
  liveState.territoriesByFaction = {};
  for (const t of liveState.territories) {
    (liveState.territoriesBySector[t.sector_id] = liveState.territoriesBySector[t.sector_id] || []).push(t);
    (liveState.territoriesByFaction[t.faction_id] = liveState.territoriesByFaction[t.faction_id] || []).push(t);
  }

  liveState.npcLocations = data.npc_locations || [];
  liveState.npcLocByNpc = {};
  for (const loc of liveState.npcLocations) liveState.npcLocByNpc[loc.npc_id] = loc;

  liveState.factions = data.factions || {};
  liveState.npcs = data.npcs || [];
  liveState.npcById = {};
  for (const n of liveState.npcs) liveState.npcById[n.id] = n;

  liveState.discoveries = data.discoveries || [];

  // HUD gauges
  const ws = liveState.worldState;
  const setGauge = (id, key) => {
    const v = Math.max(0, Math.min(100, ws[key] || 0));
    const el = document.getElementById(id);
    if (el) el.style.width = v + '%';
  };
  setGauge('g-tension', 'tension_level');
  setGauge('g-stability', 'stability');
  setGauge('g-morale', 'morale');
  setGauge('g-anomaly', 'anomaly_activity');

  // Rebuild layers that depend on data
  if (liveState.spatialEnabled && liveState.sectors.length) {
    buildSectors();
    buildTerritoryVolumes();
    buildFactionArcs();
    buildNpcMarkers();
    buildNpcAggregates();
    buildFrontierMarkers();
    buildDiscoveryLines();
    buildAdjacencyEdges();
    fitToGalaxy();
  }
}

pollData();
setInterval(pollData, 3000);

// ════════════════════════════════════════════════════════════════════════════
// §2  COORDINATE TRANSFORM
// ════════════════════════════════════════════════════════════════════════════
//   worldX =  sector.x  * SCALE
//   worldY =  0
//   worldZ = -sector.y  * SCALE
function sectorToWorld(sector, out) {
  const v = out || new THREE.Vector3();
  v.set(sector.x * SCALE, 0, -sector.y * SCALE);
  return v;
}

// ════════════════════════════════════════════════════════════════════════════
// §3  BACKDROP — starfield (GPU drift) + nebula planes + milky-way band
// ════════════════════════════════════════════════════════════════════════════

// Shared star shader (used by starfield; each particle has aZnorm for redshift coloring)
const starVert = `
attribute float aSize;
attribute float aAlpha;
attribute float aZnorm;
attribute float aSeed;
uniform float uTime;
varying float vAlpha;
varying float vZnorm;
void main(){
  vAlpha = aAlpha;
  vZnorm = aZnorm;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = aSize * (180.0 / (-mv.z));
  gl_PointSize = max(gl_PointSize, 0.5);
  gl_Position = projectionMatrix * mv;
}`;
const starFrag = `
varying float vAlpha;
varying float vZnorm;
vec3 zColor(float z){
  if(z < 0.25) return mix(vec3(0.6,0.7,1.0), vec3(0.3,0.9,0.9), z*4.0);
  if(z < 0.5)  return mix(vec3(0.3,0.9,0.9), vec3(1.0,0.9,0.3), (z-0.25)*4.0);
  if(z < 0.75) return mix(vec3(1.0,0.9,0.3), vec3(1.0,0.4,0.1), (z-0.5)*4.0);
  return mix(vec3(1.0,0.4,0.1), vec3(0.8,0.15,0.4), (z-0.75)*4.0);
}
void main(){
  float d = length(gl_PointCoord - vec2(0.5));
  if(d > 0.5) discard;
  float g = smoothstep(0.5, 0.0, d);
  vec3 c = zColor(vZnorm);
  gl_FragColor = vec4(c, vAlpha * g);
}`;

const nebVert = `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const nebFrag = `
uniform float uTime;
uniform float uSeed;
varying vec2 vUv;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(h(i), h(i+vec2(1,0)), f.x), mix(h(i+vec2(0,1)), h(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float v=0.0; float a=0.5;
  for(int i=0;i<5;i++){ v += a*n(p); p *= 2.1; a *= 0.5; } return v; }
void main(){
  vec2 uv = vUv + vec2(uTime*0.008, uTime*0.005);
  float f = fbm(uv*2.5 + uSeed);
  vec3 deep = vec3(0.06, 0.01, 0.12);
  vec3 hot  = vec3(0.6, 0.25, 0.05);
  vec3 c = mix(deep, hot, f);
  // Radial alpha falloff so plane edges are invisible — NO rectangular silhouette
  float r = length(vUv - vec2(0.5)) * 2.0;
  float radial = smoothstep(1.0, 0.2, r);
  float a = smoothstep(0.2, 0.6, f) * 0.10 * radial;
  gl_FragColor = vec4(c, a);
}`;

// Milky-Way band: a wide ribbon across the map plane
const milkyVert = `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const milkyFrag = `
varying vec2 vUv;
float h(vec2 p){ return fract(sin(dot(p, vec2(91.3, 47.7))) * 28371.3); }
float n(vec2 p){ vec2 i=floor(p); vec2 f=fract(p); f=f*f*(3.0-2.0*f);
return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float v=0.0; float a=0.5;
for(int i=0;i<4;i++){ v += a*n(p); p *= 2.3; a *= 0.5; } return v; }
void main(){
float d = abs(vUv.y - 0.5) * 2.0;
float band = smoothstep(1.0, 0.0, d);
float n = fbm(vUv * vec2(4.0, 18.0));
vec3 c = mix(vec3(0.04, 0.06, 0.14), vec3(0.12, 0.10, 0.22), n);
// Radial falloff so the plane's rectangular edges are invisible
float r = length(vUv - vec2(0.5)) * 2.0;
float radial = smoothstep(1.0, 0.25, r);
gl_FragColor = vec4(c, band * 0.45 * radial);
}`;

// ════════════════════════════════════════════════════════════════════════════
// §4  SECTORS
// ════════════════════════════════════════════════════════════════════════════
const sectorMeshes = [];           // [{mesh, data, group, regionType}]
const sectorMeshById = {};
let sectorGroup;

// Shared cluster shader — uses aSize to scale gl_PointSize, with depth-based
// size attenuation AND a screen-space minimum so faction home cores stay
// readable even when the camera is at Galaxy zoom (~200 units away).

// Cached radial sprite texture — generated once, reused for all faction home sprites
const _radialSpriteCache = {};
function makeRadialSpriteTexture(color) {
  const key = color.getHexString();
  if (_radialSpriteCache[key]) return _radialSpriteCache[key];
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cx = size / 2, cy = size / 2;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, size / 2);
  const hex = '#' + key;
  grad.addColorStop(0.0, hex);
  grad.addColorStop(0.2, hex + 'cc');
  grad.addColorStop(0.5, hex + '33');
  grad.addColorStop(1.0, hex + '00');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  _radialSpriteCache[key] = tex;
  return tex;
}
const clusterVert = `
attribute float aSize;
attribute float aAlpha;
attribute vec3 aColor;
uniform float uTime;
uniform float uMinPx;  // screen-space minimum pixel size for core points
varying float vAlpha;
varying vec3 vColor;
void main(){
  vAlpha = aAlpha;
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float distFactor = 90.0 / max(-mv.z, 1.0);
  float ps = aSize * distFactor;
  // Core points (aSize > 10) get a guaranteed minimum screen size so they
  // remain visible at Galaxy zoom. Surrounding small stars scale normally.
  float isCore = step(10.0, aSize);
  ps = max(ps, isCore * uMinPx);
  gl_PointSize = max(ps, 0.5);
  gl_Position = projectionMatrix * mv;
}`;
const clusterFrag = `
varying float vAlpha;
varying vec3 vColor;
void main(){
  float d = length(gl_PointCoord - vec2(0.5));
  if(d > 0.5) discard;
  float g = smoothstep(0.5, 0.0, d);
  gl_FragColor = vec4(vColor, vAlpha * g);
}`;

function buildSectors() {
  if (sectorGroup) {
    scene.remove(sectorGroup);
    sectorGroup.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
  }
  sectorGroup = new THREE.Group();
  scene.add(sectorGroup);
  sectorMeshes.length = 0;
  for (const k in sectorMeshById) delete sectorMeshById[k];

  for (const s of liveState.sectors) {
    const regionColor = new THREE.Color(REGION_COLORS[s.region_type] || '#9e9e9e');
    const terrList = liveState.territoriesBySector[s.id] || [];
    const isHome = terrList.some(t => t.claim_type === 'home');
    const homeFaction = isHome ? terrList.find(t => t.claim_type === 'home').faction_id : null;
    const homeColor = homeFaction && liveState.factions[homeFaction]
      ? new THREE.Color(liveState.factions[homeFaction].color)
      : regionColor;

    // Procedural star cluster: 1 bright core + 20-80 small stars in 3D
    const N = 30 + Math.floor(Math.random() * 50);
    const positions = new Float32Array(N * 3);
    const sizes = new Float32Array(N);
    const alphas = new Float32Array(N);
    const colors = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      if (i === 0) {
        positions[i*3] = 0;
        positions[i*3+1] = 0;
        positions[i*3+2] = 0;
        sizes[i] = 12.0;
        alphas[i] = 1.0;
      } else {
        // Cluster radius scaled by importance (home larger, contested denser)
        const r = 0.6 + Math.random() * (isHome ? 2.5 : 1.6);
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        positions[i*3]   = Math.sin(phi) * Math.cos(theta) * r;
        positions[i*3+1] = (Math.random() - 0.5) * (isHome ? 1.2 : 0.8);  // depth spread
        positions[i*3+2] = Math.cos(phi) * r;
        sizes[i] = 1.5 + Math.random() * 3.0;
        alphas[i] = 0.4 + Math.random() * 0.6;
      }
      // Color: slight hue bias toward region/faction but mostly white star
      const white = 0.85 + Math.random() * 0.15;
      colors[i*3]   = white * regionColor.r;
      colors[i*3+1] = white * regionColor.g;
      colors[i*3+2] = white * regionColor.b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geo.setAttribute('aAlpha', new THREE.BufferAttribute(alphas, 1));
    geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.ShaderMaterial({
      vertexShader: clusterVert,
      fragmentShader: clusterFrag,
      uniforms: {
        uTime: { value: 0 },
        uMinPx: { value: isHome ? 10.0 : 6.0 }
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const points = new THREE.Points(geo, mat);
    sectorToWorld(s, points.position);
    points.userData = { sectorId: s.id, data: s, baseEmissive: 0.4, isHome, homeFaction };

    // Faction home ring — thin, additive, only on home sectors
    if (isHome) {
      const ringGeo = new THREE.RingGeometry(2.4, 2.8, 48);
      const ringMat = new THREE.MeshBasicMaterial({
        color: homeColor,
        transparent: true,
        opacity: 0.65,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = -Math.PI / 2;
      points.add(ring);
      points.userData.ring = ring;

      // Billboard sprite — always camera-facing, guaranteed readable size at Galaxy zoom
      const spriteTex = makeRadialSpriteTexture(homeColor);
      const spriteMat = new THREE.SpriteMaterial({
        map: spriteTex,
        color: 0xffffff,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      });
      const sprite = new THREE.Sprite(spriteMat);
      sprite.scale.set(8, 8, 1);
      sprite.position.set(0, 1.5, 0);
      points.add(sprite);
      points.userData.homeSprite = sprite;
    }

    sectorGroup.add(points);
    sectorMeshes.push({ mesh: points, data: s, regionType: s.region_type, isHome, homeFaction, ring: points.userData.ring });
    sectorMeshById[s.id] = points;
  }
  updateSectorEmissive();
}

function updateSectorEmissive() {
  for (const sm of sectorMeshes) {
    const terrList = liveState.territoriesBySector[sm.data.id] || [];
    let bestClaim = 'neutral';
    let bestControl = 0;
    for (const t of terrList) {
      if (t.control_level > bestControl) {
        bestControl = t.control_level;
        bestClaim = t.claim_type;
      }
    }
    let intensity = 0.6;
    if (bestClaim === 'home') intensity = 1.2;
    else if (bestClaim === 'colony') intensity = 0.9;
    else if (bestClaim === 'contested') intensity = 1.4;
    else if (bestClaim === 'occupied') intensity = 1.0;
    // Apply intensity by scaling core alpha attribute on the Points geometry
    const alphas = sm.mesh.geometry.attributes.aAlpha;
    if (alphas) {
      const baseCore = intensity;
      for (let i = 0; i < alphas.count; i++) {
        // Core stays at baseCore, others scale relative
        if (i === 0) alphas.array[0] = Math.min(1.5, baseCore);
        else alphas.array[i] = (0.4 + (i * 13) % 7 / 17) * (0.5 + intensity * 0.5);
      }
      alphas.needsUpdate = true;
    }
    sm.mesh.userData.baseEmissive = intensity;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// §5  TERRITORY INFLUENCE — soft volumetric clouds per faction
// ════════════════════════════════════════════════════════════════════════════
const territoryGroup = new THREE.Group();
territoryGroup.visible = true;  // ENABLED — faction influence haze at Galaxy zoom
scene.add(territoryGroup);
const territoryVolumes = []; // [{mesh, factionId, color}]

const territoryVert = `
varying vec3 vWorldPos;
varying vec2 vUv;
varying float vDistToCenter;
void main(){
  vUv = uv;
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
  vDistToCenter = length(wp.xyz);
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;
// We blend Gaussian-like density falloffs at each sector controlled by the
// faction. Up to 12 anchor points passed as uniform array.
const territoryFrag = `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uTime;
uniform vec3 uAnchors[12];
uniform float uAnchorCount;
uniform float uPulse;
uniform float uSeed;
varying vec3 vWorldPos;
varying vec2 vUv;
varying float vDistToCenter;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p){ vec2 i=floor(p); vec2 f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float v=0.0; float a=0.5;
  for(int i=0;i<4;i++){ v += a*vnoise(p); p *= 2.1; a *= 0.5; } return v; }
void main(){
  // Use MINIMUM distance to any anchor — influence is localized per-sector,
  // not one smooth Gaussian blob across the whole bounding box.
  float minD = 9999.0;
  for(int i = 0; i < 12; i++){
    if(float(i) >= uAnchorCount) break;
    float d = distance(vWorldPos, uAnchors[i]);
    minD = min(minD, d);
  }
  float density = exp(-minD * minD * 0.005);
  // Aggressive noise: creates dark gaps/holes inside influence and irregular edges
  float n = fbm(vWorldPos.xz * 0.05 + uSeed);
  density *= smoothstep(0.15, 0.7, n) * 1.4;
  float pulse = 0.88 + 0.12 * sin(uTime * 0.5 + uPulse);
  // Desaturate faction color with nebular tone — astronomical tint, not HUD paint
  vec3 nebular = vec3(0.18, 0.22, 0.32);
  vec3 base = mix(nebular, uColor, 0.55);
  vec3 c = base * (0.4 + 0.6 * density) * pulse;
  float a = smoothstep(0.0, 0.9, density) * uOpacity;
  // Radial falloff hides plane edges
  float r = length(vUv - vec2(0.5)) * 2.0;
  float radial = smoothstep(1.0, 0.1, r);
  gl_FragColor = vec4(c, a * radial);
}`;

function buildTerritoryVolumes() {
  for (const v of territoryVolumes) {
    territoryGroup.remove(v.mesh);
    if (v.mesh.geometry) v.mesh.geometry.dispose();
    if (v.mesh.material) v.mesh.material.dispose();
  }
  territoryVolumes.length = 0;

  for (const fid of Object.keys(liveState.factions)) {
    const fdata = liveState.factions[fid];
    if (!fdata) continue;
    const territories = liveState.territoriesByFaction[fid] || [];
    if (territories.length === 0) continue;

    const color = new THREE.Color(fdata.color || '#9e9e9e');
    const anchors = [];
    for (const t of territories.slice(0, 12)) {
      const sec = liveState.sectorById[t.sector_id];
      if (sec) anchors.push(new THREE.Vector3(sec.x * SCALE, 0, -sec.y * SCALE));
    }
    if (anchors.length === 0) continue;

    // Bounding region around anchors — minimum-distance field naturally clusters
    // around sectors, so we only need modest padding for the falloff tails.
    const bbox = new THREE.Box3();
    for (const a of anchors) bbox.expandByPoint(a);
    bbox.expandByScalar(22.0);
    const size = new THREE.Vector3();
    bbox.getSize(size);
    const center = new THREE.Vector3();
    bbox.getCenter(center);
    const maxDim = Math.max(size.x, size.z, 40);
    const geo = new THREE.PlaneGeometry(maxDim * 3.0, maxDim * 3.0);
    const uAnchors = new Array(12).fill(0).map((_, i) => anchors[i] || new THREE.Vector3());
    const seed = Math.random() * 100;
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: color },
        uOpacity: { value: 0.55 },
        uTime: { value: 0 },
        uAnchors: { value: uAnchors },
        uAnchorCount: { value: anchors.length },
        uPulse: { value: Math.random() * Math.PI * 2 },
        uSeed: { value: seed }
      },
      vertexShader: territoryVert,
      fragmentShader: territoryFrag,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending
    });
    const m = new THREE.Mesh(geo, mat);
    m.rotation.x = -Math.PI / 2;
    m.position.set(center.x, -0.2, center.z);
    territoryGroup.add(m);
    territoryVolumes.push({ mesh: m, factionId: fid, color, centroid: center });
  }
}

// ════════════════════════════════════════════════════════════════════════════
// §6  NPCs / TRAILS — instanced markers + rolling trail buffers + patrol loops
// ════════════════════════════════════════════════════════════════════════════
const npcGroup = new THREE.Group();
scene.add(npcGroup);
const npcMarkers = []; // [{mesh, data, trail, trailGeo, trailMat, trailPositions}]
const NPC_TRAIL_LEN = 24;

function buildNpcMarkers() {
  for (const m of npcMarkers) {
    npcGroup.remove(m.mesh);
    if (m.trail) npcGroup.remove(m.trail);
    if (m.mesh.geometry) m.mesh.geometry.dispose();
    if (m.mesh.material) m.mesh.material.dispose();
    if (m.trailGeo) m.trailGeo.dispose();
    if (m.trailMat) m.trailMat.dispose();
  }
  npcMarkers.length = 0;

  const baseGeo = new THREE.SphereGeometry(0.45, 8, 6);  // small astronomical NPC marker
  for (const npc of liveState.npcs) {
    const fid = npc.affiliation;
    const fdata = fid ? liveState.factions[fid] : null;
    const baseColor = fdata ? fdata.color : (CATEGORY_COLORS[npc.category] || CATEGORY_COLORS.unknown);
    const color = new THREE.Color(baseColor);
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 });
    const mesh = new THREE.Mesh(baseGeo, mat);
    mesh.userData = { npcId: npc.id, data: npc, factionId: fid };
    npcGroup.add(mesh);

    // Thin trail (rolling buffer)
    const trailPositions = new Float32Array(NPC_TRAIL_LEN * 3);
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3));
    const trailMat = new THREE.LineBasicMaterial({
      color, transparent: true, opacity: 0.35
    });
    const trail = new THREE.Line(trailGeo, trailMat);
    trail.frustumCulled = false;
    npcGroup.add(trail);

    // Curved destination arrow (Line geometry, recomputed each frame in update)
    const arrowPositions = new Float32Array((12 + 1) * 3);
    const arrowGeo = new THREE.BufferGeometry();
    arrowGeo.setAttribute('position', new THREE.BufferAttribute(arrowPositions, 3));
    const arrowMat = new THREE.LineBasicMaterial({
      color, transparent: true, opacity: 0.5
    });
    const arrow = new THREE.Line(arrowGeo, arrowMat);
    arrow.frustumCulled = false;
    arrow.visible = false;
    npcGroup.add(arrow);

    // Pulse dot for destination
    const dotGeo = new THREE.SphereGeometry(0.35, 6, 4);
    const dotMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 });
    const dot = new THREE.Mesh(dotGeo, dotMat);
    dot.visible = false;
    npcGroup.add(dot);

    npcMarkers.push({ mesh, data: npc, trail, trailGeo, trailMat, trailPositions, color, arrow, arrowGeo, arrowMat, dot });
  }
}

// NPC aggregate activity indicators — one per sector with NPCs.
// LOD-scaled sprites so activity is visible at Galaxy zoom.
const npcAggregateGroup = new THREE.Group();
scene.add(npcAggregateGroup);
const npcAggregates = []; // [{sprite, sectorId, count, color}]
function buildNpcAggregates() {
  for (const a of npcAggregates) {
    npcAggregateGroup.remove(a.sprite);
    if (a.sprite.material.map) a.sprite.material.map.dispose();
    if (a.sprite.material) a.sprite.material.dispose();
  }
  npcAggregates.length = 0;

  // Count NPCs per sector
  const bySector = {};
  for (const npc of liveState.npcs) {
    const loc = liveState.npcLocByNpc[npc.id];
    const sid = (loc && loc.sector_id) || npc.sector_id;
    if (!sid) continue;
    bySector[sid] = bySector[sid] || { count: 0, fid: npc.affiliation };
    bySector[sid].count++;
  }
  for (const sid of Object.keys(bySector)) {
    const sec = liveState.sectorById[sid];
    if (!sec) continue;
    const info = bySector[sid];
    const fdata = info.fid ? liveState.factions[info.fid] : null;
    const color = fdata ? new THREE.Color(fdata.color) : new THREE.Color('#78909c');
    const tex = makeRadialSpriteTexture(color);
    const mat = new THREE.SpriteMaterial({
      map: tex,
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const sprite = new THREE.Sprite(mat);
    const wp = sectorToWorld(sec);
    sprite.position.set(wp.x, 0.5, wp.z);
    sprite.scale.set(6, 6, 1);
    npcAggregateGroup.add(sprite);
    npcAggregates.push({ sprite, sectorId: sid, count: info.count, color });
  }
}

// FRONTIER MARKERS — faint outward glow at frontier sectors.
// Distinguishes established space from unexplored frontier at Galaxy zoom.
const frontierGroup = new THREE.Group();
scene.add(frontierGroup);
let frontierMarkers = [];

function buildFrontierMarkers() {
  for (const f of frontierMarkers) {
    frontierGroup.remove(f.sprite);
    if (f.sprite.material.map) f.sprite.material.map.dispose();
    if (f.sprite.material) f.sprite.material.dispose();
  }
  frontierMarkers = [];

  const frontierColor = new THREE.Color('#8db4d8');  // cool blue-white for "unknown"
  for (const s of liveState.sectors) {
    const isFrontier = s.region_type === 'frontier' || (s.danger_level || 0) >= 7;
    if (!isFrontier) continue;
    const tex = makeRadialSpriteTexture(frontierColor);
    const mat = new THREE.SpriteMaterial({
      map: tex,
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const sprite = new THREE.Sprite(mat);
    const wp = sectorToWorld(s);
    sprite.position.set(wp.x, 0.3, wp.z);
    sprite.scale.set(8, 8, 1);
    frontierGroup.add(sprite);
    frontierMarkers.push({ sprite, sectorId: s.id, danger: s.danger_level || 0 });
  }
}

function updateNpcPositions(dt) {
  for (const m of npcMarkers) {
    const npc = m.data;
    const loc = liveState.npcLocByNpc[npc.id];
    const sec = loc ? liveState.sectorById[loc.sector_id] : (npc.sector_id ? liveState.sectorById[npc.sector_id] : null);
    if (!sec) {
      m.mesh.visible = false;
      m.trail.visible = false;
      m.arrow.visible = false;
      continue;
    }
    m.mesh.visible = true;
    m.trail.visible = (currentMode === 'npc' || currentMode === 'exploration');

    let pos = sectorToWorld(sec);
    let destPos = null;
    if (loc) {
      // Apply NPC offset within sector + lerp toward destination if moving
      let ox = (loc.x_offset || 0) * SCALE * 0.5;
      let oz = -(loc.y_offset || 0) * SCALE * 0.5;
      if (loc.destination_sector_id && loc.movement_progress > 0 && loc.movement_progress < 1) {
        const destSec = liveState.sectorById[loc.destination_sector_id];
        if (destSec) {
          destPos = sectorToWorld(destSec);
          pos = pos.clone().lerp(destPos, loc.movement_progress);
        }
      }
      pos.x += ox;
      pos.z += oz;
    }
    m.mesh.position.copy(pos);

    // Pulse rate from current_task
    const task = loc ? loc.current_task : 'garrison';
    const pulseSpeed = task === 'garrison' ? 0.6 : task === 'patrol' ? 1.4 : task === 'expedition' ? 2.2 : 1.0;
    const pulse = 0.7 + 0.3 * Math.sin(clock.elapsedTime * pulseSpeed);
    m.mesh.scale.setScalar(pulse);

    // Trail: rolling buffer
    for (let i = NPC_TRAIL_LEN - 1; i > 0; i--) {
      m.trailPositions[i*3]   = m.trailPositions[(i-1)*3];
      m.trailPositions[i*3+1] = m.trailPositions[(i-1)*3+1];
      m.trailPositions[i*3+2] = m.trailPositions[(i-1)*3+2];
    }
    m.trailPositions[0] = pos.x;
    m.trailPositions[1] = pos.y;
    m.trailPositions[2] = pos.z;
    m.trailGeo.attributes.position.needsUpdate = true;
    m.trailGeo.setDrawRange(0, Math.min(NPC_TRAIL_LEN, (m._trailFilled = (m._trailFilled || 0) + 1)));

    // Destination arrow: curved line from origin sector to destination,
    // with a pulsing dot traveling toward destination.
    if (destPos && (currentMode === 'npc' || currentMode === 'exploration')) {
      const origin = sectorToWorld(sec);
      const segs = 12;
      const dist = origin.distanceTo(destPos);
      const arcHeight = Math.min(12, Math.max(3, dist * 0.15));
      const pos = m.arrowGeo.attributes.position;
      for (let i = 0; i <= segs; i++) {
        const t = i / segs;
        const x = origin.x + (destPos.x - origin.x) * t;
        const z = origin.z + (destPos.z - origin.z) * t;
        const arc = Math.sin(t * Math.PI) * arcHeight;
        pos.array[i*3]   = x;
        pos.array[i*3+1] = arc;
        pos.array[i*3+2] = z;
      }
      pos.needsUpdate = true;
      m.arrowGeo.setDrawRange(0, segs + 1);
      m.arrow.visible = true;
      // Pulse dot traveling along the arc
      const pulseT = (clock.elapsedTime * 0.25) % 1.0;
      const px = origin.x + (destPos.x - origin.x) * pulseT;
      const pz = origin.z + (destPos.z - origin.z) * pulseT;
      const parc = Math.sin(pulseT * Math.PI) * arcHeight;
      m.dot.position.set(px, parc, pz);
      m.dot.visible = true;
    } else {
      m.arrow.visible = false;
      m.dot.visible = false;
    }
  }
}

// ════════════════════════════════════════════════════════════════════════════
// DISCOVERY LINES (Exploration mode)
// ════════════════════════════════════════════════════════════════════════════
// WorldDiscovery is faction-PAIR contact state (undiscovered → detected →
// contacted → relations_open). It is NOT per-sector explored/unexplored
// state. We must NOT mark individual sectors "unexplored" — the backend
// has no such field. Discovery lines connect the home sectors of two
// factions and fade in by contact progression.
const discoveryGroup = new THREE.Group();
scene.add(discoveryGroup);
let discoveryLines = [];

function buildDiscoveryLines() {
  for (const l of discoveryLines) {
    discoveryGroup.remove(l.line);
    if (l.line.geometry) l.line.geometry.dispose();
    if (l.line.material) l.line.material.dispose();
  }
  discoveryLines = [];

  for (const d of liveState.discoveries) {
    const homeA = homeSectorFor(d.faction_a_id);
    const homeB = homeSectorFor(d.faction_b_id);
    if (!homeA || !homeB) continue;
    const a = sectorToWorld(homeA);
    const b = sectorToWorld(homeB);
    const geo = new THREE.BufferGeometry().setFromPoints([a, b]);
    const opacity = DISCOVERY_OPACITY[d.state] || 0;
    if (opacity === 0) continue;
    const fA = liveState.factions[d.faction_a_id];
    const fB = liveState.factions[d.faction_b_id];
    const colA = new THREE.Color((fA && fA.color) || '#9e9e9e');
    const colB = new THREE.Color((fB && fB.color) || '#9e9e9e');
    const mat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity
    });
    const line = new THREE.Line(geo, mat);
    line.visible = (currentMode === 'exploration');
    // Per-vertex colors
    const colors = new Float32Array([colA.r, colA.g, colA.b, colB.r, colB.g, colB.b]);
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    discoveryGroup.add(line);
    discoveryLines.push({ line, state: d.state, opacity });
  }
}

function homeSectorFor(fid) {
  const f = liveState.factions[fid];
  if (!f || !f.home_sector_id) return null;
  return liveState.sectorById[f.home_sector_id];
}

// ════════════════════════════════════════════════════════════════════════════
// ADJACENCY EDGES
// ════════════════════════════════════════════════════════════════════════════
const adjacencyGroup = new THREE.Group();
scene.add(adjacencyGroup);
let adjacencyLines = [];

function buildAdjacencyEdges() {
  for (const l of adjacencyLines) {
    adjacencyGroup.remove(l);
    if (l.geometry) l.geometry.dispose();
    if (l.material) l.material.dispose();
  }
  adjacencyLines = [];

  const seen = new Set();
  for (const s of liveState.sectors) {
    for (const adjId of (s.adjacent_sector_ids || [])) {
      const key = [s.id, adjId].sort().join('::');
      if (seen.has(key)) continue;
      seen.add(key);
      const a = sectorToWorld(s);
      const b = sectorToWorld(liveState.sectorById[adjId]);
      if (!b) continue;
      const geo = new THREE.BufferGeometry().setFromPoints([a, b]);
      const mat = new THREE.LineBasicMaterial({ color: 0x223344, transparent: true, opacity: 0.35 });
      const line = new THREE.Line(geo, mat);
      line.visible = false; // shown only in Network mode (v2) or via interaction
      adjacencyGroup.add(line);
      adjacencyLines.push(line);
    }
  }
}

// ════════════════════════════════════════════════════════════════════════════
// FACTION ROUTE ARCS — luminous arcs from home sector to each controlled sector.
// Visible at Galaxy/Region zoom, hidden at Sector zoom. Gives each faction a
// visible web of presence, not just a point.
// ════════════════════════════════════════════════════════════════════════════
const factionArcsGroup = new THREE.Group();
scene.add(factionArcsGroup);
let factionArcs = [];

function buildFactionArcs() {
  for (const a of factionArcs) {
    factionArcsGroup.remove(a.line);
    if (a.line.geometry) a.line.geometry.dispose();
    if (a.line.material) a.line.material.dispose();
  }
  factionArcs = [];

  for (const fid of Object.keys(liveState.factions)) {
    const fdata = liveState.factions[fid];
    if (!fdata) continue;
    const homeSec = liveState.sectorById[fdata.home_sector_id];
    if (!homeSec) continue;
    const territories = liveState.territoriesByFaction[fid] || [];
    const color = new THREE.Color(fdata.color || '#9e9e9e');
    const homeW = sectorToWorld(homeSec);

    for (const t of territories) {
      if (t.claim_type !== 'home' && t.claim_type !== 'colony') continue;
      const targetSec = liveState.sectorById[t.sector_id];
      if (!targetSec || targetSec.id === homeSec.id) continue;
      const targetW = sectorToWorld(targetSec);
      const dist = homeW.distanceTo(targetW);
      if (dist < 1) continue;
      // Curved arc with proportional lift
      const segs = 16;
      const arcHeight = Math.min(8, dist * 0.08);
      const positions = new Float32Array((segs + 1) * 3);
      for (let i = 0; i <= segs; i++) {
        const tt = i / segs;
        const x = homeW.x + (targetW.x - homeW.x) * tt;
        const z = homeW.z + (targetW.z - homeW.z) * tt;
        const arc = Math.sin(tt * Math.PI) * arcHeight;
        positions[i*3]   = x;
        positions[i*3+1] = arc;
        positions[i*3+2] = z;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const mat = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: t.claim_type === 'home' ? 0.32 : 0.18,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      });
      const line = new THREE.Line(geo, mat);
      line.frustumCulled = false;
      factionArcsGroup.add(line);
      factionArcs.push({ line, fid, targetId: t.sector_id });
    }
  }
}

// ════════════════════════════════════════════════════════════════════════════
// §7  MAP MODES — generic registration, v1 ships 4
// ════════════════════════════════════════════════════════════════════════════
const MODE_REGISTRY = {
  universe: {
    label: 'Universe',
    hotkey: '1',
    apply: () => {
      if (sectorGroup) sectorGroup.visible = true;
      npcGroup.visible = true;
      for (const m of npcMarkers) {
        m.mesh.scale.setScalar(0.7);
        m.mesh.material.opacity = 1.0;
        m.mesh.material.transparent = false;
        m.trail.visible = false;
      }
      for (const l of adjacencyLines) l.visible = false;
      for (const l of discoveryLines) l.visible = false;
    }
  },
  territory: {
    label: 'Territory',
    hotkey: '2',
    apply: () => {
      if (sectorGroup) sectorGroup.visible = true;
      npcGroup.visible = false;
      for (const l of adjacencyLines) l.visible = false;
      for (const l of discoveryLines) l.visible = false;
    }
  },
  npc: {
    label: 'NPC',
    hotkey: '3',
    apply: () => {
      if (sectorGroup) sectorGroup.visible = true;
      npcGroup.visible = true;
      for (const m of npcMarkers) {
        m.mesh.scale.setScalar(1.4);
        m.mesh.material.transparent = true;
        m.mesh.material.opacity = 1.0;
        m.trail.visible = true;
      }
      for (const l of adjacencyLines) {
        l.material.color = new THREE.Color(0x445566);
        l.material.opacity = 0.5;
        l.visible = true;
      }
      for (const l of discoveryLines) l.visible = false;
    }
  },
  exploration: {
    label: 'Exploration',
    hotkey: '4',
    apply: () => {
      if (sectorGroup) sectorGroup.visible = true;
      npcGroup.visible = true;
      for (const m of npcMarkers) {
        m.mesh.scale.setScalar(1.0);
        m.trail.visible = true;
        const loc = liveState.npcLocByNpc[m.data.id];
        const isExpedition = loc && loc.current_task === 'expedition';
        const isPatrol = loc && loc.current_task === 'patrol';
        m.mesh.material.color = isExpedition ? new THREE.Color('#ffeb3b') :
                                 isPatrol ? new THREE.Color('#00bcd4') :
                                 m.color;
      }
      for (const l of discoveryLines) l.visible = true;
      for (const l of adjacencyLines) l.visible = false;
    }
  }
};

let currentMode = 'universe';
function setMode(name) {
  if (!MODE_REGISTRY[name]) return;
  currentMode = name;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === name);
  });
  MODE_REGISTRY[name].apply();
  // Territory haze follows zoom level, not mode — re-apply after mode adjusts
  territoryGroup.visible = (currentZoom !== 'sector');
}

// ════════════════════════════════════════════════════════════════════════════
// §8  SEMANTIC ZOOM — generic registration, v1 ships 3
// ════════════════════════════════════════════════════════════════════════════
const ZOOM_REGISTRY = {
  galaxy: {
    label: 'Galaxy',
    hotkey: 'G',
    cameraOffset: new THREE.Vector3(0, 120, 180),
    maxDistance: 600
  },
  region: {
    label: 'Region',
    hotkey: 'R',
    cameraOffset: new THREE.Vector3(0, 45, 65),
    maxDistance: 250
  },
  sector: {
    label: 'Sector',
    hotkey: 'S',
    cameraOffset: new THREE.Vector3(0, 14, 20),
    maxDistance: 80
  }
};

let currentZoom = 'galaxy';
function setZoom(name, focusSector) {
  if (!ZOOM_REGISTRY[name]) return;
  currentZoom = name;
  document.querySelectorAll('.zoom-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.zoom === name);
  });
  const z = ZOOM_REGISTRY[name];
  controls.maxDistance = z.maxDistance;
  // Faction influence haze + route arcs + frontier markers visible at Galaxy/Region zoom, hidden at Sector zoom
  territoryGroup.visible = (name !== 'sector');
  factionArcsGroup.visible = (name !== 'sector');
  frontierGroup.visible = (name !== 'sector');
  const target = focusSector ? sectorToWorld(focusSector) : fitCenter.clone();
  const camPos = target.clone().add(z.cameraOffset);
  cameraTargetAnim = { pos: camPos, look: target, t: 0 };
  updateDomLabels();
}

const fitCenter = new THREE.Vector3(0, 0, 0);

function fitToGalaxy() {
  if (!liveState.sectors.length) return;
  let minX=Infinity, maxX=-Infinity, minZ=Infinity, maxZ=-Infinity;
  for (const s of liveState.sectors) {
    const w = sectorToWorld(s);
    if (w.x < minX) minX = w.x;
    if (w.x > maxX) maxX = w.x;
    if (w.z < minZ) minZ = w.z;
    if (w.z > maxZ) maxZ = w.z;
  }
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const span = Math.max(maxX - minX, maxZ - minZ);
  fitCenter.set(cx, 0, cz);
  controls.target.copy(fitCenter);
  // Camera distance = 1.0× span ensures entire Federation fits with breathing room
  const dist = span * 1.0;
  camera.position.set(cx, dist * 0.65, cz + dist * 0.85);
}

// ════════════════════════════════════════════════════════════════════════════
// §9  INTERACTION — raycaster, click, hover, detail panel
// ════════════════════════════════════════════════════════════════════════════
const raycaster = new THREE.Raycaster();
const mouseNDC = new THREE.Vector2();
let hoveredMesh = null;
let selectedMesh = null;
let selectedNpcMesh = null;

const panelEl = document.getElementById('panel');
const pName = document.getElementById('p-name');
const pTitle = document.getElementById('p-title');
const pFaction = document.getElementById('p-faction');
const pBody = document.getElementById('p-body');
const pControl = document.getElementById('p-control');
const pThought = document.getElementById('p-thought');

function closePanel() {
  panelEl.classList.remove('show');
  if (selectedMesh) {
    selectedMesh.material.emissiveIntensity = selectedMesh.userData.baseEmissive || 0.4;
    selectedMesh = null;
  }
  selectedNpcMesh = null;
}
document.getElementById('panel-close').addEventListener('click', closePanel);
window.closePanel = closePanel;

function setMouseFromEvent(e) {
  const rect = canvas.getBoundingClientRect();
  mouseNDC.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  mouseNDC.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
}

function pickAtMouse() {
  setMouseFromFromLast();
  raycaster.setFromCamera(mouseNDC, camera);
  const targets = [];
  for (const sm of sectorMeshes) targets.push(sm.mesh);
  for (const m of npcMarkers) targets.push(m.mesh);
  const hits = raycaster.intersectObjects(targets, false);
  return hits[0] || null;
}
function setMouseFromFromLast() {
  // (state captured in onMouseMove)
}

function onMouseMove(e) {
  setMouseFromEvent(e);
  raycaster.setFromCamera(mouseNDC, camera);
  const targets = [];
  for (const sm of sectorMeshes) targets.push(sm.mesh);
  for (const m of npcMarkers) targets.push(m.mesh);
  const hits = raycaster.intersectObjects(targets, false);
  const hit = hits[0];

  if (hoveredMesh && hoveredMesh !== (hit ? hit.object : null)) {
    if (hoveredMesh !== selectedMesh && hoveredMesh.userData.baseEmissive !== undefined) {
      hoveredMesh.material.emissiveIntensity = hoveredMesh.userData.baseEmissive;
    }
    hoveredMesh = null;
    canvas.style.cursor = 'grab';
  }

  if (hit) {
    hoveredMesh = hit.object;
    if (hoveredMesh.userData.baseEmissive !== undefined && hoveredMesh !== selectedMesh) {
      hoveredMesh.material.emissiveIntensity = hoveredMesh.userData.baseEmissive * 1.6;
    }
    canvas.style.cursor = 'pointer';
  }
}

function onClick(e) {
  setMouseFromEvent(e);
  raycaster.setFromCamera(mouseNDC, camera);
  const targets = [];
  for (const m of npcMarkers) targets.push(m.mesh);
  for (const sm of sectorMeshes) targets.push(sm.mesh);
  const hits = raycaster.intersectObjects(targets, false);
  const hit = hits[0];
  if (!hit) { closePanel(); return; }
  const obj = hit.object;
  if (obj.userData.npcId) {
    selectNpc(obj);
  } else if (obj.userData.sectorId) {
    selectSector(obj);
  }
}

function onDblClick(e) {
  setMouseFromEvent(e);
  raycaster.setFromCamera(mouseNDC, camera);
  const targets = [];
  for (const sm of sectorMeshes) targets.push(sm.mesh);
  const hits = raycaster.intersectObjects(targets, false);
  if (hits[0]) {
    const s = hits[0].object.userData.data;
    setZoom('sector', s);
  }
}

function selectSector(mesh) {
  if (selectedMesh && selectedMesh !== mesh) {
    selectedMesh.material.emissiveIntensity = selectedMesh.userData.baseEmissive;
  }
  selectedMesh = mesh;
  selectedNpcMesh = null;
  mesh.material.emissiveIntensity = 1.5;
  const s = mesh.userData.data;
  const terrList = liveState.territoriesBySector[s.id] || [];
  const npcsHere = liveState.npcs.filter(n => {
    const loc = liveState.npcLocByNpc[n.id];
    return (loc && loc.sector_id === s.id) || (!loc && n.sector_id === s.id);
  });

  pName.textContent = s.name;
  pTitle.textContent = (s.region_type || '').toUpperCase() + ' REGION';
  pFaction.textContent = terrList.length
    ? 'Controlled by ' + terrList.length + ' faction(s)'
    : 'Unclaimed sector';
  const terrRows = terrList.map(t => {
    const fname = (liveState.factions[t.faction_id] || {}).display_name || t.faction_id;
    const fcol = (liveState.factions[t.faction_id] || {}).color || '#9e9e9e';
    return `<div class="row"><span class="row-label" style="color:${fcol}">${fname}</span><span class="row-val">control ${Math.round(t.control_level)} / influence ${Math.round(t.influence_level)} / ${t.claim_type}</span></div>`;
  }).join('');
  pBody.innerHTML = `
    <div class="row"><span class="row-label">Danger</span><span class="row-val">${s.danger_level}/10</span></div>
    <div class="row"><span class="row-label">Resources</span><span class="row-val">${s.resource_profile}</span></div>
    <div class="row"><span class="row-label">Adjacent</span><span class="row-val">${(s.adjacent_sector_ids || []).length}</span></div>
    <div class="row"><span class="row-label">NPCs here</span><span class="row-val">${npcsHere.length}</span></div>
    ${terrRows}
    ${s.description ? `<div style="margin-top:8px;color:#78909c;font-style:italic;font-size:12px">${s.description}</div>` : ''}
  `;

  // Per-faction control bars
  const ctrlBars = terrList.map(t => {
    const fname = (liveState.factions[t.faction_id] || {}).display_name || t.faction_id;
    const fcol = (liveState.factions[t.faction_id] || {}).color || '#9e9e9e';
    return `<div class="ctrl-row"><span class="ctrl-name" style="color:${fcol}">${fname}</span><div class="ctrl-bar"><div class="ctrl-fill" style="width:${t.control_level}%;background:${fcol}"></div></div><span style="color:#78909c;font-size:11px">${Math.round(t.control_level)}</span></div>`;
  }).join('') || '<div style="color:#546e7a;font-size:12px">No faction presence</div>';
  pControl.innerHTML = '<div style="margin-bottom:6px;color:#78909c;font-size:11px;letter-spacing:1px">FACTION CONTROL</div>' + ctrlBars;

  pThought.style.display = 'none';
  panelEl.classList.add('show');
}

function selectNpc(mesh) {
  selectedNpcMesh = mesh;
  if (selectedMesh) {
    selectedMesh.material.emissiveIntensity = selectedMesh.userData.baseEmissive;
    selectedMesh = null;
  }
  const npc = mesh.userData.data;
  const loc = liveState.npcLocByNpc[npc.id];
  const fid = mesh.userData.factionId;
  const fdata = fid ? liveState.factions[fid] : null;

  pName.textContent = npc.name || npc.id;
  pTitle.textContent = npc.role || 'NPC';
  pFaction.textContent = fdata ? fdata.display_name : (npc.category || 'unaffiliated');
  pFaction.style.color = fdata ? fdata.color : (CATEGORY_COLORS[npc.category] || '#78909c');

  let patrolInfo = '';
  if (loc && loc.patrol_route && loc.patrol_route.length > 0) {
    const names = loc.patrol_route.map(id => (liveState.sectorById[id] || {}).name || id);
    patrolInfo = `<div class="row"><span class="row-label">Patrol</span><span class="row-val">${names.join(' → ')}</span></div>`;
  }
  let destInfo = '';
  if (loc && loc.destination_sector_id) {
    const destSec = liveState.sectorById[loc.destination_sector_id];
    const destName = destSec ? destSec.name : loc.destination_sector_id;
    destInfo = `<div class="row"><span class="row-label">Heading to</span><span class="row-val">${destName} (${Math.round((loc.movement_progress || 0) * 100)}%)</span></div>`;
  }

  pBody.innerHTML = `
    <div class="row"><span class="row-label">Task</span><span class="row-val">${loc ? loc.current_task : 'unknown'}</span></div>
    <div class="row"><span class="row-label">Location</span><span class="row-val">${loc ? (liveState.sectorById[loc.sector_id] || {}).name || loc.sector_id : 'unknown'}</span></div>
    ${destInfo}
    ${patrolInfo}
    <div class="row"><span class="row-label">Mood</span><span class="row-val">${npc.mood || '—'}</span></div>
  `;
  pControl.innerHTML = '';
  pThought.style.display = npc.thought ? 'block' : 'none';
  if (npc.thought) pThought.textContent = '"' + npc.thought + '"';
  panelEl.classList.add('show');
}

// ════════════════════════════════════════════════════════════════════════════
// §10 CAMERA — OrbitControls tuning + level transitions
// ════════════════════════════════════════════════════════════════════════════
// (scene/camera/renderer/controls/lights are hoisted to §0 so §3-§6 can
// safely add to the scene. §10 only handles transitions + maxDistance
// updates per zoom level.)

// §3 BACKDROP — build after scene exists
function buildBackdrop() {
  // Starfield (GPU-drift) — fills the expanded world space (Federation ~160u, stars out to 600u)
  const N = 18000;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(N * 3);
  const sizes = new Float32Array(N);
  const alphas = new Float32Array(N);
  const znorms = new Float32Array(N);
  const seeds = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    // Spherical shell out to ~600 units, denser near the map plane (Y near 0)
    const r = 80 + Math.random() * 520;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pos[i*3]   = Math.sin(phi) * Math.cos(theta) * r;
    pos[i*3+1] = (Math.random() - 0.5) * 60 + Math.sin(phi) * Math.sin(theta) * r * 0.3;
    pos[i*3+2] = Math.cos(phi) * r * 0.8 - 100;
    sizes[i] = 0.4 + Math.random() * 2.5;
    alphas[i] = 0.15 + Math.random() * 0.85;
    znorms[i] = Math.min(1, Math.max(0, (-pos[i*3+2] + 100) / 500));
    seeds[i] = Math.random();
  }
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geo.setAttribute('aAlpha', new THREE.BufferAttribute(alphas, 1));
  geo.setAttribute('aZnorm', new THREE.BufferAttribute(znorms, 1));
  geo.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
  const mat = new THREE.ShaderMaterial({
    vertexShader: starVert,
    fragmentShader: starFrag,
    uniforms: { uTime: { value: 0 } },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  const stars = new THREE.Points(geo, mat);
  scene.add(stars);

  // Faint milky-way ribbon — spans the full Federation extent
  const milkyGeo = new THREE.PlaneGeometry(800, 200);
  const milkyMat = new THREE.ShaderMaterial({
    vertexShader: milkyVert,
    fragmentShader: milkyFrag,
    uniforms: { uTime: { value: 0 } },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  const milky = new THREE.Mesh(milkyGeo, milkyMat);
  milky.rotation.x = -Math.PI / 2;
  milky.rotation.z = 0.3;
  milky.position.y = -2.0;
  milky.position.z = -80;
  milky.material.opacity = 0.15;
  scene.add(milky);

  // Small irregular dust clouds at varied Z depths (NOT giant planar slabs)
  for (let i = 0; i < 12; i++) {
    const cloudGeo = new THREE.PlaneGeometry(60 + Math.random() * 100, 60 + Math.random() * 100);
    const cloudMat = new THREE.ShaderMaterial({
      vertexShader: nebVert,
      fragmentShader: nebFrag,
      uniforms: {
        uTime: { value: 0 },
        uSeed: { value: Math.random() * 1000 }
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    cloudMat.transparent = true;
    cloudMat.opacity = 0.04 + Math.random() * 0.06;
    const cloud = new THREE.Mesh(cloudGeo, cloudMat);
    cloud.rotation.x = -Math.PI / 2;
    cloud.rotation.z = Math.random() * Math.PI * 2;
    cloud.position.x = (Math.random() - 0.5) * 300;
    cloud.position.y = -1.0 - Math.random() * 2.0;
    cloud.position.z = -80 - i * 15 - Math.random() * 20;
    scene.add(cloud);
  }
}

buildBackdrop();

// ════════════════════════════════════════════════════════════════════════════
// DOM LABELS — always-visible sector + NPC names
// ════════════════════════════════════════════════════════════════════════════
const labelsEl = document.getElementById('labels');
const _labelPool = [];   // reused divs
function projectToScreen(worldPos) {
  const p = worldPos.clone().project(camera);
  const x = (p.x * 0.5 + 0.5) * window.innerWidth;
  const y = (-p.y * 0.5 + 0.5) * window.innerHeight;
  const visible = p.z < 1.0;
  return { x, y, visible, depth: p.z };
}
function getLabelEl(i) {
  if (!_labelPool[i]) {
    const d = document.createElement('div');
    d.className = 'lbl';
    labelsEl.appendChild(d);
    _labelPool[i] = d;
  }
  return _labelPool[i];
}

function updateDomLabels() {
  let idx = 0;

  // Build a quick lookup: factionId → territory centroid (for label centering)
  const factionCentroid = {};
  for (const v of territoryVolumes) {
    if (v.centroid) factionCentroid[v.factionId] = v.centroid;
  }

  // Sector labels — zoom-aware to reduce diagram feel
  // Galaxy: only home + selected (faction names placed at influence centroid)
  // Region: home + selected + contested
  // Sector: all visible
  for (const sm of sectorMeshes) {
    const el = getLabelEl(idx++);
    // For home sectors at Galaxy zoom, project from influence centroid
    let labelWorldPos = sm.mesh.position;
    if (sm.isHome && currentZoom === 'galaxy' && sm.homeFaction && factionCentroid[sm.homeFaction]) {
      labelWorldPos = factionCentroid[sm.homeFaction];
    }
    const s = screenPos(labelWorldPos);
    if (!s.visible) { el.style.display = 'none'; continue; }
    const terrList = liveState.territoriesBySector[sm.data.id] || [];
    const hasContest = terrList.some(t => t.claim_type === 'contested');
    const isSelected = sm.mesh === selectedMesh;
    let show = false;
    if (currentZoom === 'sector') show = true;
    else if (currentZoom === 'region') show = sm.isHome || hasContest || isSelected;
    else show = sm.isHome || isSelected;
    if (!show) { el.style.display = 'none'; continue; }
    el.style.display = 'block';
    el.style.left = s.x + 'px';
    el.style.top = (s.y - 14) + 'px';
    el.style.transform = 'translate(-50%, -100%)';
    el.className = 'lbl lbl-sector' + (hasContest ? ' contested' : '') + (sm.isHome ? ' home' : '');
    el.style.color = hasContest ? '#ef5350' : REGION_COLORS[sm.regionType] || '#4fc3f7';
    // Home sector labels (faction names) are larger at Galaxy zoom for readability
    if (sm.isHome && currentZoom === 'galaxy') {
      el.style.fontSize = '15px';
      el.style.fontWeight = '700';
      el.style.letterSpacing = '1px';
      el.style.textShadow = '0 0 6px #000, 0 0 3px #000';
    } else {
      el.style.fontSize = '';
      el.style.fontWeight = '';
      el.style.letterSpacing = '';
      el.style.textShadow = '';
    }
    el.textContent = sm.isHome && sm.homeFaction && liveState.factions[sm.homeFaction]
      ? liveState.factions[sm.homeFaction].display_name
      : sm.data.name;
  }

  // NPC labels — only show when zoomed in or in NPC/Exploration mode
  const showNpcs = currentZoom === 'sector' || currentMode === 'npc' || currentMode === 'exploration';
  for (const m of npcMarkers) {
    const el = getLabelEl(idx++);
    const s = screenPos(m.mesh.position);
    if (!s.visible) { el.style.display = 'none'; continue; }
    if (!showNpcs) { el.style.display = 'none'; continue; }
    el.style.display = 'block';
    el.style.left = s.x + 'px';
    el.style.top = (s.y + 12) + 'px';
    el.style.transform = 'translate(-50%, 0)';
    const fid = m.data.affiliation;
    const fcolor = (fid && liveState.factions[fid] && liveState.factions[fid].color) || '#78909c';
    el.className = 'lbl lbl-npc';
    el.style.color = fcolor;
    el.textContent = m.data.name || m.data.id;
  }

  // Hide unused label divs
  for (let i = idx; i < _labelPool.length; i++) {
    if (_labelPool[i]) _labelPool[i].style.display = 'none';
  }
}

function screenPos(worldPos) {
  return projectToScreen(worldPos);
}

// ════════════════════════════════════════════════════════════════════════════
// §11 ANIMATION LOOP — FIXED clock order (delta BEFORE elapsed)
// ════════════════════════════════════════════════════════════════════════════
const clock = new THREE.Clock();
let frameCount = 0;

function animate() {
  requestAnimationFrame(animate);
  frameCount++;

  // FIX: clock.getElapsedTime() internally calls getDelta() first, so a
  // subsequent getDelta() returns ~0. We must call getDelta() FIRST so dt
  // is real, then getElapsedTime() for t-based animations.
  const dt = clock.getDelta();
  const t = clock.getElapsedTime();

  // Camera transition
  if (cameraTargetAnim) {
    cameraTargetAnim.t += dt * 1.5;
    if (cameraTargetAnim.t >= 1) {
      cameraTargetAnim.t = 1;
      camera.position.copy(cameraTargetAnim.pos);
      controls.target.copy(cameraTargetAnim.look);
      cameraTargetAnim = null;
    } else {
      const ease = 1 - Math.pow(1 - cameraTargetAnim.t, 3);
      camera.position.lerp(cameraTargetAnim.pos, ease * 0.18);
      controls.target.lerp(cameraTargetAnim.look, ease * 0.18);
    }
  }

  // Backdrop shader time
  scene.children.forEach(c => {
    if (c.material && c.material.uniforms && c.material.uniforms.uTime && c.userData._nebMat) {
      c.material.uniforms.uTime.value = t;
    }
    if (c.type === 'Points' && c.material && c.material.uniforms && c.material.uniforms.uTime) {
      c.material.uniforms.uTime.value = t;
    }
  });

  // Territory volume time
  for (const v of territoryVolumes) {
    if (v.mesh.material.uniforms.uTime) v.mesh.material.uniforms.uTime.value = t;
  }

  // Home sprite LOD — scale proportional to camera distance so faction anchors
  // stay readable at Galaxy zoom and shrink at Sector zoom.
  for (const sm of sectorMeshes) {
    const sprite = sm.mesh.userData && sm.mesh.userData.homeSprite;
    if (sprite) {
      const dist = camera.position.distanceTo(sm.mesh.position);
      // ~0.045 yields ~25px at Galaxy (dist~200) and ~2px at Sector (dist~15)
      sprite.scale.set(dist * 0.045, dist * 0.045, 1);
    }
  }

  // NPC aggregate activity indicators — LOD-scaled per camera distance.
  // Scale modulated by count: more NPCs = larger, brighter glow.
  for (const a of npcAggregates) {
    const dist = camera.position.distanceTo(a.sprite.position);
    const size = dist * 0.065 * (1.0 + a.count * 0.15);
    a.sprite.scale.set(size, size, 1);
    // Pulse opacity strongly so activity reads as "alive" at Galaxy zoom
    a.sprite.material.opacity = 0.4 + 0.35 * Math.sin(t * 1.2 + a.sprite.position.x);
  }

  // Frontier markers — faint outward haze at frontier sectors.
  // Higher danger = brighter frontier glow.
  for (const f of frontierMarkers) {
    const dist = camera.position.distanceTo(f.sprite.position);
    const dangerScale = 1.0 + (f.danger - 7) * 0.15;
    const size = dist * 0.05 * dangerScale;
    f.sprite.scale.set(size, size, 1);
    f.sprite.material.opacity = 0.25 + 0.2 * Math.sin(t * 0.8 + f.sprite.position.z);
  }

  // Sector pulse — modulate core alpha for selected/hover via geometry attribute
  for (const sm of sectorMeshes) {
    if (sm.mesh === selectedMesh || sm.mesh === hoveredMesh) continue;
    const base = sm.mesh.userData.baseEmissive || 0.6;
    const pulse = 0.85 + 0.15 * Math.sin(t * 1.5 + sm.mesh.position.x);
    const alphas = sm.mesh.geometry.attributes.aAlpha;
    if (alphas && sm.mesh.geometry.attributes.position) {
      alphas.array[0] = Math.min(1.5, base * pulse);
      alphas.needsUpdate = true;
    }
  }

  // NPC markers + trails
  if (frameCount % 2 === 0) updateNpcPositions(dt);

  // DOM labels for sectors + NPCs (always-visible names per spec)
  if (frameCount % 4 === 0) updateDomLabels();

  controls.update();
  renderer.render(scene, camera);
}

// ════════════════════════════════════════════════════════════════════════════
// EVENT WIRING
// ════════════════════════════════════════════════════════════════════════════
canvas.addEventListener('mousemove', onMouseMove);
canvas.addEventListener('click', onClick);
canvas.addEventListener('dblclick', onDblClick);
canvas.addEventListener('wheel', () => {}, { passive: true });

document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => setMode(btn.dataset.mode));
});
document.querySelectorAll('.zoom-btn').forEach(btn => {
  btn.addEventListener('click', () => setZoom(btn.dataset.zoom));
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closePanel(); return; }
  if (e.key === 'f' || e.key === 'F') { fitToGalaxy(); return; }
  if (e.key === '1') setMode('universe');
  if (e.key === '2') setMode('territory');
  if (e.key === '3') setMode('npc');
  if (e.key === '4') setMode('exploration');
  if (e.key === 'g' || e.key === 'G') setZoom('galaxy');
  if (e.key === 'r' || e.key === 'R') setZoom('region');
  if (e.key === 's' || e.key === 'S') setZoom('sector');
  if (e.key === 'd' || e.key === 'D') toggleDebug();
});

let debugMode = false;
function toggleDebug() {
  debugMode = !debugMode;
  // DEBUG ON: swap cluster Points for giant flat debug spheres + always-on labels.
  // DEBUG OFF: restore astronomical cluster Points.
  for (const sm of sectorMeshes) {
    if (debugMode) {
      // Replace cluster Points with a giant debug sphere
      sectorGroup.remove(sm.mesh);
      if (sm.mesh.geometry) sm.mesh.geometry.dispose();
      const debugColor = new THREE.Color(REGION_COLORS[sm.regionType] || '#9e9e9e');
      const debugMesh = new THREE.Mesh(
        new THREE.SphereGeometry(1.4, 16, 12),
        new THREE.MeshBasicMaterial({
          color: debugColor,
          transparent: true,
          opacity: 0.7
        })
      );
      sectorToWorld(sm.data, debugMesh.position);
      debugMesh.userData = sm.mesh.userData;
      sectorGroup.add(debugMesh);
      sm.mesh = debugMesh;
      sectorMeshById[sm.data.id] = debugMesh;
    } else {
      // Restore cluster Points by rebuilding all sectors
      buildSectors();
      updateSectorEmissive();
      break;
    }
  }
  document.body.classList.toggle('debug-labels', debugMode);
}

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// Initial mode + zoom apply so the scene is visible before data arrives
setMode('universe');
setZoom('galaxy');

// ════════════════════════════════════════════════════════════════════════════
// START
// ════════════════════════════════════════════════════════════════════════════
document.getElementById('loading').style.display = 'none';
animate();
