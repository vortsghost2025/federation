"""S3A local-only CLI surface.

Commands:
    python -m steward.s3cli plan --finding FILE --snapshot FILE
    python -m steward.s3cli apply-fixture --actions FILE --store FILE
    python -m steward.s3cli inspect-fixture --store FILE

Requirements:
* `plan` is pure.
* `apply-fixture` operates ONLY on an explicitly local fixture store file.
* NO live mode exists.
* No Redis URL, Docker socket, HTTP endpoint, SSH host, or database URL arg.
* Output is always redacted and deterministic JSON.
* Safe output-path handling; symlink + traversal protection.
* Nonzero exit codes for invalid usage, denied action, conflict, malformed approval.

S3A HAS NO LIVE FEDERATION WRITER.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from .s3a_action import ProposedAction
from .s3a_audit import redact_evidence
from .s3a_planner import plan_actions
from .s3a_policy import ApprovalArtifact
from .s3a_store import InMemoryStore
from .s3a_writer import WriterCore

BANNER = "S3A HAS NO LIVE FEDERATION WRITER."


def _safe_path(path: str, base_dir: str) -> str:
    """Reject symlinks and path traversal; return an absolute, contained path."""
    abs_path = os.path.abspath(path)
    abs_base = os.path.abspath(base_dir)
    if os.path.islink(path):
        raise ValueError(f"symlink paths are not permitted: {path}")
    if not abs_path.startswith(abs_base):
        raise ValueError(f"path escapes allowed directory: {path}")
    return abs_path


def _load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_plan(args: argparse.Namespace) -> int:
    finding_doc = _load_json_file(args.finding)
    snapshot_doc = _load_json_file(args.snapshot)
    findings = finding_doc if isinstance(finding_doc, list) else [finding_doc]
    snapshot_id = snapshot_doc.get("snapshot_id", "snap:unknown") \
        if isinstance(snapshot_doc, dict) else "snap:unknown"
    requested_at = args.requested_at or "ts:cli"
    actions = plan_actions(findings, snapshot_id, requested_at)
    out = {
        "banner": BANNER,
        "action_count": len(actions),
        "actions": [a.to_dict() for a in actions],
    }
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0


def cmd_apply_fixture(args: argparse.Namespace) -> int:
    actions_doc = _load_json_file(args.actions)
    action_list = actions_doc.get("actions", actions_doc) \
        if isinstance(actions_doc, dict) else actions_doc
    store = InMemoryStore()
    writer = WriterCore(store)
    now_token = args.now_token or "ts:cli"
    results: List[Dict[str, Any]] = []
    exit_code = 0
    approval = None
    if args.approval:
        appr_doc = _load_json_file(args.approval)
        approval = ApprovalArtifact.from_dict(appr_doc)
    for raw in action_list:
        action = ProposedAction.from_dict(raw)
        outcome = writer.execute(action, now_token, approval=approval)
        results.append(outcome.result.to_dict())
        if outcome.result.decision == "denied":
            exit_code = 2
    # Persist ONLY to the explicitly local fixture store file.
    base_dir = os.path.abspath(args.store_dir or os.path.dirname(os.path.abspath(args.store)))
    store_path = _safe_path(args.store, base_dir)
    with open(store_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"banner": BANNER, "records": store.render_councilor_watch()},
            fh,
            sort_keys=True,
            indent=2,
        )
    out = {
        "banner": BANNER,
        "results": results,
    }
    print(json.dumps(out, sort_keys=True, indent=2))
    return exit_code


def cmd_inspect_fixture(args: argparse.Namespace) -> int:
    base_dir = os.path.abspath(args.store_dir or os.path.dirname(os.path.abspath(args.store)))
    store_path = _safe_path(args.store, base_dir)
    if not os.path.exists(store_path):
        print(json.dumps({"error": "fixture store not found", "banner": BANNER}))
        return 1
    with open(store_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    print(json.dumps({"banner": BANNER, "records": doc.get("records", [])}, sort_keys=True, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steward.s3cli",
        description="S3A local-only governed writer CLI. " + BANNER,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="pure plan from finding + snapshot")
    p_plan.add_argument("--finding", required=True)
    p_plan.add_argument("--snapshot", required=True)
    p_plan.add_argument("--requested-at", dest="requested_at", default=None)
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply-fixture", help="apply actions to a local fixture store")
    p_apply.add_argument("--actions", required=True)
    p_apply.add_argument("--store", required=True)
    p_apply.add_argument("--approval", default=None)
    p_apply.add_argument("--now-token", dest="now_token", default=None)
    p_apply.add_argument("--store-dir", dest="store_dir", default=None)
    p_apply.set_defaults(func=cmd_apply_fixture)

    p_inspect = sub.add_parser("inspect-fixture", help="inspect a local fixture store")
    p_inspect.add_argument("--store", required=True)
    p_inspect.add_argument("--store-dir", dest="store_dir", default=None)
    p_inspect.set_defaults(func=cmd_inspect_fixture)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "banner": BANNER}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
