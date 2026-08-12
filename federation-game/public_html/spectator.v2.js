const state = {
  paused: false,
  lastEvents: [],
  lastAnalyze: null,
  timer: null,
  seenKeys: new Set(),
  npcNameMap: {},
  factionNameMap: {},
};

function $(id) { return document.getElementById(id); }

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>\"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
  }[ch]));
}

function relDeltaClass(delta) {
  if (delta === null || delta === undefined || delta === '') return '';
  return Number(delta) >= 0 ? 'positive' : 'negative';
}

function relDeltaText(delta) {
  if (delta === null || delta === undefined || delta === '') return '';
  const v = Number(delta);
  if (v === 0) return '0';
  return v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}

function eventKey(ev) {
  const who = ev.npc_id || ev.char_id || ev.source_char_id || '';
  const partners = (ev.char_ids || []).filter(c => c && c !== who).sort().join(',');
  const desc = (ev.description || ev.summary || '').slice(0, 50);
  const etype = ev.event_type || ev.action_type || ev.task_class || '';
  const ts = ev.timestamp || ev.ts || 0;
  return `${who}:${partners}:${etype}:${desc}:${ts}`;
}

function timeAgo(ts) {
  const sec = Math.max(0, Math.floor((Date.now() / 1000) - ts));
  if (sec < 5) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function classifyEvent(ev) {
  if (ev.event_type === 'npc_interaction' || ev.action_type === 'alliance' || ev.action_type === 'betrayal' || ev.action_type === 'conflict') return 'interaction';
  if (ev.thought || ev.mood) return 'thought';
  if (ev.task_class === 'leader' && ev.output_text) return 'thought';
  if (ev.action_type) return 'action';
  if (ev.event_type === 'broadcast_event' || ev.visibility === 'public') return 'broadcast';
  return 'world';
}

function extractNpcName(ev) {
  const raw = ev.char_name || ev.source_char_name || ev.npc_id || 'Unknown';
  return state.npcNameMap[raw] || raw;
}

function extractFaction(ev) {
  const raw = ev.source_affiliation || ev.faction || ev.affiliation || '';
  return state.factionNameMap[raw] || raw || '';
}

function truncateWords(text, maxLen) {
  if (!text) return '';
  text = text.trim();
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trim() + '...';
}

function renderVibe(data) {
  if (!data || !data.system_available) return;
  const pairs = [
    ['anxiety', 'g-anxiety', 'gv-anxiety', 'Anxiety'],
    ['confidence', 'g-confidence', 'gv-confidence', 'Confidence'],
    ['expansion_hunger', 'g-expansion', 'gv-expansion', 'Expansion'],
    ['morale', 'g-morale', 'gv-morale', 'Morale'],
  ];
  pairs.forEach(([key, barId, valId, label]) => {
    const val = Math.round((data[key] || 0) * 100);
    const bar = $(barId);
    const valEl = $(valId);
    if (bar) { bar.style.width = `${val}%`; bar.setAttribute('aria-valuenow', val); bar.setAttribute('aria-label', `${label}: ${val}%`); }
    if (valEl) valEl.textContent = `${val}%`;
  });
}

function renderFactionPulse(data) {
  const container = $('faction-pulse');
  if (!container || !data || !data.factions) return;
  const factions = data.factions;
  container.innerHTML = Object.entries(factions).map(([id, f]) => {
    const name = escapeHtml(f.name || id);
    const ideology = f.ideology ? `<span style="font-size:9px;color:var(--dim)">${escapeHtml(f.ideology)}</span>` : '';
    const power = f.power != null ? Number(f.power) : 0;
    return `<div class="faction-chip"><span class="fname">${name}</span>${ideology}<div class="fbar"><div class="ffill" style="width:${power}%"></div></div><span style="font-size:10px;color:var(--dim)">${power}%</span></div>`;
  }).join('');
}

function renderHeadline(summary) {
  const el = $('headline');
  if (!el || !summary) return;
  const mood = summary.mood ? `${summary.mood}: ` : '';
  const headline = summary.headline || summary.summary || 'The Federation continues.';
  el.textContent = `${mood}${headline}`;
}

function renderEventCard(ev) {
  const type = classifyEvent(ev);
  const isNeg = (type === 'interaction' && Number(ev.relationship_delta) < 0);
  const cls = `event-card type-${type}${isNeg ? ' negative' : ''}`;

  const name = escapeHtml(extractNpcName(ev));
  const faction = escapeHtml(extractFaction(ev));
  const delta = ev.relationship_delta;

  // Use output_text as the "what they said" when available — this is the real NPC voice
  let body = '';
  let reasoning = '';
  if (ev.output_text) {
    body = truncateWords(ev.output_text.replace(/\n/g, ' '), 280);
    reasoning = '';
  } else if (ev.description) {
    body = truncateWords(ev.description, 280);
  } else if (ev.summary) {
    body = truncateWords(ev.summary, 280);
  } else if (ev.input_text) {
    body = truncateWords(ev.input_text, 200);
  } else {
    body = '—';
  }

  if (ev.thought && !ev.output_text) {
    reasoning = truncateWords(ev.thought.replace(/\n/g, ' '), 200);
  } else if (ev.mood && !ev.reasoning) {
    reasoning = `Mood: ${ev.mood}`;
  }

  const ts = ev.timestamp || ev.ts || 0;
  const time = timeAgo(ts);

  const badgeLabel = type.toUpperCase();
  const factionHtml = faction ? `<span class="faction-tag">${faction}</span>` : '';
  const deltaHtml = delta !== null && delta !== undefined && delta !== '' ? `<span class="rel-delta ${relDeltaClass(delta)}">Relationship ${relDeltaText(delta)}</span>` : '';
  const reasoningHtml = reasoning ? `<div class="event-reasoning">${escapeHtml(reasoning)}</div>` : '';
  // Show the "words spoken" label if this is an interaction or action with output_text
  const wordsLabel = ev.output_text ? '<span style="font-size:10px;color:var(--cyan);margin-left:6px">their words ↓</span>' : '';
  // Show who they interacted with
  let partnerHtml = '';
  if (ev.char_ids && ev.char_ids.length > 1) {
    const partners = ev.char_ids.filter(c => c !== (ev.npc_id || ev.char_id || ev.source_char_id));
    if (partners.length) partnerHtml = `<span style="font-size:10px;color:var(--dim)">with ${partners.map(escapeHtml).join(', ')}</span>`;
  }

  return `<article class="${cls}" role="article" aria-label="${badgeLabel}: ${name}. ${body}">
    <div class="event-meta">
      <span class="event-type-badge">${badgeLabel}</span>
      <span class="npc-name">${name}</span>
      ${factionHtml}
      ${partnerHtml}
      <span>${time}</span>
      ${deltaHtml}
      ${wordsLabel}
    </div>
    <div class="event-body">${escapeHtml(body)}</div>
    ${reasoningHtml}
  </article>`;
}

function renderTimeline(events) {
  const container = $('feed');
  const empty = $('empty-state');
  if (!container) return;
  if (!events || !events.length) {
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  const cards = events.map(renderEventCard).join('');
  container.innerHTML = cards + container.innerHTML;
}

function mergeEvents(newEvents) {
  const merged = [...newEvents];
  for (const ev of state.lastEvents) {
    const k = eventKey(ev);
    if (!state.seenKeys.has(k)) {
      merged.push(ev);
      state.seenKeys.add(k);
    }
  }
  merged.sort((a, b) => {
    const ta = (a.timestamp || a.ts || 0);
    const tb = (b.timestamp || b.ts || 0);
    return tb - ta;
  });
  return merged.slice(0, 80);
}

function renderRelationships(analyze) {
  const container = $('rel-content');
  if (!container) return;
  if (!analyze || analyze.status !== 'ok') {
    container.innerHTML = '<p style="color:var(--dim)">Relationship data loading...</p>';
    return;
  }

  const fleet = analyze.fleet || [];
  const mostActive = [...fleet].sort((a, b) => (b.turn_count || 0) - (a.turn_count || 0)).slice(0, 8);

  let html = '';
  if (mostActive.length) {
    html += '<div class="rel-section"><h3>Most Active</h3>';
    mostActive.forEach(npc => {
      const change = npc.recent_change || '';
      const changeLabel = change ? `<span style="font-size:10px;color:var(--dim);margin-left:4px">${escapeHtml(change.slice(0,40))}</span>` : '';
      html += `<div class="rel-row"><span class="rel-names">${escapeHtml(npc.npc_id)}</span><span style="color:var(--cyan)">${npc.turn_count} ticks</span>${changeLabel}</div>`;
    });
    html += '</div>';
  }

  container.innerHTML = html || '<p style="color:var(--dim)">No relationship data yet.</p>';
}

function renderNarrator(data) {
  const container = $('narrator-content');
  if (!container) return;
  if (!data || !data.recent || !data.recent.length) {
    container.innerHTML = '<p style="color:var(--dim)">No narration yet.</p>';
    return;
  }
  container.innerHTML = data.recent.map(entry =>
    `<div class="narrator-entry"><div style="color:var(--violet);font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">${escapeHtml(entry.type || 'narration')}</div><div>${escapeHtml((entry.text || entry.content || entry.summary || '')).slice(0,300)}</div></div>`
  ).join('');
}

async function fetchJson(path) {
  const r = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    throw new Error(`HTTP ${r.status} ${path} ${text.slice(0,100)}`);
  }
  return r.json();
}

async function fetchWorldState() {
  try {
    const [npcsData, summary, consciousness, factions, turns, analyze, narrator] = await Promise.all([
      fetchJson('/npcs?limit=250').catch(() => null),
      fetchJson('/spectator/summary?limit=20').catch(() => null),
      fetchJson('/consciousness').catch(() => null),
      fetchJson('/factions').catch(() => null),
      fetchJson('/npc-turns?limit=30').catch(() => null),
      fetchJson('/npc-turns/analyze').catch(() => null),
      fetchJson('/narrator').catch(() => null),
    ]);

    // Build NPC name lookup
    if (npcsData && npcsData.npcs) {
      npcsData.npcs.forEach(n => {
        if (n.char_id && n.name) state.npcNameMap[n.char_id] = n.name;
      });
    }

    if (factions && factions.factions) {
      state.factionNameMap = {};
      Object.entries(factions.factions).forEach(([id, f]) => {
        state.factionNameMap[id] = f.name || id;
      });
    }

    // Build event list from npc-turns (these have the actual words)
    const turnEvents = [];
    if (turns && turns.results) {
      turns.results.forEach(turn => {
        turnEvents.push({
          npc_id: turn.npc_id,
          char_name: turn.npc_id,
          task_class: turn.task_class,
          output_text: turn.output_text,
          input_text: turn.input_text,
          mood: turn.mood,
          timestamp: turn.timestamp,
          turn_id: turn.turn_id,
          event_type: 'npc_turn',
          action_type: turn.task_class,
        });
      });
    }

    // Also pull events from summary (these have relationship deltas and interactions)
    const summaryEvents = [];
    if (summary && summary.events) {
      summary.events.forEach(ev => {
        summaryEvents.push({
          ...ev,
          source: 'summary',
        });
      });
    }

    // Merge: prefer turn events for "what they said", summary events for interactions
    const merged = mergeEvents([...turnEvents, ...summaryEvents]);
    state.lastEvents = merged;
    renderTimeline(merged);

    if (consciousness) renderVibe(consciousness);
    if (factions) renderFactionPulse(factions);
    if (analyze) { state.lastAnalyze = analyze; renderRelationships(analyze); }
    if (narrator) renderNarrator(narrator);
  } catch (err) {
    console.error('Spectator fetch failed:', err);
    const headline = $('headline');
    if (headline && !headline.textContent.includes('.')) {
      headline.textContent = 'Signal disrupted. Retrying...';
    }
  }
}

async function askAssistant(question) {
  const answerEl = $('assistant-answer');
  if (answerEl) answerEl.textContent = 'Listening...';
  try {
    const r = await fetch('/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await r.json();
    if (answerEl) {
      const ans = data.answer || data.response || data.text || JSON.stringify(data).slice(0, 300);
      answerEl.textContent = ans;
    }
  } catch (err) {
    if (answerEl) answerEl.textContent = 'The oracle is quiet right now. The world is still running — try again in a moment.';
  }
}

function setPaused(paused) {
  state.paused = paused;
  const btn = $('pause-btn');
  if (btn) btn.textContent = paused ? '▶ Resume' : '⏸ Pause';
}

function startAutoRefresh() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!state.paused) fetchWorldState();
  }, 60000);
}

