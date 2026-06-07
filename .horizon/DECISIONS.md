# Key Decisions Log
**Project:** Federation
**Started:** 2026-06-07

| Date | Decision | Rationale | Who |
|------|----------|-----------|-----|
| 2026-06-07 | Event token (UUID) over asyncio lock for race condition | Stateless, scales, no race, matches REST principles | Wave AI + Codex + GLM (consensus) |
| 2026-06-07 | Backward-compatible choice_token (Query param, optional) | Legacy callers still work, frontend can migrate incrementally | Codex |
| 2026-06-07 | TTL sweep (300s) on pending_choices | Prevents memory leak from abandoned sessions | Codex |
| 2026-06-07 | state.py split into 3 files (constants + helpers + class) | 1109-line monolith prevention, circular imports solved via late import | GLM-5.1 |
| 2026-06-07 | Alembic stamp-at-head for existing tables | No data loss, no failed migrations on existing DB | GLM-5.1 |
| 2026-06-07 | Pipe-over-SSH deploy (not SCP) | SCP from Windows to VPS times out >60s | GLM-5.1 |
| 2026-06-07 | Single uvicorn worker enforced | Multi-worker creates multiple game_state singletons = 2-hour production bug | GLM-5.1 |
| 2026-06-07 | Mode assignment: Plan=GLM, Build=Nemotron | GLM sub-agent fanout negates 128k; Nemotron 1M handles execution | GLM + Sean |
| 2026-06-07 | Bridge purpose = plan delivery, not context survival | Same-session mode switches preserve context natively | GLM-5.1 |
| 2026-06-07 | No agent executes its own plan | Prevents race conditions like P001 build collision | GLM + Sean |
| 2026-06-07 | Bridge storage = local files in session/bridge/ | Zero infra, git-trackable, machine+human readable | GLM-5.1 |
| 2026-06-07 | 3-layer memory: L1 conversation, L2 handoff files, L3 knowledge graph | Progressive persistence from ephemeral to durable | GLM-5.1 |
| 2026-06-07 | context_pack.md <2000 tokens | Fits in compacted context without dominating | GLM-5.1 |
| 2026-06-07 | Plan IDs = sequential P001/P002 | Simple, easy to reference, no naming bikeshedding | GLM-5.1 |
| 2026-06-07 | Stability recovery mechanic in apply_governance_pressure | Death spiral below 35 had no recovery path | GLM-5.1 |
| 2026-06-07 | No HTTPException in /choose and /event handlers | Frontend expects JSON with "outcome" key, not 4xx/5xx errors | AGENTS.md constraint |
| 2026-06-07 | docker-compose.yml deploy block indentation is correct | Wave AI verified — plan agent's "2-space" claim was wrong | Wave AI |
| 2026-06-07 | SSH config cleanup (hostinger-vps → public IP) | Duplicate entry overrode correct IP with unreachable Tailscale IP | Wave AI |
| 2026-06-07 | Starmap.js base = Codex's deployed VPS version | Live VPS file is source of truth for spatial fix | NEM 3 Ultra plan |
