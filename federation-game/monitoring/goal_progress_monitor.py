#!/usr/bin/env python3
"""
Goal Progress Tracker.

Runs on the VPS host (has docker access). Each cycle it:
  1. Reads the durable completed-goals ledger for the councilor pair.
  2. Checks whether the pair is progressing through genuinely distinct
     objectives (novelty) or re-entering the same families.
  3. Reports stalled goals / lack of new completions to a state file for the
     supervisor + Hermes digest.

Exit codes (dagu convention):
  0 = healthy (progressing, or valid cooldown)
  1 = WARNING (no completion in a long time / possible stall)
  2 = CRITICAL (repeated re-entry into the same blocked families)

Usage:
    python3 monitoring/goal_progress_monitor.py
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = "/docker/federation-game"
REDIS = ["docker", "exec", "federation-game-redis-1", "redis-cli"]
PAIR = "npc_pair:char_001__char_306"
COMPLETED_KEY = f"{PAIR}:completed_goals"
STALL_MINUTES = int(os.environ.get("GOAL_STALL_MINUTES", "240"))
KNOWN_BLOCKED = [
    "structured resonance lattice", "corruption-linked resonance",
    "anchor network", "resonance", "lattice",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rd(*args):
    try:
        out = subprocess.run(REDIS + list(args), capture_output=True, text=True, timeout=15)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _recent_goals(limit=20):
    raw = rd("LRANGE", COMPLETED_KEY, f"{-limit}", "-1")
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def main():
    goals = _recent_goals()
    report = {
        "ts": now_iso(),
        "completed_goal_count": len(goals),
        "goals": [g.get("goal", "?")[:100] for g in goals[-5:]],
    }

    # Novelty / stall analysis.
    warning = None
    critical = None
    if goals:
        last_ts = goals[-1].get("resolved_at", 0)
        age_hours = (time.time() - int(last_ts)) / 3600 if last_ts else None
        report["last_completion_age_hours"] = round(age_hours, 2) if age_hours is not None else None
        if age_hours is not None and age_hours * 60 > STALL_MINUTES:
            warning = f"No goal completion in {age_hours:.1f}h (stall threshold {STALL_MINUTES}m)"

        # Re-entry analysis: do recent goals re-enter known blocked families?
        recent_text = " ".join((g.get("goal", "") or "").lower() for g in goals[-5:])
        re_entries = [t for t in KNOWN_BLOCKED if t in recent_text]
        if re_entries:
            critical = f"Recent goals re-enter blocked families: {re_entries}"
            report["re_entered_families"] = re_entries
    else:
        report["last_completion_age_hours"] = None
        warning = "No completed goals recorded yet"

    print(json.dumps(report, indent=2))

    try:
        os.makedirs(f"{BASE}/monitoring/supervisor_state", exist_ok=True)
        with open(f"{BASE}/monitoring/supervisor_state/goal_progress.json", "w") as fh:
            json.dump(report, fh, indent=2)
    except Exception as e:
        print(f"WARN: could not write state file: {e}")

    try:
        rd("SET", "fed:goal:report", json.dumps(report), "EX", "3600")
    except Exception:
        pass

    if critical:
        print(f"CRITICAL: {critical}")
        return 2
    if warning:
        print(f"WARNING: {warning}")
        return 1
    print("OK: pair progressing through distinct goals")
    return 0


if __name__ == "__main__":
    sys.exit(main())