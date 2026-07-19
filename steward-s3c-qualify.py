#!/usr/bin/env python3
"""Steward S3C shadow qualification harness (VERIFY-ONLY, shadow-only).

Runs the COMPLETE synthetic S3C replay corpus and proves the shadow pipeline
against the in-process qualification backend. It NEVER touches live Federation,
Redis, Postgres, SSH, Docker socket, NPC inbox, cognition, or credentials.

Every check fails the whole run (non-zero exit) if it does not hold. The
canonical output (a JSON report) is hashed (SHA-256) and printed so the Dagu
workflow step can capture it.

Forbidden by construction: no network, no live connectors. Only the local
S3B qualification backends (memory + temp SQLite) are used.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

# Make the steward package importable regardless of CWD.
sys.path.insert(0, "/opt/steward")

from steward.s3c.orchestrator import ShadowOrchestrator, run_fixture  # noqa: E402
from steward.s3c.replay import build_corpus  # noqa: E402
from steward.s3c.writer import ShadowWriterCore  # noqa: E402
from steward.s3c.interlock import evaluate as interlock_evaluate  # noqa: E402
from steward.s3c.readiness import evaluate as readiness_evaluate, READY_FOR_LIVE  # noqa: E402
from steward.s3c.backend import (  # noqa: E402
    build_shadow_memory_adapter,
    build_shadow_sqlite_adapter,
)
from steward.s3c.shadow_model import (  # noqa: E402
    ShadowProposedAction,
    ShadowApprovalArtifact,
)
from steward.s3c.bundles import RunBundle, sha256_of, write_bundle  # noqa: E402
from steward.s3c.manifest import RunManifest  # noqa: E402
from steward.redact import redact_value  # noqa: E402
from steward.s3b.protocol import (  # noqa: E402
    Capability,
    Approval,
    FaultKind,
)

NS = "steward:shadow:gastown"
NOW = "2026-07-08T00:00:00Z"
CHECKS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(cond), detail))
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" :: {detail}" if detail else ""), flush=True)
    if not cond:
        raise AssertionError(f"CHECK FAILED: {name} :: {detail}")


def _approval_for(action: ShadowProposedAction) -> ShadowApprovalArtifact:
    # The writer requires approval.action_id == action.action_id exactly
    # (None must match None), and the granted capability must match the
    # requested capability. Mirror both precisely.
    return ShadowApprovalArtifact(
        schema_version="steward@0.3.0",
        approval_id=f"apr_{action.action_id}",
        action_id=action.action_id,
        approving_authority="shadow_auditor",
        granted_capability=action.requested_capability,
        issued_at=NOW,
        scope=action.target_namespace,
        signature="sha256:synthetic-shadow-signature",
        expires_at="2099-01-01T00:00:00Z",
    )


def replay_corpus() -> None:
    """Requirement 1-3: run full synthetic replay corpus; approved->committed,
    denied paths->denied (capability denial + approval-gated behavior)."""
    corpus = build_corpus()
    check("replay_corpus_present", len(corpus) == 20, f"{len(corpus)} cases")

    committed = 0
    denied = 0
    for case in corpus:
        adapter = build_shadow_memory_adapter()
        core = ShadowWriterCore(
            adapter=adapter,
            capability=adapter.cap,
            namespace=case.action.target_namespace,
            now_token=NOW,
            loaded_capabilities=[],
        )
        outcome = core.execute(case.action, case.approval)
        ok = outcome.decision == case.expected_decision
        if outcome.decision == "committed":
            committed += 1
        else:
            denied += 1
        check(
            f"replay:{case.case_id}",
            ok,
            f"expected={case.expected_decision} got={outcome.decision} reason={outcome.reason}",
        )
    check("replay_committed_count", committed == 10, f"{committed} committed")
    check("replay_denied_count", denied == 10, f"{denied} denied")


def capability_denials() -> None:
    """Requirement 3 (explicit): forbidden-live capability load must fail closed."""
    verdict = interlock_evaluate(
        mode="fixture_shadow_apply",
        backend_qualification_only=True,
        namespace=NS,
        live_writer_present=False,
        loaded_capabilities=["redis-write", "docker-mutation"],
        wildcard_approval=False,
        output_dir_local_safe=True,
        redaction_enabled=True,
        deterministic_timestamp_supplied=True,
    )
    check("interlock_refuses_forbidden_capability", not verdict.allowed, verdict.reason)


def idempotent_replay() -> None:
    """Requirement 4: replaying an already-persisted action re-asserts, no dup."""
    adapter = build_shadow_memory_adapter()
    action = ShadowProposedAction(
        schema_version="steward@0.3.0",
        action_type="shadow_world_update",
        action_id=None,
        source_finding_id="find_idem",
        source_snapshot_id="snap_idem",
        target_namespace=NS,
        requested_capability="steward:shadow:write",
        actor_id="shadow_orchestrator",
        requested_at=NOW,
        idempotency_key="idem_once",
        approval_state="approved",
        normalized_payload={"kind": "shadow"},
        redacted_provenance={"origin": "synthetic"},
    )
    approval = _approval_for(action)
    core = ShadowWriterCore(
        adapter=adapter,
        capability=adapter.cap,
        namespace=NS,
        now_token=NOW,
    )
    o1 = core.execute(action, approval)
    keys_after_first = set(adapter.backend._store.keys())
    # Re-execute the SAME action (idempotent replay).
    o2 = core.execute(action, approval)
    keys_after_second = set(adapter.backend._store.keys())
    check("idempotent_first_committed", o1.decision == "committed", o1.reason)
    check(
        "idempotent_no_duplicate_key",
        keys_after_first == keys_after_second,
        f"first={len(keys_after_first)} second={len(keys_after_second)}",
    )


def transaction_rollback() -> None:
    """Requirement 5: injected fault => write NOT persisted (local rollback)."""
    # Memory backend, WRITE_FAIL fault.
    adapter = build_shadow_memory_adapter()
    adapter.set_fault(FaultKind.WRITE_FAIL)
    action = ShadowProposedAction(
        schema_version="steward@0.3.0",
        action_type="shadow_world_update",
        action_id=None,
        source_finding_id="find_fault",
        source_snapshot_id="snap_fault",
        target_namespace=NS,
        requested_capability="steward:shadow:write",
        actor_id="shadow_orchestrator",
        requested_at=NOW,
        idempotency_key="idem_fault",
        approval_state="approved",
        normalized_payload={"kind": "shadow"},
        redacted_provenance={"origin": "synthetic"},
    )
    approval = _approval_for(action)
    core = ShadowWriterCore(
        adapter=adapter,
        capability=adapter.cap,
        namespace=NS,
        now_token=NOW,
    )
    outcome = core.execute(action, approval)
    check("fault_write_not_persisted", not outcome.persisted, outcome.reason)
    check("fault_backend_untouched", len(adapter.backend._store) == 0,
          f"store size={len(adapter.backend._store)}")

    # SQLite backend: CONNECTION_DROP before commit must not survive reopen.
    fd, db_path = tempfile.mkstemp(prefix="s3c_qual_", suffix=".sqlite")
    os.close(fd)
    try:
        sadapter = build_shadow_sqlite_adapter(db_path)
        sadapter.set_fault(FaultKind.CONNECTION_DROP)
        saction = ShadowProposedAction(
            schema_version="steward@0.3.0",
            action_type="shadow_world_update",
            action_id=None,
            source_finding_id="find_sqlfault",
            source_snapshot_id="snap_sqlfault",
            target_namespace=NS,
            requested_capability="steward:shadow:write",
            actor_id="shadow_orchestrator",
            requested_at=NOW,
            idempotency_key="idem_sqlfault",
            approval_state="approved",
            normalized_payload={"kind": "shadow"},
            redacted_provenance={"origin": "synthetic"},
        )
        sapproval = _approval_for(saction)
        score = ShadowWriterCore(
            adapter=sadapter,
            capability=sadapter.cap,
            namespace=NS,
            now_token=NOW,
        )
        sout = score.execute(saction, sapproval)
        sadapter.close()
        # Reopen and confirm nothing durable landed.
        sadapter2 = build_shadow_sqlite_adapter(db_path)
        survived = sadapter2.backend.list_keys("world:")
        check("sqlite_drop_not_persisted", len(survived) == 0,
              f"survived keys={survived}")
        sadapter2.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def nested_secret_redaction() -> None:
    """Requirement 6: nested secret redaction via the real redact module."""
    payload = {
        "user": "alice",
        "config": {
            "password": "hunter2secret",
            "token": "Bearer abc123.DEF.ghi",
            "nested": {"api_key": "sk-1234567890abcdefghij", "ok": 1},
        },
        "connection_string": "postgres://u:p@db:5432/x",
    }
    redacted = redact_value(payload)
    blob = json.dumps(redacted)
    check("redact_password", "hunter2secret" not in blob)
    check("redact_bearer", "abc123.DEF.ghi" not in blob)
    check("redact_sk", "sk-1234567890abcdefghij" not in blob)
    check("redact_pg_conn", "p@db:5432" not in blob)


def path_traversal_rejection() -> None:
    """Requirement 7: shadow backend refuses non-shadow keys; simulated symlink
    / reparse style paths are rejected by the namespace guard + model."""
    from steward.s3c.backend import ShadowNamespaceGuard

    rejected = False
    try:
        ShadowNamespaceGuard.check("../../etc/passwd")
    except ValueError:
        rejected = True
    check("guard_refuses_traversal", rejected)

    # A shadow action with a traversal-style namespace must be refused by the
    # shadow model __post_init__.
    model_rejected = False
    try:
        ShadowProposedAction(
            schema_version="steward@0.3.0",
            action_type="shadow_world_update",
            action_id=None,
            source_finding_id="find_trav",
            source_snapshot_id="snap_trav",
            target_namespace="steward:shadow:../escape",
            requested_capability="steward:shadow:write",
            actor_id="shadow_orchestrator",
            requested_at=NOW,
            idempotency_key="idem_trav",
            approval_state="approved",
            normalized_payload={},
            redacted_provenance={},
        )
    except ValueError:
        model_rejected = True
    check("model_refuses_traversal_namespace", model_rejected)

    # Simulated symlink/reparse: Windows-style traversal segment inside a
    # key is rejected by the namespace guard (no symlink/reparse escape).
    sym_rejected = False
    try:
        ShadowNamespaceGuard.check("..\\..\\win")
    except ValueError:
        sym_rejected = True
    check("guard_refuses_symlink_reparse_segment", sym_rejected)


def cross_process_determinism() -> None:
    """Requirement 8-9: run fixture under two PYTHONHASHSEED values; compare
    canonical output hashes."""
    import subprocess

    def run_with_seed(seed: str) -> str:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys,json; sys.path.insert(0,'/opt/steward');"
             "from steward.s3c.orchestrator import run_fixture;"
             "b=run_fixture(finding_ids=['find_1','find_2','find_3'],"
             "namespace='steward:shadow:gastown',backend_kind='memory');"
             "print(json.dumps(b.to_dict(),sort_keys=True,separators=(',',':')))"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr)
        return out.stdout.strip()

    h1 = hashlib.sha256(run_with_seed("0").encode()).hexdigest()
    h2 = hashlib.sha256(run_with_seed("1").encode()).hexdigest()
    check("determinism_seed0_vs_seed1", h1 == h2, f"h0={h1[:12]} h1={h2[:12]}")
    return h1


def main() -> int:
    print("=== S3C SHADOW QUALIFICATION (VERIFY-ONLY) ===", flush=True)
    replay_corpus()
    capability_denials()
    idempotent_replay()
    transaction_rollback()
    nested_secret_redaction()
    path_traversal_rejection()
    canonical_hash = cross_process_determinism()

    # Requirement 10-11: readiness must be READY_FOR_SHADOW_ONLY, never LIVE.
    report = readiness_evaluate(
        manifest_present=True,
        interlock_allowed=True,
        qualification_backends_ok=True,
        unknown_dependencies=[],
        policy_violations=[],
    )
    check("readiness_shadow_only",
          report.classification == "READY_FOR_SHADOW_ONLY",
          report.classification)
    check("readiness_never_live",
          READY_FOR_LIVE not in (report.classification +
                                 json.dumps(report.evidence)),
          "live_readiness_token_absent")

    # Requirement 12: cleanup temp bundles / sqlite (harness is self-cleaning;
    # assert no stray s3c temp files remain in /tmp). The harness's own result
    # artifact lives under the DAGs dir (owned by the Dagu runtime user) and is
    # excluded from the stray scan.
    import glob
    RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "steward_qual_result.sha256")
    strays = [p for p in glob.glob("/tmp/s3c_*") if os.path.exists(p)]
    check("no_stray_temp_files", len(strays) == 0, f"strays={strays}")

    summary = {
        "classification": report.classification,
        "checks_total": len(CHECKS),
        "checks_passed": sum(1 for _, ok, _ in CHECKS if ok),
        "canonical_fixture_hash_sha256": canonical_hash,
        "all_passed": all(ok for _, ok, _ in CHECKS),
    }
    out_json = json.dumps(summary, sort_keys=True, indent=2)
    summary_hash = hashlib.sha256(out_json.encode()).hexdigest()
    print("=== QUALIFICATION SUMMARY ===", flush=True)
    print(out_json, flush=True)
    print(f"OUTPUT_SHA256={summary_hash}", flush=True)
    # Expose for the Dagu step's output capture. Written into the DAGs dir
    # (owned by the Dagu runtime user), not under /tmp/s3c_*. Includes the
    # classification string so the assert step can verify READY_FOR_SHADOW_ONLY.
    with open(RESULT_FILE, "w") as fh:
        fh.write(summary_hash + "\n")
        fh.write("CLASSIFICATION=" + report.classification + "\n")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
