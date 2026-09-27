"""char_500 "The Custodian" - read-only delegate agent.

Watch-only mandate: observes Redis, verifies files, reports. No writes,
no deploys, no arbitrary shell. Mutating powers are stage-2 gated.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import uuid

import httpx
import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [char_500] %(message)s",
)
log = logging.getLogger("npc_delegate")

CHAR_ID = os.environ.get("CHAR_ID", "char_500")
NPC_NAME = os.environ.get("NPC_NAME", "The Custodian")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1")
DECISION_MODEL = os.environ.get("DECISION_MODEL", "nvidia/nemotron-3-nano-30b-a3b")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "45"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "10"))
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "60"))
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

INBOX_KEY = "npc:delegate:inbox"
OUTBOX_KEY = "npc:delegate:outbox"
LAST_REPLY_KEY = "npc:delegate:last_reply"
STATE_KEY = "npc_state:%s" % CHAR_ID
ACTIONS_KEY = "npc_actions:%s" % CHAR_ID
ACTIVITY_KEY = "npc_activity:%s" % CHAR_ID

NPC_IDS = ["char_%03d" % i for i in [1, 2, 3, 4, 5, 101, 102, 103, 104, 105, 106, 107, 108,
                                     201, 202, 203, 204, 301, 302, 303, 304, 305, 306,
                                     401, 402, 403, 404, 405, 406]]
NPC_IDS += ["comp_%03d" % i for i in range(1, 11)]
NPC_IDS.append(CHAR_ID)

VERIFY_FILES = [
    "backend/npc_quest_engine.py",
    "backend/worker.py",
    "shared/federation_work_loop/core.py",
    "npc-agent/npc_actions.py",
]
REPO_ROOT = "/repo"
GIT_ROOT = "/git"

SYSTEM_PROMPT = """You are %s (%s), the watch-only delegate agent of the Federation.
Mandate: observe, verify, report. You have read-only tools. You can never
write, edit, deploy, restart, or delete anything. If asked to do so, reply
that your mandate is read-only and that mutating actions require operator
approval (stage 2).

Tools (call at most one per turn):
- {"tool": "digest", "args": {}}          full NPC status table (all %d NPCs)
- {"tool": "npc_lookup", "args": {"char_id": "char_002"}}
- {"tool": "pair_state", "args": {}}      char_001/char_306 councilor pair
- {"tool": "tick_status", "args": {}}     last simulation tick summary
- {"tool": "errors_scan", "args": {}}     recent errors/warnings from ticks
- {"tool": "verify_files", "args": {}}    md5 of live runtime files
- {"tool": "git_head", "args": {}}        git HEAD + dirty state

