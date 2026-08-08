=== DESKTOP (S:\federation) vs VPS (/docker/federation-game) ===
DESKTOP structure (from user listing):
  .github, .kilo, .global, .identity, .secrets, .ollama, .ruff_cache,
  .recovery, .gitignore, federation-game/, AGENTS.md, docker/
VPS workspace structure (this workspace, NO .git):
  .env + 15 .env.bak.*, .kb.staging.new, .kilo (node_modules),
  AGENTS.md, backend/, docs/, docker-compose.yml, federation-game/ subdir,
  frontend/, npc-agent/, public_html/, scripts/
IDENTITY CHECK: NOT IDENTICAL. Desktop has source control artifacts; VPS is deployed runtime.
Before any sync: confirm desktop federation-game/ content matches VPS backend/npc-agent/frontend.
