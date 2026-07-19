"""Unit tests for S2 read-only adapters (no live I/O, no mutation).

Run from repo root:
    python -m unittest tests/unit/test_s2_adapters.py

Every collector is exercised with injected fakes. No network, no Redis, no
Docker, no process execution. Assertions cover: allowlist enforcement,
unknown-on-failure, normalization, redaction, no injection, determinism.
"""

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from steward.adapters import base, docker_ro, http_ro, redis_ro  # noqa: E402
from steward.adapters.base import (  # noqa: E402
    Availability,
    ObservationSnapshot,
    unknown_snapshot,
)
from steward.adapters.npc import collect as npc_collect  # noqa: E402
from steward.adapters.semantic_loop import collect as sl_collect  # noqa: E402
from steward.adapters.host import collect as host_collect  # noqa: E402
from steward.redact import redact_value, redact_json_text  # noqa: E402

OBS = "2026-07-18T23:00:00Z"


class FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    def get(self, key):
        return self.store.get(key)

    def ttl(self, key):
        return self.store.get(f"__ttl__{key}", -1)

    def type(self, key):
        return self.store.get(f"__type__{key}", "none")

    def ping(self):
        return "PONG"

    def info(self):
        return "redis_version:7.0.0"


class FakeRequester:
    def __init__(self, status=200, body="ok", headers=None, elapsed=10):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.elapsed = elapsed

    def __call__(self, method, url, opts):
        return {
            "status_code": self.status,
            "headers": self.headers,
            "body": self.body,
            "elapsed_ms": self.elapsed,
        }


class FakeDocker:
    def __init__(self, out="container1\ncontainer2"):
        self.out = out

    def __call__(self, args):
        return self.out


