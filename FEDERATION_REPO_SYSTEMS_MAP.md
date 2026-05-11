# FEDERATION REPO SYSTEMS MAP

---

## 1. Executive Summary

- **Total lines of source code & assets**: **3,117**
- **Live Web Surface** (HTML pages actively served): **2** files (`index.html`, `adult.html`) → **~41%** of total lines.
- **Live API Surface** (backend endpoints): **1** module (`backend/main.py`) → **~37%** of lines.
- **Engine‑Ready but not directly exposed**: The core engine systems live inside `backend/main.py` but are only partially visible through the generic `/engine-status` endpoint. They constitute **~20%** of the codebase.
- **Test‑only assets**: _None_ in the repository at present.
- **Documentation‑only assets**: `README.md`, Docker‑files, `docker-compose.yml`, `requirements.txt`, Nginx configuration → **~2%** of lines.
- **Archive / lineage**: `__pycache__/` compiled byte‑code – not part of the source.
- **Unused / unknown**: `frontend/earth.html` (no navigation or import references) → **~0.6%** of lines.

> **Bottom line:** Roughly **78 %** of the repository is already live (web + API). The remaining **engine‑ready** portion is implemented but hidden from the UI, and a tiny fraction appears unused.

---

## 2. Live Web Surface

| Path | Description | Deployed Route | Primary API Calls |
|------|-------------|---------------|-------------------|
| `frontend/index.html` | Main player UI (kid‑friendly). | `/` (served by Nginx) | `/api/state`, `/api/event`, `/api/choose/{id}`, `/api/reset` |
| `frontend/adult.html` | Advanced UI that shows engine diagnostics. | `/adult.html` (served by Nginx) | `/api/atlas`, `/api/engine-status`, `/api/event`, `/api/choose/{id}`, `/api/reset` |

**Assets loaded**: All CSS is inlined in the HTML files; no external JS or CSS files exist.

---

## 3. Backend / API Surface

| HTTP Method | Path | Purpose | Engine Systems touched |
|-------------|------|---------|------------------------|
| `GET` | `/api/` | Health check (static message) | – |
| `GET` | `/api/state` | Returns the full mutable game state (credits, fuel, metrics, etc.). | All mutable state fields defined in `GameState`.
| `GET` | `/api/atlas` | Static reference data for NPCs, creatures, technology caps, USS Chaosbringer. | `atlas` constant (read‑only data).
| `GET` | `/api/engine-status` | Exposes the *engine_systems* dictionary (quest, faction, technology, NPC, event registry, consciousness, turn progression, persistence). | All sub‑systems listed under `engine_systems`.
| `GET` | `/api/event` | Returns a freshly selected event card. | Event registry (reads `event_registry` to track seen events).
| `POST` | `/api/choose/{choice_id}` | Apply a player choice, mutate state, log decision, advance turn. | All mutable fields, governance pressure, proposal history, decision ledger, engine system counters.
| `POST` | `/api/reset` | Reset the whole game to its initial `GameState`. | Re‑initialises every system.
| `GET` | `/api/log` | Returns the last 20 log entries. | Log subsystem.
| `WebSocket` | `/ws` | Real‑time push of state updates to connected browsers. | Broadcasts any state changes.

---

## 4. Engine Systems Inventory

