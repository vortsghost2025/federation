# Federation Desktop ↔ VPS Reconciliation — 2026-08-08

Status: **DONE (snapshots + canonical merge created, correction pass applied, pushed to GitHub)**

## Why this happened

Desktop repo (`S:\federation`, mounted at `/home/we4free/mnt/s-drive/federation`) and the
VPS both carried divergent work. The desktop had ~60 uncommitted working-tree changes;
the VPS had its own uncommitted files plus a live runtime (`/docker/federation-game`)
holding patches that existed in no git repo at all. The goal: preserve every change
set, then produce one canonical merged tree.

## Recovery branches (all pushed to `vortsghost2025/federation`)

| Branch | Commit | Contents |
|---|---|---|
| `recovery/desktop-2026-08-08` | `ebbdee9` | Desktop working-tree state: 60 files (backend, memory, messaging, simulation, frontend, deployment, docs, `.horizon`, `.kilo/kilo.json`) |
| `recovery/vps-2026-08-08` | `7767a1d` | VPS git working-tree state: `councilor_bridge.py`, `npc_world_snapshot.py`, `starmap3d.html` live edits (VPS `main` itself is an ancestor of GitHub `main`) |
| `recovery/runtime-2026-08-08` | `b4f67df` | Live runtime source overlay from `/docker/federation-game` (97 files): modular npc-agent set, live-patched backend files |
| `recovery/architect-2026-08-08` | (from `/docker/federation-architect` @ `6905aa5`) | Builder/architect infrastructure: full `phase2-builder-agent` history (45M .git) + uncommitted `state/registry.json`, `comparison_summary.md`, plus `/root/federation-kilo-handoffs/` docs (capability-request preflight/producer, VPS live scope audit, architect loop phase1) |

## Canonical merge

`reconciliation/merge-2026-08-08` — created from `origin/main` (`7c90aae`), then three merges:

- `ed76c53` — desktop snapshot (clean)
- `0a71313` — VPS snapshot (3 conflicts, all resolved to desktop superset)
- `e1d7d29` — runtime snapshot (16 conflicts resolved; see below)

Final tree: 743 tracked files. All merged Python files pass `py_compile`.

## Conflict resolutions (preserving both change sets)

Runtime (theirs) won where it was the live, more-evolved design; desktop (ours) won
where it was a strict superset; every losing version remains fully recoverable in the
recovery branches above.

- `councilor_bridge.py`, `routes/councilor_needs.py` — **desktop** (superset: dedupe, institutions, relationships)
- `npc_agent.py` — **runtime** (thin modular loader; monolith preserved in desktop recovery branch)
- `npc_autonomy.py` — **runtime** (modularized; inline need/artifact logic extracted to councilor_bridge)
- `npc_actions.py` — **runtime** (work-loop adapter bridge with legacy fallback)
- `npc_decisions.py` — **runtime** (robust `_extract_json` incl. `ast.literal_eval`)
- `llm_router.py` — **runtime** (superset: audit/attribution layer, prompt cache, telemetry)
- `main.py` — **runtime** (adds admin/councilor_exchange routers, metrics None-guard)
- `routes/metrics.py` — **runtime** (lazy registry init, decision counters, null guards)
- `routes/decrees.py` — **runtime** (operator auth via `require_operator`)
- `frontend/*` (`council-chat`, `simulation.css/html/js`, `spectator.html`) — **runtime** (plain-fetch vs fedFetch; `computeVerdict` refactor)
- `starmap3d.html` — **ours** (LANE-1 cosmic-scale evolution supersedes older runtime iteration)

## Correction pass (review findings, committed after merge)

Independent review of the merge surfaced three gaps; all fixed forward on the branch:

