# Federation Codebase Map

Research compiled for AI agent orchestration.

---

## 1. VPS Architecture (docker-compose.yml Services)

| Service | Ports | Bind Mounts | Build vs Restart |
|---------|-------|-------------|------------------|
| **reverse-proxy** | 80, 443, 8080 | `/var/run/docker.sock:ro`, `./letsencrypt` | Image: `traefik:latest` - restart only |
| **backend** | 8000 (internal) | `/docker/federation-game/backend:/app:ro` | Build: `/docker/federation-game/backend` - **needs rebuild** for Python changes |
| **frontend** | 80 (internal) | `/docker/federation-game/public_html:/usr/share/nginx/html:ro` | Build: `/docker/federation-game/frontend` - **needs rebuild** for HTML changes |
| **worker** | none | `/docker/federation-game/backend:/app:ro` | Build: `/docker/federation-game/backend` - **needs rebuild** for Python changes |
| **postgres** | 5432 (internal) | `postgres_data:/var/lib/postgresql/data` (named volume) | Image: `postgres:15-alpine` - restart only |
| **redis** | 6379 (internal) | none (ephemeral) | Image: `redis:7-alpine` - restart only |
| **adminer** | 8080 (internal) | none | Image: `adminer:latest` - restart only |
| **prometheus** | 9090 | `/docker/federation-game/monitoring/prometheus.yml` | Image: `prom/prometheus` - restart only |
| **grafana** | 3000 | Multiple monitoring paths | Image: `grafana/grafana` - restart only |
| **node-exporter** | 9100 | Host system access | Image: `prom/node-exporter` - restart only |
| **redis-exporter** | 9121 | none | Image: `oliver006/redis_exporter` - restart only |
| **postgres-exporter** | 9187 | none | Image: `prometheuscommunity/postgres-exporter` - restart only |
| **cadvisor** | 8080 | Host Docker socket access | Image: `gcr.io/cadvisor/cadvisor` - restart only |

---

## 2. Backend API Surface (main.py @app endpoints)

**Core Game State:**
- `@app.get("/")` - Root endpoint, returns API status message
- `@app.get("/state")` - Current player/federation state (turn, credits, fuel, shields, etc.)
- `@app.get("/atlas")` - Returns FEDERATION_ATLAS (NPC system, creature codex, technology tree)
- `@app.get("/engine-status")` - Full backend engine systems status

**Events & Choices:**
- `@app.get("/event")` - Random governance event generation
- `@app.post("/choose/{choice_id}")` - Submit player choice to an event

**NPC Endpoints:**
- `@app.get("/npcs")` - List all NPCs with basic info
- `@app.get("/npcs/{char_id}")` - Get specific NPC by ID
- `@app.post("/npcs/{char_id}/recruit")` - Recruit an NPC companion
- `@app.post("/npcs/{char_id}/interact")` - Interact with NPC
- `@app.post("/npcs/{char_id}/chat")` - Chat with NPC
- `@app.get("/npcs/{char_id}/thoughts")` - Recent NPC thoughts
- `@app.get("/npcs/{char_id}/actions")` - Recent NPC actions
- `@app.get("/npcs/{char_id}/mood")` - Current NPC mood
- `@app.get("/npcs/{char_id}/goals")` - NPC current goals
- `@app.get("/npcs/{char_id}/decisions")` - NPC decision log
- `@app.get("/npcs/{char_id}/broadcast-events")` - NPC broadcast events

**Faction Endpoints:**
- `@app.get("/factions")` - List all factions
- `@app.post("/factions/{faction_id}/join")` - Join a faction
- `@app.get("/simulation/factions")` - Faction simulation state

**Simulation/Tick Endpoints:**
- `@app.post("/simulation/tick")` - Run NPC autonomy tick
- `@app.get("/simulation/tick/status")` - Check tick completion status
- `@app.post("/simulation/autonomous/tick")` - Autonomous tick
- `@app.get("/simulation/autonomous/status")` - Autonomous tick status
- `@app.get("/simulation/status")` - Overall simulation status
- `@app.post("/npcs/advance-turn")` - Advance NPC turn

---

## 3. Worker Intelligence (worker.py)

