// ── Configuration ──
const API = '';
const POLL_INTERVAL = 10000;
let commsMessages = [];
let audioCtx = null;
let isMuted = localStorage.getItem('federation-muted') === 'true';

// ── Fetch Helpers ──
const fetchHealth = { ok: 0, fail: 0, lastOk: 0, lastFail: 0 };

async function apiFetch(path, opts = {}) {
  try {
    const r = await fetch(API + path, { ...opts, headers: { 'Accept': 'application/json', ...(opts.headers || {}) } });
    if (!r.ok) throw new Error(r.status);
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('text/html')) {
      throw new Error('Server returned HTML instead of JSON (endpoint may be misconfigured)');
    }
    fetchHealth.ok++;
    fetchHealth.lastOk = Date.now();
    return await r.json();
  } catch (e) {
    fetchHealth.fail++;
    fetchHealth.lastFail = Date.now();
    updateLinkHealth();
    return null;
  }
}

function updateLinkHealth() {
  const dot = document.getElementById('lh-dot');
  const label = document.getElementById('lh-label');
  const recent = fetchHealth.ok + fetchHealth.fail > 0;
  const failRate = recent ? fetchHealth.fail / (fetchHealth.ok + fetchHealth.fail) : 0;
  if (failRate > 0.5) { dot.className = 'crit'; label.className = 'crit'; label.textContent = 'LINK CRIT'; }
  else if (failRate > 0.2) { dot.className = 'warn'; label.className = 'warn'; label.textContent = 'LINK WARN'; }
  else { dot.className = 'ok'; label.className = 'ok'; label.textContent = 'LINK OK'; }
}

// ── Toast ──
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

// ── Audio ──
function initAudio() {
  if (audioCtx) return;
  try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch(e) {}
}
function playTone(freq, dur, vol, type) {
  if (!audioCtx || isMuted) return;
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(vol || 0.05, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + dur);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(); osc.stop(audioCtx.currentTime + dur);
  } catch(e) {}
}
function toggleMute() {
  isMuted = !isMuted;
  localStorage.setItem('federation-muted', isMuted);
  const btn = document.getElementById('audio-toggle');
  if (isMuted) { btn.classList.add('muted'); btn.setAttribute('aria-label', 'Audio muted — click to unmute'); }
  else { btn.classList.remove('muted'); btn.setAttribute('aria-label', 'Audio on — click to mute'); }
  showToast(isMuted ? 'Audio muted' : 'Audio enabled');
}

// ── World Canvas (Earth visualization) ──
let canvas, ctx, particles = [];
const WORLD_PARTICLES = 80;

function initCanvas() {
  canvas = document.getElementById('world-canvas');
  ctx = canvas.getContext('2d');
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
  for (let i = 0; i < WORLD_PARTICLES; i++) {
    particles.push({
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.0003,
      vy: (Math.random() - 0.5) * 0.0003,
      size: Math.random() * 2 + 0.5,
      alpha: Math.random() * 0.4 + 0.1
    });
  }
  animateCanvas();
}

function resizeCanvas() {
  if (!canvas) return;
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
}

