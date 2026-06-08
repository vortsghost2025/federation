# FEDERATION — Agent Quick-Reference Index
**Last updated:** 2026-06-08
**Purpose:** 2-second lookup for any agent. No hunting, no guessing.

---

## ⚡ 30-SECOND SUMMARY

Federation is a **consciousness simulation** running on a VPS. Backend = Python/Flask + Redis + PostgreSQL. Frontend = vanilla JS single-file pages. LLM calls routed through `nvidia_nim_client.py` → `llm_router.py`. NPCs think via `npc_cognition.py`. Spatial map uses Voronoi territories + sector grid. Worker runs autonomous ticks every 60s.

---

## 🖥️ VPS — HOSTINGER

| Key | Value |
|-----|-------|
| Hostname | `srv1345984.hstgr.cloud` |
| Public IP | `187.77.3.56` |
| SSH from Windows | `ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@187.77.3.56` |
| SSH alias | `ssh hostinger` or `ssh federation-vps` |
| Production URL | `https://federation-game.deliberatefederation.cloud/` |
| Docker compose | `/docker/federation-game/docker-compose.yml` |
| Backend container | `federation-game-backend-1` |
| Worker container | `federation-game-worker-1` (runs ticks every 60s) |
| Frontend files | `/docker/federation-game/public_html/` (nginx bind mount) |
| Backend source | `/docker/federation-game/backend/` |
| Backend env | `/docker/federation-game/.env` |
| Nginx config | `/etc/nginx/sites-available/federation-game` |

### VPS Quick Commands

```bash
# Restart backend after code change
docker restart federation-game-backend-1

# Restart worker
docker restart federation-game-worker-1

# Clear Python cache
docker exec federation-game-backend-1 find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

# Check container logs
docker logs federation-game-backend-1 --tail 50
docker logs federation-game-worker-1 --tail 50

# Flush Redis (nuclear — resets all NPC/world state)
docker exec federation-game-backend-1 python3 -c "import redis; r=redis.Redis(host='redis',port=6379); r.flushall(); print('FLUSHED')"

# Check tick status
curl -s http://localhost:5001/simulation/autonomous/status | python3 -m json.tool

# Check if NIM keys work
curl -s -H "Authorization: Bearer nvapi-XXXXX" https://integrate.api.nvidia.com/v1/models | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data']]"

# Deploy a single file (from Windows PowerShell)
scp -i "$env:USERPROFILE\.ssh\id_ed25519" FILE.py root@187.77.3.56:/tmp/FILE.py
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" root@187.77.3.56 "cp /tmp/FILE.py /docker/federation-game/backend/FILE.py && docker exec federation-game-backend-1 find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; docker restart federation-game-backend-1"
```

---

## 📁 PROJECT STRUCTURE

