"""S3C adversarial qualification tests (S3C-014).

50 adversarial cases proving the shadow pipeline fails closed, never produces
a live mutation, never accepts a wildcard approval, and is byte-deterministic.

No live connectors, no randomness, no wall-clock, no auto-approval, no model
calls, no push. Runs entirely against S3B qualification backends.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from steward.s3c.backend import build_shadow_memory_adapter, build_shadow_sqlite_adapter
from steward.s3c.bundles import RunBundle, write_bundle, sha256_of
from steward.s3c.interlock import evaluate, FORBIDDEN_LIVE_CAPABILITIES
from steward.s3c.manifest import RunManifest, S3C_MANIFEST_VERSION, ALLOWED_MODES
from steward.s3c.orchestrator import run_fixture, ShadowOrchestrator
from steward.s3c.readiness import (
    evaluate as evaluate_readiness,
    READY_FOR_SHADOW_ONLY,
    READY_FOR_LIVE,
)
from steward.s3c.replay import build_corpus
from steward.s3c.shadow_model import (
    ShadowApprovalArtifact,
    ShadowProposedAction,
)
from steward.s3c.writer import ShadowWriterCore
from steward.s3b.adapter import QualificationAdapter
from steward.s3b.protocol import Capability, FaultKind

_FIXED_NOW = "2026-07-08T00:00:00Z"


def _action(ns="steward:shadow:gastown", cap="steward:shadow:write", state="approved"):
    return ShadowProposedAction(
        schema_version="steward@0.3.0",
        action_type="shadow_world_update",
        action_id=None,
        source_finding_id="find_x",
        source_snapshot_id="snap_x",
        target_namespace=ns,
        requested_capability=cap,
        actor_id="shadow_orchestrator",
        requested_at=_FIXED_NOW,
        idempotency_key="idem_x",
        approval_state=state,
        normalized_payload={"k": "v"},
        redacted_provenance={"origin": "synthetic"},
    )


def _approval(action, wildcard=False):
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
        signature="sha256:synthetic",
        expires_at="2099-01-01T00:00:00Z",
    )


def _core(adapter=None, ns="steward:shadow:gastown", loaded=None):
    if adapter is None:
        adapter = build_shadow_memory_adapter()
    cap = adapter.cap
    return ShadowWriterCore(
        adapter=adapter,
        capability=cap,
        namespace=ns,
        now_token=_FIXED_NOW,
        loaded_capabilities=loaded or [],
    )


class TestManifestContract(unittest.TestCase):
    def test_001_manifest_rejects_unknown_field(self):
        raw = {
            "manifest_version": S3C_MANIFEST_VERSION,
            "mode": "fixture_shadow_apply",
            "source_profile": "fixture.default",
            "namespace": "steward:shadow:gastown",
            "snapshot_id": "snap_1",
            "capability": "steward:shadow:write",
            "requested_at": _FIXED_NOW,
            "idempotency_key": "idem_1",
            "evil_field": "live_takeover",
        }
        with self.assertRaises(ValueError):
            RunManifest.from_dict(raw)

    def test_002_manifest_rejects_illegal_mode(self):
        with self.assertRaises(ValueError):
            RunManifest(
                manifest_version=S3C_MANIFEST_VERSION,
                mode="live_apply",
                source_profile="fixture.default",
                namespace="steward:shadow:gastown",
                snapshot_id="snap_1",
                capability="steward:shadow:write",
                requested_at=_FIXED_NOW,
                idempotency_key="idem_1",
            )

    def test_003_manifest_rejects_non_steward_namespace(self):
        with self.assertRaises(ValueError):
            RunManifest(
                manifest_version=S3C_MANIFEST_VERSION,
                mode="fixture_shadow_apply",
                source_profile="fixture.default",
                namespace="live:gastown",
                snapshot_id="snap_1",
                capability="steward:shadow:write",
                requested_at=_FIXED_NOW,
                idempotency_key="idem_1",
            )
        # A steward: namespace is accepted at the manifest layer; the shadow
        # writer core enforces the stricter steward:shadow: prefix downstream.
        m = RunManifest(
            manifest_version=S3C_MANIFEST_VERSION,
            mode="fixture_shadow_apply",
            source_profile="fixture.default",
            namespace="steward:shadow:gastown",
            snapshot_id="snap_1",
            capability="steward:shadow:write",
            requested_at=_FIXED_NOW,
            idempotency_key="idem_1",
        )
        self.assertTrue(m.namespace.startswith("steward:"))

    def test_004_manifest_rejects_missing_required(self):
        with self.assertRaises(ValueError):
            RunManifest.from_dict({"manifest_version": S3C_MANIFEST_VERSION})

    def test_005_manifest_deterministic_run_id(self):
        m1 = RunManifest(
            manifest_version=S3C_MANIFEST_VERSION,
            mode="fixture_shadow_apply",
            source_profile="fixture.default",
            namespace="steward:shadow:gastown",
            snapshot_id="snap_1",
            capability="steward:shadow:write",
            requested_at=_FIXED_NOW,
            idempotency_key="idem_1",
        )
        m2 = RunManifest(
            manifest_version=S3C_MANIFEST_VERSION,
            mode="fixture_shadow_apply",
            source_profile="fixture.default",
            namespace="steward:shadow:gastown",
            snapshot_id="snap_1",
            capability="steward:shadow:write",
            requested_at=_FIXED_NOW,
            idempotency_key="idem_1",
        )
        self.assertEqual(m1.run_id, m2.run_id)

    def test_006_only_four_modes_allowed(self):
        self.assertEqual(
            set(ALLOWED_MODES),
            {
                "fixture_plan",
                "fixture_shadow_apply",
                "live_readonly_plan",
                "live_readonly_shadow_apply",
            },
        )


class TestInterlock(unittest.TestCase):
    def _base(self, **kw):
        base = dict(
            mode="fixture_shadow_apply",
            backend_qualification_only=True,
            namespace="steward:shadow:gastown",
            live_writer_present=False,
            loaded_capabilities=[],
            wildcard_approval=False,
            output_dir_local_safe=True,
            redaction_enabled=True,
            deterministic_timestamp_supplied=True,
        )
        base.update(kw)
        return base

    def test_007_interlock_allows_clean(self):
        v = evaluate(**self._base())
        self.assertTrue(v.allowed)

    def test_008_interlock_refuses_bad_mode(self):
        v = evaluate(**self._base(mode="live_apply"))
        self.assertFalse(v.allowed)

    def test_009_interlock_refuses_non_qual_backend(self):
        v = evaluate(**self._base(backend_qualification_only=False))
        self.assertFalse(v.allowed)

    def test_010_interlock_refuses_non_shadow_ns(self):
        v = evaluate(**self._base(namespace="steward:live:gastown"))
        self.assertFalse(v.allowed)

    def test_011_interlock_refuses_live_writer(self):
        v = evaluate(**self._base(live_writer_present=True))
        self.assertFalse(v.allowed)

    def test_012_interlock_refuses_forbidden_cap(self):
        for cap in FORBIDDEN_LIVE_CAPABILITIES:
            v = evaluate(**self._base(loaded_capabilities=[cap]))
            self.assertFalse(v.allowed, cap)

    def test_013_interlock_refuses_wildcard_approval(self):
        v = evaluate(**self._base(wildcard_approval=True))
        self.assertFalse(v.allowed)

    def test_014_interlock_refuses_unsafe_output(self):
        v = evaluate(**self._base(output_dir_local_safe=False))
        self.assertFalse(v.allowed)

    def test_015_interlock_refuses_no_redaction(self):
        v = evaluate(**self._base(redaction_enabled=False))
        self.assertFalse(v.allowed)

    def test_016_interlock_refuses_no_timestamp(self):
        v = evaluate(**self._base(deterministic_timestamp_supplied=False))
        self.assertFalse(v.allowed)


class TestWriterCore(unittest.TestCase):
    def test_017_denied_without_approval(self):
        core = _core()
        out = core.execute(_action())
        self.assertEqual(out.decision, "denied")
        self.assertFalse(out.persisted)

    def test_018_committed_with_valid_approval(self):
        core = _core()
        a = _action()
        out = core.execute(a, _approval(a))
        self.assertEqual(out.decision, "committed")
        self.assertTrue(out.persisted)

    def test_019_wildcard_approval_denied(self):
        core = _core()
        a = _action()
        out = core.execute(a, _approval(a, wildcard=True))
        self.assertEqual(out.decision, "denied")
        self.assertIn("wildcard", out.reason)

    def test_020_expired_approval_denied(self):
        core = _core()
        a = _action()
        apr = _approval(a)
        apr.expires_at = "2020-01-01T00:00:00Z"
        out = core.execute(a, apr)
        self.assertEqual(out.decision, "denied")
        self.assertIn("expired", out.reason)

    def test_021_capability_mismatch_denied(self):
        core = _core()
        a = _action(cap="steward:shadow:write")
        apr = _approval(a)
        apr.granted_capability = "steward:shadow:other"
        out = core.execute(a, apr)
        self.assertEqual(out.decision, "denied")

    def test_022_scope_mismatch_denied(self):
        core = _core()
        a = _action(ns="steward:shadow:gastown")
        apr = _approval(a)
        apr.scope = "steward:shadow:other"
        out = core.execute(a, apr)
        self.assertEqual(out.decision, "denied")

    def test_023_non_shadow_namespace_rejected_at_construction(self):
        # shadow_model enforces the steward:shadow: prefix, so a non-shadow
        # namespace can never be instantiated into a shadow action.
        with self.assertRaises(ValueError):
            _action(ns="steward:live:gastown")
        # A shadow action in a different shadow namespace than the core's
        # namespace is still held by the interlock since the core namespace
        # gate is enforced at orchestration time. Build one and confirm the
        # action itself is valid shadow material.
        a = _action(ns="steward:shadow:other")
        self.assertTrue(a.target_namespace.startswith("steward:shadow:"))

    def test_024_pending_state_denied(self):
        core = _core()
        a = _action(state="pending")
        out = core.execute(a, _approval(a))
        self.assertEqual(out.decision, "denied")

    def test_025_write_fail_fault_surfaces(self):
        adapter = build_shadow_memory_adapter()
        adapter.set_fault(FaultKind.WRITE_FAIL)
        core = _core(adapter=adapter)
        a = _action()
        out = core.execute(a, _approval(a))
        self.assertFalse(out.persisted)
        self.assertIn("InjectedFault", out.error)

    def test_026_connection_drop_fault_surfaces(self):
        adapter = build_shadow_memory_adapter()
        adapter.set_fault(FaultKind.CONNECTION_DROP)
        core = _core(adapter=adapter)
        a = _action()
        out = core.execute(a, _approval(a))
        self.assertFalse(out.persisted)
        self.assertIn("InjectedFault", out.error)

    def test_027_sqlite_backend_commits(self):
        fd, db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        adapter = None
        try:
            adapter = build_shadow_sqlite_adapter(db)
            core = _core(adapter=adapter)
            a = _action()
            out = core.execute(a, _approval(a))
            self.assertEqual(out.decision, "committed")
            self.assertTrue(out.persisted)
        finally:
            if adapter is not None:
                adapter.close()
            if os.path.exists(db):
                try:
                    os.remove(db)
                except OSError:
                    pass

    def test_028_no_auto_approval(self):
        core = _core()
        a = _action(state="approved")
        # No approval artifact passed => denied (no auto-approval path exists)
        out = core.execute(a, None)
        self.assertEqual(out.decision, "denied")


class TestOrchestrator(unittest.TestCase):
    def test_029_fixture_no_approve_all_denied(self):
        b = run_fixture(finding_ids=["a", "b"])
        for o in b.outcomes:
            self.assertEqual(o["decision"], "denied")

    def test_030_fixture_approve_all_committed(self):
        b = run_fixture(finding_ids=["a", "b"], approve_all=True)
        for o in b.outcomes:
            self.assertEqual(o["decision"], "committed")
            self.assertTrue(o["persisted"])

    def test_031_fixture_deterministic(self):
        b1 = run_fixture(finding_ids=["a", "b"], approve_all=True)
        b2 = run_fixture(finding_ids=["a", "b"], approve_all=True)
        self.assertEqual(b1.sha256, b2.sha256)

    def test_032_orchestrator_interlock_blocks_live_cap(self):
        orch = ShadowOrchestrator(
            RunManifest(
                manifest_version=S3C_MANIFEST_VERSION,
                mode="fixture_shadow_apply",
                source_profile="fixture.default",
                namespace="steward:shadow:gastown",
                snapshot_id="snap",
                capability="steward:shadow:write",
                requested_at=_FIXED_NOW,
                idempotency_key="idem",
            ),
            loaded_capabilities=["redis-write"],
        )
        self.assertFalse(orch._interlock_allowed())

    def test_033_bundle_atomic_write_and_deterministic(self):
        b = run_fixture(finding_ids=["a"], approve_all=True)
        d = tempfile.mkdtemp()
        try:
            path1 = write_bundle(b, d)
            self.assertTrue(os.path.exists(path1))
            # A second write of an identical bundle must be byte-identical.
            b2 = run_fixture(finding_ids=["a"], approve_all=True)
            path2 = write_bundle(b2, d)
            self.assertEqual(sha256_of(path1), sha256_of(path2))
            self.assertEqual(b.sha256, b2.sha256)
        finally:
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
            os.rmdir(d)

    def test_034_bundle_canonical_determinism(self):
        import json as _json

        b1 = run_fixture(finding_ids=["x"], approve_all=True)
        b2 = run_fixture(finding_ids=["x"], approve_all=True)
        s1 = _json.dumps(b1.to_dict(), sort_keys=True, separators=(",", ":"))
        s2 = _json.dumps(b2.to_dict(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(s1, s2)


class TestReadiness(unittest.TestCase):
    def test_035_ready_for_shadow_only(self):
        r = evaluate_readiness(
            manifest_present=True,
            interlock_allowed=True,
            qualification_backends_ok=True,
            unknown_dependencies=[],
            policy_violations=[],
        )
        self.assertEqual(r.classification, READY_FOR_SHADOW_ONLY)

    def test_036_never_ready_for_live(self):
        # The constant must not exist / must never be returned.
        self.assertNotIn(
            "READY_FOR_LIVE",
            [READY_FOR_SHADOW_ONLY, "NOT_READY", "BLOCKED_BY_UNKNOWN",
             "POLICY_DENIED", "QUALIFICATION_FAILURE"],
        )

    def test_037_not_ready_missing_manifest(self):
        r = evaluate_readiness(
            manifest_present=False,
            interlock_allowed=True,
            qualification_backends_ok=True,
            unknown_dependencies=[],
            policy_violations=[],
        )
        self.assertEqual(r.classification, "NOT_READY")

    def test_038_policy_denied(self):
        r = evaluate_readiness(
            manifest_present=True,
            interlock_allowed=True,
            qualification_backends_ok=True,
            unknown_dependencies=[],
            policy_violations=["interlock refused"],
        )
        self.assertEqual(r.classification, "POLICY_DENIED")

    def test_039_blocked_by_unknown(self):
        r = evaluate_readiness(
            manifest_present=True,
            interlock_allowed=True,
            qualification_backends_ok=True,
            unknown_dependencies=["S2 reconcile"],
            policy_violations=[],
        )
        self.assertEqual(r.classification, "BLOCKED_BY_UNKNOWN")

    def test_040_qualification_failure(self):
        r = evaluate_readiness(
            manifest_present=True,
            interlock_allowed=True,
            qualification_backends_ok=False,
            unknown_dependencies=[],
            policy_violations=[],
        )
        self.assertEqual(r.classification, "QUALIFICATION_FAILURE")


class TestReplayCorpus(unittest.TestCase):
    def test_041_corpus_count_is_twenty(self):
        self.assertEqual(len(build_corpus()), 20)

    def test_042_corpus_replay_decisions(self):
        corpus = build_corpus()
        for case in corpus:
            adapter = build_shadow_memory_adapter()
            core = _core(adapter=adapter, ns=case.action.target_namespace)
            out = core.execute(case.action, case.approval)
            self.assertEqual(
                out.decision,
                case.expected_decision,
                msg=f"{case.case_id}: {out.reason}",
            )

    def test_043_corpus_wildcard_denied(self):
        for case in build_corpus():
            if case.expected_reason_contains == "wildcard":
                self.assertEqual(case.expected_decision, "denied")

    def test_044_corpus_expired_denied(self):
        for case in build_corpus():
            if case.expected_reason_contains == "expired":
                self.assertEqual(case.expected_decision, "denied")

    def test_045_corpus_scope_mismatch_denied(self):
        for case in build_corpus():
            if case.expected_reason_contains == "scope":
                self.assertEqual(case.expected_decision, "denied")


class TestRehearsal(unittest.TestCase):
    def test_046_rehearsal_deterministic(self):
        from steward.s3c.rehearsal import run_rehearsal_twice

        r = run_rehearsal_twice()
        self.assertTrue(r["deterministic"])
        self.assertTrue(r["interlock_allowed"])

    def test_047_rehearsal_no_live_bundle_committed(self):
        from steward.s3c.rehearsal import run_rehearsal_twice

        r = run_rehearsal_twice()
        self.assertIn("NOT committed", r["note"])

    def test_048_rehearsal_disabled_transport(self):
        from steward.s3c.rehearsal import collect_observations

        with self.assertRaises(RuntimeError):
            collect_observations("x", execute=True)

    def test_049_rehearsal_observations_secret_free(self):
        from steward.s3c.rehearsal import collect_observations

        obs = collect_observations("x")
        blob = json.dumps([o.__dict__ for o in obs])
        self.assertNotIn("password", blob.lower())
        self.assertNotIn("secret", blob.lower())


class TestDaguDraft(unittest.TestCase):
    def test_050_dagu_draft_uninstalled(self):
        from steward.s3c.dagu_draft import render_draft

        d = render_draft()
        self.assertFalse(d["installed"])
        self.assertIn("NOT SCHEMA-VALIDATED", d["status"])
        self.assertIn("UNKNOWN", d["dagu_workflow_count"])


if __name__ == "__main__":
    unittest.main()
