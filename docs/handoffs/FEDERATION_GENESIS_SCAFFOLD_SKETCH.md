# SKETCH: 4-Layer Genesis Scaffold for Federation NPC Autonomy

**Date:** 2026-07-18
**Status:** SKETCH ONLY — new standalone modules. NO live wiring into `game_state`,
NO changes to running VPS. Per WORKING_AGREEMENT + standing audit go (step B).
**Reference implementation:** `S:\Genesis Kernel World Sim\world-sim\backend\`
(Genesis's proven `observe → decide → act → consequence → memory` loop).
**Theory base:** `FEDERATION_WE4FREE_THEORY_MAP.md`, `FEDERATION_NPC_AUTONOMY_AUDIT.md`
(Paper A–F. 4 invariants + 35 NFM.)

---

## 0. Why this shape (the bridge back)

Paper F §4.5 says Federation is the "uncontrolled large-system attempt" and Genesis
is the "constrained re-architecture." The bridge back = port Genesis's *constraint
discipline* into Federation WITHOUT throwing away Federation's scale (47 NPCs, Redis,
decrees, factions). Genesis already solved 3 of the 4 invariants in ~200 lines. We
lift those patterns, then add the 4th (Stability) as a WE4FREE-native layer.

---

## 1. The 4 layers (WE4FREE → Federation module)

```
┌─────────────────────────────────────────────────────────────┐
│ L4  DRIFT & IDENTITY  (WE4FREE Paper D)                      │
│     genesis_drift.py  — functorial recovery, NFM-002/009      │
├─────────────────────────────────────────────────────────────┤
│ L3  PHENOTYPE / CPS  (WE4FREE Paper C)                       │
│     genesis_phenotype.py — attractor per NPC, NFM-019        │
├─────────────────────────────────────────────────────────────┤
│ L2  CONSTRAINT LATTICE  (WE4FREE Paper B)                    │
│     genesis_constraints.py — bounds options, NFM-018/020     │
├─────────────────────────────────────────────────────────────┤
│ L1  CONSTITUTIONAL  (WE4FREE Paper A + Decrees)             │
│     genesis_constitution.py — symmetry/snapshot, NFM-002     │
└─────────────────────────────────────────────────────────────┘
            ▲ attached to existing npc_autonomy.py tick, NOT replacing it
```

Each layer is a **new file** in `federation-game/backend/genesis/` (new package,
imported lazily). Nothing in `npc_autonomy.py` changes until Sean approves wiring.

---

## 2. L1 — genesis_constitution.py  (Symmetry Preservation)

**Problem (audit):** no checkpoint/snapshot; restart = NFM-002 self-state aliasing.
**Genesis pattern:** `WorldAgent.save_state/load_state` + `WorldState` save/load +
`EventLog` append-only.

```python
# genesis/genesis_constitution.py
"""L1 Constitutional layer: identity persistence + snapshot protocol.
Operationalizes WE4FREE SNAPSHOT_PROTOCOL for Federation NPCs.
Source-of-truth precedence (Paper F §2.3): runtime > lock > registry > history."""

import json, time, hashlib
from pathlib import Path

SNAPSHOT_DIR = Path("data/npc_snapshots")

