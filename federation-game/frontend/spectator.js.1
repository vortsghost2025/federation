const state = {
  paused: false,
  lastSummary: null,
  timer: null,
};

function $(id) { return document.getElementById(id); }

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>\"]/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
  }[ch]));
}

function relationshipText(delta) {
  if (delta === null || delta === undefined || delta === '') return '';
  const value = Number(delta);
  const sign = value >= 0 ? '+' : '';
  const cls = value >= 0 ? 'relationship-positive' : 'relationship-negative';
  return `<span class="${cls}">Relationship ${sign}${value.toFixed(1)}</span>`;
}

function renderEvents(events) {
  const container = $('event-list');
  if (!events || !events.length) {
    container.innerHTML = '<p class="empty">No visible events yet. The world is still thinking.</p>';
    return;
  }

  container.innerHTML = events.map(event => {
    const rel = relationshipText(event.relationship_delta);
    const target = event.target_name ? `<span>Target: ${escapeHtml(event.target_name)}</span>` : '';
    const meta = [
      `<span>${escapeHtml(event.entry_type)}</span>`,
      `<span>${escapeHtml(event.category)}</span>`,
      target,
      rel,
    ].filter(Boolean).join('');
    return `
      <article class="event-card ${escapeHtml(event.entry_type)}">
        <div class="event-meta">${meta}</div>
        <div class="event-summary">${escapeHtml(event.summary)}</div>
      </article>
    `;
  }).join('');
}

function renderPulse(summary) {
  const distribution = summary.distribution || {};
  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const counts = summary.entry_counts || {};
  const parts = [
    ['Mood', summary.mood || 'Watching'],
    ['Interactions', counts.interaction || 0],
    ['Decisions', counts.decision || 0],
    ['Deep Thoughts', counts.cognition || 0],
    ...entries.map(([name, count]) => [name.replace(/_/g, ' '), count]),
  ];
  $('pulse-list').innerHTML = parts.map(([label, value]) => `
    <div class="pulse-item"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></div>
  `).join('');
}

function renderSuggestions(items) {
  const box = $('suggestions');
  box.innerHTML = (items || []).map(text => (
    `<button type="button" data-question="${escapeHtml(text)}">${escapeHtml(text)}</button>`
  )).join('');
  box.querySelectorAll('button').forEach(button => {
    button.addEventListener('click', () => {
      $('question-input').value = button.dataset.question;
      $('assistant-form').requestSubmit();
    });
  });
}

function renderSummary(summary) {
  state.lastSummary = summary;
  $('headline').textContent = summary.headline || 'The world is alive.';
  $('plain-summary').textContent = summary.summary || 'The Federation is between visible moments.';
  renderEvents(summary.events || []);
  renderPulse(summary);
  renderSuggestions(summary.ask_suggestions || []);
}

async function loadSummary() {
  try {
    const response = await fetch('/spectator/summary?limit=120', { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderSummary(await response.json());
  } catch (error) {
    $('headline').textContent = 'The signal is unclear.';
    $('plain-summary').textContent = 'The spectator feed could not load. I will keep trying.';
  }
}

function readAloud() {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const summary = state.lastSummary;
  const text = summary
    ? `${summary.headline}. ${summary.summary}. ${(summary.events || []).map(event => event.summary).join('. ')}`
    : 'The world is waking up.';
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.92;
  utterance.pitch = 0.96;
  window.speechSynthesis.speak(utterance);
}

async function askAssistant(question) {
  const answer = $('assistant-answer');
  answer.textContent = 'Listening to the world...';
  try {
    const response = await fetch('/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();
    answer.textContent = data.answer || 'The assistant did not have an answer.';
  } catch (error) {
    answer.textContent = 'The assistant could not answer right now. The world is still running.';
  }
}

function setPaused(paused) {
  state.paused = paused;
  $('pause-btn').textContent = paused ? 'Resume Auto' : 'Pause Auto';
}

function startAutoRefresh() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!state.paused) loadSummary();
  }, 60000);
}

$('refresh-btn').addEventListener('click', loadSummary);
$('read-btn').addEventListener('click', readAloud);
$('pause-btn').addEventListener('click', () => setPaused(!state.paused));
$('assistant-form').addEventListener('submit', event => {
  event.preventDefault();
  const question = $('question-input').value.trim();
  if (!question) return;
  askAssistant(question);
});

window.addEventListener('keydown', event => {
  if (event.code === 'Space' && event.target === document.body) {
    event.preventDefault();
    setPaused(!state.paused);
  }
  if (event.key.toLowerCase() === 'r') loadSummary();
});

loadSummary();
startAutoRefresh();
