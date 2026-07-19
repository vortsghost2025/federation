"""S3A synthetic Councilor Watch adapter.

ONLY a deterministic read-model renderer. It transforms Steward
incidents/work orders into a pair-shaped or card-shaped presentation model.

It must NOT:
* create a real NPC pair;
* write a pair workspace;
* create relationships;
* enqueue messages;
* trigger cognition;
* masquerade as an ordinary autonomous NPC.

Marker fields are always present:
    synthetic: true
    read_only_projection: true
    actor_classification: operator_npc
"""

from __future__ import annotations

from typing import Any, Dict, List

from .s3a_action import S3A_SCHEMA_VERSION
from .s3a_store import InMemoryStore


def render(store: InMemoryStore) -> List[Dict[str, Any]]:
    """Render a deterministic synthetic Councilor Watch view."""
    view = store.render_councilor_watch()
    out: List[Dict[str, Any]] = []
    for entry in view:
        out.append(
            {
                "synthetic": True,
                "read_only_projection": True,
                "actor_classification": "operator_npc",
                "schema_version": S3A_SCHEMA_VERSION,
                "card_key": entry["key"],
                "version": entry["version"],
                "occurrence_count": entry["occurrence_count"],
                "data": entry["data"],
                "audit_count": entry["audit_count"],
                "pair_workspace": None,
                "relationships_created": 0,
                "messages_enqueued": 0,
                "cognition_triggered": False,
            }
        )
    return out
