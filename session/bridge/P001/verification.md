# Verification: P001

1. `cat session/bridge/P001/context_pack.md | wc -w` → must be < 500 words
2. `jq . session/bridge/bridge_state.json` → must be valid JSON with version, active_plan, status
3. `ls .opencode/skills/bridge-write/` → must exist with SKILL.md
4. `ls .opencode/skills/bridge-read/` → must exist with SKILL.md
5. `ls .opencode/skills/bridge-sync/` → must exist with SKILL.md
6. `ls session/bridge/P001/` → must contain all 5 files (plan.md, context_pack.md, file_targets.json, constraints.md, verification.md)
7. `jq -e '.version == "1.0" and .active_plan == "P001" and .status == "completed"' session/bridge/bridge_state.json` → must exit 0
8. `jq -e '.plan_history | length > 0 and .[0].plan_id == "P001"' session/bridge/bridge_state.json` → must exit 0