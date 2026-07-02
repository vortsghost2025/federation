# Horizon Status — Living Document
**Last Updated:** 2026-07-01 20:10
**Updated By:** Kilo (opencode)

## Current State

| Item | Value |
|------|-------|
| HEAD commit | c4545c5 |
| VPS health | All 16 containers up |
| Production URL | https://federation-game.deliberatefederation.cloud/ |
| SSH alias | `ssh federation-vps` |
| Dirty tree | 12 modified, 7 untracked (metrics/nginx/spectator fixes + P3/P4 extraction work) |
| /metrics | FIXED — returns 200 with world_state + 30 institution metrics |
| Nginx proxy routes | FIXED — 4 missing routes added (/error-reports, /councilor, /institutions, /decrees) |
| Error-reporter | FIXED — nginx 404 blocked it, now routes through to backend |
| Councilor proposals label | FIXED — "Councilor autonomy" → "Councilor proposals" (was misleading) |
| Institution metrics | FIXED — uses correct Redis key pattern `institution:index`, shows real role counts |
| Admin dashboard | DEPLOYED + VERIFIED — `/api/admin/status` returns full agent/pair state |
| P3 Outcome Memory | DEPLOYED + VERIFIED LIVE — 35/35 tests pass |

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
| (scp) | P007 Leader cognition retry loop fix (timeout+cooldown) | ✅ Yes |
| (none) | P008 Tracked scratch cleanup (delete-only) | ✅ Yes |
| (none) | P009 Session-startup probe (fed-state.sh + AGENTS hook) | ✅ Yes |
| a760cce | Starmap 3D cosmic scale-of-reality visual pass | ✅ Yes (frontend baked into container) |

## Dirty Tree Summary (2026-06-28)

- **2 modified files** — institutions.py + npc_autonomy.py (P3 outcome memory, committed but not yet pushed)
- **0 untracked files**

## In Progress

- (none)

## Blocked

- OpenRouter paid models fail with HTTP 402 — ALL 3 keys have no credits for paid models
- Gemini fails with HTTP 429 "Prepayment credits depleted" — silenced 1hr via Redis key

## Next Steps (Prioritized)

1. **Context window optimization** — ARCHITECTURE_STATE.md built; consider opencode config to trim 500+ skill list
2. **Push P3 changes** — institutions.py + npc_autonomy.py committed locally, need git push
3. **Frontend hardening** — error handling, loading states, offline resilience

## Agent File Ownership

| Agent | Role | Owns | Context |
|-------|------|------|---------|
| GLM-5.1 | Plan mode | Backend, docker-compose, plan packs | Varies (128K) |
| Nemotron 3 Ultra | Build mode | Frontend, code execution | Varies (1M) |
| Wave AI | Monitor/coordination | .horizon/, SSH config | — |
| Codex | Debug mode | Kilo IDE tooling | Idle |
| Kilo IDE | Debug mode | Kilo config | MiniMax-M2.7 (rate limited on Gemma) |

## Mode Discipline Rules (ENFORCED)

- **Plan mode (GLM)** = ONLY writes plan pack files to `session/bridge/{PLAN_ID}/`
- **Build mode (Nemotron)** = ONLY reads plan packs and writes code/config
- **No agent executes its own plan** — GLM plans, Nemotron builds
- **Swap timing** = agents tell Sean when to switch modes
- **After compaction** = read `.horizon/HORIZON_STATUS.md` BEFORE doing anything else
- **GLM must delegate ALL tool calls** to sub-agents to save context

## Key Decisions

| Date | Decision | Rationale | Who |
|------|----------|-----------|-----|
| 2026-06-07 | Event token over asyncio lock | Stateless, scales, no race | Wave AI + Codex + GLM |
| 2026-06-07 | state.py 3-file split | Monolith prevention | GLM-5.1 |
| 2026-06-07 | Alembic stamp-at-head | No data loss on existing tables | GLM-5.1 |
| 2026-06-07 | Pipe-over-SSH deploy | SCP from Windows unreliable | GLM-5.1 |
| 2026-06-07 | Mode assignment: Plan=GLM, Build=Nemotron | GLM sub-agent fanout; Nemotron 1M execution | GLM + Sean |
| 2026-06-07 | Bridge = plan delivery, not context survival | Same-session mode switches preserve context | GLM-5.1 |
| 2026-06-07 | No agent executes its own plan | Prevents race conditions | GLM + Sean |
| 2026-06-07 | Bridge storage = local files in session/bridge/ | Zero infra, git-trackable | GLM-5.1 |
| 2026-06-07 | 3-layer memory: L1 conversation, L2 handoff, L3 knowledge graph | Progressive persistence | GLM-5.1 |
| 2026-06-07 | context_pack.md <2000 tokens | Fits in compacted context | GLM-5.1 |
| 2026-06-07 | Plan IDs = sequential P001/P002 | Simple, easy to reference | GLM-5.1 |
| 2026-06-07 | Git-based VPS deploy | Atomic, resumable, instant rollback | GLM-5.1 |
| 2026-06-07 | Kilo .kilocode/skills quarantined | Reduced duplicate warnings 648→326 | Codex |

## Known Issues

1. DB init retry loop blocks test runner 30s+ if Postgres unreachable
2. Redis persist_npc_traits_to_redis hangs if Redis unreachable
3. gastown-rig/deploy.js modified but not committed
4. `.claude/skills` and `.agents/skills` still have duplicate warnings (326 remaining)
5. **NVIDIA API key leaked in commit `e587a11` (`.kilo/kilo.json`).** Working copy + index clean (`.kilo/kilo.json` gitignored, key blanked) but the old key is still in GitHub history at `vortsghost2025/federation`. **Action: rotate the key at `integrate.api.nvidia.com`. Sean needs sighted help from his brother to do the rotation — flagged 2026-06-15.** Until rotated, treat the leaked prefix `nvapi-s7xc…` as compromised.
6. **starmap3d.html NOT in Traefik router list** — served via nginx catch-all, not explicitly routed. May need Traefik rule update if caching/routing matters.
7. **Stash `b6250c9` unexamined** — may contain additional uncommitted work.

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
