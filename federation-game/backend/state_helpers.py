"""
Federation Game State Helpers — extracted from state.py
Contains: pure helper functions and governance functions.
Functions that reference game_state singleton use late import to avoid circular dependency.
"""

import random
import logging
from typing import Dict, List, Any, Optional

from state_constants import (
    EVENT_LANE_DEFAULTS,
    GOVERNANCE_PROPOSALS,
    LEDGER_METRICS,
    METRIC_LABELS,
)

logger = logging.getLogger(__name__)


def clamp_percent(value: int) -> int:
    return max(0, min(100, value))


def enrich_event(event: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(event)
    defaults = EVENT_LANE_DEFAULTS.get(enriched.get("id", ""), {})
    enriched.setdefault("affected_lane", defaults.get("affected_lane", "Control Plane"))
    enriched.setdefault("domain", defaults.get("domain", "Operations"))
    enriched.setdefault("rights_at_stake", ["Provenance", "Operator discretion"])
    enriched.setdefault("constitutional_risk", "operational")
    enriched.setdefault("pressure", "Every decision mutates the system.")
    enriched.setdefault(
        "rationale",
        defaults.get(
            "rationale",
            "Decision requires explicit state-transition review."
        ),
    )
    choices = []
    for choice in enriched.get("choices", []):
        c = dict(choice)
        c.setdefault("affected_lane", enriched["affected_lane"])
        c.setdefault("rationale", enriched["rationale"])
        c.setdefault(
            "next_safe_action",
            defaults.get(
                "next_safe_action",
                "Record the decision and verify the next state."
            ),
        )
        choices.append(c)
    enriched["choices"] = choices
    return enriched


def snapshot_metrics() -> Dict[str, int]:
    from state import game_state
    return {field: getattr(game_state, field) for field in LEDGER_METRICS}


def calculate_deltas(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    return {
        field: after[field] - before[field]
        for field in LEDGER_METRICS
        if after[field] != before[field]
    }


def summarize_delta_direction(deltas: Dict[str, int], positive: bool) -> str:
    values = [
        METRIC_LABELS.get(field, field)
        for field, delta in deltas.items()
        if (delta > 0 if positive else delta < 0)
    ]
    if not values:
        return "none"
    return ", ".join(values[:3])


def build_explainability(
    event: Dict[str, Any],
    choice: Dict[str, Any],
    deltas: Dict[str, int],
) -> Dict[str, str]:
    domain = event.get("domain", "Exploration")
    risk = event.get("constitutional_risk", "operational")
    if choice.get("blocked_by_no_gate"):
        constitutional_pressure = "provenance gate vs operator temptation"
    elif choice.get("id") == "emergency_order":
        constitutional_pressure = "stability vs rights"
    elif choice.get("id") == "court_review":
        constitutional_pressure = "rights review vs speed"
    elif choice.get("id") == "vote":
        constitutional_pressure = "legitimacy vs delay"
    elif "hull" in deltas or "shields" in deltas:
        constitutional_pressure = "mission safety vs resource pressure"
    else:
        constitutional_pressure = "exploration risk vs public benefit"
    return {
        "domain": domain,
        "risk": risk,
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "constitutional_pressure": constitutional_pressure,
        "short_term_gain": summarize_delta_direction(deltas, positive=True),
        "long_term_cost": summarize_delta_direction(deltas, positive=False),
        "rationale": choice.get(
            "rationale",
            event.get(
                "rationale",
                "Decision recorded for bounded simulator continuity."
            ),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue only inside lane boundaries.",
        ),
    }


def get_governance_status() -> str:
    from state import game_state
    gs = game_state
    if gs.constitutional_integrity < 25:
        return "CONSTITUTIONAL CRISIS"
    if gs.rights_protection < 25:
        return "RIGHTS CRISIS"
    if gs.public_trust < 35:
        return "PUBLIC TRUST WARNING"
    if gs.council_support < 35:
        return "COUNCIL DEADLOCK WARNING"
    if gs.emergency_powers > 70:
        return "EMERGENCY POWERS WATCH"
    if gs.federation_stability > 75 and gs.public_trust > 70:
        return "STABLE REPUBLIC"
    return "DELIBERATIVE REPUBLIC"


def build_governance_event() -> Dict[str, Any]:
    proposal = random.choice(GOVERNANCE_PROPOSALS)
    return {
        "id": "council_proposal",
        "title": proposal["title"],
        "description": proposal["description"],
        "image": "council",
        "domain": proposal["domain"],
        "rights_at_stake": proposal["rights_at_stake"],
        "constitutional_risk": proposal["constitutional_risk"],
        "pressure": proposal["pressure"],
        "affected_lane": proposal["affected_lane"],
        "rationale": proposal["rationale"],
        "faction_affinity": {"diplomatic_corps": 0.05},
        "choices": [
            {
                "id": "vote",
                "text": "HOLD VOTE",
                "outcome": "consensus",
                "reward": {
                    "public_trust": 8,
                    "council_support": 10,
                    "federation_stability": 4,
                    "constitutional_integrity": 3,
                    "emergency_powers": -6,
                },
                "policy": proposal["policies"]["vote"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["vote"],
                "lesson": "Legitimacy rises when people can see the process.",
                "faction_affinity": {
                    "diplomatic_corps": 0.10,
                    "cultural_ministry": 0.03,
                },
            },
            {
                "id": "emergency_order",
                "text": "EMERGENCY ORDER",
                "outcome": "swift action",
                "reward": {
                    "credits": 120,
                    "public_trust": -10,
                    "council_support": -8,
                    "federation_stability": -6,
                    "constitutional_integrity": -10,
                    "rights_protection": -8,
                    "emergency_powers": 18,
                },
                "policy": proposal["policies"]["emergency_order"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["emergency_order"],
                "lesson": "Power used without checks solves one problem by creating another.",
                "faction_affinity": {
                    "military_command": 0.08,
                    "preservation_society": -0.05,
                },
            },
            {
                "id": "court_review",
                "text": "COURT REVIEW",
                "outcome": "rights protected",
                "reward": {
                    "public_trust": 12,
                    "council_support": -3,
                    "federation_stability": 8,
                    "credits": -40,
                    "constitutional_integrity": 10,
                    "rights_protection": 12,
                    "emergency_powers": -10,
                },
                "policy": proposal["policies"]["court_review"],
                "affected_lane": proposal["affected_lane"],
                "rationale": proposal["rationale"],
                "next_safe_action": proposal["next_safe_actions"]["court_review"],
                "lesson": "Rights are slower than orders, but they keep the system trustworthy.",
                "faction_affinity": {
                    "preservation_society": 0.10,
                    "diplomatic_corps": 0.03,
                },
            },
        ],
    }


def apply_governance_pressure(choice: Dict[str, Any]) -> None:
    from state import game_state
    gs = game_state
    outcome = choice.get("outcome", "").lower() if choice else ""
    positive_outcome = any(
        w in outcome
        for w in ("thrive", "flourish", "unite", "restore", "strengthen", "reform", "uphold")
    )
    if gs.public_trust < 35:
        gs.crew_morale = clamp_percent(gs.crew_morale - 3)
        gs.federation_stability = clamp_percent(gs.federation_stability - 2)
        if positive_outcome:
            gs.public_trust = clamp_percent(gs.public_trust + 1)
            gs.crew_morale = clamp_percent(gs.crew_morale + 1)
    if gs.council_support < 30:
        gs.federation_stability = clamp_percent(gs.federation_stability - 1)
        gs.emergency_powers = clamp_percent(gs.emergency_powers + 1)
        if positive_outcome:
            gs.council_support = clamp_percent(gs.council_support + 1)
    if gs.emergency_powers > 80:
        gs.constitutional_integrity = clamp_percent(gs.constitutional_integrity - 2)
        gs.rights_protection = clamp_percent(gs.rights_protection - 1)
        if positive_outcome and gs.emergency_powers > 0:
            gs.emergency_powers = clamp_percent(gs.emergency_powers - 1)
    if gs.federation_stability > 80:
        gs.public_trust = clamp_percent(gs.public_trust + 1)
    if gs.federation_stability < 25 and positive_outcome:
        gs.federation_stability = clamp_percent(gs.federation_stability + 2)
        gs.public_trust = clamp_percent(gs.public_trust + 1)
