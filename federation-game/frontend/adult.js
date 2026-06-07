const API_URL = '';

        const METRIC_LABELS = {
            credits: 'Credits', fuel: 'Fuel', shields: 'Shields', hull: 'Hull',
            crew_morale: 'Crew Morale', discovered_sectors: 'Sectors', allies: 'Allies',
            federation_stability: 'Stability', public_trust: 'Public Trust',
            council_support: 'Council Support', constitutional_integrity: 'Constitution',
            rights_protection: 'Rights', emergency_powers: 'Emergency Power'
        };

        const GOVERNANCE_FIELDS = [
            'federation_stability', 'public_trust', 'council_support',
            'constitutional_integrity', 'rights_protection', 'emergency_powers'
        ];

        const SHIP_FIELDS = ['credits', 'fuel', 'shields', 'hull', 'crew_morale', 'allies'];

        let state = null;
        let currentEvent = null;
        let currentChoiceToken = null;

        function listPreview(items, limit = 6) {
            return (items || []).slice(0, limit).map(item => `<span class="tag">${item}</span>`).join('');
        }

        function renderAtlas(atlas) {
            const sections = [
                ['NPC System', atlas.npc_system, 'archetypes'],
                ['Creature Codex', atlas.creature_codex, 'species'],
                ['Technology Tree', atlas.technology_tree, 'capstones'],
                ['USS Chaosbringer', atlas.uss_chaosbringer, 'systems'],
            ];
            document.getElementById('federationAtlas').innerHTML = sections.map(([title, data, field]) => `<div class="atlas-card">
                <strong>${title}</strong>
                <p>${data.summary}</p>
                <div class="tagline-row">${listPreview(data[field])}</div>
            </div>`).join('');
        }

        function fillClass(key, value) {
            if (key === 'emergency_powers') return 'power';
            if (value >= 70) return 'good';
            if (value >= 40) return 'warn';
            return 'bad';
        }

        function renderMetric(key, value) {
            const capped = key === 'credits' || key === 'allies' ? Math.min(100, value) : value;
            return `<div class="metric">
                <div class="metric-label">${METRIC_LABELS[key] || key}</div>
                <div class="metric-value">${value}</div>
                <div class="bar"><div class="fill ${fillClass(key, capped)}" style="width: ${Math.max(0, Math.min(100, capped))}%"></div></div>
            </div>`;
        }

        function formatDeltas(deltas) {
            const entries = Object.entries(deltas || {});
            if (!entries.length) return 'no vector movement';
            return entries.map(([key, value]) => `${METRIC_LABELS[key] || key}: ${value > 0 ? '+' : ''}${value}`).join('\n');
        }

        function renderExplanation(decision) {
            if (!decision || !decision.explainability) return 'No decision recorded yet.';
            const e = decision.explainability;
            return `<strong>${decision.event}</strong><br>
                Choice: ${decision.choice}<br>
                Result: ${decision.result}<br><br>
                ${decision.blocked_by_no_gate ? `<strong>NO GATE:</strong> ${decision.no_gate_reason}<br><br>` : ''}
                Affected lane: ${decision.affected_lane || e.affected_lane}<br>
                Domain: ${e.domain}<br>
                Risk: ${e.risk}<br>
                Constitutional pressure: ${e.constitutional_pressure}<br>
                Rationale: ${decision.rationale || e.rationale}<br>
                Short-term gain: ${e.short_term_gain}<br>
                Long-term cost: ${e.long_term_cost}<br><br>
                Next safe action: ${decision.next_safe_action || e.next_safe_action}<br><br>
                ${decision.lesson || ''}`;
        }

        function renderLedger(entries) {
            if (!entries || !entries.length) return 'No ledger entries yet.';
            return entries.slice().reverse().map(entry => `<div class="entry">
                <div class="entry-title">TURN ${entry.turn}: ${entry.event}</div>
                <div class="entry-small">${entry.choice} -> ${entry.result}<br>${entry.blocked_by_no_gate ? 'NO GATE REFUSAL<br>' : ''}Lane: ${entry.affected_lane}<br>${entry.policy}<br>Next: ${entry.next_safe_action}</div>
                <div class="deltas">${formatDeltas(entry.deltas)}</div>
            </div>`).join('');
        }

        function updateState(nextState) {
            state = nextState;
            document.getElementById('governanceStatus').textContent = state.governance_status;
            document.getElementById('activePolicy').textContent = state.active_policy;
            document.getElementById('governanceMetrics').innerHTML = GOVERNANCE_FIELDS.map(key => renderMetric(key, state[key])).join('');
            document.getElementById('shipMetrics').innerHTML = SHIP_FIELDS.map(key => renderMetric(key, state[key])).join('');
            document.getElementById('decisionLedger').innerHTML = renderLedger(state.decision_ledger);
            document.getElementById('lastExplanation').innerHTML = renderExplanation(state.last_decision);
        }

        function renderEngineStatus(data) {
            const statusDiv = document.getElementById('engineStatus');
            
            // Create status grid
            let html = '<div class="grid two">';
            
            // Add each system status
            Object.keys(data.engine_systems_loaded).forEach(system => {
                const systemData = data[system] || {};
                const loaded = data.engine_systems_loaded[system].loaded;
                const statusClass = loaded ? 'system-loaded' : 'system-unloaded';
                const statusText = loaded ? '● Loaded' : '○ Not Loaded';
                
                html += `
                    <div class="metric ${statusClass}">
                        <div class="metric-label">${system.replace('_', ' ').toUpperCase()}</div>
      <div class="metric-value">${statusText}</div>
      </div>
      `;

      // Add specific metrics for each system
      if (loaded && Object.keys(systemData).length > 0) {
        // Skip internal status fields for cleaner display
        const displayKeys = Object.keys(systemData).filter(k => !k.endsWith('_status'));
        if (displayKeys.length > 0) {
          displayKeys.slice(0, 3).forEach(key => { // Show max 3 metrics per system
            const label = key.replace('_', ' ').toUpperCase();
            const value = systemData[key];
            html += `
      <div class="metric metric-small">
        <div class="metric-label">${label}</div>
        <div class="metric-value">${typeof value === 'object' ? JSON.stringify(value).substring(0, 20) + '...' : value}</div>
      </div>
      `;
          });
        }
      }
    });
            
            html += '</div>';
            
            // Add turn and phase info
            html += `
                <div class="metric">
                    <div class="metric-label">CURRENT TURN</div>
                    <div class="metric-value">${data.turn}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">GAME PHASE</div>
                    <div class="metric-value">${data.game_phase ? data.game_phase.replace('_', ' ').toUpperCase() : 'UNKNOWN'}</div>
                </div>
            `;
            
            statusDiv.innerHTML = html;
        }

  async function fetchAtlas() {
    const data = await fedFetch('atlas', `${API_URL}/atlas`);
    if (!data) return;
    renderAtlas(data);
  }

        async function fetchEngineStatus() {
            const data = await fedFetch('engineStatus', `${API_URL}/engine-status`);
            if (!data) return;
            renderEngineStatus(data);
        }

