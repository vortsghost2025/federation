# Context Pack: {PLAN_ID}

## Project
Federation = consciousness simulation (not a game). Single HTML + vanilla JS frontend, FastAPI backend, Docker on VPS.

## Mode Assignment
- **Plan mode**: GLM 5.1 (sub-agent fanout negates 128k limit)
- **Build mode**: Nemotron 3 Ultra (1M token context handles execution without compaction)

## Current State
[Recent wins, production health, HEAD commit]

## Key Constraints
- Backend single-worker enforced (multi-worker broke game_state singleton)
- `/choose` must always return `"outcome"` key
- `gs.current_event = None` after choice is intentional
- VPS: 187.77.3.56, only `ssh hostinger` works
- Production: federation-game.deliberatefederation.cloud (TLS via Traefik)

## Relevant Files
[Key file paths for this plan]

## Token Budget
<2000 tokens (~500 words)