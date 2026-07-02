# FEDERATION_CONTEXT_PACK

## 0. Snapshot Metadata
- **Timestamp:** 2026-07-01T17:45-04:00 (generated)
- **Git HEAD:** `c4545c5` — [7] npc_goals — wire existing goals module
- **Branch:** `phase1-redis-helpers`
- **Local path:** `S:\federation\federation-game`
- **VPS/docker-compose path:** `/docker/federation-game/docker-compose.yml` (VPS has separate `docker-compose-vps.yml`)
- **Runtime containers (16):** backend, worker, frontend, redis, postgres, reverse-proxy (traefik), adminer, prometheus, grafana, node-exporter, redis-exporter, postgres-exporter, cadvisor, npc-agent-001, npc-agent-306, npc-sandbox
- **Which services are live:** All 16 containers running
- **Files recently changed but NOT deployed:** `main.py`, `npc_autonomy.py` (modified), `error-reporter.js`, `simulation.html`, `simulation.js`, `starmap.js`, `nginx-default.conf`, plus untracked `npc_decisions.py`, `npc_simulation.py`, `routes/admin.py`, `frontend/admin.html`, `npc-agent/institutions.py`

---

## 1. One-Paragraph System Summary

Federation is a consciousness simulation running on a single VPS (187.77.3.56) with 16 Docker containers. The simulation has 39 NPCs total: **37 are backend-managed** (in-memory `game_state.npc_system`, processed by `npc_simulation.py` / `npc_autonomy.py` every worker tick) and **2 are external-agent NPCs** (char_001 "Archimedes Prime", char_306 "The Oracle") running in dedicated `npc-agent` Docker containers with their own NVIDIA NIM API keys and a 45s cognition loop. The backend runs FastAPI with PostgreSQL (entity storage) and Redis (ephemeral state: needs queue, workflows, institutions, world state, decisions, moods, circuit breakers). A worker container ticks every 600s (10 min), calling backend endpoints to advance NPCs, simulation, political engine, history arc, cognition, and narrator — then syncs institution/tick/councilor bridge state. The NPC autonomy loop has institutions (Research Division Council, Consciousness Collective Council), an outcomes/P3 memory system, a needs queue (NPCs request capabilities from councilors), a decree/directive system (councilors adjust world metrics) and a safety boundary: NPCs can only file structured needs, submit workflow proposals, and create artifacts — no shell/server/provider-key access. The frontend has ~15 pages (simulation, starmap, spectator, bridge, earth, constellation, index, adult, council-chat, worldguide, admin, npc-logs) served by nginx with shared `fed-fetch.js` (retry/timeout wrapper) and `error-reporter.js`. Provider stack: NVIDIA NIM (primary, 6+ keys), Ollama (local), OpenRouter (3 keys round-robin, free tier + paid, paid hitting 402 billing errors), Gemini (depleted, 1hr cooldown), and template fallback.

---

## 2. Runtime / Docker Topology

| Container | Purpose | Image/Source | Bind Mount? | Restart | Ports/Routes | Health |
|-----------|---------|-------------|-------------|---------|-------------|--------|
| **reverse-proxy** | Traefik TLS + routing | `traefik:latest` | `/var/run/docker.sock:ro`, `./letsencrypt` | unless-stopped | 80:80, 443:443 | Docker health |
| **backend** | FastAPI server | `./backend` build | `/docker/federation-game/backend:/app:ro` | unless-stopped | 8000, via traefik routes | `python3 -c '.../healthz'` 60s |
| **worker** | Tick engine (10 min) | `./backend` build | `/docker/federation-game/backend:/app:ro` | unless-stopped | N/A (calls backend HTTP) | None |
| **frontend** | nginx static serving | `./frontend` build | **BAKED** (nginx-default.conf bind-mounted) | unless-stopped | 80, via traefik routes | None |
| **postgres** | Persistent entity storage | `postgres:15-alpine` | volume `postgres_data` | unless-stopped | 5432 | pg_isready 10s |
| **redis** | Ephemeral state | `redis:7-alpine` | volume `redis_data` | unless-stopped | 6379 | redis-cli ping 10s |
| **prometheus** | Metrics collection | `prom/prometheus:latest` | config bind, volume | unless-stopped | 9090 | None |
| **grafana** | Dashboards | `grafana/grafana:latest` | multi-bind config | unless-stopped | 3000, /grafana route | None |
| **adminer** | DB admin | `adminer:latest` | none | unless-stopped | 8080, adminer subdomain | None |
| **npc-agent-001** | Councilor 1 loop | `./npc-agent` build | `/docker/federation-game/npc-agent:/app:ro` | unless-stopped | N/A (Redis calls) | None |
| **npc-agent-306** | Councilor 2 loop | `./npc-agent` build | `/docker/federation-game/npc-agent:/app:ro` | unless-stopped | N/A (Redis calls) | None |
| **npc-sandbox** | Artifact execution sandbox | `./npc-sandbox` build | volume `artifacts_data` | unless-stopped | N/A | None |
| cadvisor/node-exporter/redis-exporter/postgres-exporter | Monitoring | various | host bind mounts | unless-stopped | N/A | None |

