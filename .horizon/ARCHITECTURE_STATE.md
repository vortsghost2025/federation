# FEDERATION ARCHITECTURE STATE

**Purpose:** Post-compaction context recovery. Read this instead of re-reading 200KB+ of backend Python.
**Last updated:** 2026-07-03 (npc_autonomy pin corrected after 06-30 extraction wave; P007 partial status noted)
**⚠ Known Issues:**
1. `npc_autonomy.py` pin below was refreshed 2026-07-03 — describes VPS reality, which is the 06-28 pre-extraction monolith (~180 lines). Home copy drifted earlier via 06-30 extraction commits that split the file into 11 sibling modules but were NOT deployed. See `.horizon/HORIZON_STATUS.md` Known Issues #8.
2. The line numbers L2396 / L2838 in the older version of this file described a now-defunct monolith. They were correct on 2026-06-28 and became stale on 2026-06-30 when the extraction wave ran. Use the live line numbers below.
3. P007 leader cognition Edit 2 (cooldown constants) was never implemented — see `.horizon/HORIZON_STATUS.md` Known Issues #9.

---

## DEPLOYED FILE HASHES

These hashes are measured against the live VPS at `187.77.3.56:/docker/federation-game/backend/` (probe date 2026-07-03). Home copies may drift — see `.horizon/HORIZON_STATUS.md` for the home-vs-VPS diff status.

| File | Live VPS md5 | Home md5 | Match? | Container sync |
|------|-----------|----------|--------|---------------|
| `npc-agent/npc_agent.py` | `18ebf18a` | (not measured this session) | assumed | ✅ agent-001 + agent-306 |
| `backend/npc_autonomy.py` | `274420c1889820378ca8b9ef462f92cc` (~180 lines, 7KB) | `d1c2f7d647a30285d8a6c22b3fbc64fb` (~1,000 lines, 29KB) | ❌ DRIFT | ✅ all 4 containers (VPS version) |
| `backend/institutions.py` | `a10900844ef5ec59ab492e21de8c4855` | `a10900844ef5ec59ab492e21de8c4855` | ✅ IDENTICAL | ✅ all 4 containers + npc-agent |
| `backend/llm_router.py` | `d45c3447149c0cad9304c90a88754ef0` (1907 lines, 69KB) | `d45c3447149c0cad9304c90a88754ef0` | ✅ IDENTICAL | ✅ |
| `backend/main.py` | `777238b564515840711a0eccd6235e92` (385 lines, has `/metrics` fallback) | differs by 9 lines (home lacks `/metrics` fallback) | ❌ minor | ✅ |
| `backend/event_cascade.py` | (not measured this session) | — | — | ✅ (per older pin) |
| `backend/routes/core.py` | `aa5195ef16cc28c19b5975849e8e268a` (32KB) | `aa5195ef16cc28c19b5975849e8e268a` | ✅ IDENTICAL | ✅ |
| `backend/npc_decree.py` | `00581e61cc196399ab62326c29ea62cf` | `00581e61cc196399ab62326c29ea62cf` | ✅ IDENTICAL | ✅ (extracted 06-30 fabf8eb) |
| `backend/npc_goals.py` | `4dcd1a008b7478ed8f5a890ee207894d` | `4dcd1a008b7478ed8f5a890ee207894d` | ✅ IDENTICAL | ✅ (extracted 06-30 c4545c5) |
| `backend/npc_interactions.py` | `386b414c4cbbd2d028f0ccad9621d405` | `386b414c4cbbd2d028f0ccad9621d405` | ✅ IDENTICAL | ✅ (extracted 06-30 a1d1f71) |
| `backend/npc_reflection.py` | `f4274c7f2984d22cde965c04e17e6bb1` | `f4274c7f2984d22cde965c04e17e6bb1` | ✅ IDENTICAL | ✅ (extracted 06-30 6803790) |

**Drift verdict:** the only structurally divergent file is `npc_autonomy.py` (VPS pre-extraction vs home post-extraction). `main.py` differs only in the 9-line `/metrics` fallback that VPS has and home lacks — VPS is the better version. All other audited files are byte-identical.

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
The home post-extraction copy of `npc_autonomy.py` (29KB) imports these from `npc_reflection` and `npc_decree`. The VPS copy (7KB) still embeds them inline — see Known Issues #1 above.

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
**P007 Edit 2 status:** constants `LEADER_COOLDOWN_FAILURE` / `SPECIALIST_COOLDOWN_FAILURE` and function `_set_cooldown` are **ABSENT** — never implemented. The current cooldown is the coarse `_trip_circuit` (one provider → 300s pause, no per-task-class differentiation). See HORIZON_STATUS Known Issues #9.

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
| npc-agent | read-only bind (`/docker/federation-game/npc-agent:/app:ro`) | scp → overwrite host → `docker compose restart` | ✅ Yes (must restart for boot code like startup scrub) |
| frontend | **BAKED** (no bind mount) | scp + `docker cp` + `nginx -s reload` | ❌ Must docker cp |
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
