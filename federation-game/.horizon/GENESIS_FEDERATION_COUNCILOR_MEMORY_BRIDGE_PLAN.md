# Genesis → Federation Councilor Memory Bridge — Phase 1 Plan
**Status:** Design  
**Scope:** `char_001` (Archimedes Prime) and `char_306` (The Oracle) only  
**Files modified:** 0 (design only; implementation deferred)  

---

## 1. Current Federation Councilor Flow

Both councilors run as isolated Docker containers (`npc-agent-001`, `npc-agent-306`) sharing a Redis connection. Each iterates a loop in `npc_agent.py`:

```
sleep(TICK_INTERVAL=30)
  → think_about_world(r)           # npc_context.py — builds world snapshot
  → decide_action(context, r)      # npc_decisions.py — constructs LLM prompt, calls call_llm()
  → execute_decision(decision, r)  # npc_actions.py — writes artifacts, mood, messages to Redis
```

### What enters the LLM prompt (inside `decide_action`):

1. `SELF_INTRO` — static system prompt (role, world description, 8 factions, ethical rules)
2. `think_about_world()` output — neighborhood snapshots, cosmic horizon, broadcast events, partner state, inbox messages
3. Instruction to return JSON with `thought`, `action`, `goal`

### What exits:

- A JSON decision parsed from the LLM response
- Written into Redis via `execute_decision()`: artifacts (`npc_artifacts:{char_id}`), mood, inbox, pair-journal, stats, topic fatigue counters

### Critical gap:

**Nothing in the prompt tells the councilor what it thought, decided, or learned on previous ticks.** The SELF_INTRO claims "You have persistent memory" — but no memory data is loaded. Every tick is a fresh context window. The councilor cannot recall its own past decisions, discoveries, or goals across ticks.

### Existing memory infrastructure (relevant but not used by councilors):

- `backend/npc_memory.py` — ZSET-based memory store with significance scoring; `harvest_tick_memories()` processes backend-managed NPCs. Councilors (`EXTERNAL_AGENT_NPCS`) are explicitly excluded from this.
- `npc_redis_helpers.py` — pair state (shared topic, open question), journals, thread messages. These are *current working state*, not persistent memory.

---

## 2. Where Memory Enters the Prompt

### Injection point: `npc_decisions.py:decide_action()`

Currently, `decide_action()` receives `context` (from `think_about_world()`) and builds a system + user prompt. The injection site is after the world-context block and before the JSON-format instruction:

```
[Current prompt structure]
  SELF_INTRO
  ## World Context (neighborhood, events, partner, inbox)
  ## Your Memories          ← NEW SECTION
  [event] (tick 142, imp 0.8): ...
  [idea] (tick 140, imp 0.6): ...
  [observation] (tick 138, imp 0.7): ...
  ## Output Format (JSON instruction)
```

### Retrieval strategy:

```
get_context_for_prompt(tick, max_memories=8)
  → Recently accessed memories (tick > current - 10)
  → High-importance memories (importance >= 0.7, top 3-5)
  → Deduplicated, sorted by recency, truncated to max_memories
  → Formatted as bullet list with type tag, tick, and importance
```

### What a memory-poor response looks like today:

```
{"thought": "I observe the Federation.", "action": "I analyze the latest reports.", "goal": "Understand the current situation."}
```

### What a memory-rich response looks like (target):

```
{"thought": "Last tick I discovered the anomaly in sector 7. My analysis was cut short. I should continue where I left off.", "action": "I request the research division's anomaly data from Commander Valorix.", "goal": "Complete anomaly investigation before the Council meeting."}
```

The memory section bridges the gap between ticks. It is not a transcript — it is a synthesized summary of what the agent has done, thought, and learned, weighted by importance and recency.

---

## 3. Where Memories Are Written (Post-Action Recording)

### Injection point: `npc_actions.py:execute_decision()`

After `execute_decision()` writes artifacts, mood, and messages to Redis, a new step appends typed memories from the decision result:

```
execute_decision(decision, r, CONTACTS)
  → write artifacts, mood, messages (existing)
  → record_councilor_memory(decision, r, tick)  ← NEW
```

### What gets recorded (mapped from Genesis patterns):

| Decision field → | Memory type | Conditions |
|---|---|---|
| `decision["thought"]` (if > 10 chars, not generic) | `idea` | Always, importance 0.5 |
| `decision["action"]` (if non-empty) | `event` | Always, importance 0.4 |
| Discovery/discovery-like action keywords | `observation` | If action matches discover/find/uncover/reveal |
| Interaction with other NPC (`to` field present) | `relationship` | If action involves another NPC |
| New artifact type mentioned | `skill` | If action creates/modifies artifact |

