#!/usr/bin/env python3
"""
Federation Simulation Monitor — Tier 1 Watchdog
Checks simulation health and outputs structured alerts.
Exit codes: 0 = all clear, 1 = warning, 2 = critical

Usage:
    python monitor.py --check tick      # Tick stall + Redis connectivity
    python monitor.py --check llm       # LLM circuit breakers + error rates
    python monitor.py --check async     # Async endpoint timeout detection
    python monitor.py --check deploy    # Post-deploy verification

Runs on the VPS host. Accesses backend via Docker network IP.
Accesses Redis via docker compose exec redis redis-cli.
Called by shell wrapper scripts via cron on the VPS host.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import socket
import subprocess
from datetime import datetime, timezone

# --- Config ---
# Backend is NOT exposed on localhost. It runs inside Docker network.
# Try Docker network IP first, fall back to public URL.
BACKEND_URL = os.environ.get("FED_BACKEND_URL", "http://172.26.0.11:8000")
PUBLIC_URL = "https://federation-game.deliberatefederation.cloud"
HEALTHZ_PATH = "/healthz"
ASYNC_STATUS_PATH = "/simulation/autonomous/status"
HEALTHZ_TIMEOUT = 5
ASYNC_STALL_SECONDS = 90
SIM_TICK_STALL_SECONDS = 60
LLM_ERROR_THRESHOLD = 5  # errors per hour per provider

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
                "/docker/federation-game/docker-compose.yml",
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


def redis_ping():
    """Check Redis connectivity."""
    out, rc = redis_cmd("PING")
    return out == "PONG", out


def redis_get(key):
    """GET a key from Redis."""
    out, rc = redis_cmd("GET", key)
    return out if rc == 0 else None


def redis_type(key):
    """TYPE of a key in Redis."""
    out, rc = redis_cmd("TYPE", key)
    return out if rc == 0 else "none"


def redis_hgetall(key):
    """HGETALL a hash key from Redis."""
    out, rc = redis_cmd("HGETALL", key)
    if rc != 0:
        return {}
    # Parse line-based output: key\nvalue\nkey\nvalue
    lines = out.strip().split("\n")
    result = {}
    i = 0
    while i < len(lines) - 1:
        result[lines[i]] = lines[i + 1]
        i += 2
    return result


def redis_keys(pattern):
    """KEYS with a pattern from Redis."""
    out, rc = redis_cmd("KEYS", pattern)
    if rc != 0 or not out:
        return []
    return [k for k in out.strip().split("\n") if k]


def redis_zcard(key):
    """ZCARD — count members in a sorted set."""
    out, rc = redis_cmd("ZCARD", key)
    try:
        return int(out) if rc == 0 else 0
    except ValueError:
        return 0


def redis_del(*keys):
    """DEL keys from Redis."""
    if not keys:
        return
    redis_cmd("DEL", *keys)


# --- HTTP Helpers ---


def http_get(url, timeout=5):
    """Simple HTTP GET. Returns (status_code, body) or (None, error)."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except urllib.error.URLError as e:
        return None, str(e.reason)
    except socket.timeout:
        return None, "Connection timed out"
    except Exception as e:
        return None, str(e)


# --- Check: Tick ---


