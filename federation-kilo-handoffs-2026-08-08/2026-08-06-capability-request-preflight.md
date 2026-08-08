# Capability-Request Producer — Deployment Preflight

**Date:** 2026-08-06 (preflight, no deployment)  
**Author:** Kilo  
**Scope:** Exact diff, SHA-256 hashes, syntax/import checks, regression testing
(separate processes), and exact Compose diff. **Nothing was deployed.**

---

## 1. GIT STATUS / DIFF / HASHES

Worktree: `/docker/federation-worktrees/capability-request-producer`
Branch: `fix/capability-request-producer`
HEAD: `c28b9dcdd39ce90b2782b6d493b83716786e0760` (the unrelated starmap commit —
**the capability-request work is NOT yet committed**; all changes are untracked).

```
$ git status --porcelain --untracked-files=all
?? federation-game/npc-agent/npc_actions.py
?? federation-game/npc-agent/npc_work_loop_adapter.py
?? run_capability_producer_tests.py
```

### SHA-256 (production-relevant files)
| File | SHA-256 |
|---|---|
| **LIVE** `/docker/federation-game/npc-agent/npc_actions.py` | `65477d425d5282ee62341810fe364ab512f0f254e254d7e5bb49ed1b9807a8fe` |
| **WORKTREE** `.../npc_actions.py` (modified) | `76282eb8f58cad134a3484cd658adcf2fdb30aa992069627658c4166661276ad` |
| **WORKTREE** `.../npc_work_loop_adapter.py` (new) | `e311973a67ebbc6a6ab2f5a0b773d74d478a42c28eaa987c0f081161019b90ca` |
| **WORKTREE** `run_capability_producer_tests.py` (new) | (see worktree) |

### Diff summary (`live npc_actions.py` → `worktree npc_actions.py`)
- **Exactly 1 hunk**, entirely inside `elif cat == "request_capability":` (live
  lines 695–727).
- The block was rewritten: legacy `file_npc_need()` call is wrapped behind the
  new `handle_request_capability()` bridge; legacy runs only on fallback.
- **No other line in `npc_actions.py` changed** (confirmed by `diff -u` hunk count = 1
  and a negative grep for changed lines outside the `request_capability` handler).

---

## 2. npc_actions.py LINEAGE PROOF

The worktree `npc_actions.py` is a **byte-identical copy of the live file except
for the `request_capability` handler**. Evidence:
- Single hunk, contiguous, lines 696–727 only.
- Context lines immediately before (`elif cat == "request_capability":`) and
  after (`else: note = _compact_text(...)`) are unchanged.
- Every changed line belongs to the bridge rewrite (import of adapter,
  `handle_request_capability(...)`, fallback branches, `file_npc_need` retained
  as legacy path).

Conclusion: deploying the worktree `npc_actions.py` will alter **only** the
intended `request_capability` behavior; all other action categories
(send_message, create_artifact, write_code, read_artifacts, investigate,
self_improve, rest, create_institution, propose_role, submit_to_institution)
are byte-for-byte unchanged.

---

## 3. REGRESSION TESTING (separate Python processes)

### 3a. NPC regression suite — directly exercises `npc_actions.py`
Run from the live dir (baseline) and from a `/tmp` copy with the **modified**
`npc_actions.py` overlaid (separate process each):

| Suite | Against LIVE `npc_actions.py` | Against MODIFIED `npc_actions.py` |
|---|---|---|
| `npc-agent/test_placeholder_rejection.py` | 16 passed | 16 passed |
| `npc-agent/test_post_resolution_pivot.py` | 6 passed | 6 passed |
| **Total** | **22 passed** | **22 passed** |

→ **No regression** in NPC agent behavior from the bridge change.

### 3b. Backend unit suites (untouched by this change, run for regression context)
| Suite | Result |
|---|---|
| `backend/test_pilot_cognition.py` (mocked) | **3 passed** |
| `backend/test_institutions.py` (FakeRedis) | 5 passed, **4 failed** |

The 4 `test_institutions.py` failures are `institutions.py:820 AttributeError` —
a **pre-existing** defect in `backend/institutions.py`, which this worktree does
**not** modify (worktree contains only `npc_actions.py`, `npc_work_loop_adapter.py`,
and the test runner). These failures are unrelated to the capability-request
bridge and exist on the live baseline today.

### 3c. New producer tests (DB1, separate processes)
`run_capability_producer_tests.py` → **15 passed, 0 failed** (all 15 authoritative
cases, each in its own process).

### 3d. Work-loop / route / auth suites — NOT PRESENT
A repo-wide search found **no dedicated test files** for:
- work-loop / `capability_request` (the draft/submit actions were described as
  "already tested in isolation" in the original task, but no such test file exists
  in this workspace tree),
- route (no `test_*.py` under `backend/routes/`),
- auth (no auth test file).

The new 15 producer tests DO exercise the real `capability_request_draft` and
`capability_request_submit` work-loop actions end-to-end against Redis DB1, which
is the closest available coverage for the work-loop path.

