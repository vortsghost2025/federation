const API = '';
let currentEvent = null;
let gameState = null;
let consciousness = null;
let currentChoiceToken = null;
let rivalsData = null;
let factionsData = null;
let decisionLog = [];
let timelineData = null;
let stars = [];
let canvas, ctx, W, H;
let tick = 0;
let currentAlert = 'green';
let audioCtx = null;
let bridgeHum = null;
let humGain = null;
let isMuted = localStorage.getItem('federation-muted') === 'true';
let savedHumLevel = 0.05;

// ============ FETCH HEALTH TRACKER ============
const fetchHealth = {};
const FETCH_PANELS = {
  state:         { panel: 'ct-ship',          label: 'STATE' },
  event:         { panel: null,               label: 'EVENT' },
  consciousness: { panel: 'ct-consciousness',  label: 'CONSC' },
  rivals:        { panel: 'ct-rivals',         label: 'RIVALS' },
  factions:      { panel: 'ct-faction',        label: 'FACTIONS' },
  map:           { panel: 'ct-events',         label: 'MAP' },
  log:           { panel: 'ct-timeline',       label: 'LOG' },
  timeline:      { panel: 'ct-timeline',       label: 'TIMELINE' },
  choose:        { panel: null,                label: 'CHOOSE' },
};

function initFetchHealth(key) {
  if (!fetchHealth[key]) {
    fetchHealth[key] = { ok: true, lastOk: null, lastFail: null, failCount: 0, retrying: false, retryTimer: null };
  }
}

function recordFetchOk(key) {
  initFetchHealth(key);
  const h = fetchHealth[key];
  h.ok = true;
  h.lastOk = Date.now();
  h.failCount = 0;
  h.retrying = false;
  if (h.retryTimer) { clearTimeout(h.retryTimer); h.retryTimer = null; }
  updateStaleBadge(key);
}

function recordFetchFail(key) {
  initFetchHealth(key);
  const h = fetchHealth[key];
  h.ok = false;
  h.lastFail = Date.now();
  h.failCount++;
  h.retrying = true;
  // Auto-retry with backoff: 5s, 10s, 20s, 30s cap
  const delay = Math.min(5000 * Math.pow(1.5, h.failCount - 1), 30000);
  if (h.retryTimer) clearTimeout(h.retryTimer);
  h.retryTimer = setTimeout(() => {
    h.retrying = false;
    retryFetch(key);
  }, delay);
  updateStaleBadge(key);
  updateLinkHealth();
}

function retryFetch(key) {
  // Trigger the corresponding fetch function again
  const retryMap = {
    state: fetchState, event: fetchEvent, consciousness: fetchConsciousness,
    rivals: fetchRivals, factions: fetchFactions, map: fetchMapEvents,
    log: fetchDecisionLog, timeline: fetchTimeline
  };
  if (retryMap[key]) retryMap[key]();
}

function timeAgo(ts) {
  if (!ts) return '--';
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 5) return 'now';
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  return m + 'm';
}

function updateStaleBadge(key) {
  const cfg = FETCH_PANELS[key];
  if (!cfg || !cfg.panel) return;
  const titleEl = document.getElementById(cfg.panel);
  if (!titleEl) return;

  const h = fetchHealth[key];
  if (!h) return;

  // Remove existing badge
  const existing = titleEl.querySelector('.stale-badge');
  if (existing) existing.remove();

  if (h.ok && h.failCount === 0) {
    // All good — no badge needed (or brief "OK" flash)
    return;
  }

  const badge = document.createElement('span');
  if (!h.ok) {
    const isCrit = h.failCount >= 3;
    badge.className = `stale-badge ${isCrit ? 'stale-crit' : 'stale-warn'}`;
    let text = isCrit ? 'LINK LOST' : 'STALE';
    if (h.retrying) text += ' ↻';
    badge.textContent = text;
    // Timestamp of last good data
    if (h.lastOk) {
      const ts = document.createElement('span');
      ts.className = 'stale-ts';
      ts.textContent = timeAgo(h.lastOk);
      badge.appendChild(ts);
    }
  } else if (h.failCount > 0) {
    // Recovered — show brief recovery indicator
    badge.className = 'stale-badge stale-ok';
    badge.textContent = 'RESTORED';
    // Auto-remove after 5s
    setTimeout(() => { if (badge.parentNode) badge.remove(); }, 5000);
  }
  titleEl.appendChild(badge);
}

function updateLinkHealth() {
  const keys = Object.keys(fetchHealth);
  const failed = keys.filter(k => !fetchHealth[k].ok);
  const critFailed = keys.filter(k => !fetchHealth[k].ok && fetchHealth[k].failCount >= 3);

  const dot = document.getElementById('lh-dot');
  const label = document.getElementById('lh-label');

  if (critFailed.length > 0) {
    dot.className = 'crit';
    label.className = 'crit';
    label.textContent = 'LINK CRIT';
  } else if (failed.length > 0) {
    dot.className = 'warn';
    label.className = 'warn';
    label.textContent = 'LINK WARN';
  } else {
    dot.className = 'ok';
    label.className = 'ok';
    label.textContent = 'LINK OK';
  }
}

// Wrapping fetch helper with health tracking
async function trackedFetch(key, url, opts) {
  var fedOpts = Object.assign({}, opts, { timeout: 10000, retries: 2, retryDelay: 2000 });
  var data = await fedFetch(key, url, fedOpts);
  if (data !== null) {
    recordFetchOk(key);
    updateLinkHealth();
    return data;
  }
  recordFetchFail(key);
  updateLinkHealth();
  return null;
}

const METRIC_LABELS = {
  credits:'Credits', fuel:'Fuel', shields:'Shields', hull:'Hull',
  crew_morale:'Morale', discovered_sectors:'Sectors', allies:'Allies',
  federation_stability:'Stability', public_trust:'Trust',
  council_support:'Council', constitutional_integrity:'Integrity',
  rights_protection:'Rights', emergency_powers:'Emergency',
  active_policy:'Policy'
};

// Faction colors for radar chart
const FACTION_COLORS = {
  diplomatic_corps: '#4fc3f7',
  military_command: '#ff1744',
  cultural_ministry: '#b388ff',
  research_division: '#69f0ae',
  consciousness_collective: '#e040fb',
  economic_council: '#ff9e1c',
  exploration_initiative: '#00e5ff',
  preservation_society: '#8d6e63'
};

