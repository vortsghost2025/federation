"""Check contract for S1.

A check is a pure function: it receives a fixture (a plain dict representing a
frozen observation snapshot) and returns a list[Finding]. Checks MUST NOT
perform any I/O, network, process, or mutation. If the fixture is missing the
needed source, the check returns a single Finding with status="unknown".
"""

from __future__ import annotations

import importlib
from typing import Callable, Dict, List

from ..schema import Finding, make_finding

CheckFn = Callable[[dict], List[Finding]]

# Registry populated by register_check / load_checks.
_REGISTRY: Dict[str, CheckFn] = {}


def register_check(check_id: str, fn: CheckFn) -> None:
    _REGISTRY[check_id] = fn


def get_check(check_id: str) -> CheckFn:
    if check_id not in _REGISTRY:
        raise KeyError(f"unknown check: {check_id}")
    return _REGISTRY[check_id]


def list_checks() -> List[str]:
    return sorted(_REGISTRY)


def run_check(check_id: str, fixture: dict) -> List[Finding]:
    """Run a registered check against a frozen fixture."""
    return get_check(check_id)(fixture)


def _unknown(check_id: str, source: str, detail: str) -> Finding:
    return make_finding(
        check_id=check_id,
        severity="info",
        status="unknown",
        summary=f"Source '{source}' unavailable; cannot determine state.",
        evidence={"source": source, "detail": detail},
        dedupe_key=f"{check_id}:unknown:{source}",
        recommended_action="Verify adapter connectivity (S2).",
        required_capability="",
        approval_required=False,
    )


def ensure_loaded() -> None:
    """Import check modules so registration side effects run."""
    if _REGISTRY:
        return
    importlib.import_module(".semantic_loops", __package__)
    importlib.import_module(".npc_heartbeats", __package__)
