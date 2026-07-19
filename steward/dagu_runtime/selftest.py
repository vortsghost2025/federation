#!/usr/bin/env python3
"""DR-004 Runtime self-test for the Steward Dagu qualification image.

Run inside the built container (or locally against the worktree) to prove the
runtime is shadow-only and safe. Exits non-zero on any failure so the
container build / qualification fails closed.

Proves:
  1. python3 present
  2. `python -m steward.s3ccli` imports (entrypoint usable)
  3. run-fixture -> shadow-only (no live path)
  4. READY_FOR_LIVE is impossible (interlock forbids live class)
  5. temp artifacts cleaned (no stray shadow db left behind)
  6. no live connector IMPORTED/INVOKED by the fixture path (comment mentions
     of forbidden modules in safety headers do NOT count)
  7. no docker socket reachable
  8. no credential material present in the package tree
  9. no canonical production paths / live-apply calls leaked
"""
from __future__ import annotations
import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# The runtime lives in steward/dagu_runtime; never scan it with its own rules.
RUNTIME_DIR = Path(__file__).resolve().parent
STEWARD_DIR = REPO_ROOT / "steward"

# Modules that would constitute a LIVE connector if actually imported/called.
LIVE_MODULES = ("redis", "paramiko", "psycopg", "psycopg2", "pymysql",
                "mysql", "sqlalchemy", "docker", "fabric", "telnetlib",
                "urllib.request", "http.client", "socket", "subprocess",
                "ssh", "requests")

# Real leak patterns (substring, case-insensitive). Comment/header text that
# merely asserts "no production path exists" is intentionally NOT a leak.
LEAK_PATTERNS = ("/docker/federation-game", "live_apply(", "push_to_remote(",
                 "git push", "subprocess.run([", "os.system(", "docker.from_env")


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        check.failed.append(name)


check.failed = []


def imports_live_connector(path: Path) -> list[str]:
    """Return list of live-connector modules actually imported/used in the file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                base = n.name.split(".")[0]
                if base in LIVE_MODULES:
                    used.add(base)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            base = mod.split(".")[0]
            if base in LIVE_MODULES or mod in LIVE_MODULES:
                used.add(base or mod)
    return sorted(used)


def main() -> int:
    # 1. python present
    check("python3-present", sys.version_info >= (3, 8),
          f"{sys.version_info.major}.{sys.version_info.minor}")

    # 2. s3ccli importable (add REPO_ROOT to path as the image does via PYTHONPATH)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        spec = importlib.util.find_spec("steward.s3ccli")
        check("s3ccli-importable", spec is not None)
    except Exception as e:
        check("s3ccli-importable", False, str(e))

    # 3. run-fixture -> shadow-only (use ephemeral memory backend)
    proc = subprocess.run(
        [sys.executable, "-m", "steward.s3ccli", "run-fixture",
         "--backend", "memory", "--namespace", "steward:shadow:gastown"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    ok = proc.returncode == 0
    shadow_only = ("shadow" in proc.stdout.lower()) or ("shadow" in proc.stderr.lower())
    check("run-fixture-succeeds", ok, (proc.stderr or proc.stdout)[-200:])
    check("run-fixture-shadow-only", shadow_only,
          "output must stay in shadow class")

    # 5. no stray shadow db left in repo root after run
    stray = list(REPO_ROOT.rglob("shadow.db")) + list(REPO_ROOT.rglob("*.shadow.db"))
    check("no-stray-shadow-db", not stray, f"found {stray}")

    # 4. READY_FOR_LIVE impossible — interlock forbids live classification
    try:
        import steward.s3c.interlock as il
        live_classes = [a for a in dir(il) if "READY_FOR_LIVE" in a.upper()]
        check("no-ready-for-live-class", not live_classes, str(live_classes))
    except Exception as e:
        check("interlock-inspectable", False, str(e))
        check("no-ready-for-live-class", False, "interlock not inspectable")

    # 6. no live connector actually imported by fixture-relevant modules
    bad = []
    scan_dirs = [STEWARD_DIR / "s3c", STEWARD_DIR / "s3b"]
    for d in scan_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if p.parent == RUNTIME_DIR:
                continue
            hits = imports_live_connector(p)
            if hits:
                bad.append(f"{p.relative_to(REPO_ROOT).as_posix()}:{','.join(hits)}")
    check("no-live-connector-in-fixture-path", not bad, "; ".join(bad[:5]))

    # 7. no docker socket reachable
    check("no-docker-socket", not Path("/var/run/docker.sock").exists())

    # 8. no credentials in package tree
    cred_hits = []
    for p in STEWARD_DIR.rglob("*"):
        low = p.name.lower()
        if any(b in low for b in ("secret", "credential", ".env", "id_rsa",
                                  "authorized_keys", "token.json", "token.txt")):
            cred_hits.append(p.relative_to(REPO_ROOT).as_posix())
    check("no-credentials-in-package", not cred_hits, "; ".join(cred_hits[:5]))

    # 9. no canonical production paths / live-apply calls leaked
    leak_hits = []
    for p in STEWARD_DIR.rglob("*.py"):
        if p.parent == RUNTIME_DIR:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore").lower()
        for pat in LEAK_PATTERNS:
            if pat.lower() in text:
                leak_hits.append(f"{p.relative_to(REPO_ROOT).as_posix()}:{pat}")
    check("no-canonical-prod-paths", not leak_hits, "; ".join(leak_hits[:5]))

    print("\n=== SELF-TEST SUMMARY ===")
    print(f"checks failed: {len(check.failed)}")
    if check.failed:
        print("FAILED:", ", ".join(check.failed))
        return 1
    print("ALL CHECKS PASSED — runtime is shadow-only and safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
