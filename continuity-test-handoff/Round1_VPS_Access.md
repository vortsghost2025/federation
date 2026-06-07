# VPS Access & Deploy Guide

## SSH Aliases

| Alias | IP | Works? | Notes |
|-------|-----|--------|-------|
| `hostinger` | 187.77.3.56 | YES | Has IdentityFile, public IP — USE THIS |
| `hostinger-vps` | 100.75.95.23 | NO | Points to unreachable Tailscale IP |
| `vps` | 100.75.95.23 | NO | Same broken Tailscale IP |

## Deploy Method

SCP from Windows times out (>60s). Use pipe-over-SSH:

```powershell
# Single file
type local\file.py | ssh hostinger "cat > /docker/federation-game/backend/file.py"

# Restart backend
ssh hostinger "cd /docker/federation-game && docker compose restart backend"

# Health check
curl -s -o /dev/null -w "%{http_code}" https://federation-game.deliberatefederation.cloud/healthz

# Check container status
ssh hostinger "cd /docker/federation-game && docker compose ps backend"

# View logs (last 20)
ssh hostinger "cd /docker/federation-game && docker compose logs --tail 20 backend"
```

## VPS File Locations

- Backend code: `/docker/federation-game/backend/`
- Docker compose: `/docker/federation-game/docker-compose.yml`
- Alembic: `/docker/federation-game/backend/alembic/`
- No git repo on VPS — files deployed manually, editing = editing production

## Critical Rules

1. **Never add `--workers N` (N>1)** to docker-compose.yml — breaks game_state singleton
2. **`/choose` must always return `"outcome"` key** — frontend calls `.outcome.toUpperCase()`
3. **`gs.current_event = None` after choice is intentional** — don't remove it
4. **Always verify after editing VPS files** — you're editing production directly
