# NPC Agency Build Log
**Started:** 2026-06-17
**Build Agent:** OpenCode (deepseek-v4-flash-free)
**Project:** Giving Federation NPCs real agency — sandboxed creation, artifacts, messaging

---

## Checkpoint 0 — Pre-build snapshot
**2026-06-17 — Save point created**

- Committed all dirty state as `pre-npc-agency` branch/tag
- Current HEAD: `bf0d99b`
- 23 modified files, 1 untracked dir
- Journal started: `session/NPC_AGENCY_LOG.md`

**Rollback:** `git checkout pre-npc-agency` or `git reset --hard <commit-hash>`

---

## Build Plan — Phase 1: NPC Agency Core

| Step | File(s) | Status | Commit |
|------|---------|--------|--------|
| 1. Artifact registry | `backend/npc_artifacts.py` | Completed | `27a2921` (P011) |
| 2. Inter-NPC message bus | `backend/npc_messaging.py` | Completed | `27a2921` (P011) |
| 3. Sandbox executor | `backend/npc_sandbox.py` + `npc-sandbox/` | Completed | `27a2921` (P011) |
| 4. Cognition upgrade | `backend/npc_cognition.py` | Completed | `27a2921` (P011) |
| 5. Docker wiring | `docker-compose-vps.yml` | Completed | `27a2921` (P011) |
| 6. Deploy & verify | VPS | Pending | — |

### Commits
- `27a2921` — feat(agency): NPC agency system — artifacts, messaging, sandbox execution
- `1082b42` — checkpoint(pre-npc-agency): save point (tag: `pre-npc-agency`)
- Tag `p011-npc-agency` — P011 milestone

### Rollback
```bash
git checkout pre-npc-agency
```

### Files Created
- `backend/npc_artifacts.py` — Artifact registry (Redis index + disk + content in Redis)
- `backend/npc_messaging.py` — Inter-NPC message bus (inbox, threads, context)
- `backend/npc_sandbox.py` — Backend client for sandbox executor
- `npc-sandbox/server.py` — Sandbox container (subprocess isolation, 30s timeout)
- `npc-sandbox/Dockerfile` — Python 3.11-slim, restricted user
- `npc-sandbox/requirements.txt` — fastapi, uvicorn, pydantic

### Files Modified
- `backend/npc_cognition.py` — New categories (create_artifact, write_code, send_message, read_artifacts), artifact/message context in prompts, execution handlers
- `docker-compose-vps.yml` — Added npc-sandbox service + artifacts_data volume + SANDBOX_URL env vars

---

## Agent Handoff — Next Agent Instructions

If the build agent runs out of credits, the next agent should:

1. Read this file (`docs/NPC_AGENCY_LOG.md`) for full context
2. Read `.horizon/HORIZON_STATUS.md` for current state
3. Deploy P011 to VPS (see deploy steps below)

### Deploy Steps (for next agent)

```bash
# 1. SSH into VPS
ssh hostinger

# 2. Pull latest code
cd /opt/federation
git pull

# 3. Copy new files to Docker locations
cp /opt/federation/federation-game/backend/npc_artifacts.py /docker/federation-game/backend/
cp /opt/federation/federation-game/backend/npc_messaging.py /docker/federation-game/backend/
cp /opt/federation/federation-game/backend/npc_sandbox.py /docker/federation-game/backend/
cp /opt/federation/federation-game/backend/npc_cognition.py /docker/federation-game/backend/

cp -r /opt/federation/federation-game/npc-sandbox /docker/federation-game/
cp /opt/federation/federation-game/docker-compose-vps.yml /docker/federation-game/docker-compose.yml

# 4. Rebuild and start sandbox
cd /docker/federation-game
docker compose build npc-sandbox
docker compose up -d npc-sandbox
docker compose restart backend worker

# 5. Verify
curl -s http://localhost:9002/health
docker compose ps
docker logs federation-game-worker-1 --tail 20
```

### Rollback
```bash
git checkout pre-npc-agency
```
Then revert docker-compose.yml and restart everything on VPS.

---

