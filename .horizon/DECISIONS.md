# DECISIONS LOG

Key decisions that constrain future architecture and workflow. Check before changing architecture.

| Date | Decision | Rationale / Source |
|------|----------|--------------------|
| 2026-09-27 | **Commit-everything mandate:** every completed work unit must be committed to GitHub with date/time and test results recorded, so all agent work is traceable at any time. API keys and secrets are NEVER committed — run the secret scan (see `TEST_RESULTS.md` §C) before staging/pushing. | Sean directive, 2026-09-27: "commit everything you do all the time to github without my api key … changes made, tests run, test results, dated, timestamped, committed" |
| 2026-09-27 | **PENDING owner:** keep or stop `federation-game-monitor.sh` periodic kilo loop | Review TEST_RESULTS §F5(a); verify-mode 2026-09-27 confirmed script has 0 restart verbs (read-only) |
| 2026-09-27 | **PENDING owner:** VPS-vs-local `worker.py` / `npc_reflection.py` drift direction — sync to git or leave | Review TEST_RESULTS §F5(b); md5s still diverged as of 2026-09-27 |
| 2026-09-27 | **DONE:** tamed `fallback_recovery.py` (two-strike guard + single-pass `--scan`) — deployed host-only, zero container restarts | Sean go-ahead 2026-09-27; TEST_RESULTS §F8 for verification |
| 2026-09-27 | **PENDING owner:** website audit leftovers (earth/bridge/constellation/starmap3d/index/universe items) — go or hold | Website audit VERIFY list; galaxy-map + nav deploy already live |
