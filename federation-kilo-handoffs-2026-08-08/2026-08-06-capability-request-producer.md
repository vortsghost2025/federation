# Capability-Request Producer Bridge — Final Report

**Date:** 2026-08-06  
**Operator:** Kilo (isolated worktree implementation, no live mutations)

---

## STATUS
IMPLEMENTED & VERIFIED IN ISOLATION. Not deployed. All 15 DB1 tests pass in
separate Python processes. Live runtime was not touched.

---

## ROOT CAUSE
The NPC agent's `request_capability` decision path
(`npc-agent/npc_actions.py`, `cat == "request_capability"`) calls the legacy
`file_npc_need()` (writes a `npc:needs` queue entry in Redis DB0). It never
invokes the already-deployed work-loop publication actions
`execute_work_loop_action("capability_request_draft", ...)` and
`execute_work_loop_action("capability_request_submit", ...)`.

Result: production NPC code never produces a work-loop capability request, so
Redis DB0 currently holds zero work-loop capability requests even though the
draft/submit actions are implemented, tested, and deployed in the shared
`federation_work_loop` package.

Secondary blocker (deployment, not code): the shared package
`federation_work_loop` is mounted read-only into the **backend** container at
`/opt/federation_shared`, but the two NPC agent containers mount **only**
`/docker/federation-game/npc-agent -> /app`. They cannot import
`federation_work_loop` or `execute_work_loop_action` at all (see LIVE NPC
IMPORT RESULTS).

---

## WORKTREE PATH
`/docker/federation-worktrees/capability-request-producer`

Created via:
`git worktree add -b fix/capability-request-producer /docker/federation-worktrees/capability-request-producer`
from the canonical repo at `/opt/federation`. The live production tree
`/docker/federation-game` was NOT modified.

---

