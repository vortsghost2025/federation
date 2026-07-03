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
| 2026-06-15 | NVIDIA API key flagged for rotation (committed in `e587a11`) | Working copy clean but key persists in GitHub history at vortsghost2025/federation. Sean needs sighted help from brother to rotate. 18+ days old as of 2026-07-03 — STILL PENDING. | GLM-5.1 |
| 2026-06-24 | Starmap 3D architecture: Three.js CDN, single HTML, universe asset proxy + /universe/ nginx route | Vanilla JS / no-framework rule honored; `/universe/assets` and `/universe/` Traefik route needed for sector textures | Sean + Codex lane ([LANE-1] commits) |
| 2026-06-27 | Institutions subsystem architecture: `institution:*` registry + `role:*` + `workflow:*` + per-institution ledger | Move from "persistent individual councilors" toward "persistent institutions with durable roles, memory, workflows". Foundation for institutions-recovery spec (2026-06-27). | GLM-5.1 |
| 2026-06-27 | Analysis_review workflow type added (submitted→peer_review→endorsed) | Complements proposal_review; gives councilor char_306 (collective_oracle) a distinct institutional action surface | GLM-5.1 |
| 2026-06-27 | Two persistent councilors fixed: `char_001`=research_chief_mathematician (institution:research_division_council), `char_306`=collective_oracle (institution:consciousness_collective_council) | Stable named councilor identities powering the npc-agent-001 + npc-agent-306 containers; bind councilor workflow to institutions | GLM-5.1 + Sean |
| 2026-06-28 | P3 Outcome Memory: branch-scoring weights set (consecutive rejection suppresses `advance_goal` 42%, approval boosts 15%) | Trial-and-error balancing; 20-entry recent_outcomes cap prevents unbounded growth | GLM-5.1 |
| 2026-06-28 | Redis keys `npc:{id}:workflow_outcomes` (hash) + `npc:{id}:recent_outcomes` (list, lpush/ltrim cap 20) | Supports the back-feed from `_record_outcome` into `_get_npc_outcome_ctx` for outcome-aware next-decisions. 35/35 tests pass. | GLM-5.1 |
| 2026-06-28 | Councilor decrees = bounded world-state write access via rule-based `evaluate_decrees` + directive system (TTL 600s on `councilor:directive:active`) | Councilors can bias world-state without direct mutation. Cooldown on `councilor:decrees:cooldown:{char_id}`. 22/22 directive tests pass. | GLM-5.1 |
| 2026-06-28 | OpenRouter free pool rotation: 3 keys × 3 tier pools (LARGE/MID/SMALL) round-robin per task class + per-model circuit breaker | Maximizes use of free OpenRouter credits across 19+ free model IDs before falling back to paid/OR/Gemini/template | GLM-5.1 |
| 2026-06-28 | Gemini depleted cooldown: persist 1hr silence to Redis key `gemini_depleted` on HTTP 429 "Prepayment credits depleted" | Avoids burning requests on a 429-confirmed exhausted budget; auto-resumes after cooldown | GLM-5.1 |
| 2026-06-28 | Architectural pin of single-uvicorn-worker rule (== AGENTS.md critical constraint #1) | Multi-worker creates multiple `game_state` singletons → /event sets current_event on worker A, /choose sees None on worker B (2-hour production bug). MUST stay single-process; scale via external Redis/DB if needed. | GLM-5.1 |
| 2026-06-28 | `/choose` must ALWAYS return JSON with `"outcome"` key, never `raise HTTPException` (== AGENTS.md constraint #2) | Frontend calls `data.outcome.toUpperCase()` on every response; bare HTTPException crashes frontend with TypeError. Verified live in `routes/core.py` make_choice — all returns include `"outcome"`. | GLM-5.1 |
| 2026-06-28 | `gs.current_event = None` after successful choice in `make_choice` is intentional (== AGENTS.md constraint #3) | Without reset, the same event could be chosen repeatedly. Verified `routes/core.py:679` — unique assignment, no other reset anywhere in core. | GLM-5.1 |
| 2026-06-30 | NPC autonomy monolith split into 11 sibling modules (npc_needs/world/decree/reflection/thoughts/opinions/actions/interactions/goals + npc_decisions/context/llm_client) | 11-commit refactor wave `[1.3]`→`[7]` extracted concerns from monolithic `npc_autonomy.py` for maintainability and testability. NOTE: extracted home but NOT yet deployed to VPS — see status drift. | GLM-5.1 |
| 2026-07-01 | Phase 1 — Memory Bridge: both councilors emit + persist Redis memories across ticks | Enables continuous councilor continuity between player visits; verified live both councilors recording. | GLM-5.1 + Sean |
| 2026-07-03 | Session dispatch policy: orchestrator (GLM 5.2) does NOT route routine work through `general` subagents (= self-routing, hits own rate budget) | 18-subagent specialist pool maps to different model backends; routing primitives (read/grep/edit) through `explore`/`code-reviewer`/`docs-specialist`/`frontend-specialist` distributes load. Reserve `general`/`debug` for self-routed exceptional work where delegation is unsafe. | Sean + GLM-5.2 |
| 2026-07-03 | P007 partial implementation recorded as architectural fact | Edit 1 (leader timeout 30s across 4 leader tiers in `llm_router.py:870,877,884,891`) is live; Edit 2 (`LEADER_COOLDOWN_FAILURE` / `SPECIALIST_COOLDOWN_FAILURE` / `_set_cooldown`) was never implemented. Cooldown remains the coarse 3-failures → 300s pause at provider level. Spec acceptance criteria NOT met. | GLM-5.2 |
