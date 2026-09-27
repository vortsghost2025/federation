# TEST RESULTS LOG

Append-only, timestamped test evidence for all agent work in this repo.
**Secrets policy: no API key ever appears in this file or any commit — values are redacted to [REDACTED] or referenced by hash only.**

Timestamps: `UTC` = VPS/log time; `LOCAL` = desktop clock (-0400).

---

## 2026-09-27 — Session: stack restoration → website pass → OpenRouter key rotation

LOCAL commit window: 2026-09-26 23:27 -0400 (UTC 2026-09-27 03:27)

### A. Starmap interactivity pass (deploy 03:04 UTC)

| # | Test | Result |
|---|------|--------|
| A1 | `node --check federation-game/frontend/starmap.js` | **PASS** — syntax clean |
| A2 | SHA-256 three-way match (local = VPS host = frontend container) for all 4 deployed files | **PASS** — `starmap.js dc4b924ade525e5f…`, `starmap.html 69c1b71c20ce1ede…`, `galaxy-map.js e2a7f0b7993e06a9…`, `galaxy-map.html 35ecc53dbaa7b1c3…` |
| A3 | Playwright live load `https://federation-game.deliberatefederation.cloud/starmap.html` | **PASS** — HTTP 200; 48 NPC nodes built |
| A4 | Follow mode injection: `setFollowNode()` + fabricated trail history | **PASS** — HUD chip rendered “FOLLOWING preservation_society — CLICK OR ESC TO RELEASE”; camera locked centered; trail polyline rendered |
| A5 | ESC release: `keyboard.press("Escape")` → `followNode === null` | **PASS** — true |
| A6 | Console errors on starmap + galaxy-map | **PASS (benign)** — exactly 1 per page = `/favicon.ico` 404 (pre-existing, verified `http=404`) |
| A7 | Playwright live load `/galaxy-map.html` (3D, 4 modes, 3 zoom levels) | **PASS** — HTTP 200, scene renders, `/map/data OK 200`, 21 sectors / 47 NPCs / 15 territories, TICK 5 |
| A8 | Nav link uniqueness: `grep -c 'href="/galaxy-map.html"'` across 10 patched pages | **PASS** — exactly 1 insertion per page, no doubles |
| A9 | HTTP 200 sweep: adult, spectator, starmap, earth, universe, worldguide + `galaxy-map.html/.js` | **PASS** — all 200 |
| A10 | Web-root litter sweep: `*.bak* *.BAK* test_scp.txt` remaining in `public_html/` | **PASS** — 23 files archived to `/docker/federation-game/archive/public_html_bak/`, 0 remain |

### B. OpenRouter key rotation (03:17–03:21 UTC)

| # | Test | Result |
|---|------|--------|
| B1 | Key auth: `GET openrouter.ai/api/v1/key` with rotation key | **PASS** — 200; spend limit `$1/month`; `limit_remaining 0.999218` after tests |
| B2 | Free-tier completion: `nvidia/nemotron-3-super-120b-a12b:free`, max_tokens 20 | **PASS** — HTTP 200, real completion body |
| B3 | Paid fallback (was 402): `meta-llama/llama-3.3-70b-instruct`, max_tokens 20 | **PASS** — HTTP 200; total test spend `$0.000782` |
| B4 | Pool health probe: `meta-llama/llama-3.3-70b-instruct:free` | **FAIL (data point)** — HTTP 404, delisted from free tier; dead pool entry documented in FEDERATION_INDEX known-issues; per-model circuit breaker absorbs it |
| B5 | `.env` rotation integrity: all 3 vars (`OPENROUTER_API_KEY`, `_1`, `_2`) md5 = `1b00a89e2f618cca3bcbdca788b56890` (= local reference hash of rotation key); `OPENROUTER_MANAGEMENT_KEY` untouched (sed pattern excluded it) | **PASS** — no key material printed anywhere |
| B6 | Container env propagation after `--force-recreate`: backend, worker, npc-agent-001, npc-agent-306 | **PASS** — 4/4 `OPENROUTER_API_KEY` md5 = `1b00a89e…` |
| B7 | Pre-recreate safety: watchdog lease keys absent (no mid-tick), RAM cache reclaimed first (prior incident: Redis OOM during recreate) | **PASS** — `fed:watchdog:*` scan empty; free 1034 MB after reclaim |
| B8 | Post-recreate health: `docker ps` states + logs + public endpoint | **PASS** — worker + backend `healthy`; quest tick 40 NPCs / 0 errors; pair `LLM OK — nemotron-3-ultra-550b-a55b`; `/map/data http=200` |

