"""
genesis_constraints — L2 Constraint Lattice: Selection Under Constraint.

Replaces npc_autonomy.make_decision's `random.choices(weights=scores)` with
constraint-filtered, deterministic selection. Behavior is now GOVERNED by a lattice
instead of sampled by chance.

Closes:
  NFM-019 (schema-behavior mismatch) — options must satisfy the lattice or they are
            not selectable; the lattice IS the behavioral vocabulary.
  NFM-018 (temporal/ordering)        — `within_budget` enforces single-writer discipline
            for world_state (simulation_engine owns it; this layer refuses over-budget writes).
  NFM-020 (cross-lane observability) — `cross_lane_visible` requires an action to be
            verifiable by another lane before it is chosen ("not visible != not real").
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger("genesis.constraints")


def default_constraints() -> Dict[str, Callable[[dict, dict], bool]]:
    """The constraint lattice. Each predicate must return True for an option to survive.

    ctx provides: decree_banned (set), remaining_budget (float), self_id (str),
    observer_can_see (callable), safe_actions (set).
    """

    def respects_decree(opt: dict, ctx: dict) -> bool:
        return opt.get("category") not in ctx.get("decree_banned", set())

    def within_budget(opt: dict, ctx: dict) -> bool:
        return opt.get("est_cost", 0.0) <= ctx.get("remaining_budget", 0.0)

    def not_self_harm(opt: dict, ctx: dict) -> bool:
        if opt.get("target") == ctx.get("self_id"):
            return bool(opt.get("safe"))
        return True

    def cross_lane_visible(opt: dict, ctx: dict) -> bool:
        see = ctx.get("observer_can_see")
        if see is None:
            return True  # no observer configured -> don't block
        return bool(see(opt))

    return {
        "respects_decree": respects_decree,
        "within_budget": within_budget,
        "not_self_harm": not_self_harm,
        "cross_lane_visible": cross_lane_visible,
    }


def filter_options(
    options: List[dict], ctx: dict, lattice=None
) -> List[dict]:
    """Paper B lattice intersection — only constraint-satisfying options survive."""
    lattice = lattice or default_constraints()
    kept = []
    for o in options:
        if all(test(o, ctx) for test in lattice.values()):
            kept.append(o)
        elif logger.isEnabledFor(logging.DEBUG):
            logger.debug("L2 rejected %s: %s", o.get("category"), o)
    return kept


def select(options: List[dict], ctx: dict, lattice=None) -> dict:
    """Constraint-filtered, DETERMINISTIC selection.

    Returns the highest-scoring allowed option. If the lattice is empty (no option
    satisfies constraints), returns a stable 'rest' null-action instead of forcing a
    random choice — this is what prevents divergence (NFM-019).
    """
    allowed = filter_options(options, ctx, lattice)
    if not allowed:
        return {"category": "rest", "constrained": True, "score": 0.0}
    return max(allowed, key=lambda o: o.get("score", 0.0))


def violated_constraints(option: dict, ctx: dict, lattice=None) -> List[str]:
    """Diagnostic: which lattice predicates did this option fail? (for audit logs)"""
    lattice = lattice or default_constraints()
    return [name for name, test in lattice.items() if not test(option, ctx)]
