# Recovery Triage - 2026-06-27

## Scope

This note captures the current post-recovery triage state:

- what is already live
- how to treat `stash@{0}` and `stash@{1}`
- which dirty-tree paths are obvious scratch versus paths that still need review

## Live Recovery Changes Already In Working Tree

These local modifications are intentional and correspond to the live councilor recovery that was deployed to the VPS:

- `federation-game/backend/worker.py`
- `federation-game/docker-compose.yml`

These untracked local-only files are also part of the real recovery path and should not be deleted as scratch:

- `federation-game/backend/councilor_bridge.py`
- `federation-game/backend/npc_world_snapshot.py`
- `federation-game/backend/routes/agents.py`
- `federation-game/frontend/council-chat.html`
- `federation-game/docs/COUNCILOR_ANALYSIS.md`
- `federation-game/npc-agent/Dockerfile`
- `federation-game/npc-agent/cosmic_monitor.py`
- `federation-game/npc-agent/requirements.txt`

## Stash 0

`stash@{0}` is not disposable. It is runtime and UI work and should be reviewed in an isolated branch or worktree, not popped onto the current dirty tree.

### Keep / Compare First

- `federation-game/backend/llm_router.py`
- `federation-game/backend/main.py`
- `federation-game/backend/routes/error_reports.py`
- `federation-game/backend/worker.py`
- `federation-game/docker-compose.yml`
- `federation-game/frontend/fed-fetch.js`
- `federation-game/frontend/simulation.css`
- `federation-game/frontend/simulation.html`
- `federation-game/frontend/simulation.js`
- `federation-game/frontend/spectator.css`
- `federation-game/frontend/spectator.html`
- `federation-game/frontend/spectator.js`
- `federation-game/npc-agent/npc_agent.py`

Reason: these are still plausibly relevant to active runtime behavior, observability, or operator UX.

### Compare Carefully Against Current Recovery Work

- `federation-game/backend/worker.py`
- `federation-game/docker-compose.yml`

Reason: both files were modified in the live recovery. Any stash restore here needs a manual merge, not an overwrite.

### Low Priority / Probably Local Meta

- `.gitignore`
- `.kiloignore`
- `AGENTS.md`
- `federation-game/.env.example`
- `federation-game/backend/autonomous_choice_resolver.py`
- `federation-game/backend/simulation_engine.py`
- `federation-game/frontend/adult.html`
- `federation-game/frontend/error-reporter.js`

Reason: these may still hold useful edits, but they are not on the shortest path for institutions or live stability.

## Stash 1

`stash@{1}` is theory/demo/documentation work. It is not on the critical runtime path.

### Keep As Reference

- `README.md`
- `federation-game/README.md`
- `federation-game/frontend/index.html`

### Defer Until Runtime Path Is Stable

- `demo_federation_complete_game.py`
- `federation_game_npcs.py`

Reason: these look like demo or narrative scaffolding, not current production recovery work.

## Dirty Tree Cleanup Buckets

### Safe To Delete As Scratch Or Backups

- `.compact-audit/`
- `.hermes/`
- `.kiloignore.backup-20260618-094242`
- `AGENTS.md.backup-20260618-100410`
- `.horizon/federation-initial.png`
- `.horizon/page-status.txt`
- `docs/Done..txt`
- `docs/FORCODEX.txt`
- `docs/cred.txt`
- `docs/httpsfederation-game.deliberatefede.txt`
- root malformed file `,m[Destination],m.get(Type,...)`
- screenshot files under `photos/` with names starting `Screenshot ` or `screenshot-`

### Keep For Review

- `CONTINUATION_TASK.md`
- `.horizon/describe-live-page.md`
- `.horizon/loop-control-proposal.md`
- `.horizon/telegram-vs-live-mismatch.md`
- `docs/SYNTHESIS_REPORT_20260618.md`
- `docs/re-establishingederationont.txt`
- `tools/`
- all local-only `federation-game/...` councilor files listed above

## Recommended Next Merge Order

1. Commit the live recovery files already verified on the VPS.
2. Review `stash@{0}` in the isolated worktree and cherry-pick only high-value runtime/UI changes.
3. Ignore `stash@{1}` until institutions work has started or documentation is being refreshed.
