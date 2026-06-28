# FEDERATION ARCHITECTURE STATE

**Purpose:** Post-compaction context recovery. Read this instead of re-reading 200KB+ of backend Python.
**Last updated:** 2026-06-28 (P3 complete)

---

## DEPLOYED FILE HASHES

| File | md5 (host) | Container sync |
|------|-----------|---------------|
| `backend/npc_autonomy.py` | `ae3475acda9596ef9de311ec9cf72ae7` | ✅ all 4 containers |
| `backend/institutions.py` | `a10900844ef5ec59ab492e21de8c4855` | ✅ all 4 containers |
| `backend/llm_router.py` | `b8c5d3f...` | ✅ deployed |
| `backend/event_cascade.py` | deployed | ✅ |
| `backend/test_needs_queue.py` | 35/35 pass | local only |

---

## KEY FUNCTION SIGNATURES (with line numbers)

### npc_autonomy.py
```
L2396: _get_npc_outcome_ctx(npc_id)
L2407: _reflect_on_missing_context(npc_id, recent_decisions, inst_ctx, world_ctx, fulfilled_need_types, outcome_ctx)
L2592: _score_decision_option(category, char_id, archetype, mood, has_active_goals, has_allies, has_rivals, recent_event_count, broadcast_event_count=0, has_active_quests=False, inst_ctx=None, need_reflection=None, fulfilled_need_types=None, affiliation=None, outcome_ctx=None)
L2709: evaluate_decision_options(char_id, char_name, archetype, affiliation, mood, fulfilled_need_types)
L2838: make_decision(char_id, char_name, archetype, affiliation, mood)
L3262: _write_decree_directive(r, char_id, metric)
L1181: _is_circuit_open(provider)   # [llm_router]
L1200: _trip_circuit(provider)      # [llm_router]
```

### institutions.py
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
| backend + worker | read-only bind | scp → overwrite host → `docker compose restart` | ✅ Yes |
| npc-agent | no bind | scp → `docker cp` → `docker restart` | ⚠️ Must docker cp |
| postgres | volume | N/A | N/A |

**PRE-RESTART GATE:** verify local md5 → local import → VPS md5 → container runtime import → THEN restart

**Large files (>100KB):** `ssh_ssh_upload` fails; use chunked base64 via Python stdin pipe

---

## LIVE SYSTEM SNAPSHOT (2026-06-28)

- **World state:** stability≈45, morale≈63.72, tension≈37.3, anomaly≈29.42, resources≈61.18, threat≈26.54
- **NPCs:** 39 (29 active, 5 hidden, 4 traveling, 1 corrupted)
- **Decisions:** 410
- **Institutions:** 2 (research_division_council, consciousness_collective_council)
- **Active workflows:** 4
- **Tests:** 35/35 pass
- **Dirty tree:** institutions.py + npc_autonomy.py (P3, committed but not yet pushed)
