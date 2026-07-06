# Metrics-Only NPC Governor Snapshot

**Status:** Milestone complete — deployed and verified.
**Date:** 2026-07-06
**Branch:** `bridge/memory-phase-1`
**Source:** Memory diagnostics → governor baseline v4 → metrics-only snapshot endpoint

---

## 1. Memory Diagnostics (commit `60dab72`)

Added counter fields to `harvest_tick_memories()` return payload in `npc_memory.py`:

- `harvested_memory_count`, `real_decisions_count`, `fallback_decisions_count`
- `skipped_no_char_id`, `skipped_no_npc_match`, `skipped_no_description`, `skipped_below_threshold`, `skipped_fallback_rest`
- `harvested_by_category`, `skipped_by_category`

Deployed to VPS, backend + worker restarted.

---

## 2. Metrics-Only Governor Snapshot (commit `483851c`)

New helper `npc_governor_metrics.py` (591 lines, 15 functions):

- Reads: `llm_audit`, `visible_activity`, `memory_state`, `harvest_diagnostics`, `operator_history`
- Classifies: `high_tier`, `medium_tier`, `low_tier`, `active_deterministic`, `expensive_low_payoff`, `memory_rich`, `special_external`
- Guardrails: `diagnostic_valid=false` on payload/skip/error/tick mismatch; fallback/idle/runaway do NOT invalidate

New routes in `routes/simulation.py`:

- `POST /simulation/operator/governor/metrics/snapshot`
- `GET /simulation/operator/governor/metrics/latest`

All tier outputs observe-only (`observe_only: true`). `__blank__` excluded from NPC tiers. `char_001` / `char_306` classified as `special_external`.

---

## 3. Deploy + POST/GET Verification

| Check | Result |
|---|---|
| Deploy | yes |
| Backend health | `/healthz` 200 |
| POST snapshot | 200 |
| GET latest | 200 |
| Cross-tick stability | 200 on second POST after natural worker tick |
| diagnostic_valid | true |
| invalid_reasons | `[]` |

---

## 4. Diagnostics

| Metric | Value |
|---|---|
| Counter-bearing ticks | 10 |
| Real decisions total | 82 |
| Harvested total | 82 |
| Harvest yield | 1.0 |
| Real-decision skips | 0 |
| Fallback rest skipped | 308 |
| High tier | 25 |
| Medium tier | 7 |
| Low tier | 0 |
| Active deterministic | `[]` |
| Expensive low payoff | `[]` |

---

## 5. Redis Keys Written

| Key | Purpose | TTL |
|---|---|---|
| `npc_governor_metrics:latest` | Latest full snapshot | 7 days |
| `npc_governor_metrics:{tick_id}` | Per-tick snapshot | 7 days |

---

## 6. No Behavior Changes

- No sleep tier
- No worker hook
- No LLM throttling
- No NPC suppression
- No memory scoring changes
- No `fallback_rest` changes
- No `llm_router` modifications
- No `simulation_engine` edits
- Governor is observe-only — zero actuation

---

## 7. Known Unrelated Issue

- `nvidia/llama-3.3-nemotron-super-49b-v1.5` and `openai/gpt-oss-120b`: **403 Authorization failed** (NIM keys expired/missing)
- `fallback_nim` worker tier: transient **read timeout**
- These do not affect the governor endpoint or memory harvest

---

## 8. Recommendation

The metrics-only governor snapshot milestone is complete. Two safe next phases:

- **A. Provider route audit for NIM 403** — independent of governor work; resolves cascading fallback latency
- **C. Optional worker hook behind config flag (default-off)** — natural automation of the manual POST endpoint, zero behavior change until explicitly opted in

Docs-only milestone is closed.
