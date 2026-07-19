# NPC Topic-Loop Control — Evidence-Only Closeout (Corrective Pass)

Local worktree: C:\Users\seand\.copilot\copilot-worktrees\federation\vortsghost2025-npc-loop-control
Branch: npc-topic-loop-control
Scope: LOCAL ONLY. No VPS access for edit, no container restart, no deploy, no Redis/Postgres
write, no NPC message/cognition, no push/fetch/merge/rebase/history-rewrite/amend.

This document supersedes the prior closeout (d360fe0). It corrects four
provenance/qualification claims and records the bounded corrective pass.

## 1. Git identity

- base (branch point):        984864c4e6898bf56d32c8a672af6c2339b0def7
- recovery commit:             abaf07c075bdacf257c74a22adbed1ef8259eaa5
- implementation commit:       118fcc9beeb1ee24cb7a4affcf395e48c55e249f
- prior doc-only commit:       d360fe0b6736bc4c308ca4ff897e473965b7d631
- corrective impl commit (SHA-256 determinism): 93073bcf495ae533d5687fb04f6623378c726ac1
- corrective doc commit:                    8fe6a5376eaf538d0b6839b9084c2e0228143302
- npc_actions provenance fix commit:       1bdbb8f1d6bd72b5328da8c67f76735338982188
- provenance closeout doc commit:          af16b285e7ceba870baa150999667f8971efe88b

git diff --name-status 984864c..HEAD (current):
  A federation-game/npc-agent/institutions.py
  M federation-game/npc-agent/npc_actions.py
  M federation-game/npc-agent/npc_agent.py
  M federation-game/npc-agent/npc_decisions.py
  A federation-game/npc-agent/npc_loop_control.py
  M federation-game/npc-agent/npc_redis_helpers.py
  A federation-game/npc-agent/test_npc_loop_control.py
  A federation-game/npc-agent/test_operator_acknowledgement.py (fixed)
  A federation-game/npc-agent/import_smoke.py (new)

## 2. Authoritative-source ancestry — CORRECTED

Captured VPS SHA-256 (live read-only, re-confirmed 2026-07-19) and Git blob
hashes at each commit. Full 64-char hashes below.

### npc_agent.py
  VPS deployed : ed599569e2894fa7b15987ba2b5feec777226f2497b350131113ac0c67786e9e
  base blob    : ed599569e2894fa7b15987ba2b5feec777226f2497b350131113ac0c67786e9e  (= VPS)
  recovery blob: ed599569e2894fa7b15987ba2b5feec777226f2497b350131113ac0c67786e9e  (= VPS)
  impl blob    : ec01a5bc8b5e7250f02322df652e6f47b3091c8e542aca308114f77e2840e13d
  head blob    : ec01a5bc8b5e7250f02322df652e6f47b3091c8e542aca308114f77e2840e13d
  status: base == VPS (deployed base recovered); impl MODIFIED_FROM_VERIFIED_DEPLOYED_BASE
          (only a bounded-exception comment was added -> hash legitimately changed).

### npc_decisions.py
  VPS deployed : fc99706becfff79405856282a962a49dbf41a7e72bf70b73c839d8f771d97561
  base blob    : fc99706becfff79405856282a962a49dbf41a7e72bf70b73c839d8f771d97561  (= VPS)
  recovery blob: fc99706becfff79405856282a962a49dbf41a7e72bf70b73c839d8f771d97561  (= VPS)
  impl blob    : dee367e251bc488a64e883d355eea869ef03d931fa825ced6e96da2dd99e680d
  head blob    : dee367e251bc488a64e883d355eea869ef03d931fa825ced6e96da2dd99e680d
  status: base == VPS (deployed base recovered); impl MODIFIED_FROM_VERIFIED_DEPLOYED_BASE
          (import + enforce wrap, 2 lines).

