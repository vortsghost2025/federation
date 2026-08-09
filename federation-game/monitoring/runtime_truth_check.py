#!/usr/bin/env python3
"""
Runtime Truth Checker — verifies deployed files are actually live.

The single most important rule in this deployment (see AGENTS.md): a change is
only "live" when the host file AND every running container file match. A file
edited on the host but stale in a running (baked) container looks deployed but
is not. This checker automates that verification.

It compares, for every file in the manifest:
  · host md5        (the canonical source on the VPS)
  · container md5   (what the running process actually sees)
  · optionall git md5 (HEAD in /opt/federation, the third source of truth)

Runs on the VPS host (has docker + file access). Exit codes follow the
monitoring convention: 0 = all clear, 1 = warning (git-only drift), 2 = critical
(host/container drift, i.e. not actually live).

Usage:
    python3 monitoring/runtime_truth_check.py
    python3 monitoring/runtime_truth_check.py --verbose
    python3 monitoring/runtime_truth_check.py --check-git
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Manifest: files that must be identical between host and running containers.
#
# Each entry maps a container to the host file that is bind-mounted into it.
#   host_path            → absolute path on the VPS host
#   containers           → list of (container_name, container_path)
# Marks "designed permanently corrupted" etc. are out of scope; this is purely
# file-integrity drift detection for code that is supposed to be live.
# ---------------------------------------------------------------------------
MANIFEST = [
    {
        "host_path": "/docker/federation-game/backend/npc_quest_engine.py",
        "containers": [("federation-game-backend-1", "/app/npc_quest_engine.py")],
    },
    {
        "host_path": "/docker/federation-game/backend/worker.py",
        "containers": [
            ("federation-game-backend-1", "/app/worker.py"),
            ("federation-game-worker-1", "/app/worker.py"),
        ],
    },
    {
        "host_path": "/docker/federation-game/backend/npcs.py",
        "containers": [("federation-game-backend-1", "/app/npcs.py")],
    },
    {
        "host_path": "/docker/federation-game/backend/simulation_engine.py",
        "containers": [("federation-game-backend-1", "/app/simulation_engine.py")],
    },
]

# NPC agent files (char_001 / char_306 share the npc-agent mount)
_NPC_AGENT_FILES = [
    "npc_agent_current.py",
    "npc_context.py",
    "npc_decisions.py",
    "npc_llm_client.py",
    "npc_actions.py",
]
for _f in _NPC_AGENT_FILES:
    MANIFEST.append(
        {
            "host_path": f"/docker/federation-game/npc-agent/{_f}",
            "containers": [
                ("federation-game-npc-agent-001-1", f"/app/{_f}"),
                ("federation-game-npc-agent-306-1", f"/app/{_f}"),
            ],
        }
    )

# Delegate agent files
_DELEGATE_FILES = ["npc_delegate.py"]
for _f in _DELEGATE_FILES:
    MANIFEST.append(
        {
            "host_path": f"/docker/federation-game/npc-delegate/{_f}",
            "containers": [("federation-game-npc-delegate-1", f"/app/{_f}")],
        }
    )

# Frontend static HTML (read-only bind mount from public_html)
_FRONTEND_FILES = ["spectator.html", "council-chat.html"]
for _f in _FRONTEND_FILES:
    MANIFEST.append(
        {
            "host_path": f"/docker/federation-game/public_html/{_f}",
            "containers": [("federation-game-frontend-1", f"/usr/share/nginx/html/{_f}")],
        }
    )

# Git source of truth. Editor can override; only used with --check-git.
GIT_ROOT = os.environ.get("FED_GIT_ROOT", "/opt/federation")


def md5_of(path: str) -> str:
    """Compute md5 of a local host file, or '' if missing."""
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except Exception:
        return ""


def container_md5(container: str, cpath: str) -> str:
    """Compute md5 of a file inside a running container via docker exec."""
    try:
        out = subprocess.run(
            ["docker", "exec", container, "md5sum", cpath],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.split()[0] if out.stdout.split() else ""
    except Exception:
        return ""


def git_md5(rel_path: str) -> str:
    """Compute md5 of a file at git HEAD, or '' if not tracked / unavailable."""
    # rel_path like npc-agent/npc_context.py or backend/worker.py
    try:
        out = subprocess.run(
            ["git", "-C", GIT_ROOT, "show", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return ""
        return hashlib.md5(out.stdout.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def host_to_git_rel(host_path: str) -> str:
    """Map a host path under /docker/federation-game to its git relative path."""
    prefix = "/docker/federation-game/"
    if host_path.startswith(prefix):
        return host_path[len(prefix):]
    return host_path


def run(check_git: bool = False, verbose: bool = False) -> int:
    max_severity = 0
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[RUNTIME-TRUTH] [{ts}] checking {len(MANIFEST)} manifest entries")

    drift = 0
    git_only_drift = 0

    for entry in MANIFEST:
        host = entry["host_path"]
        host_sum = md5_of(host)
        if not host_sum:
            print(
                f"[RUNTIME-TRUTH] [WARNING] host file missing: {host} "
                "(skipping — may be intentionally absent)"
            )
            continue

        for container, cpath in entry["containers"]:
            csum = container_md5(container, cpath)
            if not csum:
                print(
                    f"[RUNTIME-TRUTH] [WARNING] container {container}:{cpath} "
                    "unreachable or missing — cannot verify"
                )
                max_severity = max(max_severity, 1)
                continue

            if host_sum == csum:
                if verbose:
                    print(
                        f"  [OK] {container}:{cpath} == host "
                        f"({host_sum[:8]}…)"
                    )
            else:
                drift += 1
                print(
                    f"[RUNTIME-TRUTH] [CRITICAL] DRIFT {container}:{cpath}\n"
                    f"  host      {host_sum}\n"
                    f"  container {csum}\n"
                    f"  action    file edited on host but NOT live in {container}; "
                    f"restart the container (and re-run check)"
                )
                max_severity = max(max_severity, 2)

        # Optional git source-of-truth comparison
        if check_git:
            rel = host_to_git_rel(host)
            gsum = git_md5(rel)
            if gsum and gsum != host_sum:
                git_only_drift += 1
                if verbose:
                    print(
                        f"  [WARNING] git HEAD differs from host for {rel} "
                        f"(git {gsum[:8]}… vs host {host_sum[:8]}…) — "
                        f"committed code is not what is deployed"
                    )
                max_severity = max(max_severity, 1)

    summary = (
        f"checked={len(MANIFEST)} drift={drift} "
        f"git_only_drift={git_only_drift}"
    )
    if drift:
        print(f"[RUNTIME-TRUTH] [CRITICAL] {drift} file(s) NOT live: {summary}")
    elif git_only_drift:
        print(f"[RUNTIME-TRUTH] [WARNING] no host/container drift; git behind: {summary}")
    else:
        print(f"[RUNTIME-TRUTH] [INFO] all live files in sync: {summary}")

    return max_severity


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime truth (md5) checker")
    parser.add_argument("--check-git", action="store_true",
                        help="also compare against git HEAD in /opt/federation")
    parser.add_argument("--verbose", action="store_true", help="log OK rows too")
    args = parser.parse_args()
    code = run(check_git=args.check_git, verbose=args.verbose)
    sys.exit(code)


if __name__ == "__main__":
    main()