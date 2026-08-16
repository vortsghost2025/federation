// ============================================================
// FEDERATION LIVING CONSTELLATION
// Full-screen autonomous universe visualization
// ============================================================

const API = '/map/data';
const POLL_MS = 4000;

// --- Archetype poetic descriptors ---
const ARCHETYPE_POETIC = {
self_improve: 'The Self-Improver',
guardian: 'The Guardian',
explorer: 'The Explorer',
diplomat: 'The Diplomat',
warrior: 'The Warrior',
mystic: 'The Mystic',
merchant: 'The Merchant',
scholar: 'The Scholar',
artist: 'The Artist',
leader: 'The Leader',
healer: 'The Healer',
spy: 'The Shadow',
engineer: 'The Builder',
philosopher: 'The Philosopher',
rebel: 'The Rebel',
harmonizer: 'The Harmonizer',
conqueror: 'The Conqueror',
visionary: 'The Visionary',
protector: 'The Protector',
pioneer: 'The Pioneer',
traditionalist: 'The Traditionalist',
revolutionary: 'The Revolutionary'
};

// --- Faction config ---
const FACTIONS = [
{id:'diplomatic_corps',name:'Diplomatic Corps',color:'#4fc3f7'},
{id:'military_command',name:'Military Command',color:'#ef5350'},
{id:'cultural_ministry',name:'Cultural Ministry',color:'#ab47bc'},
{id:'research_division',name:'Research Division',color:'#66bb6a'},
{id:'consciousness_collective',name:'Consciousness Collective',color:'#7c4dff'},
{id:'economic_council',name:'Economic Council',color:'#ffd700'},
{id:'exploration_initiative',name:'Exploration Initiative',color:'#26c6da'},
{id:'preservation_society',name:'Preservation Society',color:'#ff7043'}
];
const FACTION_MAP = {};
FACTIONS.forEach(f => FACTION_MAP[f.id] = f);

// --- State ---
let mapData = null;
let prevWorldState = null;
let nodes = [];
let bgStars = [];
let ripples = [];
let particles = [];
let treaties = [];
let canvas, ctx, W, H;
let zoom = 1, panX = 0, panY = 0;
let dragging = false, dragStartX, dragStartY, panStartX, panStartY;
let hoveredNode = null;
let mouseX = 0, mouseY = 0;
let lastTickEffects = 0;
let tickFlashTimer = 0;
let globalBreathPhase = 0;
let factionTechData = {};
let prevFactionTech = {};
let starflares = [];
let questData = {};
let prevTreaties = [];
let crystallizeAnims = [];
let shatterAnims = [];
let cascadeChains = [];
let questRings = [];

// ============================================================
// INIT
// ============================================================
function init() {
canvas = document.getElementById('canvas');
ctx = canvas.getContext('2d');
resize();
window.addEventListener('resize', resize);
canvas.addEventListener('mousemove', onMouseMove);
canvas.addEventListener('mousedown', onMouseDown);
canvas.addEventListener('mouseup', onMouseUp);
canvas.addEventListener('wheel', onWheel, {passive:false});
canvas.addEventListener('mouseleave', () => { hoveredNode = null; hideTooltip(); });

// Background stars — deep field
for (let i = 0; i < 600; i++) {
bgStars.push({
x: Math.random() * 4000 - 500,
y: Math.random() * 3000 - 500,
r: Math.random() * 1.2 + 0.2,
brightness: Math.random() * 0.5 + 0.1,
speed: Math.random() * 0.002 + 0.0005,
phase: Math.random() * Math.PI * 2
});
}

// Build faction legend
let html = '';
FACTIONS.forEach(f => {
html += `<div class="lrow"><div class="ldot" style="background:${f.color}"></div><span class="lname">${f.name}</span></div>`;
});
document.getElementById('legend').innerHTML = html;

fetchData();
setInterval(fetchData, POLL_MS);
fetchFactionTech();
setInterval(fetchFactionTech, 60000);
fetchQuestBatch();
setInterval(fetchQuestBatch, 30000);
requestAnimationFrame(draw);
}

function resize() {
W = window.innerWidth;
H = window.innerHeight;
canvas.width = W * devicePixelRatio;
canvas.height = H * devicePixelRatio;
canvas.style.width = W + 'px';
canvas.style.height = H + 'px';
ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
// Rebuild node positions on resize
if (mapData) buildNodes();
}

// ============================================================
// DATA FETCH
// ============================================================
async function fetchData() {
  const data = await fedFetch('constellationData', API);
  if (!data) return;
  mapData = data;
  buildNodes();
  updateHUD();
  detectChanges();
}

async function fetchFactionTech() {
  const data = await fedFetch('factionTech', '/simulation/faction-tech');
  if (!data) return;
  prevFactionTech = {...factionTechData};
  factionTechData = {};
  const factions = data.factions || data;
  if (Array.isArray(factions)) {
    factions.forEach(f => { factionTechData[f.faction_id || f.id] = f; });
  } else if (typeof factions === 'object') {
    factionTechData = factions;
  }
  for (const [fid, fdata] of Object.entries(factionTechData)) {
    const prevCompleted = ((prevFactionTech[fid] && prevFactionTech[fid].completed_techs) || []).map(t => typeof t === 'string' ? t : t.name || t.id);
    const curCompleted = (fdata.completed_techs || []).map(t => typeof t === 'string' ? t : t.name || t.id);
    for (const techName of curCompleted) {
      if (!prevCompleted.includes(techName)) {
        spawnStarflare(fid, techName);
      }
    }
  }
}

