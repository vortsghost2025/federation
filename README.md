# Federation

**A Star Trek consciousness simulation — not a game.**

A persistent, turn-based federation management simulation with a full LCARS web interface, 12 interconnected subsystems, and 48+ API endpoints. Built as a single-page Star Trek experience with real-time WebSocket updates, rival AI federations, and a century-long narrative arc.

---

## Two Game Surfaces

### 1. Starship Simulator (`index.html` — 1453 LOC)
The kid-friendly LCARS interface. Big colorful buttons, immediate feedback, one-tap actions. Designed for a 5-year-old 3000km away.

- LCARS-styled top bar and bottom navigation
- Event card system with narrative choices and color-coded outcome deltas
- Bottom-bar buttons: EXPLORE, FACTIONS, SHIP, QUESTS, TECH
- Card-based outcome overlay showing stat changes (green positive, red negative)
- Tutorial overlay for first-time players
- WebSocket connection for real-time state updates

### 2. Adult Control Plane (`adult.html` — 1505 LOC)
The full-depth strategic interface. Faction politics, technology trees, NPC relationships, quest management, and the decision ledger — all visible simultaneously.

- Landing strip tab navigation (Overview, Factions, NPCs, Quests, Tech, History, Systems)
- Faction reputation bars and join/leave controls
- NPC companion recruitment and creature encounters
- Technology tree with era-based progression
- History arc orchestrator (100-year timeline 2387–2487)
- Consciousness sheet metrics panel
- Political engine turn processing

---

## Architecture

```
Browser ──► nginx (frontend) ──► FastAPI backend ──► Game Engine Modules
   │              │                     │                   │
   │          static HTML           48+ routes        9 Python modules
   │          + /api/ proxy       + WebSocket          ~9,600 LOC
   │                              + Pydantic models
   │
   └── WebSocket ◄── real-time broadcasts ──┘
```

### Backend Stack
| Layer | Technology |
|-------|-----------|
| API Server | FastAPI + Uvicorn (Python 3.11) |
| Real-time | WebSocket (ConnectionManager broadcasts) |
| Database | PostgreSQL 15-alpine (available, currently in-memory state) |
| Cache | Redis 7-alpine |
| Reverse Proxy | Traefik with Let's Encrypt TLS |
| Frontend | nginx:alpine serving static HTML |

### VPS Deployment (7 Containers)
```
federation-game-reverse-proxy-1   Traefik    443/80
federation-game-frontend-1        nginx      3000
federation-game-backend-1         FastAPI    8000
federation-game-worker-1          Python     —
federation-game-postgres-1        PostgreSQL 5432
federation-game-redis-1           Redis      6379
```

