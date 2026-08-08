"""
genesis_phenotype — L3 Phenotype / CPS: the "universe in their image" attractor.

Each NPC has a stable attractor (a distribution over decision categories). Selection
is pulled toward it, so an NPC converges on a coherent behavioral identity instead of
random-walking its entire space. This is what lets 39 NPCs each build a coherent
world rather than diverging.

Closes:
  NFM-019 (schema-behavior mismatch) — the attractor IS the coherent behavioral shape.

Seeding (per recommendations): attractors seed from the NPC's `npc:{id}` affiliation
plus decree alignment. An NPC aligned with a "builder" decree attracts toward build;
an explorer faction attracts toward explore. This keeps phenotypes constitutionally
grounded, not arbitrary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("genesis.phenotype")

# Canonical decision categories (mirrors npc_autonomy.DECISION_CATEGORIES).
CATEGORIES = [
    "advance_goal", "socialize", "investigate", "rest", "react_to_events",
    "seek_resources", "self_improve", "confront_rival", "help_ally",
    "explore", "request_capability",
]

# Affiliation -> baseline attractor tilt. Sum need not be 1.0; phenotype_pull normalizes.
AFFILIATION_TILT: Dict[str, Dict[str, float]] = {
    "builder": {"advance_goal": 0.4, "seek_resources": 0.2, "self_improve": 0.2, "rest": 0.1},
    "explorer": {"explore": 0.4, "investigate": 0.3, "react_to_events": 0.1, "rest": 0.1},
    "diplomat": {"socialize": 0.35, "help_ally": 0.25, "react_to_events": 0.15, "rest": 0.1},
    "guardian": {"confront_rival": 0.25, "help_ally": 0.25, "seek_resources": 0.15, "rest": 0.1},
    # NPCs with no stored affiliation (production default) — idle/resting is coherent.
    "independent": {"rest": 0.45, "socialize": 0.15, "investigate": 0.15, "advance_goal": 0.1},
}


@dataclass
class Phenotype:
    char_id: str
    attractors: Dict[str, float] = field(default_factory=dict)
    tolerance: float = 0.15  # max drift before L4 correction

    def normalized(self) -> Dict[str, float]:
        total = sum(self.attractors.values()) or 1.0
        return {c: self.attractors.get(c, 0.0) / total for c in CATEGORIES}


def seed_from_affiliation(char_id: str, affiliation: str, decree_alignment: float = 0.0) -> Phenotype:
    """Seed a phenotype from `npc:{id}` affiliation + decree alignment.

    decree_alignment in [-1, 1]: positive pulls toward pro-constitutional categories
    (help_ally, advance_goal, socialize); negative dampens them.
    """
    tilt = dict(AFFILIATION_TILT.get(affiliation, {}))
    # Ensure every canonical category has an entry (no silent gaps).
    for c in CATEGORIES:
        tilt.setdefault(c, 0.05)
    if decree_alignment:
        for c in ("help_ally", "advance_goal", "socialize"):
            tilt[c] = max(0.0, tilt[c] + 0.1 * decree_alignment)
    return Phenotype(char_id=char_id, attractors=tilt, tolerance=0.15)


def phenotype_pull(option: dict, pheno: Phenotype) -> float:
    """Adjust a raw score by proximity to this NPC's attractor.

    Options near the attractor score higher -> selection converges, not diverges.
    """
    base = option.get("score", 0.0)
    cat = option.get("category", "rest")
    target = pheno.normalized().get(cat, 0.0)
    return base * (0.5 + target)


def rank_with_phenotype(options: List[dict], pheno: Phenotype) -> List[dict]:
    """Return options sorted by phenotype-pulled score (desc)."""
    scored = []
    for o in options:
        o2 = dict(o)
        o2["_pulled"] = phenotype_pull(o, pheno)
        scored.append(o2)
    return sorted(scored, key=lambda x: x["_pulled"], reverse=True)


def is_coherent(option: dict, pheno: Phenotype) -> bool:
    """Stability gate: is this option within phenotype tolerance of the attractor?"""
    cat = option.get("category", "rest")
    norm = pheno.normalized().get(cat, 0.0)
    # Coherent if the category is a meaningful part of the attractor.
    return norm >= max(0.0, pheno.tolerance - 0.1)