function animateCanvas() {
  if (!ctx || !canvas) return;
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  // Draw subtle grid
  ctx.strokeStyle = 'rgba(79,195,247,0.03)';
  ctx.lineWidth = 1;
  const gridSize = 60;
  for (let x = 0; x < w; x += gridSize) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = 0; y < h; y += gridSize) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

  // Draw Earth glow (center)
  const cx = w / 2, cy = h / 2;
  const r = Math.min(w, h) * 0.25;
  const grd = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
  grd.addColorStop(0, 'rgba(79,195,247,0.08)');
  grd.addColorStop(0.5, 'rgba(79,195,247,0.03)');
  grd.addColorStop(1, 'rgba(79,195,247,0)');
  ctx.fillStyle = grd;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();

  // Inner ring
  ctx.strokeStyle = 'rgba(79,195,247,0.1)';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.6, 0, Math.PI * 2); ctx.stroke();

  // Outer ring
  ctx.strokeStyle = 'rgba(79,195,247,0.06)';
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.9, 0, Math.PI * 2); ctx.stroke();

  // Orbiting dots
  const t = Date.now() * 0.001;
  for (let i = 0; i < 3; i++) {
    const angle = t * (0.2 + i * 0.15) + i * 2.1;
    const orbitR = r * (0.5 + i * 0.15);
    const dx = cx + Math.cos(angle) * orbitR;
    const dy = cy + Math.sin(angle) * orbitR;
    ctx.fillStyle = `rgba(79,195,247,${0.3 + i * 0.15})`;
    ctx.beginPath(); ctx.arc(dx, dy, 2, 0, Math.PI * 2); ctx.fill();
  }

  // Particles
  for (const p of particles) {
    p.x += p.vx; p.y += p.vy;
    if (p.x < 0) p.x = 1; if (p.x > 1) p.x = 0;
    if (p.y < 0) p.y = 1; if (p.y > 1) p.y = 0;
    ctx.fillStyle = `rgba(79,195,247,${p.alpha})`;
    ctx.beginPath(); ctx.arc(p.x * w, p.y * h, p.size, 0, Math.PI * 2); ctx.fill();
  }

  requestAnimationFrame(animateCanvas);
}

// ── Data Fetching ──
async function fetchState() {
  const data = await apiFetch('/state');
  if (!data) return;
  // Top ribbon
  setBar('bar-trust', 'val-trust', data.public_trust, 100);
  setBar('bar-stability', 'val-stability', data.federation_stability, 100);
  setBar('bar-integrity', 'val-integrity', data.constitutional_integrity, 100);
  setBar('bar-rights', 'val-rights', data.rights_protection, 100);
  // Left governance
  setStat('sv-trust', 'sbar-trust', data.public_trust, 100);
  setStat('sv-council', 'sbar-council', data.council_support, 100);
  setStat('sv-integrity', 'sbar-integrity', data.constitutional_integrity, 100);
  setStat('sv-rights', 'sbar-rights', data.rights_protection, 100);
  setStat('sv-emergency', 'sbar-emergency', data.emergency_powers, 100);
  document.getElementById('sv-policy').textContent = data.active_policy || 'None';
  // Era
  if (data.governance_status) document.getElementById('top-era').textContent = data.governance_status.toUpperCase();
  // Condition: federation from state
  setCondCard('cv-fed', 'cf-fed', data.federation_stability, 100);
  // Comms
  if (data.last_decision) addComms(`Decision: ${data.last_decision}`);
  if (data.proposal_history && data.proposal_history.length) {
    const latest = data.proposal_history[data.proposal_history.length - 1];
    addComms(`Proposal: ${latest.policy || latest.type || 'new'}`);
  }
  return data;
}

async function fetchWorldState() {
  const data = await apiFetch('/world/state');
  if (!data || !data.state) return;
  const s = data.state;
  if (s.tension_level !== undefined) setCondCard('cv-tension', 'cf-tension', s.tension_level, 100);
  if (s.stability !== undefined) setCondCard('cv-stability', 'cf-stability', s.stability, 100);
  if (s.morale !== undefined) setCondCard('cv-morale', 'cf-morale', s.morale, 100);
  if (s.threat_level !== undefined) setCondCard('cv-threat', 'cf-threat', s.threat_level, 100);
  if (s.anomaly_activity !== undefined) setCondCard('cv-anomaly', 'cf-anomaly', s.anomaly_activity, 100);
  return data;
}

async function fetchWorldConditions() {
  const data = await apiFetch('/world/conditions');
  if (!data || !data.conditions) return data;
  // conditions is an array of {id, label, description, current, min, max}
  // We already show the main 5 from /world/state — this provides extras if any
  return data;
}

