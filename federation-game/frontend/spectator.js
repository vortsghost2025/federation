"use strict";

const state = {
  paused: false,
  timer: null,
  sceneTimer: null,
  scenes: [],
  episodes: [],
  activeEpisodeKey: null,
  factions: [],
  activeFactionId: null,
  channelStreamCache: new Map(),
  channelTimers: new Map(),
  voices: [],
  voiceByIndex: new Map(),
  voiceByName: new Map(),
  voiceByURI: new Map(),
  voiceAssignments: {},
  voicePretendLoad: false,
  refreshMs: 30000,
  slowRefreshMs: 90000,
  speaking: false,
  speakQueue: [],
  spokenKeys: new Set(),
  activeUtterance: null,
  onSpeakEndCallbacks: [],
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "\x26amp;")
    .replace(/</g, "\x26lt;")
    .replace(/>/g, "\x26gt;")
    .replace(/"/g, "\x26quot;")
    .replace(/'/g, "\x26#39;");
}

function deltaClass(value) {
  if (value === null || value === undefined || value === "") return "";
  const v = Number(value);
  return v >= 0 ? "positive" : "negative";
}

function deltaLabel(value) {
  if (value === null || value === undefined || value === "") return "";
  const v = Number(value);
  const sign = v >= 0 ? "+" : "";
  return `Relationship ${sign}${v.toFixed(1)}`;
}

function categoryClass(category) {
  if (!category) return "";
  return String(category).replace(/[^a-z_]/gi, "").toLowerCase();
}

function sceneFactionAccent(scene) {
  const cats = scene?.participants || [];
  return cats.length ? cats[0].name : "Federation";
}

function signatureOf(scenes) {
  if (!scenes || !scenes.length) return "empty";
  return scenes
    .slice(0, 12)
    .map((s) => `${s.timestamp}|${s.category}|${(s.participants || []).length}|${(s.dialogue || []).length}`)
    .join(";");
}

function renderHero(scenes, mood) {
  const lead = scenes && scenes.length ? scenes[0] : null;
  const headline = $("headline");
  const summary = $("summary");

  if (!lead) {
    headline.textContent = "The Federation is between visible moments.";
    summary.textContent = "";
    return;
  }

  const leadText = lead.summary || (lead.dialogue && lead.dialogue[0] && lead.dialogue[0].text) || "Something quiet just happened.";
  headline.textContent = leadText;
  summary.textContent = mood ? `Mood: ${mood}.` : "The world is alive.";
}

function renderSceneCard(scene) {
  const participants = scene.participants || [];
  const dialogue = scene.dialogue || [];
  const participantsHtml = participants
    .map((p) => `<button type="button" data-char="${escapeHtml(p.char_id)}" data-name="${escapeHtml(p.name)}">${escapeHtml(p.name)}</button>`)
    .join("");

  const dialogueHtml = dialogue.length
    ? `<ul class="scene-dialogue">${dialogue
        .map((d) => `<li><strong>${escapeHtml(d.speaker || "Someone")}</strong>${escapeHtml(d.text || "")}</li>`)
        .join("")}</ul>`
    : "";

  const delta = scene.relationship_delta;
  const deltaHtml = delta !== null && delta !== undefined
    ? `<span class="scene-delta ${deltaClass(delta)}">${escapeHtml(deltaLabel(delta))}</span>`
    : "";

  const metaBits = [
    `<span><strong>Category:</strong> ${escapeHtml(scene.category || scene.entry_type || "moment")}</span>`,
  ];
  if (participants.length) {
    metaBits.push(`<span><strong>Cast:</strong> ${participants.length}</span>`);
  }

  return `
    <article class="scene-card ${categoryClass(scene.category)}">
      <div class="scene-meta">${metaBits.join("")}</div>
      <div class="scene-participants">${participantsHtml}</div>
      ${dialogueHtml}
      <div class="scene-summary">${escapeHtml(scene.summary || "")}</div>
      ${deltaHtml ? `<div>${deltaHtml}</div>` : ""}
    </article>
  `;
}

function renderScenes(scenes) {
  const list = $("scene-list");
  if (!scenes || !scenes.length) {
    list.innerHTML = `<p class="empty">The world is still thinking. Refresh in a moment.</p>`;
    return;
  }
  list.innerHTML = scenes.map(renderSceneCard).join("");
}

function setStatus(level, text) {
  const dot = $("status-dot");
  const label = $("status-text");
  if (dot) {
    dot.className = `dot ${level}`;
  }
  if (label) label.textContent = text;
}

function setLastUpdate(isoOrText) {
  const el = $("last-update");
  if (el) el.textContent = isoOrText ? `Updated ${isoOrText}` : "";
}

async function loadWorldVitals() {
  const grid = $("vitals-grid");
  try {
    const response = await fetch("/spectator/world-vitals", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderVitals(data);
    renderOperatorWarnings(data.operator);
  } catch (err) {
    if (grid) {
      grid.innerHTML = `<div class="vital-tile critical"><div class="vital-label">Vitals</div><div class="vital-band">signal lost</div><div class="vital-value">--</div></div>`;
    }
    const warningsEl = $("operator-warnings");
    if (warningsEl) warningsEl.hidden = true;
  }
}

function renderVitals(data) {
  const grid = $("vitals-grid");
  if (!grid) return;
  const tiles = data.tiles || [];
  if (!tiles.length) {
    grid.innerHTML = `<div class="vital-tile placeholder">No vitals available.</div>`;
    return;
  }
  grid.innerHTML = tiles.map((tile) => {
    const value = tile.value === null || tile.value === undefined ? "--" : Number(tile.value);
    return `
      <div class="vital-tile ${escapeHtml(tile.band || "unknown")}">
        <div class="vital-label">${escapeHtml(tile.label || tile.key)}</div>
        <div class="vital-value">${escapeHtml(String(value))}</div>
        <div class="vital-band">${escapeHtml(tile.band || "unknown")}</div>
      </div>
    `;
  }).join("");
}

function renderOperatorWarnings(op) {
  const el = $("operator-warnings");
  if (!el) return;
  if (!op || !op.warnings || !op.warnings.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  const pieces = op.warnings.map((w) => {
    const who = w.char_id ? `<strong>${escapeHtml(w.char_id)}</strong>: ` : "";
    return `<div>${who}${escapeHtml(w.message || "(no detail)")}</div>`;
  }).join("");
  const delta = op.stability_delta !== undefined && op.stability_delta !== null
    ? `<div>Last tick stability drift: <strong>${escapeHtml(op.stability_delta >= 0 ? "+" : "")}${escapeHtml(String(op.stability_delta))}</strong></div>`
    : "";
  el.innerHTML = `${delta}<div>${pieces}</div>`;
  el.hidden = false;
}

async function loadThreads() {
  const list = $("thread-list");
  if (!list) return;
  try {
    const response = await fetch("/spectator/threads", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const threads = data.threads || [];
    renderThreads(threads);
    state.episodes = threads.map((t, idx) => ({
      key: `ep_${idx}`,
      title: forSpeech(t.label) || `Episode ${idx + 1}`,
      drama: t.drama || 0,
      tone: t.tone || "neutral",
      chars: (t.characters || []).slice(0, 8),
      topCategories: (t.categories || []).slice(0, 3),
      scenes: (t.scenes || []).slice(),
      raw: t,
    }));
    renderEpisodeRail(state.episodes);
    if (state.activeEpisodeKey && !state.episodes.find((e) => e.key === state.activeEpisodeKey)) {
      state.activeEpisodeKey = null;
      renderEpisodePanel(null);
    } else if (state.activeEpisodeKey) {
      renderEpisodePanel(state.episodes.find((e) => e.key === state.activeEpisodeKey));
    }
  } catch (err) {
    list.innerHTML = `<p class="empty">Active storylines could not load. I will keep trying.</p>`;
    renderEpisodeRail([]);
  }
}

function renderThreads(threads) {
  const list = $("thread-list");
  if (!list) return;
  if (!threads.length) {
    list.innerHTML = `<p class="empty">No active drama threads yet. Refresh in a moment.</p>`;
    return;
  }

  list.innerHTML = threads.map((thread) => {
    const cats = (thread.categories || []).map(([name, n]) => `${name} (${n})`).join(", ");
    const cast = (thread.characters || []).slice(0, 6).map((p) =>
      `<button type="button" data-char="${escapeHtml(p.char_id)}" data-name="${escapeHtml(p.name)}">${escapeHtml(p.name)}</button>`
    ).join("");
    const latest = thread.scenes && thread.scenes[0];
    const snippet = latest && latest.summary ? escFirstSentence(latest.summary) : "";
    return `
      <article class="thread-card tone-${escapeHtml(thread.tone || "neutral")}">
        <h3>${escapeHtml(thread.label || "Thread")}</h3>
        <div class="thread-meta">
          <span>Drama: ${escapeHtml(String(thread.drama || 0))}</span>
          <span>Scenes: ${escapeHtml(String(thread.scene_count || 0))}</span>
          <span>Categories: ${escapeHtml(cats || "—")}</span>
        </div>
        <div class="thread-cast">${cast}</div>
        ${snippet ? `<div class="thread-detail">${escapeHtml(snippet)}</div>` : ""}
      </article>
    `;
  }).join("");
}

function escFirstSentence(text) {
  const idx = text.search(/[.!?](?:\s|$)/);
  if (idx === -1 || idx > 220) return text.slice(0, 220) + (text.length > 220 ? "..." : "");
  return text.slice(0, idx + 1);
}

function bindThreadClicks() {
  const list = $("thread-list");
  if (!list) return;
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-char]");
    if (!button) return;
    showDossier(button.dataset.char, button.dataset.name);
  });
}

function renderEpisodeRail(episodes) {
  const rail = $("episode-rail");
  const count = $("episode-rail-count");
  if (!rail) return;
  if (!episodes.length) {
    rail.innerHTML = `<p class="empty">No active episodes. Drama is calm right now.</p>`;
    if (count) count.textContent = "";
    return;
  }
  rail.innerHTML = episodes.map((ep) => {
    const cats = (ep.topCategories || []).map(([n]) => n).join(", ");
    const isActive = ep.key === state.activeEpisodeKey;
    return `
      <button type="button" class="episode-thumb tone-${escapeHtml(ep.tone)}${isActive ? " active" : ""}" data-episode="${escapeHtml(ep.key)}" role="tab" aria-selected="${isActive}">
        <p class="episode-thumb-meta">Drama ${escapeHtml(String(ep.drama))}${cats ? " · " + escapeHtml(cats) : ""}</p>
        <p class="episode-thumb-title">${escapeHtml(ep.title)}</p>
      </button>
    `;
  }).join("");
  if (count) count.textContent = `${episodes.length} episode${episodes.length === 1 ? "" : "s"}`;
}

function renderEpisodePanel(ep) {
  const title = $("episode-title");
  const meta = $("episode-meta");
  const body = $("episode-body");
  const playBtn = $("play-episode-btn");
  const nextBtn = $("next-episode-btn");
  const clearBtn = $("clear-episode-btn");
  if (!body) return;

  if (!ep) {
    if (title) title.textContent = "Pick an episode to start watching";
    if (meta) meta.textContent = "";
    body.innerHTML = `<p class="empty">No episode loaded yet. Click any thumbnail below.</p>`;
    body.className = "episode-body";
    if (playBtn) playBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = !episodes.some((e) => e.key !== state.activeEpisodeKey);
    if (clearBtn) clearBtn.hidden = true;
    return;
  }

  if (title) title.textContent = ep.title;
  const castLine = ep.chars.slice(0, 6).map((c) => c.name).join(", ");
  const cats = (ep.topCategories || []).map(([n]) => n).join(", ");
  if (meta) {
    meta.textContent = [
      `Drama ${ep.drama}`,
      `${ep.scenes.length} scene${ep.scenes.length === 1 ? "" : "s"}`,
      cats || "moment",
      castLine ? `cast: ${castLine}` : "",
    ].filter(Boolean).join(" \u00B7 ");
  }

  const dialogueParts = [];
  for (const scene of ep.scenes) {
    for (const d of scene.dialogue || []) {
      if (!d.speaker || !d.text) continue;
      const sig = `${scene.timestamp}|${d.speaker}|${d.text}`;
      dialogueParts.push({ sig, scene, line: d });
    }
  }
  const dialogueHtml = dialogueParts.length
    ? `<ul class="episode-dialogue">${dialogueParts.map((p) =>
      `<li><strong>${escapeHtml(forSpeech(p.line.speaker))}</strong>${escapeHtml(forSpeech(p.line.text))}</li>`
    ).join("")}</ul>`
    : "";

  const castButtons = ep.chars.length
    ? `<div class="episode-castline">Cast: ${ep.chars.map((c) =>
      `<button type="button" class="episode-summary-link" data-char="${escapeHtml(c.char_id)}" data-name="${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>`
    ).join(", ")}</div>`
    : "";

  body.className = `episode-body tone-${escapeHtml(ep.tone)}`;
  body.innerHTML = `${dialogueHtml}${castButtons}`;

  if (playBtn) playBtn.disabled = false;
  if (nextBtn) nextBtn.disabled = false;
  if (clearBtn) clearBtn.hidden = false;
}

function bindEpisodeClicks() {
  const rail = $("episode-rail");
  if (!rail) return;
  rail.addEventListener("click", (event) => {
    const charBtn = event.target.closest("button[data-char]");
    if (charBtn) {
      showDossier(charBtn.dataset.char, charBtn.dataset.name);
      return;
    }
    const thumb = event.target.closest("button[data-episode]");
    if (!thumb) return;
    selectEpisode(thumb.dataset.episode);
  });

  const body = $("episode-body");
  if (body) {
    body.addEventListener("click", (event) => {
      const charBtn = event.target.closest("button[data-char]");
      if (charBtn) showDossier(charBtn.dataset.char, charBtn.dataset.name);
    });
  }
}

function selectEpisode(key) {
  stopSpeaking();
  state.activeEpisodeKey = key;
  const ep = state.episodes.find((e) => e.key === key) || null;
  renderEpisodePanel(ep);
  renderEpisodeRail(state.episodes);
  if (ep) {
    $("episode-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function selectNextEpisode() {
  if (!state.episodes.length) return;
  const currentIdx = state.episodes.findIndex((e) => e.key === state.activeEpisodeKey);
  let nextIdx;
  if (currentIdx === -1) {
    nextIdx = 0;
  } else {
    // Default to drama-sorted order (already sorted by API); rotate
    // next idx from current. If user clicks last episode, loop
    // back to top.
    nextIdx = (currentIdx + 1) % state.episodes.length;
  }
  selectEpisode(state.episodes[nextIdx].key);
  playActiveEpisode({ autoPlay: true });
}

function buildActiveEpisodeScript() {
  const ep = state.episodes.find((e) => e.key === state.activeEpisodeKey);
  if (!ep) return [];
  const script = []; // [{text, speaker}]
  const title = stripSpookSpeechProps(ep.title);
  if (title) script.push({ text: title + ".", speaker: null });
  if (ep.chars.length) {
    const castNames = ep.chars.slice(0, 6).map((c) => stripSpookSpeechProps(c.name)).filter(Boolean).join(", ");
    if (castNames) script.push({ text: "Cast: " + castNames + ".", speaker: null });
  }
  const cats = (ep.topCategories || []).map(([n]) => stripSpookSpeechProps(n)).filter(Boolean).join(", ");
  if (cats) script.push({ text: cats + ".", speaker: null });
  const seen = new Set();
  for (const scene of ep.scenes) {
    for (const d of scene.dialogue || []) {
      if (!d.speaker || !d.text) continue;
      const speakerClean = stripSpookSpeechProps(d.speaker);
      const textClean = stripSpookSpeechProps(d.text);
      const text = `${speakerClean}: ${textClean}`;
      if (seen.has(`${speakerClean}|${textClean}`)) continue;
      seen.add(`${speakerClean}|${textClean}`);
      script.push({ text, speaker: speakerClean });
    }
  }
  return script;
}

function playActiveEpisode(opts = {}) {
  if (!("speechSynthesis" in window)) return;
  if (state.speaking && !opts.autoPlay) {
    stopSpeaking();
    return;
  }
  const script = buildActiveEpisodeScript();
  if (!script.length) return;

  state.spokenKeys.clear();
  for (const item of script) state.spokenKeys.add(item.text.toLowerCase().replace(/\s+/g, " ").trim());

  state.speakQueue = script
    .flatMap((item) => splitIntoUtterances(item.text).map((piece) => ({
      text: piece,
      voiceURI: pickVoiceForSpeaker(item.speaker)?.voiceURI || null,
    })))
    .filter((x) => x && x.text);

  state.speaking = true;
  setPlayEpisodeButton(true);

  state.speakAdvance = true;
  speakQueueStep();
}

function stopSpeaking() {
  if (!state.speaking) return;
  window.speechSynthesis.cancel();
  state.speakQueue.length = 0;
  state.speaking = false;
  state.speakAdvance = false;
  state.activeUtterance = null;
  setReadButton(false);
  setPlayChannelButton(false);
  setPlayEpisodeButton(false);
}

function setPlayChannelButton(isSpeaking) {
  const btn = $("play-channel-btn");
  if (!btn) return;
  btn.textContent = isSpeaking ? "Stop" : "Play this channel";
}
function setPlayEpisodeButton(isSpeaking) {
  const btn = $("play-episode-btn");
  if (!btn) return;
  btn.textContent = isSpeaking ? "Stop" : "Play this episode";
}

function episodes() { return state.episodes || []; }

async function loadScenes() {
  try {
    setStatus("idle", "checking");
    const response = await fetch(`/spectator/scenes?limit=20&page=0`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const scenes = data.scenes || [];
    const sig = signatureOf(scenes);
    state.scenes = scenes;
    renderHero(scenes, data.mood);
    renderScenes(scenes);
    if (sig !== state.lastSignature) {
      state.lastSignature = sig;
    }
    setStatus("on", "live");
    setLastUpdate(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  } catch (err) {
    setStatus("error", "signal lost");
    $("headline").textContent = "The signal is unclear.";
    $("summary").textContent = err && err.message ? err.message : "";
    $("scene-list").innerHTML = `<p class="empty">The spectator feed could not load. I will keep trying.</p>`;
  }
}

function showDossier(charId, name) {
  const panel = $("dossier-panel");
  const closeBtn = $("clear-dossier-btn");
  panel.hidden = false;
  closeBtn.hidden = false;
  $("dossier-name").textContent = name || charId;
  $("dossier-name-inline").textContent = name || charId;
  $("dossier-faction").textContent = "Federation";
  $("dossier-meta").textContent = `Character ID: ${charId}`;
  $("dossier-plan").textContent = "Loading...";
  $("dossier-thoughts").innerHTML = `<li class="empty">Loading...</li>`;
  $("dossier-decisions").innerHTML = `<li class="empty">Loading...</li>`;
  $("dossier-relationships").innerHTML = `<li class="empty">Loading...</li>`;
  state.currentDossierCharId = charId;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  loadDossier(charId);
}

function hideDossier() {
  $("dossier-panel").hidden = true;
  $("clear-dossier-btn").hidden = true;
  state.currentDossierCharId = null;
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
  return response.json();
}

async function loadDossier(charId) {
  if (!charId) return;

  try {
    const [decisionsResp, turnsResp, interactionsResp] = await Promise.all([
      fetchJson(`/npcs/${encodeURIComponent(charId)}/decisions?limit=5`),
      fetchJson(`/npc-turns?char_id=${encodeURIComponent(charId)}&limit=3`),
      fetchJson(`/npcs/${encodeURIComponent(charId)}/interactions?limit=6`),
    ]);

    const decisionList = (decisionsResp.decisions || decisionsResp.results || [])
      .map((d) => {
        const rt = d.reasoning ? ` <em>— ${String(d.reasoning).slice(0, 200)}</em>` : "";
        const text = d.action_desc || d.description || d.summary || "(no description)";
        const cat = d.category ? ` [${d.category}]` : "";
        return `<li>${escapeHtml(text)}${escapeHtml(cat)}${rt}</li>`;
      })
      .filter(Boolean);
    $("dossier-decisions").innerHTML = decisionList.length
      ? decisionList.join("")
      : `<li class="empty">No recent decisions.</li>`;

    const topPlan = (decisionsResp.decisions || decisionsResp.results || [])[0];
    if (topPlan) {
      const planText = topPlan.action_desc || topPlan.description || "";
      $("dossier-plan").textContent = planText || "No plan found.";
    } else {
      $("dossier-plan").textContent = "No recent plan on file.";
    }

    const turnResults = Array.isArray(turnsResp) ? turnsResp : (turnsResp.results || []);
    const thoughtLines = [];
    for (const turn of turnResults) {
      if (turn.output_text) {
        const summary = String(turn.output_text).slice(0, 240);
        thoughtLines.push(`<li>${escapeHtml(summary)}</li>`);
      }
      const facts = turn.retrieved_facts && turn.retrieved_facts.context && turn.retrieved_facts.context.recent_thoughts;
      if (facts) {
        for (const t of facts.slice(0, 2)) {
          thoughtLines.push(`<li><em>thought:</em> ${escapeHtml(String(t).slice(0, 200))}</li>`);
        }
      }
    }
    $("dossier-thoughts").innerHTML = thoughtLines.length
      ? thoughtLines.slice(0, 6).join("")
      : `<li class="empty">No recent thoughts captured.</li>`;

    const partners = interactionsResp.all_partners || interactionsResp.results || interactionsResp.interactions || {};
    const partnerKeys = Object.keys(partners).slice(0, 6);
    const relLines = partnerKeys
      .map((key) => {
        const entry = partners[key];
        const last = entry?.last_interaction || {};
        const lastDesc = last.description || "";
        if (!lastDesc) return "";
        const tone = entry.net_sentiment > 0
          ? "ally"
          : (entry.net_sentiment < 0 ? "rival" : "familiar");
        const tag = entry.net_sentiment !== undefined ? ` <em>(${tone} ${Number(entry.net_sentiment).toFixed(1)})</em>` : "";
        return `<li><strong>${escapeHtml(key)}</strong>${escapeHtml(tag)}: ${escapeHtml(String(lastDesc).slice(0, 200))}</li>`;
      })
      .filter(Boolean);
    $("dossier-relationships").innerHTML = relLines.length
      ? relLines.join("")
      : `<li class="empty">No memorable relationships yet.</li>`;
  } catch (err) {
    $("dossier-plan").textContent = `Could not load dossier: ${err.message}`;
  }
}

function dedupe(text) {
  if (!text) return null;
  const key = text.toLowerCase().replace(/\s+/g, " ").trim();
  if (!key || state.spokenKeys.has(key)) return null;
  state.spokenKeys.add(key);
  return text;
}

// For spoken output: strip internal ids, replace underscores and
// "comp" identifiers with natural language. "char_003" -> ""; TTS
// would otherwise read each id character-by-character.
function forSpeech(text) {
  if (!text) return "";
  return String(text)
    // Drop raw ids like char_004, comp_010, char_201 before they get
    // handed to the speech engine.
    .replace(/\b(chr|char|comp|npc)[_-]?\d{2,4}\b/gi, "")
    // Underscores and stray dashes to spaces; multiple spaces collapse.
    .replace(/[_]+/g, " ")
    .replace(/\s+/g, " ")
    // Drop quotation marks - TTS otherwise says "quote" or voices them
    // literally. Dialogue quotes do not need to survive the reading.
    .replace(/["'\u2018\u2019\u201C\u201D]+/g, "")
    .trim();
}

// Final sweep passes through forSpeech and then trims single quotes
// still attached to words ('Cipher' -> Cipher).
// Final sweep passes through forSpeech and strips stray punctuation
// that TTS would voice mildly. Single quotes attached to words
// ('Cipher') become (Cipher); surrounding ellipses and stray chars
// go too.
function stripSpookSpeechProps(text) {
  if (!text) return "";
  const out = forSpeech(text);
  return out
    .replace(/["\u201C\u201D]+/g, "")
    .replace(/'+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function splitIntoUtterances(longText) {
  const parts = stringSplit(longText, 220);
  return parts.filter(Boolean);
}

function stringSplit(text, maxLen) {
  const out = [];
  if (!text) return out;
  let i = 0;
  while (i < text.length) {
    let end = Math.min(i + maxLen, text.length);
    const lastSentenceBreak = Math.max(
      text.lastIndexOf(". ", end),
      text.lastIndexOf("! ", end),
      text.lastIndexOf("? ", end),
    );
    if (lastSentenceBreak > i + 60) {
      end = lastSentenceBreak + 1;
    }
    out.push(text.slice(i, end).trim());
    i = end;
  }
  return out.filter(Boolean);
}

function setReadButton(isSpeaking) {
  const btn = $("read-btn");
  if (!btn) return;
  btn.textContent = isSpeaking ? "Stop" : "Read aloud";
  btn.dataset.speaking = String(isSpeaking);
}

function pickVoiceForSpeaker(speakerName) {
  // 1) Explicit per-character user override (set via UI).
  // 2) Stable hash assignment so the *same character* always has
  //    the same voice, letting you recognise NPC by ear.
  const voices = state.voices;
  if (!voices.length) return null;
  if (!speakerName) return voices[0];
  const cleaned = String(speakerName).trim();
  const assignedName = state.voiceAssignments[cleaned];
  if (assignedName) {
    const assigned = state.voiceByName.get(assignedName);
    if (assigned) return assigned;
  }
  let h = 0;
  for (let i = 0; i < cleaned.length; i++) {
    h = (h * 31 + cleaned.charCodeAt(i)) >>> 0;
  }
  return voices[h % voices.length];
}

function enqueueSpeech(line, speakerForVoice) {
  if (!line) return;
  const text = forSpeech(line);
  if (!text) return;
  const voice = speakerForVoice ? pickVoiceForSpeaker(speakerForVoice) : null;
  state.speakQueue.push({ text, voiceURI: voice?.voiceURI || null });
}

function speakQueueStep() {
  if (!state.speaking) return;
  const next = state.speakQueue.shift();
  if (!next) {
    state.speaking = false;
    state.activeUtterance = null;
    setReadButton(false);
    if (state.speakAdvance && state.activeEpisodeKey && state.episodes.length > 1) {
      state.speakAdvance = false;
      const currentIdx = state.episodes.findIndex((e) => e.key === state.activeEpisodeKey);
      const nextIdx = (currentIdx + 1) % state.episodes.length;
      const nextKey = state.episodes[nextIdx].key;
      selectEpisode(nextKey);
      // playActiveEpisode will be invoked by next-episode intent; here we
      // just need to know we're done with the auto-advance wrap. The
      // dedicated "Next episode" button below handles explicit advance.
    }
    return;
  }
  const item = (typeof next === "string") ? { text: next } : next;
  if (!item || !item.text) {
    speakQueueStep();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(item.text);
  utterance.rate = 0.94;
  utterance.pitch = 0.97;
  if (item.voiceURI) {
    const voice = state.voiceByURI && state.voiceByURI.get(item.voiceURI);
    if (voice) utterance.voice = voice;
  }
  utterance.onend = () => speakQueueStep();
  utterance.onerror = () => speakQueueStep();
  state.activeUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

function buildReadAloudScript() {
  const script = []; // [{text, speaker}]
  const moodLine = $("summary")?.textContent?.trim();
  if (moodLine) script.push({ text: forSpeech(moodLine), speaker: null });

  state.spokenKeys.clear();

  for (const scene of state.scenes.slice(0, 6)) {
    const intro = `${scene.category || "moment"} scene.`;
    const introText = dedupe(forSpeech(intro));
    if (introText) script.push({ text: introText, speaker: null });

    const participants = (scene.participants || [])
      .map((p) => p.name)
      .filter(Boolean)
      .join(", ");
    if (participants) {
      const castLine = dedupe(`Cast: ${forSpeech(participants)}.`);
      if (castLine) script.push({ text: castLine, speaker: null });
    }

    const seenDialogue = new Set();
    for (const d of scene.dialogue || []) {
      if (!d.speaker || !d.text) continue;
      const sp = forSpeech(d.speaker);
      const utteranceText = dedupe(`${sp}: ${forSpeech(d.text)}`);
      if (!utteranceText) continue;
      const sig = `${scene.timestamp}|${sp}|${utteranceText}`;
      if (seenDialogue.has(sig)) continue;
      seenDialogue.add(sig);
      script.push({ text: utteranceText, speaker: sp });
    }
  }

  return script.filter((x) => x && x.text);
}

function readAloud() {
  if (!("speechSynthesis" in window)) return;
  if (state.speaking) {
    window.speechSynthesis.cancel();
    state.speakQueue.length = 0;
    state.speaking = false;
    state.activeUtterance = null;
    setReadButton(false);
    return;
  }
  const script = buildReadAloudScript();
  if (!script.length) {
    script.push({ text: "The world is waking up.", speaker: null });
  }
  state.speakQueue = script
    .flatMap((item) => splitIntoUtterances(item.text).map((piece) => ({
      text: piece,
      voiceURI: pickVoiceForSpeaker(item.speaker)?.voiceURI || null,
    })))
    .filter((x) => x && x.text);
  state.speaking = true;
  setReadButton(true);
  speakQueueStep();
}

async function askAssistant(question) {
  const answer = $("assistant-answer");
  if (answer) answer.textContent = "Listening to the world...";
  try {
    const response = await fetch("/map/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();
    if (answer) answer.textContent = data.answer || "The assistant did not have an answer.";
  } catch (err) {
    if (answer) answer.textContent = `The assistant could not answer: ${err.message}`;
  }
}

function startAutoRefresh() {
  if (state.timer) clearInterval(state.timer);
  if (state.sceneTimer) clearInterval(state.sceneTimer);
  state.sceneTimer = setInterval(() => {
    if (!state.paused) loadScenes();
  }, state.refreshMs);
  state.timer = setInterval(() => {
    if (!state.paused) {
      loadWorldVitals();
      loadThreads();
    }
  }, state.slowRefreshMs);
}

function bindUi() {
  $("refresh-btn").addEventListener("click", () => {
    loadScenes();
    loadThreads();
    loadWorldVitals();
  });
  $("read-btn").addEventListener("click", readAloud);
  $("pause-btn").addEventListener("click", (e) => {
    state.paused = !state.paused;
    e.currentTarget.textContent = state.paused ? "Resume" : "Pause";
    e.currentTarget.dataset.paused = state.paused;
  });
  $("clear-dossier-btn").addEventListener("click", hideDossier);

  $("scene-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-char]");
    if (!button) return;
    showDossier(button.dataset.char, button.dataset.name);
  });

  const playEp = $("play-episode-btn");
  if (playEp) {
    playEp.addEventListener("click", () => {
      if (!state.activeEpisodeKey) {
        // Default: pick the highest-drama thread to start.
        if (state.episodes.length) selectEpisode(state.episodes[0].key);
      }
      state.speakAdvance = true;
      playActiveEpisode();
    });
  }
  const nextEp = $("next-episode-btn");
  if (nextEp) {
    nextEp.addEventListener("click", () => {
      if (!state.episodes.length) return;
      stopSpeaking();
      const currentIdx = state.episodes.findIndex((e) => e.key === state.activeEpisodeKey);
      const nextIdx = (currentIdx === -1 ? 0 : (currentIdx + 1) % state.episodes.length);
      selectEpisode(state.episodes[nextIdx].key);
      state.speakAdvance = true;
      playActiveEpisode();
    });
  }
  const clearEp = $("clear-episode-btn");
  if (clearEp) {
    clearEp.addEventListener("click", () => {
      stopSpeaking();
      state.activeEpisodeKey = null;
      renderEpisodePanel(null);
      renderEpisodeRail(state.episodes);
    });
  }

  const form = $("assistant-form");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const q = $("question-input").value.trim();
      if (q) askAssistant(q);
    });
  }

  window.addEventListener("keydown", (event) => {
    if (event.code === "Space" && event.target === document.body) {
      event.preventDefault();
      const btn = $("pause-btn");
      btn.click();
    } else if (event.key.toLowerCase() === "r") {
      loadScenes();
    } else if (event.key === "Escape") {
      hideDossier();
      if (state.speaking) readAloud();
    } else if (event.key.toLowerCase() === "s") {
      if (state.speaking) readAloud();
    } else if (event.key === "ArrowRight" && state.episodes.length) {
      const idx = state.episodes.findIndex((e) => e.key === state.activeEpisodeKey);
      const nextIdx = (idx === -1 ? 0 : (idx + 1) % state.episodes.length);
      selectEpisode(state.episodes[nextIdx].key);
      playActiveEpisode();
    }
  });
}

// ===== Channel / faction + per-species voice =============================

async function loadFactions() {
  try {
    const response = await fetch("/spectator/factions", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.factions = data.factions || [];
    renderChannelGrid(state.factions);
  } catch (err) {
    const grid = $("channel-grid");
    if (grid) grid.innerHTML = `<p class="empty">Channels could not load: ${escapeHtml(err.message || "unknown")}</p>`;
  }
}

function renderChannelGrid(factions) {
  const grid = $("channel-grid");
  if (!grid) return;
  if (!factions.length) {
    grid.innerHTML = `<p class="empty">No factions registered.</p>`;
    return;
  }
  grid.innerHTML = factions.map((f) => {
    const isActive = f.id === state.activeFactionId;
    const rosterPreview = (f.members || []).slice(0, 4).map((m) => m.name).join(", ");
    const meta = [
      `${f.member_count || (f.members || []).length} member${f.member_count === 1 ? "" : "s"}`,
      f.cohesion != null ? `cohesion ${Math.round(f.cohesion)}` : "",
    ].filter(Boolean).join(" \u00B7 ");
    return `
      <button type="button" class="channel-card${isActive ? " active" : ""}" data-faction="${escapeHtml(f.id)}" aria-pressed="${isActive}">
        <p class="channel-card-meta">${escapeHtml(meta || "channel")}</p>
        <p class="channel-card-title">${escapeHtml(f.display_name)}</p>
        <p class="channel-card-meta">${escapeHtml(rosterPreview || "no roster yet")}</p>
        <p class="channel-card-roster">${rosterPreview ? formatFullRoster(f.members) : ""}</p>
      </button>
    `;
  }).join("");
}

function formatFullRoster(members) {
  if (!members || !members.length) return "";
  if (members.length <= 4) {
    return members.map((m) => escapeHtml(m.name)).join(", ");
  }
  const extra = members.length - 4;
  return members.slice(0, 4).map((m) => escapeHtml(m.name)).join(", ") + ` and ${extra} more`;
}

async function selectFaction(factionId) {
  stopSpeaking();
  state.activeFactionId = factionId;
  renderChannelGrid(state.factions);

  const faction = state.factions.find((f) => f.id === factionId);
  $("channel-name").textContent = faction?.display_name || factionId;
  const meta = $("channel-meta");
  if (meta) {
    meta.textContent = (faction?.members || [])
      .map((m) => m.name)
      .join(", ") || "no roster";
  }
  $("channel-feed").innerHTML = `<p class="empty">Loading ${faction?.display_name || factionId}...</p>`;
  $("play-channel-btn").disabled = true;
  $("refresh-channel-btn").disabled = false;

  await loadChannelStream(factionId);
  $("channel-active-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadChannelStream(factionId) {
  try {
    const url = `/spectator/factions/${encodeURIComponent(factionId)}/stream?limit=20`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.channelStreamCache.set(factionId, data);
    renderChannelFeed(data);
    $("play-channel-btn").disabled = !(data.scenes && data.scenes.length);
  } catch (err) {
    const feed = $("channel-feed");
    if (feed) feed.innerHTML = `<p class="empty">Channel unavailable: ${escapeHtml(err.message || "unknown")}</p>`;
  }
}

function renderChannelFeed(data) {
  const feed = $("channel-feed");
  if (!feed) return;
  const scenes = data.scenes || [];
  if (!scenes.length) {
    feed.innerHTML = `<p class="empty">No recent activity in ${escapeHtml(data.faction_display || data.faction_id || "channel").toString()}.</p>`;
    return;
  }
  feed.innerHTML = scenes.map((scene) => {
    const parts = (scene.participants || []).map((p) =>
      `<button type="button" data-char="${escapeHtml(p.char_id)}" data-name="${escapeHtml(p.name)}">${escapeHtml(p.name)}</button>`
    ).join("");
    const delta = scene.relationship_delta;
    const deltaBit = (delta !== null && delta !== undefined)
      ? `<span>Relationship ${delta >= 0 ? "+" : ""}${Number(delta).toFixed(1)}</span>`
      : "";
    return `
      <article class="channel-scene ${categoryClass(scene.category)}">
        <div class="channel-scene-meta">
          <span>${escapeHtml(String(scene.category || "moment"))}</span>
          <span>${escapeHtml(new Date((scene.timestamp || 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span>
          ${deltaBit}
        </div>
        <div class="channel-scene-parts">${parts}</div>
        <div class="channel-scene-summary">${escapeHtml(scene.summary || "")}</div>
      </article>
    `;
  }).join("");
}

function playActiveChannel() {
  if (!("speechSynthesis" in window)) return;
  if (state.speaking) {
    stopSpeaking();
    return;
  }
  const factionId = state.activeFactionId;
  if (!factionId) return;
  const data = state.channelStreamCache.get(factionId);
  if (!data || !data.scenes || !data.scenes.length) return;
  const script = [];
  const faction = state.factions.find((f) => f.id === factionId);
  if (faction) script.push({ text: stripSpookSpeechProps(faction.display_name) + ".", speaker: null });
  const seen = new Set();
  for (const scene of data.scenes) {
    if (scene.summary) script.push({ text: stripSpookSpeechProps(scene.summary), speaker: null });
    for (const part of scene.participants || []) {
      script.push({ text: stripSpookSpeechProps(part.name), speaker: stripSpookSpeechProps(part.name) });
    }
    for (const d of scene.dialogue || []) {
      if (!d.speaker || !d.text) continue;
      const sp = stripSpookSpeechProps(d.speaker);
      const text = `${sp}: ${stripSpookSpeechProps(d.text)}`;
      if (seen.has(text)) continue;
      seen.add(text);
      script.push({ text, speaker: sp });
    }
  }
  state.spokenKeys.clear();
  for (const item of script) state.spokenKeys.add(item.text.toLowerCase().replace(/\s+/g, " ").trim());
  state.speakQueue = script
    .flatMap((item) => splitIntoUtterances(item.text).map((piece) => ({
      text: piece,
      voiceURI: pickVoiceForSpeaker(item.speaker)?.voiceURI || null,
    })))
    .filter((x) => x && x.text);
  state.speaking = true;
  setPlayChannelButton(true);
  speakQueueStep();
}

// ===== Voice registry / picker UI =======================================

function loadVoices() {
  if (!("speechSynthesis" in window)) {
    renderVoiceStatus("Browser does not expose speechSynthesis.", []);
    return;
  }
  const sync = () => {
    state.voices = (window.speechSynthesis.getVoices && window.speechSynthesis.getVoices().slice()) || [];
    state.voices.sort((a, b) => a.name.localeCompare(b.name));
    state.voiceByName.clear();
    state.voiceByURI.clear();
    for (const v of state.voices) {
      state.voiceByName.set(v.name, v);
      state.voiceByURI.set(v.voiceURI, v);
    }
    renderVoiceStatus(
      state.voices.length
        ? `${state.voices.length} voice${state.voices.length === 1 ? "" : "s"} ready. Click any card to set the matching archetype voice.`
        : "No voices detected yet - waiting for the browser to populate them.",
      state.voices,
    );
  };

  sync();
  if (window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = sync;
  }
  if (state.voices.length === 0) {
    // Some browsers (Windows) populate on a tick. Safety retry.
    setTimeout(sync, 250);
    setTimeout(sync, 1200);
  }
}

function renderVoiceStatus(message, voices) {
  const status = $("voice-status");
  if (status) status.textContent = message;

  const grid = $("voice-grid");
  if (!grid) return;
  if (!voices || !voices.length) return;

  // Limit the user-visible pool to a focused list: prefer English-localized
  // and reject very internal VoiceURI entries the engine emits.
  const preferred = voices.filter((v) => v.localService || /en[-_]/i.test(v.lang || "") || /english/i.test(v.name));
  const pool = preferred.length >= 4 ? preferred : voices;
  const top = pool.slice(0, 18);

  grid.innerHTML = top.map((v) => `
    <button type="button" class="voice-pick" data-voice="${escapeHtml(v.name)}" aria-pressed="${state.voiceAssignments[Object.keys(state.voiceAssignments).find((k) => state.voiceAssignments[k] === v.name)] ? "true" : "false"}">
      <span class="voice-pick-name">${escapeHtml(v.name)}</span>
      <span class="voice-pick-lang">${escapeHtml(v.lang || "default")}${v.localService ? " ✓" : ""}</span>
    </button>
  `).join("");
}

function bindVoiceClicks() {
  const grid = $("voice-grid");
  if (!grid) return;
  grid.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-voice]");
    if (!button) return;
    const voiceName = button.dataset.voice;
    const voice = state.voiceByName.get(voiceName);
    if (!voice) return;
    // Quick test utterance so the user hears the voice at the press.
    try {
      const probe = new SpeechSynthesisUtterance("Hello, this is how I will read for everyone.");
      probe.voice = voice;
      probe.rate = 0.94;
      window.speechSynthesis.speak(probe);
    } catch (e) { /* ignore */ }

    // Cycle: assign to first NPC with no voice assigned, or bucket-
    // rotate between speech roles. Simpler approach: prompt-free
    // cycling. For now, do nothing destructive. The user manually
    // picks; the system-wide voice registry still handles per-NPC
    // hash assignment by default.
    // TODO: persist per-name assignment when the user confirms.
  });
}

function bindFactionClicks() {
  const grid = $("channel-grid");
  if (!grid) return;
  grid.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-faction]");
    if (!button) return;
    selectFaction(button.dataset.faction);
  });
  const feed = $("channel-feed");
  if (feed) {
    feed.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-char]");
      if (button) showDossier(button.dataset.char, button.dataset.name);
    });
  }
  const playBtn = $("play-channel-btn");
  if (playBtn) playBtn.addEventListener("click", playActiveChannel);
  const refreshBtn = $("refresh-channel-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      if (state.activeFactionId) loadChannelStream(state.activeFactionId);
    });
  }
}

bindUi();
bindThreadClicks();
bindEpisodeClicks();
bindFactionClicks();
bindVoiceClicks();
loadFactions();
loadVoices();
loadWorldVitals();
loadThreads();
loadScenes();
startAutoRefresh();