### C. Repository hygiene (23:27 LOCAL)

| # | Test | Result |
|---|------|--------|
| C1 | Secret scan, full content of all 35 changed text files, 15 key patterns | **PASS** — 3 hits, all false positives: `nvapi-XXXXX` placeholder (INDEX:53), `api_key="ollama"` SDK literal (nvidia_nim_client.py:218), `${NVIDIA_API_KEY_CHAR_001_TEST}` env interpolation (docker-compose.yml:376) |
| C2 | Committed-tree scan (`git grep` at HEAD): `sk-or-v1-[40 hex]`, `nvapi-[20 hex]`, `github_pat_` | **PASS** — no hits |
| C3 | `.gitignore` coverage: `.env`, `.env.*`, `.secrets/`, `*secret*key*` | **PASS** — key material paths untracked |

Prior-session evidence (backend restoration, model remap, watchdog fix, Redis loop cleanup):
see `.horizon/DELTA_LOG.md` entries dated 2026-09-27 (each line records change + verification).

### D. Main-branch reconciliation (merge validation, 23:35 LOCAL)

| # | Test | Result |
|---|------|--------|
| D1 | `git merge-tree` trial: conflict surface vs origin/main (35 commits) | **PASS** — only `docker-compose.yml` conflicted; 3 key py files auto-merged |
| D2 | Compose conflict resolution audit: all main-side features present in ours (operator routes, `/environment` x2, allowlists, proxy-headers, forwarded-allow-ips, `172.16.2.7`) | **PASS** — resolved as ours = running VPS config |
| D3 | `python -m py_compile` on all 28 staged .py files from merge | **PASS** — 28/28 |
| D4 | YAML parse of merged compose (VPS python3 yaml.safe_load) | **PASS** — `YAML-PARSE OK` |
| D5 | Semantic merge checks: staged llm_router contains main's OLLAMA_MAX_ACTIVE=2 combined with session model remap | **PASS** |

### E. Free-pool liveness probe + prune (2026-09-26 23:45:38 -04:00)

Method: POST openrouter.ai/api/v1/chat/completions, max_tokens=5, all 15 unique `:free` IDs found in the repo, two passes 2s apart. Key fetched from VPS `.env` into memory only - never printed, never written to any file.

| Model | Pass 1 | Pass 2 | Verdict |
|---|---|---|---|
| nvidia/nemotron-3-ultra-550b-a55b:free | 200 | - | ALIVE (kept everywhere) |
| nvidia/nemotron-3-super-120b-a12b:free | 200 | - | ALIVE (kept everywhere) |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 200 | - | ALIVE (kept, promoted to pool SMALL head) |
| cohere/north-mini-code:free | 200 | - | ALIVE (kept) |
| google/gemma-4-26b-a4b-it:free | 429 | - | ALIVE rate-limited (kept) |
| google/gemma-4-31b-it:free | 429 | - | ALIVE rate-limited (kept) |
| meta-llama/llama-3.3-70b-instruct:free | 404 | 404 | DEAD - removed from 4 files |
| meta-llama/llama-3.2-3b-instruct:free | 404 | 404 | DEAD - removed |
| nousresearch/hermes-3-llama-3.1-405b:free | 404 | 404 | DEAD - removed |
| qwen/qwen3-next-80b-a3b-instruct:free | 404 | 404 | DEAD - removed |
| nvidia/nemotron-3-nano-30b-a3b:free | 404 | 404 | DEAD - removed |
| nvidia/nemotron-nano-9b-v2:free | 404 | 404 | DEAD - removed |
| openai/gpt-oss-120b:free | 404 | 404 | DEAD - removed |
| liquid/lfm-2.5-1.2b-instruct:free | 404 | 404 | DEAD - removed |
| cognitivecomputations/dolphin-mistral-24b-venice-edition:free | 404 | 404 | DEAD - removed |