### Recording logic:

```
def record_councilor_memory(decision, r, tick):
    thought = decision.get("thought", "")
    action = decision.get("action", "")
    goal = decision.get("goal", "")

    # Always store thought as idea
    if len(thought) > 10:
        importance = _compute_importance(thought, action)
        _add_memory("idea", thought, tick, importance)

    # Store action as event
    if action:
        _add_memory("event", action, tick, 0.4)

    # Detect discoveries for observation type
    if _has_discovery_keywords(action):
        _add_memory("observation", action, tick, 0.7)

    # Detect relationship moments
    if decision.get("to") or _has_social_keywords(action):
        _add_memory("relationship", action, tick, 0.3)

    # Auto-consolidate every 10 ticks
    if tick > 0 and tick % 10 == 0:
        _consolidate(max_memories=100)
```

### Importance heuristic:

```
_compute_importance(thought, action)
  → Base: 0.5
  + 0.3 if "discover" / "find" / "reveal" in thought or action
  + 0.2 if "critical" / "emergency" / "warning" present
  + 0.1 if "relationship" / "trust" / "alliance" present
  + 0.1 if action creates an artifact
  - 0.1 if thought matches generic pattern (95%+ similar to previous)
```

---

## 4. Redis Key Design

All memory keys live under a `councilor_memory:` namespace to avoid collisions with existing Federation keys.

| Key | Type | Purpose | TTL |
|---|---|---|---|
| `councilor_memory:{char_id}:memories` | ZSET (score = tick) | All memories, chronological order | None |
| `councilor_memory:{char_id}:important` | ZSET (score = importance) | High-importance lookup | None |
| `councilor_memory:{char_id}:next_seq` | STRING | Auto-incrementing sequence counter | None |
| `councilor_memory:{char_id}:stats` | HASH | Count by type, last tick, total | None |

### Memory value encoding (JSON string stored in ZSET member):

```
{
  "id": "{char_id}_mem_{seq}",
  "type": "event|idea|observation|relationship|skill",
  "content": "truncated to 500 chars",
  "tick": 142,
  "importance": 0.7,
  "accessed_count": 0,
  "created_at": 1779825600
}
```

### Rationale for ZSET over LIST:

- ZSET allows O(log N) range queries by tick score (`zrevrangebyscore` for "recent N ticks")
- ZSET allows O(log N) range queries by importance score (`zrevrangebyscore` for "most important")
- Each memory is a single member, deduplication is trivial (`zadd` with fixed score replaces)
- Consistent with existing `npc_memory.py` ZSET pattern in `backend/`

### Why not use Genesis's flat JSON file storage:

- Federation already has Redis running; adding file I/O to containerized agents adds deployment complexity (volume mounts, permissions)
- Redis ZSETs provide the same query patterns (recent, important) with less operational surface
- Redis persistence (RDB/AOF) already handles durability
- The data model (typed memories with importance, tick, content) is the same — only the backend differs

---

## 5. Exact Files to Modify (Implementation Phase)

All files are under `S:/federation/federation-game/npc-agent/`. No backend files change. No frontend files change.

### File 1 (new): `npc_memory_bridge.py`
- `CouncilorMemory` class — typed Redis-backed memory store for one councilor
- Methods: `add()`, `get_context_for_prompt()`, `get_stats()`, `consolidate()`, `clear()`
- Importance scoring heuristics
- Discovery/social keyword matchers
- Type-specific wrappers: `add_event()`, `add_idea()`, `add_observation()`, `add_relationship()`, `add_skill()`

### File 2 (modify): `npc_context.py`
- Import `CouncilorMemory` from `npc_memory_bridge`
- Add `load_councilor_memories(r, char_id)` function
- Call it inside `think_about_world()` — append memory context to the returned snapshot dict under a `memories` key

### File 3 (modify): `npc_decisions.py`
- In `decide_action()`: extract `memories` key from context, format into prompt as `## Your Memories` section

### File 4 (modify): `npc_actions.py`
- Import `CouncilorMemory` from `npc_memory_bridge`
- In `execute_decision()`: after existing logic, call `record_councilor_memory()` bridge function
- Auto-consolidate every 10 ticks

### Dependency graph:

```
npc_memory_bridge.py  (new, standalone)
    ↑
npc_context.py        (imports bridge, calls load_councilor_memories)
npc_actions.py        (imports bridge, calls record_councilor_memory)
    ↑
npc_decisions.py      (reads memories from context dict, formats into prompt)
    ↑
npc_agent.py          (unchanged — loop already passes context through chain)
```