async function fetchState() {
  const data = await fedFetch('state', `${API_URL}/state`);
  if (!data) return;
  updateState(data);
  return data;
}

function updateEvent(event) {
  currentEvent = event;
  document.getElementById('eventTitle').textContent = event.title || 'Awaiting Input';
  document.getElementById('eventDescription').textContent = event.description || '';
  const domainEl = document.getElementById('eventDomain');
  const rightsEl = document.getElementById('eventRights');
  const riskEl = document.getElementById('eventRisk');
  if (domainEl) domainEl.textContent = event.domain || '—';
  if (rightsEl) rightsEl.textContent = (event.rights_at_stake || []).join(', ') || '—';
  if (riskEl) riskEl.textContent = event.constitutional_risk || '—';
  const choicesDiv = document.getElementById('choices');
  if (choicesDiv && event.choices) {
    choicesDiv.innerHTML = '';
    const colorClasses = ['', 'amber', 'violet', 'red'];
    event.choices.forEach((choice, i) => {
      const btn = document.createElement('button');
      if (choice.blocked_by_no_gate) {
        btn.className = 'choice-btn no-gate';
        btn.textContent = `${choice.text} / NO GATE`;
      } else {
        btn.className = `choice-btn ${colorClasses[i % colorClasses.length]}`;
        btn.textContent = choice.text;
      }
      btn.onclick = () => choose(choice.id);
      choicesDiv.appendChild(btn);
    });
  }
}

  async function loadEvent() {
    const data = await fedFetch('event', `${API_URL}/event`);
    if (!data) return;
    currentChoiceToken = data.choice_token || null;
    updateEvent(data);
  }