Note: paid `meta-llama/llama-3.3-70b-instruct` (no `:free`) stays 200 - tested in B3, untouched.

Edits: `llm_router.py` pools LARGE/MID/SMALL (SMALL fully dead - refilled with live small models), `nvidia_nim_client.py` OPENROUTER_MODELS (kept non-empty: `_get_or_free_model_nim` does `idx % len(pool)` -> ZeroDivisionError on empty) + dead default at line 290, `npc_llm_client.py` + `npc_agent_current.py` OR_FREE_POOL.

| # | Test | Result |
|---|---|---|
| E1 | python -m py_compile on 4 edited files | **PASS** - 4/4 |
| E2 | Dead-ID sweep across all 4 files (9 patterns) | **PASS** - 0 occurrences remain |
| E3 | Entry counts after prune: llm_router 10, nim_client 7, npc_llm_client 3, npc_agent_current 3 | **PASS** - no empty pools |
| E4 | `npc_agent_current.py` VPS presence | **ABSENT on VPS** - local-only orphan, no importer, deliberately NOT deployed |

### E1. Pruned-pool deploy to VPS (2026-09-27 00:27:37 -04:00)

Deploy tool: `deploy_vps.sh` run under **Git Bash** (`C:/Program Files/Git/bin/bash.exe`). Root cause of earlier hangs: plain `bash` on this box is WSL bash - it has no VPS key and does not read `C:/Users/seand/.ssh/config`, so scp waited on a password prompt forever. Git Bash ssh authenticates via the `vps-nopass` config key (`GB-DEFAULT-OK` proven).

| # | Test | Result |
|---|---|---|
| E5 | deploy `backend+worker llm_router.py` | **PASS** - host=backend=worker md5 `8b97461f1abcd9fec63518884c2aba59` = local |
| E6 | deploy `backend+worker nvidia_nim_client.py` | **PASS** - host=backend=worker md5 `74a154e3f6eb73baee8d4601a377e8b0` = local |
| E7 | deploy `npc-agent npc_llm_client.py` | **PASS** - host=001=306 md5 `42fe982c0935ebed678ca25d15d9292a` = local |
| E8 | Mid-tick restart recovery | **PASS** - startup sweeper reset `running`; stale `fed:watchdog:*` lease (5 keys) DEL'd per AGENTS.md rule; fresh lease acquired on next tick |
| E9 | Verification tick after deploy (tick `operator_1790482758627`, 04:19-04:26 UTC) | **PASS** - `status: completed`, watchdog keys self-released (KEYS empty), `running=False` |
| E10 | Removed-model references during tick (8 dead IDs) | **PASS** - 0 occurrences in backend logs |
| E11 | `ERROR` lines during tick | **PASS** - 0 |

Notes: host `:8000` is owned by `genesis-viewer` (not backend) - trigger ticks from inside the backend container, not host localhost. Pre-existing unrelated warning: one paid-NIM `503 Service temporarily overloaded` on npc_memory tier - chain fell through normally, not caused by this change.


### F. Worker restart forensics - Sep 27 2026 (census closed 08:34:45 UTC)

**Task:** attribute every worker restart on 2026-09-27. Source: VPS `/var/log/syslog` (`stopping restart-manager` lines for container `b51cdd58`), `/var/log/auth.log` (SSH/CRON sessions), `C:\Users\seand\.local\share\opencode\log\opencode.log` (UTC-tagged local spawns), deploy_vps.sh source.

