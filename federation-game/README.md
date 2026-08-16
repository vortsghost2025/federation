# Federation Game – Deployment Guide

## Prerequisites
- Docker Engine (>= 20.10) and Docker Compose v2
- At least **4 GB RAM** on the target VPS (recommended 2 GB for containers, 1 GB for PostgreSQL, 0.5 GB for Redis, rest for app)
- Domain name pointing to the VPS IP (e.g. `federation-game.deliberatefederation.cloud`).

## Project layout (after pulling the repo)
```
/docker/federation-game/
├─ docker-compose.yml          # Base services (reverse‑proxy, backend, frontend, worker, DB, Redis)
├─ docker-compose.staging.yml  # Override for staging environment
├─ docker-compose.prod.yml     # Override for production environment
├─ README.md                  # This documentation
└─ letsencrypt/                # Traefik TLS storage (auto‑created on first run)
```

The actual application source lives outside the compose directory under the shared volume:
```
/var/lib/docker/volumes/agent-zero-qcyl_agent-zero-data/_data/projects/project_1/
├─ federation-game/
│   ├─ backend/      ← FastAPI server (Python)
│   ├─ frontend/     ← Nginx static site (HTML/JS)
│   └─ public_html/  ← UI assets mounted into the Nginx container
```

## Quick start (local development)
```bash
# Clone the repository (if you haven't already)
# git clone <repo‑url> federation-game
# cd federation-game

# Build and start all services in the background
docker compose -f /docker/federation-game/docker-compose.yml up -d
```

The reverse‑proxy (Traefik) will expose the site on **http://localhost** (or your domain if DNS is set). Traefik dashboards are reachable at `http://localhost:8080` (insecure mode is enabled for debugging).

## Staging deployment
```bash
docker compose -f /docker/federation-game/docker-compose.yml \
    -f /docker/federation-game/docker-compose.staging.yml up -d
```
Staging uses a separate PostgreSQL database (`federation_staging`). The same code base is deployed, only the DB name changes.

## Production deployment
```bash
docker compose -f /docker/federation-game/docker-compose.yml \
    -f /docker/federation-game/docker-compose.prod.yml up -d
```
Production points to the main `federation` database. Make sure the domain’s DNS record points to the VPS and that port 80/443 are open.

## Service details
| Service | Image / Build | Purpose |
|---------|--------------|---------|
| **reverse-proxy** | `traefik:latest` | Handles TLS termination, routes `https://<domain>/api/` → backend and `https://<domain>/` → frontend.
| **frontend** | Custom Nginx (`/frontend/Dockerfile`) + bind‑mount of `public_html` | Serves static UI, JavaScript client, assets.
| **backend** | Custom Python (`/backend/Dockerfile`) | FastAPI API + WebSocket. Provides `/login`, `/state/save`, `/state/load`, `/state`, `/event`, `/choose/{id}` etc.
| **worker** | Same image as backend, runs `worker.py` | Placeholder for background jobs (e.g., session cleanup, AI agents). Can be extended.
| **postgres** | `postgres:15-alpine` | Persistent relational store for future world‑state persistence.
| **redis** | `redis:7-alpine` | In‑memory cache / pub‑sub for real‑time updates.

## Health checks & logging
- All services use `restart: unless-stopped` – Docker restarts them on crash.
- Traefik exposes health checks via its dashboard.
- Backend and worker log to `stdout`; Docker captures JSON logs (view with `docker logs <container>`).
- PostgreSQL and Redis expose built‑in health endpoints (optional can be added via `docker healthcheck`).

## Backup & export (PostgreSQL)
A simple cron container can dump the database:
```yaml
  backup:
    image: alpine:latest
    command: ["sh", "-c", "apk add --no-cache postgresql-client && pg_dump -h postgres -U federation federation > /backups/federation_$(date +%F).sql"]
    environment:
      PGPASSWORD: federation_pwd
    volumes:
      - ./backups:/backups
    depends_on:
      - postgres
    restart: "no"
```
Run it manually (`docker compose run backup`) or schedule via host `cron`.

## Testing the core loop
1. **Login** – POST to `https://<domain>/login` with JSON `{"username":"player1","password":"password1"}`; store the returned `access_token`.
2. **Save state** – `POST https://<domain>/state/save` with the game JSON payload and header `Authorization: Bearer <token>`.
3. **Load state** – `GET https://<domain>/state/load` with the same header.
4. **Play** – The UI can now call `/api/state`, `/api/event`, `/api/choose/<id>` (ensure the client adds the `Authorization` header). The backend returns the updated world.

## Next steps
- Wire the UI (`public_html/game/*.js`) to call the new `/api/…` endpoints instead of local storage.
- Replace the temporary in‑memory `PLAYER_STATE` with proper tables (SQLAlchemy models) and migrations.
- Add JWT signing, password hashing, and user registration.
- Implement background worker logic for periodic world ticks, AI agents, or event queues.

---
**All files added/modified**
- `backend/auth_endpoints.py` (new) – login, session, save/load API.
- `backend/main.py` – include auth router.
- `backend/worker.py` (new) – placeholder background worker.
- `docker/federation-game/docker-compose.yml` – modular services, reverse proxy, DB, Redis.
- `docker/federation-game/docker-compose.staging.yml` – staging DB override.
- `docker/federation-game/docker-compose.prod.yml` – production DB override.
- `docker/federation-game/README.md` – deployment guide.

---
**Remaining blockers**
- **UI integration** – Front‑end JavaScript still uses localStorage; it must be updated to call the new `/api/` endpoints (login, state save/load, actions). This requires changes to `game/*.js` and possibly new helper functions.
- **Database schema** – The backend currently stores state only in‑memory (`PLAYER_STATE`). To persist across restarts we need SQLAlchemy models and migration scripts (e.g., Alembic) for `players`, `world_state`, `sessions`.
- **Authentication security** – Current login uses a plain‑text user dict. Production should use hashed passwords and a proper user table.
- **Worker implementation** – The placeholder `worker.py` does nothing beyond logging. Real background tasks (e.g., periodic world tick, AI processing) need to be implemented.
- **TLS certificates** – Traefik is configured for Let's Encrypt but requires a reachable domain and open ports 80/443 for automatic issuance.
- **Testing** – No automated tests exist for the new auth / state endpoints. Add unit/integration tests to `backend/tests/` and integrate into CI.

Once these blockers are addressed, the Federation game will be fully playable, stable, and easy to deploy on a modest 4 GB VPS.
---
**Note**: The reverse‑proxy now listens on host ports **8080** (HTTP) and **8443** (HTTPS) to avoid conflicts with any existing services on ports 80/443. Adjust any local testing URLs accordingly (e.g., `http://localhost:8080`).
