#!/usr/bin/env python3
"""
Auto-Restart Manager for Federation Simulation

Monitors for specific failure patterns (backend container crashes, worker process deaths)
and attempts safe restarts with logging to Gastown dashboard.
"""

import os
import sys
import time
import json
import logging
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import redis

log = logging.getLogger("auto_restart_manager")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [auto_restart] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# ── Configuration ──────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DOCKER_COMPOSE_FILE = os.getenv("DOCKER_COMPOSE_FILE", "docker-compose.yml")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
MAX_RESTART_ATTEMPTS = int(os.getenv("MAX_RESTART_ATTEMPTS", "3"))

# Redis for dashboard status
r = redis.from_url(REDIS_URL, decode_responses=True)

# ── Safe State Verifier Interface ───────────────────────────
def is_simulator_safe() -> bool:
    """
    Check if simulator indicates it's safe to restart.
    Queries a backend endpoint that reports simulation state safety.
    Returns True if restart is safe, False otherwise.
    """
    try:
        resp = requests.get(f"{BACKEND_URL}/state/safe-to-restart", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("safe", False)
    except Exception:
        pass
    # Default to unsafe if endpoint unavailable
    return False


# ── Health Check Functions ─────────────────────────────────
def check_backend_health() -> Dict[str, Any]:
    """Check if backend container is healthy."""
    try:
        resp = requests.get(f"{BACKEND_URL}/healthz", timeout=5)
        return {
            "healthy": resp.status_code == 200,
            "status_code": resp.status_code,
            "error": None
        }
    except requests.exceptions.ConnectionError:
        return {"healthy": False, "status_code": None, "error": "connection_refused"}
    except requests.exceptions.Timeout:
        return {"healthy": False, "status_code": None, "error": "timeout"}
    except Exception as e:
        return {"healthy": False, "status_code": None, "error": str(e)}


def check_worker_process() -> Dict[str, Any]:
    """Check if worker process is running inside its container."""
    try:
        # Check Redis for worker status
        status = r.hgetall("worker:status")
        last_tick = status.get("last_tick")
        tick_count = int(status.get("tick_count", 0))

        # Consider worker dead if no tick in last 5 minutes
        if last_tick:
            try:
                last_time = datetime.fromisoformat(last_tick.replace("Z", "+00:00"))
                age_seconds = (datetime.now(last_time.tzinfo) - last_time).total_seconds()
                if age_seconds > 300:
                    return {"alive": False, "reason": "stale_tick", "age_seconds": age_seconds}
            except Exception:
                pass

        return {"alive": True, "tick_count": tick_count, "reason": None}
    except Exception as e:
        return {"alive": False, "reason": f"redis_error: {e}"}


# ── Restart Actions ────────────────────────────────────────
restart_attempts: Dict[str, int] = {}


def restart_backend() -> Dict[str, Any]:
    """Attempt to restart the backend container."""
    service = "backend"

    # Check restart attempt count
    if restart_attempts.get(service, 0) >= MAX_RESTART_ATTEMPTS:
        return {
            "success": False,
            "error": "max_attempts_exceeded",
            "attempts": restart_attempts.get(service, 0)
        }

    # Check if safe to restart
    if not is_simulator_safe():
        return {
            "success": False,
            "error": "simulator_not_safe",
            "attempted": False
        }

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "restart", service],
            capture_output=True,
            text=True,
            timeout=60
        )
        restart_attempts[service] = restart_attempts.get(service, 0) + 1

        if result.returncode == 0:
            return {
                "success": True,
                "error": None,
                "attempts": restart_attempts[service]
            }
        else:
            return {
                "success": False,
                "error": result.stderr or "unknown_error",
                "attempts": restart_attempts[service]
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "attempts": restart_attempts.get(service, 0)}
    except Exception as e:
        return {"success": False, "error": str(e), "attempts": restart_attempts.get(service, 0)}


def restart_worker_service() -> Dict[str, Any]:
    """Attempt to restart the worker service."""
    service = "worker"

    if restart_attempts.get(service, 0) >= MAX_RESTART_ATTEMPTS:
        return {
            "success": False,
            "error": "max_attempts_exceeded",
            "attempts": restart_attempts.get(service, 0)
        }

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "restart", service],
            capture_output=True,
            text=True,
            timeout=60
        )
        restart_attempts[service] = restart_attempts.get(service, 0) + 1

        if result.returncode == 0:
            return {
                "success": True,
                "error": None,
                "attempts": restart_attempts[service]
            }
        else:
            return {
                "success": False,
                "error": result.stderr or "unknown_error",
                "attempts": restart_attempts[service]
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "attempts": restart_attempts.get(service, 0)}
    except Exception as e:
        return {"success": False, "error": str(e), "attempts": restart_attempts.get(service, 0)}


# ── Dashboard Logging ─────────────────────────────────────
def log_to_dashboard(action: str, result: Dict[str, Any]) -> None:
    """Log restart attempt to Gastown dashboard via Redis."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "success": result.get("success", False),
        "error": result.get("error"),
        "attempts": result.get("attempts", 0),
        "details": result
    }

    try:
        r.lpush("auto_restart:log", json.dumps(entry))
        r.ltrim("auto_restart:log", 0, 99)

        # Also update status hash
        r.hset("auto_restart:status", mapping={
            "last_action": action,
            "last_success": str(result.get("success", False)),
            "last_error": result.get("error", ""),
            "last_timestamp": entry["timestamp"]
        })
    except Exception as e:
        log.warning(f"Failed to log to dashboard: {e}")


# ── Main Monitoring Loop ───────────────────────────────────
def run_check_cycle() -> None:
    """Run a single health check and recovery cycle."""
    log.info("Running health check cycle...")

    # Check backend
    backend = check_backend_health()
    if not backend["healthy"]:
        log.warning(f"Backend unhealthy: {backend}")

        # Only attempt restart for specific failure patterns
        if backend["error"] in ("connection_refused", "timeout"):
            log.info("Attempting backend restart...")
            result = restart_backend()
            log_to_dashboard("backend_restart", result)
            log.info(f"Backend restart result: {result}")

    # Check worker process
    worker = check_worker_process()
    if not worker.get("alive", True):
        log.warning(f"Worker process appears dead: {worker}")

        # Only restart worker if container is still running (backend healthy)
        if backend.get("healthy", False) or backend.get("error") != "connection_refused":
            log.info("Attempting worker restart...")
            result = restart_worker_service()
            log_to_dashboard("worker_restart", result)
            log.info(f"Worker restart result: {result}")


def main():
    log.info("═══ Auto-Restart Manager Starting ══")
    log.info(f" Backend URL: {BACKEND_URL}")
    log.info(f" Redis URL: {REDIS_URL}")
    log.info(f" Check interval: {CHECK_INTERVAL}s")
    log.info(f" Max restart attempts: {MAX_RESTART_ATTEMPTS}")

    while True:
        try:
            run_check_cycle()
        except Exception as e:
            log.error(f"Check cycle failed: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()