async function choose(choiceId) {
  const data = await fedFetch('choose', `${API_URL}/choose/${choiceId}?choice_token=${currentChoiceToken || ''}`, { method: 'POST' });
  if (!data) return;

  if (data.error && !data.outcome) {
    if (String(data.error).includes('choice token')) {
      currentChoiceToken = null;
    }
    await fetchState();
    await loadEvent();
    return;
  }

  if (data.new_state) {
    updateState(data.new_state);
    const turnEl = document.getElementById('turnCounter');
    if (turnEl && data.new_state.turn) turnEl.textContent = data.new_state.turn;
  }
  showOutcome(data);
  fetchConsciousness();
  fetchRivals();
  fetchPolitical();
}

function showOutcome(data) {
  const title = data.outcome || 'Decision Made';
  document.getElementById('outcomeTitle').textContent = title.toUpperCase();

  const deltasEl = document.getElementById('outcomeDeltas');
  const deltas = data.deltas || data.reward || {};
  const entries = Object.entries(deltas);
  if (entries.length > 0) {
    deltasEl.innerHTML = entries.map(([key, value]) => {
      const label = METRIC_LABELS[key] || key;
      const sign = value > 0 ? '+' : '';
      const cls = value > 0 ? 'delta-positive' : value < 0 ? 'delta-negative' : '';
      return `<span class="${cls}">${label}: ${sign}${value}</span>`;
    }).join('<br>');
    deltasEl.style.display = 'block';
  } else {
    deltasEl.innerHTML = 'No metric movement';
    deltasEl.style.display = 'block';
  }

  if (data.blocked_by_no_gate && data.no_gate_reason) {
    deltasEl.innerHTML = `<strong style="color: var(--red);">NO GATE REFUSAL</strong><br>${data.no_gate_reason}<br>` + deltasEl.innerHTML;
  }

  const explainEl = document.getElementById('outcomeExplain');
  if (data.explainability) {
    const e = data.explainability;
    explainEl.innerHTML = `<strong>Lane:</strong> ${e.affected_lane || '—'}<br><strong>Domain:</strong> ${e.domain || '—'}<br><strong>Risk:</strong> ${e.risk || '—'}<br><strong>Constitutional Pressure:</strong> ${e.constitutional_pressure || '—'}<br><strong>Rationale:</strong> ${e.rationale || '—'}<br><strong>Short-term gain:</strong> ${e.short_term_gain || '—'}<br><strong>Long-term cost:</strong> ${e.long_term_cost || '—'}<br><strong>Next safe action:</strong> ${e.next_safe_action || '—'}`;
    explainEl.style.display = 'block';
  } else {
    explainEl.style.display = 'none';
  }

  const lessonEl = document.getElementById('outcomeLesson');
  if (data.lesson) {
    lessonEl.textContent = data.lesson;
    lessonEl.style.display = 'block';
  } else {
    lessonEl.style.display = 'none';
  }

  const subEl = document.getElementById('outcomeSubeffects');
  let subHtml = '';
  if (data.rival_effects && Object.keys(data.rival_effects).length > 0) {
    const effects = [];
    for (const [rival, effect] of Object.entries(data.rival_effects)) {
      if (typeof effect === 'string' && effect) effects.push(`${rival}: ${effect}`);
      else if (typeof effect === 'object' && effect) effects.push(`${rival}: ${effect.description || effect.action || effect.effect || JSON.stringify(effect)}`);
    }
    if (effects.length > 0) subHtml += `<div class="turn-effect-card rival-effect"><div class="effect-label">Rival Activity</div><div class="effect-content">${effects.join('<br>')}</div></div>`;
  }
  if (data.political_effects && Object.keys(data.political_effects).length > 0) {
    const effects = [];
    for (const [key, val] of Object.entries(data.political_effects)) {
      if (typeof val === 'string' && val) effects.push(val);
      else if (Array.isArray(val) && val.length > 0) effects.push(...val);
      else if (typeof val === 'object' && val) effects.push(`${key}: ${val.description || val.name || JSON.stringify(val)}`);
    }
    if (effects.length > 0) subHtml += `<div class="turn-effect-card political-effect"><div class="effect-label">Political Developments</div><div class="effect-content">${effects.join('<br>')}</div></div>`;
  }
  if (data.history_arc) {
    const ha = data.history_arc;
    const parts = [];
    if (ha.era_changed) parts.push(`<strong>ERA SHIFT</strong>: ${ha.new_era || 'New Era'}`);
    if (ha.year) parts.push(`Year: ${ha.year}`);
    if (ha.narrative) parts.push(ha.narrative);
    if (ha.summary) parts.push(ha.summary);
    if (parts.length > 0) subHtml += `<div class="turn-effect-card history-effect"><div class="effect-label">History Arc</div><div class="effect-content">${parts.join('<br>')}</div></div>`;
  }
  subEl.innerHTML = subHtml;

  if (data.game_victory) {
    subHtml += `<div class="victory-banner"><div class="victory-text">${data.game_victory}</div></div>`;
    subEl.innerHTML = subHtml;
  }

  document.getElementById('outcomeOverlay').classList.add('show');

  if (data.game_over) {
    setTimeout(() => {
      document.getElementById('outcomeOverlay').classList.remove('show');
      const goText = data.game_victory || data.game_over;
      const isVictory = goText.includes('ENDURES') || goText.includes('VICTORY');
      document.getElementById('gameoverText').textContent = goText;
      document.getElementById('gameoverText').className = `gameover-text ${isVictory ? 'victory' : 'defeat'}`;
      if (state) {
        document.getElementById('gameoverStats').innerHTML = `
          <strong>Turns:</strong> ${state.turn || '?'}<br>
          <strong>Stability:</strong> ${state.federation_stability || '?'}<br>
          <strong>Public Trust:</strong> ${state.public_trust || '?'}<br>
          <strong>Council Support:</strong> ${state.council_support || '?'}<br>
          <strong>Constitution:</strong> ${state.constitutional_integrity || '?'}<br>
          <strong>Rights:</strong> ${state.rights_protection || '?'}
        `;
      }
      document.getElementById('gameoverOverlay').classList.add('show');
    }, 1500);
  }
}

