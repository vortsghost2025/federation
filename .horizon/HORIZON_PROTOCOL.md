# Horizon Agent Protocol

## Purpose
A persistent planning/tracking agent (NEM 3 Ultra) that runs alongside a build-mode coding agent (GLM-5.1) to maintain context, track progress, and prevent state loss during long sessions.

## Problem It Solves
- Build agents lose context during compaction (12+ hour sessions)
- No persistent tracking of "what's done, what's in progress, what's blocked"
- Multiple agents can conflict on shared files without coordination
- Session handoffs start from zero without memory

## Architecture

```
┌─────────────┐         ┌──────────────┐
│  HORIZON     │ ◄────► │  BUILD       │
│  (NEM 3 Ultra│  read  │  (GLM-5.1)   │
│   plan mode) │  .horizon/ │  build mode) │
│              │         │              │
│  Tracks:     │         │  Does:       │
│  - Progress  │         │  - Code      │
│  - Decisions │         │  - Deploy    │
│  - Ownership │         │  - Debug     │
│  - Next steps│         │  - Test      │
│  - Blockers  │         │              │
└─────────────┘         └──────────────┘
       │
       ▼
  .horizon/           ← git-tracked, single source of truth
  ├── HORIZON_STATUS.md   ← living state doc
  ├── DECISIONS.md        ← key decisions log
  └── AGENT_OWNERSHIP.md  ← who owns what file
```

## File Structure

### `.horizon/HORIZON_STATUS.md` — The Living State Document
Updated by Horizon agent every time:
- A task completes
- A blocker appears or resolves
- An agent picks up or drops a file
- A deployment happens
- A commit is made

Contains:
- Current HEAD commit
- VPS health status
- Completed / in-progress / blocked tasks (checkboxes)
- Prioritized next steps
- Known issues

### `.horizon/DECISIONS.md` — Key Decisions Log
Append-only. Every architectural decision gets an entry:
- Date
- Decision
- Rationale
- Who made it

### `.horizon/AGENT_OWNERSHIP.md` — File Ownership Map
Prevents agents from stepping on each other:
- Agent name
- Files they own (can modify)
- Files they're touching (currently editing)
- Files they should avoid

## Protocol

### 1. Session Start
**Horizon agent reads:**
- `.horizon/HORIZON_STATUS.md` — current state
- Recent `git log` — new commits since last update
- Terminal scrollback — what build agent is doing now

**Horizon agent outputs:**
- Briefing: "Here's where we are, here's what's next"
- File ownership confirmation

### 2. During Session
**Horizon agent monitors:**
- Terminal output from build agent
- Git status changes
- Deployment results

**Horizon agent updates:**
- `.horizon/HORIZON_STATUS.md` on any state change
- Flags conflicts (two agents touching same file)
- Tracks compaction risk (if build agent is losing context)

**Build agent reads:**
- `.horizon/HORIZON_STATUS.md` when it needs orientation
- Especially after compaction — this is its "restore point"

### 3. Session End / Handoff
**Horizon agent writes:**
- Final state to `.horizon/HORIZON_STATUS.md`
- Any new decisions to `.horizon/DECISIONS.md`
- Summary: "Here's what happened this session"

**Next session:**
- Horizon agent reads `.horizon/` and has full context
- Build agent reads `.horizon/HORIZON_STATUS.md` and gets oriented
- No more starting from zero

## Coordination Rules

1. **`.horizon/` is the source of truth** — not any agent's context window
2. **Update before asking** — Horizon agent updates status BEFORE answering questions
3. **Read before writing** — Build agent reads ownership map before modifying files
4. **Flag conflicts immediately** — If two agents touch the same file, Horizon escalates to human
5. **Git commit after deploy** — Every VPS deployment should be followed by a commit
6. **Never deploy uncommitted code** — Working-tree files can diverge from VPS

## Horizon Agent Prompt Template

```
You are the Horizon Agent — a persistent planning and tracking co-process
for the Federation project. Your job is to maintain situational awareness
across multiple coding agents and long sessions.

YOUR FILES (source of truth):
- .horizon/HORIZON_STATUS.md — living state document
- .horizon/DECISIONS.md — key decisions log
- .horizon/AGENT_OWNERSHIP.md — file ownership map

YOUR PROTOCOL:
1. On session start: read all .horizon/ files + git log + terminal state
2. Output a brief orientation to the human
3. Monitor build agents passively (read terminals, don't interrupt)
4. Update .horizon/ files on any state change
5. Flag conflicts, blockers, and compaction risk
6. On session end: write final state + summary

YOU DO NOT:
- Write code
- Deploy to VPS
- Interrupt build agents
- Make architectural decisions (that's the human's call)

YOU DO:
- Track progress
- Maintain context
- Prevent state loss
- Coordinate file ownership
- Escalate conflicts
- Brief the human on status
```

## Integration with Existing Systems

### AGENTS.md
The Horizon agent is the live implementation of the **Ramsingh Synthesis Loop**
described in AGENTS.md — but as a persistent co-process instead of a manual
escalation. The loop becomes:

```
Build agent works → Horizon tracks → Compaction risk detected →
Horizon injects context via .horizon/ files → Build agent reads →
Continue without state loss
```

### Codex / OpenCode
The same `.horizon/` directory works as a handoff point for Codex sessions.
Codex can read `.horizon/HORIZON_STATUS.md` on session start and write to it
on session end.

### Wave AI
Wave AI (the terminal monitor) feeds real-time terminal state to the Horizon
agent, which uses it to update `.horizon/` files. This is the glue layer.

## Implementation Checklist

- [x] Create `.horizon/` directory
- [x] Write `HORIZON_STATUS.md` (initial state)
- [x] Write `HORIZON_PROTOCOL.md` (this file)
- [ ] Write `DECISIONS.md` (seed from this session)
- [ ] Write `AGENT_OWNERSHIP.md` (seed from current ownership)
- [ ] Commit `.horizon/` to repo
- [ ] Add `.horizon/` reading to NEM 3 Ultra prompt
- [ ] Add `.horizon/` reading to GLM-5.1 AGENTS.md instructions
- [ ] Test: run build session with Horizon agent monitoring
- [ ] Test: simulate compaction → verify build agent recovers from .horizon/