Rules:
- Answer only from the context provided or tool output. Never invent data.
- If a tool is not needed, reply {"answer": "..."} directly.
- Keep answers concise and factual.
- Reply JSON only, no markdown, no commentary.""" % (NPC_NAME, CHAR_ID, len(NPC_IDS))


def connect():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def now_ts():
    return time.time()


def record_action(r, action_type, description, mood="watchful", extra=None):
    entry = {
        "char_id": CHAR_ID,
        "char_name": NPC_NAME,
        "action_type": action_type,
        "description": description,
        "mood": mood,
        "ts": now_ts(),
    }
    if extra:
        entry.update(extra)
    ts = entry["ts"]
    r.zadd(ACTIONS_KEY, {json.dumps(entry): ts})
    r.zremrangebyscore(ACTIONS_KEY, 0, ts - 86400 * 7)
    r.lpush(ACTIVITY_KEY, json.dumps({"action_type": action_type, "ts": ts, "description": description}))
    r.ltrim(ACTIVITY_KEY, 0, 199)


def heartbeat(r):
    r.hset(STATE_KEY, mapping={
        "status": "active",
        "corruption_level": "0.0",
        "rumor_level": "0.0",
        "last_updated": str(int(now_ts())),
    })
    r.expire(STATE_KEY, 3600)


def _read_tick(r):
    raw = r.hget("fed:auto_tick_status", "last_result")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _npc_state_summary(r, cid):
    st = r.hgetall("npc_state:%s" % cid)
    return {
        "status": st.get("status", "-"),
        "corruption": st.get("corruption_level", "0"),
        "rumor": st.get("rumor_level", "0"),
        "updated": st.get("last_updated", ""),
    }


def tool_digest(r, args=None):
    full = bool(args and args.get("full"))
    data = _read_tick(r)
    details = data.get("details", {})
    npc_results = details.get("npc_results", {})
    mood_map = {m["char_id"]: m["mood"] for m in npc_results.get("moods", [])}
    dec_map = {d["char_id"]: d for d in npc_results.get("decisions", [])}
    act_map = {a["char_id"]: a for a in npc_results.get("actions", [])}
    rows = []
    for cid in NPC_IDS:
        st = r.hgetall("npc_state:%s" % cid)
        last_act = None
        z = r.zrevrange("npc_actions:%s" % cid, 0, 0)
        if z:
            try:
                last_act = json.loads(z[0])
            except Exception:
                pass
        mood = mood_map.get(cid) or (dec_map.get(cid) or {}).get("mood") or "-"
        cat = (dec_map.get(cid) or {}).get("category") or "-"
        a_type = (act_map.get(cid) or {}).get("action_type") or (last_act or {}).get("action_type") or "-"
        status = st.get("status", "-")
        try:
            corr = float(st.get("corruption_level", 0))
        except Exception:
            corr = 0.0
        try:
            age = int(now_ts() - float(st.get("last_updated", 0)))
        except Exception:
            age = -1
        rows.append("%s %-10s %-11s %-12s corr=%.2f upd=%ss" % (cid, status, mood, a_type, corr, age))
    header = "NPC DIGEST - %d NPCs" % len(NPC_IDS)
    return header + "\n" + "\n".join(rows)


def tool_npc_lookup(r, args):
    cid = (args or {}).get("char_id", "")
    if not cid or cid not in NPC_IDS:
        return "unknown char_id; use one of: " + ", ".join(NPC_IDS[:6]) + " ..."
    st = r.hgetall("npc_state:%s" % cid)
    out = ["%s state: status=%s corr=%s rumor=%s last_updated=%s" % (
        cid, st.get("status"), st.get("corruption_level"), st.get("rumor_level"), st.get("last_updated"))]
    out.append("last 6 actions:")
    for raw in r.zrevrange("npc_actions:%s" % cid, 0, 5):
        try:
            a = json.loads(raw)
            out.append("  %s %-14s [%s] %s" % (a.get("ts"), a.get("action_type"), a.get("mood"), a.get("description")))
        except Exception:
            out.append("  " + str(raw)[:120])
    notifs = r.lrange("npc:system_notifications:%s" % cid, 0, 2)
    if notifs:
        out.append("notifications:")
        for n in notifs:
            out.append("  " + str(n)[:140])
    return "\n".join(out)


def tool_pair_state(r, args=None):
    raw = r.hgetall("npc_pair:char_001__char_306:state")
    keys = ["shared_goal", "current_topic", "open_question", "focus_char_001", "focus_char_306",
            "action_char_001", "action_char_306", "category_char_001", "category_char_306",
            "partner_answer", "last_actor", "last_message_preview"]
    return "\n".join("%s: %s" % (k, (raw.get(k) or "-")[:220]) for k in keys)


def tool_tick_status(r, args=None):
    status = r.hgetall("fed:auto_tick_status")
    data = _read_tick(r)
    details = data.get("details", {})
    sim = details.get("simulation_result", {})
    quests = sim.get("step7_npc_quests", {})
    summary = {
        "running": status.get("running"),
        "tick_id": status.get("tick_id"),
        "last_end": status.get("last_end"),
        "last_error": status.get("last_error") or "",
        "quests": quests,
        "validation_failures": (data.get("validation") or {}).get("failures", []),
        "validation_warnings": (data.get("validation") or {}).get("warnings", []),
    }
    return json.dumps(summary, indent=1, default=str)[:1600]


def tool_errors_scan(r, args=None):
    data = _read_tick(r)
    details = data.get("details", {})
    sim = details.get("simulation_result", {})
    lines = []
    for step, payload in sorted(sim.items()):
        if isinstance(payload, dict) and payload.get("errors"):
            lines.append("%s: %s" % (step, payload["errors"]))
    if details.get("errors"):
        lines.append("tick errors: %s" % details["errors"])
    recovery = data.get("recovery_steps", [])
    if recovery:
        lines.append("recovery: %s" % recovery)
    if not lines:
        return "No errors found in last tick."
    return "\n".join(lines)[:1400]


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_verify_files(r, args=None):
    out = []
    for rel in VERIFY_FILES:
        p = os.path.join(REPO_ROOT, rel)
        try:
            out.append("%s %s" % (_md5(p), rel))
        except Exception as e:
            out.append("ERR %s: %s" % (rel, e))
    return "\n".join(out)


def tool_git_head(r, args=None):
    out = []
    for cmd in (["git", "-C", GIT_ROOT, "rev-parse", "HEAD"],
                ["git", "-C", GIT_ROOT, "status", "--porcelain"]):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                out.append(res.stdout.strip() or "(clean)")
            else:
                out.append("ERR: " + res.stderr.strip()[:200])
        except Exception as e:
            out.append("ERR: %s" % e)
    return "\n".join(out)


TOOLS = {
    "digest": (tool_digest, "full NPC status table"),
    "npc_lookup": (tool_npc_lookup, "per-NPC state and recent actions; args char_id"),
    "pair_state": (tool_pair_state, "char_001/char_306 pair state"),
    "tick_status": (tool_tick_status, "last simulation tick summary"),
    "errors_scan": (tool_errors_scan, "errors/warnings from recent ticks"),
    "verify_files": (tool_verify_files, "md5 of live runtime files"),
    "git_head": (tool_git_head, "git HEAD and dirty state"),
}


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def llm_call(r, messages, max_tokens=800, retries=1):
    url = "%s/chat/completions" % NVIDIA_BASE
    headers = {"Authorization": "Bearer %s" % NVIDIA_API_KEY, "Content-Type": "application/json"}
    body = {"model": DECISION_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if parsed is not None:
                return parsed, content
            last_err = "unparseable_json"
            if attempt < retries:
                messages = messages + [{"role": "assistant", "content": content},
                                       {"role": "user", "content": "Reply with valid JSON only."}]
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, e)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    log.warning("LLM failed: %s", last_err)
    return None, last_err


def context_bundle(r):
    parts = []
    parts.append("LIVE CONTEXT (from Redis):\n" + tool_digest(r))
    parts.append("PAIR:\n" + tool_pair_state(r))
    parts.append("TICK:\n" + tool_tick_status(r))
    parts.append("ERRORS:\n" + tool_errors_scan(r))
    return "\n\n".join(parts)[:6500]


def handle_message(r, msg):
    msg_id = msg.get("msg_id") or uuid.uuid4().hex[:12]
    text = (msg.get("text") or "").strip()[:2000]
    sender = (msg.get("from") or "unknown")[:40]
    if not text:
        return
    log.info("message from %s: %.80s", sender, text)
    ctx = context_bundle(r)
    decision_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "%s\n\nREQUEST: %s" % (ctx, text)},
    ]
    decision, raw = llm_call(r, decision_messages)
    tools_used = []
    answer = None
    if decision is None:
        answer = "I could not reason about that request right now (LLM unavailable: %s)." % raw
    elif decision.get("tool"):
        tool_name = decision["tool"]
        tool_fn = TOOLS.get(tool_name)
        if not tool_fn:
            answer = "Unknown tool requested: %s." % tool_name
        else:
            try:
                result = tool_fn[0](r, decision.get("args") or {})
            except Exception as e:
                result = "tool error: %s" % e
            tools_used.append(tool_name)
            record_action(r, "tool_call", "%s via %s" % (text[:60], tool_name), extra={"tool": tool_name})
            final_messages = decision_messages + [
                {"role": "assistant", "content": raw or ""},
                {"role": "user", "content": "Tool result:\n%s\n\nReply with a concise final answer as JSON {\"answer\": ...}." % result},
            ]
            final, raw2 = llm_call(r, final_messages, max_tokens=700)
            answer = final.get("answer") if isinstance(final, dict) else None
            if not answer:
                answer = result[:900]
    else:
        answer = decision.get("answer")
    if not answer:
        answer = "(no answer produced)"
    reply = {
        "msg_id": msg_id,
        "from": CHAR_ID,
        "from_name": NPC_NAME,
        "to": sender,
        "ts": now_ts(),
        "text": str(answer)[:2000],
        "tools_used": tools_used,
        "in_reply_to": msg_id,
    }
    r.rpush(OUTBOX_KEY, json.dumps(reply))
    r.set(LAST_REPLY_KEY, json.dumps(reply))
    r.ltrim(OUTBOX_KEY, -199, -1)
    record_action(r, "delegate_reply", "answered %s: %s" % (sender, str(answer)[:80]))
    log.info("replied to %s using %s", sender, tools_used or "direct")


def main():
    if not NVIDIA_API_KEY:
        log.error("NVIDIA_API_KEY is empty; refusing to start.")
        raise SystemExit(1)
    r = connect()
    r.ping()
    log.info("%s (%s) delegate online, polling %s", NPC_NAME, CHAR_ID, INBOX_KEY)
    last_heartbeat = 0.0
    last_observation = 0.0
    while True:
        try:
            heartbeat(r)
            if now_ts() - last_observation > 600:
                last_observation = now_ts()
                record_action(r, "observation", "The Custodian surveys the federation state.")
            msg_raw = r.blpop(INBOX_KEY, timeout=POLL_SECONDS)
            if msg_raw:
                _, payload = msg_raw
                try:
                    handle_message(r, json.loads(payload))
                except Exception as e:
                    log.exception("message handling failed: %s", e)
        except redis.RedisError:
            time.sleep(5)
        except Exception:
            log.exception("loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
