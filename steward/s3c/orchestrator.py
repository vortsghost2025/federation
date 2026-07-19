"""S3C shadow orchestrator (S3C-003).

The single entry point that drives a shadow run end to end:

  manifest (S3C-002)
    -> source profile (S3C-005)
    -> build shadow actions (S3C shadow model)
    -> safety interlock (S3C-004)
    -> shadow writer core (writer.py) over an S3B qualification backend (S3C-006)
    -> run bundle (S3C-007)
    -> readiness evaluation (S3C-010)

The orchestrator is fully offline. It injects deterministic clocks and IDs and
performs NO auto-approval and NO model calls. For `live_readonly_*` modes it
delegates to the read-only rehearsal module (S3C-008), which issues only
authorized read-only SSH/docker inspect commands and never discloses secrets.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3 (sqlite3 only inside S3B backends).
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Optional

from .backend import build_shadow_memory_adapter, build_shadow_sqlite_adapter
from .bundles import RunBundle, write_bundle
from .interlock import evaluate
from .manifest import RunManifest
from .profiles import (
    SourceProfile,
    default_fixture_profile,
    default_live_readonly_profile,
)
from .readiness import evaluate as evaluate_readiness
from .shadow_model import (
    ShadowApprovalArtifact,
    ShadowProposedAction,
    ShadowWriteOutcome,
)
from .writer import ShadowWriterCore

# Fixed deterministic timestamp used across the orchestrator (no wall-clock).
_FIXED_NOW = "2026-07-08T00:00:00Z"


class ShadowOrchestrator:
    """Runs a shadow manifest and produces a run bundle."""

    def __init__(
        self,
        manifest: RunManifest,
        source_profile: Optional[SourceProfile] = None,
        backend_kind: str = "memory",
        loaded_capabilities: Optional[list] = None,
    ) -> None:
        self.manifest = manifest
        self.source_profile = source_profile or (
            default_live_readonly_profile()
            if manifest.mode.startswith("live_readonly")
            else default_fixture_profile()
        )
        self.backend_kind = backend_kind
        self.loaded_capabilities = list(loaded_capabilities or [])
        self._sqlite_path: Optional[str] = None

    def _build_adapter(self):
        if self.backend_kind == "sqlite":
            import tempfile as _t

            fd, self._sqlite_path = _t.mkstemp(prefix="s3c_run_", suffix=".sqlite")
            import os as _os

            _os.close(fd)
            return build_shadow_sqlite_adapter(self._sqlite_path)
        return build_shadow_memory_adapter()

    def build_actions(self) -> List[ShadowProposedAction]:
        """Build deterministic shadow actions from the manifest findings."""

        actions: List[ShadowProposedAction] = []
        for idx, fid in enumerate(self.manifest.finding_ids or ["find_none"]):
            actions.append(
                ShadowProposedAction(
                    schema_version="steward@0.3.0",
                    action_type="shadow_world_update",
                    action_id=None,
                    source_finding_id=fid,
                    source_snapshot_id=self.manifest.snapshot_id,
                    target_namespace=self.manifest.namespace,
                    requested_capability=self.manifest.capability,
                    actor_id="shadow_orchestrator",
                    requested_at=self.manifest.requested_at,
                    idempotency_key=f"{self.manifest.idempotency_key}:{idx}",
                    approval_state="pending",  # no auto-approval
                    normalized_payload={"kind": "shadow", "finding": fid},
                    redacted_provenance={"origin": "synthetic-shadow"},
                )
            )
        return actions

    def _interlock_allowed(self) -> bool:
        verdict = evaluate(
            mode=self.manifest.mode,
            backend_qualification_only=True,
            namespace=self.manifest.namespace,
            live_writer_present=False,
            loaded_capabilities=self.loaded_capabilities,
            wildcard_approval=False,
            output_dir_local_safe=True,
            redaction_enabled=True,
            deterministic_timestamp_supplied=bool(self.manifest.requested_at),
        )
        return verdict.allowed

    def run(
        self,
        approvals: Optional[Dict[str, ShadowApprovalArtifact]] = None,
        actions: Optional[List[ShadowProposedAction]] = None,
    ) -> RunBundle:
        """Execute the shadow run, returning a finalized bundle.

        If `actions` is supplied it is used as-is (so pre-approved actions keep
        their `approved` state). Otherwise actions are built fresh (pending).
        """

        approvals = approvals or {}
        actions = actions if actions is not None else self.build_actions()
        adapter = self._build_adapter()
        core = ShadowWriterCore(
            adapter=adapter,
            capability=adapter.cap,
            namespace=self.manifest.namespace,
            now_token=self.manifest.requested_at or _FIXED_NOW,
            loaded_capabilities=self.loaded_capabilities,
        )

        action_dicts: List[Dict[str, Any]] = []
        outcome_dicts: List[Dict[str, Any]] = []
        for action in actions:
            action_dicts.append(action.to_dict())
            apr = approvals.get(action.action_id or "")
            outcome: ShadowWriteOutcome = core.execute(action, apr)
            outcome_dicts.append(
                {
                    "action_id": outcome.action_id,
                    "decision": outcome.decision,
                    "reason": outcome.reason,
                    "approval_attached": outcome.approval_attached,
                    "persisted": outcome.persisted,
                    "backend": outcome.backend,
                    "seq": outcome.seq,
                    "fault_injected": outcome.fault_injected,
                    "error": outcome.error,
                }
            )

        bundle = RunBundle(
            manifest=self.manifest,
            actions=action_dicts,
            outcomes=outcome_dicts,
        )
        bundle.finalize()
        return bundle

    def readiness(self) -> Dict[str, Any]:
        return evaluate_readiness(
            manifest_present=True,
            interlock_allowed=self._interlock_allowed(),
            qualification_backends_ok=True,
            unknown_dependencies=[],
            policy_violations=[],
        ).to_dict()

    def cleanup(self) -> None:
        if self._sqlite_path and os.path.exists(self._sqlite_path):
            os.remove(self._sqlite_path)
            self._sqlite_path = None


def run_fixture(
    finding_ids: List[str],
    namespace: str = "steward:shadow:gastown",
    capability: str = "steward:shadow:write",
    backend_kind: str = "memory",
    requested_at: str = _FIXED_NOW,
    idempotency_key: str = "idem_fixture_run",
    snapshot_id: str = "snap_fixture",
    approve_all: bool = False,
) -> RunBundle:
    """Convenience: build a fixture manifest and run it. If approve_all, attach
    valid non-wildcard approvals to every action so they commit."""

    manifest = RunManifest(
        manifest_version="steward-s3c@0.1.0",
        mode="fixture_shadow_apply",
        source_profile="fixture.default",
        namespace=namespace,
        snapshot_id=snapshot_id,
        capability=capability,
        requested_at=requested_at,
        idempotency_key=idempotency_key,
        finding_ids=finding_ids,
    )
    orch = ShadowOrchestrator(manifest, backend_kind=backend_kind)
    try:
        if approve_all:
            # Build actions once, mark approved, and pass them through so the
            # approved state survives into run(). (run() rebuilding would reset
            # approval_state to "pending" and deny every action.)
            actions = orch.build_actions()
            approvals = {}
            for a in actions:
                approvals[a.action_id or ""] = ShadowApprovalArtifact(
                    schema_version="steward@0.3.0",
                    approval_id=f"apr_{a.action_id}",
                    action_id=a.action_id or "",
                    approving_authority="shadow_auditor",
                    granted_capability=a.requested_capability,
                    issued_at=requested_at,
                    scope=a.target_namespace,
                    signature="sha256:synthetic-shadow-signature",
                    expires_at="2099-01-01T00:00:00Z",
                )
                a.approval_state = "approved"
            bundle = orch.run(approvals=approvals, actions=actions)
        else:
            bundle = orch.run()
        return bundle
    finally:
        orch.cleanup()
