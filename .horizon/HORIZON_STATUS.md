# Horizon Status — Living Document
**Last Updated:** 2026-06-24 20:20
**Updated By:** Kilo (mimo-v2.5-free)

## Current State

| Item | Value |
|------|-------|
| HEAD commit | a760cce |
| VPS health | All containers up (frontend 19h, backend 19h, worker 16min, NPC agents 19h) |
| Production URL | https://federation-game.deliberatefederation.cloud/ |
| SSH alias | `ssh hostinger` or `ssh federation-vps` (public IP 187.77.3.56) |
| Dirty tree | 38 modified, 42 untracked |
| Race condition | FIXED end-to-end — backend + frontend both use choice_token |
| Spatial mode | DEPLOYED — sticky flag live on production |
| Starmap 3D | DEPLOYED — cosmic scale-of-reality visual pass live on VPS |

## Completed This Session

- [x] Race condition fix (event tokens) — backend deployed, verified
- [x] state.py refactor (3-file split) — deployed
- [x] Alembic migrations — deployed
- [x] docker-compose.yml indentation — validated, deployed
- [x] Stability recovery mechanic — deployed
- [x] Frontend self-recovery (stale choice_token) — deployed
- [x] Starmap tab fix — deployed
- [x] SSH config cleanup — done locally (Wave AI)
- [x] Root cleanup (~50 debug scripts) — done
- [x] Continuity handoff docs — committed (994ba2e)
- [x] Race fix dead code cleanup (core.py line 679) — done locally (Wave AI)
- [x] .horizon/ system created — HORIZON_STATUS, PROTOCOL, DECISIONS, AGENT_OWNERSHIP
- [x] P001 — Bridge system — completed, committed (1c04c40)
- [x] P002 — Frontend choice_token integration — completed, committed (b66d9e1), deployed to VPS
- [x] P003 — Spatial mode sticky flag — completed, committed (b66d9e1), deployed to VPS
- [x] Kilo duplicate skill cleanup — quarantined .kilocode/skills, warnings dropped 648→326
- [x] P004 — Frontend Error Hardening via fed-fetch.js — completed, deployed to VPS
- [x] P005 — Dead Code Cleanup + Redis/DB Timeout Fixes — completed, deployed to VPS
- [x] P006 — Full Redis Timeout Hardening — completed, deployed to VPS
- [x] P007 — Leader cognition retry loop fix (timeout+cooldown) — committed (4b592da), deployed to VPS, verified live
- [x] P008 — Tracked scratch-file cleanup — committed (538a6dc), 29 files removed, .gitignore hardened
- [x] P009 — Session-startup probe (fed-state.sh + AGENTS hook) — committed (eef00e3), future agents auto-load fed-state on session start
- [x] P010 — Recover deployed chat-NPC improvements — committed (8265504); npc_autonomy.py rewrite + npc_event_log.py added back to git. The 26 remaining dirty-tree files are unchanged and still need individual review.

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

## Dirty Tree Summary (2026-06-24)

- **38 modified files** — mostly backend/frontend changes from starmap + NPC work
- **42 untracked files** — includes screenshots, session scratch, debug scripts, archived docs
- **Stash:** `b6250c9` exists (may contain additional uncommitted work)
- **Local ahead of remote** by several commits (starmap 3D work)

## In Progress

- **P011 — NPC Agency system** — code complete, needs VPS deploy
  - Artifact registry + inter-NPC messaging + sandbox executor + cognition upgrade
  - Commit: `27a2921` (tag: `p011-npc-agency`)
  - See `docs/NPC_AGENCY_LOG.md` for full build log

## Blocked

- (none)

## Next Steps (Prioritized)

1. **Deploy P011 to VPS** — build sandbox image, `docker compose up -d`, restart backend+worker
2. **Clean dirty tree** — categorize 38 modified + 42 untracked files, commit starmap work, gitignore temp files
3. **Examine stash `b6250c9`** — may contain additional uncommitted work
4. **VPS git deploy script** — automate `git pull → cp → docker restart` pattern
5. **Frontend hardening** — error handling, loading states, offline resilience
6. **Update starmap3d.html Traefik routing** — add to router list if needed

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
