#!/usr/bin/env python3
"""
Tier 3: Auto Restart
Checks monitor:stall_count, restarts worker container if >=4.
Cooldown prevents more than 1 restart per 15 minutes.
"""

import os
import sys
import time
import json
import subprocess
from redis_helper import (
    redis_get,
    redis_hgetall,
    redis_hset,
    redis_hset_map,
    redis_hget,
    redis_scan_iter,
    redis_ttl,
    redis_del,
    redis_set,
    redis_exists,
)

COOLDOWN_SECONDS = 900  # 15 minutes
RESTART_THRESHOLD = 15


def check():
    """One-shot check mode for cron."""
    result = run_check()
    action = result.get("action", "none")
    print(
        f"[auto_restart] {result.get('status', 'UNKNOWN')}: {result.get('summary', '')}"
    )
    if action == "restarted":
        print(f"  ACTION: Worker container restarted")
    return 0


def run_check():
    """Core logic."""
    result = {"status": "OK", "action": "none", "summary": "", "alerts": []}

    stall_count_raw = redis_get("monitor:stall_count")
    try:
        stall_count = int(stall_count_raw) if stall_count_raw else 0
    except (ValueError, TypeError):
        stall_count = 0

    if stall_count < RESTART_THRESHOLD:
        result["summary"] = (
            f"Stall count {stall_count} below threshold {RESTART_THRESHOLD}"
        )
        return result

    # Check cooldown
    last_restart = redis_get("monitor:last_auto_restart")
    now = time.time()
    if last_restart:
        try:
            elapsed = now - float(last_restart)
            if elapsed < COOLDOWN_SECONDS:
                remaining = round((COOLDOWN_SECONDS - elapsed) / 60, 1)
                result["status"] = "WARNING"
                result["summary"] = (
                    f"Stall count {stall_count} >= {RESTART_THRESHOLD} but cooldown active ({remaining} min remaining)"
                )
                result["alerts"].append(
                    f"Restart blocked by cooldown: {remaining} min remaining"
                )
                return result
        except (ValueError, TypeError):
            pass

    # Perform restart
    result["status"] = "CRITICAL"
    result["action"] = "restarted"
    result["summary"] = (
        f"Stall count {stall_count} >= {RESTART_THRESHOLD}, restarting worker"
    )
    result["alerts"].append(f"Auto-restarting worker due to stall_count={stall_count}")

    try:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "/docker/federation-game/docker-compose.yml",
                "restart",
                "worker",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Reset stall count after restart
        redis_set("monitor:stall_count", "0")
        redis_set("monitor:last_auto_restart", str(now))
        result["summary"] += " - RESTARTED OK"
    except Exception as e:
        result["summary"] += f" - RESTART FAILED: {e}"
        result["alerts"].append(f"Worker restart failed: {e}")

    # Log to Redis
    redis_hset_map(
        "monitor:auto_restart",
        {
            "status": result["status"],
            "action": result["action"],
            "summary": result["summary"],
            "stall_count": str(stall_count),
            "timestamp": str(now),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:auto_restart", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