async function fetchPolitical() {
  const data = await apiFetch('/political');
  if (!data) return;
  document.getElementById('pol-status').textContent = data.system_available ? 'Online' : 'Offline';
  document.getElementById('pol-status').style.color = data.system_available ? 'var(--green)' : 'var(--dim)';
  if (data.status) {
    document.getElementById('pol-laws').textContent = (data.status.laws_processed != null ? data.status.laws_processed : (data.status.total_laws != null ? data.status.total_laws : '--'));
  }
  return data;
}

async function fetchFactions() {
  const data = await apiFetch('/factions');
  if (!data || !data.factions) return;
  const panel = document.getElementById('faction-panel');
  let html = '';
  for (const f of data.factions) {
    const inf = Math.min(100, Math.max(0, f.influence || f.power || 50));
    const color = inf > 70 ? 'var(--amber)' : inf > 40 ? 'var(--cyan)' : 'var(--dim)';
    html += `<div class="faction-row">
      <span class="faction-name" title="${f.name}">${f.name}</span>
      <div class="faction-bar"><div class="faction-fill" style="background:${color};width:${inf}%"></div></div>
      <span class="faction-val" style="color:${color}">${inf}</span>
    </div>`;
  }
  panel.innerHTML = html || '<div style="color:var(--dim);font-size:10px">No faction data</div>';
  return data;
}

async function fetchConsciousness() {
  const data = await apiFetch('/consciousness');
  if (!data || !data.system_available) return;
  setCC('cc-coherence', 'ccv-coherence', (data.morale != null ? data.morale : data.coherence), 100);
  setCC('cc-stability', 'ccv-stability', (data.stability != null ? data.stability : data.identity), 100);
  setCC('cc-awakeness', 'ccv-awakeness', (data.confidence != null ? data.confidence : data.awakeness), 100);
  setCC('cc-anxiety', 'ccv-anxiety', data.anxiety, 100);
  setCC('cc-diplomacy', 'ccv-diplomacy', data.diplomacy_tendency, 100);
  return data;
}

async function fetchHistoryArc() {
  const data = await apiFetch('/history-arc');
  if (!data) return;
  document.getElementById('era-name').textContent = (data.current_era || '--').toUpperCase() + ' ERA';
  document.getElementById('era-year').textContent = 'YEAR ' + (data.year != null ? data.year : '--');
  document.getElementById('era-status').textContent = data.initialized ? 'ACTIVE' : 'DORMANT';
  document.getElementById('era-status').style.color = data.initialized ? 'var(--green)' : 'var(--dim)';
  if (data.current_era) document.getElementById('top-era').textContent = data.current_era.toUpperCase();
  return data;
}

async function fetchQuests() {
  const data = await apiFetch('/quests');
  if (!data) return;
  const panel = document.getElementById('quest-panel');
  let html = '';
  // Active quests
  if (data.active && data.active.length) {
    for (const q of data.active.slice(0, 5)) {
      html += `<div class="quest-entry"><span class="q-title">${q.name || q.title || q.id}</span> <span class="q-status">ACTIVE</span></div>`;
    }
  }
  // Available quests
  if (data.available && data.available.length) {
    for (const q of data.available.slice(0, 3)) {
      html += `<div class="quest-entry" style="border-left-color:var(--amber)"><span class="q-title">${q.name || q.title || q.id}</span> <span class="q-status">AVAILABLE</span></div>`;
    }
  }
  if (!html) html = '<div style="color:var(--dim);font-size:10px">No active quests</div>';
  panel.innerHTML = html;
  return data;
}

