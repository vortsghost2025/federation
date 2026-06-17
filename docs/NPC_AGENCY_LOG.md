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
| 1. Artifact registry | `backend/npc_artifacts.py` | Completed | Part of P011 |
| 2. Inter-NPC message bus | `backend/npc_messaging.py` | Completed | Part of P011 |
| 3. Sandbox executor | `backend/npc_sandbox.py` + `npc-sandbox/` | Completed | Part of P011 |
| 4. Cognition upgrade | `backend/npc_cognition.py` | Completed | Part of P011 |
| 5. Docker wiring | `docker-compose-vps.yml` | Completed | Part of P011 |
| 6. Deploy & verify | VPS | Pending | — |

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

---

