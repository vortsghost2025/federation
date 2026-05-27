#!/usr/bin/env python3
"""
Telegram Notification Diagnosis Script
Checks worker state, logs, and crisis classification to identify why
notifications may not be being received.
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime, timezone

# Redis helper - matches monitoring/redis_helper.py pattern
_REDIS_CLI = ["docker", "exec", "federation-game-redis-1", "redis-cli"]

def _redis_run(*args):
    try:
        result = subprocess.run(
            _REDIS_CLI + [str(a) for a in args],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1

def redis_get(key):
    out, rc = _redis_run("GET", key)
    if rc == 0 and out and out not in ("(nil)", "", "TIMEOUT"):
        return out
    return None

def redis_hgetall(key):
    out, rc = _redis_run("HGETALL", key)
    if rc != 0 or not out or out in ("(empty list or set)", "", "TIMEOUT"):
        return {}
    parts = out.split("\n")
    result = {}
    i = 0
    while i < len(parts) - 1:
        f = parts[i].strip()
        v = parts[i + 1].strip()
        if f:
            result[f] = v
        i += 2
    return result

def redis_zcard(key):
    out, rc = _redis_run("ZCARD", key)
    if rc == 0 and out:
        try:
            return int(out)
        except ValueError:
            pass
    return 0

def redis_cmd(*args):
    out, rc = _redis_run(*args)
    return out, rc


def http_get(url, timeout=5):
    """Simple HTTP GET to backend endpoint."""
    try:
        import urllib.request
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def check_worker_tick_state():
    """Check 1: Verify worker is actively ticking (check tick_count advancement)."""
    print("\n" + "="*60)
    print("CHECK 1: Worker Tick State")
    print("="*60)

    worker_status = redis_hgetall("worker:status")
    tick_count = worker_status.get("tick_count", "unknown")
    last_tick = worker_status.get("last_tick", "unknown")
    enabled = worker_status.get("enabled", "unknown")
    notifications_degraded = worker_status.get("notifications_degraded", "unknown")

    print(f"  tick_count: {tick_count}")
    print(f"  last_tick: {last_tick}")
    print(f"  enabled: {enabled}")
    print(f"  notifications_degraded: {notifications_degraded}")

    # Check if tick is advancing
    stall_count = redis_get("monitor:stall_count")
    print(f"  monitor:stall_count: {stall_count or 'not set'}")

    return {
        "tick_count": tick_count,
        "last_tick": last_tick,
        "enabled": enabled,
        "notifications_degraded": notifications_degraded,
        "stall_count": stall_count
    }


def check_crisis_classification():
    """Check 3: Check current crisis classification from /map/data endpoint."""
    print("\n" + "="*60)
    print("CHECK 3: Crisis Classification")
    print("="*60)

    # Try to reach backend via public URL
    status, body = http_get("https://federation-game.deliberatefederation.cloud/map/data", timeout=10)

    if status != 200:
        print(f"  ERROR: Could not reach /map/data endpoint (HTTP {status})")
        print(f"  Body: {body[:200] if body else 'empty'}")
        return None

    try:
        data = json.loads(body)
        cr = data.get("crisis_readout", {})
        classification = cr.get("classification", "UNKNOWN")
        headline = cr.get("headline", "N/A")
        severity = cr.get("severity", 0)

        print(f"  Classification: {classification}")
        print(f"  Severity: {severity}")
        print(f"  Headline: {headline[:80] if headline else 'N/A'}...")

        # Check notification tier logic
        if classification in ("STABLE", "MODERATE"):
            print(f"\n  NOTE: {classification} level suppresses Telegram notifications")
            print("  (Only ELEVATED, SEVERE, CRITICAL trigger Telegram)")
        else:
            print(f"\n  NOTE: {classification} level SHOULD trigger Telegram notifications")

        return {
            "classification": classification,
            "headline": headline,
            "severity": severity
        }
    except Exception as e:
        print(f"  ERROR: Failed to parse /map/data response: {e}")
        return None


def check_redis_metrics():
    """Check 5: Check Redis for worker:status notifications_degraded flag."""
    print("\n" + "="*60)
    print("CHECK 5: Redis Notification Metrics")
    print("="*60)

    worker_status = redis_hgetall("worker:status")

    degraded = worker_status.get("notifications_degraded", "unknown")
    failures = worker_status.get("notification_failures", "unknown")
    async_outcomes = worker_status.get("async_outcomes", "unknown")

    print(f"  notifications_degraded: {degraded}")
    print(f"  notification_failures: {failures}")
    print(f"  async_outcomes: {async_outcomes[:100] if async_outcomes else 'none'}...")

    # Check for significant events
    event_count = redis_zcard("npc_world_events")
    broadcast_count = redis_zcard("npc_broadcast_events")

    print(f"  npc_world_events count: {event_count}")
    print(f"  npc_broadcast_events count: {broadcast_count}")

    return {
        "notifications_degraded": degraded,
        "notification_failures": failures,
        "event_count": event_count,
        "broadcast_count": broadcast_count
    }


def check_worker_logs():
    """Check 2: Examine recent worker logs for notification-related entries."""
    print("\n" + "="*60)
    print("CHECK 2: Worker Logs (last 50 lines)")
    print("="*60)

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", "/docker/federation-game/docker-compose.yml", "logs", "--tail=50", "worker"],
            capture_output=True, text=True, timeout=15
        )
        logs = result.stdout

        # Filter for relevant lines
        relevant_lines = []
        for line in logs.split("\n"):
            if any(kw in line.lower() for kw in ["notification", "telegram", "apprise", "tgram", "tick", "error", "fail", "crisis", "classification"]):
                relevant_lines.append(line)

        if relevant_lines:
            print("  Relevant log lines found:")
            for line in relevant_lines[-20:]:
                print(f"    {line}")
        else:
            print("  No relevant log lines found in last 50 lines")
            print("  Showing last 10 lines of any output:")
            for line in logs.split("\n")[-10:]:
                if line.strip():
                    print(f"    {line}")

        return logs
    except Exception as e:
        print(f"  ERROR: Could not fetch worker logs: {e}")
        return None


def check_backend_health():
    """Check backend health to ensure it's running."""
    print("\n" + "="*60)
    print("CHECK: Backend Health")
    print("="*60)

    status, body = http_get("https://federation-game.deliberatefederation.cloud/healthz", timeout=5)

    if status == 200:
        print(f"  Backend health check: OK (200)")
        try:
            data = json.loads(body)
            print(f"  Status: {data.get('status', 'unknown')}")
        except:
            pass
    else:
        print(f"  Backend health check: FAILED (HTTP {status})")
        print(f"  Body: {body[:100] if body else 'empty'}")

    return status


