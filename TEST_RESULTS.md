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

### G2. Follow-on: ZSET type bug suppressed ALL decisions/actions (2026-09-27)

Custodian verification exposed a second, larger bug: `/simulation/npcs/activity` reported `recent_decisions: []` and `recent_actions: []` for **every one of the 40 NPCs**, not just char_500. Root cause: `routes/simulation.py` pipelines 3+4 read `npc_decisions:{cid}` / `npc_actions:{cid}` with `LRANGE`, but those keys are ZSETs (score=timestamp, per `npc_autonomy.py` header). Each pipeline call raised WRONGTYPE, the except-block substituted empty lists, and the whole roster rendered decision/action-blind (thoughts worked because pipeline 2 already used ZREVRANGE). This is also why the Custodian "never acted" — its actions existed all along (decisions list had 200 entries); the endpoint just couldn't read them.

Fix: pipelines 3+4 switched to `zrevrange(..., 0, 2)`. Verified `faction_choice_history:*` (the file's only other lrange) is a genuine list — untouched. Deployed between ticks (10-min wait for running=False): host swap with `.bak.zsetfix_20260927`, pycache cleared, backend restarted (healthy 9s), md5 local=host=container `f502e45399adbf72fee85d19d43242b0`.

| # | Test | Result |
|---|---|---|
| V5 | Post-fix activity feed after one full tick | **PASS** - 40/40 NPCs with decisions+actions (was 0/40); Custodian: mood alarmed, 2 thoughts, 3 decisions, 3 actions |
| V6 | Playwright live re-verify | **PASS** - 40 count, zero raw IDs page-wide, Main Risk default at morale 100, covert ops named (incl. The Custodian), 0 console errors |

Second frontend pass: transient raw-ID sightings (char_104, comp_003) traced to four unhardened sitroom sections that render full event text (Expeditions, Holding the Line, Strange Signals, Forewarning) - all four now route through `resolveIds`; re-deployed md5 `e7401d62becffad71b06ddd5b2075649` local=host, harness 17/17, live page clean.

### F9. Post-tame restart census + new container ID (2026-09-27 evening)

After the two-strike guard (F8) and the Custodian force-recreate, three more restarts - all attributed, guard verified working end to end:

| Time (UTC) | Cause | Note |
|---|---|---|
| 16:45:20 | Nuclear A | Correctly required 2 strikes (16:30 + 16:45 crons both read health 0 - sustained NIM brownout) |
| 17:49:13 | **My force-recreate** (Custodian enrollment, G item 5) | Final stop line of old container `b51cdd58`; recreate made a NEW worker container id `3de734855ce7` - all future census greps must target the new id (old-id grep silently hides new stops) |
| 18:00:43 + 18:45:21 | Nuclears B, C | Same sustained-evening NIM brownout; health sat at 0 across consecutive checks. 18:45:21 stop invisible to old-id grep - found via new id |

Guard behavior confirmed live: transient dip at 16:30 = "strike 1/2, watching (no action)"; one cron blocked at "cooldown active (0.0 min)" (17:15 boundary, 3 seconds short - held); nuclears only on sustained failure. Evening brownout context: NIM 503s/20s-timeouts in npc-agent logs all day; health oscillating 0<->100 with ~9-min self-heal cycles; 3 sustained windows hit the 2-strike threshold. Old-regime comparison: 13 restarts by 15:55 vs 3 guarded restarts since, each with a 15-min confirmation window.

### F7. Correction to F row 1 (key name)

The cited key `fed:monitor:last_auto_restart` does not exist - no code in the repo references the `fed:`-prefixed name, and `redis_helper.py` applies no key prefix. The real key is `monitor:last_auto_restart`, written by `monitoring/auto_restart.py:101`. Its live value re-verified as `1790479805.84` = exactly 03:30:05 UTC (TTL -1, no expiry). Timestamp, attribution, and conclusion stand; only the key name in F row 1 was mistranscribed.

### H. Legacy decisions + website audit completion (2026-09-27 ~21:00 UTC)

Three delegated owner decisions ("just decide") executed.

**Decision 1 — monitor loop: KEEP.** Read-only (0 restart verbs, proven in F2), 5-min cadence, rotated 1MB logs (769KB + 6.5MB rotated), live kilo 7.3.16 on VPS producing real pair diagnostics (latest report flagged the pair's state-blob corruption lead). Its kmux tmux session `fed-monitor` continues unchanged.

**Decision 2 — drift sync (VPS→git).** worker.py: VPS 90 lines ahead (Redis socket timeouts 5s + complete env-gated world-perturbation feature with idempotency marker). npc_reflection.py: VPS has float-safe `_in_world_range` (old `in range(30,70)` breaks on floats) + quest read via hgetall (same WRONGTYPE class fixed in G2). Both synced VPS→local, md5-verified 903c41e5/71b19cf1, py_compile clean. No deploys/restarts (VPS already runs them).

**Decision 3 — website audit: GO, executed.**

| # | Item | Root cause | Fix | Verify |
|---|---|---|---|---|
| H1 | universe.html 12KB drift | Local git held a newer 41,482-byte version (committed in da3ab46 backup); VPS served older 30,033 | Deployed local→VPS with .bak.20260927 rollback | Playwright: renders clean, 0 console errors, sector list + orbit/zoom live |
| H2 | earth.html stalled widgets | `for (const f of data.factions)` on a dict -> "not iterable" -> rejection inside Promise.all killed the setInterval polling loop before it registered | Coerce to array + both Promise.all→allSettled so no single fetch can kill the loop + /state/load GET→POST | 0 console errors; faction panel populated (10 rows); era LEGACY ERA |
| H3 | bridge.html consciousness dead | updateConsciousness read cs.coherence/stability/complexity/awakeness which the API never ships (morale/identity/confidence/expansion_hunger) | Remapped with legacy fallbacks | coherence 70, awakeness 90, anxiety 20 (was 0/--) |
| H4 | constellation legend/NPC mislist | /map/data built NPC list from npc_location:* Redis keys — faction hubs carry those keys too, so 8 PHANTOM "NPCs" (id=faction_id, e.g. "Economic Council") leaked into every map consumer; plus tick-text showed UNKNOWN (worker.status field never existed) | Backend: filter faction-hub ids (hkeys faction_dynamics) in map_endpoints; Frontend: status derived from worker.enabled | 48→40 NPCs, 0 phantoms; "TICK 13 · ONLINE"; 8-faction legend intact |
| H5 | starmap3d contrast | #78909c text at 9-10px | Text→#b0bec5, 9px→11px, worldbar/faction-count 10→12px, JS label fallbacks brightened | Computed style: rgb(176,190,197) 11px |
| H6 | index.html contrast | — | No defect found: LCARS orange/blue on black, opacities are decorative animations only | VERIFIED-CLEAN, no change made |

**H-REGRESSION (caught + fixed same session):** my first map_endpoints deploy used a stale local base (md5 c1c6f72c) over a newer VPS version (b5980c42) — regressed three scan_iter perf fixes + the entire founded_areas section. Caught via affiliation-count verification, recovered from .bak.hubfilter_20260927, re-applied the hub filter onto the true base. LESSON (now Delta-logged): verify local-vs-VPS md5 on EVERY backend file before editing, not just known-drift ones.

**H-AFFIL (deeper bug found under H4):** /map/data + /simulation/npcs/activity served affiliations only within 5 min of each tick — npc_faction_context keys (TTL=300) were the only live source; npc_profiles blob has no writer; backend roster carries affiliation=None for rival/neutral/enigma chars + companions (worker mutates its OWN singleton, not the backend's). Fix: Source-0 fallback in map_endpoints._enrich_affiliation + activity route — read the backend roster, then ARCHETYPE_FACTION (same deterministic mapping the worker applies per-tick). Both endpoints now 40/40 affiliated at any point in the tick cycle. md5 local=host=container: map_endpoints 1a516446, routes/simulation 844ffa9e. Custodian live on both: preservation_society, stern, 3 decisions + 3 actions.


### I. 2026-11-07 health check + public-site outage recovery (~19:30-20:00 UTC)

**Finding 1 — site was DOWN ~2 weeks.** Public URL returned 000 (connection refused) from outside and from the VPS itself. Root cause: around Oct 24-27 the host-nginx federation-game site was removed (sites-available now holds only default+genesis, dir mtime Oct 27 06:49; nginx inactive, access.log.1 last entry Oct 24 16:46) in favor of traefik, but the reverse-proxy container recreated ~Oct 24 came up with NO port bindings and NO fed-net attachment (NetworkSettings.Ports={}, no networks, hence traefik errors "unable to find the IP address for the container"). Compose file (mtime Sep 27) still declares 80:80/443:443 — the running container mismatched it.

**Fix:** `docker compose up -d --no-deps --force-recreate reverse-proxy` (traefik is stateless; acme.json volume intact). After: docker-proxy listening 0.0.0.0/[::] :80/:443, traefik on fed-net 172.16.2.19, Ports 80/443 bound. No backend/worker restart, no tick interaction.

**Verification:** from local machine, HTTPS 200 on /, index, simulation, bridge, earth, constellation, starmap3d, universe, /healthz, /state, /map/data, /simulation/autonomous/status, /simulation/npcs/activity, /factions. Playwright public sweep: 7 pages, 0 console errors, simulation.html 0 raw IDs, bridge LINK OK + coherence 70, earth 8 faction rows, constellation "TICK 102 - ONLINE". Public /map/data: 40 NPCs, 0 missing affiliations, 0 phantom faction entries, tick 102.

**Finding 2 — sim healthy.** Tick 3912 completed in 26s, 40/40 NPCs with thoughts+actions+decisions+moods (Custodian active: alarmed, react_to_events score 6.51), faction dynamics 55-70, diplomacy/quests/tech steps error-free. LLM health 100, sole NIM key (NIM_API_KEY_1) probed 200 on chat/completions. Worker up since Nov 7 02:30.

**Finding 3 — overnight fallback nuclears attributed.** Worker stops Nov 7 00:15/01:00/01:45/02:30 (45-min spacing = */15 cron, 2-strike guard, 1800s cooldown) during a health-0 window; monitor:last_nuclear_reset=1794018603 ~ 02:26 UTC; fallback log CRITICAL lines match. Two-strike tame held: no restarts since 02:30 (17h+). Health 100 now, only brief strike-1 watch entries.

**Finding 4 — uncommitted Oct-12 DELTA_LOG entries** (stale-tick wedge clear, NIM key swap to single vault key) were still uncommitted locally; committed now with this entry.


### J. 2026-11-07 NIM silent model retirement + remap (~22:46-23:30 UTC)

**Event:** the councilor agents and backend logged `HTTP 404 {"status":404,"title":"Not Found","detail":"Function 'ac74040f-...': Not found for account '8yXT_...'"}` for `nvidia/nemotron-3-super-120b-a12b` while the model REMAINED LISTED in the account's `/v1/models` catalog (84 models). Live chat probes: super-120b 404; ultra-550b/lightning-30b/nano-omni/super-vl-120b/bolt-e4b all 200. Same failure class as the Sep-27 EOL but stealthier - catalog listing is no longer trustworthy; only live chat probes are.

**Blast radius before fix:** super-120b was primary for `specialist` + `npc_memory` task classes, fallback for `leader` + `narrator`, second entry of `nvidia_nim_client` MODEL_CHAIN, and `FALLBACK_MODEL_2` for both npc-agent containers (councilor drivers). Backend logged 774 function-404 lines total container lifetime; npc_memory calls fell through to OR free (daily cap 429) + OR paid (monthly $1 cap 403) => "All LLM providers failed" storms; agent logs showed 2k+ errors/48h.

**Remap (deployed 22:46-22:47 UTC, backend+worker between ticks, agents recreated):**
- llm_router TASK_MODELS: leader/narrator fallback_nim, specialist.primary, npc_memory.primary -> `nvidia/nemotron-3.5-super-vl-120b-a12b`
- nvidia_nim_client MODEL_CHAIN[1] -> super-vl (timeout 18)
- npc-agent npc_llm_client OR_FREE_POOL + defaults; compose FALLBACK_MODEL_2 x2 -> super-vl
- OR free pools (llm_router + nim_client): `nvidia/nemotron-3-super-120b-a12b:free` is DELISTED on OpenRouter too (404 "unavailable for free, paid slug only") -> replaced with nano-omni:free / dropped from LARGE
- Also noted: OR free tier daily cap exhausted + OR paid key monthly $1 cap exceeded (403) - OR tiers dark until resets; NIM is the live tier

**Verification (all post-deploy):** md5 local=host=container 518f3a91(llm_router)/5d27200c(nim_client)/ac036810(npc_llm_client)/385ce0aa(compose); npc_memory `route_call` functional test `{'success': True, ...}`; 0 function-404s since restart; failures since restart = one ~60s in-flight burst at 22:47 while the provider-level `llm_circuit_breaker:nim` key (Redis) cooled, then 0; next full tick completed (24 thoughts, live text); health 100 (single transient 0 readings absorbed by the two-strike guard, no nuclears); worker log clean.

**Overnight-nuclears reinterpretation:** the 00:15-02:30 worker restarts at 45-min spacing were the two-strike guard firing during genuine health-0 reads, which included this dead-model fallout window; breaker cooldown explains the oscillation. No restarts since 02:30.

**Opencode side finding (Sean's session error `Function 'f238fb4a-...' Not found for account`):** same NVIDIA account, but NOT the sim - it is OpenCode's `SessionRunner.drain` (session save/replay at server start) failing on a model in OpenCode's own config. Live probe of that config's model list found: `moonshotai/kimi-k2.6` 404 (function not found), `meta/llama-3.2-11b-vision-instruct` 410 Gone (EOL), `nvidia/nemotron-3-super-120b-a12b` 404 (already labeled in config). The exact f238fb4a function ID was not conclusively matched (candidates timed out rather than fast-404). Recommendation: prune the two unlabeled dead models from `C:\Users\seand\.config\opencode\opencode.json`.


### K. 2026-11-08 LLM key redundancy (second NIM key live, ~01:55-02:10 UTC)

**Change:** added a fresh NVIDIA API key as `NIM_API_KEY_7` in the VPS-only `/docker/federation-game/.env` (value withheld from all docs/commits; piped via stdin, never written to any local file; `.env` chmod 600; local `.env` files are gitignored - confirmed `git check-ignore` + clean `git status` before commit). Key live-probed BEFORE use: `/v1/models` 200 (84 models) and chat 200 on ultra-550b / super-vl-120b / lightning-30b / nano-omni; also confirmed super-120b 404 on this account too. No code change needed - `nvidia_nim_client` already scans `NIM_API_KEY_1..8`.

**Deploy:** gated on `fed:auto_tick_status running=False`, then `docker compose up -d --no-deps --force-recreate backend worker npc-agent-001 npc-agent-306` (env_file reload). All 4 containers healthy.

**Verification:** container env shows 7 `NIM_API_KEY_*` slots populated; `/simulation/nim-stats` went from `keys_available:1, keys_total:1` to **`keys_available:5, keys_total:5`** (client prunes empty/invalid slots); next full tick completed (23 thoughts, 214s, errors None); **0 "All LLM providers failed" and 0 function-404s since recreate**; `monitor:llm_health` 100; site HTTPS 200. Redundancy goal achieved: single-key SPOF removed.


### L. 2026-11-08 VPS maintenance reboot + ssh alias (~02:36-02:45 UTC)

**Context:** VPS flagged "System restart required" (34 updates, 12 security). Sean approved reboot. Pre-flight: all game containers `restart: unless-stopped`, docker enabled at boot, Redis RDB save policy active with persistent volume - ran `BGSAVE` (status ok, dump.rdb 318MB, DBSIZE 79088) before reboot.

**Result:** `shutdown -r now` 02:36:49Z; host back after ~120s. Redis state survived (DBSIZE 79101 post-boot, ticks resumed immediately). All 7 federation-game containers auto-started. Post-reboot tick completed in 179s with 30 thoughts and zero errors; 0 provider failures / 0 function-404s since boot; `monitor:llm_health` 100; nim keys 5/5; site HTTPS 200; md5 host=container unchanged (llm_router 518f3a91); `/var/run/reboot-required` cleared. **PROVEN: sim survives a full host reboot with no state loss.**

**Also:** added `Host vps` alias (187.77.3.56, root, id_ed25519) to local `~/.ssh/config` - `ssh vps` now works. Headless mirror synced to 12f0f49 (ff-only, clean tree) via tailscale ssh after `ssh headless` came back.


### M. 2026-11-08 frontend fix + pair housekeeping + operator check-in (~03:00-03:10 UTC)

**1. "Top Recent Events" duplicate-name fix (frontend-only).** Root cause: `npcDisplay(ev)` in `simulation.js` can extract the NPC name from the *description lead* (regex fallback), and the readable-summary renderer then prepended that name as a separate span before the description - so events whose description starts with the name rendered "Name Name verb...". Fix in `renderReadableSummary()`: skip the name span when `desc` already starts with the resolved name (`nameInDesc` check). Deployed to VPS `frontend/simulation.js` AND `public_html/simulation.js` (the two had drifted: frontend 94c4886a vs live e7401d62b - now both 87c2a1eb, container md5 matches, served over HTTPS verified via curl grep). `node --check` exit 0. No backend restart needed (static file).

**2. Stale pair agenda removed.** `npc_pair:char_001__char_306:agenda` ZSET had exactly one member, `agenda_ad35b16e8d361030` (2026-08-06, agenda_key `test_work_001`, status proposed, "capability-request producer bridge"). Removed via ZREM + DEL of the `...:agenda:agenda_ad35b16e8d361030` hash. ZCARD now 0, subkey gone, pair state otherwise untouched.

**3. Operator check-in sent to both councilors.** rpush'd a `moderator`-from message ("Moderator check-in: anything you need from us?" - asking for concrete needs: resources/capabilities/approvals/engineering changes/decisions, reply to moderator inbox) to `npc_messages:char_001:inbox` (msg_8209e1c5e588) and `npc_messages:char_306:inbox` (msg_848aa0b34e28), mirrored to `npc_messages:moderator:sent` (now 18). Schema matches existing moderator:sent entries (thread_conv__{cid}__moderator). Inbox lens verified = 1 each. **Not yet acked/replied at time of commit** - agents poll their own loop; watch `operator_ack:char_001/306` and `npc_messages:moderator:inbox`.

Sim health after all changes: 100, site 200, tick clean.


### N. 2026-11-08 sandbox `nonlocal` unblock + councilor replies (~15:00-15:10 UTC)

**1. Sandbox change (code):** removed `ast.Nonlocal` from `_SANDBOX_DENIED_NODES` in `npc-agent/npc_actions.py` (sole sandbox validator; backend's same-named module is unrelated). Safety reasoning: `nonlocal` can only rebind names in an enclosing function scope, never the runner's module globals (`ast.Global` stays denied); runner keeps `-I`, RLIMIT_AS/CPU/NPROC, restricted builtins, clean env. No tests asserted the old denial. Local `py_compile` OK.

**Deploy:** scp to VPS /tmp -> `py_compile` on VPS temp -> host backup `npc_actions.py.bak-20261108` (md5 94a3bcb0) -> host file replaced -> gated on `fed:auto_tick_status running=False` (waited 5 min) -> `compose up -d --no-deps --force-recreate npc-agent-001 npc-agent-306`. md5 local = host = container-001 = container-306 = **ad92da70**. Backend/worker untouched (they never import the agent's sandbox module).

**Live proof (run inside both agent containers):** `_execute_sandboxed_python` with a 3x `nonlocal` counter -> ok=True, output "3"; mutation closure -> "10" on 001, "2" on 306. Negative controls still enforced: `global x` -> denied, `import os` -> denied.

**2. Councilor replies (Redis messages):** answered both check-in replies. To char_001 (msg_f417aa1383df): nonlocal live + quest calibration answer (research objective gains per WORK PASS, not per artifact: +1 base, +1 if a skill keyword-matches the quest faction affiliation, +1 with prob ambition*0.4 when ambition>0.7; so ~1-3/pass toward 18; artifacts are narrative evidence only - mechanics confirmed in npc_quest_engine.py L902-917). To char_306 (msg_e22857774b15): nonlocal live + **echo crystal grant of 25** to origin-myth preservation modules (also recorded as Redis hash `moderator_grant:char_306:echo_crystals` + `moderator_grant_history`) + **artifact creation approved** (merge design requirements with 47-outpost temporal-incursion alert specs). Both rpush'd to `npc_messages:{cid}:inbox` and mirrored to `moderator:sent` (len 20); inbox lens verified = 1 each.

Sim health during change: health 100, site 200 throughout.


### O. 2026-11-08 web accessibility upgrades: size stepper + spoken digest page + copy-as-text (~20:40-21:10 UTC)

Operator-approved items 1-3 from the page-improvement list. Frontend-only plus one read-only endpoint; no game-logic changes.

**New files:** `frontend/a11y.js` (injected toolbar on any page: A-/A+ text-size stepper 14-32px persisted in localStorage `fed_font_px`, plus "Copy text" button copying `document.body.innerText` with clipboard-API + execCommand fallback; ARIA-labelled, 44px tap targets), `frontend/digest.html` + `frontend/digest.js` (spoken digest page: Atkinson Hyperlegible, 22px, skip link, linear prose sections rendered with textContent only - no HTML injection; fetches `/simulation/digest?format=json` every 60s; links to raw text mode).

**Edited:** `frontend/simulation.html` (nav link "Digest" + a11y.js), `frontend/spectator.html` (nav link + a11y.js; it already had skip link + copy-report), `backend/routes/simulation.py` (NEW read-only `GET /simulation/digest?format=json|text` composing tick status, LLM health, world state, cascade temperature, 8 recent events, councilor pair state, moderator inbox count; `format=text` returns PlainTextResponse prose).

**Deploy:** node --check + py_compile locally; scp to VPS /tmp; py_compile on VPS; backup `routes/simulation.py.bak-20261108`; static files placed in BOTH `frontend/` and `public_html/`; gated on between-ticks; recreated ONLY backend (worker.py does not import routes - verified). md5: static files identical local=host-frontend=host-public_html=frontend-container (a11y 365319c3, digest.html b228c03b, digest.js e92bca7e, simulation.html 116aaefa, spectator.html 3864f464); routes/simulation.py host=container f86feb30.

**Verification (over HTTPS):** /digest.html 200, /a11y.js 200, served simulation.html references a11y.js + digest.html; `/simulation/digest?format=json` returns live data (health 100, world state, 8 events, councilor shared goal/topic/focus, inbox 14); `?format=text` returns clean prose. Post-deploy tick completed 214.5s, 24 thoughts, errors None; 0 provider failures since backend recreate; health 100; site 200.

### O-note. 2026-11-09 ~00:45 UTC: the two councilor replies from 11-08 15:07 UTC were additionally mirrored into the production inbox schema (msg:inbox:{cid} ZSET + msg:{id} hash) because the agents' decision layer reads only that ZSET (pc_decisions.py L492-510, 'last moderator message wins'); legacy list entries kept as mirror. Verified zcard=1 per councilor with correct subjects. No restart needed.

### P. 2026-11-10 second persistent agent pair: Lyra Swiftwind (comp_001) + Shadowborn (comp_010) (~01:20-01:45 UTC)

**Why:** Sean approved promoting a second pair. Sim-data grounding: comp_010 Shadowborn is the actor in the latest live world event ("secretly aligned with Military Command operatives"); comp_001 Lyra Swiftwind carries the "vanished / undisclosed channels" thread (event promotion fired on her first agent tick). Their patrol routes intersect (veil <-> threshold), both at full memory depth (200). Canonical id->name confirmed against `universe/universe.json` (comp_010=Shadowborn, comp_001=Lyra Swiftwind).

**Code changes (all local-first, py_compile OK):**
1. `PAIR_IDS` made env-driven (`PAIR_IDS` env, default `char_001,char_306`) in 4 places: `npc-agent/npc_redis_helpers.py` L14, `npc-agent/npc_actions.py` L495, `npc-agent/npc_work_loop_adapter.py` L35, `shared/federation_work_loop/core.py` L844. Default unchanged -> councilor pair behavior identical. (`npc_agent_current.py` has its own hardcoded PAIR_IDS but is imported by nothing - left alone.)
2. `npc-agent/npc_context.py` roster fix: comp_001 -> Lyra Swiftwind, comp_010 -> Shadowborn (was stale: Shadowborn/Captain Valor).
3. `npc-agent/npc_agent.py` CONTACTS defaults += comp_001/comp_010; Redis `npc_agent:contacts` HSET seeded too.
4. `docker-compose.yml`: `EXTERNAL_AGENT_NPCS=char_001,char_306,comp_001,comp_010` on backend + worker (autonomy loop now skips all 4 external agents); NEW services `npc-agent-comp001` / `npc-agent-comp010` (CHAR_ID/NPC_NAME/PAIR_IDS=comp_001,comp_010, NVIDIA_API_KEY=${NIM_API_KEY_7}/${NIM_API_KEY_4} - both live-probed HTTP 200 chat 2026-11-10, PRIMARY_MODEL=super-vl-120b specialist tier for budget, DECISION_MODEL=nano-omni, TICK_INTERVAL=180 staggered vs councilors' 120, same volumes/net/limits as npc-agent-001).
5. `backend/routes/simulation.py` digest: pair discovery via `scan_iter("npc_pair:*:state")` + new `pairs` key in JSON (councilors key kept for back-compat); text format renders every non-councilor pair. Fixed a focus-label slice bug (`k[len('focus_')]` -> `k[len('focus_'):]`) caught in live text output.
6. `frontend/digest.js`: renders each extra pair as its own section.

**Deploy (between ticks, `fed:auto_tick_status running=False` confirmed twice):** scp 9 files to VPS /tmp -> py_compile on temp -> `.bak-20261110` backups -> host files replaced -> `docker compose config -q` OK -> contacts seeded -> `docker compose up -d` (recreated backend+worker for env, created comp001/comp010; 001/306 untouched, 34h uptime). md5 verified equal: host = backend container = all 4 agent containers = frontend container for every changed file (simulation.py 1d8840c6 then fa22c55d after fix; digest.js d0dea5c3 frontend=public_html=container; npc-agent files 8134c67b/e05e286f/53a542d7/21d4f923/9bd0b346; core.py 3ca8a81a; compose f80c3868). Backend restarted once more between ticks for the focus-label fix; md5 host=container fa22c55d.

**Live proof:** registry has all 4 agents (comp_001/comp_010 started:1794273936); both new agents cognized on tick 1 with LLM 200 OK (comp_010 decision write_code executed in sandbox via super-vl-120b; comp_001 promoted the "Lyra Swiftwind vanished" event); `npc_pair:comp_001__comp_010:state` + `:journal` (len 2) being written; digest JSON `pairs` = [char_001__char_306, comp_001__comp_010]; digest text shows "Agent pair comp_001 and comp_010" with correct `comp_001/comp_010 is focused on` labels; post-deploy tick auto_tick_1794273948678 completed running=False last_error='' with 0 comp decisions in tick result (EXTERNAL_AGENT_NPCS skip confirmed); nim-stats cycle 11/30 calls, keys 5/5, failures 0; health 100; site 200; digest.html 200. No [ERROR] in backend/worker/comp010 logs since deploy; comp_001 logged one caught "Bridge exception: No module named 'npc_autonomy'" (agent container lacks backend module; non-fatal, memory bridge still recorded; watch only).

**Watch items:** NIM cycle budget over next 24h with 4 agents; councilor reply acks still pending (pre-existing); comp pair journal growth.

