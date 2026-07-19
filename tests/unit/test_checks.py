"""Pure unit tests for the S1 Steward engine (no live I/O, no mutation).

Run from the repo root:

    python -m unittest discover -s tests/unit -p "test_*.py"

Run a single file:

    python -m unittest tests/unit/test_checks.py
"""

import ast
import hashlib
import json
import os
import sys
import unittest

# Make the engine importable when run from repo root or tests/ dir.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from steward.checks import ensure_loaded, list_checks, run_check  # noqa: E402
from steward.schema import Finding, make_finding, ENGINE_VERSION  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")

# Exact 16-field finding schema required by the spec (Section 8).
REQUIRED_FIELDS = (
    "finding_id",
    "check_id",
    "observed_at",
    "severity",
    "status",
    "summary",
    "evidence",
    "affected_entities",
    "dedupe_key",
    "first_seen",
    "last_seen",
    "occurrence_count",
    "recommended_action",
    "required_capability",
    "approval_required",
    "source_versions",
)

# Modules that must never be imported by the pure engine (spec security boundary).
FORBIDDEN_IMPORTS = ("redis", "requests", "docker", "psycopg", "subprocess", "socket")


def load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _forbidden_nodes_in(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    bad.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[0]
            if base in FORBIDDEN_IMPORTS:
                bad.append(("from", node.module))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("open", "subprocess", "socket"):
                bad.append(("call", func.id))
    return bad


def _sha_of(f: Finding) -> str:
    material = {
        "check_id": f.check_id,
        "dedupe_key": f.dedupe_key,
        "observed_at": f.observed_at,
        "status": f.status,
        "severity": f.severity,
        "affected_entities": list(f.affected_entities),
        "evidence": f.evidence,
        "source_versions": f.source_versions,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _dump(findings):
    return json.dumps([f.to_dict() for f in findings], sort_keys=True)


def _run_all(fixture):
    """Replicates cli.main `check all` dispatch without touching stdout."""
    all_findings = []
    checks_block = fixture.get("checks", {})
    observed_at = fixture.get("observed_at")
    for cid in list_checks():
        if isinstance(checks_block, dict) and cid in checks_block:
            payload = dict(checks_block[cid])
            if observed_at is not None:
                payload = {"observed_at": observed_at, **payload}
        else:
            payload = {"observed_at": observed_at} if observed_at is not None else {}
        all_findings.extend(run_check(cid, payload))
    return all_findings


def _fixture_for(cid):
    return {
        "semantic-loops": "semantic_loops_loop.json",
        "npc-heartbeats": "npc_heartbeats_stale.json",
    }[cid]


class TestSchema(unittest.TestCase):
    def test_finding_defaults(self):
        f = make_finding(
            check_id="x", severity="info", summary="s",
            observed_at="2026-07-18T23:00:00Z", dedupe_key="x:k",
        )
        self.assertEqual(f.status, "open")
        self.assertIn("engine", f.source_versions)
        self.assertEqual(f.source_versions["engine"], ENGINE_VERSION)
        self.assertTrue(f.finding_id.startswith("fdg_"))
        self.assertEqual(f.first_seen, f.observed_at)
        self.assertEqual(f.last_seen, f.observed_at)
        self.assertEqual(f.occurrence_count, 1)

    def test_invalid_severity(self):
        with self.assertRaises(ValueError):
            make_finding(
                check_id="x", severity="bad", summary="s",
                observed_at="2026-07-18T23:00:00Z", dedupe_key="x:k",
            )

    def test_invalid_status(self):
        with self.assertRaises(ValueError):
            make_finding(
                check_id="x", severity="info", summary="s", status="weird",
                observed_at="2026-07-18T23:00:00Z", dedupe_key="x:k",
            )

    def test_missing_dedupe(self):
        with self.assertRaises(ValueError):
            make_finding(
                check_id="x", severity="info", summary="s",
                observed_at="2026-07-18T23:00:00Z",
            )

    def test_observed_at_required(self):
        with self.assertRaises(ValueError):
            make_finding(check_id="x", severity="info", summary="s", dedupe_key="x:k")

    def test_no_wall_clock_in_schema(self):
        bad = _forbidden_nodes_in(os.path.join(ROOT, "steward", "schema.py"))
        self.assertEqual(bad, [], msg=f"forbidden nodes in schema.py: {bad}")


class TestDeterministicFindingId(unittest.TestCase):
    def setUp(self):
        ensure_loaded()

    def test_finding_id_is_sha256_derived(self):
        f = make_finding(
            check_id="semantic-loops", severity="warning",
            summary="x", observed_at="2026-07-18T23:00:00Z",
            dedupe_key="k", evidence={"a": 1}, affected_entities=["char_001"],
        )
        self.assertEqual(f.finding_id, "fdg_" + _sha_of(f))

    def test_identical_material_same_id(self):
        a = make_finding(
            check_id="c", severity="error", summary="s",
            observed_at="2026-07-18T23:00:00Z", dedupe_key="k",
            evidence={"x": 1}, affected_entities=["e1"],
        )
        b = make_finding(
            check_id="c", severity="error", summary="s",
            observed_at="2026-07-18T23:00:00Z", dedupe_key="k",
            evidence={"x": 1}, affected_entities=["e1"],
        )
        self.assertEqual(a.finding_id, b.finding_id)

    def test_different_evidence_different_id(self):
        a = make_finding(
            check_id="c", severity="error", summary="s",
            observed_at="2026-07-18T23:00:00Z", dedupe_key="k", evidence={"x": 1},
        )
        b = make_finding(
            check_id="c", severity="error", summary="s",
            observed_at="2026-07-18T23:00:00Z", dedupe_key="k", evidence={"x": 2},
        )
        self.assertNotEqual(a.finding_id, b.finding_id)

    def test_byte_identical_run_output(self):
        a = run_check("semantic-loops", load("semantic_loops_loop.json"))
        b = run_check("semantic-loops", load("semantic_loops_loop.json"))
        self.assertEqual(_dump(a), _dump(b))
        self.assertEqual(a[0].finding_id, b[0].finding_id)


class TestCompleteSchema(unittest.TestCase):
    def setUp(self):
        ensure_loaded()

    def test_exact_sixteen_fields(self):
        for cid in ("semantic-loops", "npc-heartbeats"):
            fs = run_check(cid, load(_fixture_for(cid)))
            for f in fs:
                self.assertEqual(
                    tuple(f.to_dict().keys()), REQUIRED_FIELDS,
                    msg=f"{cid} schema keys mismatch",
                )

    def test_unknown_uses_sixteen_fields(self):
        fs = run_check("semantic-loops", load("semantic_loops_unknown.json"))
        self.assertEqual(tuple(fs[0].to_dict().keys()), REQUIRED_FIELDS)

    def test_first_last_seen_equal_observed(self):
        fs = run_check("semantic-loops", load("semantic_loops_loop.json"))
        for f in fs:
            self.assertEqual(f.first_seen, f.observed_at)
            self.assertEqual(f.last_seen, f.observed_at)
            self.assertEqual(f.occurrence_count, 1)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        ensure_loaded()

    def test_checks_present(self):
        self.assertIn("semantic-loops", list_checks())
        self.assertIn("npc-heartbeats", list_checks())


class TestSemanticLoops(unittest.TestCase):
    def setUp(self):
        ensure_loaded()

    def test_detects_loop(self):
        fs = run_check("semantic-loops", load("semantic_loops_loop.json"))
        self.assertEqual(len(fs), 1)
        f = fs[0]
        self.assertEqual(f.check_id, "semantic-loops")
        self.assertEqual(f.severity, "warning")
        self.assertEqual(f.dedupe_key, "semantic-loop:npc_pair:char_001__char_306:state")
        # steward:work_order:create is an automatic Federation-world capability;
        # no gated action requested, so approval is not required.
        self.assertFalse(f.approval_required)
        self.assertEqual(f.required_capability, "steward:work_order:create")
        self.assertEqual(f.evidence["repeated_question_count"], 3)

    def test_clean_no_finding(self):
        fs = run_check("semantic-loops", load("semantic_loops_clean.json"))
        self.assertEqual(fs, [])

    def test_unknown_source(self):
        fs = run_check("semantic-loops", load("semantic_loops_unknown.json"))
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].status, "unknown")


