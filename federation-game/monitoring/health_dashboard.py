#!/usr/bin/env python3
"""
Tier 2: Health Dashboard Aggregator
Aggregates all monitor:* keys into monitor:dashboard JSON,
outputs human-readable status report.
"""

import os
import sys
import time
import json
from redis_helper import redis_get, redis_hgetall, redis_hset, redis_hset_map, redis_hget, redis_scan_iter, redis_ttl, redis_del, redis_set, redis_exists

def check():
    """One-shot check mode for cron."""
    result = run_check()
    status = result.get("overall_status", "UNKNOWN")
    print(f"[health_dashboard] Overall: {status}")
    print(f"  Summary: {result.get('summary', '')}")
    for comp in result.get("components", []):
        icon = (
            "OK"
            if comp["status"] == "OK"
            else "!!"
            if comp["status"] == "WARNING"
            else "XX"
        )
        print(f"  [{icon}] {comp['name']}: {comp.get('detail', '')}")
    return 0 if status != "CRITICAL" else 1


def run_check():
    """Core logic."""
    result = {
        "overall_status": "OK",
        "summary": "",
        "components": [],
        "timestamp": time.time(),
    }

    # Collect all monitor keys
    components = []

    # 1. Stall count
    stall_count = redis_get("monitor:stall_count")
    try:
        stall = int(stall_count) if stall_count else 0
    except (ValueError, TypeError):
        stall = 0
    stall_status = "OK" if stall < 3 else "WARNING" if stall < 4 else "CRITICAL"
    components.append(
        {
            "name": "tick_stalls",
            "status": stall_status,
            "detail": f"stall_count={stall}",
        }
    )

    # 2. QA score
    qa_data = redis_hgetall("monitor:qa_score")
    qa_score = qa_data.get("score", "N/A")
    qa_status = qa_data.get("status", "UNKNOWN")
    components.append(
        {
            "name": "qa_quality",
            "status": qa_status if qa_status in ("OK", "WARNING", "CRITICAL") else "OK",
            "detail": f"score={qa_score}",
        }
    )

    # 3. LLM health
    llm_data = redis_hgetall("monitor:llm_health")
    llm_score = llm_data.get("health_score", "N/A")
    llm_status = llm_data.get("status", "UNKNOWN")
    components.append(
        {
            "name": "llm_health",
            "status": llm_status
            if llm_status in ("OK", "WARNING", "CRITICAL")
            else "OK",
            "detail": f"score={llm_score}, tripped={llm_data.get('tripped_providers', 'none')}",
        }
    )

    # 4. Live narration
    narr_data = redis_hgetall("monitor:live_narration")
    narr_status = narr_data.get("status", "UNKNOWN")
    narr_age = narr_data.get("narration_age", "N/A")
    components.append(
        {
            "name": "narration",
            "status": narr_status
            if narr_status in ("OK", "WARNING", "CRITICAL")
            else "OK",
            "detail": f"age={narr_age}s",
        }
    )

    # 5. Worker status
    worker_data = redis_hgetall("worker:status")
    last_tick = worker_data.get("last_tick", "NEVER")
    worker_enabled = worker_data.get("enabled", "0")
    components.append(
        {
            "name": "worker",
            "status": "OK" if worker_enabled == "1" else "CRITICAL",
            "detail": f"last_tick={last_tick}",
        }
    )

    # 6. Circuit resets
    circuit_data = redis_hgetall("monitor:circuit_resets")
    last_reset = circuit_data.get("last_reset", "never")
    components.append(
        {
            "name": "circuit_resets",
            "status": "OK",
            "detail": f"last_reset={last_reset}",
        }
    )

    # 7. Safe state
    safe_state = redis_get("monitor:safe_state")
    components.append(
        {
            "name": "safe_state",
            "status": "OK" if safe_state == "VERIFIED" else "WARNING",
            "detail": f"state={safe_state or 'NOT_SET'}",
        }
    )

    result["components"] = components

    # Determine overall status
    statuses = [c["status"] for c in components]
    if "CRITICAL" in statuses:
        result["overall_status"] = "CRITICAL"
    elif "WARNING" in statuses:
        result["overall_status"] = "WARNING"
    else:
        result["overall_status"] = "OK"

    ok_count = statuses.count("OK")
    result["summary"] = f"{ok_count}/{len(statuses)} components OK"

    # Write dashboard to Redis
    redis_set("monitor:dashboard", json.dumps(result))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