const FACTION_SHORT = {
  diplomatic_corps: 'DIPLO',
  military_command: 'MIL',
  cultural_ministry: 'CULT',
  research_division: 'RESEARCH',
  consciousness_collective: 'CONSC',
  economic_council: 'ECON',
  exploration_initiative: 'EXPLORE',
  preservation_society: 'PRESERVE'
};

// Domain → transition animation mapping
const DOMAIN_TRANSITIONS = {
  'diplomacy': 'anim-diplomacy',
  'diplomatic': 'anim-diplomacy',
  'governance': 'anim-governance',
  'government': 'anim-governance',
  'political': 'anim-governance',
  'military': 'anim-hostile',
  'defense': 'anim-hostile',
  'war': 'anim-hostile',
  'hostile': 'anim-hostile',
  'combat': 'anim-hostile',
  'economy': 'anim-economy',
  'economic': 'anim-economy',
  'trade': 'anim-economy',
  'anomaly': 'anim-anomaly',
  'exploration': 'anim-anomaly',
  'science': 'anim-anomaly',
  'research': 'anim-anomaly',
  'operations': 'anim-economy',
  'intelligence': 'anim-diplomacy',
  'culture': 'anim-diplomacy',
  'preservation': 'anim-anomaly',
};

// ============ AUDIO ENGINE ============
function initAudio() {
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    // Bridge hum — low continuous drone
    humGain = audioCtx.createGain();
    humGain.gain.value = 0;
    humGain.connect(audioCtx.destination);

    // Create hum from two detuned oscillators
    const osc1 = audioCtx.createOscillator();
    osc1.type = 'sine';
    osc1.frequency.value = 55; // A1
    const osc2 = audioCtx.createOscillator();
    osc2.type = 'sine';
    osc2.frequency.value = 55.5; // slight detune for richness
    const subOsc = audioCtx.createOscillator();
    subOsc.type = 'sine';
    subOsc.frequency.value = 27.5; // sub-bass

    const humMix = audioCtx.createGain();
    humMix.gain.value = 0.12;
    osc1.connect(humMix);
    osc2.connect(humMix);
    subOsc.connect(humMix);
    humMix.connect(humGain);

    osc1.start();
    osc2.start();
    subOsc.start();

    // Fade in hum gently
    humGain.gain.setTargetAtTime(0.06, audioCtx.currentTime, 2);
    bridgeHum = { osc1, osc2, subOsc, humMix };
  } catch(e) {
    // Audio not supported — fail silently
  }
}

function playTone(freq, duration, vol, type) {
  if (!audioCtx || isMuted) return;
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    gain.gain.value = vol || 0.08;
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + (duration || 0.3));
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + (duration || 0.3));
  } catch(e) {}
}

function playChoiceSound() {
  playTone(880, 0.1, 0.06, 'square');
  setTimeout(() => playTone(1100, 0.15, 0.04, 'sine'), 80);
}

function playAlertTone(level) {
  if (!audioCtx || isMuted) return;
  if (level === 'red') {
    playTone(440, 0.3, 0.1, 'sawtooth');
    setTimeout(() => playTone(440, 0.3, 0.1, 'sawtooth'), 350);
    setTimeout(() => playTone(440, 0.5, 0.12, 'sawtooth'), 700);
  } else if (level === 'crisis') {
    playTone(220, 0.5, 0.1, 'sawtooth');
    setTimeout(() => playTone(330, 0.5, 0.1, 'sawtooth'), 500);
    setTimeout(() => playTone(440, 0.8, 0.12, 'sawtooth'), 1000);
  } else if (level === 'yellow') {
    playTone(660, 0.2, 0.06, 'triangle');
    setTimeout(() => playTone(660, 0.2, 0.06, 'triangle'), 250);
  }
}

function playEventSound(domain) {
  const d = (domain || '').toLowerCase();
  if (d.includes('milit') || d.includes('war') || d.includes('hostile') || d.includes('combat') || d.includes('defense')) {
    playTone(150, 0.15, 0.08, 'sawtooth');
    setTimeout(() => playTone(200, 0.1, 0.06, 'square'), 100);
  } else if (d.includes('diplom') || d.includes('culture')) {
    playTone(523, 0.2, 0.05, 'sine');
    setTimeout(() => playTone(659, 0.25, 0.04, 'sine'), 150);
  } else if (d.includes('anomal') || d.includes('explor') || d.includes('research') || d.includes('science')) {
    playTone(1200, 0.3, 0.03, 'sine');
    playTone(900, 0.5, 0.02, 'triangle');
  } else if (d.includes('econ') || d.includes('trade')) {
    playTone(440, 0.1, 0.04, 'square');
    setTimeout(() => playTone(550, 0.1, 0.04, 'square'), 100);
    setTimeout(() => playTone(660, 0.15, 0.04, 'square'), 200);
  } else {
    playTone(440, 0.15, 0.04, 'triangle');
  }
}

function setHumLevel(level) {
  if (!humGain) return;
  const v = level === 'crisis' ? 0.12 : level === 'red' ? 0.10 : level === 'yellow' ? 0.07 : 0.05;
  savedHumLevel = v;
  humGain.gain.setTargetAtTime(isMuted ? 0 : v, audioCtx.currentTime, 1);
  if (bridgeHum) {
    const freq = level === 'crisis' ? 60 : level === 'red' ? 58 : 55;
    bridgeHum.osc1.frequency.setTargetAtTime(freq, audioCtx.currentTime, 0.5);
    bridgeHum.osc2.frequency.setTargetAtTime(freq + 0.5, audioCtx.currentTime, 0.5);
  }
}

function toggleMute() {
  isMuted = !isMuted;
  localStorage.setItem('federation-muted', isMuted);
  const btn = document.getElementById('audio-toggle');
  if (isMuted) {
    btn.classList.add('muted');
    btn.innerHTML = '&#9835;'; // music note with line through — we use CSS for that
    btn.setAttribute('aria-label', 'Audio muted — click to unmute');
    if (humGain) humGain.gain.setTargetAtTime(0, audioCtx.currentTime, 0.1);
  } else {
    btn.classList.remove('muted');
    btn.innerHTML = '&#9835;';
    btn.setAttribute('aria-label', 'Audio on — click to mute');
    if (humGain) humGain.gain.setTargetAtTime(savedHumLevel, audioCtx.currentTime, 0.3);
  }
}

