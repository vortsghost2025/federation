# Federation Desktop ↔ VPS Reconciliation — 2026-08-08

Status: **DONE (snapshots + canonical merge created, pushed to GitHub)**

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

## Verification

- Desktop: back on `main` at `7c90aae`, clean.
- VPS repo (`/opt/federation`): back on `main` at `c28b9dc`, clean.
- All four branches pushed to GitHub: `main` (unchanged), 3 recovery branches, 1 reconciliation branch.
- PAT used for pushes was scrubbed from git config after each push; revoke it after review.

## Next steps

1. Review `reconciliation/merge-2026-08-08` (diff vs `main`: 73 files, +18452/−11300).
2. When approved: fast-forward `main` to the merge, or open a PR.
3. Deploy pass: copy canonical backend/npc-agent/frontend into `/docker/federation-game` and restart services per AGENTS.md workflow (npc-agent is bind-mounted; backend restart required).
4. Consider `git merge --strategy=ours` none needed; both recovery branches can be deleted after main advances.
5. Out-of-tree VPS material is now fully covered: `/docker/federation-architect`, `/docker/federation-worktrees/architect` (empty), `/root/federation-kilo-handoffs/` → `recovery/architect-2026-08-08` (unrelated history branch in the same GitHub repo). The only uncommitted artifact left there is a `__pycache__` `.pyc` (recompile-recoverable).