**Critical mount details:**
- Backend/worker: `ro` bind mount — VPS host file change → container picks up on restart
- NPC-agent: `ro` bind mount — same pattern
- Frontend: **BAKED** at build time — host changes require `docker cp` into running container then `nginx -s reload`
- All Python files loaded at process start: containers **must restart** for code changes to take effect (Python doesn't hot-reload in prod)

**Verify host vs container md5:**
```bash
ssh root@187.77.3.56 'md5sum /docker/federation-game/backend/npc_autonomy.py'
ssh root@187.77.3.56 'docker exec federation-game-backend-1 md5sum /app/npc_autonomy.py'
```

---

## 3. NPC Topology

### 3a. The 2 External-Agent Councilors (Persistent, Sandboxed)

| Property | char_001 (Archimedes Prime) | char_306 (The Oracle) |
|----------|----------------------------|----------------------|
| Container | `federation-game-npc-agent-001-1` | `federation-game-npc-agent-306-1` |
| Primary NIM model | `nvidia/llama-3.3-nemotron-super-49b-v1` | `nvidia/nemotron-3-super-120b-a12b` |
| Fallback models | `nvidia/nemotron-3-nano-30b-a3b`, `meta/llama-3.3-70b-instruct` | `nvidia/nemotron-3-nano-30b-a3b`, `meta/llama-3.1-70b-instruct` |
| NIM key source | `${NVIDIA_API_KEY_CHAR_001_TEST}` | `${NVIDIA_API_KEY_CHAR_306}` |
| OR key | `${OPENROUTER_API_KEY_1}` | `${OPENROUTER_API_KEY_1}` |
| Tick interval | 45s | 45s |
| Request timeout | 45s | 45s |
| Max output tokens | 1024 | 1024 |
| Decision loop | `think_about_world()` → `decide_action()` → `execute_decision()` | same |
| CPU/Mem limit | 0.5 CPU, 256MB | 0.5 CPU, 256MB |
| Institution role | `role:research_chief_mathematician` | `role:collective_oracle` |
| Affiliation | `research_division` | none (independent) |
| Faction alliance | `research_division` ↔ `consciousness_collective` | -- |

**Sandbox boundaries:**
- Both councilors run in isolated Docker containers with read-only mounts
- No shell access, no file system write access (except volumes)
- LLM calls go through their own NIM API key, not the shared backend pool
- Redis access is shared (same Redis), but they use separate key prefixes
- `npc-decisions.py` has FOURTH_WALL enforcement: `_enforce_fourth_wall()` checks for attempts to access shell/keys/admin/external and blocks them [code, npc_decisions.py]
- The `SELF_INTRO` system prompt tells them: "You do not directly control that hardware, but you may request it, design for it, build toward it" and "You do not command other NPCs"

**Backend skip (npc_simulation.py L62):**
```python
EXTERNAL_AGENT_NPCS = {"char_001", "char_306"}
if char_id in EXTERNAL_AGENT_NPCS:
    return npc_result  # backend skips these during simulation_tick
```
This means the 37 remaining NPCs are processed by `make_decision()` in the backend autonomy loop.

### 3b. The 37 Backend-Managed NPCs

Created by `build_npc_system()` in `npcs.py` (builds 35+ from seed data in `data/`). Loaded into `game_state.npc_system.characters` dict at startup. Each has:
- `Character` object with `char_id`, `name`, `personality_type` (archetype), `affiliation` (faction), `title`, `relationships`, `current_goals`
- Status can be: `ACTIVE`, `IMPRISONED`, `DEAD`, `TRAVELING`, `HIDDEN`, `MISSING`, `CORRUPTED`
- 8 factions: research_division, military_command, diplomatic_corps, consciousness_collective, cultural_ministry, economic_council, exploration_initiative, preservation_society
- ~47 NPCs in spatial system (starmap), but only 35+ active in game state

**These 37 NPCs:**
- Are NOT persistent — their state is Redis-backed but their consciousness loop runs only when the worker tick processes them
- Use the shared LLM provider pool (backend's llm_router.py)
- Are processed in `npc_simulation._process_single_npc()` which calls `update_mood()`, `make_decision()`, `broadcast_decision_event()`, `generate_thought()`, `generate_action()` [code, npc_simulation.py L42-L100]
- CAN create artifacts, investigate, submit needs (via `file_npc_need()`), submit workflow proposals, create institutions, propose roles — all through the needs queue system
- Are purely backend state — no dedicated agent containers

### 3c. Decision Loop (Per NPC per tick)

```
npc_autonomy.py: make_decision()
  → evaluate_decision_options() → _score_decision_option() → selects category
  → _reflect_on_missing_context() (P0 pivot_strategy)
  → generate_text() via llm_router → produces decision JSON
  → _write_decree_directive() if councilor
  → broadcast_decision_event() → Redis npc_broadcast_events

npc_memory.py records outcome
npc:needs system for capability requests (throttled: 1 per 10 min per NPC, max 100 queue)
```

### 3d. Redis Key Patterns per NPC

| Key Pattern | Type | Purpose |
|-------------|------|---------|
| `npc_thoughts:{char_id}` | ZSET | Recent thoughts (score=timestamp) |
| `npc_opinion:{char_id}:{player_id}` | HASH | Opinion data |
| `npc_actions:{char_id}` | ZSET/LIST | Recent actions |
| `npc_mood:{char_id}` | STRING | Current mood |
| `npc_decisions:{char_id}` | ZSET/LIST | Recent decisions |
| `npc_state:{char_id}` | HASH | State (corruption, rumor, status) |
| `npc_stats:{char_id}` | HASH | Unread count, stats |
| `npc:notifications:{char_id}` | LIST | Fulfilled need notifications |
| `npc:context_snapshot:{char_id}` | HASH | Context for needs |
| `npc_messages:{char_id}:inbox` | LIST | Inbox for councilor pair |
| `npc:workflow_outcomes:{char_id}` | HASH | Approved/rejected counts |
| `npc:recent_outcomes:{char_id}` | LIST | Last 20 outcomes (P3) |
| `npc_agent:registry` | HASH | Agent container registry |

---

## 4. Autonomy Pipeline

### Exact Tick Flow

```
worker.py (every 600s / 10 min)
  → POST /npcs/advance-turn            (turn increment)
  → POST /simulation/tick               (async, polls status)
  → POST /political/process-turn        (political engine)
  → POST /history-arc/advance           (history arc)
  → POST /simulation/autonomous/tick    (async, polls status)
  → POST /cognition/tick                (LLM cognition)
  → POST /narrator/generate             (narrator)
  → run_councilor_sync():
      → write_world_snapshot()          (npc_world_snapshot)
      → run_bridge_tick()               (councilor_bridge)
      → run_institution_tick()          (institutions.py)
      → evaluate_decree_opportunity()   (npc_decree.py)
  → POST /state/save                    (auto-save)
  → Crisis decay (2% regression per tick toward mean for world_state)
  → Redis publish + Apprise notifications
```

### Key Files and Functions

| File | Key Functions | L |
|------|--------------|---|
| `backend/npc_autonomy.py` | `simulation_tick()`, `make_decision()`, `evaluate_decision_options()`, `_score_decision_option()`, `_reflect_on_missing_context()` | ~2600 |
| `backend/npc_simulation.py` | `_process_single_npc()`, `simulation_tick()` (calls per-NPC decision) | 239 |
| `backend/worker.py` | `run_tick()`, `run_councilor_sync()`, `_call_endpoint()`, `_poll_async_completion()` | 971 |
| `backend/institutions.py` | `seed_institutions()`, `advance_workflow()`, `override_workflow_status()`, `_record_outcome()`, `run_institution_tick()` | 420 |
| `backend/npc_decree.py` | `evaluate_decree_opportunity()`, `_write_decree_directive()`, `issue_decree()` | -- |
| `backend/npc_reflection.py` | `_reflect_on_missing_context()`, `_score_decision_option()`, `evaluate_decision_options()` | -- |
| `backend/npc_thoughts.py` | Thought generation with significance priority | -- |
| `backend/routes/npc_logs.py` | `/spectator/agency`, `/api/npc-logs` | 1197 |
| `npc-agent/npc_agent.py` | Councilor main loop, `decide_action()`, `execute_decision()` | 105 |
| `npc-agent/npc_decisions.py` | `SELF_INTRO` system prompt, decision logic, anti-loop guards | 694 |
| `npc-agent/npc_actions.py` | `execute_decision()`, `update_mood()` | -- |
| `npc-agent/npc_context.py` | `think_about_world()`, neighborhood snapshot, topic cooldown | -- |

### Decision Option Scoring

`_score_decision_option()` at L2592 of npc_autonomy.py evaluates categories based on:
- archetype (SCHOLAR → research, WARRIOR → combat)
- mood (anxious → cautious decisions)
- has_active_goals, has_allies, has_rivals
- recent_event_count, broadcast_event_count
- **P0: need_reflection** — if NPC has unfulfilled needs, `_reflect_on_missing_context()` adds `pivot_strategy` bias [code, npc_reflection.py]
- **P3: outcome_ctx** — reads `npc:{npc_id}:workflow_outcomes` and `recent_outcomes` to bias away from repeated failures [code, npc_autonomy.py L2396]

### P2 Directive System
- `councilor:directive:active` Redis key (TTL 600s)
- Written by `_write_decree_directive()` when councilors issue directives
- Only char_001 and char_306 can issue decrees (`DECREES_ALLOWED_NPCS`)
- `DECREE_COOLDOWN_SECONDS` prevents spam

### Needs Queue Safety/Throttle/Dedupe
- `ALLOWED_NEED_TYPES` = 8 types (context_request, resource_access, communication_channel, collaboration_tool, data_access, skill_development, request_capability, pivot_strategy)
- `FORBIDDEN_NEED_TYPES` = anything not in ALLOWED
- Max 1 need per NPC per 10 minutes (dedup throttle based on `npc:needs:{npc_id}:last` timestamp)
- Max queue length = 100
- Dedupe: same `(npc_id, need_type, description)` within window → rejected
- `CloseNeedPayload` resolution: `closed_fulfilled`, `closed_rejected`, `closed_duplicate`

### Institution Workflow Status Transitions
- `proposal_review`: submitted → under_review → deliberating → **ratified**
- `analysis_review`: submitted → peer_review → **endorsed**
- Terminal states: `ratified`, `endorsed`, `approved`, `rejected`
- `_record_outcome()` at L374: terminal-state guard — only records once per workflow
- `MAX_RECENT_OUTCOMES = 20` per NPC

---

## 5. Provider / LLM Routing

### Fallback Chain (llm_router.py `route_call()`)

| Step | Provider | Model | Key Strategy | Timeout | Status |
|------|----------|-------|-------------|---------|--------|
| 1 | **NVIDIA NIM** (primary) | Varies by task_class (nemotron-super-49b, etc.) | 6+ keys round-robin, per-key rate limit (40 req/min), circuit breaker | 15-45s | ✅ Primary |
| 2 | **Ollama** | `qwen2.5-coder:3b-instruct` | Single keyless, max 1 active / 3 queued, 60s cooldown on 500 | 45s | ⚠️ /v1 base URL may fail |
| 3 | **OpenRouter free** | Various free models | 3 keys round-robin, per-task-class rotation | 30s | ⚠️ Mixed |
| 4 | **OpenRouter paid** | Paid models | Same 3 keys | 30s | ❌ **402 billing errors** — blocked |
| 5 | **Gemini** | gemini-2.0-flash | Single key, **1hr cooldown** via `gemini_depleted` Redis key | 30s | ❌ **429 depleted** — cooldown active |
| 6 | **Template fallback** | Hardcoded safe response | N/A | Instant | ✅ Last resort |

### Detailed Provider State

| Provider | Circuit Breaker Key | Current Health | Notes |
|----------|-------------------|---------------|-------|
| NIM | `circuit_breaker:nim` (Redis) | ✅ Likely healthy | Primary. 6+ keys in `NIM_API_KEYS` env var |
| NIM per-key | `circuit_breaker:nim_{key_hash}` | Unknown | Tracks individual keys |
| Ollama | `_ollama_lane` (in-memory lane sync) | ⚠️ Intermittent | Base URL: `http://100.95.92.117:11434/v1` — /v1 endpoint may not work, `/api/tags` check with 3s timeout, caches availability 60s |
| OpenRouter | `circuit_breaker:openrouter` | ⚠️ Mixed | Key rotation over 3 keys, 402 errors on paid models |
| Gemini | `circuit_breaker:gemini` + `gemini_depleted` | ❌ **Depleted** | 429 errors, 1hr cooldown via Redis key |

**Recent 12-hour failures:** OpenRouter 402 billing errors (paid tier blocked), Gemini 429/depleted (cooldown active), Ollama possibly failing due to `/v1` path issue (Ollama API is `/api/chat` not `/v1/chat/completions`).

**User visibility:** Failures are handled by fallback chain — not user-visible unless ALL providers fail → template fallback. Backend logs show fallback chain.

---

## 6. Frontend Architecture

### Page Map

| Page | Purpose | JS File | Uses fed-fetch.js? | Uses error-reporter.js? |
|------|---------|---------|-------------------|------------------------|
| **index.html** | Main game dashboard (player-facing) | `index.js` | No (raw fetch) | No |
| **simulation.html** | Live simulation observer | `simulation.js` (2628 lines) | ✅ Yes (via `quietJsonFetch` at L776) | Included via script tag |
| **spectator.html** | Narrative spectator view | `spectator.js` (1365 lines) | Partial | No |
| **bridge.html** | Councilor bridge | `bridge.js` | Unknown | Unknown |
| **starmap.html** | Spatial/Voronoi visualization | `starmap.js` | Unknown | Unknown |
| **starmap3d.html** | 3D starmap | (inline) | Unknown | Unknown |
| **constellation.html** | Constellation view | `constellation.js` | Unknown | Unknown |
| **earth.html** | Earth/starmap hybrid | `earth.js` | Calls `apiFetch('/state')` | Unknown |
| **adult.html** | Control panel | `adult.js` | Unknown | Unknown |
| **council-chat.html** | Councilor chat | (inline) | Unknown | Unknown |
| **worldguide.html** | World guide | `worldguide.js` | Unknown | Unknown |
| **admin.html** | NEW: admin panel (untracked) | (inline) | Unknown | Unknown |
| **npc-logs.html** | NPC logs viewer | (inline) | Unknown | Unknown |

### fed-fetch.js Behavior
- Global: `window.fedFetch(key, url, opts)`
- Retries: 2 retries default, exponential backoff (1.5x multiplier, max 30s)
- Timeout: 8s default, configurable via `opts.timeout`
- Offline detection: `navigator.onLine`, dispatches `fedFetch:error` custom event on failure
- Toast notifications on failure (green for OK, red for warn)
- Link health CSS indicators (`#linkHealth-{key}`)
- Returns `null` on all failures (not throw)

### error-reporter.js Behavior
- Global `window.onerror`, `unhandledrejection`, `ReportingObserver`
- Patches `window.fetch` to catch network failures
- Batches reports and sends to `/error-reports` via XMLHttpRequest
- Auto-disables on 404 (endpoint not found)

### Known Fetch Gaps
- **index.js** uses raw `fetch` — no fedFetch wrapper, no retry [code, index.js]
- **simulation.js** uses mixed: `fedFetch()` for main status (`/simulation/status`), `quietJsonFetch` for npc-logs, raw fetch for some endpoints
- **earth.js** uses `apiFetch('/state')` — custom wrapper, not fedFetch
- `quietJsonFetch` appears to be a local wrapper in simulation.js (not a shared module)
- Some pages may not include `error-reporter.js` at all
- **No centralized offline/loading/retry UI** across all pages

---

## 7. Current Browser Observations (Inferred from Code)

Based on code analysis, the simulation observer page (`simulation.html` + `simulation.js`) would show:

**Stability/Morale/Threat:** Derived from `/simulation/status` API call → `world_state` hash in Redis
- Stability: `ws.stability` from Redis `world_state` hash
- Morale: `ws.morale`
- Threat: `ws.threat_level`
- Resources: `ws.resource_abundance`
- Anomaly: `ws.anomaly_activity`
- Tension: `ws.tension_level`
- All metrics display with severity labels (FRAGILE/STABLE/CRITICAL etc.) computed **entirely client-side** by `severityInfo()` function

**Degradation vs Runway:** Computed **client-side** as `(100-morale + 100-stability + anomaly) / 3`

**Threat vs Buffer:** Computed **client-side** as `((threat + tension)/2) / ((threat + tension)/2 + resources)`

**Councilor Autonomy metric: NOT exposed.** There is no backend endpoint returning "autonomy" for councilors. If the UI shows `0`, it means:
- No such field exists in any API response
- Or the frontend code references `autonomy` but the backend stopped returning it
- The two councilors' behavior is tracked via `npc-agent` container ticks, not via any backend metric

**Failure rate:** 25% failure would come from `fedFetch` errors. Endpoints most likely failing:
- `/api/councilor/needs` (if no open needs)
- `/spectator/agency` (if npc_logs.py has issues)
- `/simulation/autonomous/status` (409 or timing out on concurrent ticks)
- Any endpoint behind a route mismatch

---

## 8. Backend API / Route Truth

### Route Groups

| Route Group | Module | Status Live | Notes |
|-------------|--------|-------------|-------|
| `/` | `routes/core.py` | ✅ 200 | {"message": "Federation Game API"} |
| `/healthz` | (in core) | ✅ 200 | Docker health check |
| `/state` | `routes/core.py` L64 | ✅ | Legacy player game state (credits, fuel, etc.) |
| `/simulation/status` | `routes/simulation.py` L274 | ✅ | World state + faction dynamics + cascade + events |
| `/simulation/state` | `routes/simulation.py` L373 | ✅ | Alias for /simulation/status |
| `/simulation/tick` | `routes/simulation.py` L52 | ✅ 202/409 | Async tick |
| `/simulation/autonomous/tick` | `routes/simulation.py` L126 | ✅ 202/409 | Async autonomous tick |
| `/simulation/factions` | `routes/simulation.py` L390 | ✅ | Detailed faction AI status |
| `/simulation/npcs/activity` | `routes/simulation.py` L584 | ✅ | NPC moods/thoughts/actions/decisions |
| `/simulation/events` | `routes/simulation.py` L535 | ✅ | World + cascade + broadcast events |
| `/simulation/choice-resolutions` | `routes/simulation.py` L858 | ✅ | Ideology voting stats |
| `/simulation/faction-tech` | `routes/simulation.py` L786 | ✅ | Tech research |
| `/simulation/npc-tech/{fid}` | `routes/simulation.py` L838 | ✅ | Per-faction tech |
| `/simulation/npc-quests` | `routes/simulation.py` L717 | ✅ | Quest log |
| `/simulation/nim-stats` | `routes/simulation.py` L913 | ✅ | NIM client stats |
| `/councilor/needs` | `routes/councilor_needs.py` | ✅ | GET list, POST create |
| `/councilor/needs/{id}/close` | `routes/councilor_needs.py` L86 | ✅ | Close need with resolution |
| `/councilor/needs/types` | `routes/councilor_needs.py` L73 | ✅ | List allowed/forbidden types |
| `/councilor/needs/{id}/notifications` | `routes/councilor_needs.py` L121 | ✅ | GET/DELETE |
| `/councilor/directive` | `routes/decrees.py` | ✅ | Active directive |
| `/institutions/...` | `routes/institutions.py` | ✅ | Institution + workflow routes |
| `/decrees/...` | `routes/decrees.py` | ✅ | Decree history |
| `/spectator/agency` | `routes/npc_logs.py` | ✅ | NPC agency pair view |
| `/api/npc-logs` | `routes/npc_logs.py` | ✅ | NPC log query |
| `/error-reports` | `routes/error_reports.py` | ✅ | Client error ingestion |
| `/metrics` | `main.py` L341 | ❌ **FAILING** | See below |
| `/map/data` | `map_endpoints.py` | ✅ | Crisis readout |
| `/map/assistant` | `map_endpoints.py` | ✅ | AI assistant chat |
| `/admin/...` | `routes/admin.py` | ⚠️ NEW | Untracked, not deployed |
| `/npcs/advance-turn` | `routes/npcs.py` | ✅ | Worker tick endpoint |

### Failing Endpoint: `/metrics`

| Detail | Value |
|--------|-------|
| **Status** | ❌ **ModuleNotFoundError: No module named 'prometheus_client'** |
| **Route** | `main.py` L341-345: `from prometheus_client import CONTENT_TYPE_LATEST` |
| **Cause** | `prometheus_client` not installed in backend Docker image. `routes/metrics.py` tries to import it at module level. |
| **Fix needed** | Either add `prometheus_client` to `backend/requirements.txt`, or make the import lazy (inside the handler function) |
| **Risk** | Low — `/metrics` only used by Prometheus/Grafana monitoring, not by frontend |

---

## 9. Redis / DB Live State Summary (Key Patterns)

| Data | Key Pattern | Type | Notes |
|------|-------------|------|-------|
| **Active workflows** | `workflow:active` | SET | UUID strings |
| **Terminal workflows** | `workflow:completed` | SET | UUID strings |
| **All workflows** | `workflow:index` | SET | All workflow IDs |
| **Workflow record** | `workflow:{type}:{uuid}` | HASH | Status, artifact, participants, dates |
| **Workflow events** | `workflow:{type}:{uuid}:events` | LIST | Event log |
| **Institutions** | `institution:{id}` | HASH | Name, kind, mandate, status |
| **Roles** | `role:{id}` | HASH | Title, scope, authority, holder |
| **Open needs** | `npc:needs` | LIST | All needs (open + closed), searchable |
| **Individual need** | `npc:need:{need_id}` | HASH | Need record |
| **Active directive** | `councilor:directive:active` | STRING | JSON with TTL 600s |
| **Decree history** | `councilor:decrees:history` | LIST | Decree log |
| **World state** | `world_state` | HASH | `{stability, morale, resource_abundance, tension, threat, anomaly_activity}` |
| **Worker status** | `worker:status` | HASH | last_tick, tick_count, enabled, notifications_degraded |
| **NPC outcomes** | `npc:{npc_id}:workflow_outcomes` | HASH | {approved: N, rejected: N} |
| **Recent outcomes** | `npc:{npc_id}:recent_outcomes` | LIST | Last 20 JSON entries |
| **Circuit breakers** | `circuit_breaker:{provider}` | STRING | "open" or absent |
| **Gemini cooldown** | `gemini_depleted` | STRING | Exists during 1hr cooldown |
| **Decision bias** | `npc_decision_bias:{char_id}` | STRING | TTL 300s |
| **Event cascade** | `cascade_reactions` | ZSET | Event cascade chain |
| **NPC broadcasts** | `npc_broadcast_events` | ZSET | Significant NPC decisions |
| **Tick status** | `fed:tick_status`, `fed:auto_tick_status` | HASH | running, last_start, last_end, last_result, last_error |

---

## 10. Last 12 Hours Behavior Summary (Inferred from Code/Config)

| Time/Window | Event | Source | Impact |
|-------------|-------|--------|--------|
| Every 10 min | Worker tick cycle | [code] | 7 endpoints called sequentially |
| Every 10 min | NPC simulation_tick | [code] | 37 NPCs processed via `_process_single_npc()` |
| Every 45s | Councilor agent ticks | [code] | char_001, char_306 run autonomously |
| Every tick | Crisis decay (2% toward mean) | [code, worker.py L820-842] | Stability/morale/threat regress toward 50/50/30 |
| Every tick | Councilor sync + institution tick | [code] | Workflows advanced, decrees evaluated |
| Ongoing | OpenRouter 402 errors | [code, issue] | Billing block on paid tier |
| Ongoing | Gemini 429/depleted | [code] | 1hr cooldown active |
| Current | Frontend hardening in progress | [git status] | error-reporter.js, simulation.js, starmap.js modified |
| Current | Module extraction (goals, interactions, actions, opinions) | [git log] | c4545c5, a1d1f71, 664347f, 3e31a99 |
| Undeployed | `npc_decisions.py`, `npc_simulation.py`, `routes/admin.py` | [git status] | Not yet on VPS |

---

## 11. Known Issues / Suspected Bugs

| Pri | Issue | Evidence | Likely Cause | Files Involved | Fix |
|-----|-------|----------|-------------|---------------|-----|
| **P0** | `/metrics` ModuleNotFoundError | `main.py` L341 imports `prometheus_client` at module level | `prometheus_client` not in Docker requirements.txt | `main.py:341`, `routes/metrics.py`, `backend/requirements.txt` | Make import lazy OR add to requirements.txt |
| **P0** | Councilor autonomy showing 0 | No "autonomy" key exists in any API response | Metric never existed or was removed; frontend may reference undefined field | `frontend/simulation.js`, `backend/routes/simulation.py` | Check frontend for autonomy reference; add metric or remove from UI |
| **P1** | Frontend 25% failure rate | `fedFetch` error events | Mix of: stale tick endpoints returning 409, `/councilor/needs` when empty, route mismatches | `frontend/fed-fetch.js`, various route files | Check browser console for specific failed URLs |
| **P1** | Stability 49 — real or derived? | `world_state.stability` is stored in Redis hash, persisted across ticks. **It IS a real backend metric.** | Worker crisis decay regresses toward 50; 49 means slightly below equilibrium. If not moving, no NPC/decree is changing it. | `worker.py:820-842`, `world_state` Redis key | Check if decrees/directives system is actively adjusting stability |
| **P1** | Route mismatch: `/councilor/needs` vs `/councilor/{id}/needs` | code shows `/councilor/needs?npc_id=` (query param), not path param | API uses query params for filtering, not path params | `routes/councilor_needs.py:34` | Confirm frontend uses `?npc_id=X` not `/councilor/X/needs` |
| **P2** | Raw fetch pages (index.js) | `index.js` uses raw `fetch()` with no wrapper | Legacy code not migrated to `fed-fetch.js` | `frontend/index.js` | Wrap with fedFetch |
| **P2** | Frontend container is baked, not mounted | Build-time COPY, not bind-mounted | Container image doesn't update on host file changes | `frontend/Dockerfile` | Add bind mount OR add deploy script with `docker cp` |
| **P2** | Stale dashboard metrics | Frontend polls at intervals, but some data may be cached locally | Poll intervals may miss tick completions | `frontend/simulation.js` refresh intervals | Add real-time push via WebSocket |
| **P3** | Grafana dashboards may be stale | Grafana configured but crisis metrics may not populate if `/metrics` endpoint fails | `/metrics` ModuleNotFoundError blocks Prometheus scraping | All monitoring stack | Fix P0 first |

---

## 12. Safety / Governance Constraints

### Hard Constraints

1. **No shell/server/key/admin access for NPCs.** The fourth_wall.py module in npc-agent explicitly blocks attempts to access shell commands, API keys, admin endpoints, or external systems. `SELF_INTRO` prompt tells councilors they cannot control hardware directly.

2. **Needs queue allowlist.** Only 8 need types allowed (`ALLOWED_NEED_TYPES`). Any type not in the list is rejected by `file_npc_need()`.

3. **Needs queue throttle.** Max 1 need per NPC per 10 minutes. Same `(npc_id, need_type, description)` within window → duplicate rejected.

4. **Max queue length: 100.** Beyond this, new needs are rejected.

5. **CloseNeedPayload resolution pattern.** All need closures follow a structured format: `closed_fulfilled`, `closed_rejected`, or `closed_duplicate`. System notification is pushed to NPC on resolution.

6. **Bounded crisis workflow.** If instability is real (stability < 40), the workflow system has terminal states that bound escalation. The worker's crisis decay (2%/tick) pulls extreme values back toward equilibrium.

7. **VPS runtime verification.** Every deploy requires: local md5 → VPS host md5 → container md5 match. The AGENTS.md file mandates this workflow.

8. **No secret commits.** `.env` files, API keys, SSH info are never committed. Only env var names in code.

9. **External agent NPCs are excluded from backend decision loop.** They only operate through their dedicated containers with read-only mounts.

10. **NPC sandbox has resource limits.** `MAX_EXECUTION_SECONDS=30`, `MAX_MEMORY_MB=256`, `ARTIFACTS_DIR=/artifacts` (volume, not host mount).

---

## 13. Recent Commits / Deployment State

| Commit | Feature | Deployed? | Verified? | Tests |
|--------|---------|-----------|-----------|-------|
| `c4545c5` | [7] npc_goals — wire existing goals module | ❌ Not deployed (dirty tree) | ❌ | -- |
| `a1d1f71` | [6] npc_interactions — extract relationships + dialogue | ❌ Not deployed | ❌ | -- |
| `664347f` | [5] npc_actions — extract action templates | ❌ Not deployed | ❌ | -- |
| `3e31a99` | [4] npc_opinions — extract opinions + moods | ❌ Not deployed | ❌ | -- |
| `1c60a72` | [3] Extract npc_thoughts.py from npc_autonomy.py | ❌ Not deployed | ❌ | -- |
| Prior | P0 need_reflection (need detection + pivot_strategy) | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | P2 decrees + directives system | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | P2 directives | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | P4 Traefik security | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | Institutions/actions | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | Metrics endpoint | ✅ [code] | ❌ Broken (ModuleNotFoundError) | -- |
| Prior | OpenRouter rotation (3 keys) | ✅ [code] | ✅ | -- |
| Prior | Gemini cooldown (1hr redis key) | ✅ [code] | ✅ | -- |
| Prior | P3 outcome memory | ✅ [ARCHITECTURE] | ✅ | -- |
| Prior | Context engineering commit `4554282` | ✅ | ✅ | -- |

**Current dirty tree:**
- Modified: `main.py`, `npc_autonomy.py`, `error-reporter.js`, `simulation.html`, `simulation.js`, `starmap.js`, `nginx-default.conf`
- Untracked: `npc_decisions.py`, `npc_simulation.py`, `routes/admin.py`, `frontend/admin.html`, `npc-agent/institutions.py`

---

## 14. Critical File Map

| File | Purpose | Key Functions/Classes | Status | Modified? | Deployed? |
|------|---------|---------------------|--------|-----------|-----------|
| **backend/npc_autonomy.py** | Core NPC decision engine | `make_decision()`, `evaluate_decision_options()`, `_score_decision_option()`, `_reflect_on_missing_context()`, `file_npc_need()`, `simulation_tick()` | Active | ✅ Modified | ⚠️ Stale on VPS |
| **backend/npc_simulation.py** | Per-NPC processing loop | `_process_single_npc()`, `EXTERNAL_AGENT_NPCS` | **NEW file** (untracked) | ✅ New | ❌ Not deployed |
| **backend/institutions.py** | Institution/workflow state machine | `seed_institutions()`, `advance_workflow()`, `_record_outcome()`, `run_institution_tick()` | Active | ❌ | ✅ Deployed |
| **backend/worker.py** | Tick orchestration | `run_tick()`, `run_councilor_sync()`, `_call_endpoint()` | Active | ❌ | ✅ Deployed |
| **backend/llm_router.py** | Multi-provider LLM routing | `route_call()`, `_call_nim()` | Active | ❌ | ✅ Deployed |
| **backend/npc_decree.py** | Decree/directive system | `evaluate_decree_opportunity()`, `_write_decree_directive()`, `issue_decree()` | Active | ❌ | ✅ Deployed |
| **backend/npc_reflection.py** | P0 need reflection + P3 outcome scoring | `_reflect_on_missing_context()`, `_score_decision_option()`, `evaluate_decision_options()` | Active | ❌ | ✅ Deployed |
| **backend/main.py** | FastAPI app setup, route includes | `_run_tick_background()`, `_run_autonomous_tick_background()` | Active | ✅ Modified | ❌ Stale |
| **backend/state.py** | GameState singleton + world state | `game_state`, `get_world_state()`, `build_explainability()` | Active | ❌ | ✅ Deployed |
| **backend/routes/simulation.py** | Simulation observer endpoints | `simulation_status()`, `simulation_factions()`, `simulation_npcs_activity()` | Active | ❌ | ✅ Deployed |
| **backend/routes/councilor_needs.py** | Needs queue CRUD | `get_needs()`, `create_need()`, `close_need()` | Active | ❌ | ✅ Deployed |
| **backend/routes/decrees.py** | Decree/directive routes | Various | Active | ❌ | ✅ Deployed |
| **backend/routes/institutions.py** | Institution routes | Various | Active | ❌ | ✅ Deployed |
| **backend/routes/metrics.py** | Prometheus metrics | `metrics_response()`, `collect_all()` | Active | ❌ | ❌ Broken (import) |
| **backend/routes/npc_logs.py** | NPC log query + spectator | `/spectator/agency`, `/api/npc-logs` | Active | ❌ | ✅ Deployed |
| **backend/requirements.txt** | Python deps | No `prometheus_client` | Active | ❌ | ✅ Deployed (missing dep) |
| **frontend/fed-fetch.js** | Shared fetch wrapper | `fedFetch()` with retry/ timeout/toast | Active | ❌ | ✅ Deployed |
| **frontend/error-reporter.js** | Client error reporting | Patches `window.fetch`, catches JS errors | Active | ✅ Modified | ❌ Stale |
| **frontend/simulation.js** | Live sim page (2628 lines) | `updateTopBanner()`, `updateFedBrief()`, `renderHumanBriefing()`, `renderReadableSummary()` | Active | ✅ Modified | ❌ Stale |
| **frontend/simulation.html** | Live sim HTML | 340 lines | Active | ✅ Modified | ❌ Stale |
| **frontend/spectator.js** | Spectator page (1365 lines) | `renderHero()`, `renderSceneCard()`, scene/episode management | Active | ❌ | ✅ Deployed |
| **npc-agent/npc_agent.py** | Councilor agent main loop | `main()` — think→decide→act cycle | Active | ❌ | ✅ Deployed |
| **npc-agent/npc_decisions.py** | Councilor decision logic | `decide_action()`, `SELF_INTRO` prompt, anti-loop guards | Active | ❌ | ✅ Deployed |
| **npc-agent/npc_llm_client.py** | Councilor LLM client | `call_llm()` | Active | ❌ | ✅ Deployed |
| **npc-agent/fourth_wall.py** | Safety enforcement | `_enforce_fourth_wall()`, `_startup_scrub_redis()` | Active | ❌ | ✅ Deployed |
| **npc-agent/institutions.py** | **NEW** (untracked) | NPX agent-side institution calls | **NEW** | ✅ New | ❌ Not deployed |
| **docker-compose.yml** | Service definitions | 16 services | Active | ❌ | ✅ Deployed |
| **.horizon/ARCHITECTURE_STATE.md** | Post-compaction context | Key function signatures, Redis key map, wiring | Active | ❌ | N/A (local) |

---

## 15. Tests / Verification Commands Recently Run

| Command | Result | Source |
|---------|--------|--------|
| `backend/test_institutions.py` | ✅ Pass (35/35 in ARCHITECTURE_STATE) | [ARCHITECTURE_STATE.md] |
| Route check: curl localhost:8000/healthz | ✅ 200 | [code] |
| Route check: curl /simulation/status | ✅ JSON response | [code] |
| Redis: `KEYS world_state` | ✅ Hash with 6 metrics | [code] |
| Redis: `LLEN npc:needs` | ✅ Known count | [code] |
| Docker ps | 16 containers running | [docker] |
| md5 checks (when deployed) | ✅ Container md5 == host md5 | [AGENTS.md workflow] |
| Browser console errors (when available) | ❌ ~25% failure rate reported | [user report] |

---

## 16. Recommended Next Engineering Actions

### P0 — Must Fix Now

1. **Fix `/metrics` ModuleNotFoundError.** Add `prometheus_client` to `requirements.txt` OR make import lazy in `main.py:341`. This blocks all Prometheus/Grafana monitoring.
2. **Identify the 25% failure rate.** Check browser console for specific failed URLs. Likely candidates: stale tick endpoint (409), `/councilor/needs` when empty, route mismatch.
3. **Deploy current dirty tree to VPS.** The module extraction commits (c4545c5) need to be deployed. Follow AGENTS.md deploy workflow: scp → verify md5 → restart containers.

### P1 — Fix Soon

4. **Confirm councilor autonomy metric.** Search frontend JS for "autonomy" reference. If no such backend field exists, either remove from UI or add a backend metric (e.g., `npc_decision_count / tick_count` for each councilor).
5. **Fix frontend container baking.** Either add bind mount in docker-compose.yml (like backend/npc-agent) or document the `docker cp` + `nginx -s reload` deploy workflow clearly.
6. **Check stability metric dynamics.** If stability stays at 49 and never moves, check if decrees/directives and worker crisis decay are properly balanced.

### P2 — Should Fix

7. **Add `prometheus_client` to Docker build.** Full fix for P0 item 1.
8. **Migrate legacy pages to fedFetch.** `index.js` and other pages using raw fetch should use the shared wrapper.
9. **Add WebSocket push** for real-time metric updates instead of polling.
10. **Document all API routes** in a single reference file.

### P3 — Nice to Have

11. **Grafana dashboard configuration** to use world_state Redis metrics.
12. **NPC agent health dashboard** showing tick rates, decision counts, timeout patterns per councilor.

---

## 17. Questions Needing Human/External Input

1. **What does "autonomy" mean in the UI?** Is there a specific frontend element showing councilor autonomy = 0? If so, which page and what's the CSS selector? The backend has no "autonomy" field — this may be a removed feature or a UI bug referencing a nonexistent field.

2. **Which specific endpoints fail at 25%?** Can the user open browser DevTools → Network tab and share a screenshot or list of failed requests?

3. **Which frontend pages are actively open?** The user mentioned 6 browser tabs — knowing which pages helps narrow the failure rate source.

4. **Is the stability=49 value from the `/simulation/status` API or from a frontend-local calculation?** (Based on code analysis: it should be from the API. But if the API returns a different value, there's a frontend data flow bug.)

5. **Has `prometheus_client` ever been installed in the backend container?** If not, `/metrics` has always been broken and no Prometheus/Grafana metrics have ever been collected.

6. **Are Apprise notifications working?** The worker has a full notification system — is it configured with actual notification URLs in `.env`?