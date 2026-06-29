# FEDERATION REFACTORING JOURNAL

**Purpose:** Survival log for multi-session monolith breakup. Every step is dated, timestamped, and marked so any agent can pick up where the last one left off — even after compaction or session switch.

**Rules:**
1. NEVER delete entries. Append only.
2. Every step gets: `[ISO timestamp]` + `STATUS` (PLANNED|IN_PROGRESS|DONE|ROLLED_BACK|BLOCKED)
3. Every step records: what changed, what files touched, md5 hashes, git commit if any
4. If a step is ROLLED_BACK, the next agent knows to NOT re-attempt without new instructions
5. A step is only DONE when verified on VPS (host + container md5 match)
6. The "Current State" section at top is ALWAYS updated after each step — this is the single source of truth

---

## CURRENT STATE (read this first after compaction)

**Last updated:** 2026-06-29T16:45:00Z
**Phase:** Phase 1 in progress — [1.3] npc_llm_client.py extracted and deployed live

### What's safe to touch right now
- `npc-agent/npc_agent.py` — 2148 lines (down from 2356); imports from `npc_redis_helpers` + `fourth_wall` + `npc_llm_client`
- `npc-agent/npc_llm_client.py` — **NEW** 216 lines; call_llm, _api_key_for_model, _call_openrouter_free, all LLM constants (OR_FREE_POOL, MODEL_ENABLE_THINKING, etc.)
- `npc-agent/npc_redis_helpers.py` — 653 lines; all Redis CRUD helpers, session log, thread, question similarity, pair workspace, LLM logging
- `npc-agent/fourth_wall.py` — standalone, 18 fourth-wall regex rules, deployed live
- `backend/npc_autonomy.py` — fully functional, deployed, verified
- `scripts/Deploy-VpsFile.ps1` — new, verified
- `scripts/redis-summary.sh` — new, verified (3947 keys, 0 leaks)
- `docker-compose.yml` — frontend bind mount added

### What NOT to touch
- `backend/institutions.py` — shared dependency, changes propagate everywhere
- `.env` on VPS — API keys, never edit without Sean
- `backend/federation_game_npcs.py` / `npcs.py` — DIFFERENT, not yet analyzed
- `backend/federation_game_state.py` / `state.py` — DIFFERENT, not yet analyzed
- `backend/federation_game_timeline.py` / `timeline.py` — DIFFERENT, not yet analyzed

### Current deployed hashes (VPS)
```
npc-agent/npc_agent.py: 3bb68be10e908d6036d9b5704e52a9fe (2148 lines, imports from 3 submodules)
npc-agent/npc_llm_client.py: 9648adae8fd4f932d7dac7f424f0558f (NEW — 216 lines)
npc-agent/npc_redis_helpers.py: 69493966ae0dc045de166f8f5e02fd8d (653 lines)
npc-agent/fourth_wall.py: c9426f31 (deployed, verified)
backend/npc_autonomy.py: ae3475ac (stale — needs re-hash after P0 decree work)
```

### Known duplicates — resolved
| Pair | Lines | Status |
|------|-------|--------|
| `federation_game_factions.py` / `factions.py` | 1,602 | RESOLVED — shim re-exports from `factions.py` |
| `federation_game_quests.py` / `quests.py` | 1,063 | RESOLVED — shim re-exports from `quests.py` |
| `federation_game_technology.py` / `technology.py` | 1,709 | RESOLVED — shim re-exports from `technology.py` |
| `federation_game_npcs.py` / `npcs.py` | ~1,700 | DIFFERENT — needs analysis |
| `federation_game_state.py` / `state.py` | ~1,700 | DIFFERENT — needs analysis |
| `federation_game_timeline.py` / `timeline.py` | ~1,800 | DIFFERENT — needs analysis |

### VPS backups cleaned
Removed 17 stale `.bak`/`.backup` files from `/docker/federation-game/npc-agent/`

---