// ============ ALERT STATE ENGINE ============
function computeAlertState(s, event) {
  const isConstitutionalCrisisEvent = event && (
    (event.constitutional_risk === 'high' || event.constitutional_risk === 'critical') ||
    (event.rights_at_stake && event.rights_at_stake.length >= 2) ||
    (event.domain && (event.domain.toLowerCase().includes('governance') || event.domain.toLowerCase().includes('constitution')))
  );
  if (isConstitutionalCrisisEvent ||
    (s.constitutional_integrity !== undefined && s.constitutional_integrity < 25) ||
    (s.rights_protection !== undefined && s.rights_protection < 20)) {
    return 'crisis';
  }

  const isHostileEvent = event && (
    event.image === 'alert' ||
    (event.domain && (event.domain.toLowerCase().includes('military') || event.domain.toLowerCase().includes('defense') || event.domain.toLowerCase().includes('war') || event.domain.toLowerCase().includes('hostile')))
  );
  if (isHostileEvent ||
    (s.emergency_powers > 60) ||
    (s.hull < 30) ||
    (s.fuel < 20) ||
    (s.federation_stability < 20) ||
    (s.public_trust < 20)) {
    return 'red';
  }

  const rivalMap = rivalsData && rivalsData.rivals && (rivalsData.rivals.rivals || rivalsData.rivals);
  const hasElevatedRivals = rivalMap &&
    Object.values(rivalMap).some(r => typeof r === 'object' && r !== null && r.relationships && r.relationships.player === 'hostile' && r.power > 0.6);
  if ((s.emergency_powers > 25) ||
    (s.crew_morale < 40) ||
    (s.federation_stability < 40) ||
    (s.public_trust < 40) ||
    (s.constitutional_integrity < 50) ||
    (s.rights_protection < 50) ||
    hasElevatedRivals) {
    return 'yellow';
  }

  return 'green';
}

function setAlertState(level) {
  if (level === currentAlert) return;
  const prevLevel = currentAlert;
  currentAlert = level;

  // Bridge container glow
  const bridge = document.getElementById('bridge');
  bridge.className = `alert-${level}`;

  // Top ribbon border
  const top = document.getElementById('top');
  top.className = `alert-border-${level}`;

  // Viewscreen alert overlay
  const vsAlert = document.getElementById('vs-alert');
  vsAlert.className = level;

  // Alert indicator label
  const indicator = document.getElementById('alert-indicator');
  const labels = { green: 'GREEN ALERT', yellow: 'YELLOW ALERT', red: 'RED ALERT', crisis: 'CONSTITUTIONAL CRISIS' };
  indicator.textContent = labels[level] || 'GREEN ALERT';
  indicator.className = level;

  // Audio feedback for escalation
  if (level !== 'green' && level !== prevLevel) {
    playAlertTone(level);
  }
  setHumLevel(level);

  // Comms notification for state changes
  addComms(labels[level]);
}

// ============ VIEWSCREEN TRANSITIONS ============
function playEventTransition(domain) {
  const trans = document.getElementById('vs-transition');
  trans.className = '';
  trans.style.opacity = '0';
  void trans.offsetHeight;

  const domainKey = (domain || '').toLowerCase();
  let animClass = 'anim-diplomacy';
  for (const [key, cls] of Object.entries(DOMAIN_TRANSITIONS)) {
    if (domainKey.includes(key)) {
      animClass = cls;
      break;
    }
  }

  trans.style.opacity = '1';
  trans.className = animClass;
}

// ============ STARFIELD ============
function initStarfield() {
  canvas = document.getElementById('vs-canvas');
  ctx = canvas.getContext('2d');
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
  for (let i = 0; i < 300; i++) {
    stars.push({
      x: Math.random() * 4000 - 500,
      y: Math.random() * 2000 - 200,
      z: Math.random() * 3 + 0.5,
      r: Math.random() * 1.2 + 0.3,
      b: Math.random() * 0.5 + 0.2
    });
  }
  requestAnimationFrame(drawStarfield);
}

function resizeCanvas() {
  const rect = document.getElementById('viewscreen').getBoundingClientRect();
  W = rect.width; H = rect.height;
  canvas.width = W * devicePixelRatio;
  canvas.height = H * devicePixelRatio;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
}