class TestNpcHeartbeats(unittest.TestCase):
    def setUp(self):
        ensure_loaded()

    def test_stale_warning_and_null_error(self):
        fs = run_check("npc-heartbeats", load("npc_heartbeats_stale.json"))
        by_char = {f.evidence["char_id"]: f for f in fs}
        self.assertEqual(by_char["char_001"].severity, "warning")
        self.assertEqual(by_char["char_306"].severity, "error")
        self.assertIsNone(by_char["char_306"].evidence["age_seconds"])

    def test_fresh_no_finding(self):
        fs = run_check("npc-heartbeats", load("npc_heartbeats_fresh.json"))
        self.assertEqual(fs, [])

    def test_unknown_source(self):
        fs = run_check("npc-heartbeats", load("npc_heartbeats_unknown.json"))
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].status, "unknown")

    def test_prohibits_cognition_flag(self):
        fs = run_check("npc-heartbeats", load("npc_heartbeats_stale.json"))
        for f in fs:
            self.assertNotIn("trigger_cognition", f.evidence)


class TestCombinedDispatch(unittest.TestCase):
    """Spec Part D: `check all` splits the combined fixture per check."""

    def setUp(self):
        ensure_loaded()

    def test_combined_produces_both_checks(self):
        fs = _run_all(load("combined_all.json"))
        cids = {f.check_id for f in fs}
        self.assertIn("semantic-loops", cids)
        self.assertIn("npc-heartbeats", cids)

    def test_combined_byte_identical_twice(self):
        a = _run_all(load("combined_all.json"))
        b = _run_all(load("combined_all.json"))
        self.assertEqual(_dump(a), _dump(b))

    def test_missing_payload_yields_unknown(self):
        fs = _run_all(load("combined_missing_npc.json"))
        cids = {f.check_id for f in fs}
        self.assertIn("semantic-loops", cids)
        npc = [f for f in fs if f.check_id == "npc-heartbeats"]
        self.assertEqual(len(npc), 1)
        self.assertEqual(npc[0].status, "unknown")