async function fetchQuestBatch() {
  if (!nodes.length) return;
  const activeNodes = [...nodes].sort((a, b) => ((a.npc && a.npc.last_active) || 0) > ((b.npc && b.npc.last_active) || 0) ? -1 : 1).slice(0, 10);
  for (const node of activeNodes) {
    if (!node.id) continue;
    const qData = await fedFetch('npcQuests', `/simulation/npc-quests/${encodeURIComponent(node.id)}`);
    if (!qData) continue;
    questData[node.id] = qData;
    const activeQuests = qData.active_quests || qData.quests || [];
    if (activeQuests.length > 0) {
      let existing = questRings.find(r => r.nodeId === node.id);
      if (!existing) {
        existing = { nodeId: node.id, quests: activeQuests, phase: 0 };
        questRings.push(existing);
      } else {
        existing.quests = activeQuests;
      }
    } else {
      questRings = questRings.filter(r => r.nodeId !== node.id);
    }
  }
}

function spawnStarflare(factionId, techName) {
const fInfo = FACTION_MAP[factionId];
if (!fInfo) return;
const fi = FACTIONS.indexOf(fInfo);
const cx = W / 2, cy = H / 2, fR = Math.min(W, H) * 0.30;
const angle = (fi / 8) * Math.PI * 2 - Math.PI / 2;
const sx = cx + Math.cos(angle) * fR;
const sy = cy + Math.sin(angle) * fR;
starflares.push({
x: sx, y: sy,
color: fInfo.color,
techName,
born: performance.now(),
duration: 3000,
ringRadius: 0,
alpha: 1,
rayCount: 6,
flashAlpha: 1
});
}

// ============================================================
// CHANGE DETECTION — spawn ripples/particles on state changes
// ============================================================
function detectChanges() {
if (!mapData) return;
const ws = mapData.world_state || {};
if (!prevWorldState) { prevWorldState = {...ws}; return; }

// World state shifts → color the tick ring
const tensionDelta = Math.abs((ws.tension_level||0) - (prevWorldState.tension_level||0));
const anomalyDelta = Math.abs((ws.anomaly_activity||0) - (prevWorldState.anomaly_activity||0));
const stabilityDelta = Math.abs((ws.stability||0) - (prevWorldState.stability||0));

if (tensionDelta > 2 || anomalyDelta > 2 || stabilityDelta > 2) {
// Big shift — flash tick ring
const ring = document.getElementById('tick-ring');
ring.className = tensionDelta > stabilityDelta ? 'tension' : 'stable';
tickFlashTimer = 60;
}

// New events → spawn ripples from source NPC
const events = mapData.events || [];
if (events.length > lastTickEffects && lastTickEffects > 0) {
const newEvts = events.slice(0, events.length - lastTickEffects);
const cascadeNodes = [];
for (const ev of newEvts) {
const srcNode = nodes.find(n => n.id === ev.char_id || n.name === ev.char_name);
if (srcNode) {
const color = ev.action_type === 'conflict' ? '#ef5350' :
ev.action_type === 'diplomacy' ? '#4fc3f7' :
ev.action_type === 'discovery' ? '#26c6da' :
ev.action_type === 'consciousness' ? '#7c4dff' : '#ffd700';
spawnRipple(srcNode.x, srcNode.y, color);
spawnParticleBurst(srcNode.x, srcNode.y, color, 8);
cascadeNodes.push(srcNode);
}
}
if (cascadeNodes.length >= 2) {
for (let i = 0; i < cascadeNodes.length - 1; i++) {
cascadeChains.push({
x1: cascadeNodes[i].x, y1: cascadeNodes[i].y,
x2: cascadeNodes[i + 1].x, y2: cascadeNodes[i + 1].y,
color: '#4fc3f7',
born: performance.now(),
duration: 3500,
dashOffset: 0
});
}
}
}
lastTickEffects = events.length;
prevWorldState = {...ws};
}

// ============================================================
// NODE BUILDING
// ============================================================
function buildNodes() {
if (!mapData) return;
const npcs = mapData.npcs || [];
const cx = W / 2, cy = H / 2;
const fRadius = Math.min(W, H) * 0.30;
const now = Date.now() / 1000;

// Group by faction
const groups = {};
FACTIONS.forEach(f => groups[f.id] = []);
const unaffiliated = [];

for (const npc of npcs) {
const aff = npc.affiliation;
if (aff && groups[aff]) groups[aff].push(npc);
else unaffiliated.push(npc);
}

const oldNodes = nodes;
nodes = [];

FACTIONS.forEach((f, i) => {
const angle = (i / FACTIONS.length) * Math.PI * 2 - Math.PI / 2;
const fcx = cx + Math.cos(angle) * fRadius;
const fcy = cy + Math.sin(angle) * fRadius;
const group = groups[f.id];
const spread = Math.max(50, group.length * 14);

group.forEach((npc, j) => {
const subAngle = (j / Math.max(group.length,1)) * Math.PI * 2 + globalBreathPhase * 0.1;
const subR = spread * (0.25 + ((j * 7 + i * 13) % 10) / 14);
const x = fcx + Math.cos(subAngle) * subR;
const y = fcy + Math.sin(subAngle) * subR;
const age = npc.last_active ? (now - npc.last_active) : 9999;
const activity = Math.max(0.15, 1 - age / 3600);
const radius = 4 + activity * 7;

// Inherit position from old nodes if exists (smooth repositioning)
const existing = oldNodes.find(n => n.id === npc.id);
const sx = existing ? existing.x : x;
const sy = existing ? existing.y : y;

nodes.push({
id: npc.id, name: npc.name || npc.id,
x: sx, y: sy, tx: x, ty: y, // tx/ty = target position for smooth lerp
radius, baseRadius: radius,
color: npc.mood_color || f.color, faction: f.id,
npc, activity, age,
breathPhase: (j + i * 3) * 0.7,
pulseIntensity: activity
});
});
});

// Unaffiliated — scattered in inner ring
unaffiliated.forEach((npc, j) => {
const a = (j / Math.max(unaffiliated.length,1)) * Math.PI * 2;
const r = fRadius * (0.15 + ((j * 17) % 10) / 20);
const x = cx + Math.cos(a) * r;
const y = cy + Math.sin(a) * r;
const existing = oldNodes.find(n => n.id === npc.id);
nodes.push({
id: npc.id, name: npc.name || npc.id,
x: existing ? existing.x : x, y: existing ? existing.y : y,
tx: x, ty: y,
radius: 3, baseRadius: 3,
color: npc.mood_color || '#546e7a', faction: null,
npc, activity: 0.2, age: 999,
breathPhase: j * 1.3, pulseIntensity: 0.2
});
});

// Build treaty lines
buildTreaties();
}