def check_tick():
    """
    Bead 1: Tick Watchdog
    - healthz must return 200
    - worker:status tick_count must be advancing
    - Redis must respond to PING
    """
    max_severity = 0

    # 1. Redis PING
    pong_ok, pong_out = redis_ping()
    if not pong_ok:
        code = alert(
            "TICK-WATCHDOG",
            "CRITICAL",
            "Redis unreachable",
            f"redis-cli PING returned: {pong_out}",
            "Check redis container: docker compose restart redis",
        )
        max_severity = max(max_severity, code)
        # If Redis is down, we can't check tick count — bail early
        return max_severity

    # 2. healthz check
    status, body = http_get(f"{BACKEND_URL}{HEALTHZ_PATH}", timeout=HEALTHZ_TIMEOUT)
    if status != 200:
        code = alert(
            "TICK-WATCHDOG",
            "CRITICAL",
            "Backend health check failed",
            f"/healthz returned HTTP {status}: {body[:200]}",
            "Check backend container: docker compose logs --tail=50 backend",
        )
        max_severity = max(max_severity, code)

    # 3. Tick advancement check
    # Read current tick count from Redis
    worker_status = redis_hgetall("worker:status")
    current_tick = worker_status.get("tick_count", "unknown")
    last_tick_time = worker_status.get("last_tick", "unknown")

    # Use two Redis keys to track stall detection across cron runs:
    # monitor:last_seen_tick — the tick count we saw last check
    # monitor:stall_count — how many consecutive checks with the same tick
    last_seen_key = "monitor:last_seen_tick"
    stall_count_key = "monitor:stall_count"
    last_seen = redis_get(last_seen_key)

    # Ticks take ~60s. With 1-min cron, seeing the same tick once is normal
    # (we caught it mid-cycle). Only alert after 2+ consecutive same-tick checks
    # meaning the tick hasn't advanced in 2+ minutes.
    STALL_THRESHOLD = 2

    if last_seen is not None and last_seen == str(current_tick):
        # Same tick as last check — increment stall counter
        stall_val = redis_get(stall_count_key)
        stall_count = int(stall_val) if stall_val and stall_val.isdigit() else 1
        stall_count += 1
        redis_cmd("SET", stall_count_key, str(stall_count))

        if stall_count >= STALL_THRESHOLD:
            code = alert(
                "TICK-WATCHDOG",
                "CRITICAL",
                "Simulation stalled — tick not advancing",
                f"Tick count unchanged at {current_tick} for {stall_count} consecutive checks. Last tick time: {last_tick_time}",
                "Check worker: docker compose logs --tail=50 worker",
            )
            max_severity = max(max_severity, code)
        else:
            # One same-tick check is normal — don't alert yet
            code = info(
                "TICK-WATCHDOG",
                f"Tick #{current_tick} same as last check (stall count {stall_count}/{STALL_THRESHOLD})",
                f"Last tick time: {last_tick_time}. Waiting for next check to confirm.",
            )
            max_severity = max(max_severity, code)
    else:
        # Tick advanced — reset stall counter
        redis_cmd("SET", stall_count_key, "0")
        code = info(
            "TICK-WATCHDOG",
            "Simulation running — tick advancing",
            f"Tick #{current_tick}, last tick at {last_tick_time}, healthz={status}",
        )
        max_severity = max(max_severity, code)

    # Always update the last-seen key
    redis_cmd("SET", last_seen_key, str(current_tick))

    return max_severity


# --- Check: LLM ---


def check_llm():
    """
    Bead 2: LLM Health Monitor
    - Check all llm_circuit_breaker:* keys
    - Check all llm_errors:* ZSET cardinality
    - Check Ollama reachability
    """
    max_severity = 0

    # 1. Circuit breakers
    breaker_keys = redis_keys("llm_circuit_breaker:*")
    active_breakers = []

    for key in breaker_keys:
        val = redis_get(key)
        if val and val != "0":
            provider = key.replace("llm_circuit_breaker:", "")
            active_breakers.append(provider)

    if active_breakers:
        provider_list = ", ".join(active_breakers)

        # Check if ALL providers are in circuit breaker
        # Known providers: ollama, cloudflare, together, gemini, grok, nim_primary, nim_fallback, openrouter
        all_known = {
            "ollama",
            "cloudflare",
            "together",
            "gemini",
            "grok",
            "nim_primary",
            "nim_fallback",
            "openrouter",
            "nvidia_nim",
        }
        active_set = set(active_breakers)

        if len(active_set.intersection(all_known)) >= len(all_known) - 1:
            # Almost all or all providers down
            code = alert(
                "LLM-MONITOR",
                "CRITICAL",
                "All LLM providers in circuit breaker — simulation on template fallback only",
                f"Active breakers: {provider_list}",
                "Check LLM providers. Clear breakers: redis-cli DEL "
                + " ".join(f"llm_circuit_breaker:{p}" for p in active_breakers),
            )
        else:
            code = alert(
                "LLM-MONITOR",
                "WARNING",
                f"LLM provider circuit breaker(s) tripped — on 5-min cooldown",
                f"Active breakers: {provider_list}",
                "Monitor. If persistent, check provider status. Clear: redis-cli DEL "
                + " ".join(f"llm_circuit_breaker:{p}" for p in active_breakers),
            )
        max_severity = max(max_severity, code)
    else:
        code = info(
            "LLM-MONITOR", "No circuit breakers active", "All LLM providers operational"
        )
        max_severity = max(max_severity, code)

    # 2. Error rates
    error_keys = redis_keys("llm_errors:*")
    high_error_providers = []

    for key in error_keys:
        count = redis_zcard(key)
        provider = key.replace("llm_errors:", "")
        if count > LLM_ERROR_THRESHOLD:
            high_error_providers.append((provider, count))

    if high_error_providers:
        detail = "; ".join(f"{p}: {c} errors/hr" for p, c in high_error_providers)
        code = alert(
            "LLM-MONITOR",
            "WARNING",
            "Elevated LLM error rate detected",
            detail,
            "Check provider API status and rate limits",
        )
        max_severity = max(max_severity, code)

    # 3. Ollama reachability (via Tailscale)
    try:
        sock = socket.create_connection(("100.95.92.117", 11434), timeout=3)
        sock.close()
    except (socket.timeout, socket.error, OSError):
        code = alert(
            "LLM-MONITOR",
            "WARNING",
            "Ollama unreachable at 100.95.92.117:11434 — local LLM down",
            "TCP connect failed or timed out",
            "Check Ollama on Windows machine: is OLLAMA_HOST=0.0.0.0 set? Is Tailscale connected?",
        )
        max_severity = max(max_severity, code)

    return max_severity