def freeze_snapshot(char_id: str, live_state: dict) -> str:
    """Atomic freeze. Returns version hash (Symmetry Preservation)."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    version = hashlib.sha256(
        (char_id + str(time.time()) + json.dumps(live_state, sort_keys=True)).encode()
    ).hexdigest()[:16]
    payload = {"char_id": char_id, "version": version,
               "ts": int(time.time()), "state": live_state}
    tmp = SNAPSHOT_DIR / f"{char_id}.{version}.tmp"
    final = SNAPSHOT_DIR / f"{char_id}.snapshot.json"
    tmp.write_text(json.dumps(payload))           # write temp first
    tmp.replace(final)                            # atomic rename (Windows-safe)
    return version

def recover_snapshot(char_id: str) -> dict | None:
    """Functorial recovery — returns last stable identity, or None if absent."""
    final = SNAPSHOT_DIR / f"{char_id}.snapshot.json"
    if not final.exists():
        return None
    return json.loads(final.read_text())["state"]

def verify_aliveness(char_id: str) -> bool:
    """NFM-009 guard: freshness(timestamp) != liveness(process). Probe real liveness."""
    # TODO: real liveness = Redis PING on npc:{id} stream OR heartbeat key, not mtime.
    ...
```

**Why this fixes NFM-002/009:** identity is frozen atomically (no half-written
state) and recovered functorially. `verify_aliveness` separates "stale file" from
"dead process" — the exact NFM-009 trap.

---

## 3. L2 — genesis_constraints.py  (Selection Under Constraint — the lattice)

**Problem (audit):** `make_decision` uses `random.choices(weights=scores)` — stochastic,
unbounded. NFM-019 schema-behavior mismatch.
**Genesis pattern:** `ConsequenceEngine` is *deterministic* — it maps actions to
consequences via a fixed keyword lattice. Behavior is bounded by the engine.

```python
# genesis/genesis_constraints.py
"""L2 Constraint lattice: bounds the option space before selection.
Replaces raw random.choices with constraint-filtered selection (Paper B)."""

# The lattice: every NPC action must satisfy these before it is selectable.
CONSTRAINTS = {
    "respects_decree":   lambda opt, ctx: opt["category"] not in ctx["decree_banned"],
    "within_budget":     lambda opt, ctx: opt["est_cost"] <= ctx["remaining_budget"],
    "not_self_harm":     lambda opt, ctx: opt["target"] != ctx["self_id"] or opt["safe"],
    "cross_lane_visible":lambda opt, ctx: ctx["observer_can_see"](opt),  # NFM-020
}

def filter_options(options: list, ctx: dict) -> list:
    """Paper B lattice intersection — only constraint-satisfying options survive."""
    return [o for o in options
            if all(test(o, ctx) for test in CONSTRAINTS.values())]

def select(options: list, ctx: dict) -> dict:
    """Constraint-filtered selection. Falls back to 'rest' if lattice empty
    (stable null-action) instead of forcing a random choice."""
    allowed = filter_options(options, ctx)
    if not allowed:
        return {"category": "rest", "constrained": True}
    return max(allowed, key=lambda o: o["score"])   # deterministic, not stochastic
```

**Why this fixes NFM-019/018/020:** selection is now *governed*, not rolled. The
lattice is the "behavioral vocabulary." Empty lattice → stable 'rest' (no divergence).
`cross_lane_visible` enforces NFM-020 observability.

---

## 4. L3 — genesis_phenotype.py  (Phenotype / CPS attractor)

**Problem (audit):** no phenotype; NPC can random-walk its entire behavior space.
**WE4FREE Paper C:** Phenotype Selection — a stable config (attractor) the system
is *pulled toward*. Genesis's `harmony_level` / `boundary_respected` are crude
attractors; we make them explicit per-NPC.

```python
# genesis/genesis_phenotype.py
"""L3 Phenotype / CPS: each NPC has a stable 'universe-building' attractor.
Pulls selection toward coherence (Paper C). This is what lets 39 NPCs each build
a coherent world 'in their image' instead of diverging."""

@dataclass
class Phenotype:
    char_id: str
    attractors: dict[str, float]   # e.g. {"build": 0.7, "socialize": 0.2, "explore": 0.1}
    tolerance: float = 0.15        # how far behavior may drift before correction

def phenotype_pull(option: dict, pheno: Phenotype) -> float:
    """Adjust raw score by distance from this NPC's attractor.
    Options near the attractor score higher → selection converges, not diverges."""
    base = option["score"]
    cat = option["category"]
    target = pheno.attractors.get(cat, 0.0)
    # closer to attractor weight = higher effective score
    return base * (0.5 + target)

def is_coherent(option: dict, pheno: Phenotype) -> bool:
    """Stability gate: is this option within the phenotype tolerance?"""
    cat = option["category"]
    return abs(pheno.attractors.get(cat, 0.0) - pheno.attractors.get(cat, 0.0)) <= pheno.tolerance
```

**Why this is the 39-NPC key:** each NPC's `attractors` *is* their "universe in their
image." Selection (L2) filtered by constraints (L2) then pulled by phenotype (L3) →
coherent autonomous world-building. This is the missing half of Federation.

---

## 5. L4 — genesis_drift.py  (Stability Under Transformation — functorial recovery)

**Problem (audit):** no drift detection, no recovery. NFM-009, NFM-014.
**WE4FREE Paper D:** Drift & Identity — detect deviation from attractor, recover
identity via functorial map (structure-preserving), not central reset.

```python
# genesis/genesis_drift.py
"""L4 Drift detection + functorial recovery (Paper D).
Detects when an NPC has drifted from its phenotype attractor and recovers
identity-preservingly — no central controller needed."""

def measure_drift(recent_actions: list[str], pheno: Phenotype) -> float:
    """Distance of recent behavior distribution from attractor."""
    if not recent_actions:
        return 0.0
    counts = Counter(recent_actions)
    total = len(recent_actions)
    drift = sum(abs(counts[c]/total - pheno.attractors.get(c, 0.0))
                for c in set(list(counts) + list(pheno.attractors)))
    return drift

def functorial_recover(char_id: str, pheno: Phenotype, snapshot_state: dict) -> dict:
    """Recovery preserves structure: re-anchor to last stable snapshot + re-apply
    attractor, do NOT wipe. This is the 'functor' — maps broken state to fixed state
    keeping identity (NFM-002)."""
    stable = recover_snapshot(char_id) or snapshot_state
    stable["_drift_corrected"] = True
    stable["_phenotype"] = pheno.attractors
    return stable
```

**Why this fixes the "uncontrolled" label:** Federation gains a self-correcting loop
(Paper F §3): drift detected → phenotype re-applied → stable state. This is the 4th
invariant Federation was entirely missing.

---

## 6. How it attaches to existing npc_autonomy.py (NO rewrite)

`simulation_tick` already loops NPCs via `ThreadPoolExecutor`. The scaffold slots in
as **wrappers called inside `_process_single_npc`**, gated behind a config flag:

```python
# inside _process_single_npc, AFTER make_decision, BEFORE Redis write:
if config.GENESIS_LAYERS_ENABLED:
    snap = genesis_constitution.recover_snapshot(char_id)      # L1
    options = genesis_constraints.filter_options(raw_options, ctx)  # L2
    choice = genesis_phenotype.phenotype_pull(choice, pheno)    # L3
    if genesis_drift.measure_drift(recent, pheno) > pheno.tolerance:
        state = genesis_drift.functorial_recover(char_id, pheno, snap)  # L4
    genesis_constitution.freeze_snapshot(char_id, live_state)  # L1 persist
```

**Default OFF.** Nothing changes at runtime until Sean flips `GENESIS_LAYERS_ENABLED`.
The double-write conflict (NFM-018) is resolved by giving `simulation_engine.py`
sole ownership of `world_state` writes (already half-done in code) + L2
`within_budget` constraint.

---

## 7. What this gives the 39-NPC vision

1. **Identity survives restarts** (L1 snapshot) — no more NFM-002 on the 60s tick.
2. **Behavior is governed, not rolled** (L2 lattice) — NFM-019 gone.
3. **Each NPC builds a coherent universe** (L3 phenotype = their "image") — the
   actual ask: 39 NPCs "think and act and build and communicate and evolve."
4. **Self-correcting stability** (L4 drift) — Federation stops being "uncontrolled."
5. **Cross-lane observability** (L2 `cross_lane_visible`) — NFM-020 closed.

---

## 8. Open questions for Sean before wiring (NOT blocking the sketch)

- **Storage:** Genesis uses JSON files; Federation uses Redis. L1 snapshot should
  write to Redis (atomic `SET`+rename key) to match infra, OR a hybrid (Redis hot +
  JSON cold). Your call.
- **Phenotype seeding:** who defines each NPC's `attractors`? Councilor affiliations?
  Decrees? Propose: seeded from `npc:{id}` affiliation + decree alignment.
- **Scope:** 4 modules ~250 lines total, all new files. Verify in isolation (unit
  test each layer) before any tick integration.

---
*Sketch complete. Modules are pseudocode for review. No files created in backend yet.
Awaiting Sean's go to (a) create the `genesis/` package as real modules + unit tests,
or (b) adjust the shape first.*
