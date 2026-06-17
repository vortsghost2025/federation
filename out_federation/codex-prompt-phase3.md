## Codex review prompt (Phase 3)

Goal: review 4 specific dirty-tree files for correctness vs visible feature intent. **Do not act. Do not write. Do not commit. Just read, reason, and reply.**

### Background (so you don't repeat discovery)

The active branch `main` has 26 dirty files at commit `8265504` (P010). Most are clear keep/discard after first-pass triage by another agent (me, Hermes). Four need a second pair of eyes because the surface area is too large or the risk is too coupled.

Three of them are blocked on a separate question that was raised at the end of codex's last session: **the Postgres `public` schema looks empty under direct query, but `/npc-turns/analyze` still returns fleet data**. Until that routing mystery is closed, any change in `federation_game_db.py` or `simulation_operator.py` should be marked as **NOT-SHIP**.

### Files to review

`S:\federation\federation-game\frontend\starmap.js` — massive rewrite (2720+/2706-). I'm guessing it's a feature build for the starmap UI, but the visual diff structure suggests wholesale file replacement rather than incremental edits. **Question:** Is the rewrite functionally equivalent to the previous version, or is it introducing new behavior?

`S:\federation\federation-game\backend\simulation_operator.py` — 126 lines added. New YAML config load, apprise notification, recovery keys, TTL settings. Stylistically consistent with the existing `worker.py` module. **Question:** Does the new operator duplicate logic vs the existing `tick_engine`? Is the public-API surface (`run_simulation_operator_tick`, `get_operator_status`) compatible with what `routes/simulation.py` expects?

`S:\federation\federation-game\backend\routes\simulation.py` — 7+/9-, refactors `POST /simulation/operator/tick` from `tick_engine` into `simulation_operator`. **Question:** Is this a strict functional equivalent, or is behavior changing in subtle ways (especially around the running-tick gate)?

`S:\federation\federation-game\backend\federation_game_db.py` — 803+/399-, persistence layer rewrite. **BLOCKED on Postgres-state anomaly.** If you can solve the public-schema-empty-but-data-still-flows mystery in the same review pass, that would unblock everything. Otherwise just flag this file as "do not ship until state mystery resolved."

### Discard-likely shortlist — sanity check only

If you spot anything in the discard-likely tier that doesn't look like a no-op, flag it. Most are 1-line cosmetic noise or forward-compat scaffolding for a NIM-key path that's already saturated. User confirmed they're not a bottleneck.

One specific question that survives the discard tier:

`S:\federation\federation-game\docker-compose-vps.yml` — the 8/4 lines is a mix of (a) NVIDIA_API_KEY env injection (DISCARD, dead-code today, NIM rotation is fine) and (b) Traefik path-prefix expansion. The user already noted the production yaml has only `env_file: - .env` and no `environment:` block. **Focus on the Traefik half:** what path-prefixes does the diff add? Are they already served by `nginx-default.conf`'s new `location` blocks (60 lines, RECOVER-tier)? If yes, Traefik half is also redundant — VPS Traefik routes to backend via hostname and Traefik path controls which requests get forwarded. The new nginx `location` blocks proxy to backend already for those paths. If the Traefik path-prefix expansion mirrors the nginx locations, both are belt-and-suspenders and either can carry without the other.

### Output shape

Reply with one verdict per file:
- `KEEP` / `DISCARD` / `RECOVER` / `NOT-SHIP-BLOCKED-ON-PUBLIC-SCHEMA`
- One-paragraph reason
- One to three concrete suggestions if action is recommended (no `git` commands; just describe what change you'd make)
- No novel questions that require another agent to re-explain the dirty tree; if context is missing, ask

Cost budget: please keep this tight. Two pass-through reads max. Reuse whatever cache you've already built against commit `8265504`.
