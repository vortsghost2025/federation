---
name: bridge-sync
description: Syncs bridge_state.json after milestones. Runs in build mode. Auto-invoked on major step completion, before compaction, or manually.
---

# bridge-sync

**Mode:** Build mode (Nemotron 3 Ultra)
**Purpose:** Persist progress to bridge_state.json so plan mode can resume context.

## Usage
```
bridge-sync milestone "Completed steps 1-3"
bridge-sync complete
```

## What it does
1. Reads current `bridge_state.json`
2. Updates fields:
   - `last_sync`: ISO8601 timestamp
   - `status`: "in_progress" | "completed" | "blocked" | "failed"
   - `plan_history`: append completed plan on `complete`
3. Writes updated JSON back

## Hard Rules
- ONLY runs in build mode
- ONLY modifies `session/bridge/bridge_state.json`
- Never modifies plan pack files
- Called automatically after major step groups

## Milestone Triggers
- After completing a logical step group (e.g., "skills created")
- Before potential context compaction
- On explicit user request "bridge sync"
- Before marking plan complete