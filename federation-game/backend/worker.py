import os
import time
import json
import signal
import logging
import requests
import redis
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("federation-worker")

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TICK_INTERVAL = int(os.getenv("TICK_INTERVAL", "60"))
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() == "true"

shutdown_requested = False
tick_count = 0


def handle_signal(signum, frame):
    global shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — initiating graceful shutdown", sig_name)
    shutdown_requested = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def wait_for_backend(url: str, timeout: int = 120):
    health_url = f"{url}/healthz"
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                logger.info("Backend is healthy at %s", url)
                return True
        except requests.RequestException:
            pass
        attempt += 1
        delay = min(2**attempt, 16)
        logger.debug("Backend not ready — retrying in %ds", delay)
        time.sleep(delay)
    logger.error("Backend did not become healthy within %ds", timeout)
    return False


def post_endpoint(url: str, label: str) -> bool:
    try:
        resp = requests.post(url, timeout=30)
        logger.info(
            "%s responded %d in %.1fms",
            label,
            resp.status_code,
            resp.elapsed.total_seconds() * 1000,
        )
        return resp.status_code < 400
    except requests.RequestException as exc:
        logger.error("%s failed: %s", label, exc)
        return False


def run_tick(r: redis.Redis, session: requests.Session | None):
    global tick_count
    tick_count += 1
    tick_start = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()

    logger.info("=== Tick #%d started ===", tick_count)

    if WORKER_ENABLED:
        endpoints = [
            (f"{BACKEND_URL}/npcs/advance-turn", "NPC advance-turn"),
            (f"{BACKEND_URL}/political/process-turn", "Political process-turn"),
            (f"{BACKEND_URL}/history-arc/advance", "History-arc advance"),
        ]
        for url, label in endpoints:
            post_endpoint(url, label)
    else:
        logger.info("Ticks disabled (WORKER_ENABLED=false) — heartbeat only")

    try:
        r.publish(
            "federation:updates",
            json.dumps(
                {
                    "event": "game:tick",
                    "tick": tick_count,
                    "timestamp": now,
                }
            ),
        )
        r.hset(
            "worker:status",
            mapping={
                "last_tick": now,
                "tick_count": tick_count,
                "backend_url": BACKEND_URL,
                "enabled": str(WORKER_ENABLED),
            },
        )
    except redis.RedisError as exc:
        logger.error("Redis publish/update failed: %s", exc)

    elapsed = time.monotonic() - tick_start
    logger.info(
        "=== Tick #%d completed in %.2fs ===",
        tick_count,
        elapsed,
    )


def main():
    logger.info(
        "Federation worker starting — backend=%s redis=%s interval=%ds enabled=%s",
        BACKEND_URL,
        REDIS_URL,
        TICK_INTERVAL,
        WORKER_ENABLED,
    )

    r = redis.from_url(REDIS_URL)
    try:
        r.ping()
        logger.info("Redis connection established")
    except redis.RedisError as exc:
        logger.critical("Cannot connect to Redis: %s", exc)
        return

    if WORKER_ENABLED and not wait_for_backend(BACKEND_URL):
        logger.critical("Aborting — backend unavailable")
        return

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        r.set("worker:started_at", started_at)
        r.hset(
            "worker:status",
            mapping={
                "started_at": started_at,
                "tick_count": 0,
                "enabled": str(WORKER_ENABLED),
            },
        )
    except redis.RedisError as exc:
        logger.error("Failed to write startup status to Redis: %s", exc)

    logger.info("Worker online since %s — entering tick loop", started_at)

    while not shutdown_requested:
        run_tick(r, None)
        sleep_until = time.monotonic() + TICK_INTERVAL
        while time.monotonic() < sleep_until and not shutdown_requested:
            time.sleep(1)

    logger.info(
        "Worker shutting down after %d ticks (requested=%s)",
        tick_count,
        shutdown_requested,
    )
    try:
        r.hset(
            "worker:status",
            mapping={
                "status": "stopped",
                "stopped_at": datetime.now(timezone.utc).isoformat(),
                "total_ticks": tick_count,
            },
        )
    except redis.RedisError:
        pass

    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
