# Agent File Ownership Map
**Last Updated:** 2026-06-07

## Active Agents

| Agent | Role | Status |
|-------|------|--------|
| GLM-5.1 (OpenCode build) | Primary coding agent | Active — build mode |
| NEM 3 Ultra (OpenCode plan) | Horizon tracking + spatial fix | Active — plan mode, switching to build for spatial |
| Wave AI (Wave Terminal) | Monitor, coordination, SSH fixes | Active |
| Codex (GPT-5.4) | Previous session — race fix + frontend tabs | Done — session ended |

## File Ownership

### GLM-5.1 Owns (can modify freely)
- `federation-game/backend/state.py`
- `federation-game/backend/state_constants.py`
- `federation-game/backend/state_helpers.py`
- `federation-game/backend/federation_game_db.py`
- `federation-game/backend/routes/core.py`
- `federation-game/backend/routes/events.py`
- `federation-game/backend/routes/npcs.py`
- `federation-game/backend/map_endpoints.py`
- `federation-game/backend/tick_engine.py`
- `federation-game/backend/worker.py`
- `federation-game/backend/alembic/`
- `federation-game/docker-compose.yml`
- `session/bridge/` plan packs (plan mode only — writes, doesn't execute)

### NEM 3 Ultra Owns (can modify freely)
- `federation-game/frontend/starmap.js`
- `federation-game/frontend/starmap.html`
- `federation-game/frontend/starmap.css`
- `session/bridge/` execution (build mode only — reads plan packs, writes code)

### Wave AI Owns
- `.horizon/` (maintains status, decisions, ownership docs)
- `~/.ssh/config` (local fixes only)

### Shared (coordinate before modifying)
- `federation-game/frontend/index.js` — GLM added stale-choice recovery, NEM needs choice_token integration
- `federation-game/backend/routes/simulation.py` — GLM owns backend, but spatial state affects frontend
- `federation-game/backend/spatial_state.py` — GLM owns, NEM reads for spatial mode logic

### Avoid (other agent's territory)
- GLM should NOT modify starmap.js/html/css during NEM's spatial fix
- NEM should NOT modify backend route files during GLM's work sessions

### Not Owned (anyone can touch)
- `AGENTS.md`
- `README.md`
- `.horizon/` (Horizon agent maintains)
- `continuity-test-handoff/`
- `docs/`

## Conflict Resolution

1. **If two agents need the same file:** Human decides priority
2. **If an agent modifies an owned file:** Check `.horizon/HORIZON_STATUS.md` first
3. **If ownership needs to transfer:** Update this file, notify human