### 3e. Inventory / baseline note
- 117 `def test_` functions exist across `backend/`, `npc-agent/`,
  `npc-agent-shadow/` (grep count).
- The operator-referenced **"217 passing tests"** baseline is **not fully
  reproducible** from this workspace tree: there are no work-loop/route/auth test
  files, and the live-infra integration tests (below) cannot be run in preflight
  without touching the runtime. Documented, not fabricated.

### 3f. Tests EXCLUDED from preflight (require live runtime — unsafe to run)
These import `requests`/`http://172.21.0.7:8000` or connect to live Redis and
would mutate production state (e.g. `test_npcs.py` calls `/reset`):
`backend/test_npcs.py`, `test_event_history.py`, `test_factions.py`,
`test_quests.py`, `test_timeline.py`, `test_npc_phase3.py`,
`npc-agent-shadow/test_npc_shadow_mode.py`. **Excluded by safety rules; must be
run only after a controlled deploy, never in preflight.**

---

## 4. SYNTAX / IMPORT CHECKS (worktree files)

| Check | Result |
|---|---|
| `py_compile` on all 4 worktree files | PASS |
| `import npc_work_loop_adapter` (shared on path) | OK, `_WORK_LOOP_OK=True` |
| `callable(handle_request_capability)` | True |
| `_get_partner_for("char_001")` → `char_306` | Correct |
| `_get_partner_for("char_306")` → `char_001` | Correct |

---

## 5. EXACT COMPOSE DIFF (two NPC containers)

Both `npc-agent-001` and `npc-agent-306` currently mount only
`/docker/federation-game/npc-agent:/app:ro` and have **no** shared package or
`PYTHONPATH`. The backend container already uses the exact mount
`/docker/federation-game/shared -> /opt/federation_shared` (ro); mirror it.

### `npc-agent-001` (lines ~342–357)
```diff
     environment:
       - CHAR_ID=char_001
       - NPC_NAME=Archimedes Prime
       - NVIDIA_API_KEY=${NVIDIA_API_KEY_CHAR_001_TEST}
       - REDIS_URL=redis://redis:6379/0
+      - PYTHONPATH=/opt/federation_shared
       - PRIMARY_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
       ...
     volumes:
       - /docker/federation-game/npc-agent:/app:ro
+      - /docker/federation-game/shared:/opt/federation_shared:ro
```

### `npc-agent-306` (lines ~371–395)
```diff
     environment:
       - CHAR_ID=char_306
       - NPC_NAME=The Oracle
       - NVIDIA_API_KEY=${NVIDIA_API_KEY_CHAR_306:-KEY_REDACTED_set_in_env}
       - REDIS_URL=redis://redis:6379/0
+      - PYTHONPATH=/opt/federation_shared
       - PRIMARY_MODEL=nvidia/nemotron-3-super-120b-a12b
       ...
     volumes:
       - /docker/federation-game/npc-agent:/app:ro
+      - /docker/federation-game/shared:/opt/federation_shared:ro
```

After this change, `docker compose up -d --force-recreate npc-agent-001 npc-agent-306`
(or equivalent) applies the mount + `PYTHONPATH`, after which
`from federation_work_loop.core import execute_work_loop_action` resolves inside
both containers.

---

## 6. LIVE NPC IMPORT (read-only, unchanged from prior turn)
Both `npc-agent-001-1` and `npc-agent-306-1` still FAIL:
`npc_work_loop`, `federation_work_loop.core`, `execute_work_loop_action`
("No module named 'federation_work_loop'"). This is expected until the Compose
diff above is applied and the two containers recreated.

---

## 7. PREFLOW GATE DECISION

| Gate | Status |
|---|---|
| 1. Exact git status/diff/hashes (uncommitted acknowledged) | ✅ Provided; changes are untracked on `fix/capability-request-producer` |
| 2. Regression rerun (work-loop/route/auth/NPC) | ⚠️ NPC regression: 22/22 both live & modified (no regression). Backend unit: pilot 3/3, institutions 5 pass / 4 pre-existing fail. Work-loop/route/auth dedicated suites absent from tree; closest coverage = 15 producer tests (15/15). Live-infra suites excluded by safety. |
| 3. npc_actions.py lineage | ✅ Proven: 1 hunk, only `request_capability` |

**Recommendation:** commit the three worktree files to
`fix/capability-request-producer` (gate 1 open item), then proceed to deploy
only after the 4 pre-existing `test_institutions.py` failures are triaged
(out of scope for this bridge but noted) and a controlled post-deploy run of the
live-infra suites is scheduled.

---

## 8. NOT EXECUTED (safety)
- No live bind-mounted files edited.
- No container restarted, recreated, or redeployed.
- No Redis DB0 mutation; DB1 used only by isolated tests (cleaned up).
- No `FLUSHDB`/`FLUSHALL`/broad `KEYS`.
- No unrelated services, Postgres, frontend, Docker config, or institutions.py
  changed.
- The Compose diff above is **proposed only** — not applied.