**Census correction:** 7 stop lines = **6 actual restarts**. `04:16:09` is NOT a restart - it is the force-kill continuation of the 04:15:58 SIGTERM: `04:15:58.863 stopping restart-manager` (SIGTERM) -> `04:16:09.143 "failed to exit within 10s of signal 15 - using the force"` + duplicate stop line 78us later -> up 04:16:14.

| # | Time (UTC) | Cause | Evidence | Status |
|---|---|---|---|---|
| 1 | 03:30:10 | auto_restart Tier-3 | `fed:monitor:last_auto_restart` = 03:30:05 | PROVEN |
| 2 | 04:12:33 | My deploy #1 (`llm_router.py`, backend+worker) | opencode.log spawn **04:12:19Z** (PREFLIGHT + `deploy_vps.sh backend+worker llm_router.py`); backend stop 04:12:24 -> worker 04:12:33 = one sequential `docker restart backend worker` (deploy_vps.sh L225); ssh session 946661 04:12:24->04:12:37 from 96.20.218.2 | PROVEN |
| 3 | 04:15:58 (+force 04:16:09, up 04:16:14) | My deploy #2 (`nvidia_nim_client.py`, backend+worker) | opencode.log spawn **04:15:44.389Z** (full args: PREFLIGHT must-be-False + `deploy_vps.sh backend+worker backend/nvidia_nim_client.py nvidia_nim_client.py`); backend stop 04:15:49; ssh session 972102 04:15:49->04:16:18 spans the whole forced restart; md5 verify sessions 04:16:21/24/31/33 = script post-restart blocks | PROVEN |
| 4 | 05:08:41 | fallback nuclear (05:00 cron) | CRON[1360527] 05:00:02 -> 05:08:46 (closes 3s after container up) | PROVEN |
| 5 | 06:07:36 | fallback nuclear (06:00 cron) | CRON[1913553] 06:00:01 -> 06:07:49 (7m48s = uniquely long in the 17-session 06:00 batch; all others <= 5m31s; closes 13s after restart) | PROVEN |
| 6 | 06:53:58 -> up 06:54:08 | fallback nuclear (06:45 cron) | CRON[2328727] 06:45:02 -> 06:54:11; hash `timestamp` 06:45:03; "WORKER RESTARTED", keys_cleared=4 | PROVEN |

**F1. Nuclear timing model (why hash time != restart time).** `monitoring/fallback_recovery.py`: `now = time.time()` at `run_check()` start -> cooldown check (HEALTH_THRESHOLD=20, COOLDOWN_SECONDS=1800) -> **4 SCAN patterns via `redis_helper.py` `_run`, which spawns ONE `docker exec redis-cli` per SCAN page (COUNT 200, _TIMEOUT=15)**. At dbsize=47679 that is 238 pages x 4 patterns x ~0.56s/exec = **~8.9 min scan storm** before `docker compose restart worker` (~11s) -> redis writes with the start-time `now` -> session closes 2-13s after container up. Explains all three nuclear restarts (05:00+8m40s, 06:00+7m35s, 06:45+8m55s).

**F2. Eliminated as causes (all PROVEN exclusions):** not OOM (exit=0, OOMKilled=false, RestartCount=0); not from inside containers (no docker.sock); not monitor tmux loop (`federation-game-monitor.sh` is read-only, INTERVAL=5); not `cognition_monitor.py` (`docker logs` only); not `heartbeat_loop.sh`/`heartbeat.sh` (no restart/docker stop matches, 50 lines); not systemd timers/at; not `federation-backup.sh` (restic-only); not `supervisor_loop.py` (not running); not Dockge/Dagu (prior suspects retired by sessions above).

**F3. Cooldown consistency:** resets at 05:00 / 06:00 / 06:45 are all > 30 min apart; 04:15:58/04:16:09 could not be nuclear (30-min cooldown + belongs to deploy session). Fallback log total: 1085 "WORKER RESTARTED", 1 "RESTART FAILED".

**F4. Live snapshot 08:34:45 UTC:** worker up since 06:54:08, RestartCount=0, no restart since 06:53:58; `monitor:llm_health` health_score=100/status OK; tick cadence normal.

