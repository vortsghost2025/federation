---
name: bridge-read
description: Build mode skill — reads plan packs from session/bridge/ and loads them into working memory. Use ONLY in build mode (Nemotron 3 Ultra). Executes plan step by step.
---

# bridge-read

**Mode:** Build mode only (Nemotron 3 Ultra)
**Purpose:** Load and execute plan packs written by plan mode.

## Usage
```
bridge-read load P001
bridge-read status
```

## What it does
1. Reads `session/bridge/bridge_state.json` → gets `active_plan_path`
2. Loads all 5 files from plan pack into working memory:
   - `constraints.md` — read FIRST, hard rules to obey
   - `context_pack.md` — project context, key files, constraints
   - `plan.md` — numbered steps to execute
   - `file_targets.json` — machine-readable file operations
   - `verification.md` — pass/fail checks to run after
3. Executes plan.md steps sequentially
4. After each milestone: updates `bridge_state.json` with progress

## Hard Rules
- ONLY runs in build mode — fails if invoked in plan mode
- READS plan packs, WRITES code/config files per plan
- NEVER modifies plan pack files (they're immutable)
- Must run verification.md checks before marking complete

## File Targets (this skill reads)
- session/bridge/bridge_state.json
- session/bridge/{PLAN_ID}/plan.md
- session/bridge/{PLAN_ID}/context_pack.md
- session/bridge/{PLAN_ID}/file_targets.json
- session/bridge/{PLAN_ID}/constraints.md
- session/bridge/{PLAN_ID}/verification.md

## Output
- Updates bridge_state.json with progress/status
- Creates/modifies/deletes files per file_targets.json
- Runs verification commands