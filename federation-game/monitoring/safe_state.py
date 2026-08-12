#!/usr/bin/env python3
"""
Tier 3: Safe State Verifier
Verifies system health after restart (healthz, world_state numeric,
stall_count=0), sets monitor:safe_state = "VERIFIED".
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
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

BACKEND_URL = os.getenv("BACKEND_URL", "http://172.26.0.11:8000")


def check():
    """One-shot check mode for cron."""
    result = run_check()
    state = result.get("safe_state", "UNKNOWN")
    print(f"[safe_state] {result.get('status', 'UNKNOWN')}: safe_state={state}")
    for check_item in result.get("checks", []):
        icon = "OK" if check_item["ok"] else "FAIL"
        print(f"  [{icon}] {check_item['name']}: {check_item.get('detail', '')}")
    return 0 if state == "VERIFIED" else 1


def run_check():
    """Core logic."""
    result = {"status": "OK", "safe_state": "UNVERIFIED", "checks": [], "alerts": []}
    all_ok = True

    # 1. Healthz check
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 200:
                result["checks"].append(
                    {"name": "healthz", "ok": True, "detail": "200 OK"}
                )
            else:
                result["checks"].append(
                    {"name": "healthz", "ok": False, "detail": f"HTTP {resp.status}"}
                )
                all_ok = False
    except Exception as e:
        result["checks"].append(
            {"name": "healthz", "ok": False, "detail": str(e)[:100]}
        )
        all_ok = False

    # 2. World state numeric check
    world_state = redis_hgetall("world_state")
    numeric_ok = True
    numeric_keys = [
        "stability",
        "morale",
        "threat_level",
        "anomaly_activity",
        "tension_level",
        "resource_abundance",
        "treasury",
    ]
    bad_keys = []
    for key in numeric_keys:
        val = world_state.get(key)
        if val:
            try:
                float(val)
            except (ValueError, TypeError):
                numeric_ok = False
                bad_keys.append(key)
        else:
            numeric_ok = False
            bad_keys.append(f"{key}=MISSING")

    if numeric_ok:
        result["checks"].append(
            {"name": "world_state_numeric", "ok": True, "detail": "all numeric"}
        )
    else:
        result["checks"].append(
            {
                "name": "world_state_numeric",
                "ok": False,
                "detail": f"bad: {', '.join(bad_keys)}",
            }
        )
        all_ok = False

    # 3. Stall count check
    stall_count_raw = redis_get("monitor:stall_count")
    try:
        stall_count = int(stall_count_raw) if stall_count_raw else 0
    except (ValueError, TypeError):
        stall_count = -1

    if stall_count == 0:
        result["checks"].append({"name": "stall_count", "ok": True, "detail": "0"})
    else:
        result["checks"].append(
            {"name": "stall_count", "ok": False, "detail": str(stall_count)}
        )
        all_ok = False

    # 4. Worker enabled
    worker_enabled = redis_hget("worker:status", "enabled")
    if worker_enabled == "1":
        result["checks"].append({"name": "worker_enabled", "ok": True, "detail": "yes"})
    else:
        result["checks"].append({"name": "worker_enabled", "ok": False, "detail": "no"})
        all_ok = False

    # Set safe state
    if all_ok:
        result["safe_state"] = "VERIFIED"
        redis_set("monitor:safe_state", "VERIFIED")
    else:
        result["safe_state"] = "UNVERIFIED"
        redis_set("monitor:safe_state", "UNVERIFIED")
        result["status"] = "WARNING"

    result["timestamp"] = time.time()

    # Log to Redis
    redis_hset_map(
        "monitor:safe_state_check",
        {
            "safe_state": result["safe_state"],
            "checks_total": str(len(result["checks"])),
            "checks_passed": str(sum(1 for c in result["checks"] if c["ok"])),
            "timestamp": str(result["timestamp"]),
        },
    )

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
