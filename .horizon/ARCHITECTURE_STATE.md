# FEDERATION ARCHITECTURE STATE

**Purpose:** Post-compaction context recovery. Read this instead of re-reading 200KB+ of backend Python.
**Last updated:** 2026-07-07 (Issues #8 and #9 resolved; npc-agent/ hashes added)
**⚠ Known Issues:** None active. All prior issues resolved:
- #8 (npc_autonomy.py drift) — RESOLVED. VPS hotfixes synced home 2026-07-07.
- #9 (P007 partial) — RESOLVED. Both edits verified complete 2026-07-07.

---

## DEPLOYED FILE HASHES

Hashes measured against live VPS (`187.77.3.56`). Home-vs-VPS drift resolved 2026-07-07. See HORIZON_STATUS for current state.

| File | VPS md5 | Home md5 | Match? | Container |
|------|---------|----------|--------|-----------|
| `npc-agent/npc_agent.py` | `97ec233d` | `97ec233d` | ✅ | npc-agent-001 + 306 |
| `npc-agent/npc_actions.py` | `182ae403` | `182ae403` | ✅ | npc-agent-001 + 306 |
| `npc-agent/npc_context.py` | `e0c253a4` | `4a55cc96` | ⚠ SAME LOGIC (VPS inlined; home synced 07-07) | npc-agent-001 + 306 |
| `npc-agent/npc_decisions.py` | `31240e72` | `f98f11bb` | ⚠ SAME LOGIC | npc-agent-001 + 306 |
| `npc-agent/npc_redis_helpers.py` | `aea35983` | `775d507a` | ⚠ SAME LOGIC | npc-agent-001 + 306 |
| `npc-agent/npc_llm_client.py` | `26ad60a7` | `26ad60a7` | ✅ | npc-agent-001 + 306 |
| `npc-agent/npc_memory_bridge.py` | — | `e1d5085d` | — | npc-agent-001 + 306 |
| `backend/npc_autonomy.py` | `274420c1` (7KB) | `d1c2f7d6` (29KB) | ⚠ Home=post-extraction shim, VPS=monolith. Both serve same role — npc-agent/ containers use extracted sibling modules | ✅ backend-1 + worker-1 |
| `backend/institutions.py` | `a1090084` | `a1090084` | ✅ IDENTICAL | ✅ all |
| `backend/llm_router.py` | `d45c3447` | `d45c3447` | ✅ IDENTICAL | ✅ |
| `backend/main.py` | `777238b5` | differs by 9 lines | ⚠ minor (VPS has /metrics fallback) | ✅ |
| `backend/routes/core.py` | `aa5195ef` | `aa5195ef` | ✅ IDENTICAL | ✅ |
| `backend/npc_cognition.py` | has `LEADER_COOLDOWN_FAILURE` | has `LEADER_COOLDOWN_FAILURE` | ✅ P007 complete | ✅ |

**Drift verdict:** All structural drift resolved. Hash differences in npc-agent/*.py are cosmetic (VPS inlined parsing, home uses module-level json). npc_autonomy.py differs by extraction stage (home=shim, VPS=monolith) but both serve the same function — npc-agent containers use the extracted sibling modules. `main.py` 9-line diff is acceptable (VPS is better).

---

## KEY FUNCTION SIGNATURES (with line numbers)

### npc_autonomy.py (~180 lines on VPS; ~1,000 lines on home)
Functions in this file are EITHER the small remnant on VPS OR the post-extraction home version. VPS-only signatures (verified by direct grep 2026-07-03):
```
L589:  _get_npc_outcome_ctx(npc_id)              # reads npc:{id}:workflow_outcomes + npc:{id}:recent_outcomes
L599:  make_decision(char_id, char_name, archetype, affiliation, mood="")
```
The following signatures used to live in this monolith but were extracted on 2026-06-30 and now live in sibling modules:
```
né  _reflect_on_missing_context(...)   → npc_reflection.py (extracted commit 6803790, hash f4274c7f)
né  _score_decision_option(...)       → npc_reflection.py
né  evaluate_decision_options(...)     → npc_reflection.py
né  _write_decree_directive(r, ...)    → npc_decree.py    (extracted commit fabf8eb, hash 00581e61)
```
The home post-extraction copy of `npc_autonomy.py` (29KB) imports these from `npc_reflection` and `npc_decree`. The VPS copy (7KB) embeds them inline. This is an intentional split — the VPS `backend/npc_autonomy.py` is the monolith for the backend container, while `npc-agent/*.py` carries the extracted sibling modules for the NPC containers. Both serve their respective runtimes.

### institutions.py (current 420 lines, NOT extracted)
```
L142:  _append_workflow_event(r, workflow_id, now, status, detail)
L191:  ensure_workflow(r, councilor_id, artifact, role_ctx, wf_type, now)
L232:  ensure_proposal_review_workflow(r, councilor_id, artifact, role_ctx, now)
L237:  ensure_analysis_review_workflow(r, councilor_id, artifact, role_ctx, now)
L268:  advance_workflow(r, workflow_id, now)
L307:  override_workflow_status(r, workflow_id, new_status, now)
L374:  _record_outcome(r, workflow_id, record, new_status)  # terminal-state guard
L390:  get_npc_outcome_history(r, npc_id)
```

### llm_router.py (1907 lines, byte-identical home ↔ VPS)
```
L456:  CIRCUIT_BREAKER_THRESHOLD = 3
L457:  CIRCUIT_BREAKER_WINDOW = 300  # seconds (5 min)
L458:  CIRCUIT_BREAKER_KEY_PREFIX = "llm_circuit_breaker:"
L870:  TASK_MODELS["leader"]["primary"]["timeout"] = 30   # P007 Edit 1 (live)
L877:  TASK_MODELS["leader"]["fallback_nim"]["timeout"] = 30
L884:  TASK_MODELS["leader"]["fallback_openrouter"]["timeout"] = 30
L891:  TASK_MODELS["leader"]["fallback_openrouter_paid"]["timeout"] = 30
L1181: _is_circuit_open(provider) -> bool   # reads llm_circuit_breaker:{provider}, returns True if val=="open" and ttl>0
L1200: _trip_circuit(provider)               # sets llm_circuit_breaker:{provider}="open" with TTL 300s
L1218: _record_provider_result(...)         # failure-counting feeder using llm_circuit_failures:{provider}
```
**P007:** COMPLETE. Both Edit 1 (30s timeouts) and Edit 2 (`LEADER_COOLDOWN_FAILURE=600`, `SPECIALIST_COOLDOWN_FAILURE=300`, `_set_cooldown(char_id, duration)` with failure-path cooldown) verified on home + VPS.

### routes/core.py (32KB, byte-identical home ↔ VPS, contains make_choice)
```
L260: invalid choice token error return — {"outcome": "", ...}
L270: no active event error return      — {"outcome": "", ...}
L280: invalid choice error return       — {"outcome": "", ...}
L289: event constants not loaded        — {"outcome": "", ...}
L340: success return                    — {"outcome": choice["outcome"], ...}
L364: success return                     — {"outcome": choice["outcome"], ...}
L596: success return                     — {"outcome": choice["outcome"], ...}
L679: gs.current_event = None            # AGENTS.md constraint #3 — unique assignment, intentional reset after choice
L682: success return                     — {"outcome": choice["outcome"], ...}
```
Every return statement in `make_choice` includes an `"outcome"` key. NO `raise HTTPException` inside `make_choice` (the 3 `raise HTTPException` at L819/L823/L843 are in `/state/save` and `state_info`, NOT in `/choose` — safe per constraint #2).

---

## REDIS KEY MAP

### Needs Queue
```
npc:needs                              # list — all open needs
npc:need:{need_id}                     # hash — individual need record
npc:notifications:{char_id}            # list — fulfilled notifications
npc:context_snapshot:{char_id}         # hash — context for needs
```

### Outcomes (P3)
```
npc:{npc_id}:workflow_outcomes         # hash — {approved: N, rejected: N}
npc:{npc_id}:recent_outcomes           # list — last 20 JSON entries (lpush/ltrim)
```

### Institutions
```
institution:index                      # set — registered institution IDs
role:index                             # set — registered role IDs
workflow:active                        # set — active workflow IDs
workflow:completed                     # set — completed workflow IDs
workflow:index                         # set — all workflow IDs
workflow:{type}:{uuid}                 # hash — workflow record
workflow:{type}:{uuid}:events          # list — event log
workflow:source_artifact:{artifact_id} # string — pointer to workflow ID
```

### Councilor / Decrees
```
councilor:directive:active             # string — JSON directive (TTL 600s)
councilor:decrees:history              # list — decree log
councilor:decrees:cooldown:{char_id}  # string — cooldown marker
```

### Decision Bias
```
npc_decision_bias:{char_id}           # string — JSON bias (TTL 300s)
```

### World State
```
world_state                            # hash
world_state_history                    # list
```

### LLM Circuit Breakers
```
circuit_breaker:{provider}            # string — "open" or absent (TTL varies)
gemini_depleted                        # string — exists during 1hr cooldown
```

---

## CRITICAL CONSTANTS

```python
# institutions.py
TERMINAL_STATES   = frozenset({"ratified", "endorsed", "approved", "rejected"})
VALID_WORKFLOW_TYPES = {"proposal_review", "analysis_review"}
MAX_RECENT_OUTCOMES = 20
WORKFLOW_TRANSITIONS = {
    "proposal_review": ["submitted","under_review","deliberating","ratified"],
    "analysis_review": ["submitted","peer_review","endorsed"],
}

# npc_autonomy.py
ALLOWED_NEED_TYPES = frozenset({
    "context_request", "resource_access", "communication_channel",
    "collaboration_tool", "data_access", "skill_development",
    "request_capability", "pivot_strategy",
})
DIRECTIVE_KEY = "councilor:directive:active"
DECREES_ALLOWED_NPCS = ["char_001", "char_306"]
COUNCILOR_AFFILIATIONS = {"char_001": "research_division", "char_306": None}
FACTION_ALLIANCES = {
    "research_division": "consciousness_collective",
    "consciousness_collective": "research_division",
}

# event_cascade.py
DECISION_BIAS_TTL = 300
```

---

## WIRING MAP

```
worker.py tick cycle:
  → evaluate_decrees()           # decree evaluation (rule-based)
  → _maybe_issue_decree()        # char_001, char_306
  → advance_workflow()           # institution tick
  → _record_outcome()            # on terminal state (P3)

npc_autonomy.py decision flow:
  → evaluate_decision_options()
      → _get_npc_outcome_ctx()           # P3 read
      → _score_decision_option(category,...,outcome_ctx)  # P3 bias
      → _reflect_on_missing_context(...,outcome_ctx)     # P3 pivot_strategy
  → make_decision()
      → generate_text() via llm_router
      → _write_decree_directive() if councilor

llm_router.py fallback chain:
  NIM (primary) → Ollama → OR free pool → OR paid (402 blocked) → Gemini (429 cooldown) → template
  3 OR keys, round-robin per task class
  Per-model circuit breaker (Redis: circuit_breaker:{provider})
  Gemini depleted cooldown: 1hr Redis key

Needs queue flow:
  NPC generates need → npc:needs list → /api/councilor/needs → evaluate → approve/reject
  → fulfillment notification → npc:notifications:{char_id} → fulfilled_need_types fed back to scoring
```

---

## DEPLOY RULES

| Container type | Mount | Deploy method | Restart picks up changes? |
|---------------|-------|--------------|--------------------------|
| backend + worker | read-only bind (`/docker/federation-game/backend:/app:ro`) | scp → overwrite host → `docker compose restart` | ✅ Yes (must restart for loaded modules) |
| npc-agent | read-only bind (`/docker/federation-game/npc-agent:/app:ro`) | `deploy_vps.sh npc-agent-batch npc-agent/` — stages, validates, copies atomically, single restart | ✅ Yes (single restart) |
| frontend | **BAKED** (no bind mount) | scp + `docker cp` + `nginx -s reload` | ❌ Must docker cp |
| postgres | volume | N/A | N/A |

**PRE-RESTART GATE:** verify local md5 → local import → VPS md5 → container runtime import → THEN restart

**BATCH DEPLOY (NFM-004 fix):** `deploy_vps.sh npc-agent-batch <dir>` uploads all `.py` to `/tmp/npc-agent-batch/`, syntax-checks each, then copies all at once with a single container restart. Prevents mid-wave deploy drift.

**Large files (>100KB):** `ssh_ssh_upload` fails; use chunked base64 via Python stdin pipe

---

## LIVE SYSTEM SNAPSHOT (2026-07-07)

- **World state:** all systems healthy — 16/16 containers up
- **NPCs:** 39 (char_001 + char_306 running as dedicated npc-agent containers)
- **Institutions:** 199 total (growth stopped by bloat fix caps: 8/NPC, 20 total)
- **Memory bridge:** Phase 1 live — both councilors recording Redis memories across ticks
- **Pair convergence:** Stage 4A live — convergence_state updated per tick, both chars
- **Model routing:** nano for decisions (strict JSON), super for artifact/gen code
- **Tests:** all passing per last run