## REFACTORING PLAN

### Phase 0: Infrastructure (before any code changes)
- [0.1] PowerShell deploy script (`Deploy-VpsFile.ps1`) **— DONE, live test passed**
- [0.2] Redis summary command (`redis-summary.sh`) **— DONE, live test passed (3947 keys, 0 leaks)**
- [0.3] Extend `fed-state.sh --vps` with Redis stats **— DONE**
- [0.4] Merge `npc_agent_current.py` → `npc_agent.py` **— DONE, _current deleted, deploy script updated**
- [0.5] Eliminate duplicate backend files **— PARTIAL (3 identical pairs shimmed, 3 different pairs pending)**
- [0.6] Frontend bind mount in docker-compose.yml **— DONE, verified live (host=container md5 match)**

### Phase 1: Break `npc_agent.py` (2,970 lines → ~6 modules)
Planned module structure:
```
npc-agent/
  npc_agent.py          # main() + tick loop (~200 lines)
  fourth_wall.py        # _FOURTH_WALL_REPLACEMENTS, _enforce_fourth_wall, _startup_scrub_redis (~80 lines)
  npc_llm_client.py     # LLM routing, fallback chain, circuit breaker, OR free pool (~400 lines)
  npc_context.py        # think_about_world(), neighborhood, cosmic horizon (~300 lines)
  npc_decisions.py      # decide_action(), parse_decision(), anti-loop guards (~500 lines)
  npc_actions.py        # execute_decision(), all action handlers (~700 lines)
  npc_redis_helpers.py  # get_redis, message CRUD, session log, thread helpers (~400 lines)
  institutions.py       # already separate (14KB)
```

Steps (each is a single commit + deploy + verify):
- [1.0] Create empty module files with imports + exports, verify no breakage
- [1.1] Extract `fourth_wall.py` — smallest, zero dependencies
- [1.2] Extract `npc_redis_helpers.py` — depends on nothing but redis
- [1.3] Extract `npc_llm_client.py` — depends on redis helpers **— DONE, deployed live**
- [1.4] Extract `npc_context.py` — depends on redis helpers + fourth_wall
- [1.5] Extract `npc_decisions.py` — depends on context + llm client
- [1.6] Extract `npc_actions.py` — depends on decisions + redis helpers + fourth_wall
- [1.7] Verify full tick cycle works on VPS, all functions resolve

### Phase 2: Break `npc_autonomy.py` (3,392 lines → ~5 modules)
Planned module structure:
```
backend/
  npc_autonomy.py       # main entry + decision loop (~500 lines)
  npc_scoring.py         # _score_decision_option, decision weights (~600 lines)
  npc_needs.py           # needs queue, notifications, fulfilled types (~400 lines)
  npc_decree.py          # decree evaluation, directive writing (~300 lines)
  npc_reflection.py      # _reflect_on_missing_context, pivot logic (~300 lines)
```

Steps (each is a single commit + deploy + verify):
- [2.0] Create empty module files, verify no breakage
- [2.1] Extract `npc_needs.py`
- [2.2] Extract `npc_decree.py`
- [2.3] Extract `npc_reflection.py`
- [2.4] Extract `npc_scoring.py`
- [2.5] Verify full worker tick cycle works on VPS

### Phase 3: Other large files (lower priority)
- `simulation_engine.py` (2,441 lines)
- `federation_game_console.py` (2,205 lines)
- `llm_router.py` (1,907 lines)
- `federation_game_timeline.py` (1,800 lines)

---

## STEP LOG (append only)

### 2026-06-28T22:23:00Z — Journal created
STATUS: PLANNED
NOTES: This journal was created after identifying all friction points. No code changes made yet. Next step: get Sean's approval on plan, then start Phase 0.

