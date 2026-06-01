# Federation Game Deployment Surface

This directory contains the live Federation simulation surface: frontend pages, backend API, worker process, Docker stack, and monitoring assets.

## Frontend Pages

The active frontend pages are:

- `index.html` - kid-facing simulator surface
- `adult.html` - adult control plane
- `bridge.html` - bridge command view
- `starmap.html` - spatial and faction map
- `simulation.html` - live simulation view
- `earth.html` - Earth status view
- `constellation.html` - constellation view
- `spectator.html` - spectator mode
- `worldguide.html` - lore and world reference

Each page now lives with companion assets in `frontend/` instead of carrying large inline CSS/JS blocks.

## Backend Layout

- `backend/main.py`
  Composition entrypoint for the FastAPI app
- `backend/routes/`
  Split route modules for the active API surface
- `backend/worker.py`
  Background autonomous tick worker
- `backend/npc_autonomy.py`
  NPC thoughts, moods, actions, goals, and related world updates
- `backend/simulation_engine.py`
  Simulation support logic
- `backend/smoke_test.py`
  Basic route verification used during backend checks

WebSocket handling already lives in `backend/routes/websocket.py`.

## Runtime Stack

The live VPS stack is described in `docker-compose-vps.yml` and currently consists of:

- Traefik reverse proxy
- Frontend nginx container
- FastAPI backend container
- Worker container
- PostgreSQL
- Redis
- Optional observability services such as Prometheus and Grafana

## How Updates Work

### Frontend

Frontend files live in `frontend/`, but the VPS serves them from the bind-mounted directory:

- VPS source: `/docker/federation-game/public_html/`
- Container path: `/usr/share/nginx/html`

Frontend changes need the updated files copied into the VPS bind mount. A full dev server is not required.

### Backend

Backend files live in `backend/`, and the VPS backend container reads from:

- VPS source: `/docker/federation-game/backend/`
- Container path: `/app`

Backend code changes usually require a backend container restart after sync.

## Verification

Useful checks:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/healthz
python backend/smoke_test.py
```

Live verification snapshot from June 1, 2026:

- 9 of 9 frontend pages returned `200`
- Static page links and checked assets returned `200`
- Backend smoke sweep passed `13/13`
- `/cognition`, `/narrator`, `/world`, and `/simulation` now return `200`

## Live URL

- `https://federation-game.deliberatefederation.cloud`