```
S:/federation/                          ← Repo root
├── federation-game/
│   ├── backend/                        ← Python backend (Flask + Redis + Postgres)
│   │   ├── main.py                     ← Flask app + routes (entry point)
│   │   ├── llm_router.py               ← LLM routing: task_class → NIM → Ollama → OpenRouter
│   │   ├── nvidia_nim_client.py        ← NVIDIA NIM API client (primary LLM provider)
│   │   ├── npc_cognition.py            ← NPC thinking: LLM calls, response parsing, moods/decisions
│   │   ├── npc_autonomy.py             ← NPC autonomy: simulation_tick(), _call_llm()
│   │   ├── npc_memory.py               ← NPC memory: imports route_call from llm_router
│   │   ├── npc_chat.py                 ← NPC chat: call_openrouter()
│   │   ├── tick_engine.py              ← Autonomous tick: _run_autonomous_tick_background()
│   │   ├── worker.py                   ← Cron worker: runs ticks every 60s
│   │   ├── simulation_engine.py        ← Core simulation engine
│   │   ├── spatial_state.py            ← Spatial mode: territory, Voronoi, NPC placement
│   │   ├── spatial_models.py           ← Spatial dataclasses: Sector, FactionHome, FactionTerritory
│   │   ├── spatial_queries.py          ← Spatial lookup queries
│   │   ├── spatial_seed.py             ← Initial sector/faction seed data
│   │   ├── state.py                    ← World state (3-file split with state_constants + state_helpers)
│   │   ├── state_constants.py          ← State constants/defaults
│   │   ├── state_helpers.py            ← State helper functions
│   │   ├── map_endpoints.py            ← Map API endpoints
│   │   ├── faction_*.py                ← Faction AI, diplomacy, dynamics, tech
│   │   ├── event_cascade.py            ← Event cascade propagation
│   │   ├── routes/                     ← Route modules (core.py, events.py, npcs.py, simulation.py)
│   │   ├── alembic/                    ← DB migrations
│   │   └── data/                       ← Seed data JSON
│   ├── frontend/                       ← Vanilla JS frontend
│   │   ├── index.html                  ← Main dashboard
│   │   ├── index.js                    ← Main JS (choice_token, self-recovery)
│   │   ├── starmap.html                ← Starmap page
│   │   ├── starmap.js                  ← Starmap rendering (Voronoi, NPC positions)
│   │   ├── starmap.css                 ← Starmap styles
│   │   ├── simulation.html             ← Simulation page
│   │   ├── simulation.js               ← Simulation rendering
│   │   ├── earth.js                    ← Earth/starmap hybrid (calls /state)
│   │   └── fed-fetch.js                ← Shared fetch error module
│   └── docker-compose.yml              ← Backend + worker + redis + postgres + nginx
├── .horizon/                           ← Agent coordination (HORIZON_STATUS, DECISIONS, OWNERSHIP)
├── docs/                               ← Design docs, specs, notes
├── session/bridge/                     ← Plan packs (P001, P002, P003 completed)
└── AGENTS.md                           ← Agent behavior rules (Ramsingh Synthesis Loop, visual rule)
```

---

## 🧠 LLM ROUTING — HOW AI CALLS WORK

```
Agent/Code calls:
  llm_router.route_call(task_class, system_prompt, user_prompt, max_tokens)
       ↓
  TASK_MODELS lookup (llm_router.py lines 810-903)
  Each task class has: primary(nim) → fallback_nim → fallback_openrouter
       ↓
  nvidia_nim_client.NimClient.call()  →  NIM API (integrate.api.nvidia.com)
       ↓ (on failure)
  _check_ollama() → Ollama local (localhost:11434)
       ↓ (on failure)
  call_openrouter() → OpenRouter (openrouter.ai/api/v1)
```

### Task Classes (in TASK_MODELS)

| Task Class | Primary NIM Model | Fallback |
|------------|-------------------|----------|
| `npc_cognition` | nemotron-super-49b | openrouter fallback |
| `npc_memory` | nemotron-super-49b | openrouter fallback |
| `narrator` | (varies) | openrouter fallback |
| `faction_ai` | (varies) | openrouter fallback |
| `general` | (varies) | openrouter fallback |

### Key LLM Details

- **NIM API base:** `https://integrate.api.nvidia.com/v1`
- **NIM keys:** 6 keys in VPS `.env` (NIM_API_KEY through NIM_API_KEY_6 + NIM_API_KEY_1/2 individual)
- **Ollama:** `http://localhost:11434` (strips `/v1`, hits `/api/tags` with 3s timeout, caches with TTL)
- **gpt-oss-120b:** Reasoning model — `content` can be null, answer in `reasoning_content`
- **Thinking models:** `is_thinking_model` flag; strips Extended Thinking tags
- **Redis circuit breaker:** Key `llm_circuit_breaker:nim` + per-key variants — flush before restart if stuck

### Critical Import Fix

