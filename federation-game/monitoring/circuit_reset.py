#!/usr/bin/env python3
"""
Tier 3: Circuit Reset
Clears stale circuit breakers (TTL > 5 min AND age > 15 min),
logs resets to monitor:circuit_resets.
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

MIN_TTL = 300  # 5 minutes - key has been around at least this long
MIN_AGE = 900  # 15 minutes - breaker has been tripped at least this long


def check():
    """One-shot check mode for cron."""
    result = run_check()
    reset_count = result.get("resets", 0)
    status = result.get("status", "UNKNOWN")
    print(f"[circuit_reset] {status}: {reset_count} stale breakers cleared")
    for a in result.get("alerts", []):
        print(f"  ALERT: {a}")
    return 0


def run_check():
    """Core logic."""
    result = {"status": "OK", "resets": 0, "alerts": [], "data": {}}
    now = time.time()

    breaker_keys = list(redis_scan_iter("llm_circuit_breaker:*"))
    reset_providers = []

    for key in breaker_keys:
        val = redis_get(key)
        if val and val.lower() not in ("1", "true", "open", "tripped"):
            continue  # Not actually tripped

        provider = key.split(":")[-1]

        # Check TTL - only reset keys that have been around a while
        ttl = redis_ttl(key)
        if ttl == -1:  # No expiry set
            # Check when it was set via the failures key
            fail_key = f"llm_circuit_failures:{provider}"
            fail_val = redis_get(fail_key)
            if fail_val:
                try:
                    fail_count = int(fail_val)
                    # If no TTL and failures exist, it's stale - clear it
                    redis_del(key)
                    redis_del(fail_key)
                    error_key = f"llm_errors:{provider}"
                    redis_del(error_key)
                    reset_providers.append(provider)
                except (ValueError, TypeError):
                    pass
        elif ttl == -2:  # Key doesn't exist anymore
            continue
        # Keys with TTL > 5 min that are still tripped after 15 min
        elif ttl > MIN_TTL:
            # The breaker has a long TTL remaining, meaning it was recently set
            # Check if the breaker has been around long enough
            created_key = f"llm_circuit_created:{provider}"
            created = redis_get(created_key)
            if created:
                try:
                    age = now - float(created)
                    if age > MIN_AGE:
                        redis_del(key)
                        redis_del(f"llm_circuit_failures:{provider}")
                        redis_del(f"llm_errors:{provider}")
                        redis_del(created_key)
                        reset_providers.append(provider)
                except (ValueError, TypeError):
                    pass

    result["resets"] = len(reset_providers)
    result["data"]["reset_providers"] = reset_providers

    if reset_providers:
        result["alerts"].append(f"Reset stale breakers: {', '.join(reset_providers)}")

    # Write to Redis
    redis_hset_map(
        "monitor:circuit_resets",
        {
            "resets": str(result["resets"]),
            "providers": ",".join(reset_providers) if reset_providers else "none",
            "last_reset": str(now),
            "timestamp": str(now),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:circuit_resets", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