function buildTreaties() {
const newTreaties = [];
if (!mapData || !mapData.factions) { treaties = []; return; }
for (const [fid, fdata] of Object.entries(mapData.factions)) {
const stances = fdata.stances || {};
for (const [otherId, stance] of Object.entries(stances)) {
if (fid >= otherId) continue;
const n1 = nodes.find(n => n.faction === fid);
const n2 = nodes.find(n => n.faction === otherId);
if (!n1 || !n2) continue;
const f1 = FACTION_MAP[fid], f2 = FACTION_MAP[otherId];
const i1 = FACTIONS.indexOf(f1), i2 = FACTIONS.indexOf(f2);
if (i1 < 0 || i2 < 0) continue;
const cx = W/2, cy = H/2, fR = Math.min(W,H)*0.30;
const a1 = (i1/8)*Math.PI*2 - Math.PI/2;
const a2 = (i2/8)*Math.PI*2 - Math.PI/2;
const x1 = cx+Math.cos(a1)*fR, y1 = cy+Math.sin(a1)*fR;
const x2 = cx+Math.cos(a2)*fR, y2 = cy+Math.sin(a2)*fR;

const isAllied = stance === 'allied' || stance === 'friendly';
const isHostile = stance === 'hostile' || stance === 'war';
if (!isAllied && !isHostile) continue;

newTreaties.push({
x1, y1, x2, y2,
color: isAllied ? '#4fc3f7' : '#ef5350',
type: isAllied ? 'allied' : 'hostile',
strength: 0.3,
key: fid + ':' + otherId + ':' + stance
});
}
}

const newKeys = newTreaties.map(t => t.key);
const oldKeys = prevTreaties.map(t => t.key);

for (const tr of newTreaties) {
if (!oldKeys.includes(tr.key) && tr.type === 'allied') {
crystallizeAnims.push({
x1: tr.x1, y1: tr.y1, x2: tr.x2, y2: tr.y2,
color: tr.color,
born: performance.now(),
duration: 1500,
sparkles: Array.from({length: 12}, (_, i) => ({
t: i / 12,
offset: (Math.random() - 0.5) * 6,
phase: Math.random() * Math.PI * 2
}))
});
}
}

for (const old of prevTreaties) {
if (!newKeys.includes(old.key) && old.type === 'allied') {
shatterAnims.push({
x1: old.x1, y1: old.y1, x2: old.x2, y2: old.y2,
color: old.color,
born: performance.now(),
duration: 1000,
fragments: Array.from({length: 20}, () => {
const ft = Math.random();
return {
x: old.x1 + (old.x2 - old.x1) * ft,
y: old.y1 + (old.y2 - old.y1) * ft,
vx: (Math.random() - 0.5) * 3,
vy: (Math.random() - 0.5) * 3,
alpha: 1
};
})
});
spawnParticleBurst(
(old.x1 + old.x2) / 2, (old.y1 + old.y2) / 2,
old.color, 15
);
}
}

prevTreaties = newTreaties.map(t => ({...t}));
treaties = newTreaties;
}

// ============================================================
// HUD UPDATE
// ============================================================
function updateHUD() {
if (!mapData) return;
const ws = mapData.world_state || {};
setBar('tension', ws.tension_level, 100);
setBar('stability', ws.stability, 100);
setBar('morale', ws.morale, 100);
setBar('threat', ws.threat_level, 100);
setBar('anomaly', ws.anomaly_activity, 100);
setBar('resource', ws.resource_abundance, 100);

const worker = mapData.worker || {};
const tickCount = worker.tick_count || 0;
const status = worker.status || 'unknown';
document.getElementById('tick-text').textContent = `Tick ${tickCount} · ${status}`;

// Highlight active world-state bars
['tension','stability','morale','threat','anomaly','resource'].forEach(k => {
const row = document.getElementById('hr-' + k);
if (row) row.className = 'hud-row' + ((ws[k === 'resource' ? 'resource_abundance' : k === 'tension' ? 'tension_level' : k === 'threat' ? 'threat_level' : k === 'anomaly' ? 'anomaly_activity' : k] || 0) > 50 ? ' active' : '');
});
}

function setBar(name, val, max) {
const pct = Math.min(100, Math.max(0, ((val||0)/max)*100));
const fill = document.getElementById('hf-'+name);
const vl = document.getElementById('hv-'+name);
if (fill) fill.style.width = pct+'%';
if (vl) vl.textContent = Math.round(val||0);
}

