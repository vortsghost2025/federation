# Bridge Mode V1.2 — Deployment Proof

**Date:** 2026-05-16
**Commit:** `afea05d`
**Tag:** `bridge-v1.2`

---

## Live URL

```
https://federation-game.deliberatefederation.cloud/bridge.html
```

---

## Deployment Chain Confirmed

| Step | Status | Evidence |
|------|--------|----------|
| SCP bridge.html to VPS frontend volume | ✅ | 1571 lines confirmed via `wc -l` |
| Docker rebuild `docker compose build frontend` | ✅ | Image built, layers exported |
| Container restart `docker compose up -d frontend` | ✅ | Container recreated and started |
| HTTP 200 on live URL | ✅ | `curl -s -o /dev/null -w '%{http_code}'` returned `200` |

---

## API Endpoints Verified

All 7 endpoints that V1.2 depends on are responding with valid JSON:

| Endpoint | Method | Result | Sample Data |
|----------|--------|--------|-------------|
| `/api/state` | GET | ✅ | turn: 5, credits: 1130, shields: 100, hull: 100 |
| `/api/event` | GET | ✅ | id: `rival_border_skirmish`, title: "BORDER SKIRMISH", 3 choices |
| `/api/factions` | GET | ✅ | 8 factions, diplomatic_corps rep=0.6, military_command rep=0.55 |
| `/api/log` | GET | ✅ | 4 decision log entries, latest: "SPACE STATION" |
| `/api/timeline` | GET | ✅ | year: 2391, era: early_exploration, turn: 4 |
| `/api/npcs/{char_id}` | GET | ✅ | char_101 → Chancellor Harmony, archetype: leader |
| `/api/rivals` | GET | ✅ | 12 rivals, Void Marauders threat=0.535, Entropy Cult threat=0.366 |

Additional endpoints used by V1.1 (also confirmed working in prior deployment):
- `/api/consciousness` — morale: 0.8, identity: 0.8, anxiety: 0.2
- `/api/map/data` — 39 NPCs, 8 factions, world state

---

## V1.2 Feature Checklist

| Feature | Deployed | Verified in HTML |
|---------|----------|------------------|
| Keyboard shortcuts (1-5 choices, Space/Enter continue, R reset, Esc close modal) | ✅ | `keydown` handler present |
| `[1]`-`[5]` key hints on choice buttons | ✅ | Rendered in button HTML |
| `[SPACE]` hint on Continue button | ✅ | Present |
| NPC detail modal (click NPC name → full profile) | ✅ | `npc-modal`, `openNpcModal()`, `closeNpcModal()` |
| NPC modal: personality bars, skills, corruption, quest | ✅ | Fetched from `/api/npcs/{id}` |
| NPC modal close: × button, backdrop click, Escape | ✅ | Three close paths |
| Faction influence radar chart (8-axis canvas) | ✅ | `faction-radar` canvas, `drawFactionRadar()` |
| Faction radar polls every 30s | ✅ | `setInterval(fetchFactions, 30000)` |
| Decision timeline (Command Timeline) | ✅ | `ri-timeline` div, `updateTimeline()` |
| Era markers in timeline | ✅ | Era grouping from `/api/timeline` |
| Timeline refreshes every 15s + after each choice | ✅ | `setInterval(fetchDecisionLog, 15000)` |
| Audio engine: bridge hum (3-oscillator drone) | ✅ | `initAudio()`, 55Hz + 55.5Hz + 27.5Hz |
| Audio: hum intensity varies by alert level | ✅ | green=0.05, yellow=0.07, red=0.10, crisis=0.12 |
| Audio: choice chirp sound | ✅ | 880Hz→1100Hz chirp |
| Audio: alert tones (red, crisis, yellow) | ✅ | Sawtooth burst, ascending saw, triangle ping |
| Audio: event domain sounds | ✅ | Military, diplomacy, anomaly, economy |
| Audio: game over / victory sounds | ✅ | Descending sawtooth / ascending C-E-G |
| Audio: autoplay policy compliance | ✅ | `initAudio()` on first user interaction |

---

## Known Risks

1. **Single backend process** — `game_state` (current_event) is in-memory. If backend container restarts mid-game, the current event is lost. State endpoints still work (Redis-backed), but the active event resets.
2. **Audio autoplay restriction** — Audio context is suspended until first user interaction (click/keypress). Bridge hum won't start until the user touches something. This is by design (browser policy) but means the first few seconds are silent.
3. **No API failure handling** — If any endpoint returns an error or times out, the bridge currently shows stale/empty data with no indication to the user that something is wrong. **This is the top priority for the next pass.**
4. **NPC modal requires `char_id`** — Events that don't include a character ID will produce `openNpcModal('')` which will 404. Needs a guard.
5. **Faction radar canvas** — If `/api/factions` is slow or returns unexpected structure, `drawFactionRadar()` may throw and leave a blank canvas. No try/catch around canvas rendering.
6. **No rate limiting on refresh intervals** — `fetchDecisionLog` (15s), `fetchFactions` (30s), `fetchState`/`fetchEvent` (game loop) all run independently. Under slow network conditions, these could stack up.
7. **SCP indentation risk** — Only applies to Python files. HTML SCP is safe (confirmed). But any future Python changes must use the base64 pipeline.

---

## Next Test Needed

**Failure-state visibility pass** — Before adding any new features, the bridge needs to handle API failures gracefully:

- [ ] If an API call fails, show a **stale badge** on the affected panel
- [ ] Display **last good data timestamp** (when the data was last successfully fetched)
- [ ] Show **retry state** (spinner or "retrying in Ns" indicator)
- [ ] Keep UI fully usable with stale data — never freeze or go blank
- [ ] Guard `openNpcModal()` against empty/missing char_id
- [ ] Add try/catch around `drawFactionRadar()` and all canvas rendering
- [ ] Exponential backoff or dedup on retry intervals under sustained failure
