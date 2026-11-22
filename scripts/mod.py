#!/usr/bin/env python3
"""mod — Federation moderator CLI. Run inside the backend container:

    Get-Content -Raw scripts/mod.py | ssh vps 'docker exec -i -w /app federation-game-backend-1 python3 - <cmd> [args]'

Or via PowerShell wrapper (injection-safe base64 transport):
    .\\scripts\\mod.ps1 <cmd> [args]

Commands:
  health                              tick/capreq/llm/inbox/memory summary
  inbox [--all]                       show unread (or all recent) moderator inbox
  pins                                list moderator negative-fact pins
  reply <cid> <subject> <body>        backup, send to <cid> (list+zset), mark unread read
  read <cid> [n]                      last n decisions (default 8) with ages
  grants                              capability grants + sandbox exec stats per agent
  execs <cid>                         sandbox exec stats for one agent
  publish <title> <b64content>        publish a moderator artifact (base64 content)
  openq <pair_slug> <question>        validate & set pair open_question (with backup)
  capreq-close <id> <reason>          close an existing capability request (with backup)

Every write takes a real UTC-timestamped backup (30d TTL) first. Type-safe against Redis WRONGTYPE.
"""
import base64
import json
import re
import sys
import time
import uuid

import redis

AGENTS = ("comp_001", "comp_010", "char_001", "char_306")
NAMES = {
    "comp_001": "Lyra Swiftwind",
    "comp_010": "Shadowborn",
    "char_001": "Archimedes Prime",
    "char_306": "The Oracle",
}
BACKUP_TTL_SECONDS = 30 * 86400
_STUB_OPENQ_RE = re.compile(
    r"^what\s+about\s+(write|write_code|investigate|rest|think|send_message|create_artifact|read_artifacts)\s*\??$",
    re.I,
)


def get_redis():
    return redis.Redis(host="redis", port=6379, decode_responses=True)


def _now():
    return time.time()


def _safe_json(raw):
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _is_valid_open_question(question: str) -> bool:
    q = " ".join((question or "").split()).strip()
    if len(q) < 16 or len(q) > 240:
        return False
    if _STUB_OPENQ_RE.match(q):
        return False
    words = re.findall(r"[A-Za-z]{2,}", q)
    if len(words) < 4:
        return False
    if any(tok in q for tok in ("{", "}", "http://", "https://", "def ", "import ")):
        return False
    return True


def age_h(ts, now=None):
    try:
        ref = _now() if now is None else now
        return round((ref - float(ts)) / 3600.0, 2)
    except (TypeError, ValueError):
        return None


def backup(r, key, tag=None):
    if tag is None:
        tag = time.strftime("mod_%Y%m%d_%H%M%S", time.gmtime(_now()))
    t = r.type(key)
    if t == "list":
        data = r.lrange(key, 0, -1)
    elif t == "zset":
        data = r.zrange(key, 0, -1, withscores=True)
    elif t == "hash":
        data = r.hgetall(key)
    elif t == "set":
        data = sorted(r.smembers(key))
    elif t == "string":
        data = r.get(key)
    else:
        data = None
    bkey = f"backup:{key}:{tag}"
    r.set(bkey, json.dumps(data, default=str), ex=BACKUP_TTL_SECONDS)
    print(f"backup: {bkey} (ttl 30d)")
    return bkey


def send(r, cid, subject, body, now=None):
    ts = _now() if now is None else now
    mid = "msg_" + uuid.uuid4().hex[:12]
    msg = {
        "id": mid,
        "from": "moderator",
        "to": cid,
        "from_char_id": "moderator",
        "from_name": "Sean / Federation Moderator",
        "to_char_id": cid,
        "to_name": NAMES.get(cid, cid),
        "subject": subject,
        "body": body,
        "type": "direct_message",
        "topic": "respond",
        "read": False,
        "ts": ts,
        "created_at": ts,
    }
    raw = json.dumps(msg)
    # Write to BOTH legacy LIST inbox (npc_context.py / npc_decisions.py primary)
    # AND production ZSET inbox + HASH (peek_inbox / operator_directive fallback).
    r.rpush(f"npc_messages:{cid}:inbox", raw)
    r.zadd(f"msg:inbox:{cid}", {mid: ts})
    r.hset(f"msg:{mid}", mapping={k: str(v) for k, v in msg.items()})
    r.rpush("npc_messages:moderator:sent", raw)
    print(f"sent -> {cid}: {mid} (list + zset)")
    return mid


