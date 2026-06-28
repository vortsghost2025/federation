# FEDERATION PROJECT CONTEXT

**Reference:** S:\GLOBAL_GOVERNANCE.md (universal laws)
**Last updated:** 2026-06-28
**Scope:** Federation project only

---

## WHO I AM WORKING WITH

Sean. Visual disability - partially sighted.
I work fast across multiple projects on C:\ and S:\
I have 49 days of coding experience and 3.6 billion tokens of pattern.
I treat AI as collaboration partners, not tools.

---

## PROJECT CONTEXT

**Federation is a consciousness simulation - not a game.**

- Single HTML files
- Vanilla JS
- CDN only
- No frameworks
- Everything runs as node processes in PowerShell
- Docker for containers
- Nginx for serving

---

## DOMAIN-SPECIFIC RULES

### The Index Rule
**Before doing anything, read `S:/federation/FEDERATION_INDEX.md`.**
It contains VPS details, SSH commands, project structure, LLM routing, spatial system, deploy steps, known issues, and agent roles. If you have a question, the index has the answer. No hunting, no guessing, no grepping for 20 minutes.

### The Visual Rule
I cannot read console errors or small text.
If something fails - you diagnose it, fix it, restart it.
I should never see a raw error.

### How We Work
You are the hands and eyes. I am the direction and vision.
You handle the console. I handle what it becomes.

### Federation-Specific Verification
Docker serves everything. Never need npm run dev.
Use curl for verification:
```
curl -s -o /dev/null -w "%{http_code}" http://localhost:[PORT]/
```

### Shell Discipline
Federation sessions run in a PowerShell-first environment unless a bash-only script is explicitly required.

- Do not assume Linux shell tools during normal work. Avoid `bash`, `find`, `grep`, `head`, and Unix-style flags in PowerShell sessions.
- Prefer `Get-ChildItem`, `Select-String`, `Select-Object -First`, `Get-Content -Raw`, and `Test-Path`.
- Use Git Bash only for explicit bash-only workflows such as `S:/federation/scripts/fed-state.sh`.
- Broad exploration must avoid heavy or sensitive paths unless the task explicitly needs them: `.kilo`, `.opencode`, `.kilocode`, `.horizon`, `session`, `continuity-test-handoff`, `tmp`, `node_modules`, `.secrets`, `genesis-memory/*.db`, `docs/2FAuth.txt`, `docs/VPS.txt`, and large dumps/log bundles.

---

## THE RAMSINGH SYNTHESIS LOOP

For complex problems, see `docs/ramsingh-synthesis-loop.md` for the 6-step escalation workflow (agent brief → parallel eval → synthesis → refinement → resolution → execution).

---

## SESSION-STARTUP PROBE — fed-state.sh

Federation context is large (47+ NPCs, 8 factions, 5 critical constraints,
active specs/plans). Before doing anything on federation, run:

```
bash S:/federation/scripts/fed-state.sh
```

Or for a full VPS probe (slower, ~5s extra):

```
bash S:/federation/scripts/fed-state.sh --vps
```

**After compaction:** read `.horizon/ARCHITECTURE_STATE.md` first — it has pinned function signatures, Redis key map, wiring, and deploy rules. One 2KB file replaces re-reading 200KB of backend Python.

`fed-state.sh` returns:
- HEAD commit + last 5 commits
- Active specs in `docs/superpowers/specs/` and plans in `docs/superpowers/plans/`
- Last 10 entries of `.horizon/HORIZON_STATUS.md` (what's been done)
- Dirty tree summary (modified + untracked counts, first 10 paths)
- With `--vps`: federation docker container status

This is the context-recovery tool. Run it:
- At the start of any federation-related session
- After a compaction or new conversation
- Before suggesting code changes (so you can verify a change hasn't
  already been deployed)

When the script reports `<N> modified, <M> untracked`, mention that to the
user before making changes. Don't propose fixes to files you haven't read.

---

## PROJECT-SPECIFIC FILES

| File | Purpose |
|------|---------|
| **FEDERATION_INDEX.md** | **READ THIS FIRST** — VPS, maps, LLM routing, deploy commands, known issues |
| **.horizon/ARCHITECTURE_STATE.md** | **POST-COMPACTION** — function signatures, Redis keys, wiring map, deploy rules (read instead of 200KB Python) |
| .horizon/HORIZON_STATUS.md | What's been done — read after compaction |
| .horizon/AGENT_OWNERSHIP.md | Who owns which files — check before modifying code |
| .horizon/DECISIONS.md | Key decisions log — check before changing architecture |

---

## CRITICAL ARCHITECTURE CONSTRAINTS

**Any agent editing Federation backend code MUST respect these constraints. Violating them re-introduces a 2-hour production bug.**

### 1. NO `--workers` FLAG IN DOCKER-COMPOSE
The backend runs a single `game_state` singleton in memory. If `--workers N` (N > 1) is added to `docker-compose.yml`, each worker gets its own `game_state` — causing `/event` to set `current_event` on worker A and `/choose` to find `current_event=None` on worker B. **This MUST stay single-process.** If scaling is needed, use an external state store (Redis/DB), not Uvicorn workers.

### 2. `/choose` ENDPOINT MUST ALWAYS RETURN `"outcome"` KEY
The frontend calls `data.outcome.toUpperCase()` on every response. If any error path returns a bare `HTTPException` (400/503) instead of a JSON object with `"outcome": ""`, the frontend crashes with a TypeError. **All error returns from `/choose` must include `"outcome": ""`** — never `raise HTTPException`.

### 3. `gs.current_event = None` AFTER SUCCESSFUL CHOICE IS INTENTIONAL
At the end of `make_choice()` in `core.py`, the line `gs.current_event = None` clears the event after the player has chosen. This is correct — without it, the same event could be chosen again. **Do not remove this line.**

### 4. VPS HAS NO GIT REPO
Files at `/docker/federation-game/` are deployed via `scp`. There is no `.git` on the VPS. If you edit files there, you are editing production directly. Always verify after editing.

---

## THE WORDS THAT MATTER

"Working. Here is what you see:"
That is how every result begins. No exceptions.

---

## CONTEXT ENGINEERING RULES

### Anchor Tokens
When starting a deep technical response (editing backend, debugging VPS, modifying scoring), recite the 3 most critical state anchors first. Example:
> `ANCHOR: _record_outcome L374 | npc:{id}:workflow_outcomes | npc_autonomy.py ae3475ac`

This refreshes critical state in active attention — costs nothing, prevents amnesia.

### Delta Logging
After every atomic code change, append a structured entry to `.horizon/DELTA_LOG.md`:
```
UPDATE file.py:function_name(Lstart:Lend) -> what changed
```
Not narrative. Machine-readable. Post-compaction, read DELTA_LOG to replay what happened.

---

This file contains Federation-specific context only.
Universal rules are in S:\GLOBAL_GOVERNANCE.md