| System | Exists in code? | Exposed via API? | Current UI exposure |
|--------|----------------|------------------|--------------------|
| **Quest System** | `engine_systems["quest_system"]` (loaded, active/complete counters) | Yes – part of `/api/engine-status` | Not displayed in either HTML page.
| **Faction System** | `engine_systems["faction_system"]` (known factions, player standing) | Yes – part of `/api/engine-status` | Not displayed.
| **Technology Tree** | `engine_systems["technology_tree"]` (research points, unlocked techs) | Yes – part of `/api/engine-status` | Not displayed.
| **NPC System** | `engine_systems["npc_system"]` (known NPCs, relationships) | Yes – part of `/api/engine-status` | Not displayed.
| **Event Registry** | `engine_systems["event_registry"]` (total events, events_seen) | Yes – part of `/api/engine-status` | Partially visible via the “Event provenance” panel in `adult.html` (only a list of seen titles).
| **Consciousness Metrics** | `engine_systems["consciousness_metrics"]` (coherence, stability, complexity) | Yes – part of `/api/engine-status` | Not displayed.
| **Turn Progression** | `engine_systems["turn_progression"]` (current_phase, turns_in_phase) | Yes – part of `/api/engine-status` | Turn number shown, but phase hidden outside `adult.html`.
| **Persistence** | `engine_systems["persistence"]` (last checkpoint, save slots) | Yes – part of `/api/engine-status` | Not displayed.
| **Lore / Narrator** | Implicit in event cards and `atlas` data | No dedicated endpoint – only via `/api/atlas` | Not displayed.
| **Multi‑Agent / Coordinator** | Implemented through governance pressure logic and event handling | No UI exposure | Hidden.

---

## 5. Tests & Demos Index

The repository does **not** contain a dedicated `tests/` directory or any pytest / unittest files. The only implicit tests are the interactive demo runs exercised by the front‑end pages. Therefore:
- **Test‑only files**: _None_.
- **Behaviour verified by UI**: All engine logic is exercised when a user clicks a choice in the web UI.

---

## 6. Docs Index

| Path | Type | Summary |
|------|------|----------|
| `README.md` | Documentation | High‑level project description, gameplay overview, quick‑start instructions. |
| `backend/Dockerfile` | Documentation / Build script | Defines the Python‑based API container image. |
| `frontend/Dockerfile` | Documentation / Build script | Defines the Nginx container image serving static HTML. |
| `nginx/nginx.conf` | Documentation | Nginx server configuration (static site mapping, proxy to API). |
| `docker-compose.yml` | Documentation | Orchestrates the two containers (frontend + backend). |
| `backend/requirements.txt` | Documentation | Python dependencies for the FastAPI backend. |

All of the above are **live** in the sense that they are used by the development / deployment pipeline, but they are not directly part of the runtime game UI.

---

## 7. Used vs Unused Table

| Path | Type | Lines / Size | Classification | Imported / Linked / Tested By | Visible in Deployed Game? | Recommended Action |
|------|------|--------------|----------------|------------------------------|---------------------------|--------------------|
| `backend/main.py` | Python module | 1,161 | **LIVE_API** | Imported by FastAPI runtime (`uvicorn`). Calls made by all front‑end pages. | Yes (state, events, choices) | Keep as‑is; consider extracting engine subsystems into separate modules for clarity. |
| `frontend/index.html` | HTML | 1,015 | **LIVE_WEB** | Served by Nginx at `/`. Calls API endpoints. | Yes | Keep; add links to engine‑status panels in future. |
| `frontend/adult.html` | HTML | 699 | **LIVE_WEB** | Served at `/adult.html`. Calls `/api/engine-status` etc. | Yes (engine status panel) | Fix missing `fetchState()` reference; otherwise keep. |
| `frontend/earth.html` | HTML | 20 | **UNUSED_OR_UNKNOWN** | No navigation link or import. | No | Consider removing or repurposing as a tutorial page. |
| `backend/Dockerfile` | Dockerfile | 17 | **DOC_ONLY** | Used by Docker build process. | No (runtime) | Keep for CI/CD. |
| `frontend/Dockerfile` | Dockerfile | 6 | **DOC_ONLY** | Used by Docker build process. | No | Keep. |
| `nginx/nginx.conf` | Config | 40 | **DOC_ONLY** | Used by Nginx container. | No | Keep. |
| `docker-compose.yml` | YAML | 43 | **DOC_ONLY** | Used to spin up dev environment. | No | Keep. |
| `backend/requirements.txt` | Text | 7 | **DOC_ONLY** | pip install – part of build. | No | Keep. |
| `__pycache__/main.cpython-310.pyc` | Byte‑code | (binary) | **ARCHIVE_OR_LINEAGE** | Generated automatically; not source. | No | Safe to ignore; can be deleted on clean builds. |

---

## 8. Underused Systems (Engine‑Ready but Invisible)

