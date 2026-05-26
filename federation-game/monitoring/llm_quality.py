#!/usr/bin/env python3
"""
Tier 2: LLM Quality Monitor
Checks llm_circuit_breaker:* keys, calculates health score based on
tripped breakers, writes to monitor:llm_health.
"""

import os
import sys
import time
import json
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


def check():
    """One-shot check mode for cron."""
    result = run_check()
    score = result.get("health_score", 0)
    status = result.get("status", "UNKNOWN")
    print(f"[llm_quality] {status}: LLM health score = {score}/100")
    for a in result.get("alerts", []):
        print(f"  ALERT: {a}")
    return 0 if status != "CRITICAL" else 1


def run_check():
    """Core logic — reusable by health_dashboard."""
    result = {"status": "OK", "health_score": 100, "alerts": [], "data": {}}

    # Scan all circuit breaker keys
    breaker_keys = list(redis_scan_iter("llm_circuit_breaker:*"))
    failure_keys = list(redis_scan_iter("llm_circuit_failures:*"))
    error_keys = list(redis_scan_iter("llm_errors:*"))

    tripped = []
    for key in breaker_keys:
        val = redis_get(key)
        if val and val.lower() in ("1", "true", "open", "tripped"):
            provider = key.split(":")[-1]
            tripped.append(provider)

    failures = {}
    for key in failure_keys:
        val = redis_get(key)
        provider = key.split(":")[-1]
        try:
            failures[provider] = int(val) if val else 0
        except (ValueError, TypeError):
            failures[provider] = 0

    errors = {}
    for key in error_keys:
        provider = key.split(":")[-1]
        ttl = redis_ttl(key)
        errors[provider] = {"has_errors": True, "ttl": ttl}

    result["data"]["total_providers_monitored"] = len(breaker_keys)
    result["data"]["tripped_breakers"] = tripped
    result["data"]["failure_counts"] = failures

    # Calculate health score
    # Each tripped breaker reduces score; 3+ tripped = critical
    total_breakers = max(len(breaker_keys), 1)
    tripped_count = len(tripped)
    result["health_score"] = max(0, round(100 * (1 - tripped_count / total_breakers)))

    if tripped_count >= 3:
        result["status"] = "CRITICAL"
        result["alerts"].append(
            f"{tripped_count} circuit breakers tripped: {', '.join(tripped)}"
        )
    elif tripped_count >= 1:
        result["status"] = "WARNING"
        result["alerts"].append(
            f"{tripped_count} circuit breaker(s) tripped: {', '.join(tripped)}"
        )

    # Write to Redis
    redis_hset_map(
        "monitor:llm_health",
        {
            "health_score": str(result["health_score"]),
            "status": result["status"],
            "tripped_count": str(tripped_count),
            "tripped_providers": ",".join(tripped) if tripped else "none",
            "total_monitored": str(len(breaker_keys)),
            "timestamp": str(time.time()),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:llm_health", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
