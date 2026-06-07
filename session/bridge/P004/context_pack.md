# P004 Context Pack — Frontend Error Hardening

## Project: Federation
Consciousness simulation — single HTML files, vanilla JS, CDN only, no frameworks. Docker + nginx + FastAPI backend.

## Architecture Constraints (HARD)
- Backend single-worker (multi-worker broke `game_state` singleton)
- `/choose` MUST return `"outcome"` key — frontend calls `.outcome.toUpperCase()`
- `gs.current_event = None` after choice is intentional
- VPS: 187.77.3.56, domain federation-game.deliberatefederation.cloud (Traefik TLS)
- Frontend deploy path: `/docker/federation-game/public_html/` (nginx bind mount)
- No `docker compose` locally — VPS only

## The Problem
5 frontend JS files have inconsistent, incomplete fetch error handling:

| File | Fetches | Issues |
|------|---------|--------|
| `adult.js` | 9 | **P0 CRASH**: `choose()` L232-233 no `resp.ok` → `response.json()` on error → `showOutcome()` L260 `data.outcome.toUpperCase()` crashes on undefined |
| `index.js` | 5 | Zero `resp.ok` checks, no timeout, no user feedback |
| `starmap.js` | 2 | `fetchData()` silent return on fail; `/map/assistant` has 15s AbortController only |
| `constellation.js` | 3 | Zero timeout, all silent `catch { /* */ }` |
| `simulation.js` | 13 | Has AbortController 8s + `resp.ok` check + returns null — but NO toast, NO stale badges |

## Reference Patterns (DO NOT REFACTOR THESE — future P)
- `bridge.js` `trackedFetch` L154-166: `resp.ok`→throw, `recordFetchOk/Fail`→`updateLinkHealth()`, callers catch keep stale
- `earth.js` `apiFetch` L11-24: `r.ok`→`fetchHealth`→`updateLinkHealth()`→return `null`; 14 callers null-guard `if(!data)return`

## Solution: `fedFetch(key, url, opts={})` → `data|null`

```js
// fed-fetch.js (new file)
function fedFetch(key, url, opts={}) {
  const {timeout=8000, ...fetchOpts} = opts;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const resp = await fetch(url, {...fetchOpts, signal: ctl.signal});
    clearTimeout(timer);
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return await resp.json();
  } catch (e) {
    clearTimeout(timer);
    showToast(key + ' failed: ' + e.message, 'warn');
    updateLinkHealth(key, false);
    return null;
  }
}

function showToast(msg, type) { /* create/update toast element */ }
function updateLinkHealth(key, ok) { /* update stale badge DOM */ }

window.fedFetch = fedFetch;
```

## Caller Pattern (all 5 files)
```js
const data = await fedFetch('key', url, opts);
if (!data) return;  // null-guard — earth.js pattern
// use data
```

## File Map
- `federation-game/frontend/adult.js` — P0 target, 9 fetches, `choose()` crash
- `federation-game/frontend/index.js` — 5 fetches at L158,168,181,200,207
- `federation-game/frontend/starmap.js` — 2 fetches: L257-268 (GET /map/data), L2928 (POST /map/assistant 15s)
- `federation-game/frontend/constellation.js` — 3 fetches: L132-141, L143-166, L168-194
- `federation-game/frontend/simulation.js` — 13 fetches, internal `apiFetch` L443
- `federation-game/frontend/fed-fetch.js` — NEW
- 5 HTML files: adult.html, index.html, starmap.html, constellation.html, simulation.html

## Deploy
`ssh hostinger "cd /opt/federation && git pull && cp -r federation-game/frontend/* /docker/federation-game/public_html/ && docker compose restart nginx"`