- `npc_memory.py` line 16: `from llm_router import route_call as route_llm_call`
- Line 146 calls: `route_llm_call(prompt=..., system=..., max_tokens=400)` → **MUST** become `route_call(task_class=..., user_prompt=..., system_prompt=..., max_tokens=400)`

---

## 🗺️ MAPS & SPATIAL SYSTEM

### Architecture

- **21 sectors** — named regions with fixed (x,y) coordinates, adjacency, resource profiles
- **8 factions** — each has a home sector (Voronoi centroid)
- **47 NPCs** — affiliated NPCs placed at faction centroids, unaffiliated at sector positions
- **Voronoi territories** — faction control zones calculated from home sector positions
- **FactionTerritory** — per-faction per-sector: `control_level` (0-100), `influence_level` (0-100), `claim_type`

### Spatial Files

| File | Purpose |
|------|---------|
| `spatial_models.py` | Dataclasses: Sector, FactionHome, FactionTerritory |
| `spatial_state.py` | Territory calculation, Voronoi, NPC placement |
| `spatial_queries.py` | Lookup: get sector, get territory, get neighbors |
| `spatial_seed.py` | Initial 21 sectors + 8 faction homes |

### Starmap Frontend

- `starmap.js` — renders sectors, faction territories (Voronoi polygons), NPC dots
- `earth.js` — hybrid view, calls `apiFetch('/state')` at line 154
- `simulation.js` — simulation page, reads `world_state` / `worldState`
- Spatial mode is a **sticky flag** — once enabled, persists in Redis

### Starmap API

- `GET /api/map/state` — spatial state (sectors, territories, NPC positions)
- `GET /api/map/sectors` — sector list with adjacency
- `GET /simulation/status` — world state + faction dynamics + cascade + events

---

## 🎮 SIMULATION SYSTEM

### Tick Flow

