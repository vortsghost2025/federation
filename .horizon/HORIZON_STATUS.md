# Horizon Status — Living Document
**Last Updated:** 2026-07-03
**Updated By:** GLM-5.2 (z-ai orchestrator)

## Current State

| Item | Value |
|------|-------|
| HEAD commit | 88d44a3 (branch: bridge/memory-phase-1) |
| VPS health | All containers up (production: 187.77.3.56) |
| Production URL | https://federation-game.deliberatefederation.cloud/ |
| SSH alias | `ssh federation-vps` (resolves to 187.77.3.56) |
| Dirty tree | 1 untracked (.kilo-federation-profile/) — no modified files |
| Race condition | FIXED end-to-end — backend + frontend both use choice_token |
| Spatial mode | DEPLOYED — sticky flag live on production |
| Starmap 3D | DEPLOYED — cosmic scale-of-reality visual pass live on VPS |
| P3 Outcome Memory | DEPLOYED + VERIFIED LIVE — 35/35 tests pass |
| Phase 1 Memory Bridge | COMMITTED + DEPLOYED LIVE — both councilors recording Redis memories across ticks |
| NPC Autonomy refactor | ⚠ DRIFT — home `npc_autonomy.py` is the post-extraction (06-30) version; live VPS file is pre-extraction monolith. Deploy pending verification. See "Known Issues" #8 |
| P007 Cognition Loop Fix | PARTIAL — Edit 1 (30s leader timeout) deployed; Edit 2 (LEADER/SPECIALIST cooldown constants + `_set_cooldown`) never implemented. See "Known Issues" #9 |

## Completed 2026-06-27 to 2026-06-28 (P0-P4 + Agency + Decrees + P3)

- [x] P0 — need_reflection propagation bug fix — COMMITTED + DEPLOYED LIVE
- [x] Councilor Decrees v0 — 3 endpoints, rule-based evaluation — COMMITTED + DEPLOYED LIVE
- [x] DECREES_ALLOWED_NPCS whitespace strip fix — COMMITTED + DEPLOYED
- [x] P0 Bridge bug fix — fulfilled needs suppress repeat request_capability — COMMITTED + DEPLOYED
- [x] P1 Smoke test — PASSED
- [x] P2 Directive system — decree-based world-state bias — DEPLOYED LIVE (22/22 directive tests pass)
- [x] P4 Traefik security — API disabled, Grafana pw via env var, postgres restored — COMMITTED + DEPLOYED
- [x] Councilor topic loop fix — four-prong fix (dedup + override + partner + pivot)
- [x] 3 autonomy actions — create_institution, propose_role, submit_to_institution — DEPLOYED
- [x] Needs queue + enhancements A/B/C — DEPLOYED + VERIFIED LIVE
- [x] Prometheus/Grafana metrics — DEPLOYED + VERIFIED (commit 943accc)
- [x] OpenRouter free pool rotation — 3 keys, 3 tier pools, round-robin + per-model CB — COMMITTED
- [x] Gemini depleted cooldown — Redis-backed 1hr silence — COMMITTED
- [x] Ollama 404 fix — OLLAMA_BASE_URL must include /v1
- [x] P3 Workflow Outcome Memory — FULLY DEPLOYED + VERIFIED LIVE
  - institutions.py + npc_autonomy.py md5s verified on all 4 containers
  - 35/35 test_needs_queue.py tests pass (13 new P3 tests)
  - Live scoring verified: 3 rejections → advance_goal suppressed 42%; 3 approvals → boosted 15%
- [x] .horizon/ARCHITECTURE_STATE.md — compressed backend state for post-compaction recovery

## Completed 2026-06-24 (Starmap 3D Visual Pass)

- [x] Starmap 3D Three.js visualization — committed (`a760cce`)
- [x] Cosmic scale-of-reality visual pass — LOCAL/GALAXY/DEEP modes with multi-layer starfield, nebula, horizon band, cluster markers, scale labels (`2ba0035`)
- [x] Dramatic cosmic scale — 8x-25x camera distance between modes (`c28b9dc`)
- [x] LOD scale modes — faction clouds for DEEP, NPC/sector visibility per mode (`9f35109`)
- [x] Deep-space atmosphere pass — multi-layer starfield, scale-reactive grid/boundary (`e57d4ea`)
- [x] Merge conflict resolution in starmap3d.html (`a760cce`)
- [x] Starmap 3D deployed to VPS — verified live via HTTP

## Completed 2026-06-30 (NPC Autonomy Module Extraction Wave)

11-commit refactoring wave that split the monolithic `npc_autonomy.py` into sibling modules. **Home copy refactored; deploy to VPS pending verification** — see Known Issues #8.

