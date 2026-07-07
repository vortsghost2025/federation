# Federation-Specific Failure Modes

**Date:** 2026-07-07
**Context:** Identified during ecosystem architecture alignment. These NFMs are unique to Federation's runtime — not captured in the 36 NFMs of Book-6.

---

## NFM-001: Parallel Monologist Gap

- **Definition:** NPCs produce responses independently within the same tick without awareness of each other's in-progress output. Both councilors generate decisions, messages, and artifacts based on stale pair state from the previous tick, not the current tick's concurrent generation.
- **Evidence:** Pair convergence_state is updated per-tick but each NPC reads the state written by the *previous* tick of the *other* NPC. A char_001 decision at T+0s and char_306 decision at T+15s both see T-60s state from each other.
- **Root cause:** The tick loop processes NPCs sequentially but each NPC's `think_about_world` / `decide_action` reads shared pair state from Redis. There is no write barrier or generation fence between concurrent NPC ticks.
- **Current mitigation:** Convergence_state reducer (`_compute_convergence_state`) provides a shared reference frame. The Stage 4D post-resolution guard prevents re-anchoring to resolved topics. Neither removes the inherent 1-tick latency gap.
- **Detection pattern:** NPC dialogue where one NPC asks a question the other already answered 2 ticks ago, or where both NPCs independently propose the same action in adjacent ticks.

---

## NFM-002: Tick-Loop Causality Inversion

- **Definition:** Effects in the simulation appear before their causes because multiple independent agents modify shared Redis state in overlapping time windows. NPC A's decision processor reads NPC B's state before B has written the state that supposedly caused A's decision.
- **Evidence:** The tick loop runs `process_cognition` for each NPC, which reads `npc_state:*`, `npc_mood:*`, `npc_pair:*` and makes decisions. If NPC A's tick reads NPC B's pair state while B's tick processor is mid-write, A sees an incomplete or stale version of the causal input.
- **Root cause:** Redis lacks transactional read-your-writes guarantees across keys. Each NPC container runs independently with no distributed lock or phase barrier between read and write cycles.
- **Current mitigation:** No mitigation. Redis is eventually consistent within the tick window. The `_compute_convergence_state` timestamp gate (`last_convergence_ts`) provides a coarse ordering hint.
- **Detection pattern:** NPC decisions that reference events that haven't happened yet in the simulation, or pair journal entries with timestamps out of causal order.

---

## NFM-003: NIM Shared Pool Trust Gap

- **Description:** The NVIDIA NIM API key pool is shared across all persona containers. A compromised, misconfigured, or anomalously-behaving persona consumes from the same rate-limited pool. If one NPC enters a degenerate generation loop, it can exhaust the shared NIM quota, starving all other NPCs.
- **Evidence:** 3 NIM keys in the pool (`NVIDIA_API_KEY_1`/`_2`/`_3`). All containers - backend, npc-agent-001, npc-agent-306, worker - share the pool. NIM rate limits are per-key, not per-persona.
- **Root cause:** API key management is pooled by design (cost efficiency). No per-persona isolation, no per-persona rate tracking, no degenerate-output circuit breaker at the persona level.
- **Current mitigation:** The `_trip_circuit` function in `llm_router.py` provides provider-level circuit breaking (3 consecutive failures → 300s pause). This is per-provider, not per-persona. No per-persona quota tracking exists.
- **Detection pattern:** All NPCs simultaneously fall back to Ollama/OR/Gemini, or all NPCs simultaneously show elevated timeout rates, without any single NPC showing disproportionate error counts.

---

## NFM-004: Extraction Wave Deploy Drift

- **Definition:** The 06-30 extraction wave (11 commits splitting `npc_autonomy.py` into sibling modules) cannot be atomically deployed. Mid-wave deploys leave the VPS in a mixed state where some files are post-extraction and others pre-extraction, causing import resolution failures.
- **Evidence:** Home hash `d1c2f7d6` (29KB, post-extraction shim importing from `npc_reflection`, `npc_decree` etc.) vs VPS hash `274420c1` (7KB, pre-extraction monolith with inline definitions). The VPS *does* have extracted modules in `npc-agent/` — the drift is that `backend/npc_autonomy.py` is still the monolith, referencing functions that were extracted.
- **Root cause:** 11 separate commits deployed across 3 paths (backend, npc-agent-001, npc-agent-306) with no atomicity. Each `scp` + `docker restart` sequence deploys one file at a time, creating windows where imports resolve on one container but not the other.
- **Current mitigation:** Both VPS paths (backend, npc-agent) are independently functional. The backend container uses the monolith. The npc-agent containers use the extracted sibling modules. They don't cross-reference.
- **Detection pattern:** `ImportError` or `AttributeError` in container logs immediately after a deploy. Container restarts that succeed on one NPC but fail on another.

---

## NFM-005: Memory Provenance Absence

- **Definition:** Redis memories have no lineage tracking — no source_tick, origin_char_id, or chain-of-thought on how a memory was produced. A memory can be overwritten with no audit trail of who changed it, when, or why.
- **Evidence:** Memory keys in Redis (`npc_memory:{char_id}:*`, `npc_focus:*`, `npc:*:memories`) contain text content but no provenance metadata. The memory bridge writes memories but doesn't tag them with the source decision or tick ID.
- **Root cause:** The original memory system was designed for a single-process simulation where all writes originate from one codepath. The introduction of multi-container NPC agents (char_001 + char_306 as separate containers) removed the implicit single-writer assumption.
- **Current mitigation:** `npc_redis_helpers.py:_compute_convergence_state` writes a convergence_state hash with timestamps. This provides tick-ordered state but no per-memory lineage. The decision log (`cognition_log`) provides an independent trace but isn't linked to specific memory entries.
- **Detection pattern:** Unexplained NPC behavior changes that can't be traced to a specific input. Debugging sessions that require correlating Redis `keys *` output with container logs manually. Memory that changes value between reads without a corresponding decision log entry.

---

## Relationship to Book-6 NFMs

These 5 NFMs are Federation-specific because they emerge from Federation's architectural choices:

- **Parallel Monologist Gap** — unique to the multi-container, shared-Redis tick loop design
- **Tick-Loop Causality Inversion** — unique to the lack of distributed synchronization primitives
- **NIM Shared Pool Trust Gap** — unique to the persona-container architecture with pooled API keys
- **Extraction Wave Deploy Drift** — unique to the scp-based deploy workflow (no CI/CD pipeline)
- **Memory Provenance Absence** — unique to the evolution from single-process to multi-container

The 36 NFMs in Book-6 describe general multi-agent system failure modes (stuck-in-loops, echo chambers, sovereignty collapse, etc.). These 5 are specifically the consequence of Federation's runtime topology — they exist because of how Federation *is built*, not because of how multi-agent systems *behave*.