class TestUnknownContract(unittest.TestCase):
    """Spec 6: never infer healthy from could-not-read."""

    def setUp(self):
        ensure_loaded()

    def test_no_healthy_inference(self):
        for cid in list_checks():
            fs = run_check(cid, {})
            for f in fs:
                self.assertNotEqual(f.status, "open-healthy-fabricated")


class TestNoIoMutation(unittest.TestCase):
    """Spec security boundary: pure engine imports no I/O / mutation modules."""

    def test_engine_modules_no_forbidden_imports(self):
        # The pure engine logic (schema + checks) must never import or call
        # live I/O / mutation surfaces. The CLI (steward/cli.py) is the explicit
        # sanctioned I/O boundary and is intentionally excluded from this rule.
        for rel in (
            "steward/schema.py",
            "steward/checks/__init__.py",
            "steward/checks/semantic_loops.py",
            "steward/checks/npc_heartbeats.py",
        ):
            bad = _forbidden_nodes_in(os.path.join(ROOT, *rel.split("/")))
            self.assertEqual(bad, [], msg=f"forbidden nodes in {rel}: {bad}")

    def test_fixture_unchanged_after_check(self):
        raw = load("combined_all.json")
        snapshot = json.dumps(raw, sort_keys=True)
        _run_all(raw)
        self.assertEqual(json.dumps(raw, sort_keys=True), snapshot)


if __name__ == "__main__":
    unittest.main()
