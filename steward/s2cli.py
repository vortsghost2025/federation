"""S2 read-only CLI: live/frozen snapshot collection + live check dispatch.

This module is SEPARATE from the S1 pure engine CLI (``steward.cli``). It may
perform read-only I/O (through collectors) and is the sanctioned S2 I/O
boundary. It reuses the S1 pure engine (``steward.checks.run_check``) to
interpret normalized snapshots -- no live I/O is added to S1.

Subcommands:
  snapshot <source|all> [--from-file PATH] [--save PATH] [--no-redact]
  check-live <id|all> --from-file PATH [--save PATH] [--no-redact]

Exit codes: 0 = ran (findings may exist), 2 = usage error.

S2 NEVER writes to Federation-world, Redis, Postgres, Docker, or any API.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from .adapters.base import ObservationSnapshot
from .collectors import (
    collect_docker_snapshot,
    collect_http_snapshot,
    collect_redis_key_health,
    collect_redis_snapshot,
    load_frozen_snapshot,
)
from .redact import redact_credentials_strong, redact_value

# Source -> collector factory. Each returns an ObservationSnapshot.
SOURCES = ("redis", "http", "docker", "npc", "semantic-loop", "host")


def _emit(snapshots: List[ObservationSnapshot], redact: bool) -> None:
    out = []
    for s in snapshots:
        d = s.to_dict()
        # Structural key-redaction can be toggled off by --no-redact, but
        # credential-pattern masking is ALWAYS applied before output leaves.
        if redact:
            d = redact_value(d)
        d = redact_credentials_strong(d)
        out.append(d)
    sys.stdout.write(json.dumps(out, sort_keys=True, indent=2) + "\n")


def _collect_source(source: str, observed_at: str, args) -> ObservationSnapshot:
    """Collect one live source. Falls back to UNKNOWN on any failure."""
    if source == "redis":
        return collect_redis_key_health(
            getattr(args, "redis_keys", []) or ["steward:ping"],
            observed_at=observed_at,
        )
    if source == "http":
        return collect_http_snapshot(
            getattr(args, "http_url", "http://127.0.0.1:8080/health"),
            observed_at=observed_at,
        )
    if source == "docker":
        return collect_docker_snapshot(
            getattr(args, "docker_args", None) or ["ps", "--format", "{{.Names}}"],
            observed_at=observed_at,
        )
    # npc / semantic-loop / host need fetchers; without injected live fetchers
    # we report UNKNOWN so the engine never infers healthy.
    return ObservationSnapshot(
        source=source, observed_at=observed_at,
        availability="unknown", status_detail="no live fetcher configured (S2 read-only)",
        data={},
    )


def _cmd_snapshot(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="steward s2 snapshot")
    p.add_argument("source", choices=list(SOURCES) + ["all"])
    p.add_argument("--from-file", help="load a frozen snapshot JSON instead of live")
    p.add_argument("--save", help="write snapshot JSON to this path")
    p.add_argument("--no-redact", action="store_true", help="disable secret redaction")
    p.add_argument("--observed-at", default="1970-01-01T00:00:00Z")
    p.add_argument("--redis-keys", nargs="*", default=[])
    p.add_argument("--http-url", default="http://127.0.0.1:8080/health")
    p.add_argument("--docker-args", nargs="*", default=None)
    ns = p.parse_args(argv)

    redact = not ns.no_redact
    if ns.source == "all":
        snaps = [_collect_source(s, ns.observed_at, ns) for s in SOURCES]
    else:
        if ns.from_file:
            snaps = [load_frozen_snapshot(ns.from_file, ns.source, ns.observed_at)]
        else:
            snaps = [_collect_source(ns.source, ns.observed_at, ns)]

    if ns.save:
        payload = [s.to_dict() for s in snaps]
        if redact:
            payload = redact_value(payload)
        # Always mask credentials, even when --no-redact was given.
        payload = redact_credentials_strong(payload)
        with open(ns.save, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, indent=2)
    _emit(snaps, redact)
    return 0


def _cmd_check_live(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="steward s2 check-live")
    p.add_argument("check_id", help="check identifier, or 'all'")
    p.add_argument("--from-file", required=True, help="frozen snapshot JSON to interpret")
    p.add_argument("--save", help="write finding JSON to this path")
    p.add_argument("--no-redact", action="store_true")
    ns = p.parse_args(argv)

    redact = not ns.no_redact
    snap = load_frozen_snapshot(ns.from_file, "unknown", "1970-01-01T00:00:00Z")

    # Map snapshot source to the S1 check that consumes it.
    source_to_check = {
        "npc_heartbeat_api": "npc-heartbeats",
        "pair_workspace": "semantic-loops",
    }
    check_id = source_to_check.get(snap.source, ns.check_id)

    from .checks import ensure_loaded, run_check

    ensure_loaded()
    # Hand the normalized snapshot data into the pure S1 engine.
    payload = dict(snap.data)
    if snap.observed_at:
        payload = {"observed_at": snap.observed_at, **payload}
    findings = run_check(check_id, payload) if ns.check_id != "all" else []
    if ns.check_id == "all":
        findings = []
        for cid in ("npc-heartbeats", "semantic-loops"):
            fp = dict(snap.data)
            if snap.observed_at:
                fp = {"observed_at": snap.observed_at, **fp}
            findings.extend(run_check(cid, fp))

    out = {
        "engine": "steward@0.1.0",
        "source": snap.source,
        "finding_count": len(findings),
        "findings": [f.to_dict() for f in findings],
    }
    if redact:
        out = redact_value(out)
    # Always mask credentials, even when --no-redact was given.
    out = redact_credentials_strong(out)
    text = json.dumps(out, sort_keys=True, indent=2)
    if ns.save:
        with open(ns.save, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    sys.stdout.write(text + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="steward-s2", description="Steward S2 read-only live adapters")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="collect a live/frozen read-only snapshot").set_defaults(func=_cmd_snapshot)
    sub.add_parser("check-live", help="interpret a frozen snapshot with the S1 engine").set_defaults(func=_cmd_check_live)
    return p


def main(argv: List[str] | None = None) -> int:
    # Parse the top-level command, then re-dispatch the remaining args to the
    # subcommand parser so each subcommand owns its own argument set.
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(prog="steward-s2", description="Steward S2 read-only live adapters")
    parser.add_argument("command", choices=["snapshot", "check-live"])
    head, rest = parser.parse_known_args(argv)
    if head.command == "snapshot":
        return _cmd_snapshot(rest)
    return _cmd_check_live(rest)


if __name__ == "__main__":
    raise SystemExit(main())
