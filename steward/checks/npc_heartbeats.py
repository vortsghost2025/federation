"""Check: npc-heartbeats (pure, S1).

Inputs fixture shape (frozen):
{
  "actors": [
    {
      "char_id": "char_001",
      "last_heartbeat_ts": "2026-07-18T22:55:00Z",  # ISO UTC, or null if never
      "observed_at": "2026-07-18T23:00:00Z",
      "expected_interval_seconds": 300,
      "age_factor": 3.0   # threshold = interval * factor
    }, ...
  ]
}

Threshold (spec 7.2): age > expected_interval * factor.
Severity: warning normally; error if heartbeat is null (never beat) or age is
extreme (> factor*2). Permitted: finding. Prohibited: triggering cognition.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..schema import Finding, make_finding
from . import register_check

# Stable sentinel used only when a caller supplies no observed_at. Never a
# clock value; keeps single-check manual runs deterministic and reproducible.
DEFAULT_OBSERVED_AT = "1970-01-01T00:00:00Z"


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def npc_heartbeats(fixture: Dict[str, Any]) -> List[Finding]:
    # Top-level observed_at (combined-fixture envelope) is the fallback clock
    # for the whole check. Each actor may override it with its own field.
    check_observed_at = fixture.get("observed_at", DEFAULT_OBSERVED_AT)
    actors = fixture.get("actors")
    if actors is None:
        return [
            make_finding(
                check_id="npc-heartbeats",
                observed_at=check_observed_at,
                severity="info",
                status="unknown",
                summary="NPC heartbeat source unavailable; cannot determine state.",
                evidence={"source": "npc_heartbeat_api"},
                dedupe_key="npc-heartbeat:unknown:npc_heartbeat_api",
                recommended_action="Verify heartbeat adapter (S2).",
            )
        ]

    findings: List[Finding] = []
    for a in actors:
        char_id = a.get("char_id", "unknown-char")
        # Per-actor observed_at wins; otherwise fall back to the check envelope.
        requested_observed_at = a.get("observed_at", check_observed_at)
        observed_at = _parse(requested_observed_at) or _parse(DEFAULT_OBSERVED_AT)
        interval = float(a.get("expected_interval_seconds", 300))
        factor = float(a.get("age_factor", 3.0))
        last = _parse(a.get("last_heartbeat_ts"))

        if last is None:
            age = None
            severity = "error"
            summary = f"{char_id} has never emitted a heartbeat."
        else:
            age = int((observed_at - last).total_seconds())
            threshold = interval * factor
            if age > threshold * 2:
                severity = "error"
                summary = f"{char_id} heartbeat age {age}s exceeds hard limit."
            elif age > threshold:
                severity = "warning"
                summary = f"{char_id} heartbeat age {age}s exceeds expected window."
            else:
                # healthy: do not emit a finding (only flag anomalies).
                continue

        findings.append(
            make_finding(
                check_id="npc-heartbeats",
                observed_at=requested_observed_at,
                severity=severity,
                summary=summary,
                evidence={
                    "char_id": char_id,
                    "last_heartbeat_ts": a.get("last_heartbeat_ts"),
                    "observed_at": requested_observed_at,
                    "age_seconds": age,
                    "expected_interval_seconds": interval,
                    "age_factor": factor,
                },
                affected_entities=[char_id],
                dedupe_key=f"npc-heartbeat:{char_id}",
                recommended_action="Investigate actor liveness; do not trigger cognition.",
                required_capability="",
                approval_required=False,
            )
        )
    return findings


register_check("npc-heartbeats", npc_heartbeats)
