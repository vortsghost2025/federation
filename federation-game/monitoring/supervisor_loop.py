#!/usr/bin/env python3
"""
Supervisor Loop — the 24/7 driver for the autonomous build architecture.

This is the "brain" that keeps the agent (Kilo) working even when the operator
is away. It runs continuously, watches the live world, and maintains a
task queue + status ledger that the agent consumes.

What it does each cycle:
  1. Runtime-truth check  — host vs container md5 drift (from runtime_truth_check)
  2. Tick health          — is the simulation advancing? any new [ERROR]s?
  3. Task queue           — append actionable findings to tasks/queue.json
  4. Status ledger        — write a compact status snapshot for the agent

It is deliberately READ-ONLY with respect to the game world: it never mutates
world_state or deploys. It only records findings and tasks. The agent (or an
operator-approved automation layer) performs the actual changes. This keeps the
supervisor safe to run unattended.

Usage:
    python3 monitoring/supervisor_loop.py            # single cycle
    python3 monitoring/supervisor_loop.py --loop     # run forever (Ctrl-C to stop)
    python3 monitoring/supervisor_loop.py --interval 60 --loop
"""

import argparse
import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = "/docker/federation-game"
STATE_DIR = f"{BASE}/monitoring/supervisor_state"
QUEUE_FILE = f"{STATE_DIR}/queue.json"
STATUS_FILE = f"{STATE_DIR}/status.json"
RUNTIME_TRUTH = f"{BASE}/monitoring/runtime_truth_check.py"

CONTAINERS = [
    "federation-game-backend-1",
    "federation-game-worker-1",
    "federation-game-npc-agent-001-1",
    "federation-game-npc-agent-306-1",
    "federation-game-npc-delegate-1",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(QUEUE_FILE):
        _write_json(QUEUE_FILE, [])


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def run(cmd_list, timeout=30) -> str:
    try:
        out = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return str(e)


def runtime_truth_status(verbose=False) -> dict:
    """Run the runtime-truth checker and return its exit code + summary line."""
    cmd = [sys_python(), RUNTIME_TRUTH]
    if verbose:
        cmd.append("--verbose")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        last = [l for l in out.stdout.strip().splitlines() if l.strip()][-1]
        return {"exit": out.returncode, "summary": last}
    except Exception as e:
        return {"exit": -1, "summary": f"runtime-truth failed: {e}"}


def sys_python() -> str:
    return shlex.quote(os.environ.get("PYTHON", "python3"))


def check_containers() -> list:
    """Return list of up/healthy container names; flag any unexpected state."""
    state = run(["docker", "ps", "--format", "{{.Names}}\\t{{.Status}}"])
    issues = []
    for line in state.splitlines():
        name, _, status = line.partition("\t")
        if name in CONTAINERS and "Up" not in status:
            issues.append(f"{name}: {status}")
    return issues


def check_tick_health() -> dict:
    """Check fed:auto_tick_status for tick liveness and errors.

    Distinguishes three cases:
      · ok              — last_result parsed and has no errors
      · no_result       — last_result empty/absent (tick finished, result not
                          stored yet, or auto-tick writes elsewhere) — benign
      · error           — last_result present and carries errors
    Also surfaces last_error if the last tick failed.
    """
    def hget(field):
        return run(
            ["docker", "exec", "federation-game-redis-1", "redis-cli",
             "HGET", "fed:auto_tick_status", field]
        ).strip()

    running = hget("running")
    last_error = hget("last_error")
    raw = hget("last_result")

    if last_error:
        return {"ok": False, "detail": f"last_error: {last_error[:300]}"}

    if not raw:
        # No result stored — not necessarily a failure. If the tick is running
        # it's expected; if idle and it finished long ago, treat as benign but
        # note it so the operator/agent can confirm the ticker is alive.
        return {"ok": True, "detail": "no last_result stored",
                "running": running == "True"}

    try:
        data = json.loads("".join(raw.splitlines()))
    except Exception:
        return {"ok": True, "detail": "last_result present but unparseable",
                "running": running == "True"}
    errors = data.get("errors", [])
    return {"ok": not errors, "errors": errors, "detail": "ok"}


def scan_backend_errors(window=200) -> list:
    """Scan backend logs for recent [ERROR] lines."""
    out = run(
        ["docker", "logs", "--tail", str(window), "federation-game-backend-1"]
    )
    errors = [l for l in out.splitlines() if "ERROR" in l or "Traceback" in l]
    return errors[-10:]


def append_task(category, title, detail, priority="normal"):
    """Add a task to the queue if an identical pending one doesn't exist."""
    queue = _read_json(QUEUE_FILE, [])
    for t in queue:
        if t.get("category") == category and t.get("title") == title and not t.get("done"):
            return False
    queue.append({
        "id": f"{int(time.time())}-{len(queue)+1}",
        "category": category,
        "title": title,
        "detail": detail,
        "priority": priority,
        "created_at": now_iso(),
        "done": False,
        "resolved_at": None,
    })
    _write_json(QUEUE_FILE, queue)
    return True


def cycle(verbose=False) -> dict:
    ensure_state()

    # 1. Runtime truth
    truth = runtime_truth_status(verbose=verbose)
    if truth["exit"] == 2:
        append_task(
            "runtime_drift",
            "Host/container file drift detected",
            truth["summary"],
            priority="high",
        )

    # 2. Containers
    container_issues = check_containers()
    for issue in container_issues:
        append_task("container", "Container not healthy", issue, priority="high")

    # 3. Tick health
    tick = check_tick_health()
    if not tick.get("ok"):
        append_task(
            "tick", "Auto-tick reported errors",
            tick.get("detail", "no parseable last_result"),
            priority="high",
        )
    elif not tick.get("running") and "no last_result" in tick.get("detail", ""):
        append_task(
            "tick", "Ticker appears idle (no last_result, not running)",
            "Confirm the simulation scheduler is alive; last tick may have "
            "finished without storing a result.",
            priority="medium",
        )

    # 4. Backend errors
    backend_errors = scan_backend_errors()
    if backend_errors:
        append_task(
            "backend_errors",
            f"{len(backend_errors)} recent backend error lines",
            "; ".join(backend_errors[-3:]),
            priority="medium",
        )

    snapshot = {
        "ts": now_iso(),
        "runtime_truth": truth,
        "container_issues": container_issues,
        "tick_ok": tick.get("ok"),
        "backend_error_count": len(backend_errors),
        "queue": _read_json(QUEUE_FILE, [])[-20:],
    }
    _write_json(STATUS_FILE, snapshot)
    return snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="run forever")
    ap.add_argument("--interval", type=int, default=300, help="seconds between cycles")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.loop:
        snap = cycle(verbose=args.verbose)
        print(json.dumps(snap, indent=2))
        return

    print(f"[supervisor] starting loop, interval={args.interval}s "
          f"(stop with Ctrl-C)")
    while True:
        try:
            snap = cycle(verbose=args.verbose)
            print(f"[supervisor] {snap['ts']} truth_exit={snap['runtime_truth']['exit']} "
                  f"tick_ok={snap['tick_ok']} backend_errors={snap['backend_error_count']} "
                  f"queued={sum(1 for t in snap['queue'] if not t['done'])}")
        except KeyboardInterrupt:
            print("[supervisor] stopping")
            break
        except Exception as e:
            print(f"[supervisor] cycle error: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()