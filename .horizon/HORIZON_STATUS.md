# Horizon Status — Living Document
**Last Updated:** 2026-06-10 18:30
**Updated By:** GLM-5.1

## Current State

| Item | Value |
|------|-------|
| HEAD commit | b66d9e1 |
| VPS health | All containers up, frontend restarted |
| Production URL | https://federation-game.deliberatefederation.cloud/ |
| SSH alias | `ssh hostinger` or `ssh federation-vps` (public IP 187.77.3.56) |
| Active agents | GLM-5.1 (plan), Nemotron 3 Ultra (build), Codex (debug), Kilo IDE (MiniMax-M2.7) |
| Bridge system | Operational — P001–P006 all completed |
| Bridge status | `session/bridge/bridge_state.json` → status="completed" (P006) |
| Race condition | FIXED end-to-end — backend + frontend both use choice_token |
| Spatial mode | DEPLOYED — sticky flag live on production |

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
- [x] P007 — Leader cognition retry loop fix (timeout+cooldown) — implemented, deploy pending

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
| (scp) | P007 Leader cognition retry loop fix (timeout+cooldown) | ⏳ pending deploy |

## In Progress

- (none)

## Blocked

- (none)

## Next Steps (Prioritized)

1. **VPS git deploy script** — automate `git pull → cp → docker restart` pattern
2. **Frontend hardening** — error handling, loading states, offline resilience
3. **P007** — TBD (will plan when needed)

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
4. GLM at 76% context in 128K — high compaction risk
5. Kilo IDE hit Gemma 4 rate limit — fell back to MiniMax-M2.7
6. `.horizon/HORIZON_STATUS.md` was stale (said HEAD=994ba2e, should be b66d9e1) — now updated
7. `.claude/skills` and `.agents/skills` still have duplicate warnings (326 remaining)

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
