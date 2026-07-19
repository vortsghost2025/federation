"""S3C shadow writer core.

Consumes a ShadowProposedAction (already governed + deterministic), applies the
safety interlock, and — only when the interlock allows — persists the approved
mutation to an injected S3B qualification backend via the S3B adapter.

This is the heart of the shadow pipeline: it proves the S3A write shape behaves
correctly against a qualification backend without ever touching production.

SHADOW RULES:
* No auto-approval. If the action is not already `approved` with a valid
  ShadowApprovalArtifact, it is denied (decision="denied", backend untouched).
* No live writer. No model calls. No wall-clock.
* Idempotent replay is re-asserted, never mutated beyond confirming presence.
* Injected clocks/timestamps only (caller-supplied).

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3 (sqlite3 is allowed ONLY inside the S3B sqlite backend, not
here).
"""

from __future__ import annotations

from typing import Any, Optional

from ..s3b.adapter import QualificationAdapter
from ..s3b.protocol import Approval, Capability, FaultKind
from .interlock import evaluate
from .shadow_model import (
    ShadowApprovalArtifact,
    ShadowProposedAction,
    ShadowWriteOutcome,
)


class ShadowWriterCore:
    """Drives ShadowProposedActions through the safety interlock + S3B backend."""

    def __init__(
        self,
        adapter: QualificationAdapter,
        capability: Capability,
        namespace: str,
        now_token: str,
        loaded_capabilities: Optional[list] = None,
        output_dir_local_safe: bool = True,
        redaction_enabled: bool = True,
    ) -> None:
        self.adapter = adapter
        self.capability = capability
        self.namespace = namespace
        self.now_token = now_token
        self.loaded_capabilities = list(loaded_capabilities or [])
        self.output_dir_local_safe = output_dir_local_safe
        self.redaction_enabled = redaction_enabled

    def _interlock(self, wildcard_approval: bool) -> Any:
        return evaluate(
            mode="fixture_shadow_apply",
            backend_qualification_only=True,
            namespace=self.namespace,
            live_writer_present=False,
            loaded_capabilities=self.loaded_capabilities,
            wildcard_approval=wildcard_approval,
            output_dir_local_safe=self.output_dir_local_safe,
            redaction_enabled=self.redaction_enabled,
            deterministic_timestamp_supplied=bool(self.now_token),
        )

    def execute(
        self,
        action: ShadowProposedAction,
        approval: Optional[ShadowApprovalArtifact] = None,
    ) -> ShadowWriteOutcome:
        """Govern + persist a single shadow action.

        Returns decision="denied" (backend untouched) unless:
          - interlock allows; AND
          - action.approval_state == "approved"; AND
          - a valid, non-expired, non-wildcard approval artifact is supplied.
        """

        wildcard = approval is not None and (
            "*" in approval.granted_capability or "*" in approval.scope
        )
        verdict = self._interlock(wildcard_approval=wildcard)
        if not verdict.allowed:
            return ShadowWriteOutcome(
                action_id=action.action_id or "",
                decision="denied",
                reason=f"interlock refused: {verdict.reason}",
                approval_attached=approval is not None,
            )

        if action.approval_state != "approved" or approval is None:
            return ShadowWriteOutcome(
                action_id=action.action_id or "",
                decision="denied",
                reason="no valid approval attached",
                approval_attached=approval is not None,
            )

        try:
            approval.validate_against(action, self.now_token)
        except ValueError as exc:
            return ShadowWriteOutcome(
                action_id=action.action_id or "",
                decision="denied",
                reason=f"approval invalid: {exc}",
                approval_attached=True,
            )

        # Attach the approval to the S3B backend's revocation registry.
        self.adapter.attach_approval(
            Approval(
                token=approval.approval_id,
                capability=approval.granted_capability,
                granted_for=approval.scope,
            )
        )

        # Build a lightweight S3A-compatible outcome object for the adapter.
        outcome = _S3AlikeOutcome(action)
        receipt = self.adapter.persist(outcome)

        return ShadowWriteOutcome(
            action_id=action.action_id or "",
            decision="committed" if receipt.persisted else "denied",
            reason=receipt.error or "persisted" if receipt.persisted else "backend refused",
            approval_attached=True,
            persisted=receipt.persisted,
            backend=receipt.backend,
            seq=receipt.seq,
            fault_injected=(
                receipt.fault_injected.value if receipt.fault_injected else None
            ),
            error=receipt.error,
        )


class _S3AlikeOutcome:
    """Minimal stand-in so the S3B adapter can persist a shadow action.

    Mirrors the fields the S3B adapter reads: `.result.action_id`,
    `.result.decision`, `.result.idempotent_replay`. No S3A import needed.
    """

    def __init__(self, action: ShadowProposedAction) -> None:
        self.replayed = False
        self.result = _Result(action)


class _Result:
    def __init__(self, action: ShadowProposedAction) -> None:
        self.action_id = action.action_id or ""
        self.decision = "committed"
        self.idempotent_replay = False
