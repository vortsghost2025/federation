"""CLI: `steward check <id>`.

S1: reads a frozen fixture JSON from disk (or stdin) and emits findings as
`finding.json` to stdout. No live I/O, no mutation. Exit code 0 always for S1
(pure observation); non-zero only on usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from .checks import ensure_loaded, list_checks, run_check
from .schema import Finding


def _load_fixture(path: str) -> Dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _split_fixture(check_id: str, fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the per-check payload and observed_at for `check_id`.

    Two fixture shapes are supported:

    1. Combined (for `check all`):
       {"observed_at": "...", "checks": {"<id>": {...payload...}, ...}}
       Each check receives its own `checks[<id>]` payload plus the shared
       `observed_at`.

    2. Single (for one named check):
       {"observed_at": "...", "<payload fields...>"}  OR a bare payload
       without observed_at (observed_at may be omitted for a single check,
       in which case the check synthesizes its own stable value from input).

    A missing per-check payload yields a deterministic "unknown" finding,
    never a silent skip (spec Sections 6, 8).
    """
    observed_at = fixture.get("observed_at")
    checks_block = fixture.get("checks")
    if check_id == "all":
        return fixture  # dispatched per-check below
    if isinstance(checks_block, dict) and check_id in checks_block:
        payload = dict(checks_block[check_id])
    else:
        # Treat the whole fixture (minus envelope keys) as the payload.
        payload = {k: v for k, v in fixture.items() if k not in ("observed_at", "checks")}
    if observed_at is not None:
        payload = {"observed_at": observed_at, **payload}
    return payload


def _emit(findings: List[Finding]) -> None:
    payload = {
        "engine": "steward@0.1.0",
        "finding_count": len(findings),
        "findings": [f.to_dict() for f in findings],
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="steward", description="The Steward S1 engine")
    sub = p.add_subparsers(dest="command", required=True)
    cp = sub.add_parser("check", help="run a check against a frozen fixture")
    cp.add_argument("check_id", help="check identifier, or 'all'")
    cp.add_argument(
        "--fixture",
        required=True,
        help="path to frozen fixture JSON ('-' for stdin)",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_loaded()
    fixture = _load_fixture(args.fixture)

    if args.check_id == "all":
        all_findings: List[Finding] = []
        checks_block = fixture.get("checks", {})
        observed_at = fixture.get("observed_at")
        for cid in list_checks():
            if isinstance(checks_block, dict) and cid in checks_block:
                payload = dict(checks_block[cid])
                if observed_at is not None:
                    payload = {"observed_at": observed_at, **payload}
            else:
                # Absent per-check payload -> deterministic unknown.
                payload = {"observed_at": observed_at} if observed_at is not None else {}
            all_findings.extend(run_check(cid, payload))
        _emit(all_findings)
        return 0

    _emit(run_check(args.check_id, _split_fixture(args.check_id, fixture)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