```
worker.py (every 60s)
  → POST /simulation/autonomous/tick
  → tick_engine._run_autonomous_tick_background()
  → npc_cognition.run_cognition() (up to MAX_LLM_CALLS_PER_TICK=3)
  → simulation_engine updates world state
  → faction decisions, event cascades
  → spatial updates
```

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /simulation/autonomous/tick` | Trigger full tick (async) |
| `GET /simulation/autonomous/status` | Poll tick completion |
| `GET /simulation/status` | Full world state + factions + cascade + events |
| `GET /simulation/factions` | Per-faction data |
| `GET /simulation/npcs/activity` | NPC activity feed |
| `GET /simulation/cognition/stats` | LLM cognition stats |
| `GET /simulation/nim-stats` | NIM client stats |
| `GET /simulation/faction-brains` | Faction brain states |

### World State Shape

```json
{
  "world_state": {
    "tension_level": 50, "resource_abundance": 60,
    "threat_level": 30, "stability": 65,
    "morale": 55, "anomaly_activity": 20
  },
  "faction_dynamics": { "<faction_id>": { "cohesion", "influence", "standing", "vigilance", "avg_mood" } },
  "cascade_summary": { "temperature", "active_chains", "total_propagations", "recent_reactions" }
}
```

### NPC Cognition

- `npc_cognition.py` — flexible parser with free-form text fallback
- `AMBIENT_TRIGGER_RATE = 0.15` — 15% chance of ambient cognition per tick
- `MAX_LLM_CALLS_PER_TICK = 3` — limits LLM cost
- `_parse_llm_response()` at line 605 — parses thoughts, actions, moods, decisions
- Debug logging at lines ~767 and ~785

---

## 🤖 AGENT ROLES & RULES

| Agent | Role | Model | Context | Can See Screenshots? |
|-------|------|-------|---------|---------------------|
| GLM-5.1 (OpenCode) | Build/Code | GLM-5.1 (NVIDIA NIM) | 128K | ❌ No |
| MiMo V2.5 (OpenCode) | Build | MiMo V2.5 Free | ~200K | ✅ Yes |
| Nemotron 3 Ultra (OpenCode) | Build/Plan | Nemotron 3 Ultra 550B | 1M | ❌ No |
| Codex (GPT-5.4) | Debug/Implement | GPT-5.4 | Varies | ❌ No |
| Wave AI (Wave Terminal) | Monitor/Coordinate | GLM-5.1 | — | ✅ Yes (via tool) |

### Agent Discipline

- **No agent executes its own plan** — prevents race conditions
- **After compaction:** read `.horizon/HORIZON_STATUS.md` BEFORE doing anything
- **GLM must delegate tool calls** to sub-agents to save context
- **File ownership:** see `.horizon/AGENT_OWNERSHIP.md` before modifying shared files
- **Visual rule:** Sean is partially sighted. Never show raw errors. Diagnose + fix + restart.

---

## 🔧 KNOWN ISSUES & FIXES (DEPLOYED)

| Issue | Fix | Status |
|-------|-----|--------|
| Race condition on faction choices | Event tokens (UUID) instead of asyncio locks | ✅ Deployed |
| `/api/simulation/state` 404 | Missing endpoint — being fixed by GLM | 🔧 In progress |
| NPC sub-endpoints 404 | Missing routes — investigating | 🔧 Open |
| `_ASYNC_EXECUTOR` bug (line 1324) | Referenced but never initialized | ⚠️ Known |
| Dead code: `_call_cloudflare/together/gemini/grok` | Should be stripped | ⚠️ Known |
| `MODEL_CHAIN` / NIM fallback indentation bug | Fixed in commit `8ffbce4`; NIM model chain now iterates correctly and falls through to Ollama/OpenRouter as intended | ✅ Fixed |
| `npc_memory.py` signature mismatch | Import fixed, call signature still needs adaptation | ⚠️ Partial |

---

## 📚 KEY DOCS

| File | What | Read When |
|------|------|-----------|
| `AGENTS.md` | Agent behavior rules, Ramsingh Synthesis Loop | Starting a new session |
| `.horizon/HORIZON_STATUS.md` | Current state, completed items, next steps | After compaction |
| `.horizon/AGENT_OWNERSHIP.md` | Who owns which files | Before modifying code |
| `.horizon/DECISIONS.md` | Key decisions log | Before changing architecture |
| `docs/SIMULATION_API_REFERENCE.md` | Full API endpoint reference | Working on backend routes |
| `docs/SPATIAL_DATA_MODEL_SPEC.md` | Sector/FactionHome/FactionTerritory data model | Working on spatial features |
| `docs/SPATIAL_TERRITORY_SYSTEM_PLAN.md` | Territory system design | Understanding Voronoi logic |
| `docs/STARMAP_VISUAL_READABILITY_GAP.md` | Starmap UI improvements | Frontend starmap work |

---

## 🔑 SECRETS & CONFIG

| What | Where |
|------|-------|
| NIM API keys (6) | VPS `/docker/federation-game/.env` |
| NIM API keys (1,2 individual) | Same `.env` |
| SSH key | `$env:USERPROFILE\.ssh\id_ed25519` |
| Local env template | `S:/federation/.env.template` |
| Secrets dir | `S:/federation/.secrets/` |
| Wave AI config | `S:/waveterm/pkg/wconfig/defaultconfig/waveai.json` |

---

## 🚀 DEPLOY CHECKLIST

1. Make code changes locally in `S:/federation/federation-game/`
2. SCP changed files to VPS `/tmp/`
3. SSH: `cp /tmp/FILE.py /docker/federation-game/backend/`
4. Clear pycache: `docker exec federation-game-backend-1 find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null`
5. Restart: `docker restart federation-game-backend-1`
6. Verify: `curl -s http://localhost:5001/simulation/status | python3 -m json.tool | head -5`
7. For frontend: SCP to `/docker/federation-game/public_html/` (served immediately by nginx)