# --- Check: Async ---


def check_async():
    """
    Bead 3: Async Endpoint Timeout Watcher
    - Check /simulation/autonomous/status for hung ticks
    """
    max_severity = 0

    status, body = http_get(f"{BACKEND_URL}{ASYNC_STATUS_PATH}", timeout=10)

    if status is None:
        code = alert(
            "ASYNC-WATCHDOG",
            "CRITICAL",
            "Cannot reach async status endpoint",
            f"/simulation/autonomous/status returned: {body[:200]}",
            "Check backend container: docker compose logs --tail=50 backend",
        )
        return max(max_severity, code)

    if status != 200:
        code = alert(
            "ASYNC-WATCHDOG",
            "CRITICAL",
            "Async status endpoint returned error",
            f"HTTP {status}: {body[:200]}",
            "Check backend container health",
        )
        return max(max_severity, code)

    # Parse the response
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        code = alert(
            "ASYNC-WATCHDOG",
            "CRITICAL",
            "Async status response not valid JSON",
            f"Response: {body[:200]}",
            "Check backend /simulation/autonomous/status endpoint",
        )
        return max(max_severity, code)

    # Check for running ticks that may be hung
    # The status endpoint returns info about currently running async operations
    running_ticks = []
    if isinstance(data, dict):
        # Check autonomous tick
        auto_status = data.get("status", data.get("autonomous_tick", ""))
        auto_start = data.get("started_at", data.get("autonomous_tick_started_at", ""))
        if auto_status in ("running", "in_progress", "started"):
            running_ticks.append(("autonomous_tick", auto_start))

        # Check simulation tick
        sim_status = data.get("simulation_tick_status", data.get("simulation_tick", ""))
        sim_start = data.get("simulation_tick_started_at", "")
        if sim_status in ("running", "in_progress", "started"):
            running_ticks.append(("simulation_tick", sim_start))

    # Also check worker:status for async outcomes
    worker_status = redis_hgetall("worker:status")
    async_outcomes = worker_status.get("async_outcomes", "")

    if running_ticks:
        now = datetime.now(timezone.utc)
        for tick_name, started_at in running_ticks:
            if started_at:
                try:
                    # The API may return started_at as a float (Unix timestamp)
                    # or as an ISO 8601 string — handle both
                    if isinstance(started_at, (int, float)):
                        started_dt = datetime.fromtimestamp(started_at, tz=timezone.utc)
                    else:
                        started_dt = datetime.fromisoformat(
                            started_at.replace("Z", "+00:00")
                        )
                    elapsed = (now - started_dt).total_seconds()
                    threshold = (
                        ASYNC_STALL_SECONDS
                        if "autonomous" in tick_name
                        else SIM_TICK_STALL_SECONDS
                    )
                    if elapsed > threshold:
                        code = alert(
                            "ASYNC-WATCHDOG",
                            "WARNING",
                            f"Async {tick_name} may be hung — running for {int(elapsed)}s",
                            f"Started at {started_at}, threshold is {threshold}s",
                            f"Check backend logs: docker compose logs --tail=100 backend | grep {tick_name}",
                        )
                        max_severity = max(max_severity, code)
                    else:
                        code = info(
                            "ASYNC-WATCHDOG",
                            f"Async {tick_name} running normally ({int(elapsed)}s)",
                            f"Started at {started_at}",
                        )
                        max_severity = max(max_severity, code)
                except (ValueError, TypeError):
                    # Can't parse start time — note but don't alert
                    code = info(
                        "ASYNC-WATCHDOG",
                        f"Async {tick_name} running (start time unparseable: {started_at})",
                        "Cannot calculate elapsed time",
                    )
                    max_severity = max(max_severity, code)
    else:
        # No running ticks — all clear
        code = info(
            "ASYNC-WATCHDOG",
            "No async ticks currently running",
            f"Last async outcomes: {async_outcomes or 'none'}",
        )
        max_severity = max(max_severity, code)

    return max_severity


