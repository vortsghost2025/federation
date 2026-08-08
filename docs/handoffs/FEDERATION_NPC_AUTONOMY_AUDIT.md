# AUDIT: npc_autonomy.py vs WE4FREE 4 Invariants

**Date:** 2026-07-18
**Scope:** Read-only audit of `S:\federation\federation-game\backend\npc_autonomy.py` (863 lines)
**Framework ref:** WE4FREE Papers A–E + Paper F (Rosetta Stone book). See
`FEDERATION_WE4FREE_THEORY_MAP.md`.
**Result:** NO code changed. Report only.

---

## How the engine works (observed)

- `simulation_tick(npc_list)` — the autonomous loop (Phase 3). Runs every 60s in
  production (per Paper F §4.5). Uses `ThreadPoolExecutor(max_workers=_NPC_PARALLEL_WORKERS)`
  to process all NPCs **concurrently**. Each NPC → `_process_single_npc` → `make_decision`.
- `make_decision(char_id, ...)` — scores decision options via
  `evaluate_decision_options`, then `random.choices(top_options, weights=scores, k=1)`
  picks ONE. Category branches (advance_goal, socialize, investigate, rest,
  react_to_events, seek_resources, self_improve, confront_rival, help_ally, explore,
  request_capability) call LLM generators (`generate_action`, `generate_goal_driven_action`,
  `generate_npc_interaction`).
- State stored in per-NPC Redis keys: `npc_thoughts:{id}`, `npc_actions:{id}`,
  `npc_relationships:{id}`, `npc_mood:{id}`, `npc_last_active:{id}`, `npc_decisions:{id}`.
- Decree/broadcast layer (`npc_decree`) provides SOME constitutional propagation
  (DECREE_THRESHOLDS, DECREE_MAX_DELTA, cooldowns, councilor affiliations).
- **Notable comment in code:** `simulation_tick` stopped writing world_state because
  it was "overwriting simulation_engine's nuanced values with destructive aggregate
  calculations every tick (double-write conflict)." World-state writes now owned
  exclusively by `simulation_engine.py`.

---

## Invariant-by-invariant assessment

### 1. Symmetry Preservation (identity persists across discontinuity) — PARTIAL / GAP
- NPC identity = Redis keys + `game_state` singleton. No checkpoint/snapshot protocol.
- WE4FREE SNAPSHOT_PROTOCOL.md defines explicit freeze+version+changelog for
  architecture evolution; **Federation has no equivalent for runtime NPC state**.
- **Risk: NFM-002 (self-state aliasing).** On restart, an NPC's Redis keys may be
  stale while the process is live → NPC (or the orchestrator) concludes wrong own-state.
- **Verdict:** Identity is stored but NOT checkpoint-symmetric. Restart can lose
  in-flight decisions; no functorial recovery.

### 2. Selection Under Constraint (stable configs selected by constraint, not chance) — GAP
- `make_decision` uses `random.choices(weights=scores)`. Selection is **probabilistic**,
  not constraint-governed. Scores come from archetype/mood bias + reflection heuristics,
  not a constraint lattice.
- No phenotype attractor, no CPS (Phenotype Selection operator, Paper C). An NPC can
  random-walk its entire behavioral space each tick.
- **Risk: NFM-019 (schema-behavior mismatch).** The system has no formal "behavioral
  vocabulary" constraint — anything the LLM emits is accepted. At 39-NPC scale this
  diverges per NPC with no coherence pressure.
- **Verdict:** Selection is stochastic, not constraint-selected. This is the single
  biggest gap vs WE4FREE.

### 3. Propagation Through Layers (constitutional → behavioral) — PARTIAL / CONFLICTED
- Decree layer EXISTS (constitutional → some NPC behavior via broadcast events).
- BUT `simulation_tick` **deliberately abandoned** world_state propagation to avoid a
  double-write conflict with `simulation_engine.py`. So propagation is split across two
  owners with a known conflict.
- **Risk: NFM-018 (temporal constraint violation) / ordering.** Two writers to related
  state with no defined precedence = the same class of bug Paper F documents (artifact
  written before task ran).
- **Verdict:** Propagation present but fractured. Needs a single source-of-truth
  precedence (Paper F §2.3: runtime > lock > registry > history) applied to world_state.

### 4. Stability Under Transformation (returns to attractor after perturbation) — GAP
- No drift detection. No CPS attractor. No functorial recovery protocol.
- An NPC's mood/opinion/relationship can drift unbounded; nothing pulls it back to a
  stable phenotype.
- **Risk: NFM-009 (freshness ≠ liveness)** — `npc_last_active` timestamp measures
  artifact freshness, not process liveness. A "stale but alive" NPC looks dead.
- **Verdict:** No stability mechanism. Exactly the "uncontrolled large-system" failure
  Paper F §4.5 attributes to Federation.

---

## Failure modes confirmed applicable at 39-NPC scale

| NFM | Applies? | Where in npc_autonomy.py |
|-----|----------|--------------------------|
| NFM-002 Self-state aliasing | YES | No checkpoint; restart resets/aliases state |
| NFM-009 Freshness ≠ liveness | YES | `npc_last_active` timestamp only |
| NFM-014 Atomic write not atomic | YES (dev=Windows) | Redis multi-key writes not transactional per NPC |
| NFM-018 Temporal/ordering | YES | Double-write conflict with simulation_engine |
| NFM-019 Schema-behavior mismatch | YES | `random.choices` + unbounded LLM output |
| NFM-020 Cross-lane observability | YES | Each NPC reads its own Redis keys; no cross-NPC verification |
| NFM-026 Trust store divergence | N/A (no crypto) | — |
| NFM-032 Delegation projection | YES | ThreadPoolExecutor = delegation surface; failures project (errors list swallowed) |

---

## What this means for the 39-NPC vision

The current engine can run 47 NPCs, but it is **selection-stochastic and
stability-less** — exactly why Paper F calls Federation "uncontrolled." To get 39 NPCs
each building a *coherent* universe in their own image, the engine needs:

1. **A constraint lattice per NPC** (Paper B) that bounds decision options — replaces
   raw `random.choices` with constraint-filtered selection.
2. **A CPS phenotype attractor per NPC** (Paper C) defining its "universe-building"
   stable config; selection pulls toward it.
3. **A snapshot/checkpoint protocol** (Paper A Symmetry + WE4FREE SNAPSHOT_PROTOCOL)
   so identity persists across the 60s-tick restarts and the orchestrator can't
   self-state-alias.
4. **A drift detector + functorial recovery** (Paper D) that detects deviation from the
   attractor and recovers identity without central control.
5. **Single source-of-truth precedence** for world_state (fix the double-write conflict).

These map to the 4-layer Genesis scaffold (next step B). No live changes recommended
until the scaffold exists and is verified in isolation.

---
*Audit complete. No files modified. Next: sketch 4-layer scaffold as new modules
(see FEDERATION_WE4FREE_THEORY_MAP.md §5 / step B).*
