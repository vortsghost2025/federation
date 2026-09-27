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