- [x] `1cfcf71` [2.1] Extract npc_needs.py — 3 funcs + 6 constants, re-export shim
- [x] `6b088a8` [2.2] Extract npc_world.py — 386 lines, 6 funcs, 6 constants — DEPLOYED LIVE
- [x] `fabf8eb` [2.3] Extract npc_decree.py — broadcast + decree system
- [x] `f191a97` [2.3] fix: reconcile journal status — 3 stale LOCAL_COMPILES/NOT_YET_DEPLOYED references updated to DEPLOYED LIVE
- [x] `6803790` [2.4] Extract npc_reflection.py — decision reflection + scoring
- [x] `1c60a72` [3]   Extract npc_thoughts.py — LLM calls, thought generation, prompt filtering
- [x] `3e31a99` [4]   Extract npc_opinions.py — opinions + moods system
- [x] `664347f` [5]   Extract npc_actions.py — action templates + generation
- [x] `a1d1f71` [6]   Extract npc_interactions.py — relationships + dialogue system
- [x] `c4545c5` [7]   Extract npc_goals.py — wire existing goals module + extract from npc_autonomy
- [x] Earlier in wave: `3dc7379`[1.6] npc_actions execute_decision+update_mood (604 lines); `93dcb2b`[1.5] npc_decisions.py + npc_agent.py reconstruction (1353→708 lines, 6 bug fixes); `6e7a0fe`[1.4] npc_context.py (19 funcs, -795 lines); `4397984`[1.3] npc_llm_client.py; `2ad1196` Phase 0-1 infra + npc_redis_helpers.py

**Result:** monolithic `npc_autonomy.py` deployed on VPS is ~180 lines (hash `274420c1...`); home copy is ~1,000 lines / 29KB post-extraction (hash `d1c2f7d6...`). architecture-state pin `ae3475ac` describes now-defunct monolith — see Known Issues #8.

## Completed 2026-07-01 (Phase 1 — Memory Bridge)

Both councilors verified recording Redis memories across ticks. Deployed live.

- [x] `f6cbcdb` cherry-pick bridge plan from deploy/fix-2026-07-01
- [x] `3ea42d7` phase1: add councilor memory bridge
- [x] `88d44a3` phase1: add memory bridge tests (current HEAD)

**Verified live (2026-07-03 session):** both councilors (char_001 = research_chief_mathematician, char_306 = collective_oracle) recording Redis memories across ticks.

## Deploy History

