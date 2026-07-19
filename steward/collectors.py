"""Safe collectors: live I/O runners wired to the read-only adapters.

These are the ONLY modules that may touch network/process surfaces, and they
do so through narrow, allowlisted, bounded paths. Adapters receive these
runners as dependencies; unit tests inject fakes instead.

Live collectors here are NOT executed by the S1 pure engine and are NOT
imported by schema/checks/cli. They are invoked only by the S2 CLI
(``steward.s2cli``).

Forbidden (never done here): writes of any kind, Redis EVAL/scripts/pub-sub/
MONITOR, unbounded KEYS, Docker start/stop/restart/kill/rm/run/exec-in-app,
HTTP POST/PUT/DELETE, credential/config changes, Federation API writes.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional

from .adapters.base import ObservationSnapshot, unknown_snapshot
from .adapters.docker_ro import run as docker_run
from .adapters.http_ro import fetch as http_fetch
from .adapters.redis_ro import collect_key_health, run_command

# Hard bounds for live I/O.
_HTTP_TIMEOUT = 5.0
_HTTP_MAX_BYTES = 64 * 1024
_DOCKER_TIMEOUT = 10.0

# Live Redis client is imported lazily so importing collectors never requires
# the redis package to be installed (keeps unit tests dependency-free).
def _get_redis_client(host: str, port: int, db: int = 0, password: Optional[str] = None):
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("redis package not available for live collection") from exc
    client = redis.Redis(host=host, port=port, db=db, password=password,
                         socket_timeout=_HTTP_TIMEOUT, decode_responses=True)
    return client


def live_redis_command(client, cmd: str, args: Optional[List[str]] = None) -> Any:
    """Run one allowlisted read command against a live Redis client."""
    fn = getattr(client, cmd.lower(), None)
    if fn is None:
        raise ValueError(f"unknown redis command: {cmd}")
    return fn(*(args or []))


def live_http(method: str, url: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded read-only HTTP GET/HEAD via urllib (stdlib only)."""
    import ssl

    timeout = float(opts.get("timeout", _HTTP_TIMEOUT))
    max_bytes = int(opts.get("max_bytes", _HTTP_MAX_BYTES))
    req = urllib.request.Request(url, method=method.upper())
    import time

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - read-only GET/HEAD
            body = resp.read(max_bytes).decode("utf-8", "replace")
            status = resp.status
            headers = {k: v for k, v in resp.getheaders()}
    except Exception as exc:
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {"status_code": status, "headers": headers, "body": body, "elapsed_ms": elapsed_ms}


def live_docker(args: List[str]) -> str:
    """Run an allowlisted read-only docker subcommand via subprocess."""
    proc = subprocess.run(
        ["docker", *[str(a) for a in args]],
        capture_output=True, text=True, timeout=_DOCKER_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker returned {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def collect_redis_snapshot(
    cmd: str,
    args: Optional[List[str]] = None,
    *,
    observed_at: str,
    host: str = "127.0.0.1",
    port: int = 6379,
    db: int = 0,
    password: Optional[str] = None,
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    try:
        client = _get_redis_client(host, port, db, password)
        return run_command(
            lambda c, a: live_redis_command(client, c, a), cmd, args,
            observed_at=observed_at, source=source, provenance=provenance,
        )
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"live redis collection failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )


def collect_redis_key_health(
    keys: List[str],
    *,
    observed_at: str,
    host: str = "127.0.0.1",
    port: int = 6379,
    db: int = 0,
    password: Optional[str] = None,
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    try:
        client = _get_redis_client(host, port, db, password)
        return collect_key_health(
            lambda c, a: live_redis_command(client, c, a), keys,
            observed_at=observed_at, source=source, provenance=provenance,
        )
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"live redis key-health failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )


def collect_http_snapshot(
    url: str,
    *,
    method: str = "GET",
    observed_at: str,
    source: str = "http",
    timeout: float = _HTTP_TIMEOUT,
    max_bytes: int = _HTTP_MAX_BYTES,
    provenance: str = "",
) -> ObservationSnapshot:
    try:
        return http_fetch(
            live_http, url, method=method, observed_at=observed_at,
            source=source, timeout=timeout, max_bytes=max_bytes, provenance=provenance,
        )
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"live http collection failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )


def collect_docker_snapshot(
    args: List[str],
    *,
    observed_at: str,
    source: str = "docker",
    provenance: str = "",
) -> ObservationSnapshot:
    return docker_run(
        live_docker, args, observed_at=observed_at, source=source, provenance=provenance,
    )


def load_frozen_snapshot(path: str, source: str, observed_at: str) -> ObservationSnapshot:
    """Load a previously-saved snapshot JSON from disk (no live I/O).

    Used by ``snapshot <source> --from-file`` and by tests. The JSON must match
    ObservationSnapshot.to_dict() shape.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return ObservationSnapshot(
        source=raw.get("source", source),
        observed_at=raw.get("observed_at", observed_at),
        availability=raw.get("availability", "unknown"),
        version=raw.get("version"),
        status_detail=raw.get("status_detail", ""),
        provenance=raw.get("provenance", ""),
        data=raw.get("data", {}),
    )