# --- Check: Deploy ---


def check_deploy():
    """
    Bead 4: Deployment Verifier
    - healthz must return 200
    - All containers must be running/healthy
    - No new Python tracebacks in backend logs
    """
    max_severity = 0

    # 1. healthz
    status, body = http_get(f"{BACKEND_URL}{HEALTHZ_PATH}", timeout=HEALTHZ_TIMEOUT)
    if status != 200:
        code = alert(
            "DEPLOY-VERIFY",
            "CRITICAL",
            "Post-deploy health check failed",
            f"/healthz returned HTTP {status}: {body[:200]}",
            "Roll back or check backend: docker compose logs --tail=50 backend",
        )
        max_severity = max(max_severity, code)
    else:
        code = info("DEPLOY-VERIFY", "Health check passed", f"/healthz returned 200")
        max_severity = max(max_severity, code)

    # 2. Container status
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "/docker/federation-game/docker-compose.yml",
                "ps",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            unhealthy = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    container = json.loads(line)
                    name = container.get("Name", container.get("name", "unknown"))
                    health = container.get("Health", container.get("health", ""))
                    state = container.get("State", container.get("state", ""))
                    status_str = container.get("Status", container.get("status", ""))

                    is_healthy = (
                        state in ("running", "Up")
                        or "running" in status_str.lower()
                        or "Up" in status_str
                        or health in ("healthy",)
                    )

                    if not is_healthy and state not in ("exited",):
                        unhealthy.append(
                            f"{name}: state={state} health={health} status={status_str}"
                        )
                except json.JSONDecodeError:
                    # Try non-JSON format — check if line contains "Up" or "healthy"
                    if "Up" not in line and "healthy" not in line.lower():
                        unhealthy.append(line.strip())

            if unhealthy:
                detail = "; ".join(unhealthy[:5])
                code = alert(
                    "DEPLOY-VERIFY",
                    "CRITICAL",
                    "Container(s) not healthy after deploy",
                    detail,
                    "Restart unhealthy containers: docker compose up -d",
                )
                max_severity = max(max_severity, code)
            else:
                code = info("DEPLOY-VERIFY", "All containers running/healthy", "")
                max_severity = max(max_severity, code)
    except subprocess.TimeoutExpired:
        code = alert(
            "DEPLOY-VERIFY",
            "WARNING",
            "Container status check timed out",
            "docker compose ps did not respond within 15s",
            "Check Docker daemon: systemctl status docker",
        )
        max_severity = max(max_severity, code)
    except Exception as e:
        code = alert(
            "DEPLOY-VERIFY",
            "WARNING",
            "Could not check container status",
            str(e)[:200],
            "Run manually: docker compose ps",
        )
        max_severity = max(max_severity, code)

    # 3. Backend logs for Python tracebacks
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "/docker/federation-game/docker-compose.yml",
                "logs",
                "--tail=20",
                "backend",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            traceback_lines = [
                l
                for l in result.stdout.split("\n")
                if "Traceback" in l or "Error:" in l or "Exception" in l
            ]
            if traceback_lines:
                first_error = traceback_lines[0].strip()[:200]
                code = alert(
                    "DEPLOY-VERIFY",
                    "WARNING",
                    "Backend errors after deploy",
                    first_error,
                    "Check full logs: docker compose logs --tail=100 backend",
                )
                max_severity = max(max_severity, code)
    except Exception:
        pass  # Non-critical — skip if this check fails

    # Final summary
    if max_severity == 0:
        info(
            "DEPLOY-VERIFY",
            "Deploy verified — all systems nominal",
            "/healthz=200, all containers running, no new errors in backend logs",
        )

    return max_severity


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Federation Simulation Monitor")
    parser.add_argument(
        "--check",
        required=True,
        choices=["tick", "llm", "async", "deploy"],
        help="Type of check to run",
    )
    args = parser.parse_args()

    checks = {
        "tick": check_tick,
        "llm": check_llm,
        "async": check_async,
        "deploy": check_deploy,
    }

    exit_code = checks[args.check]()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
