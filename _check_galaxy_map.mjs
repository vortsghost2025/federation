// _check_galaxy_map.mjs — validates frontend/galaxy-map.html + galaxy-map.js
// Mirrors _check_universe.mjs with the FIXED clock-order check (delta BEFORE elapsed).

import fs from 'fs';
import path from 'path';

const ROOT = path.resolve('.');
const HTML_PATH = path.join(ROOT, 'federation-game', 'frontend', 'galaxy-map.html');
const JS_PATH = path.join(ROOT, 'federation-game', 'frontend', 'galaxy-map.js');

let failures = 0;

function logFail(msg) { console.log('FAIL: ' + msg); failures++; }
function logOk(msg) { console.log('OK:   ' + msg); }

console.log('═══════════════════════════════════════════════════════════════');
console.log('  Galaxy Map Checker');
console.log('═══════════════════════════════════════════════════════════════');

if (!fs.existsSync(HTML_PATH)) { logFail('galaxy-map.html not found at ' + HTML_PATH); process.exit(1); }
if (!fs.existsSync(JS_PATH)) { logFail('galaxy-map.js not found at ' + JS_PATH); process.exit(1); }

const html = fs.readFileSync(HTML_PATH, 'utf8');
const js = fs.readFileSync(JS_PATH, 'utf8');

// ─── HTML checks ─────────────────────────────────────────────────────────────
console.log('\n[HTML]');

if (!html.includes('importmap')) logFail('Missing importmap (Three.js module config)');
else logOk('importmap present');

if (!html.includes('galaxy-map.js')) logFail('Does not reference galaxy-map.js');
else logOk('references galaxy-map.js');

for (const id of ['topbar', 'modebar', 'zoombar', 'panel', 'help-bar', 'loading', 'tick-dot', 'tick-label']) {
  if (!html.includes('id="' + id + '"')) logFail('Missing DOM element id="' + id + '"');
  else logOk('DOM id="' + id + '"');
}

for (const fid of ['g-tension', 'g-stability', 'g-morale', 'g-anomaly']) {
  if (!html.includes('id="' + fid + '"')) logFail('Missing gauge id="' + fid + '"');
  else logOk('gauge id="' + fid + '"');
}

for (const mode of ['universe', 'territory', 'npc', 'exploration']) {
  if (!html.includes('data-mode="' + mode + '"')) logFail('Missing mode button: ' + mode);
  else logOk('mode button: ' + mode);
}

for (const z of ['galaxy', 'region', 'sector']) {
  if (!html.includes('data-zoom="' + z + '"')) logFail('Missing zoom button: ' + z);
  else logOk('zoom button: ' + z);
}

// ─── JS syntax check via Function constructor ────────────────────────────────
console.log('\n[JS]');

try {
  // Wrap in async function so top-level await/import is allowed syntactically
  new Function('"use strict"; return (async () => { ' + js.replace(/import [^;]+;/g, '') + ' })();');
  logOk('JS SYNTAX: PASS');
} catch (e) {
  logFail('JS SYNTAX: ' + e.message);
}

// ─── Three.js imports sanity ─────────────────────────────────────────────────
console.log('\n[IMPORTS]');
for (const sym of ['* as THREE', 'OrbitControls']) {
  if (!js.includes(sym)) logFail('Missing import: ' + sym);
  else logOk('imports ' + sym);
}

// ─── Section markers ─────────────────────────────────────────────────────────
console.log('\n[SECTIONS]');
const sections = [
  '§1  DATA / STATE',
  '§2  COORDINATE TRANSFORM',
  '§3  BACKDROP',
  '§4  SECTORS',
  '§5  TERRITORY INFLUENCE',
  '§6  NPCs / TRAILS',
  '§7  MAP MODES',
  '§8  SEMANTIC ZOOM',
  '§9  INTERACTION',
  '§10 CAMERA',
  '§11 ANIMATION LOOP'
];
for (const s of sections) {
  if (!js.includes(s)) logFail('Missing section marker: ' + s);
  else logOk('section: ' + s);
}

// ─── Mode registry completeness ──────────────────────────────────────────────
console.log('\n[MODE REGISTRY]');
for (const m of ['universe', 'territory', 'npc', 'exploration']) {
  const re = new RegExp('^\\s*' + m + ':\\s*\\{', 'm');
  if (!re.test(js)) logFail('MODE_REGISTRY missing key: ' + m);
  else logOk('mode registered: ' + m);
}