function closeOutcome() {
  document.getElementById('outcomeOverlay').classList.remove('show');
  loadEvent();
}

function dismissTutorial() {
  document.getElementById('tutorialOverlay').classList.remove('show');
  localStorage.setItem('fed_adult_tutorial_shown', 'true');
}

function showTutorial() {
  document.getElementById('tutorialOverlay').classList.add('show');
}

function resetFromGameover() {
  document.getElementById('gameoverOverlay').classList.remove('show');
  resetGame();
}

  function renderTurnEffects(data) {
    const card = document.getElementById('turnEffectsCard');
    const container = document.getElementById('turnEffects');
    const victoryBanner = document.getElementById('victoryBanner');
    const victoryText = document.getElementById('victoryText');
    let html = '';
    let hasContent = false;

    // Rival effects
    if (data.rival_effects && Object.keys(data.rival_effects).length > 0) {
      const effects = [];
      for (const [rival, effect] of Object.entries(data.rival_effects)) {
        if (typeof effect === 'string' && effect) {
          effects.push(`<strong>${rival}</strong>: ${effect}`);
        } else if (typeof effect === 'object' && effect) {
          const desc = effect.description || effect.action || effect.effect || JSON.stringify(effect);
          effects.push(`<strong>${rival}</strong>: ${desc}`);
        }
      }
      if (effects.length > 0) {
        html += `<div class="turn-effect-card rival-effect"><div class="effect-label">Rival Activity</div><div class="effect-content">${effects.join('<br>')}</div></div>`;
        hasContent = true;
      }
    }

    // Political effects
    if (data.political_effects && Object.keys(data.political_effects).length > 0) {
      const effects = [];
      for (const [key, val] of Object.entries(data.political_effects)) {
        if (typeof val === 'string' && val) {
          effects.push(val);
        } else if (Array.isArray(val) && val.length > 0) {
          effects.push(...val);
        } else if (typeof val === 'object' && val) {
          effects.push(`${key}: ${val.description || val.name || JSON.stringify(val)}`);
        }
      }
      if (effects.length > 0) {
        html += `<div class="turn-effect-card political-effect"><div class="effect-label">Political Developments</div><div class="effect-content">${effects.join('<br>')}</div></div>`;
        hasContent = true;
      }
    }

    // History arc
    if (data.history_arc) {
      const ha = data.history_arc;
      const parts = [];
      if (ha.era_changed) parts.push(`<strong>ERA SHIFT</strong>: ${ha.new_era || 'New Era'}`);
      if (ha.year) parts.push(`Year: ${ha.year}`);
      if (ha.narrative) parts.push(ha.narrative);
      if (ha.summary) parts.push(ha.summary);
      if (parts.length > 0) {
        html += `<div class="turn-effect-card history-effect"><div class="effect-label">History Arc</div><div class="effect-content">${parts.join('<br>')}</div></div>`;
        hasContent = true;
      }
    }

    container.innerHTML = html;
    card.style.display = hasContent ? 'block' : 'none';

    // Victory
    if (data.game_victory) {
      victoryText.textContent = data.game_victory;
      victoryBanner.style.display = 'block';
      card.style.display = 'block';
    } else {
      victoryBanner.style.display = 'none';
    }
  }

  async function resetGame() {
    const data = await fedFetch('reset', `${API_URL}/reset`, { method: 'POST' });
    if (!data) return;
    if (data.state) updateState(data.state);
    await loadEvent();
  }

