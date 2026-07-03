# Agent File Ownership Map
**Last Updated:** 2026-07-03
**Updated By:** GLM-5.2 (z-ai orchestrator)

## Active Agents

| Agent | Role | Status |
|-------|------|--------|
| GLM-5.2 (z-ai orchestrator) | Primary orchestrator — code review, dispatch, horizon tracking, deploy-gate verification | Active — build mode |
| NEM 3 Ultra (OpenCode build) | Frontend + spatial — starmap, visual scale, executes plan packs | Active — build mode (was previously misdocumented as "plan mode") |
| Wave AI (Wave Terminal) | Monitor, coordination, SSH fixes — historical; status uncertain since 2026-06-28 | ⚠ Possibly inactive — verify before assigning work |
| Codex (GPT-5.4) | Previous session — race fix + frontend tabs | Done — session ended |

## Mode Discipline (REFRESHED 2026-07-03)

- The previous "Plan mode = GLM, Build mode = Nemotron" split is **depicrated**. GLM 5.2 (current orchestrator) operates as a subagent-dispatching orchestrator and can both plan and build.
- The previous "GLM must delegate ALL tool calls" rule is **partially retained** — orchestrator-level bash (scp, md5, diff, git log) stays in the main shell; subagents used for fanout of read/grep/edit operations to spread rate-limit pressure.
- The 18-subagent model execution pool routes primitives to **specialist types** (`explore`, `code-reviewer`, `docs-specialist`, `frontend-specialist`, `debug`, `test-engineer`, `code-simplifier`, `code-skeptic`, `researcher`, `plan`, `ask`). **`general` subagent type = orchestrator's own model (GLM 5.2) — avoid for routine dispatch to prevent self-taxing the rate budget.**
- Per-wave dispatch limits tuned adaptively: cross-agent parallelism more effective than intra-agent parallelism. Aim for 1 subagent : 1 tool call for primitives, 1 subagent : 1 file-pair for diffs.

## File Ownership

### GLM-5.2 Owns (can modify freely)
- `.horizon/` (maintains HORIZON_STATUS, DECISIONS, AGENT_OWNERSHIP, ARCHITECTURE_STATE, DELTA_LOG)
- (Historical backend ownership from GLM-5.1 carried forward as GLM-5.2:)
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
- `session/bridge/` plan packs (orchestrator can plan + delegate builds, does NOT necessarily self-execute)

### NEM 3 Ultra Owns (can modify freely)
- `federation-game/frontend/starmap.js`
- `federation-game/frontend/starmap.html`
- `federation-game/frontend/starmap.css`
- `session/bridge/` execution (build mode — reads plan packs, writes code)

### Wave AI Owns (status uncertain)
- `~/.ssh/config` (local fixes only)
- (`.horizon/ maintenance now owned by GLM-5.2; previously attributed to Wave AI but Wave AI hasn't been active since ~2026-06-28)

### Shared (coordinate before modifying)
- `federation-game/frontend/index.js` — historical GLM+stale-choice-recovery / NEM choice_token integration
- `federation-game/backend/routes/simulation.py` — GLM owns backend, spatial state affects frontend
- `federation-game/backend/spatial_state.py` — GLM owns, NEM reads for spatial mode logic
- `federation-game/backend/npc_autonomy.py` — ⚠ CURRENTLY DIVERGED home↔VPS. Before ANY deploy, must be coordinated atomically with the 11 sibling modules (npc_needs/world/decree/reflection/thoughts/opinions/actions/interactions/goals + npc_decisions/context/llm_client). See HORIZON_STATUS Known Issues #8.
- `federation-game/backend/llm_router.py` — P007 Edit 2 (cooldown constants + `_set_cooldown`) pending. See HORIZON_STATUS Known Issues #9.

### Avoid (other agent's territory)
- GLM-5.2 should NOT modify starmap.js/html/css during NEM build sessions
- NEM 3 Ultra should NOT modify backend route files during orchestrator-led backend work

### Not Owned (anyone can touch)
- `AGENTS.md`
- `README.md`
- `continuity-test-handoff/`
- `docs/`

## Conflict Resolution

1. **If two agents need the same file:** Human (Sean) decides priority
2. **If an agent modifies an owned file:** Check `.horizon/HORIZON_STATUS.md` first
3. **If ownership needs to transfer:** Update this file, notify Sean
4. **If GLM-5.2 (orchestrator) feels the rate wall (32-cap or 429):** delegate the primitive to a specialist subagent, do NOT fanout multiple tool calls inside one `general` invocation — that self-taxes the orchestrator's model.
