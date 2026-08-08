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