async function fetchMapData() {
  const data = await apiFetch('/map/data');
  if (!data) return;
  // Extract recent events for the events panel
  const events = data.events || [];
  const panel = document.getElementById('events-panel');
  if (events.length) {
    let html = '';
    for (const e of events.slice(0, 8)) {
      const domain = e.domain || e.category || '';
      const color = domain.includes('rival') || domain.includes('hostile') ? 'var(--red)' :
                    domain.includes('constitutional') ? 'var(--violet)' :
                    domain.includes('consciousness') ? 'var(--green)' : 'var(--dim)';
      html += `<div style="padding:2px 0;border-bottom:1px solid rgba(79,195,247,0.04)"><span style="color:${color};font-size:9px">${domain.toUpperCase()}</span> <span>${e.title || (e.description && e.description.substring(0,40)) || 'Event'}</span></div>`;
    }
    panel.innerHTML = html;
  } else {
    panel.innerHTML = '<div style="color:var(--dim);font-size:10px">No recent events</div>';
  }
  // Use world_state from map if available
  if (data.world_state) {
    const ws = data.world_state;
    if (ws.tension_level !== undefined) setCondCard('cv-tension', 'cf-tension', ws.tension_level, 100);
    if (ws.stability !== undefined) setCondCard('cv-stability', 'cf-stability', ws.stability, 100);
    if (ws.morale !== undefined) setCondCard('cv-morale', 'cf-morale', ws.morale, 100);
    if (ws.threat_level !== undefined) setCondCard('cv-threat', 'cf-threat', ws.threat_level, 100);
    if (ws.anomaly_activity !== undefined) setCondCard('cv-anomaly', 'cf-anomaly', ws.anomaly_activity, 100);
  }
  return data;
}

async function fetchTechnology() {
  const data = await apiFetch('/technology');
  if (!data) return;
  const panel = document.getElementById('tech-panel');
  let html = '';
  if (data.completed && data.completed.length) {
    html += `<div style="color:var(--green);font-size:9px;letter-spacing:1px;font-family:'Orbitron',sans-serif;margin-bottom:4px">COMPLETED (${data.completed.length})</div>`;
    for (const t of data.completed.slice(0, 4)) {
      html += `<div style="font-size:10px;color:var(--dim);padding:1px 0">✓ ${t.name || t.id}</div>`;
    }
  }
  if (data.available && data.available.length) {
    html += `<div style="color:var(--cyan);font-size:9px;letter-spacing:1px;font-family:'Orbitron',sans-serif;margin:4px 0">AVAILABLE (${data.available.length})</div>`;
    for (const t of data.available.slice(0, 4)) {
      html += `<div style="font-size:10px;color:var(--dim);padding:1px 0">○ ${t.name || t.id} <span style="color:var(--amber)">T${t.tier || '?'}</span></div>`;
    }
  }
  if (!html) html = '<div style="color:var(--dim);font-size:10px">No technology data</div>';
  panel.innerHTML = html;
  return data;
}

// ── UI Helpers ──
function setBar(barId, valId, value, max) {
  const v = Math.max(0, Math.min(max, value || 0));
  const pct = (v / max * 100).toFixed(0);
  const bar = document.getElementById(barId);
  const val = document.getElementById(valId);
  if (bar) bar.style.width = pct + '%';
  if (val) val.textContent = Math.round(v);
}

function setStat(valId, barId, value, max) {
  const v = Math.max(0, Math.min(max, value || 0));
  const pct = (v / max * 100).toFixed(0);
  const val = document.getElementById(valId);
  const bar = document.getElementById(barId);
  if (val) val.textContent = Math.round(v);
  if (bar) bar.style.width = pct + '%';
}

function setCondCard(valId, fillId, value, max) {
  const v = Math.max(0, Math.min(max, value || 0));
  const pct = (v / max * 100).toFixed(0);
  const val = document.getElementById(valId);
  const fill = document.getElementById(fillId);
  if (val) val.textContent = Math.round(v);
  if (fill) fill.style.width = pct + '%';
}

function setCC(fillId, valId, value, max) {
  const v = Math.max(0, Math.min(max, value || 0));
  const pct = (v / max * 100).toFixed(0);
  const fill = document.getElementById(fillId);
  const val = document.getElementById(valId);
  if (fill) fill.style.width = pct + '%';
  if (val) val.textContent = Math.round(v);
}

