# Federation

**Federation is a consciousness simulation - not a game.**

## What It Is

Federation is a persistent AI society simulator presented through a Star Trek LCARS surface. The frontend pages are only the visible layer. Underneath, the backend tracks NPC thoughts, moods, goals, faction pressure, world conditions, and broadcast events on a recurring simulation tick.

This repo is now centered on the `federation-game/` deployment surface rather than the older root-level monolith.

## What Is Live Right Now

- 9 frontend pages are part of the active surface:
  `index.html`, `adult.html`, `bridge.html`, `starmap.html`, `simulation.html`,
  `earth.html`, `constellation.html`, `spectator.html`, `worldguide.html`
- FastAPI backend with split route modules
- Dedicated worker process for autonomous simulation ticks
- Redis-backed fast state
- PostgreSQL snapshot persistence
- Traefik routing and TLS on the VPS
- Prometheus and Grafana observability on the VPS

## Current Architecture

### Core runtime

- `federation-game/frontend/`
  Static HTML, CSS, and JS served by nginx
- `federation-game/backend/main.py`
  Small composition entrypoint that mounts the backend routers
- `federation-game/backend/routes/`
  Split API surface, including `core`, `events`, `quests`, `npcs`, `simulation`,
  `world`, `cognition`, `narrator`, `factions`, `spatial`, `technology`,
  `timeline`, `history`, `political`, `consciousness`, `rivals`, and `websocket`
- `federation-game/backend/worker.py`
  Background tick process
- `federation-game/docker-compose-vps.yml`
  Main VPS stack description

### State and persistence

- Redis stores fast-changing simulation state
- PostgreSQL stores snapshots and survives backend restarts

## Verification Snapshot

Checked June 1, 2026:

- Live website page audit: 9 of 9 frontend page URLs returned `200`
- Static page-to-page links returned `200`
- Checked local CSS and JS asset links returned `200`
- Backend smoke sweep passed `13/13`
- Legacy compatibility endpoints now return `200`:
  `/cognition`, `/narrator`, `/world`, `/simulation`
- Existing problem routes also return `200`:
  `/event`, `/quests`, `/npcs/test/quest-chains`, `/npcs/test/goals`

Live URL:

- `https://federation-game.deliberatefederation.cloud`

## Repo Layout

```text
federation/
|- federation-game/
|  |- backend/
|  |- frontend/
|  |- monitoring/
|  |- docker-compose-vps.yml
|  `- README.md
|- docs/
|- session/
|- _archive/
|- COVENANT.md
|- GOVERNANCE.md
`- README.md
```

## What Still Needs Work

- Root cleanup pass 2 for stale files outside `federation-game/`
- Headless box monitoring
- Real auth instead of hardcoded simulation credentials
- Continued doc cleanup for older legacy notes

## Origin

Built by Sean David as a proof that meaningful systems can be made through human-AI collaboration without traditional gatekeeping.

## License

GNU GPL v3