// ============================================================
// EFFECTS — Ripples & Particles
// ============================================================
function spawnRipple(x, y, color) {
ripples.push({x, y, color, radius: 0, maxRadius: 180, alpha: 0.8, speed: 2.5});
ripples.push({x, y, color, radius: 0, maxRadius: 120, alpha: 0.5, speed: 1.8});
}

function spawnParticleBurst(x, y, color, count) {
for (let i = 0; i < count; i++) {
const angle = Math.random() * Math.PI * 2;
const speed = 0.5 + Math.random() * 2;
particles.push({
x, y, vx: Math.cos(angle)*speed, vy: Math.sin(angle)*speed,
color, life: 1, decay: 0.008 + Math.random()*0.012, radius: 1 + Math.random()*2
});
}
}

// ============================================================
// DRAWING — the heart of the Living Constellation
// ============================================================
function draw() {
const t = performance.now();
globalBreathPhase = t * 0.0001;

ctx.clearRect(0, 0, W, H);

// --- Deep space background ---
ctx.fillStyle = '#050510';
ctx.fillRect(0, 0, W, H);

ctx.save();
ctx.translate(panX, panY);
ctx.scale(zoom, zoom);

// --- Background stars with twinkle ---
for (const s of bgStars) {
const twinkle = 0.4 + 0.6 * Math.sin(t * s.speed + s.phase);
const alpha = s.brightness * twinkle;
ctx.beginPath();
ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
ctx.fillStyle = `rgba(180,200,240,${alpha})`;
ctx.fill();
}

// --- Faction nebulae — soft radial glows ---
drawNebulae(t);

// --- Treaty/connection lines ---
drawTreatyLines(t);

// --- Crystallize animations ---
drawCrystallize(t);

// --- Shatter animations ---
drawShatter(t);

// --- Cascade chain lines ---
drawCascadeChains(t);

// --- Quest particle streams ---
drawQuestStreams(t);

// --- Ripple effects ---
drawRipples();

// --- Floating particles ---
drawParticles();

// --- NPC stars ---
drawStars(t);

// --- Quest spinning rings ---
drawQuestRings(t);

// --- Tech progress arcs ---
drawTechArcs(t);

// --- Starflare effects ---
drawStarflares(t);

// --- Center beacon ---
drawCenterBeacon(t);

ctx.restore();

// --- Cinematic vignette ---
const vigGrad = ctx.createRadialGradient(W/2, H/2, Math.min(W,H)*0.3, W/2, H/2, Math.max(W,H)*0.75);
vigGrad.addColorStop(0, 'rgba(5,5,16,0)');
vigGrad.addColorStop(1, 'rgba(5,5,16,0.4)');
ctx.fillStyle = vigGrad;
ctx.fillRect(0, 0, W, H);

// --- Tick flash ---
if (tickFlashTimer > 0) {
tickFlashTimer--;
if (tickFlashTimer <= 0) {
document.getElementById('tick-ring').className = '';
}
const hud = document.getElementById('tick-hud');
hud.className = tickFlashTimer > 0 ? 'flash' : '';
}

requestAnimationFrame(draw);
}

// --- Faction nebulae — breathing colored clouds ---
function drawNebulae(t) {
if (!mapData || !mapData.factions) return;
const cx = W/2, cy = H/2, fR = Math.min(W,H)*0.30;

FACTIONS.forEach((f, i) => {
const angle = (i / 8) * Math.PI * 2 - Math.PI / 2;
const fcx = cx + Math.cos(angle) * fR;
const fcy = cy + Math.sin(angle) * fR;

// Breathing radius
const breath = 1 + 0.08 * Math.sin(t * 0.0008 + i * 0.9);
const nebulaR = 90 * breath;

// Influence from faction data (if available)
const fdata = mapData.factions[f.id];
const influence = fdata ? (fdata.influence || 0.5) : 0.5;
const r = nebulaR * (0.6 + influence * 0.8);

// Multi-layered glow
for (let layer = 3; layer >= 1; layer--) {
const lr = r * layer * 0.5;
const alpha = 0.015 * (4 - layer) * influence;
const grad = ctx.createRadialGradient(fcx, fcy, 0, fcx, fcy, lr);
grad.addColorStop(0, f.color + hexAlpha(alpha));
grad.addColorStop(0.6, f.color + hexAlpha(alpha * 0.3));
grad.addColorStop(1, f.color + '00');
ctx.beginPath();
ctx.arc(fcx, fcy, lr, 0, Math.PI * 2);
ctx.fillStyle = grad;
ctx.fill();
}

// Faction name label — very subtle
ctx.fillStyle = f.color + '44';
ctx.font = '9px Courier New';
ctx.textAlign = 'center';
ctx.fillText(f.name.toUpperCase(), fcx, fcy + r + 18);
});
}

// --- Treaty lines with animation ---
function drawTreatyLines(t) {
for (const tr of treaties) {
const dx = tr.x2 - tr.x1, dy = tr.y2 - tr.y1;
const len = Math.sqrt(dx*dx + dy*dy);
if (len < 1) continue;

if (tr.type === 'allied') {
// Solid flowing line with pulse
const pulse = 0.3 + 0.3 * Math.sin(t * 0.002);
ctx.beginPath();
ctx.moveTo(tr.x1, tr.y1);
ctx.lineTo(tr.x2, tr.y2);
ctx.strokeStyle = tr.color + hexAlpha(pulse * tr.strength);
ctx.lineWidth = 1.5;
ctx.stroke();

// Traveling dot along the line
const progress = ((t * 0.0003) % 1);
const px = tr.x1 + dx * progress;
const py = tr.y1 + dy * progress;
ctx.beginPath();
ctx.arc(px, py, 2, 0, Math.PI * 2);
ctx.fillStyle = tr.color + '88';
ctx.fill();
} else {
// Crackling hostile line — dashed, flickering
const flicker = 0.15 + 0.2 * Math.random();
ctx.save();
ctx.setLineDash([4, 8]);
ctx.lineDashOffset = -t * 0.05;
ctx.beginPath();
ctx.moveTo(tr.x1, tr.y1);
ctx.lineTo(tr.x2, tr.y2);
ctx.strokeStyle = tr.color + hexAlpha(flicker * tr.strength);
ctx.lineWidth = 1;
ctx.stroke();
ctx.restore();
}
}
}