// Render rival federations
  async function fetchRivals() {
    const data = await fedFetch('rivals', `${API_URL}/rivals`);
    if (!data) return;
    const grid = document.getElementById('rivalGrid');
    if (!data.system_available || !data.rivals) {
      grid.innerHTML = '<div style="color: var(--muted); font-size: 0.85rem;">Rival system unavailable</div>';
      return;
    }
    const rivalData = data.rivals;
    const entries = rivalData.rivals || rivalData;
    const keys = Object.keys(entries).filter(k => typeof entries[k] === 'object' && entries[k].name);
    grid.innerHTML = keys.slice(0, 6).map(key => {
      const r = entries[key];
      const rel = (r.relationships && r.relationships.player) || 'neutral';
      const relClass = rel === 'hostile' ? 'hostile' : rel === 'friendly' ? 'friendly' : 'neutral';
      return `<div class="rival-entry ${relClass}">
        <strong>${r.name}</strong>
        <div class="rival-meta">
          ${r.personality} · Power ${(r.power * 100).toFixed(0)}% · Territory ${r.territory || 0} · <span class="rival-rel ${relClass}">${rel.toUpperCase()}</span>
        </div>
      </div>`;
    }).join('');
    if (keys.length > 6) {
      grid.innerHTML += `<div style="color: var(--muted); font-size: 0.8rem;">+${keys.length - 6} more rivals</div>`;
    }
  }

