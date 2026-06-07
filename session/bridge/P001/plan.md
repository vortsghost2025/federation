# Plan: P001 — Build Agent Bridge System

## Objective
Create the persistent agent bridge system (plan↔build mode context handoff) with plan packs, bridge state, and 3 opencode skills.

## Steps
1. Create `session/bridge/bridge_state.json` with initial schema v1.0
2. Create `.opencode/skills/bridge-write/SKILL.md` — plan mode writer skill
3. Create `.opencode/skills/bridge-read/SKILL.md` — build mode reader/executor skill
4. Create `.opencode/skills/bridge-sync/SKILL.md` — milestone sync skill
5. Create `session/bridge/P001/plan.md` — this file
6. Create `session/bridge/P001/context_pack.md` — compressed project context (<2000 tokens)
7. Create `session/bridge/P001/file_targets.json` — machine-readable file operations for this plan
8. Create `session/bridge/P001/constraints.md` — hard rules for P001 execution
9. Create `session/bridge/P001/verification.md` — pass/fail verification checks
10. Run all verification checks from verification.md
11. Update bridge_state.json status to "completed", add P001 to plan_history

## Success Criteria
- [ ] bridge_state.json exists with valid JSON, version 1.0, active_plan "P001"
- [ ] 3 skills exist with valid SKILL.md frontmatter + body
- [ ] P001 directory contains all 5 plan pack files
- [ ] context_pack.md < 500 words (~2000 tokens)
- [ ] All verification commands pass
- [ ] bridge_state.json status = "completed", P001 in plan_history