**F5. Open decisions for owner (not actioned):** (a) keep or stop `federation-game-monitor.sh` periodic kilo loop; (b) VPS-vs-local `worker.py`/`npc_reflection.py` drift direction; (c) tame `fallback_recovery.py` scan storm (page-walk could be one `--scan` subprocess pass) and/or nuclear cadence (3 fires today via llm_health=0 NIM circuit-trip cycles).

### F6. Post-census nuclear restarts - addendum 2026-09-27 (after 08:34:45 UTC census)

Six more worker restarts, same proven mechanism (fallback cron finds LLM health 0 < 20, ~8-min scan storm, `docker compose restart worker`). Day total is now **12 restarts**.

| # | Stop (UTC) | Cron start | Scan | +10s force line? |
|---|---|---|---|---|
| 7 | 08:53:21 | 08:45:03 | 8m18s | yes (08:53:31) |
| 8 | 10:52:26 | 10:45:03 | 7m23s | yes (10:52:36) |
| 9 | 11:53:05 | 11:45:03 | 8m02s | no |
| 10 | 12:52:57 | 12:45:03 | 7m54s | no |
| 11 | 14:38:23 | 14:30:03 | 8m20s | yes (14:38:34) |
| 12 | 15:08:28 | 15:00:03 | 8m25s | no |
| 13 | 15:55:44 | 15:45:03 | 10m41s | no |