function readAloud() {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const parts = [];
  const headline = $('headline')?.textContent;
  if (headline) parts.push(headline);
  const cards = document.querySelectorAll('.event-card');
  const latest = Array.from(cards).slice(0, 3);
  latest.forEach(card => {
    const body = card.querySelector('.event-body')?.textContent;
    const name = card.querySelector('.npc-name')?.textContent;
    if (body && name) parts.push(`${name} said: ${body}`);
  });
  const text = parts.join('. ') || 'The Federation is awake.';
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.92;
  u.pitch = 0.96;
  window.speechSynthesis.speak(u);
}

document.addEventListener('DOMContentLoaded', () => {
  const refreshBtn = $('refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', fetchWorldState);

  const pauseBtn = $('pause-btn');
  if (pauseBtn) pauseBtn.addEventListener('click', () => setPaused(!state.paused));

  const readBtn = $('read-btn');
  if (readBtn) readBtn.addEventListener('click', readAloud);

  const assistantForm = $('assistant-form');
  if (assistantForm) {
    assistantForm.addEventListener('submit', e => {
      e.preventDefault();
      const input = $('question-input');
      const q = input?.value.trim();
      if (q) askAssistant(q);
    });
  }

  window.addEventListener('keydown', e => {
    if (e.code === 'Space' && document.activeElement === document.body) {
      e.preventDefault();
      setPaused(!state.paused);
    }
    if (e.key === 'r' && document.activeElement === document.body) fetchWorldState();
  });

  fetchWorldState();
  startAutoRefresh();
});
