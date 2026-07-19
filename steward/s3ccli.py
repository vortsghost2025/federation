"""S3C command-line interface (S3C-013).

Subcommands:
  run-fixture        run a fixture shadow plan (offline, deterministic)
  run-live-readonly  run the live read-only rehearsal (offline fixture mode)
  verify-bundle      verify a run bundle's manifest + sha256
  compare-runs       compare two read-only rehearsal runs for determinism
  readiness          print the readiness classification
  dagu-draft         print the illustrative (uninstalled) Dagu draft

SHADOW WARNING: This tool only ever operates in SHADOW MODE. There is no
live-apply / production flag and none can be added. The safety interlock fails
closed. No push is performed by any subcommand.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3 (sqlite3 only inside S3B backends).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from .s3c.bundles import RunBundle, sha256_of
from .s3c.dagu_draft import render_draft
from .s3c.manifest import RunManifest
from .s3c.orchestrator import run_fixture
from .s3c.readiness import evaluate as evaluate_readiness
from .s3c.rehearsal import run_rehearsal_twice

SHADOW_BANNER = (
    "=====================================================================\n"
    "  S3C SHADOW-MODE PIPELINE — NO LIVE APPLY / NO PRODUCTION PATH EXISTS\n"
    "  All runs are shadow-only. The safety interlock fails closed.\n"
    "  No push is performed by this tool.\n"
    "====================================================================="
)


def _cmd_run_fixture(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    findings = args.findings or [f"find_{i}" for i in range(1, 6)]
    bundle = run_fixture(
        finding_ids=findings,
        namespace=args.namespace,
        capability=args.capability,
        backend_kind=args.backend,
        approve_all=args.approve,
    )
    print(json.dumps(bundle.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_run_live_readonly(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    result = run_rehearsal_twice(namespace=args.namespace, backend_kind=args.backend)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _cmd_verify_bundle(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    try:
        with open(args.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        print(f"cannot read bundle: {exc}", file=sys.stderr)
        return 2
    try:
        bundle = RunBundle.from_payload(raw)
    except ValueError as exc:
        print(f"invalid bundle: {exc}", file=sys.stderr)
        return 2
    on_disk = sha256_of(args.path)
    ok = on_disk == bundle.sha256
    print(
        json.dumps(
            {
                "valid": True,
                "run_id": bundle.manifest.run_id,
                "manifest_mode": bundle.manifest.mode,
                "declared_sha256": bundle.sha256,
                "on_disk_sha256": on_disk,
                "sha_match": ok,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


def _cmd_compare_runs(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    result = run_rehearsal_twice(namespace=args.namespace, backend_kind=args.backend)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _cmd_readiness(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    report = evaluate_readiness(
        manifest_present=True,
        interlock_allowed=True,
        qualification_backends_ok=True,
        unknown_dependencies=[],
        policy_violations=[],
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_dagu_draft(args: argparse.Namespace) -> int:
    print(SHADOW_BANNER)
    print(json.dumps(render_draft(), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="steward.s3ccli", description="S3C shadow pipeline CLI")
    sub = p.add_subparsers(dest="command", required=True)

    rf = sub.add_parser("run-fixture", help="run a fixture shadow plan")
    rf.add_argument("--namespace", default="steward:shadow:gastown")
    rf.add_argument("--capability", default="steward:shadow:write")
    rf.add_argument("--backend", default="memory", choices=["memory", "sqlite"])
    rf.add_argument("--findings", nargs="*", default=None)
    rf.add_argument("--approve", action="store_true", help="attach valid non-wildcard approvals")
    rf.set_defaults(func=_cmd_run_fixture)

    rl = sub.add_parser("run-live-readonly", help="run live read-only rehearsal (offline fixture)")
    rl.add_argument("--namespace", default="steward:shadow:federation_vps")
    rl.add_argument("--backend", default="memory", choices=["memory", "sqlite"])
    rl.set_defaults(func=_cmd_run_live_readonly)

    vb = sub.add_parser("verify-bundle", help="verify a run bundle")
    vb.add_argument("--path", required=True)
    vb.set_defaults(func=_cmd_verify_bundle)

    cr = sub.add_parser("compare-runs", help="compare two read-only rehearsal runs")
    cr.add_argument("--namespace", default="steward:shadow:federation_vps")
    cr.add_argument("--backend", default="memory", choices=["memory", "sqlite"])
    cr.set_defaults(func=_cmd_compare_runs)

    rd = sub.add_parser("readiness", help="print readiness classification")
    rd.set_defaults(func=_cmd_readiness)

    dg = sub.add_parser("dagu-draft", help="print illustrative Dagu draft")
    dg.set_defaults(func=_cmd_dagu_draft)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
