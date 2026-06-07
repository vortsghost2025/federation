# P004 Verification Checklist

## Pre-Deploy (Local)

### File Existence
- [ ] `federation-game/frontend/fed-fetch.js` exists
- [ ] Contains `function fedFetch(key, url, opts={})`
- [ ] Contains `function showToast(msg, type)`
- [ ] Contains `function updateLinkHealth(key, ok)`
- [ ] Exports `window.fedFetch = fedFetch;`

### Signature Check
- [ ] `fedFetch(key, url, opts={})` — 3 params, opts destructured with `timeout=8000`
- [ ] Returns `Promise<data|null>`
- [ ] Uses `AbortController` with timeout
- [ ] Checks `resp.ok` → throws on fail
- [ ] Calls `showToast(key + ' failed: ' + e.message, 'warn')` in catch
- [ ] Calls `updateLinkHealth(key, false)` in catch, `updateLinkHealth(key, true)` on success
- [ ] Returns `null` in catch

### Adult.js P0 Crash Fix
- [ ] `choose()` function uses `fedFetch('choose', ...)` 
- [ ] Has null-guard: `const data = await fedFetch(...); if (!data) return;`
- [ ] Calls `showOutcome(data)` only after null-guard
- [ ] No direct `response.json()` on unchecked response
- [ ] `fetchEngineStatus()` uses `fedFetch('engineStatus', ...)`

### Other 4 Files Patched
- [ ] `index.js` — 5 fetches replaced, all null-guarded
- [ ] `starmap.js` — `fetchData()` + `/map/assistant` use fedFetch; `/map/assistant` has `timeout:15000`
- [ ] `constellation.js` — 3 fetch functions use fedFetch
- [ ] `simulation.js` — internal `apiFetch` removed, 13 call sites use fedFetch

### HTML Script Tags
- [ ] `adult.html` has `<script src="fed-fetch.js"></script>` before `adult.js`
- [ ] `index.html` has `<script src="fed-fetch.js"></script>` before `index.js`
- [ ] `starmap.html` has `<script src="fed-fetch.js"></script>` before `starmap.js`
- [ ] `constellation.html` has `<script src="fed-fetch.js"></script>` before `constellation.js`
- [ ] `simulation.html` has `<script src="fed-fetch.js"></script>` before `simulation.js`

## Post-Deploy (Production)

### Deploy Verification
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://federation-game.deliberatefederation.cloud/` returns `200`
- [ ] `curl -s https://federation-game.deliberatefederation.cloud/fed-fetch.js` returns JS content (200)

### Functional Tests
- [ ] Load adult page → trigger event → make choice → no crash, toast appears on simulated failure
- [ ] Load index page → verify state/event loads, no console errors
- [ ] Load starmap page → verify map data loads, assistant works
- [ ] Load constellation page → verify data loads, no silent failures
- [ ] Load simulation page → verify NPCs/factions load, stale badges update

### Error Path Tests
- [ ] Disconnect network → click any action → toast appears "X failed: Failed to fetch"
- [ ] Stale badges show red/offline after failures
- [ ] Reconnect → next action succeeds, badges green, toast clears