def mark_unread_read(r, cid=None):
    ib = r.lrange("npc_messages:moderator:inbox", 0, -1)
    marked = 0
    for i, m in enumerate(ib):
        d = _safe_json(m)
        if not d:
            continue
        if not d.get("read") and (cid is None or d.get("from_char_id") == cid):
            d["read"] = True
            r.lset("npc_messages:moderator:inbox", i, json.dumps(d))
            marked += 1
    if marked:
        print(f"marked read: {marked}")
    return marked


def cmd_health(r):
    t = r.hgetall("fed:auto_tick_status")
    print("tick:", {k: str(v)[:70] for k, v in t.items() if k != "last_result"})
    print("capreq:", r.zcard("npc_capability_requests:index"))
    print("pins:", r.scard("world_facts:nonexistent"))
    print("llm_health:", r.hgetall("monitor:llm_health"))
    ib = r.lrange("npc_messages:moderator:inbox", 0, -1)
    parsed = [_safe_json(m) for m in ib]
    unread = [d for d in parsed if d and not d.get("read")]
    bad = sum(1 for d in parsed if d is None)
    extra = f" (malformed={bad})" if bad else ""
    print(
        f"moderator inbox: {len(ib)} unread: {len(unread)}{extra} | sent: {r.llen('npc_messages:moderator:sent')}"
    )
    print("redis:", r.info("memory").get("used_memory_human"))


def cmd_inbox(r, show_all=False):
    ib = r.lrange("npc_messages:moderator:inbox", 0, -1)
    shown = 0
    now = _now()
    for m in ib:
        d = _safe_json(m)
        if not d:
            continue
        if not show_all and d.get("read"):
            continue
        print(
            f"FROM {d.get('from_char_id')} | age_h {age_h(d.get('ts') or d.get('created_at') or 0, now)} | read={d.get('read')}"
        )
        print("  subj:", (d.get("subject") or "")[:100])
        print("  body:", (d.get("body") or "")[:600].replace("\n", " "))
        print("  ---")
        shown += 1
    print(f"({shown} shown of {len(ib)})")


def cmd_pins(r):
    raw_items = r.smembers("world_facts:nonexistent") or []
    facts = [d for d in (_safe_json(x) for x in raw_items) if d]
    facts.sort(key=lambda f: float(f.get("ts") or 0))
    for f in facts:
        print(f"- [{f.get('id', '?')}] {f.get('text', '')}")
        if f.get("alternative"):
            print(f"    ALT: {f.get('alternative')}")
    print(f"({len(facts)} pins)")


def cmd_reply(r, cid, subject, body, force=False):
    if cid not in AGENTS and not force:
        raise ValueError(f"Unknown agent '{cid}' (expected one of {AGENTS}; pass --force to override)")
    tag = time.strftime("mod_%Y%m%d_%H%M%S", time.gmtime(_now()))
    backup(r, f"npc_messages:{cid}:inbox", tag)
    backup(r, f"msg:inbox:{cid}", tag)
    backup(r, "npc_messages:moderator:sent", tag)
    backup(r, "npc_messages:moderator:inbox", tag)
    send(r, cid, subject, body)
    mark_unread_read(r, cid)


def cmd_read(r, cid, n=8):
    z = r.zrange(f"npc_decisions:{cid}", -int(n), -1, withscores=True)
    now = _now()
    for e, score in z:
        d = _safe_json(e)
        if not d:
            continue
        print(
            f"  [{age_h(score, now)}h] {d.get('category')} | {(d.get('description') or d.get('reasoning') or '')[:140]}"
        )
        if d.get("action_taken"):
            print("      ->", d.get("action_taken"), "|", (d.get("summary") or "")[:120])


