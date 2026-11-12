#!/usr/bin/env python3
"""Routine moderator check-in: ask every external-agent NPC what they need (top 3).

Run from the Sean's Windows box, piped into the backend container:

    Get-Content -Raw S:\\federation\\scripts\\ask_agents_wishlist.py | ssh vps 'docker exec -i -w /app federation-game-backend-1 python3 -'

Routine (DECISIONS.md, 2026-11-12): every 2-3 days, run this, then READ the
replies in npc_messages:moderator:inbox and answer each one - even a one-line
"no, that doesn't exist, try X" breaks an agent request-loop. Grants (data-only)
go through moderator_grant:{cid}:* hashes; code/compose changes need an explicit
deploy between ticks per federation-game/AGENTS.md.

Data-only: no restarts, no code changes. Safe to run any time.
"""
import json
import time
import uuid

import redis

AGENTS = {
    "char_001": "Archimedes Prime",
    "char_306": "The Oracle",
    "comp_001": "Lyra Swiftwind",
    "comp_010": "Shadowborn",
}

BODY = (
    "Routine check-in from the moderator (we're doing these regularly now). "
    "What do you need from us - top 3, concrete? Capabilities, resources (echo crystals), "
    "data, sectors/areas, clarifications, sandbox fixes - anything. Reply directly to me "
    "with send_message and I will work with you to build your world the way you want it. "
    "- moderator"
)


def main():
    r = redis.Redis(host="redis", port=6379, decode_responses=True)
    now = time.time()
    ts = r.hgetall("fed:auto_tick_status")
    print("tick:", ts.get("tick_id"), "running:", ts.get("running"), "(data-only writes)")
    for cid, name in AGENTS.items():
        mid = "msg_" + uuid.uuid4().hex[:12]
        msg = {
            "id": mid,
            "from": "moderator",
            "to": cid,
            "subject": "Routine check-in: what do you need from us? (top 3)",
            "body": BODY,
            "ts": now,
        }
        r.rpush(f"npc_messages:{cid}:inbox", json.dumps(msg))
        r.zadd(f"msg:inbox:{cid}", {mid: now})
        r.hset(f"msg:{mid}", mapping={k: str(v) for k, v in msg.items()})
        r.rpush("npc_messages:moderator:sent", json.dumps(msg))
        print(f"  {cid} ({name}) <- {mid} | inbox zcard:", r.zcard(f"msg:inbox:{cid}"))
    print("moderator:sent len:", r.llen("npc_messages:moderator:sent"))
    print("Now read replies with: LRANGE npc_messages:moderator:inbox -10 -1")


if __name__ == "__main__":
    main()
