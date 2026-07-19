"""S3A pure action planner.

Converts selected S1 findings into ProposedAction objects.

The planner:
* remains pure (no side effects, no I/O, no clock, no randomness);
* never reads live sources;
* never executes actions;
* uses deterministic IDs;
* produces only known capabilities;
* emits zero actions when evidence is `unknown` unless an uncertainty incident
  is explicitly required;
* avoids action storms through deterministic deduplication (dedupe_key).

It returns a list of ProposedAction and never mutates its inputs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .s3a_action import (
    S3A_SCHEMA_VERSION,
    ProposedAction,
)
from .s3a_operator import OPERATOR_ACTOR_ID, OPERATOR_CLASSIFICATION
from .s3a_policy import AUTO_PERMITTED

# Map finding check_id patterns to an auto-permitted capability.
_CHECK_TO_CAPABILITY = {
    "npc_heartbeat": "steward:incident:create",
    "semantic_loop": "steward:work_order:create",
}

# Capability -> action_type template.
_CAP_TO_ACTION_TYPE = {
    "steward:incident:create": "incident_create",
    "steward:work_order:create": "work_order_create",
    "steward:occurrence:increment": "occurrence_increment",
    "steward:notification:suppress_duplicate": "notification_suppress",
    "steward:councilor_watch:render": "councilor_watch_render",
}


def _namespace_for(capability: str) -> str:
    # All actions stay within the steward namespace.
    return "steward:local"


def plan_actions(
    findings: List[Dict[str, Any]],
    snapshot_id: str,
    requested_at: str,
    require_uncertainty_incident: bool = False,
) -> List[ProposedAction]:
    """Pure: findings -> proposed actions.

    `findings` are S1 finding dicts (from schema.Finding.to_dict). Inputs are
    never mutated.
    """
    actions: List[ProposedAction] = []
    seen_dedupe: set = set()

    for finding in findings:
        check_id = finding.get("check_id", "")
        severity = finding.get("severity", "")
        status = finding.get("status", "")
        evidence = dict(finding.get("evidence") or {})
        finding_id = finding.get("finding_id", "")
        dedupe_key = finding.get("dedupe_key", "")

        # Uncertainty handling: unknown evidence produces no unsafe action
        # unless an uncertainty incident is explicitly required.
        if status == "unknown" and not require_uncertainty_incident:
            continue

        capability = _CHECK_TO_CAPABILITY.get(check_id)
        if capability is None:
            # Default governance: a diagnostic snapshot is always safe.
            capability = "steward:diagnostic_snapshot:create"

        # Deterministic deduplication to avoid action storms.
        dedup_sig = (capability, dedupe_key or finding_id)
        if dedup_sig in seen_dedupe:
            continue
        seen_dedupe.add(dedup_sig)

        action_type = _CAP_TO_ACTION_TYPE.get(capability, "generic_write")
        idem_key = f"{finding_id}:{capability}"

        action = ProposedAction(
            schema_version=S3A_SCHEMA_VERSION,
            action_type=action_type,
            action_id=None,  # derived deterministically
            source_finding_id=finding_id,
            source_snapshot_id=snapshot_id,
            target_namespace=_namespace_for(capability),
            requested_capability=capability,
            actor_id=OPERATOR_ACTOR_ID,
            requested_at=requested_at,
            idempotency_key=idem_key,
            approval_state="none",
            normalized_payload={
                "check_id": check_id,
                "severity": severity,
                "status": status,
                "evidence_summary": _safe_summary(evidence),
            },
            redacted_provenance={"operator_classification": OPERATOR_CLASSIFICATION},
            expected_preconditions={"capability": capability},
            resulting_status="planned",
            dedupe_key=dedupe_key,
        )
        actions.append(action)

    return actions


def _safe_summary(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic, non-secret summary of evidence keys."""
    return {
        "evidence_keys": sorted(evidence.keys()),
        "evidence_count": len(evidence),
    }
