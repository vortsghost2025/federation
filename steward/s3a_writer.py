"""S3A deterministic transactional writer core.

Applies a ProposedAction against an injected store using all-or-nothing,
optimistic, idempotent, bounded transaction semantics. No live connector.

Decision flow per action:
1. Capability decision (permit / require_approval / deny).
2. If permit: validate + apply atomically.
3. If require_approval: validate against an ApprovalArtifact; if invalid or
   absent, DENY with no mutation.
4. If deny: DENY with no mutation.

Idempotency: an action whose idempotency_key was already committed returns the
original result (replay), with no new mutation.

Every outcome produces a deterministic, redacted AuditResult. Input action
objects are never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .s3a_action import S3A_SCHEMA_VERSION, ProposedAction
from .s3a_audit import AuditResult, make_result_id, redact_evidence


def _clone_action(action: ProposedAction) -> ProposedAction:
    """Return a copy so the caller's input object is never mutated."""
    return ProposedAction.from_dict(action.to_dict())
from .s3a_operator import OPERATOR_ACTOR_ID
from .s3a_policy import (
    ApprovalArtifact,
    PolicyDecision,
    decide_capability,
    validate_approval,
)
from .s3a_store import (
    BoundedCounterError,
    ConflictError,
    InMemoryStore,
    StoreError,
)


@dataclass
class WriteOutcome:
    result: AuditResult
    committed: bool
    replayed: bool


class WriterCore:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def execute(
        self,
        action: ProposedAction,
        now_token: str,
        approval: Optional[ApprovalArtifact] = None,
    ) -> WriteOutcome:
        """Execute one governed action. Pure inputs; deterministic result."""
        action = _clone_action(action)

        # Idempotency replay: return original committed result.
        if self.store.has_idempotency_key(action.idempotency_key):
            original = self.store.original_result(action.idempotency_key)
            return WriteOutcome(
                result=AuditResult(
                    result_id=make_result_id(
                        action.action_id, "replayed", action.requested_at
                    ),
                    action_id=action.action_id,
                    decision="replayed",
                    mutation_status="none",
                    before_version=original.get("after_version", 0),
                    after_version=original.get("after_version", 0),
                    denial_reason="",
                    approval_reference=original.get("approval_reference"),
                    idempotent_replay=True,
                    redacted_evidence=redact_evidence(action.normalized_payload),
                ),
                committed=False,
                replayed=True,
            )

        decision = decide_capability(action.requested_capability)

        if decision.decision == "deny":
            return self._deny(action, decision.reason, now_token)

        if decision.decision == "require_approval":
            if approval is None:
                return self._deny(
                    action, "approval required but not supplied", now_token
                )
            appr_decision = validate_approval(approval, action, now_token)
            if appr_decision.decision != "permit":
                return self._deny(action, appr_decision.reason, now_token)
            decision = appr_decision

        # Permitted path: validate-before-mutate, all-or-nothing.
        try:
            before = self._apply_permit(action)
        except (ConflictError, BoundedCounterError, StoreError) as exc:
            return self._deny(action, f"transaction failed: {type(exc).__name__}", now_token)

        result = AuditResult(
            result_id=make_result_id(action.action_id, "committed", action.requested_at),
            action_id=action.action_id,
            decision="committed",
            mutation_status="applied",
            before_version=before,
            after_version=before + 1,
            denial_reason="",
            approval_reference=decision.approval_reference,
            idempotent_replay=False,
            redacted_evidence=redact_evidence(action.normalized_payload),
        )
        # Register idempotency only on successful commit.
        self.store.register_idempotency(action.idempotency_key, result.to_dict())
        self.store.append_audit(self._record_key(action), result.to_dict())
        return WriteOutcome(result=result, committed=True, replayed=False)

    def _apply_permit(self, action: ProposedAction) -> int:
        """All-or-nothing application. Raises StoreError on failure."""
        cap = action.requested_capability
        key = self._record_key(action)
        if cap == "steward:occurrence:increment":
            existing = self.store.read(key)
            if existing is None:
                rec = self.store.create_if_absent(
                    key, {"capability": cap, "payload": action.normalized_payload}
                )
                return rec.version - 1
            rec = self.store.increment_occurrence(key, existing.version, 1)
            return rec.version - 1
        # Default: create-if-absent then update to latest (idempotent upsert).
        existing = self.store.read(key)
        if existing is None:
            rec = self.store.create_if_absent(
                key, {"capability": cap, "payload": action.normalized_payload}
            )
            return rec.version - 1
        rec = self.store.update(key, existing.version, {
            "capability": cap,
            "payload": action.normalized_payload,
        })
        return rec.version - 1

    def _deny(
        self, action: ProposedAction, reason: str, now_token: str
    ) -> WriteOutcome:
        result = AuditResult(
            result_id=make_result_id(action.action_id, "denied", action.requested_at),
            action_id=action.action_id,
            decision="denied",
            mutation_status="none",
            before_version=0,
            after_version=0,
            denial_reason=reason,
            approval_reference=None,
            idempotent_replay=False,
            redacted_evidence=redact_evidence(action.normalized_payload),
        )
        # Denied actions still record an audit entry (no mutation of records).
        key = self._record_key(action)
        if self.store.read(key) is not None:
            self.store.append_audit(key, result.to_dict())
        return WriteOutcome(result=result, committed=False, replayed=False)

    @staticmethod
    def _record_key(action: ProposedAction) -> str:
        # Deterministic, namespace-scoped key. Never arbitrary filesystem path.
        return f"{action.target_namespace}:{action.action_type}:{action.source_finding_id}"
