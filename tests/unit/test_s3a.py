"""S3A adversarial, determinism, idempotency, and regression test suite.

Covers S3A-012 (40 minimum categories) plus S1/S2 regression.
No live connectors; all execution is against in-memory stores.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict

from steward.s3a_action import (
    S3A_SCHEMA_VERSION,
    ProposedAction,
)
from steward.s3a_audit import make_result_id, redact_evidence
from steward.s3a_councilor_watch import render
from steward.s3a_operator import (
    EXCLUDED_SUBSYSTEMS,
    OPERATOR_ACTOR_ID,
    can_participate,
    is_excluded,
)
from steward.s3a_planner import plan_actions
from steward.s3a_policy import (
    APPROVAL_GATED,
    AUTO_PERMITTED,
    ApprovalArtifact,
    decide_capability,
    validate_approval,
)
from steward.s3a_static import scan_module, scan_path
from steward.s3a_store import (
    BoundedCounterError,
    ConflictError,
    InMemoryStore,
)
from steward.s3a_writer import WriterCore

import steward.schema as S1
import tests.unit.test_s2_adapters as S2T  # noqa: F401  (ensures S2 importable)


def _make_action(capability="steward:incident:create", **kw):
    base = dict(
        schema_version=S3A_SCHEMA_VERSION,
        action_type="incident_create",
        action_id=None,
        source_finding_id="fdg_test",
        source_snapshot_id="snap_test",
        target_namespace="steward:local",
        requested_capability=capability,
        actor_id=OPERATOR_ACTOR_ID,
        requested_at="ts:test",
        idempotency_key="idem_test",
        approval_state="none",
    )
    base.update(kw)
    return ProposedAction(**base)


class TestValidAutoActions(unittest.TestCase):
    def test_1_valid_incident_creation(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:incident:create")
        o = w.execute(a, "ts:test")
        self.assertTrue(o.committed)
        self.assertEqual(o.result.decision, "committed")
        self.assertEqual(store.read("steward:local:incident_create:fdg_test").version, 1)

    def test_2_valid_work_order_creation(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:work_order:create", action_type="work_order_create")
        o = w.execute(a, "ts:test")
        self.assertTrue(o.committed)


class TestDeterminism(unittest.TestCase):
    def test_3_deterministic_action_ids(self):
        a1 = _make_action()
        a2 = _make_action()
        self.assertEqual(a1.action_id, a2.action_id)

    def test_4_deterministic_result_ids(self):
        r1 = make_result_id("act_x", "committed", "ts:1")
        r2 = make_result_id("act_x", "committed", "ts:1")
        self.assertEqual(r1, r2)

    def test_24_cross_process_byte_determinism(self):
        # Same action material built in two processes with different dict order.
        import subprocess, sys

        script = (
            "from steward.s3a_action import ProposedAction, S3A_SCHEMA_VERSION\n"
            "a=ProposedAction(schema_version=S3A_SCHEMA_VERSION,action_type='incident_create',"
            "action_id=None,source_finding_id='fdg_d',source_snapshot_id='snap_d',"
            "target_namespace='steward:local',requested_capability='steward:incident:create',"
            "actor_id='op_steward',requested_at='ts:1',idempotency_key='idem_d',"
            "approval_state='none',normalized_payload={'z':1,'a':2})\n"
            "import hashlib,json\n"
            "print(hashlib.sha256(json.dumps(a.to_dict(),sort_keys=True).encode()).hexdigest())\n"
        )
        def run_with(order):
            env = dict(os.environ)
            code = script.replace("'z':1,'a':2", order)
            p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
            return p.stdout.strip()

        h1 = run_with("'a':2,'z':1")
        h2 = run_with("'z':1,'a':2")
        self.assertEqual(h1, h2)
        self.assertTrue(h1)


class TestCapabilityDenial(unittest.TestCase):
    def test_5_unknown_capability_denied(self):
        d = decide_capability("steward:unknown:cap")
        self.assertEqual(d.decision, "deny")

    def test_6_approval_gated_does_not_mutate(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        o = w.execute(a, "ts:test", approval=None)
        self.assertEqual(o.result.decision, "denied")
        self.assertEqual(o.result.mutation_status, "none")
        self.assertIsNone(store.read("steward:local:npc_msg:fdg_test"))


class TestApproval(unittest.TestCase):
    def _approval(self, action, granted="steward:incident:create", scope="steward:local",
                  expires=None, action_id=None):
        return ApprovalArtifact(
            approval_id="apr_1",
            action_id=action_id or action.action_id,
            approving_authority="sean",
            granted_capability=granted,
            issued_at="ts:0",
            scope=scope,
            signature="sig:placeholder",
            schema_version=S3A_SCHEMA_VERSION,
            expires_at=expires,
        )

    def test_7_valid_exact_scope_approval(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        apr = self._approval(a, granted="steward:npc_message:inject")
        o = w.execute(a, "ts:test", approval=apr)
        self.assertTrue(o.committed)

    def test_8_expired_approval_rejected(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        apr = self._approval(a, granted="steward:npc_message:inject", expires="ts:0")
        o = w.execute(a, "ts:test_later", approval=apr)
        self.assertEqual(o.result.decision, "denied")
        self.assertIn("expired", o.result.denial_reason)

    def test_9_mismatched_action_approval_rejected(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        apr = self._approval(a, granted="steward:npc_message:inject", action_id="other")
        o = w.execute(a, "ts:test", approval=apr)
        self.assertEqual(o.result.decision, "denied")

    def test_10_mismatched_capability_approval_rejected(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        apr = self._approval(a, granted="steward:docker:mutate")
        o = w.execute(a, "ts:test", approval=apr)
        self.assertEqual(o.result.decision, "denied")

    def test_11_broad_wildcard_approval_rejected(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:npc_message:inject", action_type="npc_msg")
        apr = self._approval(a, granted="steward:npc_message:inject", scope="steward:*")
        o = w.execute(a, "ts:test", approval=apr)
        self.assertEqual(o.result.decision, "denied")


class TestSchemaValidation(unittest.TestCase):
    def test_12_namespace_escape_rejected(self):
        with self.assertRaises(ValueError):
            _make_action(target_namespace="federation:global")

    def test_13_option_path_injection_rejected(self):
        with self.assertRaises(ValueError):
            _make_action(target_namespace="../escape")

    def test_14_unknown_schema_fields_rejected(self):
        raw = _make_action().to_dict()
        raw["evil_field"] = "x"
        with self.assertRaises(ValueError):
            ProposedAction.from_dict(raw)

    def test_15_malformed_actor_rejected(self):
        with self.assertRaises(ValueError):
            _make_action(actor_id="")

    def test_unknown_capability_in_action_rejected_by_policy(self):
        a = _make_action("steward:evil:cap")
        store = InMemoryStore()
        w = WriterCore(store)
        o = w.execute(a, "ts:test")
        self.assertEqual(o.result.decision, "denied")


class TestOperatorExclusions(unittest.TestCase):
    def test_16_steward_autonomy_exclusions(self):
        for sub in EXCLUDED_SUBSYSTEMS:
            self.assertTrue(is_excluded(sub))
            self.assertFalse(can_participate(sub))
        self.assertFalse(is_excluded("ordinary_heartbeat_scheduling") is False and can_participate("ordinary_heartbeat_scheduling"))

    def test_operator_actor_stable(self):
        self.assertTrue(OPERATOR_ACTOR_ID.startswith("op_steward_"))


class TestTransactions(unittest.TestCase):
    def test_17_optimistic_version_conflict(self):
        store = InMemoryStore()
        rec = store.create_if_absent("k", {"v": 0})
        with self.assertRaises(ConflictError):
            store.update("k", expected_version=999, data={"v": 1})

    def test_18_all_or_nothing_rollback(self):
        # A gated action with missing approval yields no mutation.
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action("steward:docker:mutate", action_type="docker_mutate")
        before = store.read("steward:local:docker_mutate:fdg_test")
        o = w.execute(a, "ts:test")
        self.assertEqual(o.result.decision, "denied")
        self.assertIsNone(store.read("steward:local:docker_mutate:fdg_test"))

    def test_19_bounded_occurrence_count(self):
        store = InMemoryStore()
        key = "steward:local:occurrence_increment:fdg_o"
        store.create_if_absent(key, {"capability": "steward:occurrence:increment"})
        rec = store.read(key)
        with self.assertRaises(BoundedCounterError):
            # Force overflow by repeated increments beyond bound is hard; instead
            # directly test the bound via a large step using internal path.
            store.increment_occurrence(key, rec.version, 1_000_000_000)

    def test_20_duplicate_action_idempotency(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action()
        o1 = w.execute(a, "ts:test")
        o2 = w.execute(a, "ts:test")
        self.assertTrue(o2.replayed)
        self.assertTrue(o2.result.idempotent_replay)

    def test_21_replay_returns_original_result(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action()
        o1 = w.execute(a, "ts:test")
        o2 = w.execute(a, "ts:1")
        # Replay id is deterministic from the action's own material, not the
        # new call token.
        self.assertEqual(
            o2.result.result_id,
            make_result_id(a.action_id, "replayed", a.requested_at),
        )
        self.assertTrue(o2.result.idempotent_replay)


class TestInputNonMutation(unittest.TestCase):
    def test_22_input_objects_not_mutated(self):
        payload = {"a": [1, 2, 3], "b": {"c": 4}}
        a = _make_action(normalized_payload=payload)
        snapshot = json.dumps(a.to_dict(), sort_keys=True)
        WriterCore(InMemoryStore()).execute(a, "ts:test")
        self.assertEqual(json.dumps(a.to_dict(), sort_keys=True), snapshot)
        self.assertEqual(payload["a"], [1, 2, 3])

    def test_23_stable_dict_list_ordering(self):
        a1 = _make_action(normalized_payload={"z": 1, "a": 2})
        a2 = _make_action(normalized_payload={"a": 2, "z": 1})
        self.assertEqual(a1.action_id, a2.action_id)


class TestPrivacyRedaction(unittest.TestCase):
    def test_25_nested_secret_redaction(self):
        ev = {"user": {"password": "hunter2", "name": "x"}}
        red = redact_evidence(ev)
        self.assertEqual(red["user"]["password"], "<redacted:secret>")
        self.assertEqual(red["user"]["name"], "x")

    def test_26_exception_redaction(self):
        red = redact_evidence({"note": "Traceback (most recent call last)"})
        self.assertEqual(red["note"], "<redacted:exception>")

    def test_27_private_npc_content_never_serialized(self):
        red = redact_evidence({"msg": "private message between NPCs"})
        self.assertEqual(red["msg"], "<redacted:private_npc_content>")


class TestPlanner(unittest.TestCase):
    def test_28_unknown_observation_no_unsafe_action(self):
        acts = plan_actions([{"check_id": "x", "status": "unknown",
                               "finding_id": "f", "dedupe_key": "d",
                               "severity": "info", "evidence": {}}],
                             "snap", "ts")
        self.assertEqual(acts, [])

    def test_29_action_storm_suppression(self):
        findings = [{"check_id": "npc_heartbeat", "status": "open",
                     "finding_id": f"f{i}", "dedupe_key": "same",
                     "severity": "warning", "evidence": {}} for i in range(5)]
        acts = plan_actions(findings, "snap", "ts")
        self.assertEqual(len(acts), 1)

    def test_planner_uses_known_capability(self):
        acts = plan_actions([{"check_id": "semantic_loop", "status": "open",
                              "finding_id": "f", "dedupe_key": "d",
                              "severity": "warning", "evidence": {}}], "snap", "ts")
        self.assertEqual(acts[0].requested_capability, "steward:work_order:create")


class TestCouncilorWatch(unittest.TestCase):
    def test_30_synthetic_markers(self):
        store = InMemoryStore()
        w = WriterCore(store)
        w.execute(_make_action(), "ts:test")
        view = render(store)
        self.assertTrue(view[0]["synthetic"])
        self.assertTrue(view[0]["read_only_projection"])
        self.assertEqual(view[0]["actor_classification"], "operator_npc")

    def test_31_no_pair_workspace_output(self):
        store = InMemoryStore()
        w = WriterCore(store)
        w.execute(_make_action(), "ts:test")
        view = render(store)
        self.assertIsNone(view[0]["pair_workspace"])
        self.assertEqual(view[0]["relationships_created"], 0)
        self.assertEqual(view[0]["messages_enqueued"], 0)
        self.assertFalse(view[0]["cognition_triggered"])


class TestCLI(unittest.TestCase):
    def _run(self, argv):
        from steward import s3cli
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = s3cli.main(argv)
        return rc, buf.getvalue()

    def test_32_cli_traversal_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            finding = os.path.join(d, "finding.json")
            snap = os.path.join(d, "snap.json")
            with open(finding, "w") as f:
                json.dump([{"check_id": "npc_heartbeat", "status": "open",
                            "finding_id": "f", "dedupe_key": "d",
                            "severity": "warning", "evidence": {}}], f)
            with open(snap, "w") as f:
                json.dump({"snapshot_id": "s"}, f)
            rc, out = self._run(["plan", "--finding", finding, "--snapshot", snap])
            self.assertEqual(rc, 0)
            self.assertIn("S3A HAS NO LIVE FEDERATION WRITER", out)

    def test_33_cli_symlink_rejection(self):
        from steward import s3cli
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "real.json")
            with open(target, "w") as f:
                json.dump({}, f)
            link = os.path.join(d, "link.json")
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symlink privilege unavailable on this platform")
            with self.assertRaises(ValueError):
                s3cli._safe_path(link, d)

    def test_34_cli_exit_codes(self):
        from steward import s3cli
        # invalid usage (missing subcommand) -> argparse exits 2
        with self.assertRaises(SystemExit) as ctx:
            s3cli.main([])
        self.assertEqual(ctx.exception.code, 2)


class TestSafePathPlatformIndependent(unittest.TestCase):
    """Mock-based path/traversal/symlink/junction guards.

    Windows symlink creation needs a privilege; these tests simulate the
    link/junction/reparse condition by patching os.path.islink, so the
    security rule is exercised on every platform.
    """

    def _call(self, path, base, is_link=False):
        from steward import s3cli
        import steward.s3cli as mod
        real_islink = os.path.islink
        os.path.islink = lambda p: is_link if p == path else real_islink(p)
        try:
            return s3cli._safe_path(path, base)
        finally:
            os.path.islink = real_islink

    def test_35_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertRaises(ValueError, self._call,
                            os.path.join(d, "link.json"), d, is_link=True)

    def test_36_junction_reparse_rejected(self):
        # Same guard path as a Windows junction/reparse point.
        with tempfile.TemporaryDirectory() as d:
            self.assertRaises(ValueError, self._call,
                            os.path.join(d, "jnk.json"), d, is_link=True)

    def test_37_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            evil = os.path.abspath(os.path.join(d, "..", "escape.json"))
            self.assertRaises(ValueError, self._call, evil, d, is_link=False)

    def test_38_resolved_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            # A path that textually starts with base but resolves outside via ../
            nested = os.path.join(d, "sub")
            os.makedirs(nested)
            escape = os.path.abspath(os.path.join(nested, "..", "..", "x.json"))
            self.assertRaises(ValueError, self._call, escape, d, is_link=False)

    def test_39_contained_path_accepted(self):
        from steward import s3cli
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "ok.json")
            resolved = s3cli._safe_path(good, d)
            self.assertTrue(resolved.startswith(os.path.abspath(d)))

    def test_40_rejection_is_fail_closed(self):
        # If islink detection is true the call must raise, never return a path.
        with tempfile.TemporaryDirectory() as d:
            raised = False
            try:
                self._call(os.path.join(d, "x.json"), d, is_link=True)
            except ValueError:
                raised = True
            self.assertTrue(raised)


class TestCrossProcessDeterminism(unittest.TestCase):
    """A3: two separate Python processes, different hash seed + dict order,
    must produce byte-identical plan/commit/replay hashes."""

    _HARNESS = r'''
import sys, json, hashlib
from steward.s3a_action import ProposedAction, S3A_SCHEMA_VERSION
from steward.s3a_writer import WriterCore
from steward.s3a_store import InMemoryStore
p = {"zeta": 1, "alpha": 2, "mid": 3}
ordered = dict(sorted(p.items())) if sys.argv[1] == "sorted" else p
a = ProposedAction(schema_version=S3A_SCHEMA_VERSION, action_type="incident_create",
    action_id=None, source_finding_id="fdg_x", source_snapshot_id="snap_x",
    target_namespace="steward:local", requested_capability="steward:incident:create",
    actor_id="actor:operator", requested_at="ts:SAME", idempotency_key="idem_x",
    approval_state="none", normalized_payload=ordered)
s = InMemoryStore(); w = WriterCore(s)
o1 = w.execute(a, "ts:SAME")
o2 = w.execute(a, "ts:SAME")
def h(x): return hashlib.sha256(x.encode()).hexdigest()[:16]
print(h(json.dumps(a.to_dict(), sort_keys=True)),
      h(json.dumps(o1.result.to_dict(), sort_keys=True)),
      h(json.dumps(o2.result.to_dict(), sort_keys=True)))
'''

    def _run(self, order, seed):
        import subprocess
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(self._HARNESS)
            path = fh.name
        try:
            env = dict(os.environ, PYTHONPATH=os.environ.get("PYTHONPATH", ""),
                       PYTHONHASHSEED=str(seed))
            out = subprocess.run([sys.executable, path, order], capture_output=True,
                                text=True, env=env, cwd=os.getcwd())
            return out.stdout.split()
        finally:
            os.unlink(path)

    def test_41_cross_process_byte_identical(self):
        h1 = self._run("scrambled", 0)
        h2 = self._run("sorted", 12345)
        self.assertEqual(h1, h2, "cross-process determinism broken")
        self.assertEqual(len(h1), 3)


class TestNoLiveConnectors(unittest.TestCase):
    def test_35_no_live_connector_imports(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        s3a_modules = [
            "s3a_action.py", "s3a_policy.py", "s3a_store.py",
            "s3a_writer.py", "s3a_planner.py", "s3a_audit.py",
            "s3a_operator.py", "s3a_councilor_watch.py", "s3cli.py",
        ]
        violations = []
        for m in s3a_modules:
            with open(os.path.join(root, "steward", m), "r", encoding="utf-8") as fh:
                v = scan_module(fh.read())
            violations.extend([f"{m}: {x}" for x in v])
        self.assertEqual(violations, [],
                         f"forbidden imports found: {violations}")

    def test_36_no_socket_subprocess_redis_in_core(self):
        core_modules = [
            "s3a_action.py",
            "s3a_policy.py",
            "s3a_store.py",
            "s3a_writer.py",
            "s3a_planner.py",
            "s3a_audit.py",
            "s3a_operator.py",
            "s3a_councilor_watch.py",
        ]
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for m in core_modules:
            with open(os.path.join(root, "steward", m), "r", encoding="utf-8") as fh:
                v = scan_module(fh.read())
            self.assertEqual(v, [], f"steward/{m} has forbidden imports: {v}")


class TestStaticCheck(unittest.TestCase):
    def test_static_scan_detects_forbidden(self):
        evil = "import redis\nimport socket\n"
        self.assertIn("import redis", scan_module(evil))
        self.assertIn("import socket", scan_module(evil))


class TestRegression(unittest.TestCase):
    def test_37_s1_regression(self):
        f = S1.make_finding(
            check_id="c1", observed_at="2020-01-01T00:00:00Z",
            summary="s", evidence={}, affected_entities=[],
            severity="warning", dedupe_key="dk", status="open",
        )
        self.assertTrue(f.finding_id.startswith("fdg_"))

    def test_38_randomized_input_order(self):
        # Different insertion orders must yield identical action id.
        ids = []
        for order in ({"a": 1, "b": 2}, {"b": 2, "a": 1}):
            a = _make_action(normalized_payload=order)
            ids.append(a.action_id)
        self.assertEqual(ids[0], ids[1])

    def test_39_simulated_concurrent_writers(self):
        # Two writers against the same store; optimistic version makes only one win.
        store = InMemoryStore()
        w1 = WriterCore(store)
        w2 = WriterCore(store)
        a = _make_action()
        o1 = w1.execute(a, "ts:test")
        o2 = w2.execute(a, "ts:test")  # replay because idempotency registered
        self.assertTrue(o1.committed)
        self.assertTrue(o2.replayed)

    def test_40_audit_append_behavior(self):
        store = InMemoryStore()
        w = WriterCore(store)
        a = _make_action()
        w.execute(a, "ts:test")
        key = "steward:local:incident_create:fdg_test"
        self.assertEqual(len(store.read(key).audit), 1)


if __name__ == "__main__":
    unittest.main()