| Commit | What | Deployed? |
|--------|------|-----------|
| b5bcc06 | state refactor, event tokens, alembic, docker-compose | ✅ Yes |
| 994ba2e | Continuity handoff docs | N/A (docs only) |
| 1c04c40 | Bridge system P001 + .horizon/ tracking | N/A (infra) |
| b66d9e1 | P002 choice_token + P003 spatial mode | ✅ Yes |
| (scp) | P004 Frontend Error Hardening | ✅ Yes |
| (scp) | P005 Dead code removal + Redis/DB timeouts | ✅ Yes |
| (scp) | P006 Full Redis timeout hardening (5 files) | ✅ Yes |
| (scp) | P007 Leader cognition retry loop fix (timeout+cooldown) | ⚠ PARTIAL — Edit 1 (timeout 30s) deployed; Edit 2 (cooldown constants) never implemented |
| (none) | P008 Tracked scratch cleanup (delete-only) | ✅ Yes |
| (none) | P009 Session-startup probe (fed-state.sh + AGENTS hook) | ✅ Yes |
| a760cce | Starmap 3D cosmic scale-of-reality visual pass | ✅ Yes (frontend baked into container) |
| 4554282 (06-28) | P3 outcome memory + context engineering (ARCHITECTURE_STATE, DELTA_LOG, CONFIG_MAP) | ✅ Yes (35/35 tests) |
| 005fc9f (06-28) | Directive system + security hardening (Grafana env var, postgres restored) | ✅ Yes |
| 943accc (06-27) | Prometheus metrics endpoint + Grafana needs-queue dashboard | ✅ Yes |
| e1dc671 (06-27) | Institutions module — seed, bind, proposal_review workflow | ✅ Yes |
| 06-30 wave (11 commits) | NPC autonomy module extraction (npc_needs/world/decree/reflection/thoughts/opinions/actions/interactions/goals + npc_decisions/context/llm_client) | ⚠ Home only — NOT deployed to VPS (see Known Issues #8) |
| f6cbcdb, 3ea42d7, 88d44a3 (07-01) | Phase 1 memory bridge — councilor memory bridge + tests | ✅ Deployed live; verified both councilors recording Redis memories across ticks |

## Dirty Tree Summary (2026-07-03)

- **0 modified files**
- **1 untracked file** — `.kilo-federation-profile/` (Kilo profile dir)
- Branch: `bridge/memory-phase-1` at HEAD `88d44a3`

## In Progress

- (none)

## Blocked

- OpenRouter paid models fail with HTTP 402 — ALL 3 keys have no credits for paid models
- Gemini fails with HTTP 429 "Prepayment credits depleted" — silenced 1hr via Redis key

## Next Steps (Prioritized)

1. **Resolve npc_autonomy.py deploy drift** — home post-extraction (~1,000 lines / 29KB / hash d1c2f7d6) vs live VPS pre-extraction (~180 lines / 7KB / hash 274420c1). Before any deploy, verify the extracted sibling modules (npc_needs/world/decree/reflection/thoughts/opinions/actions/interactions/goals + npc_decisions/context/llm_client) resolve cleanly together. See Known Issues #8.
2. **Finish P007** — implement Edit 2 (LEADER_COOLDOWN_FAILURE / SPECIALIST_COOLDOWN_FAILURE constants + `_set_cooldown` accepting explicit duration) in `llm_router.py`, then deploy + verify. See Known Issues #9.
3. **Refresh ARCHITECTURE_STATE.md** — stale pin (npc_autonomy L2396/L2838 describes defunct monolith); needs removal + replacement with reality. See ARCHITECTURE_STATE Known Issues #1 inline.
4. **Frontend hardening** — error handling, loading states, offline resilience.

## Agent File Ownership

See `.horizon/AGENT_OWNERSHIP.md` for current agent ownership and mode discipline.

## Mode Discipline Rules (ENFORCED)

- **Plan mode (GLM)** = ONLY writes plan pack files to `session/bridge/{PLAN_ID}/`
- **Build mode (Nemotron)** = ONLY reads plan packs and writes code/config
- **No agent executes its own plan** — GLM plans, Nemotron builds
- **Swap timing** = agents tell Sean when to switch modes
- **After compaction** = read `.horizon/HORIZON_STATUS.md` BEFORE doing anything else
- **GLM must delegate ALL tool calls** to sub-agents to save context

## Key Decisions

See `.horizon/DECISIONS.md` for the full decisions log.

## Known Issues

1. DB init retry loop blocks test runner 30s+ if Postgres unreachable
2. Redis persist_npc_traits_to_redis hangs if Redis unreachable
3. gastown-rig/deploy.js modified but not committed
4. `.claude/skills` and `.agents/skills` still have duplicate warnings (326 remaining)
5. **NVIDIA API key leaked in commit `e587a11` (`.kilo/kilo.json`).** Working copy + index clean (`.kilo/kilo.json` gitignored, key blanked) but the old key is still in GitHub history at `vortsghost2025/federation`. **Action: rotate the key at `integrate.api.nvidia.com`. Sean needs sighted help from his brother to do the rotation — flagged 2026-06-15.** Until rotated, treat the leaked prefix `nvapi-s7xc…` as compromised.
6. **starmap3d.html NOT in Traefik router list** — served via nginx catch-all, not explicitly routed. May need Traefik rule update if caching/routing matters.
7. **Stash `b6250c9` unexamined** — may contain additional uncommitted work.
8. **npc_autonomy.py DRIFT home vs VPS** (flagged 2026-07-03). Home hash `d1c2f7d6...` (29KB, post-extraction) ≠ VPS hash `274420c1...` (7KB, pre-extraction monolith). The 06-30 extraction wave (11 commits `[2.1]`→`[7]`) split monolithic npc_autonomy.py into `npc_needs/world/decree/reflection/thoughts/opinions/actions/interactions/goals` + `npc_decrees/context/llm_client`. Sibling modules verified identical home ↔ VPS, but the orchestration file itself was NOT pushed. Post-extraction home imports `from npc_reflection import evaluate_decision_options, _score_decision_option, _reflect_on_missing_context, _write_decree_directive` etc. — these resolve downstream once the VPS gets the matching home copies. Action: verify the full extraction set deploys atomically before any `deploy_vps.sh npc-agent npc_autonomy.py` runs.
9. **P007 only partially implemented** (flagged 2026-07-03). Edit 1 (leader cognition timeout 8s→30s on all 4 leader tiers in `llm_router.py:870,877,884,891`) is live on VPS. Edit 2 (constants `LEADER_COOLDOWN_FAILURE` and `SPECIALIST_COOLDOWN_FAILURE`, function `_set_cooldown` accepting explicit duration) was **never implemented** — grep returns zero matches in both home and VPS. Current cooldown is the coarse fixed `_trip_circuit` (3 failures → `llm_circuit_breaker:{provider}` open for 300s, no per-task-class differentiation). Acceptance criteria for P007 spec are NOT met.

## Architecture

```
Frontend (index.html + JS) → Traefik (TLS) → Backend (FastAPI :8000, single worker)
  → PostgreSQL (Docker internal)
  → Redis (Docker internal)
```

- Single worker enforced — multi-worker breaks game_state singleton
- VPS: 187.77.3.56 — use `ssh hostinger` or `ssh federation-vps`
- VPS deploy: git pull from /opt/federation → cp to /docker/federation-game/ → docker restart
- No git on VPS /docker/ — files deployed via /opt/federation git pull + cp
