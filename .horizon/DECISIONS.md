# DECISIONS LOG

Key decisions that constrain future architecture and workflow. Check before changing architecture.

| Date | Decision | Rationale / Source |
|------|----------|--------------------|
| 2026-09-27 | **Commit-everything mandate:** every completed work unit must be committed to GitHub with date/time and test results recorded, so all agent work is traceable at any time. API keys and secrets are NEVER committed — run the secret scan (see `TEST_RESULTS.md` §C) before staging/pushing. | Sean directive, 2026-09-27: "commit everything you do all the time to github without my api key … changes made, tests run, test results, dated, timestamped, committed" |