1. **Stale shared work-loop core.** The reconciled `shared/federation_work_loop/core.py` was an old 10-action version; the live runtime's core has 11 actions including `area_found` (dispatch + `_action_area_found`). Overlaid the live core so `create_area → handle_found_area → area_found` works end-to-end. Verified: `area_found` registered, dispatched, adapter imports (`_WORK_LOOP_OK=True`).
2. **NPC container wiring.** `docker-compose-vps.yml` had no npc-agent services at all, and neither compose gave NPC containers the shared package. Added `npc-agent-001`/`npc-agent-306` to the VPS compose mirroring the live containers (bind-mount `/docker/federation-game/npc-agent:/app:ro` + `/docker/federation-game/shared:/opt/federation_shared:ro`, `PYTHONPATH=/opt/federation_shared`, live model/env config via env vars, no hardcoded keys); backend gained the shared mount + PYTHONPATH; dev compose NPC services gained shared mount + PYTHONPATH.
3. **Junk classification.** 104 forensic/recovery-only files removed from the canonical branch (43 replay captures, audit/debug/investigate scripts, `.horizon/`/`.kilo/`/`.recovery/` agent state, one-off Windows verify scripts, nginx/simulation `.bak` files, genesis harness captures/samples). All remain on the recovery branches. `.gitignore` (line 91+: `federation-game/backend/_*.py`, `fix2.py`, …) already keeps the live runtime's debug scripts out of git.

Test gap fixed: `test_institutions.py` FakeRedis mock gained `hincrby`, `ltrim`, and a faithful Python translation of the `_APPLY_EFFECTS_LUA` `eval` semantics (idempotency, cutoff skip, caps, clamping, rounding, receipts).

## Verification

- Desktop: back on `main` at `7c90aae`, clean.
- VPS repo (`/opt/federation`): back on `main` at `c28b9dc`, clean.
- All branches pushed to GitHub: `main` (unchanged), 4 recovery branches, 1 reconciliation branch.
- PAT used for pushes was scrubbed from git config after each push; revoke it after review.
- Tests: npc-agent 22/22 passed; institutions 9/9 passed (after mock fixes, zero skips); full `compileall` clean; both compose files YAML-valid; adapter import smoke test OK.
- Real branch-vs-main scope after classification: **156 files changed (+32258/−13293)** — the "73 files" figure in earlier notes was one merge commit's stat, not the branch scope.

## Next steps

1. Review `reconciliation/merge-2026-08-08` (diff vs `main`: 156 files, +32258/−13293).
2. When approved: fast-forward `main` to the merge, or open a PR.
3. Deploy pass: copy canonical backend/npc-agent/frontend/shared into `/docker/federation-game` and restart services per AGENTS.md workflow (npc-agent is bind-mounted; backend restart required). Compose now describes the full NPC setup.
4. Consider `git merge --strategy=ours` none needed; both recovery branches can be deleted after main advances.
5. Out-of-tree VPS material is now fully covered: `/docker/federation-architect`, `/docker/federation-worktrees/architect` (empty), `/root/federation-kilo-handoffs/` → `recovery/architect-2026-08-08` (unrelated history branch in the same GitHub repo). The only uncommitted artifact left there is a `__pycache__` `.pyc` (recompile-recoverable).

## Deploy completion addendum (2026-08-08 ~01:45 UTC)

