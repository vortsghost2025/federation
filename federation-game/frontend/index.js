const API_URL = '';
        
        // Event icons (emoji for now, can be replaced with SVGs)
        const EVENT_ICONS = {
            alien_ship: '👽',
            nebula: '🌌',
            distress: '📡',
            asteroid: '☄️',
            station: '🛸',
            anomaly: '🌀',
            council: '⚖️',
            default: '🚀'
        };

        let gameState = null;
        let currentEvent = null;

        const METRIC_LABELS = {
            credits: 'credits',
            fuel: 'fuel',
            shields: 'shields',
            hull: 'hull',
            crew_morale: 'crew morale',
            discovered_sectors: 'sectors',
            allies: 'allies',
            federation_stability: 'stability',
            public_trust: 'public trust',
            council_support: 'council support',
            constitutional_integrity: 'constitutional integrity',
            rights_protection: 'rights protection',
            emergency_powers: 'emergency powers'
        };

// Create stars background
        function createStars() {
            const container = document.getElementById('stars');
            for (let i = 0; i < 200; i++) {
                const star = document.createElement('div');
                star.className = 'star';
                star.style.left = Math.random() * 100 + '%';
                star.style.top = Math.random() * 100 + '%';
                star.style.width = Math.random() * 3 + 1 + 'px';
                star.style.height = star.style.width;
                star.style.animationDelay = Math.random() * 2 + 's';
                container.appendChild(star);
            }
        }

        // Update UI with game state
        function updateUI(state) {
            gameState = state;
            document.getElementById('turn').textContent = state.turn;
            document.getElementById('credits').textContent = state.credits;
            document.getElementById('fuel').textContent = state.fuel;
            document.getElementById('shields').textContent = state.shields;
            document.getElementById('hull').textContent = state.hull;
            document.getElementById('morale').textContent = state.crew_morale;
            document.getElementById('sectors').textContent = state.discovered_sectors;
            document.getElementById('allies').textContent = state.allies;
            document.getElementById('stability').textContent = state.federation_stability;
            document.getElementById('publicTrust').textContent = state.public_trust;
            document.getElementById('councilSupport').textContent = state.council_support;
            document.getElementById('constitution').textContent = state.constitutional_integrity;
            document.getElementById('rights').textContent = state.rights_protection;
            document.getElementById('emergency').textContent = state.emergency_powers;
            document.getElementById('governanceStatus').textContent = state.governance_status;
            document.getElementById('activePolicy').textContent = state.active_policy;

            // Update progress bars
            document.getElementById('fuelBar').style.width = state.fuel + '%';
            document.getElementById('shieldsBar').style.width = state.shields + '%';
            document.getElementById('hullBar').style.width = state.hull + '%';
            document.getElementById('moraleBar').style.width = state.crew_morale + '%';
            document.getElementById('stabilityBar').style.width = state.federation_stability + '%';
            document.getElementById('trustBar').style.width = state.public_trust + '%';
            document.getElementById('councilBar').style.width = state.council_support + '%';
            document.getElementById('constitutionBar').style.width = state.constitutional_integrity + '%';
            document.getElementById('rightsBar').style.width = state.rights_protection + '%';
            document.getElementById('emergencyBar').style.width = state.emergency_powers + '%';

            const policyLog = document.getElementById('policyLog');
            if (state.proposal_history && state.proposal_history.length > 0) {
                policyLog.innerHTML = state.proposal_history.slice().reverse().map(p =>
                    `<li>T${p.turn}: ${p.domain} - ${p.decision}<br>${p.policy}</li>`
                ).join('');
            } else {
                policyLog.innerHTML = '<li>No council decisions yet</li>';
            }

  const decisionLedger = document.getElementById('decisionLedger');
  if (state.decision_ledger && state.decision_ledger.length > 0) {
    decisionLedger.innerHTML = state.decision_ledger.slice().reverse().map(d => {
      const deltaEntries = Object.entries(d.deltas || {});
      const deltaHtml = deltaEntries.length > 0
        ? deltaEntries.map(([key, value]) => {
            const label = METRIC_LABELS[key] || key;
            const sign = value > 0 ? '+' : '';
            const cls = value > 0 ? 'delta-positive' : value < 0 ? 'delta-negative' : '';
            return `<span class="${cls}">${label}: ${sign}${value}</span>`;
          }).join(' | ')
        : 'No metric movement';
      return `<li>T${d.turn}: ${d.event}<br>${d.choice} - ${d.result}<br>${d.blocked_by_no_gate ? '<strong style="color: var(--lcars-red);">NO GATE REFUSAL</strong><br>' : ''}LANE: ${d.affected_lane}<br>NEXT: ${d.next_safe_action}<br>${deltaHtml}</li>`;
    }).join('');
  } else {
    decisionLedger.innerHTML = '<li>No decisions recorded</li>';
  }

            // Update tech list
            const techList = document.getElementById('techList');
            if (state.technologies_unlocked.length > 0) {
                techList.innerHTML = state.technologies_unlocked.map(t => 
                    `<li>${t.replace(/_/g, ' ')}</li>`
                ).join('');
            } else {
                techList.innerHTML = '<li>None discovered</li>';
            }

            // Update stardate
            const stardate = 47634.44 + (state.turn * 0.1);
            document.getElementById('stardate').textContent = stardate.toFixed(2);
        }

        // Load event
        function loadEvent(event) {
            currentEvent = event;
            document.getElementById('loading').style.display = 'none';
            document.getElementById('eventContent').style.display = 'block';

            document.getElementById('eventIcon').textContent = EVENT_ICONS[event.image] || EVENT_ICONS.default;
            document.getElementById('eventTitle').textContent = event.title;
            document.getElementById('eventDesc').textContent = event.description;

            const eventMeta = document.getElementById('eventMeta');
            if (event.domain) {
                const rights = (event.rights_at_stake || []).join(', ');
                eventMeta.innerHTML = `LANE: ${event.affected_lane || 'Control Plane'}<br>DOMAIN: ${event.domain}<br>RIGHTS: ${rights}<br>RISK: ${event.constitutional_risk}<br>${event.pressure || ''}`;
            } else {
                eventMeta.innerHTML = '';
            }

            const choicesDiv = document.getElementById('choices');
            choicesDiv.innerHTML = '';

            const colors = ['', 'blue', 'purple', 'red'];
            event.choices.forEach((choice, i) => {
                const btn = document.createElement('button');
                btn.className = `choice-btn ${colors[i % colors.length]}`;
                btn.textContent = choice.blocked_by_no_gate ? `${choice.text} / NO GATE` : choice.text;
                btn.onclick = () => makeChoice(choice.id);
                choicesDiv.appendChild(btn);
            });
        }

        // API calls
        async function fetchState() {
            try {
                const resp = await fetch(`${API_URL}/state`);
                const data = await resp.json();
                updateUI(data);
            } catch (e) {
                console.error('Failed to fetch state:', e);
            }
        }

        async function newEvent() {
            try {
                const resp = await fetch(`${API_URL}/event`);
                const data = await resp.json();
                loadEvent(data);
            } catch (e) {
                console.error('Failed to fetch event:', e);
            }
        }

