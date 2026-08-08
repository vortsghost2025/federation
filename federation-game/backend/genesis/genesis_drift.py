"""
genesis_drift — L4 Drift & Identity: Stability Under Transformation.

Detects when an NPC has drifted from its phenotype attractor and recovers identity
PRESERVINGLY (functorial map), with no central controller. This is the 4th WE4FREE
invariant Federation was entirely missing — the self-correcting loop (Paper F 3):
Failure -> Detection -> Correction -> Constraint Refinement -> New Stable State.

Closes:
  NFM-002 (self-state aliasing) — functorial_recover re-anchors to last stable
            snapshot, preserving structure rather than wiping.
  NFM-009 (freshness != liveness) — drift is measured on BEHAVIOR, independent of
            any timestamp freshness.
  (the "uncontrolled large-system" label from Paper F 4.5 — now self-correcting)
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List, Tuple

from . import genesis_constitution as constitution
from .genesis_phenotype import Phenotype

logger = logging.getLogger("genesis.drift")


def measure_drift(recent_actions: List[str], pheno: Phenotype, salience_eps: float = 0.1) -> float:
    """Distance of recent behavior distribution from the attractor.

    Returns a Total Variation Distance in [0, 1] over the NPC's COMMITTED categories
    (attractor weight >= salience_eps). Ignoring the near-zero noise floor prevents
    the 6 unused categories from dominating the metric. 0.0 = on-attractor.

    Closes the "uncontrolled" gap: a stable NPC sits near 0; a diverging one climbs.
    """
    if not recent_actions:
        return 0.0
    counts = Counter(recent_actions)
    total = len(recent_actions)
    norm = pheno.normalized()
    committed = [c for c in norm if norm[c] >= salience_eps]
    if not committed:
        return 0.0
    drift = sum(
        abs(counts.get(c, 0) / total - norm[c]) for c in committed
    ) / 2.0
    return drift


def functorial_recover(char_id: str, pheno: Phenotype, fallback_state: Dict[str, Any]) -> Dict[str, Any]:
    """Identity-preserving recovery. Maps broken state to fixed state.

    The 'functor' keeps structure: we re-anchor to the last stable snapshot (L1) and
    re-apply the attractor, rather than deleting and restarting. Identity (char_id,
    relationships, memories) is preserved.
    """
    stable = constitution.recover_snapshot(char_id) or dict(fallback_state)
    stable = dict(stable)  # copy so we don't mutate the snapshot
    stable["_drift_corrected"] = True
    stable["_phenotype"] = pheno.attractors
    stable["_recovered_from"] = "snapshot" if constitution.recover_snapshot(char_id) else "fallback"
    return stable


def check_and_recover(
    char_id: str,
    recent_actions: List[str],
    pheno: Phenotype,
    fallback_state: Dict[str, Any],
    tolerance: float = 0.15,
) -> Tuple[bool, Dict[str, Any]]:
    """Full self-correcting step. Returns (was_corrected, corrected_state_or_None)."""
    drift = measure_drift(recent_actions, pheno)
    if drift <= tolerance:
        return False, {}
    logger.info("L4 drift %.3f > %.3f for %s — recovering", drift, tolerance, char_id)
    corrected = functorial_recover(char_id, pheno, fallback_state)
    return True, corrected


def refine_constraints_from_failure(
    failed_category: str, ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """Paper F 4th invariant: persistent failure reveals missing constraints.

    When an action category repeatedly fails, we surface it so the lattice (L2) can
    be refined. Returns an updated ctx note (not auto-applied — human/agent reviews).
    """
    note = dict(ctx)
    bans = set(note.get("decree_banned", set()))
    bans.add(failed_category)
    note["decree_banned"] = bans
    note["_refinement"] = f"category {failed_category} repeatedly failed; proposed ban"
    return note