def summarize_findings(worker_state, crisis_data, redis_metrics):
    """Provide a summary of findings and likely causes."""
    print("\n" + "="*60)
    print("DIAGNOSIS SUMMARY")
    print("="*60)

    issues = []

    # Check worker stall
    last_tick = worker_state.get("last_tick", "unknown")
    if last_tick and "2026-05-26" in str(last_tick):
        issues.append("WORKER STALLED: last_tick is from yesterday")

    # Check notification degradation
    degraded = redis_metrics.get("notifications_degraded", "unknown")
    if degraded == "1" or degraded == "true":
        issues.append("NOTIFICATIONS DEGRADED: Redis flag set to 1")

    # Check crisis classification
    if crisis_data:
        cls = crisis_data.get("classification", "UNKNOWN")
        if cls in ("STABLE", "MODERATE"):
            issues.append(f"CRISIS LEVEL LOW: {cls} (Telegram suppressed for STABLE/MODERATE)")

    if not issues:
        print("  No clear issues detected - notifications should be working")
        print("  Check: Telegram bot token, chat ID, and network connectivity")
    else:
        print("  Potential issues found:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")


if __name__ == "__main__":
    print("Telegram Notification Diagnosis")
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")

    # Run all checks
    worker_state = check_worker_tick_state()
    crisis_data = check_crisis_classification()
    redis_metrics = check_redis_metrics()
    logs = check_worker_logs()
    backend_health = check_backend_health()

    # Summarize
    summarize_findings(worker_state, crisis_data, redis_metrics)