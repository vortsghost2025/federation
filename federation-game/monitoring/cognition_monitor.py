#!/usr/bin/env python3
"""Lightweight cognition monitor for the Federation Game.

Watches the two real signals from the cognition-config change:
  1. LEADER COGNITION ELEVATION — how many faction leaders are cognized per
     tick in the recent window (baseline was ~1; the config raised this).
  2. RATE-LIMIT BURST FREQUENCY — whether NVIDIA "All keys rate-limited" hits
     are clustering into saturation (bad) or staying benign-sporadic (ok).
Plus a tick-health sanity check (are ticks still completing with 0 errors?).

Read-only. Safe to run from cron (no writes to runtime state; only appends
to a log file). Exit 0 always; prints a one-line STATUS summarizing verdicts.
"""
import datetime
import re
import subprocess
import sys
import time

WINDOW_MIN = 120  # how far back to look for cognition lines
BACKEND = "federation-game-backend-1"


def run(cmd):
    try:
        # docker logs writes to stderr; merge both streams so nothing is lost.
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return str(e)


def since_logs(container, minutes):
    # NOTE: do NOT append "2>&1" here — run() already merges stdout+stderr in
    # Python via capture_output. Passing "2>&1" as a literal list element makes
    # docker reject the command (rc=1) and the monitor reads only the usage error.
    return run(["docker", "logs", "--since", f"{minutes}m", container])


def parse_cognition(log):
    """Return (ticks_seen, elevated_count, max_leaders, errors_seen)."""
    # Cognition lines look like: Cognition tick: 6 leaders, 1 specialists, ... 0 errors
    lines = [l for l in log.splitlines() if "Cognition tick" in l]
    ticks = 0
    elevated = 0
    max_leaders = 0
    errors = 0
    leader_re = re.compile(r"Cognition tick:\s*(\d+)\s+leaders")
    err_re = re.compile(r"Cognition tick:.*?(\d+)\s+errors")
    for ln in lines:
        ticks += 1
        m = leader_re.search(ln)
        if m:
            n = int(m.group(1))
            max_leaders = max(max_leaders, n)
            if n > 1:
                elevated += 1
        e = err_re.search(ln)
        if e:
            errors += int(e.group(1))
    return ticks, elevated, max_leaders, errors


def count_rate_limits(log):
    lines = [l for l in log.splitlines() if re.search(r"ALL KEYS rate.limited|resource.?exhausted", l, re.I)]
    return len(lines)


def tick_health(log):
    """Return (completions, errors_in_last) or (0, -1) if none."""
    comp = [l for l in log.splitlines() if "Tick complete" in l]
    if not comp:
        return 0, -1
    errs = [int(m.group(1)) for l in comp for m in [re.search(r"Tick complete:.*?(\d+)\s+errors", l)] if m]
    last_errors = errs[-1] if errs else -1
    return len(comp), last_errors


def hhmm():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    log = since_logs(BACKEND, WINDOW_MIN)

    ticks, elevated, max_leaders, c_errors = parse_cognition(log)
    rl = count_rate_limits(log)
    completed, last_errors = tick_health(log)

    # Staleness: did any tick complete recently? If tick_health returned 0
    # completions we can't tell; fall back to whether cognition lines exist.
    signals = []

    # 1) Leader cognition elevation
    if ticks == 0:
        signals.append(("cognition", "NO-RECENT-COGNITION-LINES"))
    elif elevated >= 1:
        signals.append(("cognition", f"ELEVATED max={max_leaders} elevated_ticks={elevated}/{ticks}"))
    else:
        signals.append(("cognition", f"BASELINE max={max_leaders} (1 per tick)"))

    # 2) Rate-limit burst frequency
    rl_per_min = rl / WINDOW_MIN
    if rl_per_min >= 1.0 or (rl >= 10 and max_leaders > 1):
        signals.append(("rate-limit", f"HIGH rl_hits={rl} in {WINDOW_MIN}m (~{rl_per_min:.1f}/min)"))
    elif rl > 0:
        signals.append(("rate-limit", f"MODERATE rl_hits={rl} in {WINDOW_MIN}m"))
    else:
        signals.append(("rate-limit", "NONE"))

    # 3) Tick health
    if last_errors == -1:
        signals.append(("tick", "NO-COMPLETIONS-LOGGED"))
    elif last_errors == 0:
        signals.append(("tick", f"HEALTHY ({completed} completions, last errors=0)"))
    else:
        signals.append(("tick", f"ERRORS ({completed} completions, last errors={last_errors})"))

    status = " | ".join(f"{k}={v}" for k, v in signals)
    line = f"{hhmm()} {status} (cognition_errors={c_errors})"
    print(line)
    # Persist a rolling log
    try:
        with open("/var/log/federation/cognition_monitor.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

    # No alarming exit: this is an observability probe, not a pager.
    # A sticky HIGH rate-limit or cognition errors is surfaced in the line.
    return 0


if __name__ == "__main__":
    sys.exit(main())
