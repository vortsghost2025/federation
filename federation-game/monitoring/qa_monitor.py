#!/usr/bin/env python3
"""
Tier 2: QA Monitor
Samples NPC thoughts and decisions, checks for empty/fallback/error responses,
writes quality score to monitor:qa_score (0-100).
"""

import os
import sys
import time
import json
import random
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

SAMPLE_COUNT = 3

BAD_PATTERNS = [
    "fallback",
    "error",
    "none",
    "null",
    "empty",
    "failed",
    "timeout",
    "???",
    "...",
]


def _is_bad(text):
    """Check if a text response is empty, fallback, or error."""
    if not text or not text.strip():
        return True
    lower = text.strip().lower()
    if len(lower) < 10:
        return True
    for pattern in BAD_PATTERNS:
        if pattern in lower and len(lower) < 50:
            return True
    return False


def check():
    """One-shot check mode for cron."""
    result = run_check()
    score = result.get("score", 0)
    status = result.get("status", "UNKNOWN")
    print(f"[qa_monitor] {status}: quality score = {score}/100")
    for a in result.get("alerts", []):
        print(f"  ALERT: {a}")
    return 0 if status != "CRITICAL" else 1


def run_check():
    """Core logic — reusable by health_dashboard."""
    result = {"status": "OK", "score": 100, "alerts": [], "data": {}}

    # Sample NPC thoughts
    thought_keys = list(redis_scan_iter("npc_thoughts:*"))
    sampled_thoughts = (
        random.sample(thought_keys, min(SAMPLE_COUNT, len(thought_keys)))
        if thought_keys
        else []
    )
    bad_thoughts = 0
    total_thoughts_checked = 0

    for key in sampled_thoughts:
        raw = redis_get(key)
        total_thoughts_checked += 1
        if raw:
            try:
                data = json.loads(raw)
                text = data.get("thought", "") or data.get("text", "")
            except (json.JSONDecodeError, TypeError):
                text = raw
            if _is_bad(str(text)):
                bad_thoughts += 1
        else:
            bad_thoughts += 1

    # Sample NPC decisions
    decision_keys = list(redis_scan_iter("npc_decisions:*"))
    sampled_decisions = (
        random.sample(decision_keys, min(SAMPLE_COUNT, len(decision_keys)))
        if decision_keys
        else []
    )
    bad_decisions = 0
    total_decisions_checked = 0

    for key in sampled_decisions:
        raw = redis_get(key)
        total_decisions_checked += 1
        if raw:
            try:
                data = json.loads(raw)
                text = (
                    data.get("decision", "")
                    or data.get("action", "")
                    or data.get("text", "")
                )
            except (json.JSONDecodeError, TypeError):
                text = raw
            if _is_bad(str(text)):
                bad_decisions += 1
        else:
            bad_decisions += 1

    # Calculate quality score
    total_checked = total_thoughts_checked + total_decisions_checked
    total_bad = bad_thoughts + bad_decisions
    if total_checked > 0:
        result["score"] = max(0, round(100 * (1 - total_bad / total_checked)))
    else:
        result["score"] = 0
        result["alerts"].append("No NPC thoughts or decisions found in Redis")
        result["status"] = "CRITICAL"

    result["data"]["thoughts_checked"] = total_thoughts_checked
    result["data"]["thoughts_bad"] = bad_thoughts
    result["data"]["decisions_checked"] = total_decisions_checked
    result["data"]["decisions_bad"] = bad_decisions

    if result["score"] < 50:
        result["status"] = "CRITICAL"
        result["alerts"].append(f"Quality score critically low: {result['score']}")
    elif result["score"] < 75:
        result["status"] = "WARNING"
        result["alerts"].append(f"Quality score below threshold: {result['score']}")

    # Write to Redis
    redis_hset_map(
        "monitor:qa_score",
        {
            "score": str(result["score"]),
            "status": result["status"],
            "thoughts_checked": str(total_thoughts_checked),
            "thoughts_bad": str(bad_thoughts),
            "decisions_checked": str(total_decisions_checked),
            "decisions_bad": str(bad_decisions),
            "timestamp": str(time.time()),
        },
    )
    if result["alerts"]:
        redis_hset("monitor:qa_score", "alerts", "; ".join(result["alerts"]))

    return result


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        sys.exit(check())
