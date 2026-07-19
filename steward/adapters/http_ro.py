"""Read-only HTTP adapter (S2).

Only GET and HEAD are permitted. Requests are bounded by timeout and max
response size. Only health-oriented endpoints should be queried. On any
failure the adapter returns UNKNOWN -- never infers healthy from a failed read.

Network I/O is provided by an injected ``requester`` so the adapter is
unit-testable without touching the network.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_BYTES = 64 * 1024
ALLOWED_METHODS = frozenset({"GET", "HEAD"})


class HttpRefusedMethodError(Exception):
    """Raised when a non-read-only HTTP method is requested."""


def _check_method(method: str) -> str:
    upper = method.upper()
    if upper not in ALLOWED_METHODS:
        raise HttpRefusedMethodError(f"refused non-read-only method: {method}")
    return upper


def fetch(
    requester: Callable[[str, str, Dict[str, Any]], Any],
    url: str,
    *,
    method: str = "GET",
    observed_at: str,
    source: str = "http",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    provenance: str = "",
) -> ObservationSnapshot:
    """Issue a read-only HTTP request via the injected requester.

    ``requester`` signature:
        ``requester(method, url, opts) -> {"status_code": int,
                                          "headers": dict,
                                          "body": str (trimmed),
                                          "elapsed_ms": int}``
    Returns UNKNOWN on refused method, timeout, or error.
    """
    try:
        upper = _check_method(method)
    except HttpRefusedMethodError as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=str(exc), provenance=provenance,
        )

    opts = {"timeout": timeout, "max_bytes": max_bytes}
    try:
        resp = requester(upper, url, opts)
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"http read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    status = int(resp.get("status_code", 0))
    availability = (
        Availability.AVAILABLE.value
        if 200 <= status < 400
        else Availability.DEGRADED.value
    )
    data = asdict_safe(
        {
            "url": url,
            "method": upper,
            "status_code": status,
            "elapsed_ms": resp.get("elapsed_ms"),
            "headers": {k: v for k, v in (resp.get("headers") or {}).items()},
            "body_excerpt": (resp.get("body") or "")[:max_bytes],
        }
    )
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=availability,
        version=None, status_detail="read-only GET/HEAD health check",
        provenance=provenance,
    )