| System | Exists (in `main.py`) | Proven by Demo / UI | Minimal Bridge to expose |
|--------|----------------------|--------------------|--------------------------|
| **Quest System** | `engine_systems["quest_system"]` | No UI component currently shows active/completed quests. | Add a small GET endpoint `GET /api/engine-status/quests` (or reuse `/engine-status`) and a panel in `adult.html` listing `active_quests` / `completed_quests`. |
| **Faction System** | `engine_systems["faction_system"]` | Not visible. | Extend `engine-status` JSON with `faction_system` details and add a “Factions” tab in `adult.html`. |
| **Technology Tree** | `engine_systems["technology_tree"]` | Not visible. | Add a “Research” panel showing `unlocked_techs` and `research_points`. |
| **NPC System** | `engine_systems["npc_system"]` | Not visible. | Show a list of known NPCs and their current relationship status in a new UI section. |
| **Consciousness Metrics** | `engine_systems["consciousness_metrics"]` | Hidden. | Simple read‑only display of `coherence`, `stability`, `complexity` in the diagnostics panel. |
| **Persistence** | `engine_systems["persistence"]` | No UI. | Expose `last_checkpoint` and `save_slots` via `/engine-status` and add a “Save/Load” indicator. |
| **Lore / Narrator** | `atlas` constant and event text | Only partially shown via `fetchAtlas()` (summary). | Add a “Lore” tab that renders full `atlas` descriptions. |

---

## 9. Game Comprehension Audit

1. **Unclear Goal** – Players are not told *why* they are gathering credits, exploring sectors, or influencing council support.
2. **Hidden Engine State** – Most engine subsystems (quests, factions, tech tree) never surface, making it hard to see the consequences of choices.
3. **Abstract Metrics** – Numbers such as `council_support` or `emergency_powers` are displayed without contextual explanation.
4. **Missing Tutorial** – No onboarding flow explains the governance mechanics, the meaning of “lanes”, or how decisions affect the federation.
5. **Event‑to‑Consequence Mapping** – Event cards give rewards/penalties, but the long‑term impact on hidden systems is invisible.
6. **Information Overload** – The UI packs many numeric bars and text blocks, which can overwhelm younger users.

---

## 10. Recommended Wiring Plan (3‑Step)

**Step 1 – Expose Engine State through API**
- Extend the existing `/api/engine-status` payload (or add dedicated endpoints) to return the full `engine_systems` dictionary **plus** a flattened summary for each subsystem (quests, factions, tech, NPCs, consciousness, persistence).
- Ensure the response includes a `timestamp` so the front‑end can cache safely.

**Step 2 – Show Engine State in `adult.html` (or a new “Diagnostics” page)**
- Add new UI panels/tabs: **Quests**, **Factions**, **Research**, **NPCs**, **Consciousness**, **Persistence**.
- Each panel consumes the corresponding JSON slice from the API and renders a simple list or progress bar.
- Keep the design consistent with the existing LCARS style (use the same colour variables, grid layout, and minimal text).

**Step 3 – Add a Light‑weight Tutorial / Ledger Explanation**
- Create a “Tutorial” modal that appears on first load, walking the player through:
  * The goal of maintaining federation stability and public trust.
  * How each metric maps to a visible UI element.
  * Where to find hidden systems (the new Diagnostics tab).
- Add a small “Help” button on every page linking to the tutorial.
- Optionally surface a concise “What happened this turn?” ledger entry that ties the most recent decision to changes in the newly‑exposed systems.

> **Outcome:** The game will stop being a hidden‑engine sandbox and become a *transparent* governance simulation that re‑uses the already‑implemented engine logic rather than layering new mechanics.

---

**Next Safe Action**

> *Recommend the smallest bridge that makes existing tested engine systems visible in the web game.*
> The immediate, low‑effort bridge is to **add a “Diagnostics” tab to `adult.html` that consumes `/api/engine-status`** and shows the quest, faction, technology, and NPC data. This satisfies the audit findings without altering core game logic.

---

*This document was generated automatically by the repository‑audit agent as instructed. No files were modified.*