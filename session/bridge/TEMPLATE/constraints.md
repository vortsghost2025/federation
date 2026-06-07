# Constraints: {PLAN_ID}

## Hard Rules
- [ ] No backend code changes
- [ ] No VPS deploys
- [ ] No Docker changes
- [ ] Only create files in `session/bridge/` and `.opencode/skills/`
- [ ] All files must be valid JSON or Markdown
- [ ] `context_pack.md` must stay under 2000 tokens (~500 words)
- [ ] `bridge_state.json` must be valid JSON with version field
- [ ] SKILL.md files must follow opencode skill format (frontmatter + body)

## Format Requirements
- JSON files: valid JSON, 2-space indent
- Markdown: standard GitHub-flavored markdown