// ─── Zoom registry completeness ──────────────────────────────────────────────
console.log('\n[ZOOM REGISTRY]');
for (const z of ['galaxy', 'region', 'sector']) {
  const re = new RegExp('^\\s*' + z + ':\\s*\\{', 'm');
  if (!re.test(js)) logFail('ZOOM_REGISTRY missing key: ' + z);
  else logOk('zoom registered: ' + z);
}

// ─── Clock order check (the FIXED one) ───────────────────────────────────────
// Real bug pattern: BOTH calls on the same line, OR across two consecutive
// lines in the wrong order. We look for the first non-comment line that
// captures either call, then verify the assignment that follows (within 5
// lines) has getDelta BEFORE getElapsedTime.
console.log('\n[CLOCK ORDER]');
if (js.includes('getElapsedTime()') && js.includes('getDelta()')) {
  const lines = js.split('\n');
  let found = false;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) continue;
    if (!lines[i].includes('clock.get')) continue;
    // Found the animation loop's clock reads. Check order across the next 5 lines.
    const window = lines.slice(i, i + 5).filter(l => !l.trim().startsWith('//') && !l.trim().startsWith('*'));
    const firstDelta = window.findIndex(l => l.includes('getDelta()'));
    const firstElapsed = window.findIndex(l => l.includes('getElapsedTime()'));
    if (firstDelta === -1 || firstElapsed === -1) continue;
    found = true;
    if (firstDelta < firstElapsed) {
      logOk('Line ' + (i + 1 + firstDelta) + ': getDelta() called BEFORE getElapsedTime() (correct)');
    } else {
      logFail('Line ' + (i + 1 + firstElapsed) + ': getElapsedTime() called BEFORE getDelta() = BUG. Swap order.');
    }
    break;
  }
  if (!found) logFail('Clock usage not located in animation loop');
} else {
  logFail('Animation loop missing getElapsedTime() or getDelta()');
}

// ─── GLSL shader sanity ──────────────────────────────────────────────────────
console.log('\n[SHADERS]');
const shaderGens = [
  { name: 'starVert', marker: 'const starVert' },
  { name: 'starFrag', marker: 'const starFrag' },
  { name: 'nebVert', marker: 'const nebVert' },
  { name: 'nebFrag', marker: 'const nebFrag' },
  { name: 'milkyVert', marker: 'const milkyVert' },
  { name: 'milkyFrag', marker: 'const milkyFrag' },
  { name: 'territoryVert', marker: 'const territoryVert' },
  { name: 'territoryFrag', marker: 'const territoryFrag' }
];
for (const sh of shaderGens) {
  if (!js.includes(sh.marker)) { logFail('Missing shader: ' + sh.name); continue; }
  const idx = js.indexOf(sh.marker);
  const end = js.indexOf('`', idx + sh.marker.length);
  const body = js.substring(idx, end);
  let openBrace = 0, closeBrace = 0;
  for (const ch of body) { if (ch === '{') openBrace++; if (ch === '}') closeBrace++; }
  if (openBrace !== closeBrace) {
    logFail('Shader ' + sh.name + ': unbalanced braces ' + openBrace + '/' + closeBrace);
  } else {
    logOk('shader: ' + sh.name + ' (braces balanced: ' + openBrace + '/' + closeBrace + ')');
  }
}

// ─── Discovery state honesty check ────────────────────────────────────────────
console.log('\n[EXPLORATION HONESTY]');
if (js.includes('DISCOVERY_OPACITY') && js.includes('undiscovered:    0.0')) {
  logOk('Undiscovered faction pairs: line opacity 0 (invisible — honest)');
} else {
  logFail('Undiscovered discovery line opacity not set to 0');
}
if (js.includes('WorldDiscovery') && /faction-?pair/i.test(js)) {
  logOk('Comments note WorldDiscovery is faction-pair, not per-sector');
} else {
  logFail('Missing honesty note about WorldDiscovery being faction-pair only');
}

// ─── Final ────────────────────────────────────────────────────────────────────
console.log('\n═══════════════════════════════════════════════════════════════');
if (failures === 0) {
  console.log('  RESULT: ALL CHECKS PASSED');
  console.log('═══════════════════════════════════════════════════════════════');
  process.exit(0);
} else {
  console.log('  RESULT: ' + failures + ' FAILURE(S)');
  console.log('═══════════════════════════════════════════════════════════════');
  process.exit(1);
}
