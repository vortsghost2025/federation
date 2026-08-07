"""
Command‑line interface for the Builder Agent.
Provides sub‑commands: status, list-pending, approve, reject, show-cognition, show-state.
All commands operate on the on‑disk state file and use `builder.redis_discovery`
to reach Redis when needed.
"""

import json
import os
import sys
from typing import Any, Dict

# Ensure the project root is on the import path when this module is run via
# `python -m builder.cli`. The package layout places this file under
# `/docker/federation-architect/builder/`.
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.append(root)

from builder.state import BuilderState
from builder.redis_discovery import get_redis

STATE_PATH = os.getenv("BUILDER_STATE_PATH", "/docker/federation-architect/builder/state.json")


def _load_state() -> BuilderState:
    return BuilderState(STATE_PATH)


def cmd_status(_: list[str]) -> None:
    state = _load_state()
    print(json.dumps({"stats": state.stats()}, indent=2))


def cmd_list_pending(_: list[str]) -> None:
    state = _load_state()
    print(json.dumps(state.pending(), indent=2))


def cmd_approve(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: approve <draft_id> <by>")
        sys.exit(1)
    draft_id, by = args[0], args[1]
    state = _load_state()
    ok = state.approve(draft_id, by)
    print(json.dumps({"approved": ok, "id": draft_id}, indent=2))


def cmd_reject(args: list[str]) -> None:
    if len(args) < 3:
        print("Usage: reject <draft_id> <by> <reason>")
        sys.exit(1)
    draft_id, by, reason = args[0], args[1], args[2]
    state = _load_state()
    ok = state.reject(draft_id, reason, by)
    print(json.dumps({"rejected": ok, "id": draft_id}, indent=2))


def cmd_show_cognition(args: list[str]) -> None:
    if len(args) < 1:
        print("Usage: show-cognition <char_id>")
        sys.exit(1)
    char_id = args[0]
    client = get_redis()
    if client is None:
        print(json.dumps({"error": "redis not reachable"}))
        sys.exit(1)
    key = f"npc_cognition:{char_id}"
    data = client.hgetall(key)
    # Decode bytes if needed
    if isinstance(data, dict):
        out = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
    else:
        out = {}
    print(json.dumps({"char": char_id, "cognition": out}, indent=2))


def cmd_show_state(args: list[str]) -> None:
    if len(args) < 1:
        print("Usage: show-state <char_id>")
        sys.exit(1)
    char_id = args[0]
    # Cognition
    client = get_redis()
    cogn = {}
    if client:
        raw = client.hgetall(f"npc_cognition:{char_id}")
        if isinstance(raw, dict):
            cogn = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in raw.items()}
    # Latest decision
    latest = None
    if client:
        dec = client.zrevrange(f"npc_decisions:{char_id}", 0, 0)
        if dec:
            try:
                latest = json.loads(dec[0])
            except Exception:
                latest = dec[0]
    out = {"char": char_id, "cognition": cogn, "latest_decision": latest}
    print(json.dumps(out, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: builder_cli <command> [args]")
        sys.exit(1)
    cmd, *args = sys.argv[1:]
    commands = {
        "status": cmd_status,
        "list-pending": cmd_list_pending,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "show-cognition": cmd_show_cognition,
        "show-state": cmd_show_state,
    }
    fn = commands.get(cmd)
    if not fn:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()
