#!/usr/bin/env python3
"""
Tier 2: Live Narrator Monitor
Reads narration:latest and npc_thoughts for faction leaders,
produces plain-English summary, writes to monitor:live_narration.
Alerts if narration is stale (>10 min).
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

STALE_THRESHOLD = 600  # 10 minutes in seconds


def check():
    """One-shot check mode for cron."""
    result = run_check()
    status = result.get("status", "UNKNOWN")
    summary = result.get("summary", "No summary")
    alerts = result.get("alerts", [])
    print(f"[live_narrator] {status}: {summary}")
    for a in alerts:
        print(f"  ALERT: {a}")
    return 0 if status != "CRITICAL" else 1


def run_check():
    """Core logic — reusable by health_dashboard."""
    result = {"status": "OK", "summary": "", "alerts": [], "data": {}}

    # Check narration freshness
    narration_raw = redis_get("narration:latest")
    narration_ts = redis_get("narration:timestamp")
    now = time.time()

    if narration_raw:
        try:
            narration = json.loads(narration_raw)
            result["data"]["narration_preview"] = str(
                narration.get("text", narration_raw)
            )[:200]
        except (json.JSONDecodeError, AttributeError):
            result["data"]["narration_preview"] = str(narration_raw)[:200]
    else:
        result["data"]["narration_preview"] = "NONE"

    # Check staleness
    if narration_ts:
        try:
            age = now - float(narration_ts)
            result["data"]["narration_age_seconds"] = round(age, 1)
            if age > STALE_THRESHOLD:
                result["alerts"].append(
                    f"Narration stale: {round(age / 60, 1)} min old"
                )
                result["status"] = "WARNING"
        except (ValueError, TypeError):
            result["data"]["narration_age_seconds"] = -1
    else:
        result["alerts"].append("No narration timestamp found")
        result["status"] = "WARNING"

    # Sample faction leader thoughts
    leader_thoughts = []
    for key in redis_scan_iter("npc_thoughts:*"):
        thought_raw = redis_get(key)
        if thought_raw:
            try:
                thought = json.loads(thought_raw)
                if thought.get("is_leader") or thought.get("role") == "leader":
                    leader_thoughts.append(
                        {
                            "npc": thought.get("name", key.split(":")[-1]),
                            "thought": str(thought.get("thought", ""))[:100],
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                pass

    result["data"]["leader_thought_count"] = len(leader_thoughts)
    result["data"]["leaders"] = leader_thoughts[:5]

    # Build summary
    n_text = (
        "recent"
        if result["data"].get("narration_age_seconds", -1) < STALE_THRESHOLD
        else "STALE"
    )
    result["summary"] = (
        f"Narration {n_text}, {len(leader_thoughts)} leader thoughts captured"
    )

    # Write to Redis
    redis_hset_map(
        "monitor:live_narration",
        {
            "status": result["status"],
            "summary": result["summary"],
            "narration_age": str(result["data"].get("narration_age_seconds", "N/A")),
            "leader_thoughts": str(len(leader_thoughts)),
            "timestamp": str(now),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:live_narration", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
