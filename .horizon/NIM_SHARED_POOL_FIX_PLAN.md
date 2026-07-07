# NIM Shared Pool — Config-Only Fix Plan (PLANNED, NOT APPLIED)

**Status:** PLANNED — do NOT apply tonight. No deploy, no restart, no commit required to land this doc.
**Source:** Read-only NPC/Councilor + shared-NIM audit (WATCH verdict). Sim is safe; only provider config is broken.
**Owner:** apply later, separately, behind its own approved plan.

---

## WARNING (do not violate)

> **Do NOT set `NIM_DISABLED=1` globally / via shared docker-compose env.**

`NIM_DISABLED` is checked in the shared NIM call path:
- `backend/llm_router.py:1415` → `return _early_failure("NIM disabled by env (NIM_DISABLED=1)")`
- `backend/nvidia_nim_client.py:895` → `if NIM_DISABLED:`

The **councilor agent containers share this same code**:
- `federation-game-npc-agent-001-1` (char_001)
- `federation-game-npc-agent-306-1` (char_306)

Setting `NIM_DISABLED=1` in those containers would kill their *working* NVIDIA calls
(`nvidia/nemotron-3-nano-30b-a3b`, `llama-3.3-nemotron-super-49b-v1`, `nemotron-3-super-120b-a12b`
→ `HTTP/1.1 200 OK`). They would fall back to local 3B and degrade. **Do not touch them.**

`NIM_DISABLED=1` is at most a *later, optional, main-backend-only* toggle (see Fix 3).

---

## Fix 1 — Refresh the shared NIM key pool

**Symptom:** every shared-pool key returns `403 Forbidden — Authorization failed`.
All keys fail → the whole pool is expired/invalid, not one bad key, not mis-selection.

**Pool definition** (`backend/nvidia_nim_client.py:45-55`):
- `NIM_API_KEYS` (comma-separated env)
- `NIM_API_KEY_1` … `NIM_API_KEY_8` (individual env vars)
- `NVIDIA_API_KEY` (common NVIDIA env var, appended if present)

Round-robin across all of the above (`_next_available_key`). **All currently 403.**

**Action (later):** replace the values of `NIM_API_KEYS` / `NIM_API_KEY_1..6` / `NVIDIA_API_KEY`
in the runtime env (VPS `/docker/federation-game/` compose env or secret store) with valid keys.

**Out of scope / must NOT touch:** councilor keys `NPC_KEY_CHAR_001`, `NPC_KEY_CHAR_001_SET`,
`NVIDIA_API_KEY_CHAR_001`, `NVIDIA_API_KEY_CHAR_001_TEST`, and the `char_306` equivalents.
These are NOT in the shared pool (grep of both router files for `*_CHAR_*` = empty) and they WORK.

**Verify (read-only, post-change):** `docker logs --tail 2000 federation-game-backend-1 | grep -c 403`
should drop toward 0 on `worker`/`npc_memory` tiers; `Tick complete:` lines stay `0 errors`.

---

## Fix 2 — Fix `npc_memory` tier 404 (stale model IDs)

**Symptom:** `npc_memory` tier returns `HTTP 404: 404 page not found` — model endpoints don't exist
(retired/renamed IDs), independent of key validity.

**Current (wrong) IDs** (`backend/llm_router.py`):
- `npc_memory.primary.model` = `nvidia/llama-3.1-nemotron-super-49b-v1`  (line ~1073)
- `npc_memory.fallback_nim.model` = `nvidia/llama-3.1-nemotron-ultra-251b`  (line ~1080)

**Action (later):** confirm the current valid NVIDIA NIM model IDs and update those two strings.
(Do NOT guess — verify against NVIDIA NIM catalog or a successful `200 OK` call before editing.)

**Verify (read-only):** `docker logs federation-game-backend-1 | grep "npc_memory tier" | grep 404`
count should go to 0.

---

## Fix 3 — `NIM_DISABLED=1` (optional, main-backend-only, later only)

**Only** if the shared pool keeps wasting calls/timeouts after Fix 1+2, OR to cut tick latency
(the `Exception: The read operation timed out` NIM fallback waits — bounded by the circuit breaker
`backend/llm_router.py:13`: 3 consecutive fails → 5-min cooldown).

- Set `NIM_DISABLED=1` **only** on `federation-game-backend-1` (and `federation-game-worker-1` if it shares the pool).
- **Never** on `federation-game-npc-agent-001-1` / `federation-game-npc-agent-306-1`.
- Effect: shared tiers skip NIM and go straight to Ollama (local) — already what happens post-cooldown.

**Verify:** backend tick latency drops; councilor agents still log `LLM OK … 200 OK`.

---

## Rollback
- Keys: restore previous env values.
- Model IDs: `git revert` the edited lines (single file `backend/llm_router.py`).
- `NIM_DISABLED`: unset the env var on the backend container and restart only that container.

## Constraints respected
- No behavior/code patch to NPC cognition, dialogue, or memory logic.
- No `--workers` change; single `game_state` process untouched.
- `/choose` contract untouched.
- `gs.current_event = None` after choice untouched.
- No deploy tonight. No restart tonight.
