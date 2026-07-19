"""S3B backend-qualification adversarial test suite.

Local-only. Proves the QualificationAdapter and the two qualification backends
(memory, sqlite) honor the capability boundary, the approval boundary (incl.
revocation-after-write), fault injection, and crash recovery.

No live backend, no push, no Redis. sqlite3 is the only connector and only
inside sqlitedb.py (verified by test_no_live_connectors).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from steward.s3a_action import ProposedAction
from steward.s3a_writer import WriterCore, WriteOutcome
from steward.s3a_store import InMemoryStore
from steward.s3a_policy import ApprovalArtifact
from steward.s3b.protocol import (
    Approval,
    Capability,
    FaultKind,
    clear_registry,
    is_approval_live,
    revoke_approval,
)
from steward.s3b.adapter import (
    PersistReceipt,
    QualificationAdapter,
    build_memory_adapter,
    build_sqlite_adapter,
)
from steward.s3b.static import scan_path


def _make_action(action_id="act_abc",
                 cap="steward:redis_external:write",
                 namespace="steward:local") -> ProposedAction:
    return ProposedAction(
        schema_version="steward@0.3.0",
        action_type="redis_external_write",
        action_id=None,  # derived deterministically in __post_init__
        source_finding_id=f"find_{action_id}",
        source_snapshot_id="snap_1",
        target_namespace=namespace,
        requested_capability=cap,
        actor_id="operator",
        requested_at="2026-07-10T00:00:00Z",
        idempotency_key=f"idem_{action_id}",
        approval_state="none",
        normalized_payload={"title": "Gastown rebuild"},
    )


def _govern(action: ProposedAction, approval=None) -> WriteOutcome:
    store = InMemoryStore()
    writer = WriterCore(store)
    return writer.execute(action, "2026-07-10T00:00:00Z", approval=approval)


def _approval_for(action: ProposedAction, token="tok_1"):
    from steward.s3a_policy import S3A_SCHEMA_VERSION
    art = ApprovalArtifact(
        approval_id="apr_1",
        action_id=action.action_id,
        approving_authority="operator",
        granted_capability=action.requested_capability,
        issued_at="2026-07-10T00:00:00Z",
        scope=action.target_namespace,
        signature="local-only",
        schema_version=S3A_SCHEMA_VERSION,
        expires_at="2099-01-01T00:00:00Z",
    )
    ap = Approval(token=token, capability=action.requested_capability,
                  granted_for=action.target_namespace)
    return ap, art


class TestCapabilityBoundary(unittest.TestCase):
    def test_write_denied_when_capability_cannot_write(self):
        cap = Capability(name="readonly", can_write=False)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        outcome = _govern(action, approval=art)
        rec = adapter.persist(outcome)
        self.assertFalse(rec.persisted)
        self.assertIn("PermissionError", rec.error)

    def test_write_allowed_when_capability_can_write(self):
        cap = Capability(name="writer", can_write=True)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        outcome = _govern(action, approval=art)
        rec = adapter.persist(outcome)
        self.assertTrue(rec.persisted)
        self.assertEqual(rec.seq, 1)

    def test_delete_denied_when_capability_cannot_delete(self):
        cap = Capability(name="writer-nodelete", can_write=True, can_delete=False)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        with self.assertRaises(PermissionError):
            adapter.backend.delete("world:x")


class TestApprovalBoundary(unittest.TestCase):
    def setUp(self):
        clear_registry()

    def test_write_refused_without_approval(self):
        # S3A writer denies (no approval artifact) -> outcome is 'denied' ->
        # adapter never touches the backend at all.
        cap = Capability(name="writer", can_write=True, requires_approval=True)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        outcome = _govern(action)  # writer denies: require_approval, none supplied
        self.assertEqual(outcome.result.decision, "denied")
        rec = adapter.persist(outcome)
        self.assertFalse(rec.persisted)
        self.assertIn("denied", rec.error)

    def test_write_refused_when_approval_revoked(self):
        cap = Capability(name="writer", can_write=True, requires_approval=True)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        ap, art = _approval_for(action, "tok_rev")
        adapter.attach_approval(ap)
        self.assertTrue(is_approval_live("tok_rev"))
        rec1 = adapter.persist(_govern(action, approval=art))
        self.assertTrue(rec1.persisted)
        # Revoke AFTER the write was accepted.
        self.assertTrue(revoke_approval("tok_rev", "incident"))
        self.assertFalse(is_approval_live("tok_rev"))
        # A *new* write must now be refused.
        action2 = _make_action("act_new")
        ap2, art2 = _approval_for(action2, "tok_rev")
        adapter.attach_approval(ap2)
        rec2 = adapter.persist(_govern(action2, approval=art2))
        self.assertFalse(rec2.persisted)
        self.assertIn("revoked", rec2.error.lower())

    def test_revocation_does_not_alter_persisted_value(self):
        cap = Capability(name="writer", can_write=True, requires_approval=True)
        adapter = build_memory_adapter(cap)
        action = _make_action("act_keep")
        ap, art = _approval_for(action, "tok_keep")
        adapter.attach_approval(ap)
        rec = adapter.persist(_govern(action, approval=art))
        revoke_approval("tok_keep", "incident")
        # The value written under the now-revoked approval is still present.
        key = f"world:{rec.action_id}"
        self.assertIsNotNone(adapter.backend.get(key))


class TestFaultInjection(unittest.TestCase):
    def _adapter(self, fault: FaultKind, action_id="act_abc"):
        cap = Capability(name="writer", can_write=True)
        adapter = build_memory_adapter(cap)
        action = _make_action(action_id)
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        adapter.set_fault(fault)
        return adapter, action, art

    def test_write_fail_surfaces(self):
        adapter, action, art = self._adapter(FaultKind.WRITE_FAIL)
        rec = adapter.persist(_govern(action, approval=art))
        self.assertFalse(rec.persisted)
        self.assertIn("InjectedFault", rec.error)

    def test_connection_drop_surfaces_no_persist(self):
        adapter, action, art = self._adapter(FaultKind.CONNECTION_DROP)
        rec = adapter.persist(_govern(action, approval=art))
        self.assertFalse(rec.persisted)
        self.assertIn("InjectedFault", rec.error)

    def test_partial_write_drops_keys(self):
        cap = Capability(name="writer", can_write=True)
        adapter = build_memory_adapter(cap)
        adapter.set_fault(FaultKind.PARTIAL_WRITE)
        ok = 0
        for i in range(4):
            action = _make_action(f"act_{i}")
            ap, art = _approval_for(action)
            adapter.attach_approval(ap)
            rec = adapter.persist(_govern(action, approval=art))
            if rec.persisted:
                ok += 1
        # With drop-every-other, at most 2 of 4 persist.
        self.assertLessEqual(ok, 2)

    def test_corrupt_read_returns_modified_bytes(self):
        cap = Capability(name="writer", can_write=True)
        adapter = build_memory_adapter(cap)
        action = _make_action("act_c")
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        rec = adapter.persist(_govern(action, approval=art))
        adapter.set_fault(FaultKind.CORRUPT_READ)
        key = f"world:{rec.action_id}"
        val = adapter.backend.get(key)
        self.assertTrue(val.endswith(b"\x00CORRUPTED"))

    def test_denied_outcome_never_touches_backend(self):
        # A denied S3A outcome (no approval supplied to the writer) must not
        # reach a backend even though the adapter has write capability.
        cap = Capability(name="writer", can_write=True)
        adapter = build_memory_adapter(cap)
        action = _make_action()
        ap, _ = _approval_for(action)
        adapter.attach_approval(ap)
        outcome = _govern(action)  # writer denies (require_approval)
        self.assertEqual(outcome.result.decision, "denied")
        rec = adapter.persist(outcome)
        self.assertFalse(rec.persisted)
        self.assertIn("denied", rec.error)


class TestCrashRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="s3b_")
        self.db = os.path.join(self.tmp, "qual.db")

    def test_sqlite_value_survives_reopen(self):
        cap = Capability(name="writer", can_write=True, can_persist=True)
        adapter = build_sqlite_adapter(cap, self.db)
        action = _make_action("act_persist")
        ap, art = _approval_for(action)
        adapter.attach_approval(ap)
        rec = adapter.persist(_govern(action, approval=art))
        self.assertTrue(rec.persisted)
        # Simulate crash: drop connection + reopen. Value must remain.
        adapter.backend.reopen()
        key = f"world:{rec.action_id}"
        val = adapter.backend.get(key)
        self.assertIsNotNone(val)
        self.assertIn(b"committed", val)
        adapter.backend.close()

    def test_sqlite_committed_row_count_after_reopen(self):
        cap = Capability(name="writer", can_write=True, can_persist=True)
        adapter = build_sqlite_adapter(cap, self.db)
        keys = []
        for i in range(3):
            action = _make_action(f"act_r{i}")
            ap, art = _approval_for(action)
            adapter.attach_approval(ap)
            rec = adapter.persist(_govern(action, approval=art))
            keys.append(f"world:{rec.action_id}")
        adapter.backend.reopen()
        self.assertEqual(len(adapter.backend.list_keys("world:")), 3)
        adapter.backend.close()


class TestStaticNoLiveConnectors(unittest.TestCase):
    def test_no_live_connectors_in_s3b(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        s3b_dir = os.path.join(here, "steward", "s3b")
        violations, _notes = scan_path(s3b_dir)
        self.assertEqual(violations, [], f"live-connector violations: {violations}")


class TestNoLiveConnectorsWholeTree(unittest.TestCase):
    def test_s3b_tree_only_allows_sqlite_in_sqlitedb(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        s3b_dir = os.path.join(here, "steward", "s3b")
        violations, _notes = scan_path(s3b_dir)
        # Re-assert: sqlite3 must appear only in sqlitedb.py; nothing else.
        self.assertEqual(violations, [])


def tearDownModule():
    clear_registry()


if __name__ == "__main__":
    unittest.main()
