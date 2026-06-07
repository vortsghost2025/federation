---
name: bridge-write
description: Plan mode skill — writes plan packs to session/bridge/. Use ONLY in plan mode (GLM 5.1). Creates P001, P002, etc. with all 5 required files. Enforces schema from SCHEMA.md.
---

# bridge-write

**Mode:** Plan mode only (GLM 5.1)
**Purpose:** Create plan packs that build mode (Nemotron) will execute.

## Usage
```
bridge-write create P001 "Build Agent Bridge System"
```

## What it does
1. Creates `session/bridge/P001/` directory
2. Writes 5 files from TEMPLATE/ populated with plan-specific content:
   - `plan.md` — numbered implementation steps
   - `context_pack.md` — compressed context (<2000 tokens)
   - `file_targets.json` — machine-readable create/modify/delete arrays
   - `constraints.md` — hard rules for this plan
   - `verification.md` — pass/fail executable checks
3. Updates `bridge_state.json` with active_plan, status, last_sync
4. Validates context_pack.md token budget (<500 words ≈ <2000 tokens)

## Hard Rules
- ONLY runs in plan mode — fails if invoked in build mode
- ONLY writes to `session/bridge/` and `.opencode/skills/`
- NEVER modifies backend code, Docker configs, or VPS files
- All JSON must be valid (2-space indent)
- context_pack.md must stay under 2000 tokens

## File Targets (this skill creates)
- session/bridge/{PLAN_ID}/plan.md
- session/bridge/{PLAN_ID}/context_pack.md
- session/bridge/{PLAN_ID}/file_targets.json
- session/bridge/{PLAN_ID}/constraints.md
- session/bridge/{PLAN_ID}/verification.md
- session/bridge/bridge_state.json (updates)