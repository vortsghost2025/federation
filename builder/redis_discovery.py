"""
Redis discovery helper.

The builder lives outside the federation-game work loop, so it cannot
import the shared _get_redis() helper directly. Instead we probe the
well-known container's published port via the env var REDIS_URL or, if
that is unset, via `docker inspect federation-game-redis-1`.

The helper is deliberately tolerant: if Docker isn't reachable we return
None so the caller can fall back to a stub for testing.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger("federation.builder.redis_discovery")


def get_redis(redis_url: Optional[str] = None):
    """Return a redis.Redis client or None if discovery failed."""
    import redis  # imported lazily so test envs without redis still work

    if redis_url is None:
        redis_url = os.environ.get("BUILDER_REDIS_URL")

    if redis_url:
        try:
            client = redis.Redis.from_url(redis_url)
            client.ping()
            return client
        except Exception as exc:
            logger.warning("redis url %s failed: %s", redis_url, exc)

    host_port = _discover_via_docker()
    if host_port is None:
        return None

    host, port = host_port
    try:
        client = redis.Redis(host=host, port=port, db=0)
        client.ping()
        return client
    except Exception as exc:
        logger.warning("redis %s:%s failed: %s", host, port, exc)
        return None


def _discover_via_docker() -> Optional[tuple]:
    """Use `docker inspect federation-game-redis-1` to find a published port."""
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "federation-game-redis-1"],
            stderr=subprocess.STDOUT, timeout=4,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.info("docker inspect not available: %s", exc)
        return None
    try:
        info = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not info:
        return None
    net = info[0].get("NetworkSettings", {}).get("Ports", {})
    # Prefer 6379/tcp if exposed; fall back to any 6379 mapping.
    candidates = []
    for spec, mappings in net.items():
        if not spec.startswith("6379"):
            continue
        if not mappings:
            continue
        for m in mappings:
            try:
                candidates.append((m["HostIp"] or "127.0.0.1", int(m["HostPort"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not candidates:
        return None
    # Prefer 127.0.0.1 over 0.0.0.0 for safety on multi-host boxes.
    for host, port in candidates:
        if host in ("127.0.0.1", "localhost"):
            return host, port
    return candidates[0]


__all__ = ["get_redis"]
