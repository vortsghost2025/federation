# Federation Simulation Monitoring & Observability System

**Date:** 2026-05-25
**Status:** Approved
**Author:** Kilo (orchestrator) + Sean

---

## Purpose

The Federation simulation runs with almost no automated oversight. Ticks stall silently, LLM providers fail silently, circuit breakers trip without anyone knowing. This system deploys Polecat watchdogs that continuously monitor simulation health and route alerts through Gastown to Sean.

## Architecture

```
SIMULATION (VPS)              GASTOWN                  SEAN
+------------------+     +------------------+     +----------+
| Backend          |     | Coordinator      |     |          |
| Worker           |--healthz-->|           |     | Dashboard|
| Redis            |--keys---->| Routes    |--alert--->| You    |
| LLM Router       |--status-->| alerts to |     | decide   |
| Containers       |--ps------>| you       |     |          |
+------------------+     +------------------+     +----------+
        ^                        ^
        |                        |
   +----+-----------+            |
   | POLECATS       |            |
   | (Watchdogs)    |            |
   | Tick Watchdog  |---alert--->+
   | LLM Monitor    |---alert--->+
   | Async Timeout  |---alert--->+
   | Deploy Verify  |---alert--->+
   +----------------+
```

## 4 Watchdog Beads

### Bead 1: Tick Watchdog

**Frequency:** Every 60 seconds
**What it checks:**
- `curl https://federation-game.deliberatefederation.cloud/healthz` — expect HTTP 200
- Redis `worker:status` hash — tick_count field should increment between checks
- Redis connectivity — `redis-cli PING` should return PONG

**Alert conditions:**
- `/healthz` returns non-200 or times out (5s timeout) → CRITICAL: "Backend health check failed"
- Tick count unchanged for 2+ consecutive checks (2+ minutes) → CRITICAL: "Simulation stalled — tick not advancing"
- Redis PING fails → CRITICAL: "Redis unreachable"

**Alert detail includes:**
- Last known tick count and timestamp
- HTTP status code received
- Redis connection status

### Bead 2: LLM Health Monitor

**Frequency:** Every 5 minutes
**What it checks:**
- All `llm_circuit_breaker:*` keys in Redis — any active breakers
- All `llm_errors:*` ZSETs — count of errors in last hour
- Ollama reachability at `100.95.92.117:11434` via Tailscale

**Alert conditions:**
- Any `llm_circuit_breaker:{provider}` key exists → WARNING: "LLM provider [provider] circuit breaker tripped — on 5-min cooldown"
- Error count > 5 in last hour for any provider → WARNING: "LLM provider [provider] elevated error rate: [N] errors/hr"
- Ollama unreachable (TCP connect timeout) → WARNING: "Ollama unreachable at 100.95.92.117:11434 — local LLM down"
- All providers in circuit breaker simultaneously → CRITICAL: "All LLM providers in circuit breaker — simulation running on template fallback only"

### Bead 3: Async Endpoint Timeout Watcher

**Frequency:** Every 90 seconds
**What it checks:**
- `GET /simulation/autonomous/status` — check if async tick is still running
- If possible, `GET /simulation/tick` status

**Alert conditions:**
- Async autonomous_tick running longer than 90s → WARNING: "Async autonomous_tick may be hung — running for [N]s"
- Async simulation_tick running longer than 60s → WARNING: "Async simulation_tick may be hung — running for [N]s"
- Status endpoint returns error → CRITICAL: "Cannot reach async status endpoint"

### Bead 4: Deployment Verifier

**Frequency:** Triggered (runs after any deploy, not on a schedule)
**What it checks:**
- `curl https://federation-game.deliberatefederation.cloud/healthz` — expect 200
- `docker compose ps` via shell.js — all containers should show healthy/running
- `docker compose logs --tail=20 backend` — no new Python tracebacks since deploy

**Alert conditions:**
- `/healthz` returns non-200 after deploy → CRITICAL: "Post-deploy health check failed"
- Any container not running/healthy → CRITICAL: "Container [name] not healthy after deploy"
- New Python tracebacks in backend logs → WARNING: "Backend errors after deploy: [first error line]"

**Also reports success:**
- All checks pass → INFO: "Deploy verified — all systems nominal"

## Alert Format

Every alert follows this structure:

```
[WATCHDOG] [SEVERITY] [SOURCE]
What: one-line plain English description
When: ISO 8601 timestamp
Detail: what the Polecat found (numbers, keys, status codes)
Action: what you could do about it
```

### Severity Levels

| Level | Meaning | Example |
|-------|---------|---------|
| CRITICAL | Simulation broken or degraded right now | Backend down, tick stalled, all LLM providers failed |
| WARNING | Something concerning that could become critical | One LLM provider tripped, elevated error rate |
| INFO | Normal status confirmation | Deploy verified, all systems nominal |

### Example Alerts