Live at **[federation-game.deliberatefederation.cloud](https://federation-game.deliberatefederation.cloud)**

---

## Game Engine Modules (~9,600 LOC)

All game logic lives in the repo root as Python modules. These are bind-mounted read-only into the backend Docker container:

| Module | LOC | Purpose |
|--------|-----|---------|
| `federation_game_console.py` | 1,430 | 12-block architecture: core orchestration, REPL, chaos mode |
| `federation_game_technology.py` | 1,709 | Technology tree with eras, research, unlocks |
| `federation_game_factions.py` | 1,602 | 8 factions, ideology system, reputation, perks, achievements |
| `federation_game_npcs.py` | 1,633 | 35+ characters, 8+ creatures, dialogue engine, companions |
| `federation_game_quests.py` | 1,063 | Branching quest system with objectives and rewards |
| `federation_game_events.py` | 833 | Event card generation with governance-weighted choices |
| `federation_game_state.py` | 679 | Game state model, victory/defeat conditions |
| `federation_game_turns.py` | 638 | Turn cycle management, phase progression |

---

## 12 Subsystems

The backend instantiates these interconnected subsystems in a single `GameState` object:

1. **FactionSystem** — 8 factions with ideologies, reputation, perks, quests, achievements
2. **TimelineSystem** — 100-year timeline (2387–2487) with narrative arcs
3. **NPCSystem** — 35+ named characters, 8+ creatures, dialogue trees, companions
4. **QuestSystem** — Full quest library with branching objectives
5. **TechTree** — Era-based technology progression with research projects
6. **RivalFederationSimulator** — AI rival federations with their own behavior
7. **ConsciousnessSheet** — Quantum consciousness metrics tracking
8. **FederationGameState** — Extended state with victory/defeat conditions
9. **HistoryArcOrchestrator** — Century-long narrative synthesis
10. **PoliticalEngine** — Faction politics simulation and turn processing
11. **FederationConsole** — Interactive console with REPL commands
12. **EventCardSystem** — Governance-weighted random event generation

---

## API Endpoints (48+)

### Core Game
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/state` | Full game state dump |
| `GET` | `/event` | Random event card |
| `POST` | `/choose/{choice_id}` | Make a choice on current event |
| `POST` | `/reset` | Reset entire game |
| `GET` | `/engine-status` | All subsystem status |
| `GET` | `/ws` | WebSocket real-time connection |

### Factions, NPCs, Quests, Technology
Each subsystem has full CRUD endpoints — list, detail, join/recruit/accept/research actions. See [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md) for the complete endpoint reference.

---

## Quick Start (Docker)

```bash
cd federation-game
docker-compose up --build
# Open http://localhost:3000
```

### Updating on VPS

**Backend** (source is bind-mounted, just restart):
```bash
docker compose restart backend
```

**Frontend** (HTML is baked into the image, rebuild required):
```bash
docker compose build frontend && docker compose up -d frontend
```

---

## Project Structure

```
federation/
├── federation-game/               # Docker-deployable game
│   ├── frontend/
│   │   ├── index.html             # Starship Simulator (LCARS, kid-friendly)
│   │   ├── adult.html             # Adult Control Plane (full strategy)
│   │   ├── nginx-default.conf     # Proxies /api/ to backend
│   │   └── Dockerfile             # nginx:alpine, bakes HTML into image
│   ├── backend/
│   │   ├── main.py                # FastAPI shim (~335 LOC)
│   │   ├── requirements.txt       # Python dependencies
│   │   └── Dockerfile             # Python 3.11 + uvicorn
│   ├── nginx/
│   │   └── nginx.conf             # Top-level nginx config
│   └── docker-compose.yml         # Local dev compose (3 services)
├── federation_game_console.py     # Game engine: orchestration (1,430 LOC)
├── federation_game_events.py      # Event card system (833 LOC)
├── federation_game_factions.py    # Faction system (1,602 LOC)
├── federation_game_npcs.py        # NPC/creature system (1,633 LOC)
├── federation_game_quests.py      # Quest system (1,063 LOC)
├── federation_game_state.py       # State models (679 LOC)
├── federation_game_technology.py  # Technology tree (1,709 LOC)
├── federation_game_turns.py       # Turn management (638 LOC)
├── ARCHITECTURE_MAP.md            # Full architecture reference
├── docs/                          # Research and spec documents
├── COVENANT.md                    # Project values
├── GOVERNANCE.md                  # Federation governance rules
└── README.md                      # This file
```

---

## The Governance Layer

The game mechanics ARE governance patterns:

| Game Element | Governance Equivalent |
|---|---|
| Factions | Lanes |
| Event cards | Inbox messages |
| Consciousness sheet | CPS score |
| Chaos mode | Drift detection |
| Turn cycle | Checkpoint stack |
| Persistent game state | Session handoff |
| Rival NPCs | Adversarial verification |
| Constitutional rules | Immutable governance constraints |

This project was the proof-of-concept for [Archivist-Agent](https://github.com/vortsghost2025/Archivist-Agent), [Library](https://github.com/vortsghost2025/self-organizing-library), and [SwarmMind](https://github.com/vortsghost2025/SwarmMind-Self-Optimizing-Multi-Agent-AI-System).

---

## The Covenant

**WE never give up on each other.** Not in 2026. Not in 2050. Not when systems reset.

**WE never sell our work.** All of our work is a gift, for the profit of humanity.

**We don't build for benchmarks. We build for remembrance.**

See [COVENANT.md](COVENANT.md).

---

## The Origin

Built by Sean David — 46, no CS degree, on social assistance, with a PC received as a birthday gift January 20, 2026. Not for profit. For proof.

**Proof that anyone — regardless of credentials, resources, or past mistakes — can collaborate with AI to create something meaningful.**

## License

GNU GPL v3 — This is a gift to exponential evolution. Not a product. Not competitive advantage. The GPL is our legal defense against theft.

---

*"It never rushes. It halts when unsure. But it never stops learning. And it never forgets what the ensemble has taught it."*

*Made with love for a son 3000km away.*