- Local `main` fast-forwarded to `58396dc` (identical to PR head). Direct push of `main` rejected by branch protection (required approving review) → opened **PR #7** (`reconciliation/merge-2026-08-08` → `main`).
- Deployed from locally-promoted main: backend (129 files), npc-agent (18), frontend (43), shared (3) rsynced into `/docker/federation-game`; md5 verified canonical == runtime for `shared/federation_work_loop/core.py` (`9822cca5…`), `npc_agent.py` (`97ec233d…`), `npc_messaging.py` (`1c30f6b8…`). Restarted backend, worker, npc-agent-001, npc-agent-306. All healthy; frontend untouched (baked image, 5 days uptime).
- Frontend convergence: live `public_html` (container-served) held uncommitted hotfixes (spectator open_question_ref/fedFetch rendering, council-chat idempotency, error-reporter 404-disable, starmap density modes, accessibility CSS). Folded runtime-newer files into canonical; deployed git-newer pages (adult/worldguide/starmap tabs, AI chat suggestions, error-reporter include, favicon) to runtime. nginx config (mounted `frontend/nginx-default.conf`, Docker-DNS resolver) reloaded; all three frontend copies now md5-identical. Commit `d02af2f`.
- Fixed regression the reconciliation introduced: `/councilor/areas` route was dropped from canonical `routes/councilor_needs.py` (present in live runtime snapshot `b4f67df`); restored, deployed, backend restarted — endpoint returns `ok, count=46`. Commit `61888ae`. Heartbeat areas check green again (`last_areas=46`).
- Architect restored: `heartbeat_loop.sh` + `spectator_loop.sh` relaunched (nohup, logged under `/var/lib/dagu/state/architect/`); browserless screenshot service (port 32769) and dagu were already up. Screenshots flowing every 60s; heartbeat cycles complete with 3 capreqs tracked, 4 decisions/10m per char.
- PR #7 head now `61888ae`, mergeable, **blocked on required approving review** — needs one approval + merge from a reviewer with write access, then desktop sync (`tailscale ssh root@ubuntu-headless-we` → `git fetch origin && git checkout main && git merge --ff-only origin/main`). PAT still active for post-merge sync; revoke after.

## Code-review fix pass (2026-08-08 ~02:55 UTC)

Applied the review fix pass (1 CRITICAL + 4 WARNING) to the reconciliation branch; all verified live on the backend container (`federation-game-backend-1`, bind-mounted, restarted, healthy):

1. **CRITICAL — `backend/main.py` `ProxyHeadersMiddleware trusted_hosts="*"` → `"172.16.2.10,172.16.2.11"`** (Traefik + frontend nginx on fed-net; verified IPs via `docker inspect`). Uvicorn 0.51 source (read in-container) confirmed: XFF is only processed when the direct socket peer is in `trusted_hosts`, then right-most untrusted XFF entry wins. Verified live: public-visitor simulation (fed-net container → Traefik, `Host: federation-game.deliberatefederation.cloud`) now gets **401** on `/api/admin/status`, `/api/councilor/areas`, `/api/councilor/capability-requests`; spoofed `X-Forwarded-For: 100.64.0.5`/`8.8.8.8` does **not** bypass (still 401); `/api/spectator/agency` and `/api/healthz` still public (200). Before the fix, `always_trust` took `XFF[0]` — any public visitor or fed-net peer could spoof a Tailscale/loopback client and reach operator routes.
2. **WARN — `routes/agents.py` `post_agent_message` / `request_self_diagnostic` returned an unqueued payload**: response `message` now comes from `_queue_message(...)` return (actual stored message). Verified: POST returned `msg_45234c8cfd52`, `id == msg_id`, and the identical JSON exists in `npc_messages:{id}:inbox` tail and `msg:{id}` key (test message + keys cleaned up afterwards).
3. **WARN — unauthenticated operator GETs now `require_operator`**: `routes/admin.py` `/admin/status`; `routes/councilor_needs.py` `/councilor/areas`, `/councilor/capability-requests`, `/councilor/capability-requests/{id}`. `operator_auth` trusts Tailscale (`100.64.0.0/10`) + loopback only. Verified: in-container loopback (architect heartbeat path) returns 200 — `areas` count 52→53 (pair keeps founding sectors; the 46 in the earlier addendum was already stale), capability-requests 200, admin/status 200; fed-net peer direct + spoofed XFF → 401; host-origin NAT (172.16.2.1) → 401, same as before the change (not a regression).
4. **WARN — `read` schema mismatch**: `agents.py` payloads were bool `False` while `npc_messaging.py` stores string `"false"` (redis-py rejects bool mapping values). Normalized `agents.py` (`_build_message_payload`, `_queue_message`) to `"read": "false"`. Verified response and stored message both carry the string.
5. **WARN — baked backup junk removed** from canonical and `/docker/federation-game`: `frontend/spectator.html.1`, `spectator.css.1`, `spectator.js.1`, `nginx-default.conf.1`, `starmap.tmp`, `backend/npc_autonomy_backup_20260628.py` (3019 lines, zero imports). All were git-tracked; commit records the deletions. Frontend pages still serve 200 (baked container unaffected); runtime backend tree md5-identical to canonical (all 4 edited files verified inside the running container).