async function makeChoice(choiceId) {
  if (!currentEvent) return;

  try {
    const resp = await fetch(`${API_URL}/choose/${choiceId}`, { method: 'POST' });
    const data = await resp.json();

    // Show outcome
    document.getElementById('outcomeText').textContent = data.outcome.toUpperCase();

    // Victory display
    const victoryEl = document.getElementById('outcomeVictory');
    if (data.game_victory) {
      victoryEl.textContent = data.game_victory;
      victoryEl.style.display = 'block';
    } else {
      victoryEl.style.display = 'none';
    }

    // Color-coded deltas
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
    } else {
      deltasEl.innerHTML = 'No metric movement';
    }

    // No Gate refusal
    if (data.blocked_by_no_gate && data.no_gate_reason) {
      deltasEl.innerHTML = `<strong style="color: var(--lcars-red);">NO GATE REFUSAL</strong><br>${data.no_gate_reason}<br>` + deltasEl.innerHTML;
    }

    // Explainability box
    const explainEl = document.getElementById('outcomeExplainBox');
    if (data.explainability) {
      const e = data.explainability;
      explainEl.innerHTML = `<strong>Lane:</strong> ${e.affected_lane || '—'}<br><strong>Domain:</strong> ${e.domain || '—'}<br><strong>Risk:</strong> ${e.risk || '—'}<br><strong>Constitutional Pressure:</strong> ${e.constitutional_pressure || '—'}<br><strong>Rationale:</strong> ${e.rationale || '—'}<br><strong>Short-term gain:</strong> ${e.short_term_gain || '—'}<br><strong>Long-term cost:</strong> ${e.long_term_cost || '—'}<br><strong>Next safe action:</strong> ${e.next_safe_action || '—'}`;
      explainEl.style.display = 'block';
    } else {
      explainEl.style.display = 'none';
    }

    // Lesson
    const lessonEl = document.getElementById('outcomeLesson');
    if (data.lesson) {
      lessonEl.textContent = data.lesson;
      lessonEl.style.display = 'block';
    } else {
      lessonEl.style.display = 'none';
    }

    // Render per-turn subsystem feedback
    const subEl = document.getElementById('outcomeSubsections');
    let subHtml = '';

    // Rival effects
    if (data.rival_effects && Object.keys(data.rival_effects).length > 0) {
      const effects = [];
      for (const [rival, effect] of Object.entries(data.rival_effects)) {
        if (typeof effect === 'string' && effect) {
          effects.push(`${rival}: ${effect}`);
        } else if (typeof effect === 'object' && effect) {
          const desc = effect.description || effect.action || effect.effect || JSON.stringify(effect);
          effects.push(`${rival}: ${desc}`);
        }
      }
      if (effects.length > 0) {
        subHtml += `<div class="outcome-subsection rival-sub"><div class="sub-label">Rival Activity</div><div class="sub-content">${effects.join('<br>')}</div></div>`;
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
        subHtml += `<div class="outcome-subsection political-sub"><div class="sub-label">Political Developments</div><div class="sub-content">${effects.join('<br>')}</div></div>`;
      }
    }

    // History arc effects
    if (data.history_arc) {
      const ha = data.history_arc;
      const parts = [];
      if (ha.era_changed) parts.push(`ERA SHIFT: ${ha.new_era || 'New Era'}`);
      if (ha.year) parts.push(`Year: ${ha.year}`);
      if (ha.narrative) parts.push(ha.narrative);
      if (ha.summary) parts.push(ha.summary);
      if (parts.length > 0) {
        subHtml += `<div class="outcome-subsection history-sub"><div class="sub-label">History Arc</div><div class="sub-content">${parts.join('<br>')}</div></div>`;
      }
    }

    subEl.innerHTML = subHtml;

    document.getElementById('outcomeOverlay').classList.add('show');

    // Check game over
    if (data.game_over) {
      setTimeout(() => {
        document.getElementById('outcomeOverlay').classList.remove('show');
        const goText = data.game_victory || data.game_over;
        const isVictory = goText.includes('ENDURES') || goText.includes('VICTORY');
        document.getElementById('gameOverText').textContent = goText;
        document.getElementById('gameOverText').style.color = isVictory ? 'var(--lcars-yellow)' : 'var(--lcars-red)';
        document.getElementById('finalStats').innerHTML = `
          TURNS: ${gameState.turn}<br>
          SECTORS EXPLORED: ${gameState.discovered_sectors}<br>
          ALLIES: ${gameState.allies}<br>
          TECHNOLOGIES: ${gameState.technologies_unlocked.length}<br>
          STABILITY: ${gameState.federation_stability}<br>
          PUBLIC TRUST: ${gameState.public_trust}<br>
          CONSTITUTION: ${gameState.constitutional_integrity}<br>
          RIGHTS: ${gameState.rights_protection}
        `;
        document.getElementById('gameOver').classList.add('show');
      }, 1500);
    }

    updateUI(data.new_state);
    fetchConsciousness();
  } catch (e) {
    console.error('Failed to make choice:', e);
  }
}

        async function resetGame() {
            try {
                const resp = await fetch(`${API_URL}/reset`, { method: 'POST' });
                const data = await resp.json();
                updateUI(data.state);
                document.getElementById('gameOver').classList.remove('show');
                document.getElementById('loading').style.display = 'block';
                document.getElementById('eventContent').style.display = 'none';
            } catch (e) {
                console.error('Failed to reset:', e);
            }
        }