def exec_stats(r, cid):
    entries = r.zrange(f"npc_sandbox_exec_log:{cid}", 0, -1, withscores=True)
    stats = {
        "total": len(entries),
        "blocked": 0,
        "ok": 0,
        "failed": 0,
        "remote": 0,
        "local": 0,
        "last_age_h": None,
    }
    now = _now()
    last_ts = None
    for e, score in entries:
        d = _safe_json(e)
        if not d:
            continue
        if d.get("blocked"):
            stats["blocked"] += 1
        if d.get("ok") is True or d.get("ok") == "True":
            stats["ok"] += 1
        else:
            stats["failed"] += 1
        stats["remote" if d.get("path") == "remote" else "local"] += 1
        last_ts = d.get("ts", score)
    if last_ts is not None:
        stats["last_age_h"] = age_h(last_ts, now)
    return stats


def cmd_grants(r):
    for cid in AGENTS:
        g = sorted(r.smembers(f"npc_capability:grants:{cid}") or [])
        print(cid, "grants:", g, "| exec:", exec_stats(r, cid))


def cmd_publish(r, title, b64):
    content = base64.b64decode(b64).decode("utf-8")
    tag = time.strftime("mod_%Y%m%d_%H%M%S", time.gmtime(_now()))
    backup(r, "npc_artifacts:global", tag)
    backup(r, "npc_artifacts:moderator", tag)
    ts = _now()
    artifact = {
        "artifact_id": str(uuid.uuid4()),
        "char_id": "moderator",
        "char_name": "moderator",
        "title": title,
        "artifact_type": "reference_data",
        "content": content,
        "created_at": ts,
    }
    raw = json.dumps(artifact)
    r.rpush("npc_artifacts:global", raw)
    r.rpush("npc_artifacts:moderator", raw)
    print("published:", artifact["artifact_id"])
    return artifact["artifact_id"]


def cmd_openq(r, slug, question):
    key = f"npc_pair:{slug}:state"
    if not r.exists(key):
        raise ValueError(f"Pair state key does not exist: {key}")
    if not _is_valid_open_question(question):
        raise ValueError(f"Rejected invalid/too-short open_question: {question!r}")
    backup(r, key)
    r.hset(
        key,
        mapping={
            "open_question": question.strip(),
            "open_question_from": "moderator",
            "open_question_ts": str(int(_now())),
            "open_question_source": "moderator",
        },
    )
    print("open_question set on", key)


def cmd_capreq_close(r, rid, reason):
    key = f"npc_capability_request:{rid}"
    if not r.exists(key):
        raise ValueError(f"Capability request does not exist: {key}")
    backup(r, key)
    r.hset(
        key,
        mapping={
            "status": "rejected",
            "resolution": reason,
            "updated_ts": str(_now()),
        },
    )
    print("closed:", rid)


def parse_argv(argv):
    if len(argv) >= 2 and argv[0] == "--b64-argv":
        decoded = json.loads(base64.b64decode(argv[1]).decode("utf-8"))
        if not isinstance(decoded, list):
            raise ValueError("--b64-argv payload must be a JSON list")
        return [str(x) for x in decoded]
    return list(argv)


def dispatch(argv, r=None):
    args = parse_argv(argv)
    if not args:
        print(__doc__)
        return 0
    if r is None:
        r = get_redis()
    cmd, rest = args[0], args[1:]
    if cmd == "health":
        cmd_health(r)
    elif cmd == "inbox":
        cmd_inbox(r, show_all="--all" in rest)
    elif cmd == "pins":
        cmd_pins(r)
    elif cmd == "reply":
        force = "--force" in rest
        clean = [a for a in rest if a != "--force"]
        if len(clean) < 3:
            raise ValueError("reply requires <cid> <subject> <body>")
        cmd_reply(r, clean[0], clean[1], " ".join(clean[2:]), force=force)
    elif cmd == "read" and rest:
        cmd_read(r, rest[0], int(rest[1]) if len(rest) > 1 else 8)
    elif cmd == "grants":
        cmd_grants(r)
    elif cmd == "execs" and rest:
        print(rest[0], exec_stats(r, rest[0]))
    elif cmd == "publish" and len(rest) >= 2:
        cmd_publish(r, rest[0], rest[1])
    elif cmd == "openq" and len(rest) >= 2:
        cmd_openq(r, rest[0], " ".join(rest[1:]))
    elif cmd == "capreq-close" and len(rest) >= 2:
        cmd_capreq_close(r, rest[0], " ".join(rest[1:]))
    else:
        print(__doc__)
        return 2
    return 0


def main():
    try:
        rc = dispatch(sys.argv[1:])
        sys.exit(rc)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