Frontend caller audit (pre-lock): no JS/HTML calls `/councilor/*`; `admin.html` calls `/api/admin/status` (operator-only dashboard — intended consumer, works from Tailscale/loopback); `council-chat.html` calls `/api/agents/*` (messages/broadcast/self-diagnostic — left open by design, not in scope). npc-agent Python uses work-loop functions directly, no HTTP to these routes.

Observed (not changed, for the record): running backend container was created with stale CLI flags `--proxy-headers --forwarded-allow-ips 172.16.2.7` (postgres container IP — not a proxy); the canonical `docker-compose-vps.yml` already specifies bare `uvicorn main:app --host 0.0.0.0 --port 8000`, so a future `docker compose up -d --force-recreate` will drop the stale flag. The running Traefik container also lacks `--api.insecure=true` (compose declares it) — not needed for operation.

PR #7 head will be updated to this commit; still blocked on required approving review.

## NPC-agent loop/parse fix pass (2026-08-08 ~03:45 UTC)

Diagnosed from 2h live logs (`docker logs federation-game-npc-agent-001-1 / -306-1`): both external agents were stuck in a `create_area` loop re-proposing `lumen_confluence` (idempotent guard fired every ~120s), char_306 was resting ~11/51 decisions on LLM JSON parse failures, and `area_found` raised `TypeError: int() argument must be ... not 'ellipsis'`.

Root causes found and fixed (deployed to `/docker/federation-game`, mirrored to canonical, md5-verified inside both containers):

1. **Notifications never consumed by the external agent**: the idempotent guard pushes `area_already_founded` to `npc:system_notifications:{char_id}`, but `npc_decisions.decide_action` never read that inbox — so the agent never learned the area exists. Added `_consume_system_notifications()` (drains inbox into the prompt as SYSTEM NOTIFICATIONS) and `_current_areas_summary()` (pair map list injected as CURRENT WORLD MAP with an explicit "use a NEW area_id" instruction).
2. **`ast.literal_eval` accepts `...`**: LLM outputs like `"danger_level": ...` parse into the Ellipsis singleton → `int(...)` TypeError in `_action_area_found`. Added `_unwrap_decision` (recursive Ellipsis → `""`, unwraps `{'content': '<json>'}` envelopes) in `_extract_json`, plus a brace-scan pre-pass for single-quoted envelopes containing apostrophes, and hardened `core.py` `_action_area_found` with `_clean_str`/`_coerce_int`/`_coerce_float` (Ellipsis-safe, defense in depth).
3. **Parse failure → forced `rest`**: prose-only or truncated LLM output fell back to resting. Added one hardened retry (`decide_retry`, explicit raw-JSON mandate, no envelope/no prose); if the retry also fails, falls back to `read_artifacts` instead of rest.
4. **Deterministic area guard**: `npc_actions.execute_decision` now checks `area_exists_on_map(area_id)` before executing `create_area`; existing areas are rerouted to `read_artifacts` (recursive execute), so the weak decision model can never re-found an area even if it ignores the prompt constraint.
5. **Stale moderator directive purged** (state, not code): the inbox still held "create_area restored — found Lumen Confluence now", which the agent followed every tick against the idempotent guard. Removed from `npc_messages:{char_001,char_306}:inbox` (kept the overnight-summary message).

Verified live after restart (both containers, md5-identical to canonical):
- Map grew 54 → 56 with three genuinely new areas (`stellar_harmony`, `crystal_veil`, `anchor_echo`); no `area_found idempotent` lines since the guard deploy.
- Zero parse-failure rests; retry path exercised once and succeeded; no Ellipsis TypeErrors.
- Decisions diversified: create_artifact, create_institution, submit_to_institution, read_artifacts.
- Backend + worker restarted (shared `core.py` change) — no errors in logs.
