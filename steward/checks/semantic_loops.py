"""Check: semantic-loops (pure, S1).

Detects the resolved-topic semantic loop (diagnosed live in a prior session,
PASS). Mechanism (read-only description, no dependency on commit 909ea76):

A resolved pair whose active `shared_goal` still equals `resolved_shared_goal`,
combined with a sync path that insists on a nonblank question and re-applies
the same universal fallback ("What happens next in the Federation?"), produces
a permanent semantic loop.

Detection (spec 7.3):
  convergence_state.resolved == true
  AND shared_goal == resolved_shared_goal
  AND repeated identical fallback question in recent actions (>= 2)

Inputs fixture shape (frozen):
{
  "pairs": [
    {
      "pair_key": "npc_pair:char_001__char_306:state",
      "convergence_resolved": true,
      "shared_goal": "deep-signal",
      "resolved_shared_goal": "deep-signal",
      "recent_actions": ["What happens next in the Federation?",
                          "What happens next in the Federation?"],
      "fallback_question": "What happens next in the Federation?",
      "char_ids": ["char_001", "char_306"]
    }, ...
  ]
}
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..schema import Finding, make_finding
from . import register_check

FALLBACK_QUESTION = "What happens next in the Federation?"
MIN_REPEATS = 2

# Stable sentinel used only when a caller supplies no observed_at. Never a
# clock value; keeps single-check manual runs deterministic and reproducible.
DEFAULT_OBSERVED_AT = "1970-01-01T00:00:00Z"


def _count_repeats(actions: List[str], question: str) -> int:
    return sum(1 for a in actions if a == question)


def semantic_loops(fixture: Dict[str, Any]) -> List[Finding]:
    observed_at = fixture.get("observed_at", DEFAULT_OBSERVED_AT)
    pairs = fixture.get("pairs")
    if pairs is None:
        return [
            make_finding(
                check_id="semantic-loops",
                observed_at=observed_at,
                severity="info",
                status="unknown",
                summary="Pair workspace source unavailable; cannot determine state.",
                evidence={"source": "pair_workspace"},
                dedupe_key="semantic-loop:unknown:pair_workspace",
                recommended_action="Verify pair-state adapter (S2).",
            )
        ]

    findings: List[Finding] = []
    for p in pairs:
        pair_key = p.get("pair_key", "unknown-pair")
        resolved = bool(p.get("convergence_resolved"))
        shared = p.get("shared_goal")
        rshared = p.get("resolved_shared_goal")
        fallback = p.get("fallback_question", FALLBACK_QUESTION)
        actions = p.get("recent_actions", [])
        repeats = _count_repeats(actions, fallback)
        char_ids = p.get("char_ids", [])

        matched = resolved and shared == rshared
        is_loop = matched and repeats >= MIN_REPEATS

        if is_loop:
            findings.append(
                make_finding(
                    check_id="semantic-loops",
                    observed_at=observed_at,
                    severity="warning",
                    summary=(
                        f"Resolved pair {pair_key} re-anchored to generic "
                        f"fallback question."
                    ),
                    evidence={
                        "pair_key": pair_key,
                        "convergence_resolved": resolved,
                        "shared_goal": shared,
                        "resolved_shared_goal": rshared,
                        "fallback_question": fallback,
                        "repeated_question_count": repeats,
                    },
                    affected_entities=char_ids,
                    dedupe_key=f"semantic-loop:{pair_key}",
                    recommended_action=(
                        "Assign investigation work order; consider "
                        "post-resolution topic transition."
                    ),
                    # steward:work_order:create is an automatic Federation-world
                    # capability (spec Section 9). No gated action is requested,
                    # so approval is not required.
                    required_capability="steward:work_order:create",
                    approval_required=False,
                )
            )
    return findings


register_check("semantic-loops", semantic_loops)