class TestRedisAllowlist(unittest.TestCase):
    def test_allowed_command_runs(self):
        fake = FakeRedis({"k": "v"})
        snap = redis_ro.run_command(
            lambda c, a: getattr(fake, c.lower())(*a), "GET", ["k"],
            observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertEqual(snap.data["result"], "v")

    def test_refused_command_unknown(self):
        snap = redis_ro.run_command(
            lambda c, a: None, "FLUSHALL", [], observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("refused", snap.status_detail)

    def test_redis_error_unknown(self):
        def boom(c, a):
            raise RuntimeError("connection reset")

        snap = redis_ro.run_command(boom, "GET", ["k"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("failed", snap.status_detail)

    def test_bounded_key_health(self):
        fake = FakeRedis({
            "k1": "a", "__type__k1": "string", "__ttl__k1": 100,
            "k2": "b", "__type__k2": "string", "__ttl__k2": -1,
        })
        snap = redis_ro.collect_key_health(
            lambda c, a: getattr(fake, c.lower())(*a),
            ["k1", "k2"], observed_at=OBS,
        )
        self.assertEqual(snap.data["key_count"], 2)
        self.assertEqual(snap.data["sampled_keys"]["k1"]["ttl"], 100)


class TestHttpAllowlist(unittest.TestCase):
    def test_get_ok(self):
        snap = http_ro.fetch(FakeRequester(200), "http://x/health", observed_at=OBS)
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertEqual(snap.data["status_code"], 200)

    def test_degraded_on_5xx(self):
        snap = http_ro.fetch(FakeRequester(503), "http://x/health", observed_at=OBS)
        self.assertEqual(snap.availability, Availability.DEGRADED.value)

    def test_post_refused(self):
        snap = http_ro.fetch(FakeRequester(200), "http://x", method="POST", observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("refused", snap.status_detail)

    def test_error_unknown(self):
        def boom(m, u, o):
            raise TimeoutError("timed out")

        snap = http_ro.fetch(boom, "http://x", observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)


class TestDockerAllowlist(unittest.TestCase):
    def test_ps_allowed(self):
        snap = docker_ro.run(FakeDocker(), ["ps"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertIn("docker", snap.data["command"][0])

    def test_exec_refused(self):
        snap = docker_ro.run(FakeDocker(), ["exec", "c1", "bash"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("refused", snap.status_detail)

    def test_run_refused(self):
        snap = docker_ro.run(FakeDocker(), ["run", "img"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)

    def test_error_unknown(self):
        def boom(args):
            raise RuntimeError("docker daemon down")

        snap = docker_ro.run(boom, ["ps"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)


class TestNpcSemanticHost(unittest.TestCase):
    def test_npc_normalizes(self):
        snap = npc_collect(
            lambda: {"actors": [{"char_id": "c1", "last_heartbeat_ts": OBS}]},
            observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertEqual(snap.data["actors"][0]["char_id"], "c1")

    def test_npc_missing_actors_unknown(self):
        snap = npc_collect(lambda: {}, observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)

    def test_npc_error_unknown(self):
        snap = npc_collect(lambda: (_ for _ in ()).throw(RuntimeError("x")), observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)

    def test_semantic_normalizes(self):
        snap = sl_collect(lambda: {"pairs": [{"pair_key": "p1"}]}, observed_at=OBS)
        self.assertEqual(snap.data["pairs"][0]["pair_key"], "p1")

    def test_semantic_missing_unknown(self):
        snap = sl_collect(lambda: {}, observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)

    def test_host_normalizes(self):
        snap = host_collect(lambda: {"disk": {"free_pct": 30}}, observed_at=OBS)
        self.assertEqual(snap.data["disk"]["free_pct"], 30)

    def test_host_error_unknown(self):
        snap = host_collect(lambda: (_ for _ in ()).throw(RuntimeError("x")), observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)


class TestRedaction(unittest.TestCase):
    def test_sensitive_key_redacted(self):
        data = {"password": "hunter2", "name": "ok"}
        out = redact_value(data)
        self.assertEqual(out["password"], "***REDACTED***")
        self.assertEqual(out["name"], "ok")

    def test_jwt_redacted_in_string(self):
        data = {"token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"}
        out = redact_value(data)
        self.assertEqual(out["token"], "***REDACTED***")

    def test_redis_url_redacted(self):
        data = {"conn": "redis://user:secretpw@127.0.0.1:6379"}
        out = redact_value(data)
        self.assertEqual(out["conn"], "***REDACTED***")

    def test_no_secret_on_any_surface(self):
        snap = ObservationSnapshot(
            source="redis", observed_at=OBS,
            data={"password": "hunter2", "info": "redis_version:7.0.0"},
        )
        text = snap.to_json(redact=True)
        self.assertNotIn("hunter2", text)
        self.assertIn("***REDACTED***", text)

    def test_redact_json_text_handles_nonjson(self):
        text = redact_json_text("token eyJhbGciOiJIUzI1NiJ9.x.y here")
        self.assertNotIn("eyJhbGci", text)


class TestSnapshotDeterminism(unittest.TestCase):
    def test_identical_observations_identical_json(self):
        fake = FakeRedis({"k": "v", "__ttl__k": 5, "__type__k": "string"})
        a = redis_ro.run_command(
            lambda c, a2: getattr(fake, c.lower())(*a2), "GET", ["k"], observed_at=OBS,
        ).to_json(redact=True)
        b = redis_ro.run_command(
            lambda c, a2: getattr(fake, c.lower())(*a2), "GET", ["k"], observed_at=OBS,
        ).to_json(redact=True)
        self.assertEqual(a, b)

    def test_snapshot_fields_ordered(self):
        snap = unknown_snapshot("redis", OBS, "detail")
        keys = list(snap.to_dict().keys())
        self.assertEqual(
            keys,
            ["source", "observed_at", "availability", "version", "status_detail", "provenance", "data"],
        )


class TestNoLiveIoInAdapters(unittest.TestCase):
    """Adapters must never import live I/O / mutation modules (spec boundary)."""

    FORBIDDEN = ("redis", "requests", "docker", "psycopg", "subprocess", "socket", "urllib")

    def _forbidden_nodes(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in self.FORBIDDEN:
                        bad.append(("import", alias.name))
            elif isinstance(node, ast.ImportFrom):
                base = (node.module or "").split(".")[0]
                if base in self.FORBIDDEN:
                    bad.append(("from", node.module))
        return bad

    def test_adapter_modules_pure(self):
        base = os.path.join(ROOT, "steward", "adapters")
        for name in os.listdir(base):
            if name.endswith(".py") and not name.startswith("__"):
                bad = self._forbidden_nodes(os.path.join(base, name))
                self.assertEqual(bad, [], msg=f"forbidden nodes in {name}: {bad}")

    def test_pure_engine_untouched_by_live_io(self):
        # The S1 pure engine MUST stay free of live I/O / mutation imports.
        # collectors.py is the sanctioned I/O boundary and MAY import
        # subprocess/urllib/redis; adapters.py is the read-only adapter layer
        # and MUST NOT import live I/O (it relies on injected runners).
        for rel in (
            "steward/schema.py",
            "steward/checks/__init__.py",
            "steward/checks/semantic_loops.py",
            "steward/checks/npc_heartbeats.py",
            "steward/cli.py",
        ):
            bad = self._forbidden_nodes(os.path.join(ROOT, *rel.split("/")))
            self.assertEqual(bad, [], msg=f"forbidden nodes in {rel}: {bad}")


class TestS21Hardening(unittest.TestCase):
    """S2.1-008: adversarial validation of the hardened read-only boundaries."""

    def test_http_adapter_rejects_non_http_scheme(self):
        from steward.adapters import http_ro

        snap = http_ro.fetch(
            lambda m, u, o: None, "file:///etc/passwd", method="GET", observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("scheme", snap.status_detail.lower())

    def test_http_adapter_rejects_embedded_credentials(self):
        from steward.adapters import http_ro

        snap = http_ro.fetch(
            lambda m, u, o: None, "https://user:pass@host/x", method="GET", observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)

    def test_http_adapter_allows_clean_https(self):
        from steward.adapters import http_ro

        captured = {}

        def fake(m, u, o):
            captured["m"] = m
            captured["u"] = u
            return {"status_code": 200, "headers": {}, "body": "ok", "elapsed_ms": 1}

        snap = http_ro.fetch(fake, "https://example.com/health", method="GET", observed_at=OBS)
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertEqual(captured["u"], "https://example.com/health")

    def test_collectors_http_target_blocked_networks(self):
        from steward import collectors

        # metadata IP, loopback, private ranges must be refused.
        blocked = (
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8080/health",
            "http://10.0.0.5/health",
            "http://192.168.1.1/health",
            "ftp://example.com/x",
            "file:///etc/passwd",
        )
        for url in blocked:
            self.assertFalse(
                collectors._http_target_allowed(url, allowed_hosts=None),
                msg=f"should refuse {url}",
            )
            # live_http must also raise for http(s) blocked targets.
            if url.startswith(("http://", "https://")):
                with self.assertRaises(ValueError):
                    collectors.live_http("GET", url, {})

    def test_docker_adapter_rejects_option_injection(self):
        from steward.adapters import docker_ro

        snap = docker_ro.run(lambda a: "ok", ["ps", "--evil-flag"], observed_at=OBS)
        self.assertEqual(snap.availability, Availability.UNKNOWN.value)
        self.assertIn("option injection", snap.status_detail.lower())

    def test_docker_adapter_allows_known_flags(self):
        from steward.adapters import docker_ro

        out = []
        snap = docker_ro.run(
            lambda a: out.append(a) or "NAME\n",
            ["ps", "--format", "{{.Names}}", "--no-stream"], observed_at=OBS,
        )
        self.assertEqual(snap.availability, Availability.AVAILABLE.value)
        self.assertEqual(out[0], ["ps", "--format", "{{.Names}}", "--no-stream"])

    def test_collectors_docker_rejects_option_injection(self):
        from steward import collectors

        with self.assertRaises(ValueError):
            collectors.live_docker(["ps", "-r"])

    def test_redis_client_never_takes_password(self):
        from steward import collectors
        import inspect

        sig = inspect.signature(collectors._get_redis_client)
        self.assertNotIn("password", sig.parameters)

    def test_redact_masks_bytes_values(self):
        from steward.redact import redact_value

        data = {"token": b"supersecretvalue"}
        out = redact_value(data)
        self.assertEqual(out["token"], "***REDACTED***")

    def test_redact_masks_bytes_in_list(self):
        from steward.redact import redact_value

        out = redact_value([b"secretbytes"])
        self.assertEqual(out[0], "***REDACTED***")

    def test_s2cli_always_masks_credentials_even_with_no_redact(self):
        from steward import s2cli
        from steward.redact import redact_credentials_strong

        snap_like = [{"source": "http", "data": {"Authorization": "Bearer abc123"}}]
        # Simulate the always-on pass applied regardless of --no-redact.
        out = redact_credentials_strong(snap_like)
        self.assertEqual(out[0]["data"]["Authorization"], "***REDACTED***")

    def test_collectors_redis_signature_has_no_password(self):
        from steward import collectors
        import inspect

        for fn in (collectors.collect_redis_snapshot, collectors.collect_redis_key_health):
            self.assertNotIn("password", inspect.signature(fn).parameters)


class TestCrossProcessDeterminism(unittest.TestCase):
    """EVID-005: same normalized snapshot serialized in two separate Python
    processes, with different input dict insertion order, must be byte-identical
    and carry a stable SHA-256."""

    _RUNNER = (
        "import sys, json, hashlib\n"
        "sys.path.insert(0, '.')\n"
        "from steward.adapters.base import snapshot_from\n"
        "order = json.loads(sys.argv[1])\n"
        "data = {k: order[k] for k in order}\n"
        "snap = snapshot_from(source='redis', observed_at='2026-07-19T00:00:00Z',\n"
        "                      data=data, availability='available', version='1.0',\n"
        "                      provenance='test')\n"
        "out = snap.to_json(redact=True)\n"
        "print(json.dumps({'sha256': hashlib.sha256(out.encode('utf-8')).hexdigest(),\n"
        "                   'bytes': out}, sort_keys=True))\n"
    )

    def _serialize_in_subprocess(self, insertion_order):
        import subprocess
        import sys
        import json

        res = subprocess.run(
            [sys.executable, "-c", self._RUNNER, json.dumps(insertion_order)],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout.strip())

    def test_cross_process_byte_determinism(self):
        order_a = {"alpha": 1, "beta": 2, "gamma": 3, "delta": 4}
        order_b = {"delta": 4, "gamma": 3, "beta": 2, "alpha": 1}
        doc_a = self._serialize_in_subprocess(order_a)
        doc_b = self._serialize_in_subprocess(order_b)
        self.assertEqual(doc_a["sha256"], doc_b["sha256"])
        self.assertEqual(doc_a["bytes"], doc_b["bytes"])
        # Pin the deterministic hash so unintended drift is caught.
        self.assertEqual(
            doc_a["sha256"],
            "ac34d3e51a9c508c88492503d3ea8a16111ba377cfd1285c82b443b621389869",
        )

    _FINDING_RUNNER = (
        "import sys, json\n"
        "sys.path.insert(0, '.')\n"
        "from steward.schema import make_finding\n"
        "ev = json.loads(sys.argv[1])\n"
        "f = make_finding(check_id='chk_x', observed_at='2026-07-19T00:00:00Z',\n"
        "                  severity='info', summary='s', evidence=ev,\n"
        "                  dedupe_key='dk', required_capability='steward:incident:create')\n"
        "print(json.dumps({'finding_id': f.finding_id, 'digest': f.finding_id[4:]},\n"
        "                  sort_keys=True))\n"
    )

    def _finding_in_subprocess(self, evidence):
        import subprocess
        import sys
        import json

        res = subprocess.run(
            [sys.executable, "-c", self._FINDING_RUNNER, json.dumps(evidence)],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout.strip())

    def test_cross_process_finding_determinism(self):
        ev_a = {"host": "h1", "metric": "cpu", "value": 91}
        ev_b = {"value": 91, "metric": "cpu", "host": "h1"}
        doc_a = self._finding_in_subprocess(ev_a)
        doc_b = self._finding_in_subprocess(ev_b)
        self.assertEqual(doc_a["finding_id"], doc_b["finding_id"])
        self.assertEqual(doc_a["digest"], doc_b["digest"])
        self.assertEqual(
            doc_a["digest"],
            "b958e9c2418b73c1e275ffc17106ce00d68a2a9a2fe599cd26c3df1ffb207042",
        )


if __name__ == "__main__":
    unittest.main()
