#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Federation Architect Loop — Phase 1 Monitor.

DETECT → PACKETIZE → TRACK

Scans submitted capability requests via the local backend's read-only REST
API and produces durable Markdown request packets plus a lightweight JSON
registry. Does not mutate Redis DB0 or any upstream service.

Usage:
  python3 monitor.py                    # full scan + packetize new requests
  python3 monitor.py --list             # list all tracked requests
  python3 monitor.py --request <id>     # print packet for a request
  python3 monitor.py --diff             # only new requests since last run

State:    /docker/federation-architect/state/registry.json
Packets:  /docker/federation-architect/requests/{request_id}.md
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from datetime import timezone

# ── Constants ──────────────────────────────────────────────────────────
ARCHITECT_DIR  = "/docker/federation-architect"
STATE_DIR      = os.path.join(ARCHITECT_DIR, "state")
PACKET_DIR     = os.path.join(ARCHITECT_DIR, "requests")
REGISTRY_PATH  = os.path.join(STATE_DIR, "registry.json")

BACKEND_CONTAINER = os.environ.get("BACKEND_CONTAINER", "federation-game-backend-1")
BACKEND_INTERNAL  = os.environ.get("BACKEND_INTERNAL", "http://127.0.0.1:8000")
HTTP_TIMEOUT      = 15

LIFECYCLE_MAP  = {
    "draft": "drafting",
    "submitted": "review",
    "acknowledged": "planning",
    "approved": "implementing",
    "rejected": "closed",
    "delivered": "acceptance",
    "verification_pending": "verifying",
    "verified": "complete",
}

# ── Utility ────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"


def _get(path: str) -> dict:
    test_db = os.environ.get("REDIS_TEST_DB", "")
    if test_db and path == "/councilor/capability-requests":
        import subprocess
        db_url = test_db if "://" in test_db else f"redis://redis:{test_db}"
        py = (
            f"import redis,json,sys; "
            f"r=redis.from_url('{db_url}',decode_responses=True); "
            f"ids=r.zrange('npc_capability_requests:index',0,-1); "
            f"out=[]; "
            f"for rid in ids: "
            f"d=r.hgetall(f'npc_capability_request:{{rid}}'); "
            f"for f in ['consulted_npcs','transitions']: "
            f"  try: d[f]=json.loads(d.get(f,'[]')) "
            f"  except: d[f]=[]; "
            f"out.append(d); "
            f"print(json.dumps({{'requests':out,'count':len(out)}}))"
        )
        import subprocess as _sub
        r = _sub.run(["docker","exec",BACKEND_CONTAINER,"python3","-c",py],
                      capture_output=True, text=True, timeout=HTTP_TIMEOUT+5)
        if r.returncode == 0:
            return json.loads(r.stdout)
        return {"_error":r.stderr.strip()}
    direct_url = os.environ.get("BACKEND_URL", "")
    if direct_url:
        try:
            resp = urllib.request.urlopen(f"{direct_url}{path}", timeout=HTTP_TIMEOUT)
            return json.loads(resp.read().decode())
        except Exception as exc:
            return {"_error": str(exc)}
    import subprocess
    cmd = [
        "docker", "exec", BACKEND_CONTAINER,
        "python3", "-c",
        f"import urllib.request,json,sys; "
        f"resp=urllib.request.urlopen('{BACKEND_INTERNAL}{path}',timeout={HTTP_TIMEOUT}); "
        f"sys.stdout.write(resp.read().decode())"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=HTTP_TIMEOUT + 5)
        if result.returncode != 0:
            return {"_error": f"docker exec failed: {result.stderr.strip()}"}
        return json.loads(result.stdout)
    except Exception as exc:
        return {"_error": f"docker exec exception: {exc}"}


def _load_registry() -> dict:
    os.makedirs(STATE_DIR, exist_ok=True)
    if os.path.isfile(REGISTRY_PATH):
        try:
            return json.load(open(REGISTRY_PATH))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_run_iso": "", "requests": {}}


