# Verification: {PLAN_ID}

1. `cat session/bridge/{PLAN_ID}/context_pack.md | wc -w` → must be < 500 words
2. `jq . session/bridge/bridge_state.json` → must be valid JSON with version, active_plan, status
3. `ls .opencode/skills/bridge-write/` → must exist with SKILL.md
4. `ls .opencode/skills/bridge-read/` → must exist with SKILL.md
5. `ls .opencode/skills/bridge-sync/` → must exist with SKILL.md
6. `ls session/bridge/{PLAN_ID}/` → must contain all 5 files (plan.md, context_pack.md, file_targets.json, constraints.md, verification.md)