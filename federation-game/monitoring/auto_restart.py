#!/usr/bin/env python3
"""
Federation Simulation Auto-Restart Manager
Monitors simulation stall count and restarts worker if stalled too long.
Exit codes: 0 = all clear, 1 = warning, 2 = critical

Usage:
    python auto_restart.py --check      # Check stall count and restart if needed

Runs on the VPS host. Accesses backend via Docker network IP.
Accesses Redis via docker compose exec redis redis-cli.
Called by shell wrapper scripts via cron on the VPS host.
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime, timezone

# --- Config ---
BACKEND_URL = os.environ.get("FED_BACKEND_URL", "http://172.26.0.11:8000")
REDIS_COMPOSE_FILE = "/docker/federation-game/docker-compose.yml"
WORKER_CONTAINER = "federation-game-worker-1"

# Thresholds
STALL_THRESHOLD_RESTART = 4  # Restart if stall_count >= 4
STALL_THRESHOLD_WARNING = 3  # Warning if stall_count >= 3
COOLDOWN_MINUTES = 15        # Minimum minutes between restarts
MAX_RESTART_LOG = 50         # Keep last 50 restart events

# --- Alert Formatter ---

def alert(source, severity, what, detail, action):
    """Output a structured alert to stdout."""
    ts = datetime.now(timezone.utc).isoformat()
    lines = [
        f"[{source}] [{severity}] [monitor]",
        f"What: {what}",
        f"When: {ts}",
        f"Detail: {detail}",
        f"Action: {action}",
    ]
    print("\n".join(lines))
    # Return exit code based on severity
    if severity == "CRITICAL":
        return 2
    elif severity == "WARNING":
        return 1
    return 0


def info(source, what, detail):
    """Output an INFO-level status message."""
    return alert(source, "INFO", what, detail, "None needed")


# --- Redis Access (via Docker exec bridge) ---
# Since this script runs on the VPS host (not inside a container),
# it calls docker compose exec redis for Redis commands.

def redis_cmd(*args):
    """Run a Redis command via docker compose exec redis redis-cli."""
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                REDIS_COMPOSE_FILE,
                "exec",
                "-T",
                "redis",
                "redis-cli",
            ]
            + list(args),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1
    except Exception as e:
        return str(e), 1


def redis_get(key):
    """GET a key from Redis."""
    out, rc = redis_cmd("GET", key)
    return out if rc == 0 else None


def redis_set(key, value):
    """SET a key in Redis."""
    out, rc = redis_cmd("SET", key, value)
    return rc == 0


def redis_lpush(key, value):
    """LPUSH a value to a Redis list."""
    out, rc = redis_cmd("LPUSH", key, value)
    return rc == 0


def redis_ltrim(key, start, stop):
    """LTRIM a Redis list to keep only elements in range [start, stop]."""
    out, rc = redis_cmd("LTRIM", key, str(start), str(stop))
    return rc == 0


def redis_llen(key):
    """LLEN - get length of a Redis list."""
    out, rc = redis_cmd("LLEN", key)
    if rc == 0:
        try:
            return int(out)
        except ValueError:
            return 0
    return 0


# --- Main Check Function ---

def check_auto_restart():
    """
    Bead 5: Auto-Restart Manager
    - Check monitor:stall_count from Redis
    - If stall_count >= STALL_THRESHOLD_RESTART, restart worker container
    - Enforce cooldown using monitor:last_restart
    - Log restarts to monitor:restart_log (keep last 50)
    - Alert CRITICAL on restart, WARNING if stall_count >= STALL_THRESHOLD_WARNING
    """
    max_severity = 0

    # 1. Check Redis connectivity
    pong_ok, pong_out = redis_cmd("PING")
    if pong_ok != "PONG":
        code = alert(
            "AUTO-RESTART",
            "CRITICAL",
            "Redis unreachable",
            f"redis-cli PING returned: {pong_out}",
            "Check redis container: docker compose restart redis",
        )
        max_severity = max(max_severity, code)
        return max_severity

    # 2. Get current stall count
    stall_count_str = redis_get("monitor:stall_count")
    stall_count = int(stall_count_str) if stall_count_str and stall_count_str.isdigit() else 0

    # 3. Check cooldown - last restart time
    last_restart_str = redis_get("monitor:last_restart")
    last_restart = 0
    if last_restart_str and last_restart_str.isdigit():
        last_restart = int(last_restart_str)

    # Calculate minutes since last restart
    now = datetime.now(timezone.utc).timestamp()
    minutes_since_last_restart = (now - last_restart) / 60 if last_restart > 0 else float('inf')
    cooldown_remaining = max(0, COOLDOWN_MINUTES - minutes_since_last_restart)

    # 4. Check if we should restart
    should_restart = (
        stall_count >= STALL_THRESHOLD_RESTART and 
        minutes_since_last_restart >= COOLDOWN_MINUTES
    )

    # 5. Handle restart logic
    if should_restart:
        # Perform the restart
        try:
            result = subprocess.run(
                ["docker", "restart", WORKER_CONTAINER],
                capture_output=True,
                text=True,
                timeout=30,
            )
            restart_success = result.returncode == 0
            restart_error = result.stderr.strip() if not restart_success else ""
        except subprocess.TimeoutExpired:
            restart_success = False
            restart_error = "docker restart command timed out"
        except Exception as e:
            restart_success = False
            restart_error = str(e)

        if restart_success:
            # Log the restart event
            restart_event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stall_count": stall_count,
                "reason": f"Simulation stalled for {stall_count}+ minutes",
            }
            event_json = json.dumps(restart_event)

            # Add to restart log and trim to last 50
            redis_lpush("monitor:restart_log", event_json)
            redis_ltrim("monitor:restart_log", 0, MAX_RESTART_LOG - 1)

            # Update last restart time
            redis_set("monitor:last_restart", str(int(now)))

            # Reset stall count after successful restart
            redis_set("monitor:stall_count", "0")

            # Alert CRITICAL for restart
            code = alert(
                "AUTO-RESTART",
                "CRITICAL",
                "Worker container restarted due to stall",
                f"Stall count: {stall_count}, restarted {WORKER_CONTAINER}",
                "Check worker logs: docker compose logs --tail=50 worker",
            )
            max_severity = max(max_severity, code)
        else:
            # Failed to restart
            code = alert(
                "AUTO-RESTART",
                "CRITICAL",
                "Failed to restart worker container",
                f"Stall count: {stall_count}, error: {restart_error}",
                "Check Docker daemon and container status",
            )
            max_severity = max(max_severity, code)

    # 6. Handle warning logic (stall_count >= 3 but not restarting yet)
    elif stall_count >= STALL_THRESHOLD_WARNING:
        if cooldown_remaining > 0:
            detail = f"Stall count: {stall_count}, restart in cooldown ({cooldown_remaining:.1f} min remaining)"
        else:
            detail = f"Stall count: {stall_count}, checking cooldown..."

        code = alert(
            "AUTO-RESTART",
            "WARNING",
            "Simulation approaching stall threshold",
            detail,
            "Monitor stall count - restart will occur if count reaches 4 and cooldown passed",
        )
        max_severity = max(max_severity, code)

    # 7. Info level for normal operation
    else:
        if stall_count > 0:
            detail = f"Stall count: {stall_count}/{STALL_THRESHOLD_RESTART}"
            if cooldown_remaining > 0:
                detail += f", cooldown active ({cooldown_remaining:.1f} min remaining)"
        else:
            detail = "Simulation running normally"
            if last_restart > 0:
                detail += f", last restart {minutes_since_last_restart:.1f} minutes ago"

        code = info(
            "AUTO-RESTART",
            "Auto-restart monitor active",
            detail,
        )
        max_severity = max(max_severity, code)

    return max_severity


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Federation Simulation Auto-Restart Manager")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the auto-restart check",
    )
    args = parser.parse_args()

    if args.check:
        exit_code = check_auto_restart()
        sys.exit(exit_code)
    else:
        print("Error: --check argument required")
        sys.exit(1)


if __name__ == "__main__":
    main()