// --- Quest particle streams between NPCs ---
function drawQuestStreams(t) {
if (!mapData) return;
// Find NPCs with active quests and draw faint particle trails
// to their faction center (quest effort flowing outward)
for (const node of nodes) {
if (!node.npc || !node.faction) continue;
const hasQuest = node.npc.latest_action && node.activity > 0.5;
if (!hasQuest) continue;

// Faint particle trail from NPC outward
const streamPhase = (t * 0.001 + node.breathPhase) % 1;
const trailLen = 20;
for (let p = 0; p < 3; p++) {
const pp = (streamPhase + p * 0.33) % 1;
const angle = node.breathPhase + pp * 0.5;
const dist = node.radius + pp * trailLen;
const px = node.x + Math.cos(angle) * dist;
const py = node.y + Math.sin(angle) * dist;
const alpha = (1 - pp) * 0.3 * node.activity;
ctx.beginPath();
ctx.arc(px, py, 1, 0, Math.PI * 2);
ctx.fillStyle = node.color + hexAlpha(alpha);
ctx.fill();
}
}
}

// --- Ripple shockwaves ---
function drawRipples() {
for (let i = ripples.length - 1; i >= 0; i--) {
const r = ripples[i];
r.radius += r.speed;
r.alpha -= 0.008;

if (r.alpha <= 0 || r.radius >= r.maxRadius) {
ripples.splice(i, 1);
continue;
}

ctx.beginPath();
ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2);
ctx.strokeStyle = r.color + hexAlpha(r.alpha * 0.6);
ctx.lineWidth = 2;
ctx.stroke();

// Inner glow ring
ctx.beginPath();
ctx.arc(r.x, r.y, r.radius * 0.7, 0, Math.PI * 2);
ctx.strokeStyle = r.color + hexAlpha(r.alpha * 0.2);
ctx.lineWidth = 1;
ctx.stroke();
}
}

// --- Floating particles ---
function drawParticles() {
for (let i = particles.length - 1; i >= 0; i--) {
const p = particles[i];
p.x += p.vx;
p.y += p.vy;
p.vx *= 0.99;
p.vy *= 0.99;
p.life -= p.decay;

if (p.life <= 0) {
particles.splice(i, 1);
continue;
}

ctx.beginPath();
ctx.arc(p.x, p.y, p.radius * p.life, 0, Math.PI * 2);
ctx.fillStyle = p.color + hexAlpha(p.life * 0.7);
ctx.fill();
}
}

// --- NPC stars — the living points of light ---
function drawStars(t) {
for (const node of nodes) {
// Smooth lerp toward target position
node.x += (node.tx - node.x) * 0.03;
node.y += (node.ty - node.y) * 0.03;

// Breathing radius
const breath = Math.sin(t * 0.002 + node.breathPhase) * 0.25 + 1;
const r = node.baseRadius * breath * (hoveredNode === node ? 1.5 : 1);
node.radius = r;

const isHovered = hoveredNode === node;

// World-state color modulation
const ws = mapData ? mapData.world_state : {};
const tensionTint = Math.min(1, (ws.tension_level || 0) / 80);
const anomalyTint = Math.min(1, (ws.anomaly_activity || 0) / 80);
const modColor = modulateColor(node.color, tensionTint, anomalyTint);

// Outer glow — 3 layers
for (let g = 3; g >= 1; g--) {
const glowR = r * (2 + g * 1.5);
const alpha = (0.03 * (4 - g)) * node.pulseIntensity;
const grad = ctx.createRadialGradient(node.x, node.y, r * 0.3, node.x, node.y, glowR);
grad.addColorStop(0, modColor + hexAlpha(alpha));
grad.addColorStop(1, modColor + '00');
ctx.beginPath();
ctx.arc(node.x, node.y, glowR, 0, Math.PI * 2);
ctx.fillStyle = grad;
ctx.fill();
}

// Activity pulse ring — breathes with the universe
if (node.activity > 0.4) {
const pulseR = r + 3 + Math.sin(t * 0.004 + node.breathPhase) * 4;
ctx.beginPath();
ctx.arc(node.x, node.y, pulseR, 0, Math.PI * 2);
ctx.strokeStyle = modColor + hexAlpha(node.activity * 0.25);
ctx.lineWidth = 1;
ctx.stroke();
}

// Core star — radial gradient
const coreGrad = ctx.createRadialGradient(
node.x - r*0.2, node.y - r*0.2, 0,
node.x, node.y, r
);
coreGrad.addColorStop(0, lighten(modColor, 60));
coreGrad.addColorStop(0.6, modColor);
coreGrad.addColorStop(1, darken(modColor, 30));
ctx.beginPath();
ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
ctx.fillStyle = coreGrad;
ctx.fill();

// Hover ring
if (isHovered) {
ctx.beginPath();
ctx.arc(node.x, node.y, r + 5, 0, Math.PI * 2);
ctx.strokeStyle = '#ffffff55';
ctx.lineWidth = 1.5;
ctx.stroke();
}

// Name label — only on hover or high zoom
if (isHovered || zoom > 1.5) {
ctx.fillStyle = isHovered ? '#ffffffcc' : '#ffffff44';
ctx.font = `${isHovered ? 12 : 9}px Courier New`;
ctx.textAlign = 'center';
ctx.fillText(node.name, node.x, node.y + r + 14);
}
}
}