Evidence: VPS syslog stop lines (16 total through #12 = 12 restarts + 4 force continuations); `monitor:last_nuclear_reset` chain 12:45:03 -> 14:30:03 -> 15:00:03 (exact cron starts; stop = start + scan); health oscillation captured live (0 at 14:27:58 -> 100 at 14:36:39, self-healed in ~9 min with no intervention); fallback log totals reconciled: **1092 CRITICAL = 1091 RESTARTED + 1 FAILED**. The FAILED is a `docker compose restart worker` 120-second timeout at a 0.0-minute cooldown boundary (compose restart can hang when the worker is deep mid-tick). One WARNING correctly blocked a fire at 14.9-min remaining cooldown. Note: 15:00 fired exactly 30 min after 14:30 (cooldown-boundary racing). dbsize grew 47679 -> 48007, so the storm is ~1% worse than F1 measured.

Restart 13 (15:55:44 from the 15:45:03 cron, 10m41s storm, no force line) is the last nuclear of the old regime - the tame (F8) deployed ~16:20 UTC.

### F8. Fallback tame deployed + verified 2026-09-27 (~16:20 UTC)

Changes (`federation-game/monitoring/`, local canonical edited first, LF endings): `redis_helper.redis_scan_iter` now does a single `redis-cli --scan` subprocess pass per pattern (was one docker exec per SCAN page); added `redis_incr` / `redis_expire` helpers. `fallback_recovery.py` now requires TWO consecutive sub-threshold reads: healthy reads clear strikes, strike 1 logs WARNING watch-only, strike 2 enters the unchanged cooldown+nuclear path, strikes reset on nuclear entry (success or failure). Strike key `monitor:nuclear_strikes`, TTL 3600. Deployed via scp with `.bak.20260927_tame` host backups - host-only files, zero container restarts, zero tick contact.

| # | Test | Result |
|---|---|---|
| T1 | `py_compile` local (3.13) + VPS host python3 | **PASS** both |
| T2 | md5 local=host | **PASS** (`2f9fc860` fallback, `30ffd931` helper) |
| T3 | Live OK-path run (health 100) | **PASS** - OK line, no strike key created |
| T4 | Full 4-pattern clear-scan, timed live at dbsize 48143 | **PASS** - 13.4s, 7 keys (was ~9 min storm) |
| T5 | 20/20 stubbed drill of the real `run_check()` (OK, strike 1, strike 2 nuclear, restart, reset, cooldown block, recovery clear, restart-failure path) | **PASS** - exit 0 (3 initial FAILs were test-expectation bugs, code correct throughout) |
| T6 | LIVE debut: 16:30 cron read health 0 under new code | **PASS** - `WARNING: strike 1/2, watching (no action)`; strikes=1, last_nuclear untouched at 15:45:03, worker unrestarted (old code would have fired restart #14) |

### G. Simulation page 6-issue fix (2026-09-27)

Report (Sean, live page): raw char IDs in logs, mid-word truncation, 39-vs-40 count, covert 1-vs-0, Custodian unknown, MAIN RISK showing a positive. All six root-caused against live data before editing; backend roster/endpoints proven complete (40/40 named, char_500 present) so five fixes are frontend-only.

1. ID leak: LLM-written thoughts/actions/descriptions embed raw IDs (char_101 x3 etc. in live activity text); six render paths ignored the name fields the backend already sends. Fix: `npcDisplay()` (named fields -> char_id-to-roster map -> description-lead extraction with adverb-tolerant verbs incl. aligned/made) + `resolveIds()` free-text pass, applied at 28 render sites (logs, cards, feeds, briefing, sitroom, chains, broadcasts).
2. Truncation: hard `slice(0,217/137)` cut mid-word ("differing v"). Fix: `truncateWords()` word-boundary helper.
3. Count: static "39 autonomous NPCs" HTML predates char_500; every dynamic count reads 40. Fix: number bound to live `npcCount` via span.
4. Covert 1-vs-0: Shadowborn (comp_010) correctly bucketed as Covert Op, but name extraction failed (no source_char_name, verb 'aligned' missing from list) -> rendered "0 Covert Ops". Quick Status counted it from a different event copy. Fix: resolver consults char_name + char_id map (same helper as #1).
5. Custodian: NOT a bug - deliberately excluded from cognition via `EXTERNAL_AGENT_NPCS=char_001,char_306,char_500` (VPS `.env:46`, matching its read-only mandate). Mood key never written in 7 weeks (verified: no `npc_mood:char_500`, zero backend mentions) while decrees/quests/location all knew it. Per owner go-ahead ("follow your recommendation"): enrolled - env trimmed to char_001,char_306 (backup `.env.bak.custodian_20260927`), backend+worker recreated between ticks, new env verified in both containers. Proof within 2 ticks: mood rotating protective->alarmed->protective + first Custodian thought recorded.
6. MAIN RISK: `worstScore` init -1 let clean metrics (score 0) "win", so the healthy default was unreachable. Fix: init 0 (only flagged metrics score 2+).

| # | Test | Result |
|---|---|---|
| V1 | `node --check` (caught + fixed two `*/`-in-comment syntax breaks from the new helpers) | **PASS** |
| V2 | 17/17 node harness loading the real file (resolver incl. comp IDs/unknown passthrough, truncation incl. Sean's examples, risk calm/stressed/morale-crisis) | **PASS** exit 0 |
| V3 | Playwright live: overview "40", zero raw IDs page-wide, Main Risk default with morale at 100, Covert Ops named, zero console errors | **PASS** (one transient char_005 sighting, gone on re-run; uncovered briefing-summary/headline paths patched in second pass) |
| V4 | Custodian tick proof: mood rotation + first thought | **PASS** (decisions/actions still 0, expected next ticks - thought implies a decision object existed) |

Deploy: `simulation.js`/`simulation.html` scp'd to `public_html` (md5 local=host, nginx serves immediately, no restart). No backend code changed (env-only). Observed side note (not fixed, out of scope): Top Recent Events duplicates names ("Kyren Frostblade Kyren Frostblade ordered...") because descriptions already lead with the name.

### F7. Correction to F row 1 (key name)

The cited key `fed:monitor:last_auto_restart` does not exist - no code in the repo references the `fed:`-prefixed name, and `redis_helper.py` applies no key prefix. The real key is `monitor:last_auto_restart`, written by `monitoring/auto_restart.py:101`. Its live value re-verified as `1790479805.84` = exactly 03:30:05 UTC (TTL -1, no expiry). Timestamp, attribution, and conclusion stand; only the key name in F row 1 was mistranscribed.