No changes to `npc_agent.py` are required. The existing `think → decide → act` pipeline already carries `context` dict through every function. Adding a `memories` key to the dict is sufficient — `decide_action` reads it, `execute_decision` writes to it via the bridge.

No changes to `npc_redis_helpers.py` are required. The memory bridge has its own Redis connection and key namespace.

---

## 6. Test Plan (Implementation Phase)

### Unit tests (run locally, no container):

1. **Memory add + retrieval cycle:** Add 5 memories of different types. Verify `get_context_for_prompt()` returns them sorted by recency, with type tags and tick numbers.
2. **Importance filtering:** Add 3 low-importance (0.2) and 2 high-importance (0.9) memories. Verify `get_important()` returns only the 2 high-importance entries.
3. **Deduplication:** Add same memory twice. Verify ZSET prevents duplicate members at the same score.
4. **Consolidation:** Add 200 memories. Consolidate to max 100. Verify only 100 remain and they are the highest-scored by `importance * 0.6 + recency_normalized * 0.4`.
5. **Redis key isolation:** Verify all keys start with `councilor_memory:` and no existing Federation keys are touched.

### Integration tests (in container, against real Redis):

6. **Full-tick memory persistence:** Run one `think → decide → act` cycle. Verify `councilor_memory:{char_id}:memories` contains 1-3 entries.
7. **Cross-tick memory retrieval:** Run 3 ticks. On the 4th tick, verify `get_context_for_prompt()` returns memories from ticks 1-3.
8. **Consolidation threshold:** Run 15 ticks. Verify consolidation fires at tick 10 and again at tick 20.
9. **Rolling restart:** Stop and restart the councilor container. Verify memories survive (Redis persists independently of the container).

### Acceptance criteria:

- `/api/admin/status` shows memory stats (total memories, by type, last tick)
- LLM response references a prior tick's discovery or decision (qualitative check — run 10 ticks, inspect decision JSON for cross-tick reference)
- No new ERROR-level log entries from `npc_memory_bridge`
- No increase in LLM call latency beyond 200ms (memory retrieval is Redis ZSET `zrevrangebyscore`, O(log N + M))

---

## 7. Rollback Plan

### If memory bridge causes LLM failures (parse errors, empty responses, degraded quality):

**Immediate rollback:**
1. Comment out the `record_councilor_memory()` call in `npc_actions.py`
2. Comment out the memory-section injection in `npc_decisions.py`
3. Comment out the `load_councilor_memories()` call in `npc_context.py`
4. Redeploy all three files via `deploy_vps.sh`
5. Restart both councilor containers
6. Delete `councilor_memory:*` keys from Redis to leave no trace

### If memory causes prompt-bloat (context window pressure):

- Reduce `max_memories` from 8 to 4 in `get_context_for_prompt()` — no redeploy needed if stored as env var or Redis config key
- Or exclude low-importance memories below 0.5 threshold

### If Redis memory usage increases unacceptably:

- Reduce `MAX_MEMORIES_PER_TYPE` from 200 to 50
- Shorten content truncation from 500 to 200 chars
- Run consolidation more aggressively (every 5 ticks instead of 10)

### If councilor behavior becomes incoherent or loops:

The memory injection passively adds context — it does not force the LLM to use it. The LLM can ignore the `## Your Memories` section entirely (equivalent to the current stateless behavior). Rollback is only needed if the memory section actively degrades responses (e.g., confuses the model with contradictory "memories").

---

## 8. Safety Boundaries

### What the bridge must NOT do:

- **No self-modifying code.** The bridge writes memories, reads memories, consolidates memories. It does not modify `npc_agent.py` control flow, inject new LLM calls, or change the tick loop timing.
- **No prompt rewriting beyond adding a section.** The existing system prompt (`SELF_INTRO`), world context, and JSON instruction remain untouched. Only `## Your Memories` is appended.
- **No cross-councilor memory sharing.** `char_001` cannot read `char_306` memories. Each councilor has its own namespace.
- **No backend NPC-managed key collisions.** All keys use `councilor_memory:` prefix, which does not overlap with existing `npc_memory:`, `npc_thoughts:`, or other Federation Redis key patterns.
- **No Redis pipeline or transaction for memory writes.** Memory recording happens after the LLM call and artifact write. If it fails, the tick still completes. Best-effort only.
- **No memory mutations.** Memories are append-only via ZSET. Consolidation removes low-value entries but does not edit existing entries. No update-in-place.
- **No blocking operations during critical path.** `zadd` and `zrevrangebyscore` are O(log N) — negligible for N < 1000 memories.

