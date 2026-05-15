# Federation Game — Star Trek LCARS Edition

A turn-based federation management simulation with a full LCARS web interface, deployed as Docker containers.

## Two Game Surfaces

### Starship Simulator (`index.html`)
Kid-friendly LCARS interface. Big buttons, immediate feedback, one-tap actions.

### Adult Control Plane (`adult.html`)
Full strategic interface. Faction politics, technology trees, NPC relationships, quest management, and the decision ledger.

## Quick Start (Docker)

```bash
# Start all services
docker-compose up --build

# Open the Starship Simulator
open http://localhost:3000

# Open the Adult Control Plane
open http://localhost:3000/adult.html
```

## Ports

| Service | Port |
|---------|------|
| Frontend (nginx) | 3000 |
| Backend API (FastAPI) | 8000 |
| PostgreSQL | 5432 |

## How It Works

The backend (`main.py`) is a thin FastAPI shim that imports the game engine modules bind-mounted from the parent directory:

```
backend container /app/
├── main.py              ← FastAPI shim (this directory)
├── game_engine.py       ← bind-mounted from ../federation_game_console.py
├── events.py            ← bind-mounted from ../federation_game_events.py
├── factions.py          ← bind-mounted from ../federation_game_factions.py
├── npcs.py              ← bind-mounted from ../federation_game_npcs.py
├── quests.py            ← bind-mounted from ../federation_game_quests.py
├── state.py             ← bind-mounted from ../federation_game_state.py
├── technology.py        ← bind-mounted from ../federation_game_technology.py
└── turns.py             ← bind-mounted from ../federation_game_turns.py
```

**Backend changes** take effect with `docker compose restart backend` (source is bind-mounted).

**Frontend changes** require `docker compose build frontend && docker compose up -d frontend` (HTML is baked into the nginx image).

## VPS Deployment

The live deployment runs on a Hostinger VPS with 7 containers (Traefik, frontend, backend, worker, postgres, redis, reverse-proxy).

Live at **[federation-game.deliberatefederation.cloud](https://federation-game.deliberatefederation.cloud)**

---

*Made with love for a son 3000km away.*
