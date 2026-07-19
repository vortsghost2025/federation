"""Read-only Redis adapter (S2).

Connects only through a dependency-injected command runner so no real network
I/O happens inside unit tests. The runner is allowlisted: only the read
commands enumerated in ``ALLOWED_REDIS_COMMANDS`` are dispatched. All writes,
EVAL, scripts, pub/sub, MONITOR, and unrestricted KEYS are refused.

On any refused command, timeout, or connection error, the adapter returns an
UNKNOWN snapshot -- never a fabricated healthy state.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot

# Read-only command allowlist (spec Section 5 / S2 authorization block).
ALLOWED_REDIS_COMMANDS = frozenset(
    {
        "PING", "INFO", "DBSIZE", "SCAN", "TYPE", "GET", "MGET",
        "HGET", "HMGET", "HGETALL", "HEXISTS", "HLEN", "TTL", "PTTL",
        "ZCARD", "ZRANGE", "ZSCORE", "SCARD", "SMEMBERS", "LLEN", "LRANGE",
    }
)

# Commands that read many keys and must be bounded.
_SCAN_LIKE = frozenset({"SCAN", "ZRANGE", "LRANGE", "SMEMBERS", "HGETALL"})


class RefusedCommandError(Exception):
    """Raised when a command is outside the read-only allowlist."""


def _check_command(cmd: str) -> str:
    upper = cmd.upper()
    if upper not in ALLOWED_REDIS_COMMANDS:
        raise RefusedCommandError(f"refused non-read-only command: {cmd}")
    return upper


def run_command(
    runner: Callable[[str, List[str]], Any],
    cmd: str,
    args: Optional[List[str]] = None,
    *,
    observed_at: str,
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    """Execute one allowlisted read command via the injected runner.

    ``runner`` signature: ``runner(command: str, args: List[str]) -> Any``.
    Returns a normalized snapshot. Refused/errored commands -> UNKNOWN.
    """
    args = args or []
    try:
        upper = _check_command(cmd)
    except RefusedCommandError as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=str(exc), provenance=provenance,
        )

    try:
        raw = runner(upper, list(args))
    except Exception as exc:  # timeout / connection / decode error
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"redis read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    data = asdict_safe({"command": upper, "args": args, "result": raw})
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="read-only command permitted",
        provenance=provenance,
    )


def collect_key_health(
    runner: Callable[[str, List[str]], Any],
    keys: List[str],
    *,
    observed_at: str,
    source: str = "redis",
    provenance: str = "",
) -> ObservationSnapshot:
    """Sample TTL/type for a bounded set of keys (no unbounded KEYS scan).

    Returns a normalized snapshot describing key presence, type, and TTL.
    """
    try:
        _check_command("TTL")
        _check_command("TYPE")
    except RefusedCommandError as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=str(exc), provenance=provenance,
        )

    sampled: Dict[str, Any] = {}
    try:
        for key in keys[:200]:  # hard bound to avoid huge payloads
            try:
                ktype = runner("TYPE", [key])
                ttl = runner("TTL", [key])
                sampled[key] = {"type": ktype, "ttl": ttl}
            except Exception:
                sampled[key] = {"type": "unknown", "ttl": None}
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"redis key-health read failed: {exc}",
            provenance=provenance,
        )

    return snapshot_from(
        source=source, observed_at=observed_at,
        data={"sampled_keys": asdict_safe(sampled), "key_count": len(sampled)},
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="bounded key sample (no KEYS scan)",
        provenance=provenance,
    )
