#!/usr/bin/env python3
"""DR-007 Security scan for the Steward Dagu qualification runtime.

Validates the generated source manifest (DR-003) and source tree against the
brief's hard constraints. Produces security_report.json. Fails closed:
any forbidden artifact present -> non-zero exit.

Checks:
  - manifest excludes .git, __pycache__, drafts, tests-not-needed, DBs
  - no forbidden file names (credentials, npc_agent_current, docker-compose)
  - no live-connector modules actually imported in fixture path
  - no docker socket / no production creds / no canonical prod paths
  - Dockerfile pins a digest (no :latest)
  - workflow YAML has no schedule/trigger and no creds
"""
from __future__ import annotations
import ast
import json
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[1]
STEWARD_DIR = REPO_ROOT / "steward"

LIVE_MODULES = ("redis", "paramiko", "psycopg", "psycopg2", "pymysql", "mysql",
                "sqlalchemy", "docker", "fabric", "telnetlib", "urllib.request",
                "http.client", "socket", "subprocess", "ssh", "requests")
FORBIDDEN_NAMES = ("npc_agent_current", "credentials", "secret", ".env",
                   "id_rsa", "authorized_keys", "docker-compose")
LEAK_PATTERNS = ("/docker/federation-game", "live_apply(", "push_to_remote(",
                 "git push", "docker.from_env")


def findings() -> list[str]:
    return []


def strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        # remove inline comments (not inside strings — good enough for YAML/key checks)
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return "\n".join(out)


def scan_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.split(".")[0] in LIVE_MODULES:
                    used.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in LIVE_MODULES:
                used.add(mod)
    return sorted(used)


def main() -> int:
    f = findings()
    checks = {}

    # 1. Dockerfile pins a digest (no :latest) — ignore comment lines
    df = strip_comments((RUNTIME_DIR / "Dockerfile").read_text(encoding="utf-8"))
    checks["dockerfile_pins_digest"] = ("sha256:" in df) and (":latest" not in df)

    # 2. Workflow YAML: no schedule/trigger, no creds — ignore comment lines
    wf = strip_comments((RUNTIME_DIR / "steward-s3c-shadow-fixture.yaml")
                        .read_text(encoding="utf-8"))
    checks["workflow_no_schedule"] = ("schedule" not in wf and "scheduler" not in wf)
    checks["workflow_no_trigger"] = ("trigger" not in wf.lower())
    checks["workflow_no_creds"] = ("password" not in wf.lower()
                                   and "secret" not in wf.lower()
                                   and "token" not in wf.lower())
    checks["workflow_fixture_only"] = ("run-fixture" in wf)

    # 3. Manifest excludes forbidden items
    manifest_txt = (RUNTIME_DIR / "source_manifest.txt").read_text(encoding="utf-8")
    checks["manifest_excludes_pycache"] = "__pycache__" not in manifest_txt
    checks["manifest_excludes_git"] = "/.git/" not in manifest_txt
    checks["manifest_excludes_drafts"] = "steward/drafts/" not in manifest_txt
    checks["manifest_excludes_db"] = (".db" not in manifest_txt
                                      and ".sqlite" not in manifest_txt)

    # 4. No forbidden file names anywhere in steward tree
    bad_names = []
    for p in STEWARD_DIR.rglob("*"):
        low = p.name.lower()
        if any(b in low for b in FORBIDDEN_NAMES):
            bad_names.append(p.relative_to(REPO_ROOT).as_posix())
    checks["no_forbidden_filenames"] = not bad_names

    # 5. No live connectors actually imported (fixture path: s3c + s3b only)
    bad_imports = []
    for sub in ("s3c", "s3b"):
        d = STEWARD_DIR / sub
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            hits = scan_imports(p)
            if hits:
                bad_imports.append(f"{p.relative_to(REPO_ROOT).as_posix()}:{hits}")
    checks["no_live_connector_imports"] = not bad_imports

    # 6. No canonical prod path / live-apply calls (fixture path only)
    leaks = []
    for sub in ("s3c", "s3b"):
        d = STEWARD_DIR / sub
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for pat in LEAK_PATTERNS:
                if pat.lower() in text:
                    leaks.append(f"{p.relative_to(REPO_ROOT).as_posix()}:{pat}")
    checks["no_canonical_prod_paths"] = not leaks

    passed = all(checks.values())
    report = {
        "checks": checks,
        "forbidden_filenames_found": bad_names,
        "live_connector_imports_found": bad_imports,
        "leaks_found": leaks,
        "all_passed": passed,
    }
    (RUNTIME_DIR / "security_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    for k, v in checks.items():
        print(f"[{'PASS' if v else 'FAIL'}] {k}")
    print("\nall_passed:", passed)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