// --- Center beacon — the Federation core ---
function drawCenterBeacon(t) {
const cx = W/2, cy = H/2;
const pulse = Math.sin(t * 0.001) * 0.3 + 0.7;

// Soft core glow
const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 25 * pulse);
grad.addColorStop(0, 'rgba(79,195,247,0.15)');
grad.addColorStop(1, 'rgba(79,195,247,0)');
ctx.beginPath();
ctx.arc(cx, cy, 25 * pulse, 0, Math.PI * 2);
ctx.fillStyle = grad;
ctx.fill();

// Tiny core dot
ctx.beginPath();
ctx.arc(cx, cy, 2, 0, Math.PI * 2);
ctx.fillStyle = `rgba(79,195,247,${0.5 + pulse * 0.3})`;
ctx.fill();

// Expanding ring
const ringR = 8 + pulse * 6;
ctx.beginPath();
ctx.arc(cx, cy, ringR, 0, Math.PI * 2);
ctx.strokeStyle = `rgba(79,195,247,${0.15 + pulse * 0.1})`;
ctx.lineWidth = 1;
ctx.stroke();
}

// ============================================================
// INTERACTION
// ============================================================
function screenToWorld(sx, sy) {
return { x: (sx - panX) / zoom, y: (sy - panY) / zoom };
}

function getNodeAt(sx, sy) {
const {x, y} = screenToWorld(sx, sy);
for (let i = nodes.length - 1; i >= 0; i--) {
const n = nodes[i];
const dx = x - n.x, dy = y - n.y;
if (dx*dx + dy*dy < (n.radius + 6) * (n.radius + 6)) return n;
}
return null;
}

function onMouseMove(e) {
const rect = canvas.getBoundingClientRect();
mouseX = e.clientX - rect.left;
mouseY = e.clientY - rect.top;

if (dragging) {
panX = panStartX + (e.clientX - dragStartX);
panY = panStartY + (e.clientY - dragStartY);
return;
}

const node = getNodeAt(mouseX, mouseY);
hoveredNode = node;
canvas.style.cursor = node ? 'pointer' : 'grab';

if (node) showTooltip(node, e.clientX, e.clientY);
else hideTooltip();
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
document.body.classList.add('dragging');
}
}

function onMouseUp() {
dragging = false;
document.body.classList.remove('dragging');
canvas.style.cursor = hoveredNode ? 'pointer' : 'grab';
}

function onWheel(e) {
e.preventDefault();
const delta = e.deltaY > 0 ? 0.92 : 1.08;
zoom = Math.max(0.3, Math.min(5, zoom * delta));
}

// --- Tooltip — atmospheric, minimal ---
function showTooltip(node, cx, cy) {
const tt = document.getElementById('tooltip');
tt.classList.add('show');
document.getElementById('tt-name').textContent = node.name;
document.getElementById('tt-name').style.color = node.color;
const fInfo = FACTION_MAP[node.faction];
document.getElementById('tt-faction').textContent = fInfo ? fInfo.name : (node.faction || 'Unaffiliated');
document.getElementById('tt-faction').style.color = fInfo ? fInfo.color : '#546e7a';

const npc = node.npc;
const archetype = npc.archetype ? (ARCHETYPE_POETIC[npc.archetype] || 'The ' + (npc.archetype.charAt(0).toUpperCase() + npc.archetype.slice(1).replace(/_/g,' '))) : '';
document.getElementById('tt-archetype').textContent = archetype;
document.getElementById('tt-archetype').style.color = node.color;

const moodEl = document.getElementById('tt-mood');
if (npc.mood) {
moodEl.textContent = npc.mood;
moodEl.style.color = npc.mood_color || node.color;
} else {
moodEl.textContent = '';
}

document.getElementById('tt-thought').textContent = npc.latest_thought || '';

// Position tooltip
const ttW = 300, ttH = 120;
let tx = cx + 16, ty = cy - 10;
if (tx + ttW > W) tx = cx - ttW - 16;
if (ty + ttH > H) ty = H - ttH - 10;
if (ty < 10) ty = 10;
tt.style.left = tx + 'px';
tt.style.top = ty + 'px';
}

function hideTooltip() {
document.getElementById('tooltip').classList.remove('show');
}

