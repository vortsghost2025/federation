# NPC Usefulness Governor + LLM Attribution

**Status:** Design doc only — no implementation.
**Date:** 2026-07-05
**Source:** NPC cognition code-path audit (`audit-reports/2026-07-05-npc-usefulness-governor-notes.txt`)

---

## 1. Problem

The simulation runs 39 NPCs through autonomous ticks. Every tick, each NPC produces:
- a thought (`npc_thoughts:*`, cache-first → conditional LLM → template fallback)
- an action (`npc_actions:*`, pure template)
- a decision (`npc_decisions:*`, template-based scoring)

86,561 `npc_turns` accumulated in 7 days. The background NPCs (37 of 39) produce deterministic or worker-tier LLM content with **no downstream consumer**. Redis keys grow unboundedly while the councilor pair (char_001, char_306) drives all visible narrative.

---

## 2. Audit Findings

### LLM call volume (`llm_audit`, 1-hour window)

| Metric | Value |
|---|---|
| Total entries | 501 |
| Actual route_call attempts | ~179 |
| task_class=worker | 179 |
| task_class=leader | 0 |
| task_class=specialist | 0 |
| Success rate | 72.7% |
| Avg latency | 1757ms |

### Models used (all small/free)
- `meta/llama-3.1-8b-instruct` — 245 calls, mostly 403 Forbidden (NIM keys dead)
- `qwen2.5-coder:3b-instruct-q4_K_M` (Ollama local) — 118 calls, mostly successful
- `nvidia/llama-3.1-nemotron-nano-8b-v1` (NIM) — 78 calls
- Various OpenRouter free models — ~60 calls, some 429 rate limited

Expensive NIM 70B models never fired (dead keys). All successful calls through local Ollama or free-tier OpenRouter. **API cost is near zero.**

### Redis waste
- 86,561 `npc_turns` in 7 days
- 37 `npc_thoughts:*` keys, 37 `npc_actions:*` keys, 39 `npc_decisions:*` keys
- Template filler with no consumer

---

## 3. Logging Gap

`llm_audit` entries have: `ts`, `provider`, `model`, `task_class`, `success`, `latency_ms`.

They lack:
- **char_id** — which NPC triggered the call
- **source** — `cognition` vs `thought` vs `narrator` vs `assistant`
- **is_final** — final route_call result or provider sub-call

`npc_llm_logs:*` covers only agent-side (char_001, char_306).

**Result:** Cannot tell which NPCs drive LLM spend or whether background ticks produce useful output.

---

## 4. Proposed Governor Cadence

```
persistent councilors (char_001, char_306) → high cadence (current)
event-relevant NPCs                        → medium cadence
background NPCs                            → low cadence
stale NPCs (>N hours inactive)             → sleep until triggered
```

- **High:** every tick (no change)
- **Medium:** every 2nd-3rd tick (skip 50-67%)
- **Low:** every 5th-10th tick (skip 80-90%)
- **Sleep:** no processing until event or interaction wakes NPC

Implementation: read-only check at top of `_process_single_npc()` in `npc_autonomy.py`. Check `npc_state:{char_id}` for `governor_tier`. Staleness: skip if `last_active > N hours`. Add TTL on `npc_thoughts:*` and `npc_actions:*`.

---

## 5. Proposed LLM Attribution Fix

In `llm_router.py:_record_call()` and `route_call()` success paths, extend audit_entry:

```python
audit_entry = {
    "ts": now,
    "char_id": char_id,        # who triggered it
    "source": source,          # "cognition" | "thought" | "narrator" | "assistant"
    "is_final": is_final,      # True = final route_call result, False = provider sub-call
    "provider": provider,
    "model": model,
    "task_class": task_class,
    "success": success,
    "latency_ms": round(latency_ms, 1),
}
```

Requires plumbing `char_id` and `source` through `_call_provider()` and `_call_ollama()` — they currently lack these params.

---

## 6. What This Changes

- Stage 5A (pair dialogue relay): **do not build yet** — audit does not warrant it
- Artifact retention policy: **do not implement yet** — char_001/306 already manage their logs
- Blind NPC pause: **do not do** — worker-tier calls are small/free, not the problem
- NIM key rotation: **should fix** — 403 errors cause cascading fallbacks to slower providers
- Governor + attribution fix: **design only** — no code changes

---

## 7. Files Referenced

- `backend/npc_autonomy.py:856` — autonomous_tick, _process_single_npc
- `backend/npc_thoughts.py:400` — generate_thought, _call_llm
- `backend/npc_actions.py:202` — deterministic action templates
- `backend/npc_cognition.py:1414` — tiered cognition engine
- `backend/llm_router.py:1907` — route_call, _record_call, _call_provider, _call_ollama
- `backend/simulation_operator.py` — wraps autonomous_tick, caps cognition LLM to 1/tick
- `npc-agent/npc_redis_helpers.py:818` — writes npc_llm_logs (agent-side only)
- `npc-agent/npc_agent.orig.py` — councilor-side LLM client

## 8. Open Questions

- What is the downstream consumer of background NPC thoughts/actions? None found.
- Should event-relevant NPC tick affinity be set by `/event` endpoint or computed from `npc_state`?
- Should stale NPC ticks be fully skipped or just LLM calls? Likely skip both — no one reads the templated output.
- TTL value for thought/action keys? 24h for background, 72h for event-relevant, no TTL for councilors.
- Should `npc_llm_logs` be merged into `llm_audit` or stay separate? Separate is fine — one is agent-side, one is backend. Fix is adding char_id to llm_audit.