def _save_registry(reg: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    reg["last_run_iso"] = _now()
    tmp = REGISTRY_PATH + ".tmp"
    json.dump(reg, open(tmp, "w"), indent=2, sort_keys=True)
    os.replace(tmp, REGISTRY_PATH)


def pack(s: str) -> str:
    return s if s else "_(not provided)_"


# ── Packet generation ──────────────────────────────────────────────────

def packet_markdown(req: dict) -> str:
    rid   = req.get("request_id", "unknown")
    title = req.get("title", "Untitled")
    st    = req.get("status", "draft")
    stage = LIFECYCLE_MAP.get(st, st)
    requ  = req.get("requester_id", "?")
    coll  = req.get("collaborating_councilor_id", "")

    out = [
        f"# {title}",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Stage | {stage} |",
        f"| Status | {st} |",
        f"| Requester | {requ} |",
        f"| Collaborator | {coll} |",
        f"| Capability key | `{req.get('capability_key','')}` |",
        f"| Priority | {req.get('priority','medium')} |",
        f"| Agenda | {req.get('agenda_item_id','')} |",
        f"| Lifecycle version | {req.get('lifecycle_version','0')} |",
        f"",
        f"## Objective",
        f"{pack(req.get('objective',''))}",
        f"",
        f"## Blocker",
        f"{pack(req.get('blocker',''))}",
        f"",
        f"## Requested Change",
        f"{pack(req.get('requested_change',''))}",
        f"",
        f"## Attempts Already Made",
        f"{pack(req.get('attempts',''))}",
        f"",
        f"## Evidence",
        f"{pack(req.get('evidence',''))}",
        f"",
        f"## Acceptance Criteria",
        f"{pack(req.get('acceptance_criteria',''))}",
        f"",
        f"## Expected Benefit",
        f"{pack(req.get('expected_benefit',''))}",
        f"",
        f"## Implementation Risks",
        f"{pack(req.get('implementation_risks',''))}",
        f"",
        f"## Raw JSON (collapsed)",
        f"```json",
        json.dumps(req, indent=2, default=str),
        f"```",
        f"",
        f"## Architect Kilo command",
        f"",
        f"Copy into the active tmux Kilo session:",
        f"",
        f"```bash",
        f"# Process capability request {rid}",
        f"kilo run --session arch-loop --command /architect-entry \\",
        f"  \"process-request {rid}\"",
        f"```",
    ]
    return "\n".join(out)


# ── API calls (read-only) ──────────────────────────────────────────────

def fetch_all_capability_requests() -> list:
    resp = _get("/councilor/capability-requests")
    if resp.get("_error"):
        return []
    return resp.get("requests", [])

def fetch_submitted_requests() -> list:
    return [r for r in fetch_all_capability_requests() if r.get("status") == "submitted"]


# ── Process and save ───────────────────────────────────────────────────

def process_new_requests(reg: dict, requests: list) -> dict:
    reg_reqs = reg.setdefault("requests", {})
    os.makedirs(PACKET_DIR, exist_ok=True)
    for req in requests:
        return
        # This implementation looks broken — fix in monitor iteration below
        pass


# ── CLI dispatch ───────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        _cmd_default()
    elif args[0] == "--list":
        _cmd_list()
    elif args[0] == "--request" and len(args) > 1:
        _cmd_request(args[1])
    elif args[0] == "--diff":
        _cmd_diff()
    elif args[0] == "--debug":
        _cmd_debug()
    elif args[0] in ("--help", "-h"):
        print(__doc__.strip())
    else:
        print(f"Unknown argument: {args[0]}\n{__doc__.strip()}", file=sys.stderr)


def _cmd_default():
    print(f"Architect monitor  |  {_now()}")
    reg = _load_registry()
    all_reqs = fetch_all_capability_requests()
    if not all_reqs:
        print("No capability requests found.")
        _save_registry(reg)
        return

    submitted = [r for r in all_reqs if r.get("status") == "submitted"]
    print(f"{len(all_reqs)} total requests, {len(submitted)} submitted")

    reg_reqs = reg.setdefault("requests", {})
    os.makedirs(PACKET_DIR, exist_ok=True)
    new = 0

    for req in all_reqs:
        rid = req.get("request_id", "")
        if not rid:
            continue
        st = req.get("status", "draft")
        if rid not in reg_reqs:
            reg_reqs[rid] = {
                "detected_at": _now(),
                "last_checked_at": _now(),
                "status": st,
                "clarification_questions": [],
                "acceptance_001": {"result": None, "evidence": ""},
                "acceptance_306": {"result": None, "evidence": ""},
            }
            new += 1
        else:
            reg_reqs[rid]["last_checked_at"] = _now()
            reg_reqs[rid]["status"] = st

        # write/update packet
        with open(os.path.join(PACKET_DIR, f"{rid}.md"), "w") as fp:
            fp.write(packet_markdown(req))

    _save_registry(reg)
    print(f"{new} new requests tracked. Registry saved.")


def _cmd_list():
    reg = _load_registry()
    reqs = reg.get("requests", {})
    if not reqs:
        print("No tracked requests.")
        return
    for rid, entry in reqs.items():
        pth = os.path.join(PACKET_DIR, f"{rid}.md")
        ex = "✓" if os.path.isfile(pth) else "✗"
        print(f"  {ex}  {rid}  {entry.get('status','?')}  {entry.get('detected_at','?')}")


def _cmd_request(rid: str):
    pth = os.path.join(PACKET_DIR, f"{rid}.md")
    if os.path.isfile(pth):
        with open(pth) as fp:
            sys.stdout.write(fp.read())
    else:
        print(f"No packet found for {rid}")


def _cmd_diff():
    reg = _load_registry()
    all_req = fetch_all_capability_requests()
    submitted = [r for r in all_req if r.get("status") == "submitted"]
    known = set(reg.get("requests", {}).keys())
    diff = [r for r in submitted if r.get("request_id","") not in known]
    if not diff:
        print("No newly submitted requests (all are tracked).")
        return
    print(f"{len(diff)} NEW request(s):")
    for r in diff:
        print(f"  • {r.get('request_id','?')} — {r.get('title','')[:70]}")


def _cmd_debug():
    resp = _get("/councilor/capability-requests")
    print("BACKEND RESPONSE — raw:")
    print(json.dumps(resp, indent=2)[:2000])


if __name__ == "__main__":
    main()