// Render consciousness sheet
  async function fetchConsciousness() {
    const data = await fedFetch('consciousness', `${API_URL}/consciousness`);
    if (!data) return;
    if (!data.system_available) return;
    document.getElementById('csIdentity').textContent = data.identity.toFixed(2);
    document.getElementById('csIdentityBar').style.width = (data.identity * 100) + '%';
    document.getElementById('csAnxiety').textContent = data.anxiety.toFixed(2);
    document.getElementById('csAnxietyBar').style.width = (data.anxiety * 100) + '%';
    document.getElementById('csConfidence').textContent = data.confidence.toFixed(2);
    document.getElementById('csConfidenceBar').style.width = (data.confidence * 100) + '%';
    document.getElementById('csExpansion').textContent = data.expansion_hunger.toFixed(2);
    document.getElementById('csExpansionBar').style.width = (data.expansion_hunger * 100) + '%';
    document.getElementById('csDiplomacy').textContent = data.diplomacy_tendency.toFixed(2);
    document.getElementById('csDiplomacyBar').style.width = (data.diplomacy_tendency * 100) + '%';
    // Render tags
    const tags = document.getElementById('csTags');
    let html = '';
    (data.dreams || []).forEach(d => { html += `<span class="cs-tag dream">Dream: ${d}</span>`; });
    (data.prophecies || []).forEach(p => { html += `<span class="cs-tag prophecy">Prophecy: ${p}</span>`; });
    (data.traumas || []).forEach(t => { html += `<span class="cs-tag trauma">Trauma: ${t}</span>`; });
    (data.archetypes || []).forEach(a => { html += `<span class="cs-tag archetype">${a}</span>`; });
    tags.innerHTML = html;
  }

// Render political engine status
  async function fetchPolitical() {
    const data = await fedFetch('political', `${API_URL}/political`);
    if (!data) return;
    const div = document.getElementById('politicalStatus');
    if (!data.system_available) {
      div.innerHTML = '<div style="color: var(--muted);">Political system not loaded</div>';
      return;
    }
    const status = data.status || {};
    let html = '<div class="political-summary">';
    html += `<div style="color: var(--violet); font-weight: 800; text-transform: uppercase; margin-bottom: 0.5rem;">Political Engine Active</div>`;
    if (typeof status === 'object') {
      Object.entries(status).slice(0, 6).forEach(([key, value]) => {
        const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const display = typeof value === 'object' ? JSON.stringify(value).substring(0, 40) : value;
        html += `<div style="color: var(--muted); font-size: 0.85rem;"><strong style="color: var(--text);">${label}:</strong> ${display}</div>`;
      });
    } else {
      html += `<div style="color: var(--muted);">${status}</div>`;
    }
    html += '</div>';
    div.innerHTML = html;
  }

// Render systems overview
  async function fetchSystemsOverview() {
    const data = await fedFetch('systemsOverview', `${API_URL}/systems-overview`);
    if (!data) return;
    const grid = document.getElementById('systemsGrid');
    const summary = document.getElementById('systemsSummary');
    const allSystems = { ...data.core_systems, ...data.new_systems };
    let html = '';
    for (const [name, isLoaded] of Object.entries(allSystems)) {
      const label = name.replace(/_/g, ' ');
      html += `<div class="system-chip ${isLoaded ? 'loaded' : 'unloaded'}">
        <div class="system-dot ${isLoaded ? 'loaded' : 'unloaded'}"></div>
        ${label}
      </div>`;
    }
    grid.innerHTML = html;
    summary.textContent = `${data.integration_status.loaded_systems}/${data.integration_status.total_systems} systems loaded · Turn ${data.turn}`;
  }

// Initialize
fetchState().then((data) => {
  loadEvent();
  if (data && data.turn) {
    const turnEl = document.getElementById('turnCounter');
    if (turnEl) turnEl.textContent = data.turn;
  }
});
fetchAtlas();
fetchEngineStatus();
fetchRivals();
fetchConsciousness();
fetchPolitical();
fetchSystemsOverview();

// Show tutorial on first visit
if (!localStorage.getItem('fed_adult_tutorial_shown')) {
  document.getElementById('tutorialOverlay').classList.add('show');
}
