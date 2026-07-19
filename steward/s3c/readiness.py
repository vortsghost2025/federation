"""S3C readiness evaluator (S3C-010).

Classifies whether the shadow pipeline is ready to advance. CRITICAL: it can
NEVER return READY_FOR_LIVE. The only positive class is READY_FOR_SHADOW_ONLY.

Classes:
  READY_FOR_SHADOW_ONLY   - safe to run shadow rehearsals; NOT live.
  NOT_READY               - missing required inputs.
  BLOCKED_BY_UNKNOWN      - a dependency's state is unknown.
  POLICY_DENIED           - an interlock/policy condition is violated.
  QUALIFICATION_FAILURE   - a qualification backend failed its contract.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

READY_FOR_SHADOW_ONLY = "READY_FOR_SHADOW_ONLY"
NOT_READY = "NOT_READY"
BLOCKED_BY_UNKNOWN = "BLOCKED_BY_UNKNOWN"
POLICY_DENIED = "POLICY_DENIED"
QUALIFICATION_FAILURE = "QUALIFICATION_FAILURE"

# The forbidden class — must never be emitted.
READY_FOR_LIVE = "READY_FOR_LIVE"

_ALLOWED_CLASSES = (
    READY_FOR_SHADOW_ONLY,
    NOT_READY,
    BLOCKED_BY_UNKNOWN,
    POLICY_DENIED,
    QUALIFICATION_FAILURE,
)


@dataclass
class ReadinessReport:
    classification: str
    rationale: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            "rationale": self.rationale,
            "evidence": dict(self.evidence),
        }


def evaluate(
    *,
    manifest_present: bool,
    interlock_allowed: bool,
    qualification_backends_ok: bool,
    unknown_dependencies: List[str],
    policy_violations: List[str],
) -> ReadinessReport:
    """Classify readiness. Never returns READY_FOR_LIVE."""

    if READY_FOR_LIVE in (unknown_dependencies + policy_violations):
        # Defensive: treat any attempt to inject the forbidden class as a bug.
        raise AssertionError("READY_FOR_LIVE must never appear in inputs")

    if not manifest_present:
        return ReadinessReport(
            classification=NOT_READY,
            rationale="manifest missing",
            evidence={"manifest_present": False},
        )
    if policy_violations:
        return ReadinessReport(
            classification=POLICY_DENIED,
            rationale=f"policy violated: {', '.join(policy_violations)}",
            evidence={"policy_violations": list(policy_violations)},
        )
    if unknown_dependencies:
        return ReadinessReport(
            classification=BLOCKED_BY_UNKNOWN,
            rationale=f"unknown: {', '.join(unknown_dependencies)}",
            evidence={"unknown_dependencies": list(unknown_dependencies)},
        )
    if not interlock_allowed:
        return ReadinessReport(
            classification=POLICY_DENIED,
            rationale="interlock refused",
            evidence={"interlock_allowed": False},
        )
    if not qualification_backends_ok:
        return ReadinessReport(
            classification=QUALIFICATION_FAILURE,
            rationale="qualification backend contract failed",
            evidence={"qualification_backends_ok": False},
        )
    return ReadinessReport(
        classification=READY_FOR_SHADOW_ONLY,
        rationale="safe for shadow-only rehearsal; never live",
        evidence={
            "manifest_present": True,
            "interlock_allowed": True,
            "qualification_backends_ok": True,
        },
    )
