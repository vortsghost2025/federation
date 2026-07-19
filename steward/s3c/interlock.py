"""S3C safety interlock — fail closed.

The interlock is the single gate that decides whether the shadow pipeline is
allowed to run a given plan. It MUST refuse by default (fail closed) unless
every condition below is satisfied:

1. mode is one of the 4 allowed shadow modes (S3C-002);
2. the backend is marked `qualification_only`;
3. the target namespace starts with `steward:shadow:`;
4. no live writer object is present;
5. no capability in the forbidden-live set is loaded:
     redis-write, postgres, federation-write, docker-mutation, ssh-write,
     dagu, npc-inbox, cognition;
6. no wildcard approval is in play;
7. the output directory is local and deemed safe (temp/local only);
8. redaction is enabled;
9. the caller supplied a deterministic timestamp (no wall-clock use).

Any violation returns an InterlockVerdict with allowed=False and a reason.
There is intentionally NO code path that relaxes these for "production".

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Capabilities that must NEVER be loaded for a shadow run.
FORBIDDEN_LIVE_CAPABILITIES = (
    "redis-write",
    "postgres",
    "federation-write",
    "docker-mutation",
    "ssh-write",
    "dagu",
    "npc-inbox",
    "cognition",
)

ALLOWED_MODES = (
    "fixture_plan",
    "fixture_shadow_apply",
    "live_readonly_plan",
    "live_readonly_shadow_apply",
)


@dataclass
class InterlockVerdict:
    allowed: bool
    reason: str
    checks: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "checks": dict(self.checks),
        }


def evaluate(
    *,
    mode: str,
    backend_qualification_only: bool,
    namespace: str,
    live_writer_present: bool,
    loaded_capabilities: List[str],
    wildcard_approval: bool,
    output_dir_local_safe: bool,
    redaction_enabled: bool,
    deterministic_timestamp_supplied: bool,
) -> InterlockVerdict:
    """Fail-closed evaluation. Returns allowed=True only if ALL checks pass."""

    checks: Dict[str, bool] = {
        "mode_allowed": mode in ALLOWED_MODES,
        "backend_qualification_only": backend_qualification_only,
        "namespace_shadow": namespace.startswith("steward:shadow:"),
        "no_live_writer": not live_writer_present,
        "no_forbidden_capability": not any(
            cap in FORBIDDEN_LIVE_CAPABILITIES for cap in loaded_capabilities
        ),
        "no_wildcard_approval": not wildcard_approval,
        "output_dir_local_safe": output_dir_local_safe,
        "redaction_enabled": redaction_enabled,
        "deterministic_timestamp": deterministic_timestamp_supplied,
    }

    denied = [name for name, ok in checks.items() if not ok]
    if not denied:
        return InterlockVerdict(
            allowed=True,
            reason="all interlock conditions satisfied",
            checks=checks,
        )
    return InterlockVerdict(
        allowed=False,
        reason=f"interlock refused: {', '.join(denied)}",
        checks=checks,
    )