// --- Starflare effect on tech completion ---
function drawStarflares(t) {
for (let i = starflares.length - 1; i >= 0; i--) {
const sf = starflares[i];
const elapsed = t - sf.born;
if (elapsed > sf.duration) { starflares.splice(i, 1); continue; }
const progress = elapsed / sf.duration;
const ringR = progress * 120;
const ringAlpha = (1 - progress) * 0.8;
const flashAlpha = progress < 0.15 ? (1 - progress / 0.15) : 0;
const labelAlpha = progress < 0.7 ? 1 : (1 - progress) / 0.3;
const c = hexToRgb(sf.color);

if (flashAlpha > 0) {
const fg = ctx.createRadialGradient(sf.x, sf.y, 0, sf.x, sf.y, 80 * flashAlpha);
fg.addColorStop(0, `rgba(255,255,255,${flashAlpha * 0.6})`);
fg.addColorStop(0.4, `rgba(${(c&&c.r)||200},${(c&&c.g)||200},${(c&&c.b)||255},${flashAlpha * 0.3})`);
                fg.addColorStop(1, `rgba(${(c&&c.r)||200},${(c&&c.g)||200},${(c&&c.b)||255},0)`);
ctx.beginPath();
ctx.arc(sf.x, sf.y, 80, 0, Math.PI * 2);
ctx.fillStyle = fg;
ctx.fill();
}

ctx.beginPath();
ctx.arc(sf.x, sf.y, ringR, 0, Math.PI * 2);
ctx.strokeStyle = `rgba(${(c&&c.r)||200},${(c&&c.g)||200},${(c&&c.b)||255},${ringAlpha * 0.6})`;
ctx.lineWidth = 2 + (1 - progress) * 3;
ctx.stroke();

for (let r = 0; r < sf.rayCount; r++) {
const rayAngle = (r / sf.rayCount) * Math.PI * 2 + progress * 0.5;
const rayLen = 30 + progress * 60;
const rayAlpha = (1 - progress) * 0.5;
ctx.beginPath();
ctx.moveTo(sf.x, sf.y);
ctx.lineTo(sf.x + Math.cos(rayAngle) * rayLen, sf.y + Math.sin(rayAngle) * rayLen);
ctx.strokeStyle = `rgba(255,255,255,${rayAlpha})`;
ctx.lineWidth = 1.5 * (1 - progress);
ctx.stroke();
}

if (labelAlpha > 0 && sf.techName) {
ctx.fillStyle = `rgba(255,255,255,${labelAlpha * 0.9})`;
ctx.font = '11px Courier New';
ctx.textAlign = 'center';
ctx.fillText(sf.techName, sf.x, sf.y - ringR - 8);
}
}
}

// --- Crystallize animation for new allied treaties ---
function drawCrystallize(t) {
for (let i = crystallizeAnims.length - 1; i >= 0; i--) {
const ca = crystallizeAnims[i];
const elapsed = t - ca.born;
if (elapsed > ca.duration) { crystallizeAnims.splice(i, 1); continue; }
const progress = elapsed / ca.duration;
const drawProgress = Math.min(1, progress * 1.2);
const fromLeft = drawProgress;
const fromRight = drawProgress;
const midX = (ca.x1 + ca.x2) / 2;
const midY = (ca.y1 + ca.y2) / 2;

const endLX = ca.x1 + (midX - ca.x1) * fromLeft;
const endLY = ca.y1 + (midY - ca.y1) * fromLeft;
const endRX = ca.x2 + (midX - ca.x2) * fromRight;
const endRY = ca.y2 + (midY - ca.y2) * fromRight;

const lineAlpha = (1 - progress * 0.3) * 0.7;
ctx.beginPath();
ctx.moveTo(ca.x1, ca.y1);
ctx.lineTo(endLX, endLY);
ctx.strokeStyle = ca.color + hexAlpha(lineAlpha);
ctx.lineWidth = 2;
ctx.stroke();

ctx.beginPath();
ctx.moveTo(ca.x2, ca.y2);
ctx.lineTo(endRX, endRY);
ctx.strokeStyle = ca.color + hexAlpha(lineAlpha);
ctx.lineWidth = 2;
ctx.stroke();

for (const sp of ca.sparkles) {
const spProgress = Math.min(1, progress * 1.5);
const sx = ca.x1 + (ca.x2 - ca.x1) * sp.t * spProgress;
const sy = ca.y1 + (ca.y2 - ca.y1) * sp.t * spProgress;
const sparkleAlpha = Math.sin(progress * Math.PI) * 0.8 * (1 - Math.abs(sp.t - 0.5) * 1.5);
if (sparkleAlpha <= 0) continue;
const offY = Math.sin(t * 0.01 + sp.phase) * sp.offset;
ctx.beginPath();
ctx.arc(sx, sy + offY, 1.5, 0, Math.PI * 2);
ctx.fillStyle = `rgba(255,255,255,${sparkleAlpha})`;
ctx.fill();
}
}
}

// --- Shatter animation for broken allied treaties ---
function drawShatter(t) {
for (let i = shatterAnims.length - 1; i >= 0; i--) {
const sa = shatterAnims[i];
const elapsed = t - sa.born;
if (elapsed > sa.duration) { shatterAnims.splice(i, 1); continue; }
const progress = elapsed / sa.duration;
for (const frag of sa.fragments) {
frag.x += frag.vx;
frag.y += frag.vy;
frag.vx *= 0.97;
frag.vy *= 0.97;
frag.alpha = (1 - progress) * 0.8;
ctx.beginPath();
ctx.arc(frag.x, frag.y, 1.5 * (1 - progress), 0, Math.PI * 2);
const c = hexToRgb(sa.color);
ctx.fillStyle = `rgba(${(c&&c.r)||200},${(c&&c.g)||200},${(c&&c.b)||255},${frag.alpha})`;
ctx.fill();
}
if (progress < 0.15) {
const flashA = (1 - progress / 0.15) * 0.4;
const mx = (sa.x1 + sa.x2) / 2, my = (sa.y1 + sa.y2) / 2;
const fg = ctx.createRadialGradient(mx, my, 0, mx, my, 40);
fg.addColorStop(0, `rgba(255,255,255,${flashA})`);
fg.addColorStop(1, `rgba(255,255,255,0)`);
ctx.beginPath();
ctx.arc(mx, my, 40, 0, Math.PI * 2);
ctx.fillStyle = fg;
ctx.fill();
}
}
}