### 2026-06-28T23:00:00Z — [0.1] Deploy-VpsFile.ps1 created
STATUS: DONE
FILES:
- NEW: `scripts/Deploy-VpsFile.ps1`
TARGETS: npc-agent, backend, docker-compose
WORKFLOW: syntax check → scp → md5 host → restart → md5 containers
VERIFIED: md5 `18ebf18a` returned from both agent-001 and agent-306 containers

### 2026-06-28T23:15:00Z — [0.2] redis-summary.sh created
STATUS: DONE
FILES:
- NEW: `scripts/redis-summary.sh`
VERIFIED: `bash scripts/redis-summary.sh --vps` → 3947 total keys, 0 fourth-wall leaks detected
FEATURES: prefix counts, inbox depths, leak scan

### 2026-06-29T00:10:00Z — [0.3] fed-state.sh --vps Redis stats
STATUS: DONE
FILES:
- MODIFIED: `scripts/fed-state.sh`
CHANGE: inline Redis summary (total keys, prefix counts) added to VPS section
CLEANUP: removed stale "deep probes not yet implemented" note

### 2026-06-29T07:55:00Z — [0.4] Merge npc_agent_current.py → npc_agent.py
STATUS: DONE
FILES:
- DELETED: `npc-agent/npc_agent_current.py`
- MODIFIED: `scripts/Deploy-VpsFile.ps1` — removed `_current`→runtime sync logic
- CLEANUP: removed 17 stale `.bak`/`.backup` files from VPS `/docker/federation-game/npc-agent/`
VERIFIED: `npc_agent.py` is now the single source of truth (md5 `18ebf18a`)
NOTE: `npc_agent.orig.py` kept (different hash, old version)

### 2026-06-29T07:58:00Z — [0.5] Eliminate duplicate backend files (partial)
STATUS: PARTIAL — 3 identical pairs resolved, 3 different pairs pending
FILES:
- MODIFIED: `backend/federation_game_factions.py` → re-export shim from `factions.py`
- MODIFIED: `backend/federation_game_quests.py` → re-export shim from `quests.py`
- MODIFIED: `backend/federation_game_technology.py` → re-export shim from `technology.py`
- SKIPPED: `federation_game_npcs.py`/`npcs.py` — DIFFERENT content (hashes differ)
- SKIPPED: `federation_game_state.py`/`state.py` — DIFFERENT content
- SKIPPED: `federation_game_timeline.py`/`timeline.py` — DIFFERENT content
DEPLOYED: scp to VPS, backend+worker restarted
VERIFIED: `docker exec federation-game-backend-1 python -c "import federation_game_factions; import federation_game_quests; import federation_game_technology; print('All 3 shims import OK')"` → success
BACKEND SMOKE: `curl` via frontend container → 200 on `/event`

### 2026-06-29T08:00:00Z — [0.6] Frontend bind mount
STATUS: DONE
FILES:
- MODIFIED: `docker-compose.yml` — added volumes for frontend service
CHANGE:
  ```yaml
  frontend:
    volumes:
      - /docker/federation-game/public_html:/usr/share/nginx/html:ro
      - /docker/federation-game/frontend/nginx-default.conf:/etc/nginx/conf.d/default.conf:ro
  ```
DEPLOYED: `docker compose up -d frontend` (container recreated)
VERIFIED:
- `docker inspect` shows both bind mounts active
- host md5 (`446e336d`) == container md5 for `index.html`
- nginx config syntax OK, reloaded
NOTE: Host `public_html/` and `frontend/` dirs on VPS are out of sync — deploy workflow must sync to BOTH for now

