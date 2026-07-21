# LIVE Loop-Control Integration Recovery Handoff
**Date:** 2026-07-21  
**Branch:** fix/live-loop-control-integration-20260721  
**Worktree:** `C:\Users\seand\.copilot\copilot-worktrees\federation\live-loop-control-integration`  
**Status:** AUDIT COMPLETE — PATCH NOT YET AUTHORIZED  

---

## Corrected Source-Separation Findings

### File Inventory (independent SHA-256, size, line count)

| File | Path | Size | Lines | SHA-256 |
|------|------|------|-------|---------|
| LIVE npc_decisions.py | `…\Temp\federation-live-source-snapshot\20260720-231250\npc-agent__npc_decisions.py` | 54,855 B | 1,098 | FC99706BECFFF79405856282A962A49DBF41A7E72BF70B73C839D8F771D97561 |
| LIVE npc_actions.py | `…\Temp\federation-live-source-snapshot\20260720-231250\npc-agent__npc_actions.py` | 34,845 B | 741 | 045559459009C0ED34460BF979C20DC8A1B5022F3E3C54DA79EEF73E7264294F |
| AUTHORITATIVE npc_decisions.py | `…\live-loop-control-integration\federation-game\npc-agent\npc_decisions.py` | 55,092 B | 1,101 | DEE367E251BC488A64E883D355EEA869EF03D931FA825CED6E96DA2DD99E680D |
| AUTHORITATIVE npc_actions.py | `…\live-loop-control-integration\federation-game\npc-agent\npc_actions.py` | 36,670 B | 777 | 9832F2ADCDF9F779C263CDD31B19C2A9314B105F2E5B11E1256919E82157FC19 |

---

## Hook Presence Matrix

| FILE | HAS LOOP-CTRL IMPORT | HAS LOOP-CTRL TAIL-CALL | HAS INLINE STREAK LAYER | HAS record_deferral | HAS record_completed_work |
|------|---------------------|------------------------|------------------------|--------------------|--------------------------|
| LIVE npc_decisions.py | **NO** | **NO** | YES (lines 1076–1094) | NO | NO |
| AUTHORITATIVE npc_decisions.py | YES (line 64) | YES (line 1096) | YES (lines 1076–1094) | NO | NO |
| LIVE npc_actions.py | NO | NO | NO | **NO** | **NO** |
| AUTHORITATIVE npc_actions.py | **YES** (line 20) | NO | NO | YES (line 284,300,307) | YES (line 281,288,294,309) |

> **Prior report error corrected:** Earlier output claimed AUTHORITATIVE npc_actions.py did NOT import the loop-control functions. That was wrong. The import is present at line 20 of the authoritative file (`from npc_loop_control import record_deferral, record_completed_work`). The LIVE npc_actions.py lacks both the import and the call sites.

---

## Key Technical Corrections

### Counter Ownership (corrected)

| Function | Keys affected |
|----------|--------------|
| `record_deferral(r, CHAR_ID, topic)` | Increments `npc_loopctrl:defer`; sets `npc_loopctrl:topic` |
| `record_completed_work(r, CHAR_ID, "create_artifact", title)` | Conditionally clears defer, topic, and shape state after confirmed different completed work |
| **No `npc_loopctrl:create` counter exists** | The module's ≥3 gate depends on the defer streak populated by `record_deferral()`, not a separate create counter |

### Module Gate Semantics (do not reorder `enforce()`)

`npc_loop_control.enforce()` has two intentionally different reachable gates:
- `>=2 AND same blocked topic` → force `read_artifacts`
- `>=3 AND any create_artifact topic` → force `rest`

The ≥3 branch remains reachable when the proposed artifact's topic differs from the blocked topic. The ordering defect is **only** in the inline `npc_decisions.py` block where both conditions use `chosen == banned` and the ≥2 branch returns first, making the ≥3 branch unreachable for that same condition.

---

## Policy vs Runtime Layers

**Three policy layers, two executable runtime enforcement layers:**

1. **Advisory prompt constraint** (≥4 hard, ≥3 soft) — text guidance to the LLM, not enforced in code.
2. **Inline post-parse block** in `npc_decisions.py` (lines 1076–1094) — executable; has the ≥2/≥3 ordering defect.
3. **Module enforcement** via `_enforce_loop_control()` tail-call — executable; has correctly-ordered distinct gates.

---

## Answer to Seven Diagnostic Questions

1. **Can npc_loopctrl:defer and npc_loopctrl:topic ever change if record_* calls are not installed?**  
   `record_deferral` writes `npc_loopctrl:defer` and `npc_loopctrl:topic`. `record_completed_work` may conditionally delete defer, topic, and shape state. Without the `record_*` hooks in live `npc_actions.py`, the module's deferral state is not maintained.