```
[TICK-WATCHDOG] [CRITICAL] [worker:status]
What: Simulation stalled — tick not advancing
When: 2026-05-25T21:45:00Z
Detail: Last tick was 3 minutes ago. Tick count unchanged at 1847.
Action: Check `docker compose logs --tail=50 worker` and consider restarting worker container

[LLM-MONITOR] [WARNING] [llm_circuit_breaker:ollama]
What: Ollama circuit breaker tripped — on 5-min cooldown
When: 2026-05-25T21:47:30Z
Detail: 3 consecutive failures. Fallback to Cloudflare Workers active.
Action: Check Ollama at 100.95.92.117:11434. Clear with: redis-cli DEL llm_circuit_breaker:ollama

[DEPLOY-VERIFY] [INFO] [post-deploy]
What: Deploy verified — all systems nominal
When: 2026-05-25T22:00:15Z
Detail: /healthz=200, all containers running, no new errors in backend logs
Action: None needed
```

## Implementation Plan

### Files to Create (new only, zero modifications to existing code)

1. **`monitor.py`** — Python monitoring script deployed to VPS at `/docker/federation-game/monitoring/`
   - Connects to Redis on Docker network (`redis:6379`)
   - Hits health endpoints via `localhost:8000` (internal, no HTTPS overhead)
   - Reads watchdog Redis keys
   - Outputs structured alerts to stdout
   - Exit code 0 = all clear, 1 = warning, 2 = critical

2. **`watchdog_tick.sh`** — Runs tick + async timeout checks, calls monitor.py with `--check tick`
   - Scheduled via cron or systemd timer on VPS

3. **`watchdog_llm.sh`** — Runs LLM health checks, calls monitor.py with `--check llm`
   - Scheduled via cron or systemd timer on VPS

4. **`watchdog_deploy.sh`** — Runs post-deploy verification, calls monitor.py with `--check deploy`
   - Called manually or from deploy scripts after each deployment

### Polecat Bead Breakdown

**Convoy:** Federation Monitoring Tier 1
**Rig:** 3a7ffdcb-636d-4074-9f53-8c26fc167cb1
**Parallel:** No — sequential beads with dependencies

**Bead 1:** Read simulation backend to understand Redis key patterns, endpoint paths, and container names
- Depends on: nothing
- Output: documented list of all keys/endpoints the monitor needs

**Bead 2:** Write `monitor.py` — the core monitoring script
- Depends on: Bead 1 (needs the key/endpoint list)
- Scope: Python script with argparse for --check (tick|llm|async|deploy), Redis connection, HTTP requests, structured alert output

**Bead 3:** Write shell wrapper scripts (`watchdog_tick.sh`, `watchdog_llm.sh`, `watchdog_deploy.sh`)
- Depends on: Bead 2 (needs monitor.py to exist)
- Scope: Simple bash wrappers that call monitor.py and pipe output

**Bead 4:** Deploy monitoring scripts to VPS and set up cron schedules
- Depends on: Bead 3 (needs all scripts written)
- Scope: SCP files to VPS, configure cron, verify first run

**Bead 5:** Test all 4 watchdogs — simulate failure conditions and verify alerts
- Depends on: Bead 4 (needs monitoring running on VPS)
- Scope: Stop a container, check a circuit breaker key, verify alerts fire correctly

## What This Does NOT Touch

- Zero modifications to simulation backend Python files
- Zero modifications to worker.py
- Zero modifications to existing frontend HTML
- Zero modifications to docker-compose.yml
- Monitor scripts are additive — new files in a new directory only
- Existing Telegram notifications continue unchanged
- Gastown integration is via Polecat alerting to Gastown messages (read-only from sim)

## Future Extensions (not in this spec)

These are documented so we remember them, but NOT in scope for Tier 1:

1. **Self-Healing Mode** — Polecats auto-restart containers, reset circuit breakers on CRITICAL alerts
2. **Live Narration** — Polecat reads `narration:latest` + `/map/data` and produces story prose for Sean
3. **Story Archive** — Persist `narration:history` to PostgreSQL before the 500-entry Redis cap drops old entries
4. **Quality Assurance** — Audit NPC behavior coherence, story arc consistency, LLM response quality
5. **Tick Latency Tracking** — Histogram of how long each tick takes end-to-end
6. **NPC Behavior Audit** — Log NPC decisions + thoughts to persistent store for review
7. **Cascade Visualization** — Build cascade graph from `cascade_chains` Redis data
8. **LLM Cost Tracking** — Add token counting and per-provider cost estimation

## Key VPS Reference

- **Public IP:** 187.77.3.56
- **Backend:** localhost:8000 (internal), federation-game.deliberatefederation.cloud (external)
- **Redis:** redis:6379 on Docker network
- **Docker compose path:** /docker/federation-game/
- **Frontend HTML:** /docker/federation-game/public_html/
- **Backend Python:** /docker/federation-game/backend/
- **Monitoring (new):** /docker/federation-game/monitoring/
