# Context Pack: P001

## Project
Federation = consciousness simulation (not a game). Single HTML + vanilla JS frontend, FastAPI backend, Docker on VPS.

## Mode Assignment
- **Plan mode**: GLM 5.1 (sub-agent fanout negates 128k limit)
- **Build mode**: Nemotron 3 Ultra (1M token context handles execution without compaction)

## Current State (HEAD 994ba2e)
- Production healthy: /healthz 200, /event returns choice_token UUID
- Backend single-worker enforced (multi-worker broke game_state singleton)
- `/choose` always returns `"outcome"` key
- `gs.current_event = None` after choice is intentional
- Alembic migrations deployed, state.py refactored (1109→485 lines)
- VPS: 187.77.3.56, only `ssh hostinger` works
- Production: federation-game.deliberatefederation.cloud (TLS via Traefik)

## Bridge Architecture (3-layer)
- L1: session-memory skill (per-repo durable state)
- L2: structured handoff files in `session/bridge/` (this system)
- L3: knowledge graph (future)

## Plan Pack Format
`session/bridge/{PLAN_ID}/` with 5 files: plan.md, context_pack.md, file_targets.json, constraints.md, verification.md

## Key Files
- SCHEMA.md — bridge system schema (exists)
- TEMPLATE/ — skeleton files (exist)
- bridge_state.json — active plan tracking (created by P001)
- 3 skills: bridge-write, bridge-read, bridge-sync (created by P001)

## Token Budget
<2000 tokens (~500 words)