function addComms(msg) {
  commsMessages.push(msg);
  if (commsMessages.length > 20) commsMessages.shift();
  const ticker = document.getElementById('comms-ticker');
  ticker.innerHTML = commsMessages.map(m => `<span class="comms-msg">${m}</span>`).join('');
}

// ── Action Handlers ──
async function processPoliticalTurn() {
  playTone(600, 0.15, 0.05);
  showToast('Processing political year...');
  const data = await apiFetch('/political/process-turn', { method: 'POST' });
  if (data) {
    showToast('Political year processed');
    addComms('Political year processed');
    fetchPolitical(); fetchState();
  } else {
    showToast('Political process failed');
  }
}

async function advanceHistoryArc() {
  playTone(500, 0.15, 0.05);
  showToast('Advancing timeline...');
  const data = await apiFetch('/history-arc/advance', { method: 'POST' });
  if (data) {
    showToast('Timeline advanced');
    addComms('Timeline advanced');
    fetchHistoryArc(); fetchState();
  } else {
    showToast('Timeline advance failed');
  }
}

async function saveState() {
  playTone(700, 0.1, 0.05);
  showToast('Saving snapshot...');
  const data = await apiFetch('/state/save', { method: 'POST' });
  if (data && data.status === 'saved') {
    showToast('State saved');
    addComms('State snapshot saved');
  } else {
    showToast('Save failed');
  }
}

async function loadState() {
  playTone(400, 0.1, 0.05);
  showToast('Loading state...');
  const data = await apiFetch('/state/load');
  if (data) {
    showToast('State loaded');
    addComms('State restored from snapshot');
    fetchState(); fetchWorldState(); fetchHistoryArc(); fetchConsciousness();
  } else {
    showToast('Load failed');
  }
}

// ── Main Init ──
async function init() {
  initCanvas();
  // Initial data fetch (parallel)
  await Promise.all([
    fetchState(),
    fetchWorldState(),
    fetchPolitical(),
    fetchFactions(),
    fetchConsciousness(),
    fetchHistoryArc(),
    fetchQuests(),
    fetchMapData(),
    fetchTechnology(),
  ]);
  addComms('Earth Command online — all systems nominal');

  // Polling loop
  setInterval(async () => {
    await Promise.all([
      fetchState(),
      fetchWorldState(),
      fetchPolitical(),
      fetchFactions(),
      fetchConsciousness(),
      fetchHistoryArc(),
      fetchQuests(),
      fetchMapData(),
      fetchTechnology(),
    ]);
  }, POLL_INTERVAL);
}

// Audio init on first interaction
document.addEventListener('click', function audioInit() {
  if (!audioCtx) initAudio();
  if (isMuted && audioCtx) { /* state already saved */ }
  document.removeEventListener('click', audioInit);
}, { once: true });

// Audio toggle button
const audioBtn = document.getElementById('audio-toggle');
if (isMuted) { audioBtn.classList.add('muted'); audioBtn.setAttribute('aria-label', 'Audio muted — click to unmute'); }
audioBtn.addEventListener('click', function(e) {
  e.stopPropagation();
  if (!audioCtx) initAudio();
  toggleMute();
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (!audioCtx) initAudio();
  if (e.key === 'm' || e.key === 'M') { toggleMute(); e.preventDefault(); return; }
  if (e.key === 'p' || e.key === 'P') { processPoliticalTurn(); e.preventDefault(); return; }
  if (e.key === 't' || e.key === 'T') { advanceHistoryArc(); e.preventDefault(); return; }
  if (e.key === 's' || e.key === 'S') { saveState(); e.preventDefault(); return; }
  if (e.key === 'l' || e.key === 'L') { loadState(); e.preventDefault(); return; }
});

// Start
init();