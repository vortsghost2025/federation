# FEDERATION × WE4FREE THEORY MAP

**Date:** 2026-07-18
**Author:** Copilot CLI (agent)
**Purpose:** Permanent trail connecting Sean's WE4FREE / Rosetta Stone framework to the
Federation backend, so any agent (Copilot, GPT, human) can pick up the 39-NPC universe
vision without re-deriving the theory.

---

## 0. What this is

Sean shared 7 documents:
- `01_The_Rosetta_Stone.pdf` (Paper A + Paper F appendix content: failure modes, self-correcting loop)
- `02_Constraint_Lattices_and_Stability.pdf` (Paper B)
- `03_Phenotype_Selection_in_Constraint_Governed_Systems.pdf` (Paper C)
- `04_Drift_Identity_and_Ensemble_Coherence.pdf` (Paper D)
- `05_The_WE4FREE_Framework.pdf` (Paper E — operationalization)
- `book-6-ensemble-intelligence-foundation.md` (Paper F — "Failure Modes, Formal Limits, and the Self-Correcting Loop")
- `CAISC_CONTRIBUTION_SELF_STATE_ALIASING.md` (NFM-002 case study, proposed paper contribution)

Source repo (OSF, public): `The WE4FREE Framework: Mathematical Foundations for
Constitutional AI Collaboration` — https://osf.io/n3tya/ (5 PDFs listed).
Author: Sean. Jan 30 – Feb 15, 2026. 16-day human-AI collaboration.

**Key realization:** Paper F §4.5 names Federation directly as the case study.
Federation = "the uncontrolled large-system attempt: 47+ NPCs, 9 API keys,
Redis/PostgreSQL/Docker stack, autonomous 60s tick loop. It exposed delegation
amplification under runtime complexity." Genesis = the constrained re-architecture
(4 agents, phase-gated deterministic modules). The **bridge back to Federation** is the
prescribed path: a simpler verified substrate refines the larger live system.

This means: **the 39-NPC universe-building vision is Federation's north star, and
WE4FREE is the theory that tells us how to make it stable instead of chaotic.**

---

## 1. The Four Invariants (Paper A) → Federation requirement

| Invariant | Definition | Federation backend must... |
|-----------|------------|----------------------------|
| Symmetry Preservation | structure unchanged under transformation | NPC identity/lore persists across restarts (checkpoint symmetry) |
| Selection Under Constraint | stable configs selected by constraint pressure | NPC behavior selected by constitutional constraints, not arbitrary LLM output |
| Propagation Through Layers | rules flow constitutional→behavioral | Council/Decree layer → NPC action layer |
| Stability Under Transformation | returns to attractor after perturbation | Drift recovery returns NPC to phenotype attractor |

## 2. WE4FREE architecture layers (Paper E) → proposed Federation layers

```
Paper A: Invariants        →  Constitutional Layer (Federation council/decree/faction rules)
Paper B: Constraint Lattice→  Constraint Lattice Layer (enforce invariants per-NPC, per-tick)
Paper C: Phenotype + CPS   →  Phenotype Layer (each NPC has a CPS attractor; selection operator)
Paper D: Drift & Identity  →  Drift Detection + Functorial Recovery (detect deviation, recover identity)
```

Federation's current backend has NONE of these as explicit layers. It is a single
`game_state` singleton (see ARCHITECTURE_STATE.md constraint #1: NO --workers) with
event/choice routes. To reach 39 universe-building NPCs, the backend needs the 4-layer
stack above.

## 3. Failure modes that WILL bite at 39-NPC scale (from Paper F NFM taxonomy)

These are ordered by how soon they appear as NPC count grows from ~47 to 39 autonomous:

| NFM | Name | Federation impact at scale |
|-----|------|----------------------------|
| NFM-002 | Self-state aliasing | NPC concludes it is "dead"/reset while actively running (stale session artifact > live runtime) |
| NFM-020 | Cross-lane observability | NPC B cannot verify NPC A's world-state if outside B's scope ("not visible ≠ not real") |
| NFM-018 | Temporal constraint violation | Constraint evaluated before satisfaction reachable (tick checks artifact before task runs) |
| NFM-019 | Schema-behavior mismatch | Schema covers governance values; NPCs produce universe-lifecycle values not in schema |
| NFM-009 | Freshness ≠ liveness | Heartbeat fresh ≠ NPC process alive |
| NFM-032/AL-4 | Delegation projection | Each NPC's autonomy boundary leaks into others at the delegation surface |
| NFM-014 | Windows atomic write not atomic | State writes appear success but don't persist (VPS is Ubuntu, but dev is Windows) |
| NFM-026 | Trust store divergence | No runtime cross-lane consistency check |

**Source-of-truth precedence (hard rule from Paper F §2.3, apply to NPCs):**
1. Live runtime/process state (authoritative)
2. Fresh local lock (timestamp valid)
3. Shared registry (advisory only)
4. Terminated history (never authoritative)

**Self-verification sequence (NFM-002 fix):**
1. "Am I alive?" (self-state)
2. "Is my authority valid?" (self-authority)
3. "Are others alive?" (cross-lane)
Skipping step 1 invalidates 2 and 3.

## 4. The Self-Correcting Loop (Paper F §4.2) — our operating procedure

```
Failure → Detection → Correction → Constraint Refinement → (New Stable State)
   ↑                                                              │
   └──────────────────────────────────────────────────────────────┘
```

4th Invariant (Paper F): **Persistent failure reveals missing/mis-specified constraints.**
Transient errors = noise; persistent failures = signal/diagnosis.

We already run this loop via the 6 Copilot workflows (see WORKING_AGREEMENT.md +
FEDERATION_CHANGE_JOURNAL.md): ci-watchdog = Detection, dirty-tree-guardian =
Constraint Refinement signal, self-test-keeper = Verification.

## 5. Prescribed path to 39-NPC universes (Paper F §4.5 Genesis bridge)

1. **Constrained re-architecture (Genesis pattern):** build a small verified substrate
   (few agents, phase-gated deterministic modules, append-only ledger, active CI) that
   implements the 4-layer WE4FREE stack for NPC autonomy.
2. **Bridge back to Federation:** transfer constraints from the verified substrate into
   the live Federation `simulation_engine.py` / `npc_autonomy.py` as governance scaffolding.
3. **Scale by clonal expansion (Paper A):** add NPCs without losing phenotype coherence
   (CPS attractor preserved). Each NPC builds its universe within its constraint lattice.

This is NOT a rewrite of Federation. It is: add the 4 layers as a governance scaffold
around the existing `game_state` singleton, then scale NPC autonomy under those
constraints.

## 6. What I will NOT do without explicit go (per WORKING_AGREEMENT 0.0001% rule)

- No code changes to `simulation_engine.py` / `npc_autonomy.py` production paths yet.
- No deploy, no VPS/Redis/.env changes.
- The Genesis re-architecture is a separate substrate (new modules), not a live edit.

## 7. Next concrete steps (pending Sean's go)

A. Audit `npc_autonomy.py` against the 4 invariants (read-only report).
B. Sketch the 4-layer scaffold as new modules (no live wiring).
C. Define one NPC's CPS/phenotype attractor as a concrete schema.
D. Tier-3 Federation runtime crons (sim tick, decay sweep, log digest) — held pending.

---
*This file is the trail. Any agent reading it can continue the 39-NPC work by following
sections 1–5 and respecting section 6.*
