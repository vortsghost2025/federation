# Bridge System Schema

## Overview
The bridge system enables persistent coordination between plan mode (GLM 5.1) and build mode (Nemotron 3 Ultra) across sessions, compaction events, and multi-agent workflows.

**Storage:** Local files in `session/bridge/` — zero infrastructure, git-trackable.

**Format:** JSON + Markdown — machine + human readable, diffable.

---

## Plan Pack Format (5 Files)

Each plan pack lives in `session/bridge/{PLAN_ID}/` and contains:

### 1. `plan.md` — Implementation Steps
- Numbered, sequential steps
- Each step: action + target file(s) + expected outcome
- No prose, just execution instructions

### 2. `context_pack.md` — Compressed Context (<2000 tokens)
- Project essentials: what, why, how
- Key constraints (hard limits, not preferences)
- Critical file paths
- Current state summary
- **Token budget: ~1500 words max**

### 3. `file_targets.json` — Machine-Readable File Operations
```json
{
  "create": ["path/to/file1", "path/to/file2"],
  "modify": ["path/to/existing"],
  "delete": ["path/to/remove"]
}
```

### 4. `constraints.md` — Hard Rules (Never Violate)
- Architectural invariants
- Security boundaries
- Performance ceilings
- Forbidden patterns

### 5. `verification.md` — Pass/Fail Checks
- Executable commands
- Expected outputs
- No ambiguity — each check is binary pass/fail

---

## Bridge State Schema (`session/bridge/bridge_state.json`)

```json
{
  "version": "1.0",
  "schema_version": "1.0",
  "active_plan": "P001",
  "active_plan_path": "session/bridge/P001/",
  "status": "in_progress" | "completed" | "blocked" | "failed",
  "last_sync": "ISO8601 timestamp",
  "plan_history": [
    {
      "plan_id": "P001",
      "title": "Build Agent Bridge System",
      "status": "completed",
      "completed_at": "ISO8601 timestamp"
    }
  ],
  "agent_namespace": "nemotron-build",
  "session_id": "20260607_XXXXXX"
}
```

**Fields:**
- `version` — Bridge system version
- `schema_version` — Schema version for migrations
- `active_plan` — Current plan ID
- `active_plan_path` — Path to active plan pack
- `status` — One of: `in_progress`, `completed`, `blocked`, `failed`
- `last_sync` — When bridge_state was last updated
- `plan_history` — Array of completed plans with metadata
- `agent_namespace` — Isolates multi-agent runs (e.g., `glm-plan`, `nemotron-build`)
- `session_id` — Unique session identifier

---

## Multi-Agent Isolation

Directory structure:
```
session/bridge/
├── .gitkeep
├── SCHEMA.md
├── bridge_state.json
├── TEMPLATE/
│   ├── plan.md
│   ├── context_pack.md
│   ├── file_targets.json
│   ├── constraints.md
│   └── verification.md
├── P001/
│   ├── plan.md
│   ├── context_pack.md
│   ├── file_targets.json
│   ├── constraints.md
│   └── verification.md
└── P002/
    └── ...
```

**Agent namespacing:** Each agent writes to `session/bridge/{agent_namespace}/{session_id}/`

---

## Sync Protocol

**Plan mode writes:**
1. Creates plan pack in `session/bridge/{PLAN_ID}/`
2. Updates `bridge_state.json` with `active_plan`, `status: "in_progress"`, `last_sync`
3. Signals "swap to build mode"

**Build mode reads:**
1. Reads `bridge_state.json` → gets `active_plan_path`
2. Loads all 5 files from plan pack into working memory
3. Executes step by step
4. After each milestone: updates `bridge_state.json` with progress

**Auto-sync on milestones:**
- After completing a major step group
- Before potential compaction
- On explicit "bridge-sync" skill invocation

---

## Token Budget Enforcement

- `context_pack.md` target: <2000 tokens (~1500 words)
- Use `wc -w` to verify: `cat context_pack.md | wc -w` should return < 1800
- If over budget: summarize further, move detail to plan.md or constraints.md

---

## Versioning

- `schema_version` in bridge_state.json tracks schema compatibility
- Plan packs are immutable once written — new plans get new IDs
- Breaking schema changes = new `schema_version` + migration guide in SCHEMA.md