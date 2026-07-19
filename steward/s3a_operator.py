"""S3A operator (Steward) identity and autonomy exclusions.

The Steward is represented as a stable deterministic actor:

    classification: operator_npc   (or system_actor)

Explicitly excluded from:
* autonomous cognition;
* NPC pair matching;
* pair workspaces;
* relationship evolution;
* open-question selection;
* convergence;
* artifact orbit;
* ordinary NPC inbox consumption;
* ordinary heartbeat scheduling.

These exclusions are enforced structurally: the actor ID is constant and the
exclusion set is exported so tests (and future live code) can assert membership.
"""

from __future__ import annotations

import hashlib
from typing import FrozenSet

OPERATOR_CLASSIFICATION = "operator_npc"
OPERATOR_ACTOR_ID = "op_steward_" + hashlib.sha256(b"steward:operator").hexdigest()[:16]

# Stable list of subsystems the Steward must never participate in.
EXCLUDED_SUBSYSTEMS: FrozenSet[str] = frozenset(
    {
        "autonomous_cognition",
        "npc_pair_matching",
        "pair_workspaces",
        "relationship_evolution",
        "open_question_selection",
        "convergence",
        "artifact_orbit",
        "ordinary_npc_inbox",
        "ordinary_heartbeat_scheduling",
    }
)


def is_excluded(subsystem: str) -> bool:
    return subsystem in EXCLUDED_SUBSYSTEMS


def can_participate(subsystem: str) -> bool:
    return not is_excluded(subsystem)


def actor_profile() -> dict:
    return {
        "actor_id": OPERATOR_ACTOR_ID,
        "classification": OPERATOR_CLASSIFICATION,
        "excluded_subsystems": sorted(EXCLUDED_SUBSYSTEMS),
        "autonomous": False,
    }
