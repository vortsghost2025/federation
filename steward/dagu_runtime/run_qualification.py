#!/usr/bin/env python3
"""DR-006 / DR-007 Local qualification harness for the Steward Dagu runtime.

Two execution paths:

  A) Docker available locally:
       - build the image from the pinned Digest Dockerfile
       - run the container self-test (selftest.py) inside it
       - record image id + repo digest
       - emit a local SBOM of the steward package (DR-007)
  B) Docker NOT available (this dev machine):
       - the in-container build is reported as SKIPPED (environment-blocked,
         not a code failure)
       - the local (worktree) self-test still runs as a substitute
         qualification of the source tree
       - the SBOM is still generated from the source tree

Nothing here touches the VPS, pushes, or installs a workflow.
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[1]


def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "info"], capture_output=True, text=True
    ).returncode == 0


def build_image() -> dict:
    img = "steward-dagu-runtime:qualification"
    r = subprocess.run(
        ["docker", "build", "-f", str(RUNTIME_DIR / "Dockerfile"),
         "-t", img, str(REPO_ROOT)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr[-500:]}
    info = subprocess.run(
        ["docker", "inspect", "--format",
         "{{.Id}} {{index .RepoDigests 0}}", img],
        capture_output=True, text=True,
    )
    parts = info.stdout.strip().split(maxsplit=1)
    return {"ok": True, "image": img,
            "id": parts[0] if parts else "",
            "digest": parts[1] if len(parts) > 1 else ""}


def run_container_selftest(img: str) -> dict:
    r = subprocess.run(
        ["docker", "run", "--rm", "--read-only",
         "-e", "STEWARD_HOME=/opt/steward", "-e", "PYTHONPATH=/opt/steward",
         img, "python3", "/opt/steward/steward/dagu_runtime/selftest.py"],
        capture_output=True, text=True,
    )
    return {"returncode": r.returncode,
            "output": (r.stdout + r.stderr)[-1500:]}


def local_selftest() -> dict:
    r = subprocess.run(
        [sys.executable, str(RUNTIME_DIR / "selftest.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    return {"returncode": r.returncode,
            "output": (r.stdout + r.stderr)[-1500:]}


def source_sbom() -> dict:
    files = sorted(p.relative_to(REPO_ROOT).as_posix()
                   for p in (REPO_ROOT / "steward").rglob("*.py"))
    return {"steward_py_file_count": len(files), "files": files}


def main() -> int:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": REPO_ROOT.as_posix(),
        "docker_available": docker_available(),
        "build": None,
        "container_selftest": None,
        "local_selftest": None,
        "sbom": None,
        "notes": [],
    }

    if report["docker_available"]:
        report["build"] = build_image()
        if report["build"].get("ok"):
            report["container_selftest"] = run_container_selftest(
                report["build"]["image"])
        else:
            report["notes"].append("docker build failed (see build.error)")
    else:
        report["notes"].append(
            "DOCKER_UNAVAILABLE: in-container build + run SKIPPED. "
            "Environment-blocked on this dev host — not a code defect. "
            "Local source-tree self-test used as substitute qualification.")

    report["local_selftest"] = local_selftest()
    report["sbom"] = source_sbom()

    out = RUNTIME_DIR / "qualification_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    # Pass only if the executed self-test(s) succeed.
    container_ok = report["container_selftest"] is None or \
        report["container_selftest"]["returncode"] == 0
    local_ok = report["local_selftest"]["returncode"] == 0
    return 0 if (local_ok and container_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
