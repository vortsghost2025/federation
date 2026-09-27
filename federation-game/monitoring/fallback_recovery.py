#!/usr/bin/env python3
"""
Tier 3: Fallback Recovery
If monitor:llm_health < 20 on TWO consecutive checks, clears all LLM keys
and restarts worker. Nuclear option for when the system is completely broken.

Two-strike rule (2026-09-27): a single sub-threshold reading only logs a
WARNING and records a strike (TTL 1h). The nuclear path requires a second
consecutive sub-threshold reading, so transient NIM circuit-trip dips that
self-heal within minutes no longer restart mid-tick workers. Healthy reads
clear the strike counter.
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
    redis_expire,
    redis_incr,
)

HEALTH_THRESHOLD = 20
COOLDOWN_SECONDS = 1800  # 30 minutes between nuclear resets
STRIKE_KEY = "monitor:nuclear_strikes"
STRIKES_REQUIRED = 2  # consecutive sub-threshold checks before nuclear
STRIKE_TTL_SECONDS = 3600  # stale strikes expire after 1h


def check():
    """One-shot check mode for cron."""
    result = run_check()
    action = result.get("action", "none")
    status = result.get("status", "UNKNOWN")
    print(f"[fallback_recovery] {status}: {result.get('summary', '')}")
    if action == "nuclear_reset":
        print(f"  ACTION: Nuclear reset performed")
    return 0


def run_check():
    """Core logic."""
    result = {"status": "OK", "action": "none", "summary": "", "alerts": []}
    now = time.time()

    # Read LLM health
    llm_data = redis_hgetall("monitor:llm_health")
    try:
        health = int(llm_data.get("health_score", 100))
    except (ValueError, TypeError):
        health = 100

    if health >= HEALTH_THRESHOLD:
        # Healthy: clear any pending strikes and report OK (unchanged path).
        redis_del(STRIKE_KEY)
        result["summary"] = f"LLM health {health} above threshold {HEALTH_THRESHOLD}"
        return result

    # Sub-threshold: record a strike (expires after STRIKE_TTL_SECONDS so a
    # lone dip hours ago cannot combine with a fresh one into a firing).
    strikes = redis_incr(STRIKE_KEY)
    redis_expire(STRIKE_KEY, STRIKE_TTL_SECONDS)

    if strikes < STRIKES_REQUIRED:
        # First strike: watch only. No key clearing, no restart.
        result["status"] = "WARNING"
        result["action"] = "watch"
        result["summary"] = (
            f"LLM health {health} < {HEALTH_THRESHOLD} - "
            f"strike {strikes}/{STRIKES_REQUIRED}, watching (no action)"
        )
        result["alerts"].append(
            f"First sub-threshold reading (llm_health={health}); "
            f"nuclear reset requires {STRIKES_REQUIRED} consecutive strikes"
        )
        redis_hset_map(
            "monitor:fallback_recovery",
            {
                "status": result["status"],
                "action": result["action"],
                "summary": result["summary"],
                "llm_health": str(health),
                "strikes": str(strikes),
                "timestamp": str(now),
            },
        )
        return result

    # Check cooldown
    last_nuclear = redis_get("monitor:last_nuclear_reset")
    if last_nuclear:
        try:
            elapsed = now - float(last_nuclear)
            if elapsed < COOLDOWN_SECONDS:
                remaining = round((COOLDOWN_SECONDS - elapsed) / 60, 1)
                result["status"] = "WARNING"
                result["summary"] = (
                    f"LLM health {health} < {HEALTH_THRESHOLD} but nuclear cooldown active ({remaining} min)"
                )
                result["alerts"].append(
                    f"Nuclear reset blocked by cooldown: {remaining} min"
                )
                return result
        except (ValueError, TypeError):
            pass

    # Nuclear reset
    result["status"] = "CRITICAL"
    result["action"] = "nuclear_reset"
    result["summary"] = (
        f"LLM health {health} < {HEALTH_THRESHOLD} - performing nuclear reset"
    )
    result["alerts"].append(f"Nuclear reset triggered by llm_health={health}")

    # Clear all LLM keys (single --scan pass per pattern via redis_helper)
    cleared = 0
    for pattern in [
        "llm_circuit_breaker:*",
        "llm_circuit_failures:*",
        "llm_errors:*",
        "llm_circuit_created:*",
    ]:
        for key in redis_scan_iter(pattern):
            redis_del(key)
            cleared += 1

    result["alerts"].append(f"Cleared {cleared} LLM keys")

    # Restart worker
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
        result["summary"] += " - WORKER RESTARTED"
    except Exception as e:
        result["summary"] += f" - WORKER RESTART FAILED: {e}"
        result["alerts"].append(f"Worker restart failed: {e}")

    # Fresh confirmation required for any future episode: reset strikes now
    # that the nuclear path has been entered (success or failure).
    redis_del(STRIKE_KEY)
    redis_set("monitor:last_nuclear_reset", str(now))

    # Log
    redis_hset_map(
        "monitor:fallback_recovery",
        {
            "status": result["status"],
            "action": result["action"],
            "summary": result["summary"],
            "llm_health": str(health),
            "keys_cleared": str(cleared),
            "strikes": str(strikes),
            "timestamp": str(now),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:fallback_recovery", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