## BRANCH AND HEAD
- Branch: `fix/capability-request-producer`
- HEAD: `c28b9dcdd39ce90b2782b6d493b83716786e0760` (`[LANE-1] starmap: dramatic cosmic scale — 8x-25x camera distance between modes`)
- Remote: `origin` (https://github.com/vortsghost2025/federation.git)

Note: the git repo at `/opt/federation` tracks only `npc_agent.py` under
`federation-game/npc-agent/`. The production-deployed `npc_actions.py`,
`npc_decisions.py`, etc. live in the live workspace tree
`/docker/federation-game/npc-agent/` (bind-mounted). The worktree copies the
production `npc_actions.py` and applies the bridge edit; the new adapter and
tests are added as new files in the worktree.

---

## FILES CHANGED
1. **`federation-game/npc-agent/npc_work_loop_adapter.py`** (NEW — the production bridge)
   - Safe import of `federation_work_loop.core` (`execute_work_loop_action`,
     `get_shared_agenda`, `get_agenda_item`, `get_capability_request`,
     `_pair_slug`, `_stable_capability_id`). Falls back gracefully if unavailable.
   - `handle_request_capability(decision, actor_id, r, result, desc, reasoning)`
     implements the full draft→submit flow with idempotency and partial-failure
     handling.
   - Partner resolution `_get_partner_for()` matches production helper
     (`char_001 ↔ char_306`).

2. **`federation-game/npc-agent/npc_actions.py`** (MODIFIED — `request_capability` handler)
   - Replaces the direct `file_npc_need()` call with:
     - `bridge_ok = handle_request_capability(...)`;
     - if `bridge_ok` → new path used, legacy path skipped;
     - if `bridge_ok is False` and `action_taken == "capability_request_partial_failure"`
       → draft preserved, legacy path skipped (retryable);
     - otherwise → legacy `file_npc_need()` invoked exactly once.

3. **`test_capability_request_producer.py`** (NEW — DB1-only authoritative tests, 15 cases)
4. **`run_capability_producer_tests.py`** (NEW — runs each test in a separate Python process)

---

## PRODUCTION PRODUCER PATH
`federation-game/npc-agent/npc_work_loop_adapter.py`
→ `handle_request_capability()` →
`execute_work_loop_action("capability_request_draft", payload)` then
`execute_work_loop_action("capability_request_submit", submit_payload)`.

Called from `federation-game/npc-agent/npc_actions.py`
`execute_decision()` at `cat == "request_capability"`.

---

## FIELD MAPPING
Decision fields → capability-request fields (in-world text only; no
Redis/moderator/source/container/API/fourth-wall leakage):

| Decision field | Capability-request field |
|---|---|
| `need_type` | drives `capability_key` (`suggested_capability`) and `title`/narrative context |
| `priority` | `priority` |
| `description` | `blocker` (truncated to 240) |
| `why_needed` | `evidence` (truncated to 300) |
| `suggested_capability` | `capability_key`, `title` |
| (derived from resolved agenda) | `agenda_id`, `objective` |
| (in-world generated) | `attempts`, `consulted_npcs` (=[partner]), `requested_change`, `acceptance_criteria`, `expected_benefit`, `implementation_risks` |

`collaborating_councilor_id` = the resolved pair partner. `requester_id` =
`CHAR_ID` (the acting NPC).

---

## IDEMPOTENCY BEHAVIOR
- Stable identity: `stable_id = sha256("{agenda_id}:{capability_key}")[:16]`.
- Before drafting, the adapter reads
  `npc_capability_requests:stable:{stable_id}`. If a request already exists:
  - status `draft` (preserved from a prior partial submit failure) → the retry
    path **submits the existing draft** (does not create a new one);
  - status `submitted` or beyond → returns the existing request id
    (`action_taken = capability_request_existing`), no new draft.
- The core `create_capability_request` also dedups by stable id as a backstop.
- Equivalent repeated decisions therefore never create a duplicate request.

---

## PARTIAL-FAILURE BEHAVIOR
- If draft succeeds but submit fails AND the request is still `draft`:
  - adapter returns `False` with `action_taken = capability_request_partial_failure`,
    `request_id` = the preserved draft id, `status = draft_preserved_for_retry`.
  - The draft is left intact in Redis (no second draft created).
  - `npc_actions.py` does **not** call the legacy path (draft is retryable).
- On retry (same NPC + agenda + capability_key):
  - the idempotency check finds the existing `draft` and **submits it**,
    returning `True` with the same request id.
- Non-retryable submit failure (e.g. `request_not_found`) → returns `False`,
  and `npc_actions.py` invokes the legacy `file_npc_need()` exactly once.

---

## TEST FILES AND COUNTS
- **`test_capability_request_producer.py`** — 15 authoritative test functions:
  1. real decision + valid agenda creates one request
  2. transitions draft → submitted
  3. requester is the acting NPC
  4. collaborating councilor is the actual pair partner
  5. all substantive mapped fields non-empty
  6. equivalent repeated decisions create no duplicate
  7. char_001 → char_306 mapping
  8. char_306 → char_001 mapping
  9. no valid agenda → legacy fallback exactly once
  10. work-loop unavailability → legacy fallback exactly once
  11. successful publication never calls legacy
  12. draft failure → one fallback, no submitted partial state
  13. submit failure preserves one retryable draft
  14. retry after submit failure creates no second draft
  15. exact DB1 namespaced cleanup removes only test-created keys
- **`run_capability_producer_tests.py`** — runner that executes each of the 15
  functions in a **separate Python process** (avoids `sys.modules` contamination).

**Result: 15 passed, 0 failed** (verified both as one process and as 15 separate processes).

---

## DB1 CLEANUP PROOF
- All tests use `redis://172.16.2.12:6379/1` (DB1, test-only).
- `cleanup_db1()` removes only test-created state:
  - namespaced keys (`test_capreq_producer_20260806:*`);
  - capability request hashes/stable keys created during the session;
  - agenda items whose `agenda_key` starts with `test_work_` / `test_capreq_`.
- Test 15 asserts a deliberately created non-test key (`production:some_key`)
  survives cleanup. **Test 15 PASSED**, proving cleanup is scoped and does not
  touch unrelated keys.
- No `FLUSHDB`/`FLUSHALL`/`KEYS *`/broad cleanup was used. Only `scan_iter`
  with exact prefixes plus targeted deletes.

---

## LIVE NPC IMPORT RESULTS (read-only `docker exec ... python -c`)
Both containers were checked; neither was modified.

| Import | npc-agent-001-1 | npc-agent-306-1 |
|---|---|---|
| `npc_work_loop` | FAIL (No module named 'npc_work_loop') | FAIL (No module named 'npc_work_loop') |
| `federation_work_loop.core` | FAIL (No module named 'federation_work_loop') | FAIL (No module named 'federation_work_loop') |
| `execute_work_loop_action` | FAIL (No module named 'federation_work_loop') | FAIL (No module named 'federation_work_loop') |

Conclusion: the live containers **cannot** reach the shared package today.
Deployment requires mounting the shared package and setting `PYTHONPATH`.

Container mounts observed:
- `federation-game-npc-agent-001-1`: only `/docker/federation-game/npc-agent -> /app` (ro)
- `federation-game-backend-1`: `/docker/federation-game/backend -> /app` (ro),
  `/docker/federation-game/shared -> /opt/federation_shared` (ro),
  `/docker/federation-game/universe -> /docker/federation-game/universe` (rw)

---

## EXACT PRODUCTION TRIGGER EVENT
1. NPC cognition loop (`npc_agent.py` → `decide_action()`) selects the
   `request_capability` action category (LLM-driven, when a structured need is
   observed — never shell/admin/system changes).
2. `execute_decision(decision, r, CONTACTS)` in `npc_actions.py` reaches
   `cat == "request_capability"`.
3. The modified handler calls
   `handle_request_capability(decision, CHAR_ID, r, result, desc, reasoning)`.
4. The adapter resolves the pair slug + partner, finds an **existing active**
   agenda, maps fields, drafts via `execute_work_loop_action`, then submits.
5. On success the real request id + `submitted` status are returned; legacy
   `file_npc_need()` is NOT called.

---

## MINIMAL DEPLOYMENT PLAN (NOT EXECUTED)
1. **Copy new file** `npc_work_loop_adapter.py` →
   `/docker/federation-game/npc-agent/npc_work_loop_adapter.py`.
2. **Copy modified file** `npc_actions.py` →
   `/docker/federation-game/npc-agent/npc_actions.py` (preserving the rest of
   the production file; the edit is isolated to `cat == "request_capability"`).
3. **Mount the shared package** into both NPC containers read-only:
   `/docker/federation-game/shared -> /opt/federation_shared` (ro).
4. **Set env** `PYTHONPATH=/opt/federation_shared` in both NPC container
   definitions (so `from federation_work_loop.core import ...` resolves).
5. **Recreate exactly the two NPC containers** (`federation-game-npc-agent-001-1`
   and `federation-game-npc-agent-306-1`) so the new mount + PYTHONPATH take
   effect and the new files are loaded.
6. **Verify** host md5 and container md5 match for both files on both
   containers (per AGENTS.md deploy workflow), and confirm
   `docker exec ... python -c "from federation_work_loop.core import execute_work_loop_action"`
   now succeeds on both.

Required from the checklist:
- [x] changed `npc-agent/npc_agent.py` — N/A (logic lives in `npc_actions.py`,
      which `npc_agent.py` already calls; no change needed there)
- [x] changed `npc-agent/npc_work_loop.py` — delivered as
      `npc_work_loop_adapter.py` (no pre-existing `npc_work_loop.py`)
- [x] shared package mount — required (read-only, `/opt/federation_shared`)
- [x] `PYTHONPATH=/opt/federation_shared` — required
- [x] read-only shared mount for npc-agent-001 — required
- [x] read-only shared mount for npc-agent-306 — required
- [x] recreation of exactly the two NPC containers — required (for mount/PYTHONPATH to apply)

---

## NOT EXECUTED (safety — per instructions)
- No live bind-mounted files were edited.
- No container was restarted, recreated, or redeployed.
- No Redis DB0 mutation, no `FLUSHDB`/`FLUSHALL`/`SCRIPT FLUSH`/broad `KEYS`.
- Redis DB1 was used only by isolated tests, cleaned up afterward.
- No unrelated services, NPC data, reverse proxy, Postgres, frontend,
  institutions, or Docker configuration were touched.
- The live NPC import limitation was confirmed read-only and not fixed in place.
- The bridge was implemented only in the isolated worktree at
  `/docker/federation-worktrees/capability-request-producer`.