function closeOutcome() {
  document.getElementById('outcomeOverlay').classList.remove('show');
  newEvent();
  fetchConsciousness();
  fetchSystemsStatus();
}

// Dismiss tutorial overlay
function dismissTutorial() {
  document.getElementById('tutorialOverlay').classList.remove('show');
  localStorage.setItem('fed_tutorial_shown', 'true');
}

function showTutorial() {
  document.getElementById('tutorialOverlay').classList.add('show');
}

        function explore() {
            newEvent();
        }

        // Fetch and render rival federations
async function fetchRivals() {
  try {
    const resp = await fetch(`${API_URL}/rivals`);
    const data = await resp.json();
    const rivalList = document.getElementById('rivalList');
    const rivalCount = document.getElementById('rivalCount');
    if (!data.system_available || !data.rivals || typeof data.rivals !== 'object') {
      rivalList.innerHTML = '<div style="color: var(--lcars-tan); font-size: 0.85rem;">No rival data</div>';
      return;
    }
    const rivals = data.rivals;
    if (rivals.total_rivals !== undefined) {
      rivalCount.textContent = `${rivals.total_rivals} detected`;
    }
    const rivalEntries = rivals.rivals || rivals;
    const rivalKeys = Object.keys(rivalEntries).filter(k => typeof rivalEntries[k] === 'object' && rivalEntries[k].name);
    rivalList.innerHTML = rivalKeys.map(key => {
      const r = rivalEntries[key];
      const relToPlayer = r.relationships?.player || 'neutral';
      const relClass = relToPlayer === 'hostile' ? 'hostile' : relToPlayer === 'friendly' ? 'friendly' : '';
      return `<div class="rival-card ${relClass}">
        <div class="rival-name">${r.name || key}</div>
        <div class="rival-personality">${r.personality || 'unknown'}</div>
        <div class="rival-stat"><span>Power</span><span>${(r.power * 100).toFixed(0)}%</span></div>
        <div class="rival-stat"><span>Territory</span><span>${r.territory || 0}</span></div>
        <div class="rival-stat"><span>Relations</span><span style="color: ${relToPlayer === 'hostile' ? 'var(--lcars-red)' : relToPlayer === 'friendly' ? 'var(--lcars-blue)' : 'var(--lcars-tan)'}">${relToPlayer.toUpperCase()}</span></div>
      </div>`;
    }).join('');
  } catch (e) {
    console.error('Failed to fetch rivals:', e);
  }
}

