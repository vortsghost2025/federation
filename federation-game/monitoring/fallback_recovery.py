#!/usr/bin/env python3
"""
Tier 3: Fallback Recovery
If monitor:llm_health < 20, clears all LLM keys and restarts worker.
Nuclear option for when the system is completely broken.
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

HEALTH_THRESHOLD = 20
COOLDOWN_SECONDS = 1800  # 30 minutes between nuclear resets


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
        result["summary"] = f"LLM health {health} above threshold {HEALTH_THRESHOLD}"
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

    # Clear all LLM keys
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