### npc_actions.py  — PROVENANCE GAP RESOLVED (this corrective pass)
  VPS deployed : 045559459009c0ed34460bf979c20dc8a1b5022f3e3c54da79eef73e7264294f
  recovered pre-edit (commit 1bdbb8f, blob): 045559459009c0ed34460bf979c20dc8a1b5022f3e3c54da79eef73e7264294f  (= VPS)
  corrected post-edit (commit 1bdbb8f, blob): 8d974b77b9d5fc39bbf1d7de43cd6782db076e045676f04557217df95708108d
  head blob    : 8d974b77b9d5fc39bbf1d7de43cd6782db076e045676f04557217df95708108d
  status: RESOLVED. The branch's npc_actions.py was REPLACED with the exact deployed
          VPS file (SHA-256 verified byte-identical to 04555945...) and the four
          intended loop-control hunks were replayed. git diff --no-index against the
          deployed file shows ONLY the four intended hunks (no other changes):
            1. +from npc_loop_control import record_deferral, record_completed_work
            2. +record_deferral(r, CHAR_ID, dedup_topic or title)  (in dedup branch,
               composes with the existing _is_repetitive_artifact gate)
            3. artifact_content = _enforce_fourth_wall(llm_result.get("content") or desc)
            4. +record_completed_work(r, CHAR_ID, "create_artifact", title)
          Unchanged: operator acknowledgement, attribution kwarg, moderator repair,
          provider routing, fourth-wall enforcement.
          The previously-divergent local base (c2fdf2df...) is superseded. The
          deployed copy is preserved locally as npc_actions_deployed.py for provenance.

### Unmodified recovered modules (recovery commit == VPS, UNCHANGED_FROM_DEPLOYED)
  npc_context.py       815d06f6...
  npc_redis_helpers.py e34a3fae...
  npc_llm_client.py    c4f90cdc...
  npc_memory_bridge.py a85710bf...
  fourth_wall.py       8fed9407...45e5d
  cosmic_monitor.py    55bc0777...
  institutions.py      8c051df7...

### New local-only layer
  npc_loop_control.py  NEW in 118fcc9 (no deployed equivalent).

## 3. Implementation enumeration (corrective pass)

Runtime source changed this pass:
- npc_loop_control.py: replaced `hash(char_id)` in `_diverse_topic` with
  `_stable_index()` using SHA-256 over the UTF-8 char_id (seed-independent).
  Added `import hashlib`. Removed a duplicate `import time`.

Tests changed this pass:
- test_npc_loop_control.py: added test_13b (exact diverse-topic determinism),
  test_13c (exact complete decision determinism), test_13d (both content and
  description empty -> safe empty-string fallback). Total 17 tests.
- test_operator_acknowledgement.py: spy signatures now accept `**kwargs` and
  capture `attribution=`; assertions updated to verify attribution wiring.
  This REPAIRS the 8 pre-existing failures (0 failed now).
- import_smoke.py (NEW): clean-process import smoke that prints and validates
  absolute `__file__` for each module, proving worktree-local resolution.

New Redis keys / TTL / thresholds / reset (unchanged from prior pass):
- npc_loopctrl:defer:{cid}   int streak, TTL 600s
- npc_loopctrl:topic:{cid}   normalized topic word, TTL 600s
- npc_loopctrl:shapes:{cid}  capped list (cap 8), TTL 1800s
- Thresholds: >=2 same-topic deferral -> prohibit create_artifact on that topic;
  >=3 -> force read_artifacts/investigate/rest; >=4 repeated shapes -> force rest
  or investigate a deterministically selected different world topic.
- Reset only after genuinely different completed work (different normalized topic
  OR non-create_artifact category). Reworded same-topic title does NOT reset.
- No private content stored (only normalized topic word + category shape).
- Existing `_is_repetitive_artifact` dedup gate UNCHANGED (composed, not replaced).

Artifact-content fallback (corrected wording):
  `artifact_content = llm_result.get("content") or desc`
  Missing, null, or empty model content falls back to the decision description.
  A non-empty result is guaranteed ONLY when either model content OR description
  is non-empty. When BOTH are empty the result is an empty string (safe, no crash,
  no private body) - covered by test_13d.

## 4. Compile / import qualification — CORRECTED

- `python -m compileall -q` over npc_loop_control.py, npc_decisions.py,
  npc_actions.py, npc_agent.py, and all test files: exit 0.
