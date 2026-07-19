"""Read-only Docker adapter (S2).

Inspection only. Docker commands are run through an injected command runner so
no real container changes occur during tests. Only info-only Docker subcommands
are permitted; start/stop/restart/kill/rm/run/exec-in-app-containers and
compose mutations are refused.

On any refused or errored command, the adapter returns UNKNOWN.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Availability, ObservationSnapshot, asdict_safe, snapshot_from, unknown_snapshot

# Info-only Docker subcommands (spec Section 5 / S2 authorization block).
ALLOWED_DOCKER_SUBCOMMANDS = frozenset(
    {
        "ps",          # docker ps
        "inspect",     # docker inspect
        "stats",       # docker stats --no-stream
        "logs",        # docker logs --tail
        "network",     # docker network inspect
        "volume",      # docker volume inspect
    }
)

# Subcommands that would mutate or enter app containers -> refused.
FORBIDDEN_DOCKER_SUBCOMMANDS = frozenset(
    {
        "start", "stop", "restart", "kill", "rm", "run", "exec",
        "compose", "update", "rename", "pause", "unpause", "cp",
    }
)


class RefusedDockerCommandError(Exception):
    """Raised when a Docker subcommand is outside the read-only allowlist."""


def _check_subcommand(subcommand: str) -> str:
    sc = subcommand.lower()
    if sc in FORBIDDEN_DOCKER_SUBCOMMANDS:
        raise RefusedDockerCommandError(f"refused mutating docker subcommand: {subcommand}")
    if sc not in ALLOWED_DOCKER_SUBCOMMANDS:
        raise RefusedDockerCommandError(f"refused non-info docker subcommand: {subcommand}")
    return sc


def run(
    runner: Callable[[List[str]], Any],
    args: List[str],
    *,
    observed_at: str,
    source: str = "docker",
    provenance: str = "",
) -> ObservationSnapshot:
    """Run an allowlisted read-only docker subcommand via the injected runner.

    ``runner`` signature: ``runner(full_args: List[str]) -> str`` (raw output).
    Returns UNKNOWN on refused subcommand or execution error.
    """
    if not args:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail="empty docker command", provenance=provenance,
        )
    try:
        _check_subcommand(args[0])
    except RefusedDockerCommandError as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=str(exc), provenance=provenance,
        )

    try:
        raw = runner([str(a) for a in args])
    except Exception as exc:
        return unknown_snapshot(
            source=source, observed_at=observed_at,
            detail=f"docker read failed: {type(exc).__name__}: {exc}",
            provenance=provenance,
        )

    data = asdict_safe(
        {
            "command": ["docker", *[str(a) for a in args]],
            "output_excerpt": str(raw)[:4096],
        }
    )
    return snapshot_from(
        source=source, observed_at=observed_at, data=data,
        availability=Availability.AVAILABLE.value,
        version=None, status_detail="read-only docker inspection",
        provenance=provenance,
    )
