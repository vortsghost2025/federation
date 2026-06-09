# Simulation Briefing + NPC Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `simulation.html` understandable in 10 seconds by adding a plain-English briefing, an NPC Reality Feed, and Ollama-first assistant prompts.

**Architecture:** Keep the current single-page vanilla JS page. Add a top briefing renderer fed by existing `/simulation/status`, `/simulation/npcs/activity`, `/npcs/stats`, and NPC log APIs. Use `/api/npc-logs` when available for Postgres-backed history, with `/npcs/{char_id}/log` as fallback.

**Tech Stack:** Vanilla HTML/CSS/JS, FastAPI, Redis/Postgres NPC activity logs, existing `llm_router` with Ollama-first assistant routing.

---

### Task 1: Newcomer Briefing Block

**Files:**
- Modify: `federation-game/frontend/simulation.html`
- Modify: `federation-game/frontend/simulation.css`
- Modify: `federation-game/frontend/simulation.js`

- [ ] Add a `#human-briefing` block above the existing Situation Room.
- [ ] Render one headline, three explainer cards, and one CTA row for the AI chat.
- [ ] Source headline from existing world metrics and latest log/event data.
- [ ] Verify the page still loads at `/simulation.html`.

### Task 2: NPC Reality Feed

**Files:**
- Modify: `federation-game/frontend/simulation.html`
- Modify: `federation-game/frontend/simulation.css`
- Modify: `federation-game/frontend/simulation.js`

- [ ] Add `#npc-reality-feed` beneath the briefing.
- [ ] Load NPC list from `/npcs?limit=200`.
- [ ] Prefer `/api/npc-logs?char_id=<id>&limit=20`; fallback to `/npcs/<id>/log?limit=20`.
- [ ] Convert raw entries into human-readable rows: actor, type, summary, time, and importance.
- [ ] Add filter chips for All, Conversations, Decisions, Plans, Cognition, Alliances, Conflict.

### Task 3: Assistant Prompt Chips + Ollama First

**Files:**
- Modify: `federation-game/frontend/simulation.html`
- Modify: `federation-game/backend/llm_router.py` or `federation-game/backend/map_endpoints.py`

- [ ] Replace assistant suggestions with: `What is this simulation?`, `How does it work?`, `Explain what is happening right now.`, `Who is talking to who?`, `What are the NPCs planning?`, `Which NPC should I watch?`.
- [ ] Route assistant questions through Ollama first, then current NIM/OpenRouter chain.
- [ ] Verify `/map/assistant` returns provider `ollama` when available or a NIM provider when Ollama is unavailable.

### Task 4: Future Advanced Analyst Blueprint

**Files:**
- Create or update: `docs/ADVANCED_ANALYST_MODE_BLUEPRINT.md`

- [ ] Document the future C mode: full server-side CSV, pagination, model stats, tick diagnostics, faction graphs, raw logs, and debug telemetry.
- [ ] Do not implement C today.

---

### Verification

- [ ] `python -m pytest federation-game/backend/test_npc_stats_route.py -q`
- [ ] `curl -s -H "Host: federation-game.deliberatefederation.cloud" http://187.77.3.56/simulation.html` returns page HTML.
- [ ] `curl -s -H "Host: federation-game.deliberatefederation.cloud" http://187.77.3.56/npcs/stats` returns counts.
- [ ] Browser smoke check: briefing text visible, NPC feed visible, AI chips visible.

### Future C Blueprint

Advanced Analyst Mode should be a separate tab/page. It should expose raw telemetry, server-side NPC log pagination, server CSV export, full provider stats, tick diagnostics, faction power graphs, and debugging views without cluttering the newcomer default page.