- Real clean-process import executed (NOT merely AST parse) via import_smoke.py
  in isolated subprocesses with no live Redis/network. All four modules import
  successfully and resolve from THIS worktree (absolute __file__ validated):
    PYTHONHASHSEED=0   -> ALL IMPORTS RESOLVED FROM WORKTREE
    PYTHONHASHSEED=1   -> ALL IMPORTS RESOLVED FROM WORKTREE
    PYTHONHASHSEED=random -> ALL IMPORTS RESOLVED FROM WORKTREE
- Compile qualification: PASS. Clean-process import qualification: PASS.

## 5. Test evidence — CORRECTED

New loop-control tests (17) - all pass under PYTHONHASHSEED=0, =1, AND =random:
  test_1_first_and_second_deferral
  test_2_third_deferral_create_artifact_prohibited
  test_3_fourth_repeated_shape_hard_break
  test_4_reworded_titles_same_topic
  test_5_genuinely_different_topic_allowed
  test_6_streak_reset_only_after_different_work
  test_7_ttl_expiry
  test_8_separate_state_per_npc
  test_9_no_private_content_stored
  test_10_existing_dedup_untouched
  test_11_parser_fail_then_repair_success
  test_12_parser_and_repair_fail_truthful
  test_13_artifact_content_fallback_variants
  test_13b_diverse_topic_exact_determinism
  test_13c_diverse_topic_complete_decision_determinism
  test_13d_fallback_both_content_and_desc_empty
  test_14_caught_per_tick_exception_continues

Pre-existing modular regression tests (all 5 files, 84 tests):
  test_moderator_prompt_visibility.py   4 passed
  test_operator_enforcement.py          23 passed
  test_operator_llm_route.py            36 passed
  test_operator_acknowledgement.py      21 passed  (was 8 FAILED; now repaired)
  test_npc_loop_control.py              17 passed
  TOTAL: 101 passed, 0 failed, under each of the three seed settings.

Result hash (pytest summary line) identical across seeds: "101 passed".

## 6. Fake-Redis fidelity

Operations used by npc_loop_control and implemented by the fake backend:
  get, set(key,val,ex), incr, expire, ttl, exists, delete, rpush, lrange,
  ltrim, scan_iter  -> all 11 present with equivalent semantics.
- Per-NPC key isolation: namespaced by char_id (test_8).
- Expiry: set(ex=ttl) and expire() honored (test_7).
- Increment/update: incr for streak; rpush+ltrim(cap=8) for shape history.
- Delete/reset: delete() on genuinely-different work (test_6).
- Absent-key: get returns None; incr initializes 0; lrange returns [].
- Deterministic ordering: list appends in call order; no randomness.
- No private body storage: only normalized topic word + category shape stored.
Limitation: fake backend is in-memory only; it does not exercise Redis
cluster/network behavior, but covers every op the implementation uses.

## 7. Limitations

- PROVENANCE GAP RESOLVED: npc_actions.py was replaced with the byte-identical
  deployed VPS file (04555945...) and the 4 intended hunks replayed; git diff
  --no-index confirms no extra changes. All three edited modules
  (npc_agent.py, npc_decisions.py, npc_actions.py) are now proven to descend from
  deployed source.
- Cross-process determinism is now EXACT via SHA-256 (no Python hash()). Verified
  by test_13b/test_13c asserting the exact selected topic and complete decision.
- Runtime execution relies on sibling modules only at import (no live calls during
  import); full import was executed cleanly.

## 8. Final layered verdict

Local implementation:                 PASS
Authoritative provenance:             PASS
    npc_agent.py:    PASS (base == VPS ed599569...)
    npc_decisions.py: PASS (base == VPS fc99706b...)
    npc_actions.py:  PASS (resolved: replaced with byte-identical VPS 04555945...,
                           4 intended hunks replayed; git diff --no-index clean)
Compile:                              PASS
Clean-process imports:                PASS (real import, 4/4 modules, 3 seeds)
New tests:                            PASS (17/17, 3 seeds)
Existing regression tests:            PASS (84/84; prior 8 failures repaired -> 0 failed)
Cross-process exact determinism:      PASS (SHA-256; exact topic + decision asserted)
Fake-Redis fidelity:                  PASS (11/11 ops; no private content)
Eligible for separately authorized shadow deployment: YES (provenance now complete)
Live deployment authorization:        NOT AUTHORIZED
Push authorization:                   NOT AUTHORIZED