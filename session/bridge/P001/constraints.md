# Constraints: P001

## Hard Rules
- [ ] No backend code changes (federation-game/backend/)
- [ ] No VPS deploys (no ssh hostinger commands)
- [ ] No Docker/docker-compose changes
- [ ] Only create files in `session/bridge/` and `.opencode/skills/`
- [ ] All files must be valid JSON or Markdown
- [ ] `context_pack.md` must stay under 2000 tokens (~500 words)
- [ ] `bridge_state.json` must be valid JSON with version field
- [ ] SKILL.md files must follow opencode skill format (frontmatter + body)
- [ ] Plan mode (GLM) writes plan packs; Build mode (Nemotron) executes them
- [ ] No agent executes its own plan — strict mode separation

## Format Requirements
- JSON files: valid JSON, 2-space indent
- Markdown: standard GitHub-flavored markdown
- SKILL.md frontmatter: name, description (required)