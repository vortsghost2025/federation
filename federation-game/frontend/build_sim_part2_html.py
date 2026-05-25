"""Part 2: HTML body string for simulation.html builder."""

HTML_BODY = r"""
<div class="starfield" id="starfield"></div>
<div id="app">
<header id="top">
<div class="top-row">
<span class="top-row-label">Degradation vs Runway</span>
<div class="split-bar-container">
<div class="split-bar-left degradation-fill" id="deg-fill" style="width:0"></div>
<div class="split-bar-right runway-fill" id="runway-fill" style="width:100%"></div>
</div>
<div class="split-metric-chips">
<span class="split-chip degradation" id="chip-morale">M &#8212;</span>
<span class="split-chip degradation" id="chip-stability">S &#8212;</span>
<span class="split-chip degradation" id="chip-anomaly">A &#8212;</span>
</div>
<span class="split-severity nominal" id="deg-sev">NOMINAL</span>
<div class="top-tick-display">
<span class="top-tick-label">Tick</span>
<span class="top-tick-val" id="tick-count">&#8212;</span>
</div>
<div class="time-since">
<span class="time-since-label">Last Tick</span>
<span class="time-since-val" id="time-since">&#8212;</span>
</div>
</div>
<div class="top-row">
<span class="top-row-label">Threat vs Buffer</span>
<div class="split-bar-container">
<div class="split-bar-left threat-fill" id="threat-fill" style="width:0"></div>
<div class="split-bar-right buffer-fill" id="buffer-fill" style="width:100%"></div>
</div>
<div class="split-metric-chips">
<span class="split-chip threat" id="chip-threat">T &#8212;</span>
<span class="split-chip threat" id="chip-tension">X &#8212;</span>
<span class="split-chip buffer" id="chip-resources">R &#8212;</span>
</div>
<span class="split-severity nominal" id="threat-sev">NOMINAL</span>
<nav class="top-nav" aria-label="Main navigation">
<a href="bridge.html">Bridge</a>
<a href="starmap.html">Starmap</a>
<a href="/">Simulator</a>
<a href="simulation.html" class="active">Live Sim</a>
<a href="adult.html">Control</a>
<a href="worldguide.html">World Guide</a>
<a href="earth.html">Earth</a>
<button class="help-btn" onclick="toggleHelp()" aria-label="How to read this page" title="How to read this page">?</button>
</nav>
</div>
</header>

<!-- SITUATION SUMMARY BAR -->
<div id="situation">
<div class="sit-card" id="sit-current">
<div class="sit-card-label">Current Situation</div>
<div class="sit-card-value" id="sit-current-text">Loading world state...</div>
</div>
<div class="sit-card sit-risk" id="sit-risk">
<div class="sit-card-label">Main Risk</div>
<div class="sit-card-value" id="sit-risk-text">&#8212;</div>
</div>
<div class="sit-card sit-watch" id="sit-watch" style="flex:2.5">
<div class="sit-card-label">Watchlist <span style="font-weight:400;font-size:10px;letter-spacing:0.5px;color:var(--dim)">(click to highlight)</span></div>
<div class="watchlist" id="watchlist-cards">
<div class="sit-card-value" id="sit-watch-text">&#8212;</div>
</div>
</div>
</div>

<!-- HELP OVERLAY -->
<div class="help-overlay" id="help-overlay" role="dialog" aria-label="How to read this page">
<div class="help-box">
<button class="help-close" onclick="toggleHelp()">&#10005; Close</button>
<h2>How to Read This Page</h2>
<h3>What Is This?</h3>
<div class="help-section">
<p>This is a <strong>living simulation</strong> &#8212; 39 AI-controlled characters (NPCs) organized into 8 factions are running autonomously right now. No player is controlling them. They think, decide, act, and react to each other every few seconds (each cycle is called a <strong>tick</strong>).</p>
<p>Your job as a viewer is to <strong>watch civilization emerge</strong>. Factions form alliances, declare rivalries, research technology, pass laws, and respond to world events &#8212; all without human input.</p>
</div>
<h3>Top Banner &#8212; Is The World Healthy?</h3>
<div class="help-section">
<p>Two split-bars show system health at a glance:</p>
<ul>
<li><strong>Degradation vs Runway</strong> &#8212; Red side = how bad things are (low Morale, low Stability, high Anomaly). Green side = how much buffer remains. When red dominates, the system is in trouble.</li>
<li><strong>Threat vs Buffer</strong> &#8212; Red side = external danger (Threat, Tension). Blue side = resources available to absorb it. When red dominates, the federation is under pressure.</li>
</ul>
<p>Each bar has <strong>metric chips</strong> (M=Morale, S=Stability, A=Anomaly, T=Threat, X=Tension, R=Resources) and a <strong>severity badge</strong> (NOMINAL / ELEVATED / HIGH / SEVERE / CRITICAL).</p>
</div>
<h3>Cascade Pipeline &#8212; What Just Happened?</h3>
<div class="help-section">
<p>When one event triggers reactions in multiple NPCs, the <strong>cascade pipeline</strong> shows the domino chain:</p>
<ul>
<li><strong style="color:#F44336">Root Trigger</strong> &#8212; The original event, highlighted in red with a pulse.</li>
<li><strong style="color:#CE93D8">Depth Badges</strong> &#8212; D1, D2, D3... show how far the reaction spread.</li>
<li><strong>Tone Tags</strong> &#8212; fear, conflict, caution, support, celebration show the emotional color.</li>
</ul>
</div>
<h3>NPC Cards &#8212; Who Is Affected?</h3>
<div class="help-section">
<p>NPC card borders light up based on cascade involvement:</p>
<ul>
<li><span class="color-swatch" style="background:#F44336"></span><strong>Red border + pulse</strong> = TRIGGER (started the chain)</li>
<li><span class="color-swatch" style="background:#CE93D8"></span><strong>Violet border</strong> = REACTOR (directly reacted)</li>
<li><span class="color-swatch" style="background:#FF9800"></span><strong>Amber border</strong> = AFFECTED (impacted indirectly)</li>
</ul>
<p>Use the <strong>FILTER ON/OFF</strong> toggle to hide idle NPCs and focus on active participants.</p>
</div>
<h3>Left Panel &#8212; Who Has Power?</h3>
<div class="help-section">
<p>Each card is one of the 8 factions. Key info:</p>
<ul>
<li><strong>Power number</strong> &#8212; How strong the faction is overall.</li>
<li><strong>Cohesion bar</strong> &#8212; How united the faction&#39;s members are. Green = united, Red = fractured.</li>
<li><strong>Colored dots</strong> &#8212; Stance toward each other faction: <span class="color-swatch" style="background:#4CAF50"></span>Ally, <span class="color-swatch" style="background:#FFC107"></span>Neutral, <span class="color-swatch" style="background:#F44336"></span>Enemy</li>
</ul>
<p><strong>Click a faction card</strong> to expand details. <strong>Faction Tech tab</strong> shows research progress.</p>
</div>
<h3>Bottom Bar &#8212; What Is Unresolved?</h3>
<div class="help-section">
<p>Era progress and pending items &#8212; how much backlog pressure the simulation has.</p>
</div>
<h3>What to Watch For</h3>
<div class="help-section">
<ul>
<li><strong>CRITICAL or SEVERE severity labels</strong> = Something needs attention now.</li>
<li><strong>Red dominating the split bars</strong> = System is degrading fast.</li>
<li><strong>Pulsing root trigger in pipeline</strong> = A cascade chain is active.</li>
<li><strong>Faction cohesion dropping</strong> = Members turning on each other.</li>
</ul>
</div>
</div>
</div>

<section id="left" class="panel">
<div class="intro-box">
<strong>Federation Simulation</strong> &#8212; 39 autonomous NPCs across 8 factions evolve without player input. Click any card to expand details.
<div class="intro-legend">
<div class="legend-item"><div class="legend-dot" style="background:var(--green)"></div> Ally</div>
<div class="legend-item"><div class="legend-dot" style="background:#FFC107"></div> Neutral</div>
<div class="legend-item"><div class="legend-dot" style="background:var(--red)"></div> Enemy</div>
</div>
</div>
<div class="tab-bar" id="left-tabs" role="tablist">
<button class="tab-btn active-amber" data-tab="factions" role="tab" onclick="switchLeftTab('factions')">Factions</button>
<button class="tab-btn" data-tab="faction-tech" role="tab" onclick="switchLeftTab('faction-tech')">Faction Tech</button>
</div>
<div class="tab-content visible" id="left-factions">
<div class="section-title amber">Who Has Power?</div>
<div id="faction-list"></div>
</div>
<div class="tab-content" id="left-faction-tech">
<div class="section-title amber">Faction Tech Research</div>
<div id="tech-list"></div>
</div>
</section>

<section id="center" class="panel">
<div class="section-title cyan">What Just Happened?</div>
<div id="cascade-pipeline"></div>
<div id="event-chains"></div>
<div class="raw-toggle" id="raw-toggle" onclick="toggleRaw()" tabindex="0" role="button" aria-expanded="false">Raw Events</div>
<div class="raw-events-wrap" id="raw-wrap">
<div class="event-feed" id="event-feed"></div>
</div>
<div class="signal-lost" id="signal-lost-center">
<span class="signal-lost-text">SIGNAL LOST</span>
</div>
</section>

<section id="right" class="panel">
<div class="tab-bar" id="right-tabs" role="tablist">
<button class="tab-btn active-violet" data-tab="npcs" role="tab" onclick="switchRightTab('npcs')">NPCs</button>
<button class="tab-btn" data-tab="npc-quests" role="tab" onclick="switchRightTab('npc-quests')">NPC Quests</button>
<button class="tab-btn" data-tab="choices" role="tab" onclick="switchRightTab('choices')">Choices</button>
</div>
<div class="tab-content visible" id="right-npcs">
<div class="section-title violet">NPC Activity <span id="npc-count" style="font-size:13px;color:var(--dim);font-weight:400"></span></div>
<div class="npc-noise-toggle" id="npc-noise-toggle" onclick="toggleNpcFilter()" tabindex="0" role="button" aria-pressed="false">
<span class="npc-noise-toggle-label">FILTER OFF</span>
<span class="npc-noise-toggle-count" id="npc-active-count"></span>
</div>
<div class="npc-grid" id="npc-grid"></div>
</div>
<div class="tab-content" id="right-npc-quests">
<div class="section-title violet">What Are Agents Trying To Do?</div>
<div class="quest-health" id="quest-health">
<div class="sit-card-label">Quest Health</div>
<div class="qh-grid" id="qh-grid"></div>
<div class="qh-type-list" id="qh-types"></div>
</div>
<div id="quest-detail-area"></div>
<div class="quest-log" id="quest-log"></div>
</div>
<div class="tab-content" id="right-choices">
<div class="section-title violet">Choice Resolutions</div>
<div id="faction-choice-detail-area"></div>
<div class="choice-list" id="choice-list"></div>
</div>
</section>

<footer id="bottom">
<div class="bottom-era" id="era-name">&#8212;</div>
<div class="bottom-progress">
<span class="bottom-progress-label">Next Era</span>
<div class="bottom-progress-bar"><div class="bottom-progress-fill" id="era-fill" style="width:0"></div></div>
<span class="bottom-progress-pct" id="era-pct">0%</span>
</div>
<div class="bottom-triggers" id="era-triggers"></div>
<div class="bottom-pending" id="pending-items">What Is Unresolved: <strong>&#8212;</strong></div>
</footer>
</div>
"""
