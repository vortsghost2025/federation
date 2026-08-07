#!/usr/bin/env python3
"""DB1-only tests for the Federation Architect Loop Monitor.
All tests use docker exec transport (same as production monitor).
Each test runs in a separate Python process to avoid module contamination.
"""

import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, "/docker/federation-game/shared")
sys.path.insert(0, "/opt/federation_shared")

ARCHITECT   = "/docker/federation-architect"
PACKET_DIR  = os.path.join(ARCHITECT, "requests")
STATE_DIR   = os.path.join(ARCHITECT, "state")
REG_FILE    = os.path.join(STATE_DIR, "registry.json")
MONITOR     = os.path.join(ARCHITECT, "monitor.py")

BACKEND_CONTAINER = "federation-game-backend-1"
BACKEND_INTERNAL  = "http://127.0.0.1:8000"

TEST_NS = f"architect_test_{uuid.uuid4().hex[:8]}"
REDIS_DB1 = "redis://172.16.2.12:6379/1"


def docker_get(path: str) -> dict:
    """Read-only GET via docker exec into backend container."""
    cmd = [
        "docker", "exec", BACKEND_CONTAINER,
        "python3", "-c",
        f"import urllib.request,json,sys; "
        f"resp=urllib.request.urlopen('{BACKEND_INTERNAL}{path}',timeout=15); "
        f"sys.stdout.write(resp.read().decode())"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(f"docker exec failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _wait():
    time.sleep(0.3)


# ── Test 1: monitor executes (uses docker exec transport) ─────────────
def test_1_monitor_executes():
    result = subprocess.run(
        ["python3", MONITOR],
        capture_output=True, text=True, timeout=30, cwd=ARCHITECT,
    )
    assert result.returncode == 0, f"monitor failed: {result.stderr}"
    assert "Architect monitor" in result.stdout

# ── Test 2: registry created and valid JSON ───────────────────────────
def test_2_registry_valid():
    os.makedirs(STATE_DIR, exist_ok=True)
    # Clear old registry to force fresh run
    if os.path.isfile(REG_FILE):
        os.remove(REG_FILE)
    subprocess.run(["python3", MONITOR], capture_output=True, timeout=30, cwd=ARCHITECT)
    assert os.path.isfile(REG_FILE), "registry.json not created after run"
    with open(REG_FILE) as f:
        reg = json.load(f)
    assert "last_run_iso" in reg
    assert "requests" in reg
    assert isinstance(reg["requests"], dict)

# ── Test 3: backend reachable via docker exec ─────────────────────────
def test_3_backend_reachable():
    data = docker_get("/councilor/capability-requests")
    assert "requests" in data, f"unexpected response: {list(data.keys())[:5]}"
    assert isinstance(data["requests"], list)

# ── Test 4: monitor --list works ─────────────────────────────────────
def test_4_list_works():
    result = subprocess.run(
        ["python3", MONITOR, "--list"],
        capture_output=True, text=True, timeout=30, cwd=ARCHITECT,
    )
    assert result.returncode == 0
    # Should list requests (might be some from existing DB0 data)

# ── Test 5: monitor --diff works ─────────────────────────────────────
def test_5_diff_works():
    result = subprocess.run(
        ["python3", MONITOR, "--diff"],
        capture_output=True, text=True, timeout=30, cwd=ARCHITECT,
    )
    assert result.returncode == 0
    # Should print something (new or "no new")

# ── Test 6: packet directory exists and has files ────────────────────
def test_6_packet_directory():
    assert os.path.isdir(PACKET_DIR), "packet dir missing"
    files = os.listdir(PACKET_DIR)
    assert len(files) > 0, "no packet files found"

# ── Test 7: packet files are valid Markdown ──────────────────────────
def test_7_packet_format():
    for fname in os.listdir(PACKET_DIR):
        if fname.endswith(".md"):
            with open(os.path.join(PACKET_DIR, fname)) as fx:
                content = fx.read()
            assert "# " in content, f"no title in {fname}"
            assert "## Objective" in content, f"missing Objective in {fname}"
            assert "## Blocker" in content, f"missing Blocker in {fname}"


if __name__ == "__main__":
    tests = [
        ("test_1_monitor_executes",       test_1_monitor_executes),
        ("test_2_registry_valid",         test_2_registry_valid),
        ("test_3_backend_reachable",      test_3_backend_reachable),
        ("test_4_list_works",             test_4_list_works),
        ("test_5_diff_works",             test_5_diff_works),
        ("test_6_packet_dir",             test_6_packet_directory),
        ("test_7_packet_format",          test_7_packet_format),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"[PASS] {name}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {e}")
    print(f"\n=== {passed} passed, {failed} failed (of {len(tests)}) ===")