2. **Would a Layered patch without npc_actions changes address artifact_deferred_dedup, or only repeated decision shapes?**  
   Only repeated decision shapes. The dedup deferral fires *before* the LLM runs; the module's defer-streak counters are invisible to that path because `record_deferral()` is absent. The dedup-the-same-topic loop would remain unaddressed.

3. **How many enforcement layers exist after a Layered patch (no npc_actions changes)?**  
   Three policy layers; two executable runtime layers (inline block + module).

4. **Which layer owns the ≥2 read_artifacts escalation?**  
   The inline post-parse block in `npc_decisions.py` (lines 1081–1086 in both LIVE and AUTHORITATIVE).

5. **Which layer owns the ≥3 escalation?**  
   The module's ≥3 "any create_artifact" gate. The inline ≥3 branch (chosen==banned) exists but is unreachable for that condition due to the ≥2 return.

6. **Is either ≥3 path unreachable?**  
   - Inline ≥3 (chosen==banned): **YES** — unreachable due to ≥2 early return in the same block.  
   - Module ≥3 (any create_artifact, ≥3 streak, topic differs from blocked): **Reachable** — but only if `record_deferral()` is installed and populating the defer streak.

7. **Which smallest patch addresses the observed dedup deferral loop?**  
   Restore `record_deferral()` in `npc_actions.py` artifact_deferred_dedup branch and `record_completed_work()` after `artifact_created`, add the npc_loop_control import and tail-call to `npc_decisions.py`, and fix only the inline post-parse ordering (evaluate ≥3 before ≥2, or use if/elif). Do NOT reorder `npc_loop_control.enforce()`.

---

## Proposed Coherent Candidate Patch — NOT AUTHORIZED

Scope: isolated worktree `fix/live-loop-control-integration-20260721` only.

1. **Baseline:** Preserve live `npc_decisions.py` and `npc_actions.py` as the production-proven baseline.  
2. **Add module:** Add `npc_loop_control.py` to the dedicated-agent runtime.  
3. **Restore in `npc_decisions.py`:**  
   - `from npc_loop_control import enforce as _enforce_loop_control`  
   - One final `return _enforce_loop_control(decision, r, CHAR_ID)` call  
4. **Fix inline ordering only:**  
   - Evaluate `streak >= 3` before `streak >= 2` OR convert to `if/elif`.  
   - Do NOT alter `npc_loop_control.enforce()` internal ordering.  
5. **Restore in `npc_actions.py`:**  
   - `from npc_loop_control import record_deferral, record_completed_work`  
   - `record_deferral(r, CHAR_ID, dedup_topic or title)` in `artifact_deferred_dedup` branch  
   - `record_completed_work(r, CHAR_ID, "create_artifact", title)` after `artifact_created`  
6. **Exclude:** `npc_shadow_mode.py` must not be added or promoted.  
7. **Backend:** Out of scope unless runtime call graph separately proves it executes the dedicated councilor decision path.  
8. **Test:** `test_char_901` and `test_char_902` only, no network, no live Redis, no paid model calls, no protected councilors.

---

## Constraints (in force)

- Do not modify `S:\federation`.
- Do not deploy.
- Do not restart containers.
- Do not modify Redis or Postgres.
- Do not run protected councilors (`char_001`, `char_306`).
- Do not push main, force-push, or open/merge a PR.
- No patch or deployment is authorized by this document.

---

## Commands to execute when patch is authorized (not run now)

```bash
# In isolated worktree only:
cd C:\Users\seand\.copilot\copilot-worktrees\federation\live-loop-control-integration

# After isolated tests pass:
git add docs/handoffs/LIVE_LOOP_CONTROL_INTEGRATION_RECOVERY_20260721.md
git commit -m "checkpoint: preserve corrected live loop-control audit

Corrected findings:
- AUTHORITATIVE npc_actions.py DOES import record_deferral and record_completed_work
- LIVE npc_actions.py is missing both import and call sites
- record_deferral increments defer counter and sets topic
- record_completed_work conditionally clears state after different work
- no npc_loopctrl:create counter exists
- module >=3 gate depends on record_deferral streak, not a create counter
- inline >=3 branch in npc_decisions.py is unreachable due to >=2 early return
- fix ordering only in inline block; do not reorder enforce()
- layered patch without npc_actions hooks addresses shapes only, not dedup delayps

Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"

git push -u origin fix/live-loop-control-integration-20260721
```

Deployment remains out of scope and unauthorized. Before any future deployment, a separate authorization must define:

- exact compose project directory
- actual compose service names
- complete deployed file manifest
- backup hashes
- atomic installation method
- synthetic canary procedure
- complete rollback procedure

No raw VPS address, SCP command, restart command, Redis deletion, or protected councilor instruction belongs in this recovery handoff.