function drawStarfield() {
  tick += 0.005;
  ctx.fillStyle = '#040810';
  ctx.fillRect(0, 0, W, H);

  // Subtle nebula glow — tinted by alert state
  const nebulaColor = currentAlert === 'red' ? '255,23,68' :
    currentAlert === 'crisis' ? '179,136,255' :
    currentAlert === 'yellow' ? '255,158,28' : '79,195,247';
  const nebulaAlpha = currentAlert === 'red' ? 0.04 : currentAlert === 'crisis' ? 0.03 : 0.02;

  const nebulaGrad = ctx.createRadialGradient(W*0.3, H*0.4, 0, W*0.3, H*0.4, W*0.5);
  nebulaGrad.addColorStop(0, `rgba(${nebulaColor},${nebulaAlpha})`);
  nebulaGrad.addColorStop(1, 'transparent');
  ctx.fillStyle = nebulaGrad;
  ctx.fillRect(0, 0, W, H);

  const nebulaGrad2 = ctx.createRadialGradient(W*0.7, H*0.6, 0, W*0.7, H*0.6, W*0.4);
  nebulaGrad2.addColorStop(0, `rgba(${nebulaColor},${nebulaAlpha * 0.7})`);
  nebulaGrad2.addColorStop(1, 'transparent');
  ctx.fillStyle = nebulaGrad2;
  ctx.fillRect(0, 0, W, H);

  // Stars with drift
  for (const s of stars) {
    s.x -= s.z * 0.15;
    if (s.x < -10) s.x = W + 10;
    const twinkle = 0.5 + 0.5 * Math.sin(tick * 3 + s.x * 0.01);
    const alpha = s.b * twinkle;
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200,220,255,${alpha})`;
    ctx.fill();
  }

  // Grid lines (subtle tactical overlay)
  const gridAlpha = currentAlert === 'red' ? 0.06 : currentAlert === 'crisis' ? 0.05 : 0.03;
  ctx.strokeStyle = `rgba(${nebulaColor},${gridAlpha})`;
  ctx.lineWidth = 0.5;
  for (let x = 0; x < W; x += 80) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  for (let y = 0; y < H; y += 80) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  requestAnimationFrame(drawStarfield);
}

// ============ FACTION RADAR CHART ============
function drawFactionRadar(factions) {
  try {
  const c = document.getElementById('faction-radar');
  if (!c) return;
  const fctx = c.getContext('2d');
  if (!fctx) return;
  const dpr = window.devicePixelRatio || 1;

  // Size the canvas to its container
  const rect = c.parentElement.getBoundingClientRect();
  const cw = rect.width;
  const ch = 180;
  c.width = cw * dpr;
  c.height = ch * dpr;
  c.style.width = cw + 'px';
  c.style.height = ch + 'px';
  fctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const cx = cw / 2;
  const cy = ch / 2 + 8;
  const R = Math.min(cx, cy) - 24;
  const fKeys = Object.keys(factions);
  const n = fKeys.length;
  if (n < 3) return;

  fctx.clearRect(0, 0, cw, ch);

  // Draw concentric rings
  for (let ring = 1; ring <= 4; ring++) {
    const r = R * ring / 4;
    fctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
      const px = cx + r * Math.cos(angle);
      const py = cy + r * Math.sin(angle);
      if (i === 0) fctx.moveTo(px, py); else fctx.lineTo(px, py);
    }
    fctx.strokeStyle = `rgba(79,195,247,${ring === 4 ? 0.15 : 0.06})`;
    fctx.lineWidth = 0.5;
    fctx.stroke();
  }

  // Draw spokes and labels
  fctx.font = '8px "Share Tech Mono", monospace';
  fctx.textAlign = 'center';
  for (let i = 0; i < n; i++) {
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const ex = cx + R * Math.cos(angle);
    const ey = cy + R * Math.sin(angle);
    fctx.beginPath();
    fctx.moveTo(cx, cy);
    fctx.lineTo(ex, ey);
    fctx.strokeStyle = 'rgba(79,195,247,0.08)';
    fctx.lineWidth = 0.5;
    fctx.stroke();

    // Label
    const lx = cx + (R + 16) * Math.cos(angle);
    const ly = cy + (R + 16) * Math.sin(angle);
    const fk = fKeys[i];
    const label = FACTION_SHORT[fk] || fk.substring(0, 6).toUpperCase();
    fctx.fillStyle = FACTION_COLORS[fk] || '#607080';
    fctx.fillText(label, lx, ly + 3);
  }

  // Draw data polygon
  const values = fKeys.map(k => Math.max(0, factions[k].reputation || 0));
  fctx.beginPath();
  for (let i = 0; i <= n; i++) {
    const idx = i % n;
    const angle = (Math.PI * 2 * idx / n) - Math.PI / 2;
    const r = R * values[idx];
    const px = cx + r * Math.cos(angle);
    const py = cy + r * Math.sin(angle);
    if (i === 0) fctx.moveTo(px, py); else fctx.lineTo(px, py);
  }
  fctx.closePath();
  fctx.fillStyle = 'rgba(79,195,247,0.1)';
  fctx.fill();
  fctx.strokeStyle = 'rgba(79,195,247,0.5)';
  fctx.lineWidth = 1.5;
  fctx.stroke();

  // Draw data points with faction colors
  for (let i = 0; i < n; i++) {
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const r = R * values[i];
    const px = cx + r * Math.cos(angle);
    const py = cy + r * Math.sin(angle);
    fctx.beginPath();
    fctx.arc(px, py, 3, 0, Math.PI * 2);
    fctx.fillStyle = FACTION_COLORS[fKeys[i]] || '#4fc3f7';
    fctx.fill();
    fctx.strokeStyle = 'rgba(255,255,255,0.3)';
    fctx.lineWidth = 0.5;
    fctx.stroke();
  }

  // Center dot
  fctx.beginPath();
  fctx.arc(cx, cy, 2, 0, Math.PI * 2);
  fctx.fillStyle = 'rgba(255,158,28,0.5)';
  fctx.fill();
  } catch(e) {
    // Canvas rendering error — draw error indicator instead
    const c = document.getElementById('faction-radar');
    if (c) {
      const fctx2 = c.getContext('2d');
      if (fctx2) {
        fctx2.clearRect(0, 0, c.width, c.height);
        fctx2.fillStyle = 'rgba(255,23,68,0.3)';
        fctx2.font = '10px "Orbitron", sans-serif';
        fctx2.textAlign = 'center';
        fctx2.fillText('RADAR UNAVAILABLE', c.width / 4, 90);
      }
    }
  }
}

// ============ NPC DETAIL MODAL ============
async function openNpcModal(charId) {
  if (!charId || charId.trim() === '') return; // Guard: no empty char IDs
  const modal = document.getElementById('npc-modal');
  const body = document.getElementById('npc-modal-body');

  body.innerHTML = '<div style="color:var(--dim);text-align:center;padding:20px">Scanning...</div>';
  modal.classList.add('open');

  try {
    const npc = await trackedFetch('npc-' + charId, `${API}/npcs/${charId}`);

    if (!npc) {
      body.innerHTML = `<div style="color:var(--red);text-align:center;padding:20px">SCAN FAILED — ${charId}</div>`;
      return;
    }

    const affilColor = FACTION_COLORS[npc.affiliation] || '#607080';
    const affilName = npc.affiliation ? (FACTION_SHORT[npc.affiliation] || npc.affiliation.replace(/_/g,' ')) : 'UNAFFILIATED';
    const statusColor = npc.status === 'corrupted' ? 'var(--red)' : npc.status === 'active' ? 'var(--green)' : 'var(--dim)';

    let html = `
      <div class="npc-m-name">${npc.name || charId}</div>
      <div class="npc-m-title">${npc.title || ''}</div>
      <div class="npc-m-affil" style="color:${affilColor};border:1px solid ${affilColor}40;background:${affilColor}15">${affilName}</div>
      <div class="npc-m-stat"><span class="npc-m-stat-label">Status</span><span class="npc-m-stat-val" style="color:${statusColor}">${(npc.status || 'unknown').toUpperCase()}</span></div>
    `;

    if (npc.description) {
      html += `<div class="npc-m-desc">${npc.description}</div>`;
    }

    // Personality stats
    if (npc.personality) {
      html += `<div class="npc-m-section"><div class="npc-m-section-title">Personality Profile</div>`;
      for (const [k, v] of Object.entries(npc.personality)) {
        const pct = Math.round((v || 0) * 100);
        const barColor = v > 0.7 ? 'var(--amber)' : v > 0.4 ? 'var(--cyan)' : 'var(--dim)';
        html += `<div class="npc-m-stat"><span class="npc-m-stat-label">${k}</span>
          <div style="flex:1;margin:0 8px;height:4px;background:rgba(255,255,255,0.05);border-radius:2px;overflow:hidden">
            <div style="width:${pct}%;height:100%;background:${barColor};border-radius:2px"></div>
          </div>
          <span class="npc-m-stat-val">${pct}</span></div>`;
      }
      html += `</div>`;
    }

    // Relationship
    if (npc.relationship_to_player !== undefined) {
      const rel = npc.relationship_to_player;
      const relColor = rel > 0.3 ? 'var(--green)' : rel < -0.3 ? 'var(--red)' : 'var(--dim)';
      html += `<div class="npc-m-stat"><span class="npc-m-stat-label">Relationship</span><span class="npc-m-stat-val" style="color:${relColor}">${Math.round(rel * 100)}</span></div>`;
    }

    // Skills
    if (npc.skills && npc.skills.length) {
      html += `<div class="npc-m-section"><div class="npc-m-section-title">Skills</div><div class="npc-m-skills">`;
      for (const s of npc.skills) {
        html += `<span class="npc-m-skill">${s}</span>`;
      }
      html += `</div></div>`;
    }

    // Current quest
    if (npc.current_quest) {
      html += `<div class="npc-m-section"><div class="npc-m-section-title">Current Quest</div><div class="npc-m-quest">${npc.current_quest}</div></div>`;
    }

    // Corruption / rumor
    if (npc.corruption_level > 0) {
      html += `<div class="npc-m-stat"><span class="npc-m-stat-label">Corruption</span><span class="npc-m-stat-val" style="color:var(--red)">${Math.round(npc.corruption_level * 100)}%</span></div>`;
    }
    if (npc.rumor_level > 0) {
      html += `<div class="npc-m-stat"><span class="npc-m-stat-label">Rumor Level</span><span class="npc-m-stat-val" style="color:var(--amber)">${Math.round(npc.rumor_level * 100)}%</span></div>`;
    }

    body.innerHTML = html;
  } catch(e) {
    body.innerHTML = `<div style="color:var(--red);text-align:center;padding:20px">SCAN FAILED — ${charId}</div>`;
  }
}

function closeNpcModal() {
  document.getElementById('npc-modal').classList.remove('open');
}

// Close modal on backdrop click
document.getElementById('npc-modal').addEventListener('click', function(e) {
  if (e.target === this) closeNpcModal();
});

// ============ KEYBOARD SHORTCUTS ============
document.addEventListener('keydown', function(e) {
// Init audio on first key press (browser autoplay policy)
if (!audioCtx) initAudio();

// M for Mute toggle
if (e.key === 'm' || e.key === 'M') {
  toggleMute();
  e.preventDefault();
  return;
}

  // Number keys 1-5 for choice buttons
  if (e.key >= '1' && e.key <= '5') {
    const btns = document.querySelectorAll('#cmd-buttons .cmd-btn:not(:disabled)');
    const idx = parseInt(e.key) - 1;
    if (btns[idx]) {
      btns[idx].click();
      e.preventDefault();
    }
  }

  // Space or Enter for Continue
  if ((e.key === ' ' || e.key === 'Enter') && document.getElementById('continue-btn').style.display !== 'none') {
    nextEvent();
    e.preventDefault();
  }

  // R for Reset (when game over)
  if (e.key === 'r' || e.key === 'R') {
    if (document.getElementById('vs-gameover').style.display === 'block' ||
        document.getElementById('vs-gameover').style.display === '') {
      // Only reset if game over is visible
      const goEl = document.getElementById('vs-gameover');
      if (goEl.style.display === 'block') {
        resetGame();
        e.preventDefault();
      }
    }
  }

  // Escape to close NPC modal
  if (e.key === 'Escape') {
    closeNpcModal();
  }
});

// ============ API CALLS ============
async function fetchState() {
  gameState = await trackedFetch('state', `${API}/state`);
  if (!gameState) return;
  updateTopRibbon(gameState);
  updateLeftConsole(gameState);
  updateRightConsole(gameState);
  const alertLevel = computeAlertState(gameState, currentEvent);
  setAlertState(alertLevel);
}

async function fetchEvent() {
  const data = await trackedFetch('event', `${API}/event`);
  if (!data) { addComms('EVENT LINK UNSTABLE'); return; }
  currentEvent = data;
  currentChoiceToken = data.choice_token || null;
  loadEvent(data);
}

async function fetchConsciousness() {
  consciousness = await trackedFetch('consciousness', `${API}/consciousness`);
  if (consciousness) updateConsciousness(consciousness);
}

async function fetchRivals() {
  const data = await trackedFetch('rivals', `${API}/rivals`);
  if (!data) return;
  rivalsData = data;
  updateRivals(data);
  if (gameState) {
    const alertLevel = computeAlertState(gameState, currentEvent);
    setAlertState(alertLevel);
  }
}

async function fetchFactions() {
  const data = await trackedFetch('factions', `${API}/factions`);
  if (!data) return;
  factionsData = data.factions || {};
  try { drawFactionRadar(factionsData); } catch(drawErr) { /* canvas error, non-fatal */ }
}

async function fetchMapEvents() {
  const data = await trackedFetch('map', `${API}/map/data`);
  if (data) updateEventsFeed(data);
}

async function fetchDecisionLog() {
  decisionLog = await trackedFetch('log', `${API}/log`);
  if (decisionLog) updateTimeline(decisionLog, timelineData);
}

async function fetchTimeline() {
  timelineData = await trackedFetch('timeline', `${API}/timeline`);
  if (decisionLog.length > 0 && timelineData) {
    updateTimeline(decisionLog, timelineData);
  }
}

async function makeChoice(choiceId) {
  if (!currentEvent) return;
  const btns = document.querySelectorAll('.cmd-btn');
  btns.forEach(b => { b.dataset.origText = b.textContent; b.textContent = 'EXECUTING…'; b.disabled = true; });
  playChoiceSound();

  try {
    const data = await trackedFetch('choose', `${API}/choose/${choiceId}?choice_token=${currentChoiceToken || ''}`, { method: 'POST' });

    if (!data) {
      addComms('COMMAND LINK FAILURE');
      btns.forEach(b => { b.textContent = b.dataset.origText; b.disabled = false; });
      return;
    }

    if (data.error && !data.outcome) {
      if (String(data.error).includes('choice token')) {
        currentChoiceToken = null;
      }
      currentEvent = null;
      await fetchState();
      await fetchEvent();
      addComms('EVENT REFRESHED');
      return;
    }

    showOutcome(data);
    gameState = data.new_state || gameState;
    updateTopRibbon(gameState);
    updateLeftConsole(gameState);
    updateRightConsole(gameState);

    currentEvent = null;
    const alertLevel = computeAlertState(gameState, null);
    setAlertState(alertLevel);

    if (data.outcome) addComms(data.outcome);
    if (data.rival_effects && Object.keys(data.rival_effects).length > 0) {
      addComms('Rival activity detected');
    }

    // Refresh timeline data
    fetchDecisionLog();
    fetchFactions();
  } catch(e) {
    addComms('COMMAND LINK FAILURE');
    document.querySelectorAll('.cmd-btn').forEach(b => b.disabled = false);
  }
}

async function resetGame() {
  var resetBtn = document.querySelector('[onclick="resetGame()"]') || document.getElementById('btn-reset');
  var restore = btnSpinner(resetBtn, 'RESETTING…');
  try {
    await fedFetch('reset', `${API}/reset`, { method: 'POST', timeout: 10000 });
    // Clear all fetch health on reset (fresh game)
    for (const k of Object.keys(fetchHealth)) {
      fetchHealth[k].ok = true;
      fetchHealth[k].failCount = 0;
      fetchHealth[k].retrying = false;
    }
    updateLinkHealth();
    // Remove all stale badges
    document.querySelectorAll('.stale-badge').forEach(el => el.remove());
    document.getElementById('vs-gameover').style.display = 'none';
    fetchState().then(() => { fetchEvent(); fetchRivals(); fetchConsciousness(); fetchFactions(); fetchDecisionLog(); fetchTimeline(); });
  } catch(e) { addComms('RESET LINK FAILURE'); }
  finally { restore(); }
}
function updateTopRibbon(s) {
  document.getElementById('top-era').textContent = (s.governance_status || '--').toUpperCase().substring(0, 18);
  const year = 2387 + (s.turn || 0);
  document.getElementById('top-year').textContent = `YEAR ${year}`;
  setTopBar('trust', s.public_trust, 100);
  setTopBar('stability', s.federation_stability, 100);
  setTopBar('morale', s.crew_morale, 100);
  setTopBar('threat', s.emergency_powers, 100);
  setTopBar('integrity', s.constitutional_integrity, 100);
  setTopBar('rights', s.rights_protection, 100);
}

function setTopBar(name, val, max) {
  const pct = Math.min(100, Math.max(0, ((val || 0) / max) * 100));
  const fill = document.getElementById('bar-' + name);
  const vl = document.getElementById('val-' + name);
  if (fill) fill.style.width = pct + '%';
  if (vl) vl.textContent = val || 0;
}

function updateLeftConsole(s) {
  setSysBar('hull', s.hull, 100, s.hull < 30 ? 'var(--red)' : 'var(--green)');
  setSysBar('shields', s.shields, 100, 'var(--cyan)');
  setSysBar('fuel', s.fuel, 100, s.fuel < 25 ? 'var(--red)' : 'var(--amber)');
  document.getElementById('sv-credits').textContent = s.credits || 0;
  document.getElementById('sv-sectors').textContent = s.discovered_sectors || 0;
  document.getElementById('sv-allies').textContent = s.allies || 0;

  // Decision ledger (last 3)
  const ledger = s.decision_ledger || [];
  const le = document.getElementById('ledger-content');
  if (ledger.length > 0) {
    le.innerHTML = ledger.slice(-3).reverse().map(d =>
      `<div style="padding:3px 0;border-bottom:1px solid rgba(79,195,247,0.08)"><span style="color:var(--amber)">T${d.turn}</span> ${d.choice || '?'}</div>`
    ).join('');
  }
}

function setSysBar(name, val, max, color) {
  const pct = Math.min(100, Math.max(0, ((val || 0) / max) * 100));
  const vl = document.getElementById('sv-' + name);
  const fill = document.getElementById('sbar-' + name);
  if (vl) vl.textContent = val || 0;
  if (fill) { fill.style.width = pct + '%'; if (color) fill.style.background = color; }
}

function updateConsciousness(cs) {
  if (!cs || !cs.system_available) return;
  setCSBar('coherence', cs.coherence, 1);
  setCSBar('cs-stability', cs.stability, 1);
  setCSBar('complexity', cs.complexity, 1);
  setCSBar('awakeness', cs.awakeness, 1);
  setCSBar('anxiety', cs.anxiety, 1, cs.anxiety > 0.6 ? 'var(--red)' : 'var(--amber)');
}

function setCSBar(name, val, max, color) {
  const pct = Math.min(100, Math.max(0, ((val || 0) / max) * 100));
  const fill = document.getElementById('sbar-' + name);
  const vl = document.getElementById('sv-' + name);
  if (fill) fill.style.width = pct + '%';
  if (vl) vl.textContent = Math.round((val || 0) * 100);
  if (fill && color) fill.style.background = color;
}

function updateRightConsole(s) {
  document.getElementById('ri-policy').textContent = s.active_policy || 'None';
  const ld = s.last_decision;
  if (ld) {
    document.getElementById('ri-last-decision').textContent =
      `${ld.choice || '?'} \u2192 ${ld.result ? ld.result.substring(0, 60) + '...' : '?'}`;
  }
}

function updateRivals(data) {
  const el = document.getElementById('ri-rivals');
  if (!data || !data.rivals) {
    el.innerHTML = '<span style="color:var(--dim);font-size:10px">No hostile contacts</span>';
    return;
  }

  const rivalMap = data.rivals.rivals || data.rivals;
  let rivalList = [];

  if (typeof rivalMap === 'object' && !Array.isArray(rivalMap)) {
    const metaKeys = ['success','total_rivals','active_rivals','aggregate_threat','threat_level'];
    rivalList = Object.entries(rivalMap)
      .filter(([k, v]) => typeof v === 'object' && v !== null && !metaKeys.includes(k) && v.success !== false)
      .map(([id, r]) => ({ id, ...r }));
  } else if (Array.isArray(rivalMap)) {
    rivalList = rivalMap;
  }

  if (rivalList.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-size:10px">No hostile contacts</span>';
    return;
  }

  rivalList.sort((a, b) => (b.power || 0) - (a.power || 0));
  const top3 = rivalList.slice(0, 3);

  el.innerHTML = top3.map(r => {
    const name = r.name || r.id || 'Unknown';
    const power = r.power !== undefined ? Math.round(r.power * 100) : '?';
    const aggression = r.aggression !== undefined ? Math.round(r.aggression * 100) : '?';
    const rel = (r.relationships && r.relationships.player) || 'neutral';
    const borderColor = rel === 'hostile' ? 'var(--red)' : rel === 'friendly' ? 'var(--green)' : 'var(--amber)';
    const nameColor = borderColor;
    const personality = r.personality || 'unknown';

    return `<div class="rival-entry" style="border-left-color:${borderColor};background:${rel === 'hostile' ? 'var(--red-dim)' : rel === 'friendly' ? 'rgba(105,240,174,0.05)' : 'rgba(255,158,28,0.05)'}">
    <span class="rival-name" style="color:${nameColor}">${name.toUpperCase()}</span>
    <div class="rival-threat">PWR ${power}% \u00b7 AGG ${aggression}% \u00b7 ${personality.toUpperCase()}</div>
    </div>`;
  }).join('');
}

// ============ TIMELINE ============
function updateTimeline(log, tl) {
  const el = document.getElementById('ri-timeline');
  if (!log || log.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-size:10px">No history</span>';
    return;
  }

  // Group by era if timeline data available
  const eraMap = {};
  if (tl && tl.era_history && tl.era_history.length > 0) {
    for (const e of tl.era_history) {
      if (e.start_turn !== undefined) eraMap[e.start_turn] = e.name || e.era || 'Unknown Era';
    }
  }

  let html = '';
  const entries = log.slice().reverse(); // newest first

  for (const entry of entries) {
    // Era marker if turn matches an era boundary
    if (eraMap[entry.turn]) {
      const eraName = eraMap[entry.turn].replace(/_/g, ' ').toUpperCase();
      html += `<div class="tl-era">\u27e1 ${eraName}</div>`;
    }
    const year = 2387 + (entry.turn || 0);
    html += `<div class="timeline-entry">
      <span class="tl-turn">T${entry.turn}</span>
      <div>
        <div class="tl-event">${(entry.event || '?').substring(0, 28)}</div>
        <div class="tl-choice">${(entry.choice || '?').substring(0, 24)}</div>
      </div>
    </div>`;
  }

  el.innerHTML = html;
}

function updateEventsFeed(mapData) {
  const el = document.getElementById('ri-events');
  const events = (mapData.events || []).slice(0, 8);
  if (!events.length) { el.innerHTML = '<span style="color:var(--dim);font-size:10px">No signals</span>'; return; }
  el.innerHTML = events.map(ev =>
    `<div class="event-feed-item"><span class="ef-char" onclick="openNpcModal('${ev.char_id || ev.character_id || ''}')">${ev.char_name || '?'}</span> <span style="color:var(--dim);font-size:9px">${(ev.action_type || '').toUpperCase()}</span><div class="ef-desc">${(ev.description || '').substring(0, 80)}</div></div>`
  ).join('');
}

// ============ EVENT LOADING ============
function loadEvent(event) {
  document.getElementById('vs-loading').style.display = 'none';
  document.getElementById('vs-outcome').style.display = 'none';
  document.getElementById('vs-gameover').style.display = 'none';
  document.getElementById('vs-event').style.display = 'block';

  const domain = event.domain || event.category || 'Operations';
  document.getElementById('vs-domain').textContent = domain.toUpperCase();
  document.getElementById('vs-title').textContent = event.title || 'Unknown Event';
  document.getElementById('vs-desc').textContent = event.description || '';

  const metaParts = [];
  if (event.affected_lane) metaParts.push(`<span>LANE:</span> ${event.affected_lane}`);
  if (event.rights_at_stake && event.rights_at_stake.length) metaParts.push(`<span>RIGHTS:</span> ${event.rights_at_stake.join(', ')}`);
  if (event.constitutional_risk) metaParts.push(`<span>RISK:</span> ${event.constitutional_risk}`);
  if (event.pressure) metaParts.push(`<span>PRESSURE:</span> ${event.pressure}`);
  document.getElementById('vs-meta').innerHTML = metaParts.join(' &nbsp;\u00b7&nbsp; ');

  // Play viewscreen transition based on event domain
  playEventTransition(domain);

  // Play domain-specific audio
  playEventSound(domain);

  // Compute and set alert state with event context
  const alertLevel = computeAlertState(gameState || {}, event);
  setAlertState(alertLevel);

  // Render command buttons with key hints
  const cmdEl = document.getElementById('cmd-buttons');
  cmdEl.innerHTML = '';
  const btnStyles = ['cyan-btn', 'amber-btn', 'violet-btn', 'red-btn', 'green-btn'];
  (event.choices || []).forEach((choice, i) => {
    const btn = document.createElement('button');
    btn.className = `cmd-btn ${btnStyles[i % btnStyles.length]}`;
    btn.textContent = choice.blocked_by_no_gate ? `${choice.text} / NO GATE` : choice.text;
    btn.onclick = () => makeChoice(choice.id);
    // Add key hint
    const hint = document.createElement('span');
    hint.className = 'key-hint';
    hint.textContent = `[${i + 1}]`;
    btn.appendChild(hint);
    cmdEl.appendChild(btn);
  });

  addComms(`INCOMING: ${event.title}`);
}

// ============ OUTCOME DISPLAY ============
function showOutcome(data) {
  document.getElementById('vs-event').style.display = 'none';

  // Flash effect
  const flash = document.getElementById('vs-flash');
  const flashColor = data.game_over ? 'rgba(255,23,68,0.3)' :
    currentAlert === 'crisis' ? 'rgba(179,136,255,0.2)' :
    currentAlert === 'red' ? 'rgba(255,23,68,0.2)' :
    'rgba(79,195,247,0.15)';
  flash.style.background = flashColor;
  flash.style.animation = 'none';
  flash.offsetHeight;
  flash.style.animation = 'vs-flash 0.6s ease-out forwards';

  // Check game over / victory
  if (data.game_over || data.game_victory) {
    document.getElementById('vs-gameover').style.display = 'block';
    const titleEl = document.getElementById('vs-go-title');
    const textEl = document.getElementById('vs-go-text');
    if (data.game_victory) {
      titleEl.textContent = data.game_victory;
      titleEl.style.color = 'var(--green)';
      textEl.textContent = `The Federation survived ${(gameState && gameState.turn) || 100} turns.`;
      playTone(523, 0.3, 0.08, 'sine');
      setTimeout(() => playTone(659, 0.3, 0.08, 'sine'), 200);
      setTimeout(() => playTone(784, 0.5, 0.1, 'sine'), 400);
    } else {
      titleEl.textContent = data.game_over;
      titleEl.style.color = 'var(--red)';
      textEl.textContent = 'The Federation has fallen.';
      playTone(220, 0.8, 0.1, 'sawtooth');
    }
    document.querySelectorAll('.cmd-btn').forEach(b => b.style.display = 'none');
    return;
  }

  document.getElementById('vs-outcome').style.display = 'block';

  // Outcome title
  const outTitle = document.getElementById('vs-outcome-title');
  outTitle.textContent = 'RESOLUTION';
  outTitle.style.color = 'var(--cyan)';

  // Outcome text
  document.getElementById('vs-outcome-text').textContent = data.outcome || '';

  // Deltas
  const deltas = data.deltas || {};
  const deltaEntries = Object.entries(deltas).filter(([k,v]) => v !== 0);
  const deltasEl = document.getElementById('vs-deltas');
  if (deltaEntries.length > 0) {
    deltasEl.innerHTML = deltaEntries.map(([key, value]) => {
      const label = METRIC_LABELS[key] || key;
      const sign = value > 0 ? '+' : '';
      const cls = value > 0 ? 'delta-pos' : 'delta-neg';
      return `<span class="${cls}">${label}: ${sign}${value}</span>`;
    }).join(' &nbsp;\u00b7&nbsp; ');
  } else {
    deltasEl.textContent = 'No metric movement';
  }

  // Lesson
  const lessonEl = document.getElementById('vs-lesson');
  if (data.lesson) {
    lessonEl.textContent = data.lesson;
    lessonEl.style.display = 'block';
  } else {
    lessonEl.style.display = 'none';
  }

  // Rival effects
  const rivalEl = document.getElementById('vs-rival-effects');
  if (data.rival_effects && Object.keys(data.rival_effects).length > 0) {
    const effects = [];
    for (const [rival, effect] of Object.entries(data.rival_effects)) {
      const desc = typeof effect === 'string' ? effect : (effect.description || effect.action || JSON.stringify(effect));
      effects.push(`${rival}: ${desc}`);
    }
    rivalEl.innerHTML = effects.join('<br>');
    rivalEl.style.display = 'block';
  } else {
    rivalEl.style.display = 'none';
  }

  // Show continue button
  document.getElementById('continue-btn').style.display = 'inline-block';

  // Clear command buttons
  document.getElementById('cmd-buttons').innerHTML = '';
}

function nextEvent() {
  document.getElementById('vs-outcome').style.display = 'none';
  document.getElementById('continue-btn').style.display = 'none';
  fetchEvent();
  fetchRivals();
  fetchConsciousness();
  fetchFactions();
  fetchDecisionLog();
  fetchTimeline();
}

// ============ COMMS TICKER ============
const commsBuffer = [];
function addComms(msg) {
  commsBuffer.push({ text: msg, time: Date.now(), isNew: true });
  if (commsBuffer.length > 20) commsBuffer.shift();
  renderComms();
  setTimeout(() => {
    const item = commsBuffer.find(c => c.text === msg && c.isNew);
    if (item) { item.isNew = false; renderComms(); }
  }, 8000);
}

function renderComms() {
  const el = document.getElementById('comms-ticker');
  el.innerHTML = commsBuffer.slice().reverse().map(c =>
    `<span class="${c.isNew ? 'comms-new' : ''}">${c.text}</span>`
  ).join('');
}

// ============ INIT ============
function init() {
  initStarfield();
  // Audio is initialized on first user interaction (click or keypress) to comply with autoplay policy
  document.addEventListener('click', function audioInit() {
    if (!audioCtx) initAudio();
    // Apply mute state if user had it muted from last session
    if (isMuted && humGain) humGain.gain.setTargetAtTime(0, audioCtx.currentTime, 0.05);
    document.removeEventListener('click', audioInit);
  }, { once: true });

  // Audio toggle button
  const audioBtn = document.getElementById('audio-toggle');
  if (isMuted) {
    audioBtn.classList.add('muted');
    audioBtn.setAttribute('aria-label', 'Audio muted — click to unmute');
  } else {
    audioBtn.setAttribute('aria-label', 'Audio on — click to mute');
  }
  audioBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    if (!audioCtx) initAudio();
    toggleMute();
  });

  fetchState().then(() => {
    fetchEvent();
    fetchRivals();
    fetchConsciousness();
    fetchMapEvents();
    fetchFactions();
    fetchDecisionLog();
    fetchTimeline();
  });

  // Refresh state every 10s
  setInterval(() => {
    fetchState();
    fetchConsciousness();
  }, 10000);
  setInterval(fetchMapEvents, 15000);
  setInterval(fetchRivals, 20000);
  setInterval(fetchFactions, 30000);
  setInterval(fetchDecisionLog, 15000);

  // Refresh stale badge timestamps every 5s
  setInterval(() => {
    for (const key of Object.keys(fetchHealth)) {
      if (!fetchHealth[key].ok) updateStaleBadge(key);
    }
    updateLinkHealth();
  }, 5000);
}

init();
