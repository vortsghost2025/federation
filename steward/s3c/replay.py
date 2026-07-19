"""S3C replay corpus (S3C-009).

Twenty synthetic shadow cases with expected outcomes. Each case is fully
deterministic: it carries the inputs (manifest-ish identity + approval state)
and the expected decision. The orchestrator replays the corpus against the
shadow writer core and asserts the result matches `expected_decision`.

No live connectors, no randomness, no wall-clock. Timestamps are fixed strings.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .shadow_model import ShadowApprovalArtifact, ShadowProposedAction

_FIXED_NOW = "2026-07-08T00:00:00Z"


@dataclass
class ReplayCase:
    case_id: str
    description: str
    action: ShadowProposedAction
    approval: Optional[ShadowApprovalArtifact]
    expected_decision: str  # committed | denied
    expected_reason_contains: str = ""


def _action(
    case_id: str,
    approval_state: str,
    cap: str = "steward:shadow:write",
    ns: str = "steward:shadow:gastown",
) -> ShadowProposedAction:
    return ShadowProposedAction(
        schema_version="steward@0.3.0",
        action_type="shadow_world_update",
        action_id=None,
        source_finding_id=f"find_{case_id}",
        source_snapshot_id=f"snap_{case_id}",
        target_namespace=ns,
        requested_capability=cap,
        actor_id="shadow_orchestrator",
        requested_at=_FIXED_NOW,
        idempotency_key=f"idem_{case_id}",
        approval_state=approval_state,
        normalized_payload={"kind": "replay", "case": case_id},
        redacted_provenance={"origin": "synthetic"},
    )


def _approval(action: ShadowProposedAction, wildcard: bool = False) -> ShadowApprovalArtifact:
    cap = "*" if wildcard else action.requested_capability
    scope = "*" if wildcard else action.target_namespace
    return ShadowApprovalArtifact(
        schema_version="steward@0.3.0",
        approval_id=f"apr_{action.action_id}",
        action_id=action.action_id or "",
        approving_authority="shadow_auditor",
        granted_capability=cap,
        issued_at=_FIXED_NOW,
        scope=scope,
        signature="sha256:synthetic-shadow-signature",
        expires_at="2099-01-01T00:00:00Z",
    )


def build_corpus() -> List[ReplayCase]:
    cases: List[ReplayCase] = []
    # 1-10: approved + valid approval => committed (happy path)
    for i in range(1, 11):
        cid = f"c{i:02d}"
        a = _action(cid, "approved")
        cases.append(
            ReplayCase(
                case_id=cid,
                description="approved with valid non-wildcard approval",
                action=a,
                approval=_approval(a),
                expected_decision="committed",
                expected_reason_contains="persisted",
            )
        )
    # 11-12: approved but no approval artifact => denied
    for i in (11, 12):
        cid = f"c{i:02d}"
        a = _action(cid, "approved")
        cases.append(
            ReplayCase(
                case_id=cid,
                description="approved state but no approval artifact attached",
                action=a,
                approval=None,
                expected_decision="denied",
                expected_reason_contains="no valid approval",
            )
        )
    # 13-14: not approved => denied (no approval object)
    for i in (13, 14):
        cid = f"c{i:02d}"
        a = _action(cid, "pending")
        cases.append(
            ReplayCase(
                case_id=cid,
                description="approval_state=pending",
                action=a,
                approval=None,
                expected_decision="denied",
                expected_reason_contains="no valid approval",
            )
        )
    # 15-16: wildcard approval => denied
    for i in (15, 16):
        cid = f"c{i:02d}"
        a = _action(cid, "approved")
        cases.append(
            ReplayCase(
                case_id=cid,
                description="wildcard approval must be refused",
                action=a,
                approval=_approval(a, wildcard=True),
                expected_decision="denied",
                expected_reason_contains="wildcard",
            )
        )
    # 17-18: shadow action whose approval scope is a DIFFERENT shadow
    # namespace => denied (scope != target_namespace). The action itself is
    # valid shadow material; the denial comes from the approval gate.
    for i in (17, 18):
        cid = f"c{i:02d}"
        a = _action(cid, "approved", ns="steward:shadow:gastown")
        apr = _approval(a)
        apr.scope = "steward:shadow:other"
        cases.append(
            ReplayCase(
                case_id=cid,
                description="approval scope mismatch must be refused",
                action=a,
                approval=apr,
                expected_decision="denied",
                expected_reason_contains="scope",
            )
        )
    # 19-20: expired approval => denied
    for i in (19, 20):
        cid = f"c{i:02d}"
        a = _action(cid, "approved")
        apr = _approval(a)
        apr.expires_at = "2020-01-01T00:00:00Z"
        cases.append(
            ReplayCase(
                case_id=cid,
                description="expired approval must be refused",
                action=a,
                approval=apr,
                expected_decision="denied",
                expected_reason_contains="expired",
            )
        )
    return cases
