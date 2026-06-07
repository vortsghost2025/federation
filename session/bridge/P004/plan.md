# P004 Plan — Frontend Error Hardening via Shared `fed-fetch.js`

## Objective
Replace ad-hoc fetch error handling in 5 frontend JS files with a single shared module `fed-fetch.js` that provides:
- AbortController timeout (8s default)
- `resp.ok` check with throw → return `null` on failure
- User-visible `showToast(msg, 'warn')` on failure
- `updateLinkHealth(key, ok)` for stale data badges
- Consistent null-guard pattern for callers

## Target Files (5)
1. `federation-game/frontend/adult.js` — P0: crash bug in `choose()` L232-233
2. `federation-game/frontend/index.js` — 5 fetch calls, zero error handling
3. `federation-game/frontend/starmap.js` — 2 fetches, partial protection
4. `federation-game/frontend/constellation.js` — 3 fetches, zero timeout, silent catches
5. `federation-game/frontend/simulation.js` — 13 fetches, closest to pattern but missing toast/stale

## New File
- `federation-game/frontend/fed-fetch.js` — shared module

## HTML Files Needing `<script src="fed-fetch.js"></script>` (5)
- `federation-game/frontend/adult.html`
- `federation-game/frontend/index.html`
- `federation-game/frontend/starmap.html`
- `federation-game/frontend/constellation.html`
- `federation-game/frontend/simulation.html`

## Execution Steps

### Step 1: Create `fed-fetch.js`
Write new file `federation-game/frontend/fed-fetch.js` with:
- `fedFetch(key, url, opts={})` → returns `data|null`
- Internal `showToast(msg, type)` — creates/updates toast element
- Internal `updateLinkHealth(key, ok)` — updates stale badge indicator
- AbortController timeout (default 8000ms, configurable via opts.timeout)
- `resp.ok` check → throw → catch → toast + updateLinkHealth + return null
- Exports: `window.fedFetch = fedFetch;`

### Step 2: Patch adult.js (P0 — CRASH FIX)
- Replace `choose()` L230-256 fetch with `fedFetch('choose', url, {method:'POST', body:...})`
- Remove manual `response.json()` + `showOutcome()` call — `showOutcome` expects `data.outcome`
- Guard: `const data = await fedFetch(...); if (!data) return; showOutcome(data);`
- Also patch `fetchEngineStatus()` L168-174 with `fedFetch('engineStatus', ...)`
- All other 7 fetches in file → `fedFetch`

### Step 3: Patch index.js
- Replace 5 fetch calls (L158, L168, L181, L200, L207) with `fedFetch`
- Keys: 'state', 'event', 'choose', 'vote', 'flag'
- Null-guard each: `const data = await fedFetch(...); if (!data) return;`
- Note: `submitVote()` and `flagEvent()` do NOT exist — find actual function names and patch those

### Step 4: Patch starmap.js
- `fetchData()` L257-268 → `fedFetch('mapData', '/map/data')`
- `POST /map/assistant` L2928 → `fedFetch('mapAssistant', url, {method:'POST', body:..., timeout:15000})` (keep 15s timeout)
- Remove local AbortController (fedFetch handles it)
- Search (`onSearch` L2736) is local-only — no change needed

### Step 5: Patch constellation.js
- `fetchData()` L132-141 → `fedFetch('constellationData', ...)`
- `fetchFactionTech()` L143-166 → `fedFetch('factionTech', ...)`
- `fetchQuestBatch()` L168-194 → `fedFetch('npcQuests', ...)` (batched calls inside — keep batching, wrap each with fedFetch)
- All 3 currently have silent catches → fedFetch provides toast + stale badge

### Step 6: Patch simulation.js
- Replace internal `apiFetch` L443 with `fedFetch` calls
- 13 call sites (find via grep) → each becomes `fedFetch(key, url, opts)`
- Preserve `Promise.all` stale fallback pattern at L1890 — wrap each promise with fedFetch
- Remove local AbortController timeout logic (fedFetch handles it)

### Step 7: Add `<script>` tags to 5 HTML files
Insert `<script src="fed-fetch.js"></script>` **before** each page's main JS script tag

### Step 8: Commit + Deploy
- `git add -A && git commit -m "P004: frontend error hardening via fed-fetch.js"`
- `git push`
- VPS deploy: `ssh hostinger "cd /opt/federation && git pull && cp -r federation-game/frontend/* /docker/federation-game/public_html/ && docker compose restart nginx"`

## Success Criteria
- adult.js `choose()` no longer crashes on HTTP error
- All 5 files use `fedFetch` for every network call
- User sees toast on any fetch failure
- Stale badges update via `updateLinkHealth`
- No silent catches remain
- Production verified at federation-game.deliberatefederation.cloud