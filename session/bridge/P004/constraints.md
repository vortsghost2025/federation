# P004 Constraints — Hard Rules

## 1. fedFetch Return Contract
- **ALWAYS returns `data|null`** — never throws to caller
- Caller **MUST** null-guard: `const data = await fedFetch(...); if (!data) return;`
- Matches `earth.js` `apiFetch` pattern exactly

## 2. Timeout
- Default **8000ms** (8 seconds) via AbortController
- Configurable per-call: `fedFetch(key, url, {timeout: 15000})`
- `starmap.js` `/map/assistant` needs 15000ms (currently has 15s)

## 3. User Feedback
- **`showToast(msg, 'warn')` on EVERY failure** — no silent failures
- Toast implementation lives in `fed-fetch.js` (self-contained)
- Types: `'warn'` for errors, `'info'` for success if needed

## 4. Stale Data Tracking
- **`updateLinkHealth(key, ok)` on EVERY call** — `ok=true` on success, `false` on failure
- Used by stale badge indicators (bridge.js pattern)
- Implementation in `fed-fetch.js`

## 5. /choose Endpoint Contract
- Backend **MUST** return `"outcome"` key
- Frontend calls `data.outcome.toUpperCase()` — **will crash if missing**
- adult.js `showOutcome(data)` expects `data.outcome` to exist
- P0 fix: null-guard before calling `showOutcome`

## 6. No Refactoring of Reference Files
- **DO NOT modify** `bridge.js` `trackedFetch` or `earth.js` `apiFetch`
- They remain as-is for future plan
- Only the 5 target files + new `fed-fetch.js`

## 7. No Frameworks / No Build Step
- Vanilla JS only, CDN only
- Single HTML files
- `<script src="fed-fetch.js"></script>` in HTML — no bundler

## 8. Single-Worker Backend
- VPS backend runs 1 worker — `game_state` singleton in memory
- Multi-worker broke `/event` + `/choose` race
- This plan does NOT touch backend

## 9. Deploy Path
- Frontend files → `/docker/federation-game/public_html/` (nginx bind mount)
- NOT `/docker/federation-game/frontend/`
- `ssh hostinger` alias required (IdentityFile configured)

## 10. Git Tracking
- `.opencode/` and `session/` in `.gitignore`
- Must `git add -f session/bridge/P004/` to track bridge files