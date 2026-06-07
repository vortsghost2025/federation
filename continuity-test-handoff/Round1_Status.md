# Federation Continuity Test — Round 1 Status
**Date:** 2026-06-07
**Commit:** b5bcc06
**Production URL:** https://federation-game.deliberatefederation.cloud/

## Production Health

| Check | Result |
|-------|--------|
| /healthz | 200 OK |
| /event | Returns choice_token + UUID |
| Backend container | Up, healthy |
| Traefik routing | Working (TLS via letsencrypt) |
| DB + Redis | Connected (backend logs confirm) |

## What Was Done This Round

1. **state.py refactor** — 1109→485 lines; split into state_constants.py (489 lines) + state_helpers.py (255 lines) + state.py; all consumer imports backward-compatible via re-exports
2. **Event token flow** — /event returns choice_token UUID; /choose validates it; prevents race condition where wrong worker processes a choice
3. **Alembic migrations** — alembic.ini, env.py, script.py.mako, initial migration (GameSnapshot table); _run_alembic_upgrade() in federation_game_db.py with stamp-if-exists + upgrade path; create_all() fallback
4. **docker-compose.yml fix** — all 10 `deploy:` blocks re-indented from 2→4 space under parent services; validated with `docker compose config --quiet`
5. **Stability recovery** — apply_governance_pressure() now has recovery path when metrics drop below death-spiral thresholds
6. **Frontend self-recovery** — index.js detects stale choice_token, auto-requests new event
7. **VPS deploy** — all backend files + alembic + docker-compose.yml deployed via pipe-over-SSH; backend restarted; health verified
8. **Root cleanup** — ~50 debug/diag scripts + 11 root debug .py files deleted from repo
9. **Git commit** — b5bcc06 pushed to main

## Architecture

```
Frontend (index.html + JS) → Traefik (TLS) → Backend (FastAPI :8000, single worker)
                                              → PostgreSQL (Docker internal)
                                              → Redis (Docker internal)
```

- **No host port mapping** — Traefik routes all traffic internally
- **Single worker enforced** — multi-worker breaks game_state singleton
- **VPS:** 187.77.3.56 (srv1345984.hstgr.cloud) — use `ssh hostinger` alias only

## Known Issues / Technical Debt

1. SSH config has duplicate `hostinger-vps` entries pointing to wrong Tailscale IP (100.75.95.23) — only `hostinger` alias works
2. DB init retry loop blocks test runner 30s+ if Postgres unreachable (3 attempts with sleep)
3. Redis `persist_npc_traits_to_redis` hangs if Redis unreachable — must mock in tests
4. `gastown-rig/deploy.js` modified but not part of Federation core — left unstaged
5. Multiple docs/ and photos/ untracked files — not committed (not project code)

## Key File Map

| File | Purpose |
|------|---------|
| state.py | GameState class + singleton (485 lines) |
| state_constants.py | All constant dicts, flags, thresholds (489 lines) |
| state_helpers.py | Helper functions with late import pattern (255 lines) |
| federation_game_db.py | DB manager, GameSnapshot model, alembic integration |
| routes/core.py | /choose endpoint — validates choice_token |
| routes/events.py | /event endpoint — returns choice_token UUID |
| routes/npcs.py | NPC endpoints |
| spatial_state.py | is_spatial_enabled() — re-exported by state.py |
| event_cascade.py | get_cascade_summary() — re-exported by state.py |
| alembic.ini + env.py | Alembic migration config |
| docker-compose.yml | All 10 services with deploy blocks |