**Tick Loop Flow:**
1. Fetches backend health check
2. Initializes Apprise notifications
3. Enters main loop with `TICK_INTERVAL` (default 60s from env)
4. Calls endpoints in sequence:
   - `/npcs/advance-turn` (120s timeout)
   - `/simulation/tick` (15s, async with polling)
   - `/political/process-turn` (60s)
   - `/history-arc/advance` (60s)
   - `/simulation/autonomous/tick` (15s, async with polling)
   - `/cognition/tick` (120s)
   - `/narrator/generate` (90s)
5. Auto-saves via `/state/save`
6. Publishes to Redis `federation:updates` channel
7. Checks for significant events and sends notifications

**Notification Decision Logic:**
- Fetches crisis readout from `/map/data`
- Checks for era transitions, coherence collapse, rival hostile actions, timeline branch points, Chaosbringer activity, laws passed
- Checks NPC broadcasts with significance >= 0.5

**Throttle/Dedupe Logic:**
- STABLE/MODERATE: No Telegram notification
- ELEVATED+: Notification sent
- 10-minute dedupe on same headline+classification
- Severity increase always sends immediately

---

## 4. Frontend Pages Inventory

| Filename | Lines | JS Init Function | API Endpoints Called |
|----------|-------|-----------------|-------------------|
| `simulation.html` | ~800 | `init()` | `/map/data`, `/simulation/events`, `/broadcast-events`, `/npcs/*`, `/factions`, `/simulation/npc-quests`, `/simulation/choice-resolutions`, `/simulation/faction-tech` |
| `bridge.html` | ~1842 | `init()` | `/state`, `/factions`, `/engine-status`, `/world/state`, `/quests`, `/technology` |
| `starmap.html` | ~1869 | `init()` | `/map/data`, `/world/state`, `/broadcast-events`, `/factions` |
| `earth.html` | ~828 | `init()` | `/state`, `/factions`, `/simulation/status` |
| `index.html` | smaller | Various init functions | Core game state, events |
| `adult.html` | - | - | Control/adult content pages |
| `worldguide.html` | - | - | World documentation |
| `constellation.html` | - | - | Universe/star charts |
| `spectator.html` | - | - | Read-only simulation view |

---

## 5. Traefik Routing

**Frontend HTML Paths (Priority 200):**
- `/simulation.html`
- `/bridge.html`
- `/starmap.html`
- `/earth.html`

**Backend API Paths (Priority 100):**
- `/npcs`, `/world`, `/simulation/`, `/political`, `/factions`, `/broadcast-events`, `/quests`, `/technology`, `/history-arc`, `/atlas`, `/consciousness`, `/engine-status`, `/map/`, `/state`, `/systems-overview`, `/timeline`, `/rivals`, `/reset`, `/log`, `/ws`, `/healthz`, `/docs`, `/openapi.json`, `/redoc`, `/cognition`, `/narrator`

---

## 6. Redis Data Model

**Redis Keys:**
- `npc_thoughts:{char_id}` - ZSET (score=timestamp)
- `npc_opinion:{char_id}:{player_id}` - HASH
- `npc_actions:{char_id}` - ZSET (score=timestamp)
- `npc_relationships:{char_id}` - HASH
- `npc_world_events` - ZSET
- `npc_mood:{char_id}` - STRING
- `npc_last_active:{char_id}` - STRING
- `npc_decisions:{char_id}` - ZSET
- `npc_broadcast_events` - ZSET
- `npc_profiles` - HASH/list
- `npc_faction_context:{char_id}` - STRING JSON

---

## 7. Simulation Status

**Tick Interval:** 60 seconds (TICK_INTERVAL env var)

**LLM Model:** NVIDIA NIM primary, OpenRouter fallback

**Environment Variables:**
- `TICK_INTERVAL` - Default 60
- `BACKEND_URL` - Default `http://backend:8000`
- `REDIS_URL` - Default `redis://redis:6379/0`
- `NOTIFICATION_URLS` - Apprise notification URLs
- `OPENROUTER_API_KEY` - LLM API key

---

## 8. Build/Deploy Pipeline

**Backend Python:**
```bash
docker-compose build backend && docker-compose up -d backend
```

**Worker Python:**
```bash
docker-compose build worker && docker-compose up -d worker
```
(Shares backend image - same rebuild)

**Frontend HTML:**
```bash
docker-compose restart frontend
```
(No build needed - static HTML via nginx bind mount)