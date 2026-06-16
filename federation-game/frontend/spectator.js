"use strict";

const state = {
  paused: false,
  timer: null,
  scenes: [],
  lastSignature: "",
  currentDossierCharId: null,
  refreshMs: 30000,
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

function readAloud() {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const parts = [];
  const headline = $("headline")?.textContent;
  if (headline) parts.push(headline);
  for (const scene of state.scenes.slice(0, 4)) {
    if (scene.summary) parts.push(scene.summary);
    for (const d of scene.dialogue || []) {
      if (d.speaker && d.text) parts.push(`${d.speaker}: ${d.text}`);
    }
  }
  if (!parts.length) parts.push("The world is waking up.");
  const utterance = new SpeechSynthesisUtterance(parts.join(". "));
  utterance.rate = 0.92;
  utterance.pitch = 0.96;
  window.speechSynthesis.speak(utterance);
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
  state.timer = setInterval(() => {
    if (!state.paused) loadScenes();
  }, state.refreshMs);
}

function bindUi() {
  $("refresh-btn").addEventListener("click", () => loadScenes());
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
    }
  });
}

bindUi();
loadScenes();
startAutoRefresh();
