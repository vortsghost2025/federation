# DECISIONS LOG

Key decisions that constrain future architecture and workflow. Check before changing architecture.

| Date | Decision | Rationale / Source |
|------|----------|--------------------|
| 2026-09-27 | **Commit-everything mandate:** every completed work unit must be committed to GitHub with date/time and test results recorded, so all agent work is traceable at any time. API keys and secrets are NEVER committed — run the secret scan (see `TEST_RESULTS.md` §C) before staging/pushing. | Sean directive, 2026-09-27: "commit everything you do all the time to github without my api key … changes made, tests run, test results, dated, timestamped, committed" |
| 2026-09-27 | **DONE:** tamed `fallback_recovery.py` (two-strike guard + single-pass `--scan`) — deployed host-only, zero container restarts | Sean go-ahead 2026-09-27; TEST_RESULTS §F8 for verification |
| 2026-09-27 | **DONE:** Custodian enrolled in cognition (removed char_500 from `EXTERNAL_AGENT_NPCS`) — exclusion was deliberate per read-only mandate, owner chose enrollment | Sean "follow your recommendation" 2026-09-27; TEST_RESULTS §G item 5 |
| 2026-09-27 | **DECIDED (delegated): KEEP** `federation-game-monitor.sh` loop — read-only (proven), 5-min cadence, rotated 1MB logs, and its kilo reports flag real pair diagnostics (e.g. state-blob corruption lead). Restart suspicion fully retired by forensics | Sean "just decide" 2026-09-27; TEST_RESULTS §F5(a) + §H |
| 2026-09-27 | **DECIDED (delegated):** worker.py + npc_reflection.py drift — **synced VPS→git** (runtime truth). VPS was strictly ahead: Redis socket timeouts + full world-perturbation feature (worker), float-range bug fix + HGETALL quest-read fix (reflection). No deploys or restarts needed | Sean "just decide" 2026-09-27; TEST_RESULTS §H |
| 2026-09-27 | **DECIDED (delegated): website audit leftovers → GO, all executed** | Sean "just decide" 2026-09-27; TEST_RESULTS §H: earth crash fix, bridge consciousness mapping, constellation phantom-NPC fix (backend), starmap3d contrast, universe 41KB newer version shipped; index verified clean |