### Guard against memory explosion:

- `MAX_MEMORIES = 200` per councilor (hard ceiling in consolidation)
- `CONSOLIDATION_INTERVAL = 10` ticks (prevent unbounded growth between consolidations)
- Content truncation at 500 chars (prevent oversized members)
- If `zcard` exceeds 1000 in `get_context_for_prompt()`, trigger early consolidation

### Guard against prompt bloat:

- `get_context_for_prompt()` returns at most 8 memories regardless of how many exist
- Each memory renders as one line (`- [type] (tick N): content\n`) — ~100 chars average
- Worst-case memory section: 8 lines × ~100 chars = ~800 chars added to prompt
- Federation councilor context window: 128K tokens (NVIDIA Nemotron Super 49B) — 800 chars is ~200 tokens, ~0.15% of available context

### Guard against generic/empty memory:

- Thoughts shorter than 10 chars are not stored
- Thoughts meeting the generic-pattern heuristic (95%+ similarity to "I observe the Federation" or "I analyze reports") receive importance penalty reducing them to near-zero, making them likely to be pruned on consolidation

---

## 9. Explicit Non-Goals (Phase 1)

| Item | Status | Rationale |
|---|---|---|
| Append-only event ledger | Phase 2 | Requires validation schema, evidence_refs, before/after refs. Genesis world_event_ledger.py is the reference. |
| claim_scope taxonomy | Phase 2 | Requires schema changes to decision output, spectator display. Genesis claim_scope enum is the reference. |
| Spectator evidence view | Phase 2 | Requires frontend changes, new endpoint for ledger query. |
| Backend NPC memory upgrade | Phase 3 | The 37 backend-managed NPCs have a different memory system (npc_memory.py). This bridge is councilor-only. |
| Frontend changes | Phase 2 | No spectator.html, admin.html, or simulation.html changes in Phase 1. |
| Provider routing changes | Never | llm_router.py, nvidia_nim_client.py are not touched. |
| Dockerfile or compose changes | Phase 1.1 if needed | The bridge is pure Python + Redis. No new dependencies. |
| Container restart orchestration | Out of scope | Deploy scripts handle this. Plan does not include deploy instructions. |
| Cross-councilor memory sync | Phase 3 | No char_001 reading char_306 memories. Each is independent. |
| Memory search/indexing | Phase 2 | No full-text search. Only recency + importance queries. |

---

## 10. Phase 2: Append-Only Ledger / Claim Scope / Spectator View

Phase 2 builds on Phase 1's memory layer with an evidence and verification layer, directly inspired by Genesis's `world_event_ledger.py`, `world_event_candidate_mapper.py`, and `world_event_verifier.py`.

### 10a. Append-Only Councilor Event Ledger

A JSONL file recording every councilor decision as a structured event:

```
{
  "event_id": "councilor_001_0042",
  "schema_version": "1",
  "councilor_id": "char_001",
  "tick": 42,
  "thought": "...",
  "action": "...",
  "goal": "...",
  "claim_scope": "observed|memory|hypothesis|action",
  "evidence_refs": [
    {"category": "agent_memory", "ref": "councilor_memory:char_001:...", "summary": "Anomaly detected tick 38"}
  ],
  "before_ref": "hash of world state at tick start",
  "after_ref": "hash of world state after action",
  "affected_agents": ["char_002"],
  "artifacts_created": [],
  "relationship_delta": {},
  "consequence": "summary of what changed",
  "verification_status": "unverified|consistent|contradicted",
  "timestamp_utc": "2026-07-01T21:00:00Z"
}
```

### 10b. Claim Scope on Councilor Output

The LLM's decision JSON gains an optional `claim_scope` field. Post-processing in `execute_decision()` infers scope from content if the LLM does not supply it:

| Scope | Trigger |
|---|---|
| `observed` | "I see", "I notice", "the data shows", "reports indicate" |
| `memory` | "I remember", "earlier I", "previously I found" |
| `hypothesis` | "I suspect", "perhaps", "may be", "could indicate" |
| `action` | "I send", "I request", "I create", "I propose" |
| `speech` | "I told", "I asked", "I discussed" |

### 10c. Spectator Evidence View

A new endpoint `/councilor/{char_id}/ledger?limit=10` serves events from the append-only ledger. The spectator's "Councilor proposals" panel loads from the ledger instead of ephemeral Redis state.