// --- Cascade chain visualization ---
function drawCascadeChains(t) {
for (let i = cascadeChains.length - 1; i >= 0; i--) {
const cc = cascadeChains[i];
const elapsed = t - cc.born;
if (elapsed > cc.duration) { cascadeChains.splice(i, 1); continue; }
const progress = elapsed / cc.duration;
const alpha = (1 - progress) * 0.7;

ctx.save();
ctx.setLineDash([6, 4]);
cc.dashOffset = -t * 0.05;
ctx.lineDashOffset = cc.dashOffset;
ctx.beginPath();
ctx.moveTo(cc.x1, cc.y1);
ctx.lineTo(cc.x2, cc.y2);
const c = hexToRgb(cc.color);
ctx.strokeStyle = `rgba(${(c&&c.r)||79},${(c&&c.g)||195},${(c&&c.b)||247},${alpha})`;
ctx.lineWidth = 2;
ctx.stroke();
ctx.restore();

const pulseT = ((t * 0.004) % 1);
const px = cc.x1 + (cc.x2 - cc.x1) * pulseT;
const py = cc.y1 + (cc.y2 - cc.y1) * pulseT;
ctx.beginPath();
ctx.arc(px, py, 3, 0, Math.PI * 2);
ctx.fillStyle = `rgba(255,255,255,${alpha * 0.6})`;
ctx.fill();
}
}

// --- Quest spinning rings around active NPC stars ---
function drawQuestRings(t) {
for (let i = questRings.length - 1; i >= 0; i--) {
const qr = questRings[i];
const node = nodes.find(n => n.id === qr.nodeId);
if (!node) { questRings.splice(i, 1); continue; }
qr.phase = (qr.phase + 0.02) % (Math.PI * 2);
const r = node.radius + 6;
const arcLen = Math.PI * 0.6;
const fInfo = FACTION_MAP[node.faction];
const c = hexToRgb(fInfo ? fInfo.color : node.color);
const colorStr = c ? `rgba(${c.r},${c.g},${c.b}` : 'rgba(200,200,255';

for (let a = 0; a < 3; a++) {
const startAngle = qr.phase + (a * Math.PI * 2 / 3);
ctx.beginPath();
ctx.arc(node.x, node.y, r, startAngle, startAngle + arcLen);
ctx.strokeStyle = `${colorStr},0.4)`;
ctx.lineWidth = 1.5;
ctx.stroke();
}
}
}

// --- Tech progress arcs around faction brightest stars ---
function drawTechArcs(t) {
for (const [fid, fdata] of Object.entries(factionTechData)) {
const ar = fdata.active_research;
const research = ar ? ar.technology : null;
const progress = ar ? ar.progress_percentage : 0;
if (!research || !progress || progress <= 0) continue;
const fInfo = FACTION_MAP[fid];
if (!fInfo) continue;
const fi = FACTIONS.indexOf(fInfo);
const cx = W / 2, cy = H / 2, fR = Math.min(W, H) * 0.30;
const angle = (fi / 8) * Math.PI * 2 - Math.PI / 2;
const fx = cx + Math.cos(angle) * fR;
const fy = cy + Math.sin(angle) * fR;
const arcR = 14;
const arcProgress = Math.min(progress, 100) / 100;
const startA = -Math.PI / 2;
const endA = startA + arcProgress * Math.PI * 2;
const c = hexToRgb(fInfo.color);
const colorStr = c ? `rgba(${c.r},${c.g},${c.b}` : 'rgba(200,200,255';

ctx.beginPath();
ctx.arc(fx, fy, arcR, 0, Math.PI * 2);
ctx.strokeStyle = `${colorStr},0.08)`;
ctx.lineWidth = 2;
ctx.stroke();

ctx.beginPath();
ctx.arc(fx, fy, arcR, startA, endA);
ctx.strokeStyle = `${colorStr},0.55)`;
ctx.lineWidth = 2;
ctx.stroke();

const tipX = fx + Math.cos(endA) * arcR;
const tipY = fy + Math.sin(endA) * arcR;
ctx.beginPath();
ctx.arc(tipX, tipY, 2.5, 0, Math.PI * 2);
ctx.fillStyle = `${colorStr},0.7)`;
ctx.fill();
}
}

// ============================================================
// COLOR UTILITIES
// ============================================================
function hexAlpha(a) {
return Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, '0');
}

function lighten(hex, amt) {
const c = hexToRgb(hex);
if (!c) return hex;
const r = Math.min(255,c.r+amt);
const g = Math.min(255,c.g+amt);
const b = Math.min(255,c.b+amt);
return '#' + [r,g,b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
}

function darken(hex, amt) {
const c = hexToRgb(hex);
if (!c) return hex;
const r = Math.max(0,c.r-amt);
const g = Math.max(0,c.g-amt);
const b = Math.max(0,c.b-amt);
return '#' + [r,g,b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
}

function hexToRgb(hex) {
if (!hex) return null;
let c = hex.replace('#','');
if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
if (c.length > 6) c = c.substring(0,6);
const n = parseInt(c, 16);
if (isNaN(n)) return null;
return { r:(n>>16)&0xff, g:(n>>8)&0xff, b:n&0xff };
}

function modulateColor(baseHex, tensionTint, anomalyTint) {
const c = hexToRgb(baseHex);
if (!c) return baseHex;
const r = Math.min(255, c.r + tensionTint * 40 + anomalyTint * 20);
const g = Math.max(0, c.g - tensionTint * 30);
const b = Math.min(255, c.b + anomalyTint * 40);
return '#' + [r,g,b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
}

// ============================================================
// START
// ============================================================
init();