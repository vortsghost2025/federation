"""S3A capability policy and approval artifact validation.

Phase S3A scope: governed writer core only. The policy decision is pure and
deterministic. Approval-gated capabilities perform NO store mutation and emit a
deterministic `approval_required` result.

No model can grant approval. Approvals are externally supplied, validated
artifacts. Expired, mismatched, malformed, or overly broad approvals fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .s3a_action import S3A_SCHEMA_VERSION, ProposedAction

# Automatically permitted local writer capabilities (no approval required).
AUTO_PERMITTED = frozenset(
    {
        "steward:incident:create",
        "steward:incident:update",
        "steward:work_order:create",
        "steward:work_order:assign_owner",
        "steward:diagnostic_snapshot:create",
        "steward:occurrence:increment",
        "steward:notification:suppress_duplicate",
        "steward:councilor_watch:render",
    }
)

# Approval-gated capabilities. These require a valid approval artifact and
# must NOT mutate the store before approval is validated.
APPROVAL_GATED = frozenset(
    {
        "steward:npc_message:inject",
        "steward:npc_cognition:trigger",
        "steward:redis_external:write",
        "steward:docker:mutate",
        "steward:deployment:change",
        "steward:schema:change",
        "steward:configuration:change",
        "steward:external_notification:send",
    }
)

KNOWN_CAPABILITIES = AUTO_PERMITTED | APPROVAL_GATED

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_SCOPE_PATTERN = re.compile(r"^steward:[a-z0-9_]+$")


@dataclass
class PolicyDecision:
    capability: str
    decision: str  # "permit" | "require_approval" | "deny"
    reason: str
    approval_reference: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "decision": self.decision,
            "reason": self.reason,
            "approval_reference": self.approval_reference,
        }


def decide_capability(capability: str) -> PolicyDecision:
    """Pure, deterministic capability decision."""
    if capability in AUTO_PERMITTED:
        return PolicyDecision(capability, "permit", "capability auto-permitted")
    if capability in APPROVAL_GATED:
        return PolicyDecision(
            capability,
            "require_approval",
            "capability is approval-gated; no store mutation performed",
        )
    return PolicyDecision(capability, "deny", "unknown capability denied")


@dataclass
class ApprovalArtifact:
    """Externally supplied authorization artifact.

    S3A validates structure and scope but does NOT implement cryptographic trust
    or fabricate approvals. The signature field is a verification placeholder.
    """

    approval_id: str
    action_id: str
    approving_authority: str
    granted_capability: str
    issued_at: str
    scope: str
    signature: str
    schema_version: str
    expires_at: Optional[str] = None

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "ApprovalArtifact":
        required = {
            "approval_id",
            "action_id",
            "approving_authority",
            "granted_capability",
            "issued_at",
            "scope",
            "signature",
            "schema_version",
        }
        missing = required - set(raw.keys())
        if missing:
            raise ValueError(f"missing approval fields: {sorted(missing)}")
        extra = set(raw.keys()) - (required | {"expires_at"})
        if extra:
            raise ValueError(f"unknown approval fields: {sorted(extra)}")
        return ApprovalArtifact(
            approval_id=raw["approval_id"],
            action_id=raw["action_id"],
            approving_authority=raw["approving_authority"],
            granted_capability=raw["granted_capability"],
            issued_at=raw["issued_at"],
            scope=raw["scope"],
            signature=raw["signature"],
            schema_version=raw["schema_version"],
            expires_at=raw.get("expires_at"),
        )


def _is_expired(artifact: ApprovalArtifact, now_token: str) -> bool:
    """Deterministic expiry check.

    `now_token` is a caller-supplied lexicographic timestamp (ISO-8601 sorts
    correctly as text). S3A never reads the system clock.
    """
    if artifact.expires_at is None:
        return False
    return now_token > artifact.expires_at


def validate_approval(
    artifact: ApprovalArtifact,
    action: ProposedAction,
    now_token: str,
) -> PolicyDecision:
    """Fail-closed approval validation.

    Rules:
    * schema version must match;
    * expiration must not be passed (caller-supplied, monotonic token);
    * approval.action_id must equal action.action_id;
    * approval.granted_capability must equal the exact requested capability;
    * scope must exactly equal action.target_namespace;
    * a wildcard/broad scope is rejected.
    """
    if artifact.schema_version != S3A_SCHEMA_VERSION:
        return PolicyDecision(
            action.requested_capability,
            "deny",
            "approval schema_version mismatch",
        )
    if _is_expired(artifact, now_token):
        return PolicyDecision(
            action.requested_capability, "deny", "approval expired"
        )
    if artifact.action_id != action.action_id:
        return PolicyDecision(
            action.requested_capability, "deny", "approval action_id mismatch"
        )
    if artifact.granted_capability != action.requested_capability:
        return PolicyDecision(
            action.requested_capability,
            "deny",
            "approval granted_capability mismatch",
        )
    if not _SCOPE_PATTERN.match(artifact.scope):
        return PolicyDecision(
            action.requested_capability, "deny", "approval scope malformed"
        )
    if artifact.scope != action.target_namespace:
        return PolicyDecision(
            action.requested_capability, "deny", "approval scope mismatch"
        )
    # Wildcard / overly broad scope rejection: only exact namespace allowed.
    if artifact.scope in ("steward:*", "steward", "*"):
        return PolicyDecision(
            action.requested_capability, "deny", "approval scope too broad"
        )
    return PolicyDecision(
        action.requested_capability,
        "permit",
        "approval valid",
        approval_reference=artifact.approval_id,
    )
