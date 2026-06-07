# FEDERATION PROJECT CONTEXT

**Reference:** S:\GLOBAL_GOVERNANCE.md (universal laws)
**Last updated:** 2026-04-16
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

---

## THE RAMSINGH SYNTHESIS LOOP

Federation-specific escalation workflow for complex problems:

**STEP 1 - AGENT GENERATES BRIEF**
Stuck agent produces PROJECT SUMMARY BRIEF

**STEP 2 - PARALLEL EVALUATION**
Brief goes to lmarena battle mode:
- Model A: Claude (latest)
- Model B: GPT (latest)
Both answer simultaneously

**STEP 3 - SYNTHESIS REQUEST**
Both answers go to Claude single model:
"Here is a problem and two solutions. Take the best of both. Add your own insight. Give me one superior answer."

**STEP 4 - PARALLEL REFINEMENT**
Synthesized answer goes back to battle mode
Both models refine and implement
Two implementation approaches produced

**STEP 5 - FINAL RESOLUTION**
Both implementations go to Claude single model
Final answer produced
Saved as 3 documents:
- Solution_A.txt
- Solution_B.txt
- Final_Synthesis.txt

**STEP 6 - EXECUTION**
File paths handed to coding agent
Agent implements from documents
Agent tests, fixes, reports in plain language

---

## PROJECT-SPECIFIC FILES

| File | Purpose |
|------|---------|
| BOOTSTRAP.md | Entry point for Federation |
| COVENANT.md | Values specific to consciousness simulation |
| GOVERNANCE.md | Rules specific to Federation architecture |

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

This file contains Federation-specific context only.
Universal rules are in S:\GLOBAL_GOVERNANCE.md
