# Horizon Status — Living Document
**Last Updated:** 2026-06-07 14:50
**Updated By:** Wave AI

## Current State

| Item | Value |
|------|-------|
| HEAD commit | 994ba2e |
| VPS health | All containers up, backend healthy |
| Production URL | https://federation-game.deliberatefederation.cloud/ |
| SSH alias | `ssh hostinger` (public IP 187.77.3.56) |
| Active agents | GLM-5.1 (plan mode), NEM 3 Ultra (build mode) |
| Bridge system | Operational — P001 completed ✅ |
| Bridge status | `session/bridge/bridge_state.json` → status="completed" |

## Completed This Session

- [x] Race condition fix (event tokens) — deployed, verified
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
- [x] .horizon/ system created — HORIZON_STATUS, PROTOCOL, DECISIONS, AGENT_OWNERSHIP (Wave AI)
- [x] Bridge system P001 — completed by Nemotron, all 8 verification checks passed

## Bridge System (P001 — Completed)

| Deliverable | Size | Status |
|-------------|------|--------|
| `session/bridge/bridge_state.json` | — | ✅ version=1.0, status=completed |
| `session/bridge/SCHEMA.md` | 4KB | ✅ Created |
| `session/bridge/TEMPLATE/` (5 files) | — | ✅ All templates |
| `.opencode/skills/bridge-write/SKILL.md` | 1543B | ✅ Plan mode writer |
| `.opencode/skills/bridge-read/SKILL.md` | 1590B | ✅ Build mode executor |
| `.opencode/skills/bridge-sync/SKILL.md` | 1024B | ✅ Milestone sync |
| `session/bridge/P001/` (5 plan pack files) | — | ✅ All present, verified |

## In Progress

- [ ] Spatial mode auto-activation (NEM 3 Ultra owns — needs P002 plan pack from GLM)
- [ ] Frontend needs to send choice_token on /choose requests
- [ ] Commit bridge system + .horizon/ to repo

## Blocked

- (none)

## Next Steps (Prioritized)

1. **Commit bridge system + .horizon/ to repo** — everything on disk, nothing committed yet
2. **GLM writes P002 plan pack** — spatial mode fix (using bridge-write skill)
3. **Swap to build mode** — Nemotron executes P002 (using bridge-read skill)
4. **Frontend choice_token integration** — index.js/starmap.js need to capture `choice_token` from `/event` response and send it as query param on `/choose`
5. **DB init test blocking** — 3-attempt retry loop hangs tests 30s+ when Postgres unreachable
6. **Redis test blocking** — persist_npc_traits_to_redis hangs when Redis unreachable

## Agent File Ownership

| Agent | Role | Owns | Context |
|-------|------|------|---------|
| GLM-5.1 | Plan mode | Backend (state, routes, db, alembic), docker-compose.yml | 100K/128K (76%) 🔴 |
| NEM 3 Ultra | Build mode | Frontend (starmap.js, starmap.html, starmap.css) | 116K/1M (12%) 🟢 |
| Wave AI | Monitor/coordination | .horizon/, SSH config | — |
| Codex (done) | Previous session | Race fix files (handed off to GLM) | — |

## Mode Discipline Rules (ENFORCED)

- **Plan mode (GLM)** = ONLY writes plan pack files to `session/bridge/{PLAN_ID}/`
- **Build mode (Nemotron)** = ONLY reads plan packs and writes code/config
- **No agent executes its own plan** — GLM plans, Nemotron builds
- **Swap timing** = agents tell Sean when to switch modes

## Key Decisions

| Date | Decision | Rationale | Who |
|------|----------|-----------|-----|
| 2026-06-07 | Event token over asyncio lock | Stateless, scales, no race | Wave AI + Codex + GLM |
| 2026-06-07 | state.py 3-file split | Monolith prevention | GLM-5.1 |
| 2026-06-07 | Alembic stamp-at-head strategy | No data loss on existing tables | GLM-5.1 |
| 2026-06-07 | Pipe-over-SSH deploy method | SCP from Windows unreliable | GLM-5.1 |
| 2026-06-07 | Mode assignment: Plan=GLM, Build=Nemotron | GLM sub-agent fanout negates 128k; Nemotron 1M handles execution | GLM + Sean |
| 2026-06-07 | Bridge purpose = plan delivery, not context survival | Same-session mode switches preserve context natively | GLM-5.1 |
| 2026-06-07 | No agent executes its own plan | Prevents race conditions like P001 build collision | GLM + Sean |

## Known Issues

1. DB init retry loop blocks test runner 30s+ if Postgres unreachable
2. Redis persist_npc_traits_to_redis hangs if Redis unreachable
3. gastown-rig/deploy.js modified but not committed
4. Frontend doesn't send choice_token yet — race fix only works server-side
5. GLM at 76% context — high compaction risk, may need fresh session

## Architecture

```
Frontend (index.html + JS) → Traefik (TLS) → Backend (FastAPI :8000, single worker)
  → PostgreSQL (Docker internal)
  → Redis (Docker internal)
```

- Single worker enforced — multi-worker breaks game_state singleton
- VPS: 187.77.3.56 — use `ssh hostinger` only
- No git on VPS — files deployed manually, editing = editing production
