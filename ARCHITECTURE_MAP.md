# Federation Game — Full Architecture Map

**VPS:** 187.77.3.56 | **Domain:** federation-game.deliberatefederation.cloud  
**Last mapped:** 2026-05-14

---

## 1. Deployment Stack

| Layer | Tech | Container | Port |
|-------|------|-----------|------|
| Reverse Proxy | Traefik (Let's Encrypt TLS) | federation-game-reverse-proxy-1 | 443/80 |
| Frontend | nginx:alpine (serves static HTML) | federation-game-frontend-1 | 3000 |
| Backend | FastAPI + uvicorn (Python 3.11) | federation-game-backend-1 | 8000 |
| Worker | Python (redis heartbeat, placeholder) | federation-game-worker-1 | — |
| Database | PostgreSQL 15-alpine | federation-game-postgres-1 | 5432 |
| Cache | Redis 7-alpine | federation-game-redis-1 | 6379 |

**Volume mount:** Backend source lives at `/var/lib/docker/volumes/agent-zero-qcyl_agent-zero-data/_data/projects/project_1/federation-game/backend` → mounted read-write at `/app/` inside the backend container.

**Database:** `federation_game` DB exists on postgres container but **has zero tables** — all state is in-memory via Python dataclasses. SQLAlchemy and psycopg2-binary are in requirements.txt but unused.

---

## 2. Backend Architecture (FastAPI)

### 2.1 Core State Object: `GameState` (main.py:76)

All game state lives in a single in-memory `GameState` class instance (`game_state = GameState()`). No persistence to DB.

**Core metrics:**
- `turn`, `credits` (1000), `fuel` (100), `shields` (100), `hull` (100), `crew_morale` (80)
- `federation_stability` (70), `public_trust` (65), `council_support` (55)
- `constitutional_integrity` (80), `rights_protection` (80), `emergency_powers` (0)
- `active_policy`, `proposal_history`, `decision_ledger`, `last_decision`
- `technologies_unlocked`, `current_event`, `log`, `federation_name`

**Subsystem instances (all in-memory):**
- `faction_system: FactionSystem` — 8 factions
- `timeline: TimelineSystem` — 100-year timeline (2387-2487)
- `npc_system: NPCSystem` — 35+ characters, 8+ creatures
- `quest_system: QuestSystem` — full quest library
- `tech_tree: TechTree` — technology tree with eras
- `rival_simulator: RivalFederationSimulator` — AI rival federations
- `consciousness_sheet: ConsciousnessSheet` — quantum consciousness metrics
- `game_state_v2: FederationGameState` — extended state with victory/defeat
- `history_arc: HistoryArcOrchestrator` — century-long narrative arc
- `political_engine: PoliticalEngine` — faction politics simulation
- `console_engine: FederationConsole` — interactive console with commands

**Victory condition:** Reach turn 100 with federation stability ≥ 30.

---

### 2.2 API Endpoints

#### Core Game
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Root health check |
| GET | `/state` | Full game state dump |
| GET | `/atlas` | Star map/atlas data |
| GET | `/engine-status` | All subsystem status |
| GET | `/healthz` | Health check |
| GET | `/event` | Random event card (governance-weighted) |
| POST | `/choose/{choice_id}` | Player makes a choice on current event |
| POST | `/reset` | Reset entire game state |
| GET | `/log` | Event log |
| GET | `/systems-overview` | Aggregated subsystem overview |

#### Factions
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/factions` | List all factions with player reputation |
| POST | `/factions/{faction_id}/join` | Join a faction |

#### NPCs / Companions / Creatures
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/npcs` | List NPCs (filter by archetype/faction) |
| GET | `/npcs/companions/list` | List recruitable companions |
| GET | `/npcs/creatures/list` | List creatures |
| GET | `/npcs/creatures/{creature_id}` | Creature detail |
| GET | `/npcs/encounter` | Spawn random encounter |
| GET | `/npcs/{char_id}` | NPC detail |
| POST | `/npcs/{char_id}/recruit` | Recruit companion (body: RecruitRequest) |
| POST | `/npcs/{char_id}/interact` | Interact with NPC (body: InteractRequest) |
| POST | `/npcs/creatures/{creature_id}/encounter` | Encounter creature (body: EncounterRequest) |
| POST | `/npcs/advance-turn` | Advance NPC turn cycle |

#### Quests
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/quests` | List quests (filter by faction) |
| GET | `/quests/report/summary` | Quest report |
| GET | `/quests/{quest_id}` | Quest detail |
| POST | `/quests/{quest_id}/accept` | Accept quest (body: QuestAcceptRequest) |
| POST | `/quests/{quest_id}/progress` | Progress quest objective (body: QuestProgressRequest) |
| POST | `/quests/{quest_id}/complete` | Complete quest (body: QuestCompleteRequest) |
| POST | `/quests/{quest_id}/abandon` | Abandon quest (body: QuestAbandonRequest) |

#### Technology
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/technology` | List technologies (filter by philosophy) |
| GET | `/technology/tree` | Full tech tree |
| GET | `/technology/report` | Research report |
| GET | `/technology/{tech_id}` | Tech detail |
| GET | `/technology/unlocks/{tech_id}` | What a tech unlocks |
| POST | `/technology/{tech_id}/research` | Start research (body: StartResearchRequest) |
| POST | `/technology/research/advance` | Advance research (body: AdvanceResearchRequest) |

#### Advanced Subsystems
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/rivals` | List rival federations |
| POST | `/rivals/spawn` | Spawn new rival |
| GET | `/consciousness` | Consciousness sheet metrics |
| GET | `/history-arc` | History arc status |
| POST | `/history-arc/advance` | Advance history year |
| GET | `/history-arc/export` | Export history state |
| GET | `/political` | Political engine status |
| POST | `/political/process-turn` | Process political turn |
| GET | `/timeline` | Timeline data |
| GET | `/timeline/narrative` | Narrative arc |
| GET | `/timeline/divergences` | Timeline divergences |

#### Auth
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/login` | Login (hardcoded: player1/password1), returns Bearer token |
| POST | `/state/save` | Save game state (in-memory) |
| POST | `/state/load` | Load game state (in-memory) |

#### WebSocket
| Path | Purpose |
|------|---------|
| `/ws` | Real-time WebSocket (ConnectionManager broadcasts to all connections) |

---

### 2.3 Request/Response Models (Pydantic)

- `RecruitRequest` — player_id
- `InteractRequest` — player_id, dialogue_choice
- `EncounterRequest` — player_id, approach_type
- `QuestAcceptRequest` — player_id
- `QuestProgressRequest` — player_id, objective_id, amount
- `QuestCompleteRequest` — player_id
- `QuestAbandonRequest` — player_id
- `StartResearchRequest` — player_id
- `AdvanceResearchRequest` — player_id, project_id, research_points

---

## 3. Subsystem Deep Dives

### 3.1 NPC System (npcs.py — ~1467 lines, federation_game_npcs.py — ~1544 lines)

**Enums:**
- `PersonalityTrait`: LOYALTY, AMBITION, WISDOM, CHARISMA, CUNNING (0-1 scale)
- `CharacterStatus`: ACTIVE, IMPRISONED, DEAD, TRAVELING, HIDDEN, MISSING, CORRUPTED
- `CharacterArchetype`: HERO, SCHOLAR, ROGUE, WARRIOR, MYSTIC, LEADER
- `CreatureType`: MYTHIC_BEAST, COSMIC_ENTITY, NEBULA_PHENOMENON, ANOMALY, SPIRIT, CRYSTAL_LIFE, STORM_ENTITY, VOID_DWELLER
- `CreatureRarity`: COMMON, UNCOMMON, RARE, LEGENDARY, MYTHIC
- `CompanionBonus`: COMBAT, SCIENCE, DIPLOMACY, STEALTH, MORALE, REPAIR, NAVIGATION, CULTURE

**Classes:**
- `DialogueOption` — text, next_node_id, condition, effect
- `DialogueNode` — dialogue_id, speaker, text, options[]
- `DialogueEngine` — register/get dialogue nodes, process choices, check conditions
- `Character` — id, name, title, archetype, status, personality (dict of traits), faction_id, location, relationships{}, quest_ids[], dialogue_id, backstory, abilities[], level, experience, is_companion
- `Companion(Character)` — bonus_type, bonus_value, loyalty, betrayal_threshold, unique_ability
- `Creature` — id, name, type, rarity, description, habitat, danger_level, tamable, taming_difficulty, abilities[], lore
- `NPCSystem` — manages all characters, companions, creatures; dialogue engine; random encounters; recruiting; relationship tracking; turn advancement

**Pre-built content (factory functions):**
- `build_historical_figures()` — ~15 named characters
- `build_faction_leaders()` — ~15 leaders
- `build_companion_candidates()` — ~20 recruitable companions
- `build_antagonists()` — ~8 villains
- `build_mysterious_figures()` — ~12 enigmatic NPCs
- `build_unique_npcs()` — ~10 special characters
- `build_creatures()` — ~8 creatures (Space Leviathan, Nebula Wraith, etc.)
- `build_npc_system()` — assembles everything into NPCSystem

**Dialogue:** Purely scripted/templated — no LLM API calls. All dialogue is pre-written in DialogueNode trees with condition/effect systems.

---

### 3.2 Faction System (factions.py — ~1524 lines)

**Enums:**
- `IdeologyType`: PROGRESS, SECURITY, FREEDOM, TRADITION, UNITY, DISCOVERY, HARMONY, POWER
- `BonusType`: DIPLOMACY, RESEARCH, COMBAT, STEALTH, MORALE, ECONOMY, CULTURE, EXPLORATION
- `QuestType`: DIPLOMATIC, COMBAT, EXPLORATION, RESEARCH, CULTURAL

**Classes:**
- `FactionPerk` — perk_id, name, description, bonus_type, bonus_value, required_reputation
- `FactionQuest` — quest_id, name, description, difficulty, rewards, required_reputation
- `FactionAchievement` — achievement_id, name, description, condition, unlocked
- `Faction` — id, name, ideology, description, reputation (per player), perks[], quests[], achievements[], history, is_joinable, is_secret
- `FactionSystem` — manages all factions; join/leave; reputation tracking; perk/quest/achievement unlocks

**8 Factions:**
1. `Diplomatic Corps` (DIPLOMACY) — Progress ideology
2. `Military Command` (COMBAT) — Security ideology
3. `Cultural Ministry` (CULTURE) — Freedom ideology
4. `Research Division` (RESEARCH) — Discovery ideology
5. `Consciousness Collective` (MORALE) — Unity ideology
6. `Economic Council` (ECONOMY) — Power ideology
7. `Exploration Initiative` (EXPLORATION) — Discovery ideology
8. `Preservation Society` (STEALTH) — Tradition ideology

---

### 3.3 Quest System (quests.py — ~580 lines)

**Enums:**
- `QuestDifficulty`: EASY, MODERATE, HARD, LEGENDARY
- `ObjectiveType`: EXPLORE, DEFEAT, NEGOTIATE, RESEARCH, BUILD, PROTECT, DELIVER, DISCOVER, SURVIVE, INFLUENCE
- `QuestStatus`: AVAILABLE, ACTIVE, COMPLETED, FAILED, ABANDONED
- `FactionAffiliation`: NONE, DIPLOMATIC, MILITARY, CULTURAL, RESEARCH

**Classes:**
- `QuestReward` — credits, reputation, items, unlock_ids, experience
- `QuestObjective` — objective_id, type, description, required, current, optional, bonus_multiplier
- `Quest` — id, title, description, faction, difficulty, status, objectives[], rewards, prerequisites, turn_accepted, turn_limit
- `QuestSystem` — register/accept/progress/complete/abandon quests; objective tracking by type; quest sync report; quest library creation

---

### 3.4 Technology Tree (technology.py — ~527 lines)

**Enums:**
- `Era`: EARLY_EXPLORATION, CONSOLIDATION, EXPANSION, CRISES_AND_CONFLICTS, MATURITY, TRANSCENDENCE
- `ResearchPhilosophy`: SCIENTIFIC, INTUITIVE, COLLABORATIVE, CONTROVERSIAL

**Classes:**
- `TechBonus` — metric, value, description
- `Technology` — id, name, era, philosophy, description, prerequisites[], bonuses[], unlocks[], cost, research_time, is_breakthrough
- `ResearchProject` — id, tech_id, player_id, progress, total, start_turn, status (ACTIVE/PAUSED/COMPLETE)
- `TechTree` — register technologies; availability checks; start/advance/complete research; tech-by-era/philosophy; research tree/report; unlock chains

---

### 3.5 Timeline System (timeline.py + federation_game_timeline.py — ~1700 lines)

**Legacy (timeline.py):** Simple `TimelineSystem` with `Era` enum and `DecadeGate` dataclass.

**Full (federation_game_timeline.py):**
- `TimelineEra`: GENESIS, EXPLORATION, CONSOLIDATION, EXPANSION, CONFLICT, MATURITY, TRANSCENDENCE
- `FactionSnapshot` — power, reputation, stability per faction per year
- `TimelineEvent` — year, era, title, description, factions_affected, effects, significance
- `HistoricalMemory` — event_id, emotional_weight, faction_interpretations, decay_rate, current_salience
- `NarrativeMemoryTracker` — memory decay, faction perspectives, generational narratives
- `TimelineEngine` — advance years; generate timeline events; faction drift; reputation drift; ideology drift; era summaries; seed events; import/export

---

### 3.6 Event System (federation_game_events.py — ~798 lines)

**Enums:**
- `EventType`: DIPLOMATIC_CRISIS, DREAM_DESTABILIZATION, RIVAL_MOVE, PROPHECY, RESOURCE, CULTURAL_SHIFT, PARADOX, FIRST_CONTACT
- `EventSeverity`: LOW, MEDIUM, HIGH, CRITICAL
- `EffectType`: METRIC_CHANGE, REPUTATION_CHANGE, QUEST_UNLOCK, TECH_UNLOCK, NPC_SPAWN, FACTION_SHIFT

**Classes:**
- `GameEffect` — type, target, value, duration, description
- `GameChoice` — choice_id, text, effects[], requirements, ideology_bias
- `GameEvent` — id, type, severity, title, description, choices[], expiry_turn, metadata
- `EventGenerator` — generates events by type (diplomatic crisis, dream destabilization, rival move, prophecy, resource, cultural shift, paradox, first contact)
- `EventSystem` — register subsystem callbacks; generate/resolve events; choice impacts; event chains; event log/statistics; export

---

### 3.7 Rival Federation Simulator (federation_game_rival_simulator.py — ~2133 lines)

**Enums:**
- `RivalPersonality`: AGGRESSIVE, DIPLOMATIC, ISOLATIONIST, EXPANSIONIST, SCIENTIFIC, MYSTICAL, PRAGMATIC, CHAOTIC
- `RivalAction`: ATTACK, DIPLOMACY, ESPIONAGE, RESEARCH, EXPAND, PROPAGANDA, ALLIANCE, SABOTAGE
- `ThreatLevel`: MINIMAL, LOW, MODERATE, HIGH, CRITICAL, EXISTENTIAL

**Classes:**
- `RivalFederation` — name, personality, power, technology, military, economy, diplomacy, territory, relationships
- `RivalActionRecord` — year, action, target, success, narrative
- `RivalSimulationState` — full simulation state tracking
- `RivalFederationSimulator` — initialize rivals; AI action selection; target selection; power cost; success resolution; narrative generation; impact calculation; alliance dynamics; threat assessment; encounter resolution; import/export

---

### 3.8 Consciousness Sheet (federation_game_console.py — ~1923 lines)

**Classes:**
- `ConsciousnessSheet` — awareness, stability, coherence, awakeness, memories_recorded, complexity (all float 0-100 with clamping); health/stability/coherence/awakeness/complexity computed properties
- `RivalFederation` (simplified) — name, philosophy, diplomatic_style
- `EventCard` — id, type, title, description, choices, resolve()
- `EventRegistry` — ~653 lines of event library initialization
- `NarrativeGenerator` — static narrative templates (no LLM)
- `ChaosMode` — generates chaos events/narratives
- `TurnCycle` — phase management (event, player_action, resolution, advancement)
- `PersistenceManager` — save/load game to filesystem (JSON)
- `FederationConsole` — full interactive console with 20+ commands (status, turn, event, rivals, chaos, dream, prophecy, consciousness, save, load, factions, npcs, quests, tech, history, choose, reset, bridge, politics)

---

### 3.9 Quantum Consciousness Engine (federation_game_quantum_consciousness.py — ~1283 lines)

**Enums:**
- `QuantumState`: SUPERPOSITION, COLLAPSED, ENTANGLED, DECOHERENT
- `ObserverRole`: LEADER, HISTORIAN, CITIZEN, RIVAL, MYSTIC, SCIENTIST
- `IdeologyType`: PROGRESS, SECURITY, FREEDOM, TRADITION, UNITY, DISCOVERY
- `NarrativePattern`: RISE_AND_FALL, CYCLE, LINEAR_PROGRESS, DIVERGENCE, CONVERGENCE, CHAOS

**Classes:**
- `NarrativeInterpretation` — observer_role, ideology, interpretation, emotional_resonance, confidence, timestamp
- `ConsciousnessWave` — amplitude, frequency, phase, era, description
- `QuantumNarrative` — event_id, interpretations[], state (quantum), coherence, entangled_events[]
- `LostPossibility` — event_id, branch_description, weight, emotional_impact
- `EventEntanglement` — event_pair, entanglement_strength, drift_direction
- `ObserverProfile` — role, ideology, trust, bias, interpretation_style
- `FactionInterpretationEngine` — generates faction-specific interpretations of events
- `QuantumConsciousnessEngine` — observer registration; event interpretation; consciousness wave generation; superposition collapse; event entanglement; coherence measurement; meta-narrative generation; pattern detection; lost possibilities; faction narrative arcs

---

### 3.10 History Arc Orchestrator (federation_game_history_arc.py — ~1321 lines)

**Classes:**
- `HistoryArcReport` — year, era, events, consciousness_waves, faction_states, divergences, branch_points
- `HistoryArcOrchestrator` — initialize with all subsystems; advance years; run simulations; resolve branch points; emotional valence; ideological polarity; proximity; clarity; event category inference; era consciousness waves; state sync with game; export/import

---

### 3.11 Game State V2 (federation_game_state.py — ~744 lines)

**Enums:**
- `GamePhase`: EXPLORATION, CONSOLIDATION, EXPANSION, CRISIS, MATURITY, TRANSCENDENCE
- `VictoryType`: CONSCIOUSNESS_ASCENSION, DIPLOMATIC_UNITY, SCIENTIFIC_TRANSCENDENCE, CULTURAL_RENAISSANCE, MILITARY_DOMINANCE

**Classes:**
- `FederationCoreState` — stability, public_trust, council_support, constitutional_integrity, rights_protection, emergency_powers
- `SubsystemState` — quest_system, faction_system, technology_tree, npc_system, event_registry, consciousness_metrics, turn_progression, persistence (each with loaded/active metrics)
- `GameStatistics` — total_turns, events_resolved, quests_completed, techs_researched, rivals_encountered, companions_recruited, creatures_discovered, decisions_made, policies_enacted, rights_protected, rights_violated, consciousness_peak, stability_avg, trust_avg
- `ActionRecord` — turn, action_type, description, outcome, metrics_before, metrics_after, timestamp
- `GameState` — full state management; advance_turn; record_action; victory/defeat conditions; game summary/statistics; save/load (JSON); state validation; serialization/deserialization; state hashing

---

### 3.12 Turn System (federation_game_turns.py — ~603 lines)

**Turn phases (per advance):**
1. Dream Generation
2. Rival Actions
3. Diplomacy Shifts
4. Prophecy Updates
5. Consciousness Evolution
6. Random Events
7. Status Updates

**Computed metrics:** stability, morale, growth, consciousness, resources

**Features:** undo_turn, pause/resume, auto_mode, export_state, attach_dream/rival/diplomacy/consciousness/culture engines

---

### 3.13 Political Engine (federation_game_political_integration.py — ~5.1KB)

**Self-contained political simulation** — no separate political_system.py file exists.

Wires factions to game state for political turn processing. Provides:
- Faction power dynamics during political turns
- Ideology drift calculations
- Coalition/alliance formation logic
- Political pressure on game state metrics
- Integration hooks for HistoryArcOrchestrator

**Note:** All 4 integration adapters (NPC, Quest, Political, Technology) are opt-in/disabled by default. The `HistoryArcOrchestrator` must explicitly enable them to activate cross-subsystem effects.

---

## 4. Frontend Architecture

### 4.1 Main UI (index.html — 54KB, single file)

**Theme:** Star Trek LCARS (orange/tan/dark color scheme)

**Layout:** CSS Grid — 280px left panel | flexible center | 300px right panel

**Tab Navigation:** Multiple tabs for different subsystems

**JavaScript Functions:**
| Function | API Call | Purpose |
|----------|----------|---------|
| `fetchState()` | GET `/state` | Load full game state, update all UI panels |
| `newEvent()` | GET `/event` | Pull random event card |
| `makeChoice(id)` | POST `/choose/{id}` | Submit player choice, show outcome (deltas, explainability, rival effects, political effects, history arc) |
| `resetGame()` | POST `/reset` | Full game reset |
| `fetchRivals()` | GET `/rivals` | Render rival federation cards |
| `fetchConsciousness()` | GET `/consciousness` | Render consciousness sheet metrics |
| `fetchSystemsStatus()` | GET `/engine-status` | Render subsystem status dashboard |
| `explore()` | — | Trigger exploration action |
| `updateUI(state)` | — | Master UI renderer (stardate, metrics, policy log, tech list, etc.) |
| `loadEvent(event)` | — | Render event card with choices, rights_at_stake |
| `formatDeltas()` | — | Format metric changes with +/- signs |
| `formatExplainability()` | — | Format AI explainability data |
| `createStars()` | — | Background star animation |

**WebSocket:** Connected to `/ws` for real-time updates (broadcasts from ConnectionManager)

**Features:** Tutorial overlay, outcome modal with victory/defeat detection, rights tracking, governance events

### 4.2 Adult UI (adult.html — 57KB)

**Theme:** Dark "Federation Control Plane" — landing-strip nav tabs, amber/violet/red color coding

**Layout:** Tab-based with landing-strip navigation

**JavaScript Architecture (lines 921–1600+):**
- `API_URL = '/api'` — all calls go through Traefik proxy
- `METRIC_LABELS` — display names for 12 core metrics
- `GOVERNANCE_FIELDS` / `SHIP_FIELDS` — arrays grouping metrics into governance vs ship categories
- `state` / `currentEvent` — module-level state vars

**Core Functions:**
| Function | API Call | Purpose |
|----------|----------|---------|
| `fetchState()` | GET `/state` | Load state, call `updateState()` |
| `updateState()` | — | Refresh all metric displays using `renderMetric()` |
| `loadEvent()` | GET `/event` | Pull event, call `updateEvent()` |
| `updateEvent()` | — | Render event card: title, description, domain, rights_at_stake, risk level + choice buttons |
| `choose(id)` | POST `/choose/{id}` | Submit choice → `updateState()` + process new event + check victory |
| `resetGame()` | POST `/reset` | Full reset |
| `fetchRivals()` | GET `/rivals` | Render rival grid (name, personality, power%, territory, relationship) |
| `fetchConsciousness()` | GET `/consciousness` | Render consciousness metrics |
| `listPreview()` | — | Preview list renderer |
| `renderAtlas()` | — | 4 atlas sections: NPC System / Creature Codex / Tech Tree / USS Chaosbringer |
| `fillClass(val)` | — | CSS class mapping: emergency_powers→'power', ≥70→'good', ≥40→'warn', else→'bad' |
| `renderMetric()` | — | Individual metric renderer with color coding |

**Color-coded choice buttons:** empty (neutral), amber (caution), violet (rights-restricting), red (dangerous)

**Victory banner:** Displayed when win condition met

### 4.3 Modular Game Frontend (public_html/game/ — 15+ ES module files)

**Separate codebase** from the Docker-served frontend. Lives at `/var/lib/docker/volumes/agent-zero-qcyl_agent-zero-data/_data/projects/project_1/public_html/game/`

**Architecture:** ES module system with `ParallelFXEngine` as central FX/animation/data hub

**Module Map:**
| Module | Purpose |
|--------|---------|
| `game.js` | Main bootstrap — imports all systems, initializes game |
| `GameLoop.js` | Core tick loop (requestAnimationFrame) |
| `GameState.js` | Default state factory (initial values for all game vars) |
| `AgentSystem.js` | 5 agents with unlock conditions, passive/active abilities, zone affinity, cooldowns; ParallelFXEngine integrated |
| `UISystem.js` | Full UI rendering (~12KB) |
| `EventSystem.js` | Weighted rarity event pool (common→mythic) with zone modifiers |
| `ResourceSystem.js` | Passive energy/shard generation with zone modifiers |
| `ZoneSystem.js` | Zone progression and unlocking |
| `ProgressionSystem.js` | Level and milestone tracking |
| `PersistenceSystem.js` | localStorage save/load with versioning, migration, validation |
| `PlayerActions.js` | Player action handlers |
| `AnomalySystem.js` | Boss events (Void Tyrant, Prism Singularity) |
| `AudioSystem.js` | WebAudio ambient + SFX synthesis |
| `MetaProgressionSystem.js` | Cross-run meta upgrades (persists across resets) |
| `PrestigeSystem.js` | Prestige/reset mechanic |
| `parallelFXEngine.js` | Central FX/animation/data engine — shared across AgentSystem and other modules |
| `api.js` | Client wrapper for backend API: login, saveState, loadState, getEvent, getRival, getFactions (Bearer token auth to `/api/`) |

**Game Data JSON (public_html/game/data/):**
| File | Content |
|------|---------|
| `agents.json` | 5 agent definitions with stats, abilities, unlock conditions |
| `zones.json` | Zone definitions with resource/event modifiers |
| `progression.json` | Progression rules and milestones |
| `events.json` | Event pool definitions |
| `creatures.json` | Creature definitions |
| `rivals.json` | Rival federation data |
| `upgrades.json` | Upgrade definitions |

**Key difference from Docker frontend:** Uses localStorage persistence (PersistenceSystem) and has a proper game loop with delta-time tick. Also has WebAudio synthesis and meta-progression across runs.

### 4.4 Other UIs

- `earth.html` (1.4KB) — Earth page (minimal)

---

## 5. Database Schema

**Current state: EMPTY.** PostgreSQL is running but has zero tables. All game state is held in Python memory (dataclasses). SQLAlchemy and psycopg2-binary are installed but not used.

**Redis:** Configured but worker.py is a placeholder (heartbeat only). No actual Redis usage in game logic.

---

## 6. LLM / AI Integration

**No LLM API keys found anywhere.** Searched all backend .py files, .env files, and container environment.

**All dialogue and narrative is template-based:**
- NPC dialogue uses pre-written `DialogueNode` trees with conditions/effects
- Narratives use string templates in `NarrativeGenerator`, `ChaosMode`, `RivalFederationSimulator`
- Event descriptions are hardcoded in `EventRegistry` (~653 lines of event library)
- Faction interpretations use template strings in `FactionInterpretationEngine`

**No external AI API calls exist in the codebase.** All "intelligence" is procedural — weighted random selection, personality-driven action weights, scripted narrative templates.

---

## 7. Authentication

**In-memory only.** Single hardcoded user:
```
USERS = {"player1": "password1"}
```
Returns a simple Bearer token. No database-backed auth. Save/load is also in-memory (no persistence).

---

## 8. Key Architectural Observations

1. **Everything is in-memory** — zero DB persistence. Game resets on backend restart.
2. **Dual module system** — legacy modules (npcs.py, factions.py, quests.py, technology.py, timeline.py) and "federation_game_*" versions coexist. The newer versions are more sophisticated but both are loaded.
3. **Massive single-file modules** — main.py is 131KB/2677 lines, console.py is 88KB/1923 lines, rival_simulator is 98KB/2133 lines
4. **No LLM integration** — all narrative/dialogue is scripted. The consciousness simulation is entirely procedural.
5. **No real auth or persistence** — placeholder systems only
6. **Worker is a no-op** — just a heartbeat loop
7. **Redis is unused** — configured but no game logic uses it
8. **The game is fully playable** via the API — event → choice → outcome loop works
9. **WebSocket exists** but broadcasts are limited (ConnectionManager with basic connect/disconnect/broadcast)
10. **Governance/explainability system** — every choice produces deltas, explainability data, rights impact, rival effects, political effects, and history arc data

---

## 9. File Size Reference

| File | Size | Lines |
|------|------|-------|
| main.py | 131KB | ~2677 |
| federation_game_rival_simulator.py | 98KB | ~2133 |
| federation_game_console.py | 88KB | ~1923 |
| federation_game_timeline.py | 83KB | ~1700+ |
| technology.py | 67KB | ~527+ |
| federation_game_quantum_consciousness.py | 61KB | ~1283 |
| factions.py | 60KB | ~1524 |
| federation_game_history_arc.py | 59KB | ~1321 |
| federation_game_npcs.py | 60KB | ~1544 |
| npcs.py | 59KB | ~1467 |
| federation_game_state.py | 30KB | ~744 |
| federation_game_events.py | 35KB | ~798 |
| federation_game_turns.py | 27KB | ~603 |
| quests.py | 41KB | ~580+ |
| index.html | 54KB | — |
| adult.html | 57KB | ~1600+ |

---

## 10. Critical Context & Open Issues

### Two Frontend Codebases
1. **Docker-served** (`frontend/`): Single-file HTML apps (index.html LCARS UI, adult.html Control Plane UI) — served via nginx container on port 3000
2. **Modular ES** (`public_html/game/`): 15+ module game engine with localStorage persistence, WebAudio, meta-progression — separate codebase

### Persistence Gap
- PostgreSQL is running but **has zero tables** — SQLAlchemy/psycopg2 installed but unused
- No Alembic migrations exist
- All game state is in-memory Python dataclasses — **resets on backend restart**
- The `public_html/game/` frontend has its own localStorage persistence (PersistenceSystem) — this is the only persistence that actually works
- `FederationConsole` has a `PersistenceManager` that saves to filesystem JSON — but this is console-only, not wired to API

### Auth Gap
- Single hardcoded user: `player1/password1`
- No database-backed auth
- Save/load endpoints exist but operate on in-memory state only

### LLM Gap
- No API keys for any LLM service (OpenAI, Anthropic, etc.)
- All NPC dialogue is pre-scripted DialogueNode trees
- All narratives are string templates
- The "consciousness simulation" is entirely procedural (weighted randoms, personality matrices)
- To add LLM-generated dialogue, would need: API key injection, dialogue generation service, prompt templates, and integration into NPCSystem/DialogueEngine

### Infrastructure
- Docker-compose mounts backend as read-only (`:ro`) into container — code changes require volume remount or container rebuild
- Redis configured but unused — worker.py is placeholder
- WebSocket is minimal (basic ConnectionManager, no room/channel system)
- Production domain: federation-game.deliberatefederation.cloud via Traefik + Let's Encrypt TLS

### Recommended Next Steps (Priority Order)
1. **Add DB persistence** — create SQLAlchemy models matching GameState, run Alembic migrations, wire save/load to actual DB
2. **Add LLM dialogue** — inject API key, create dialogue generation service, integrate with NPCSystem
3. **Consolidate frontends** — merge best of both codebases (LCARS theme + modular ES architecture + localStorage backup)
4. **Real auth** — database-backed user system with proper token management
5. **Wire Redis** — use for session caching, event queues, and WebSocket state
6. **Modularize main.py** — 131KB monolith should be split into route modules
