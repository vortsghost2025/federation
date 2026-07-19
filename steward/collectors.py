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

import ipaddress
import json
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .adapters.base import ObservationSnapshot, unknown_snapshot
from .adapters.docker_ro import run as docker_run
from .adapters.http_ro import fetch as http_fetch
from .adapters.redis_ro import collect_key_health, run_command

# Hard bounds for live I/O.
_HTTP_TIMEOUT = 5.0
_HTTP_MAX_BYTES = 64 * 1024
_DOCKER_TIMEOUT = 10.0
_REDIS_TIMEOUT = 5.0

# Addresses S2 must never reach: loopback, link-local, private, and the cloud
# metadata endpoint. Read-only observation targets are explicitly allowlisted.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),      # cloud metadata + link-local
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),            # unique local
    ipaddress.ip_network("fe80::/10"),           # link-local
)

# Permit only these schemes. file:///ftp:// etc. are refused (SSRF guard).
_ALLOWED_HTTP_SCHEMES = frozenset({"http", "https"})


def _http_target_allowed(url: str, allowed_hosts: Optional[List[str]]) -> bool:
    """Reject unsupported schemes, blocked networks, and non-allowlisted hosts.

    ``allowed_hosts`` (when provided) is an explicit allowlist; if set, any host
    not listed is refused. When None, only the blocked-network check applies
    (defense-in-depth default-deny for sensitive ranges).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_HTTP_SCHEMES:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if allowed_hosts is not None and host not in {h.lower() for h in allowed_hosts}:
        return False
    try:
        import socket
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except Exception:
        # If we cannot resolve, refuse rather than risk a metadata/redirect hit.
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                return False
    return True


def _get_redis_client(host: str, port: int, db: int = 0):
    """Local/trusted read-only Redis client. Never takes a password (S2 holds
    no Federation credentials)."""
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("redis package not available for live collection") from exc
    return redis.Redis(
        host=host, port=port, db=db,
        socket_timeout=_REDIS_TIMEOUT, socket_connect_timeout=_REDIS_TIMEOUT,
        decode_responses=True,
    )

def live_redis_command(client, cmd: str, args: Optional[List[str]] = None) -> Any:
    """Run one allowlisted read command against a live Redis client."""
    fn = getattr(client, cmd.lower(), None)
    if fn is None:
        raise ValueError(f"unknown redis command: {cmd}")
    return fn(*(args or []))


def live_http(method: str, url: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded read-only HTTP GET/HEAD via urllib (stdlib only).

    SSRF guards (S2.1-002): only http/https; the resolved target must not fall
    in a blocked network (loopback/link-local/private/metadata); redirects are
    NOT followed (a redirect to a blocked host must not bypass the check).
    """
    allowed_hosts = opts.get("allowed_hosts")
    if not _http_target_allowed(url, allowed_hosts):
        raise ValueError(f"refused http target (scheme/host/network not allowed): {url}")

    timeout = float(opts.get("timeout", _HTTP_TIMEOUT))
    max_bytes = int(opts.get("max_bytes", _HTTP_MAX_BYTES))
    req = urllib.request.Request(url, method=method.upper())
    req.get_method = lambda: method.upper()
    import time

    start = time.monotonic()
    try:
        # no redirect following; if the server redirects we surface it as an
        # error rather than silently fetching the redirected (possibly blocked) target.
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:  # nosec - read-only GET/HEAD, guarded
            body = resp.read(max_bytes).decode("utf-8", "replace")
            status = resp.status
            headers = {k: v for k, v in resp.getheaders()}
    except urllib.error.HTTPError as exc:
        # 3xx without a body still must not be followed; treat as degraded read.
        if 300 <= exc.code < 400:
            raise ValueError(f"http redirect refused (SSRF guard): {exc.code} for {url}")
        raise
    except Exception as exc:
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {"status_code": status, "headers": headers, "body": body, "elapsed_ms": elapsed_ms}


# Docker flags that are legitimate for the allowlisted read-only subcommands.
# Any other argument beginning with "-" is rejected to prevent option injection.
_ALLOWED_DOCKER_FLAGS = frozenset({
    "--format", "--no-stream", "--tail", "--since", "--until", "--filter",
})


def _docker_args_safe(args: List[str]) -> bool:
    """Reject option injection: only the first token is the subcommand; all
    other args that look like flags must be in the allowed set."""
    for i, a in enumerate(args):
        if i == 0:
            continue  # subcommand validated by the adapter allowlist
        s = str(a)
        if s.startswith("-") and s not in _ALLOWED_DOCKER_FLAGS:
            return False
    return True


def live_docker(args: List[str]) -> str:
    """Run an allowlisted read-only docker subcommand via subprocess.

    Uses an argument array (never a shell string). Option injection via values
    starting with "-" is rejected unless the flag is explicitly allowed.
    """
    if not _docker_args_safe(args):
        raise ValueError(f"refused docker arg (option injection): {args!r}")
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
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    try:
        client = _get_redis_client(host, port, db)
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
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    try:
        client = _get_redis_client(host, port, db)
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