// Fetch and render consciousness sheet
async function fetchConsciousness() {
  try {
    const resp = await fetch(`${API_URL}/consciousness`);
    const data = await resp.json();
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
    const tags = document.getElementById('consciousnessTags');
    let html = '';
    (data.dreams || []).forEach(d => {
      html += `<span class="dream-indicator">Dream: ${d}</span> `;
    });
    (data.prophecies || []).forEach(p => {
      html += `<span class="prophecy-indicator">Prophecy: ${p}</span> `;
    });
    (data.traumas || []).forEach(t => {
      html += `<span class="trauma-indicator">Trauma: ${t}</span> `;
    });
    tags.innerHTML = html;
  } catch (e) {
    console.error('Failed to fetch consciousness:', e);
  }
}

// Fetch and render systems status
async function fetchSystemsStatus() {
  try {
    const resp = await fetch(`${API_URL}/systems-overview`);
    const data = await resp.json();
    const bar = document.getElementById('systemsBar');
    const count = document.getElementById('systemsCount');
    const allSystems = { ...data.core_systems, ...data.new_systems };
    let html = '';
    let loaded = 0;
    for (const [name, isLoaded] of Object.entries(allSystems)) {
      html += `<div class="system-dot ${isLoaded ? 'loaded' : 'unloaded'}" title="${name}: ${isLoaded ? 'loaded' : 'not loaded'}"></div>`;
      if (isLoaded) loaded++;
    }
    bar.innerHTML = html;
    count.textContent = `${loaded}/${Object.keys(allSystems).length} loaded`;
  } catch (e) {
    console.error('Failed to fetch systems status:', e);
  }
}

// Initialize
        createStars();
        // Show tutorial overlay on first visit
        if (!localStorage.getItem('fed_tutorial_shown')) {
            document.getElementById('tutorialOverlay').classList.add('show');
        }
fetchState().then(() => {
  setTimeout(newEvent, 1000);
  fetchRivals();
  fetchConsciousness();
  fetchSystemsStatus();
});