### 2026-06-29T08:20:00Z — [1.2] Extract npc_redis_helpers.py from npc_agent.py
STATUS: DONE — deployed and verified live on both containers
FILES:
- NEW: `npc-agent/npc_redis_helpers.py` (653 lines) — all Redis CRUD helpers migrated from npc_agent.py
- MODIFIED: `npc-agent/npc_agent.py` (2968 → 2356 lines, -612 lines) — imports from npc_redis_helpers + fourth_wall
CLEANUP:
- Removed broken `_recent_decision_shapes` stub (bodyless leftover from partial removal)
- Removed stale `from fourth_wall import` line (now combined with npc_redis_helpers import)
- Updated `_session_transcript(r)` → `_session_transcript(r, contacts=CONTACTS)` call site
FUNCTIONS EXTRACTED (32 total):
- get_redis, _trunc, _partner_id, _conversation_thread_id, _pair_slug
- _pair_state_key, _pair_journal_key, _pair_state, _pair_hset, _pair_append_journal
- _pair_recent_journal, _pair_thread_id, _store_thread_message, _recent_thread_messages
- _recent_decisions, _normalize_question, _question_similarity, _partner_answered_open_question
- _new_evidence_since, _duplicate_open_question, _open_question_from_partner
- _state_question_from_partner, _has_work_after_open_question, _compact_text
- _extract_open_question, _message_cooldown_remaining, _sync_pair_workspace
- _log_llm_call, _session_append, _session_transcript, _recent_decision_shapes, _newest_first_streak
DESIGN: All functions accept optional `char_id` param (defaults to `os.environ.get("CHAR_ID", "")`)
DEPLOYED:
- scp npc_agent.py + npc_redis_helpers.py to VPS /docker/federation-game/npc-agent/
- `docker compose restart npc-agent-001 npc-agent-306`
VERIFIED:
- md5 HOST: `ec8be183` (npc_agent.py), `69493966` (npc_redis_helpers.py)
- md5 CONTAINER 001: MATCHES both files
- md5 CONTAINER 306: MATCHES both files
- No ModuleNotFoundError after restart (errors were from old container pre-deploy)
- Both agents running their normal tick cycles

### 2026-06-29T16:45:00Z — [1.3] Extract npc_llm_client.py from npc_agent.py
STATUS: DONE — deployed and verified live on both containers
FILES:
- NEW: `npc-agent/npc_llm_client.py` (216 lines) — LLM routing, fallback chain, OR free pool
- MODIFIED: `npc-agent/npc_agent.py` (2356 → 2148 lines, -208 lines) — imports added for npc_llm_client
FUNCTIONS EXTRACTED:
- call_llm(system_prompt, user_prompt, model, r, call_label) -> dict
- _api_key_for_model(model, char_id) -> str|None
- _call_openrouter_free(messages, model, char_id) -> dict
CONSTANTS EXTRACTED:
- OR_FREE_POOL, _or_pool_idx, MODEL_ENABLE_THINKING, MODEL_REASONING_BUDGET
- REQUEST_TIMEOUT, ARTIFACT_TIMEOUT, MAX_TOTAL_BUDGET_MS, MAX_OUTPUT_TOKENS
- NVIDIA_BASE, OR_BASE
DEAD CODE REMOVED:
- _FOURTH_WALL_REPLACEMENTS dict (lines 1371-1390, shadowed by fourth_wall import)
- def _enforce_fourth_wall (lines 1393-1396, shadowed by fourth_wall import)
BUG FIX:
- extract script accidentally stripped `from fourth_wall import` line during content slicing
- detected via post-extraction import check; manually re-added both fourth_wall + npc_llm_client imports
DEPLOYED:
- scp npc_llm_client.py + npc_agent.py to VPS /docker/federation-game/npc-agent/
- Deploy-VpsFile.ps1 uploaded npc_agent.py (md5 match confirmed)
- `docker restart federation-game-npc-agent-001-1 federation-game-npc-agent-306-1`
VERIFIED:
- md5 HOST: `3bb68be1` (npc_agent.py), `9648adae` (npc_llm_client.py)
- md5 CONTAINER 001: MATCHES both files
- md5 CONTAINER 306: MATCHES both files
- Both containers restarted, cognition loop running, LLM calls succeeding
- char_001: llama-3.3-nemotron-super-49b returning 200 OK
- char_306: nemotron-3-super-120b returning 200 OK (occasional JSON parse fallback to rest)
