import json
import logging
import os
import re
import time
import uuid

import redis

logger = logging.getLogger("npc_redis_helpers")

CHAR_ID = os.environ.get("CHAR_ID", "")
PAIR_IDS = {"char_001", "char_306"}
PAIR_STATE_TTL = int(os.environ.get("PAIR_STATE_TTL", str(86400 * 30)))
PAIR_JOURNAL_CAP = int(os.environ.get("PAIR_JOURNAL_CAP", "48"))
PAIR_MESSAGE_COOLDOWN = int(os.environ.get("PAIR_MESSAGE_COOLDOWN", "180"))
SESSION_CAP = int(os.environ.get("SESSION_CAP", "24"))
SESSION_TRANSCRIPT_CHARS = int(os.environ.get("SESSION_TRANSCRIPT_CHARS", "1800"))
OPEN_QUESTION_REPEAT_HOURS = int(os.environ.get("OPEN_QUESTION_REPEAT_HOURS", "6"))
QUESTION_TOKEN_RE = re.compile(r"[a-z0-9]+")
TICK_INTERVAL = int(os.environ.get("TICK_INTERVAL", "30"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


def _trunc(s, n=400):
    return s[:n] + "..." if len(s) > n else s


def _normalize_question(text: str) -> str:
    return " ".join(QUESTION_TOKEN_RE.findall((text or "").lower()))


def _question_similarity(a: str, b: str) -> float:
    a_norm = _normalize_question(a)
    b_norm = _normalize_question(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm or a_norm in b_norm or b_norm in a_norm:
        return 1.0
    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))


def _compact_text(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    return _trunc(text, limit) if text else ""


def _extract_open_question(*parts: str) -> str:
    merged = " ".join(_compact_text(part, 220) for part in parts if part)
    if "?" not in merged:
        return ""
    question = merged.split("?", 1)[0].rsplit(". ", 1)[-1].strip()
    return _trunc(f"{question}?", 180) if question else ""


def _partner_id(char_id: str = "", pair_ids: set | None = None) -> str:
    cid = char_id or CHAR_ID
    pids = pair_ids or PAIR_IDS
    if cid in pids:
        others = [x for x in sorted(pids) if x != cid]
        if others:
            return others[0]
    if cid == "char_001":
        return "char_306"
    if cid == "char_306":
        return "char_001"
    return ""


def _conversation_thread_id(char_a: str, char_b: str) -> str:
    return f"thread_conv__{'__'.join(sorted([char_a, char_b]))}"


def _pair_slug(char_a: str, char_b: str) -> str:
    return "__".join(sorted([char_a, char_b]))


def _pair_state_key(partner_id: str = "", char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    pid = partner_id or _partner_id(cid)
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(cid, pid)}:state"


def _pair_journal_key(partner_id: str = "", char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    pid = partner_id or _partner_id(cid)
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(cid, pid)}:journal"


def _pair_state(r, partner_id: str = "", char_id: str = "") -> dict:
    key = _pair_state_key(partner_id, char_id)
    if not key:
        return {}
    try:
        return r.hgetall(key) or {}
    except Exception:
        return {}


def _pair_hset(r, partner_id: str, mapping: dict, char_id: str = "") -> None:
    key = _pair_state_key(partner_id, char_id)
    if not key or not mapping:
        return
    clean = {}
    deletes = []
    for k, v in mapping.items():
        if v is None:
            continue
        if v == "":
            deletes.append(k)
        else:
            clean[k] = str(v)
    if not clean and not deletes:
        return
    try:
        pipe = r.pipeline(transaction=False)
        if clean:
            pipe.hset(key, mapping=clean)
        if deletes:
            pipe.hdel(key, *deletes)
        pipe.expire(key, PAIR_STATE_TTL)
        pipe.execute()
    except Exception:
        pass


def _pair_append_journal(r, partner_id: str, entry: dict, char_id: str = "") -> None:
    key = _pair_journal_key(partner_id, char_id)
    if not key:
        return
    try:
        payload = dict(entry)
        payload["ts"] = int(payload.get("ts") or time.time())
        r.rpush(key, json.dumps(payload, default=str))
        r.ltrim(key, -PAIR_JOURNAL_CAP, -1)
        r.expire(key, PAIR_STATE_TTL)
    except Exception:
        pass


def _pair_recent_journal(r, partner_id: str = "", limit: int = 4, char_id: str = "") -> list[dict]:
    key = _pair_journal_key(partner_id, char_id)
    if not key:
        return []
    try:
        raw = r.lrange(key, -max(limit, 1), -1)
    except Exception:
        return []
    items = []
    for item in raw:
        try:
            items.append(json.loads(item))
        except Exception:
            pass
    return items


def _pair_thread_id(r, partner_id: str = "", char_id: str = "") -> str:
    state = _pair_state(r, partner_id, char_id)
    thread_id = state.get("active_thread_id", "")
    if thread_id:
        return thread_id
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    _pair_hset(r, partner_id, {"active_thread_id": thread_id}, char_id)
    return thread_id


def _store_thread_message(r, msg: dict, thread_id: str, char_id: str = "") -> None:
    cid = char_id or CHAR_ID
    if r is None or not thread_id:
        return
    payload = dict(msg)
    payload["thread_id"] = thread_id
    msg_key = f"msg:{payload['msg_id']}"
    raw = json.dumps(payload, default=str)
    ts = float(payload.get("ts") or time.time())
    try:
        pipe = r.pipeline(transaction=False)
        pipe.set(msg_key, raw, ex=PAIR_STATE_TTL)
        pipe.zadd(f"msg:thread:{thread_id}", {msg_key: ts})
        pipe.zremrangebyrank(f"msg:thread:{thread_id}", 0, -81)
        pipe.expire(f"msg:thread:{thread_id}", PAIR_STATE_TTL)
        pipe.zadd(f"msg:threads:{payload['from_char_id']}", {thread_id: ts})
        pipe.zadd(f"msg:threads:{payload['to_char_id']}", {thread_id: ts})
        pipe.zremrangebyrank(f"msg:threads:{payload['from_char_id']}", 0, -21)
        pipe.zremrangebyrank(f"msg:threads:{payload['to_char_id']}", 0, -21)
        pipe.expire(f"msg:threads:{payload['from_char_id']}", PAIR_STATE_TTL)
        pipe.expire(f"msg:threads:{payload['to_char_id']}", PAIR_STATE_TTL)
        pipe.execute()
    except Exception as e:
        logger.debug("[%s] thread store failed: %s", cid, e)


def _recent_thread_messages(r, thread_id: str, limit: int = 4) -> list[dict]:
    if not thread_id:
        return []
    try:
        keys = r.zrevrange(f"msg:thread:{thread_id}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    items = []
    for key in reversed(keys):
        try:
            raw = r.get(key)
            if raw:
                items.append(json.loads(raw))
        except Exception:
            pass
    return items


def _recent_decisions(r, limit: int = 10, char_id: str = "") -> list[dict]:
    cid = char_id or CHAR_ID
    try:
        raw = r.zrevrange(f"npc_decisions:{cid}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    items = []
    for item in raw:
        try:
            items.append(json.loads(item))
        except Exception:
            pass
    return items


def _partner_answered_open_question(r, partner_id: str, since_ts: int, char_id: str = "") -> bool:
    if r is None or not since_ts:
        return False
    state = _pair_state(r, partner_id, char_id)
    try:
        last_ts = int(state.get("last_message_ts", 0) or 0)
    except Exception:
        last_ts = 0
    if state.get("last_message_from") == partner_id and last_ts >= since_ts:
        return True
    active_thread_id = state.get("active_thread_id", "")
    if not active_thread_id:
        return False
    for msg in _recent_thread_messages(r, active_thread_id, 20):
        try:
            if msg.get("from_char_id") == partner_id and int(msg.get("ts", 0) or 0) >= since_ts:
                return True
        except Exception:
            continue
    return False


def _new_evidence_since(r, partner_id: str, since_ts: int) -> bool:
    if r is None or not since_ts:
        return False
    try:
        raw_artifacts = r.lrange(f"npc_artifacts:{partner_id}", -10, -1)
        for raw in raw_artifacts:
            try:
                obj = json.loads(raw)
                ts = int(obj.get("created_at") or obj.get("ts") or 0)
                if ts >= since_ts:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        raw_decisions = r.zrevrange(f"npc_decisions:{partner_id}", 0, 9)
        for raw in raw_decisions:
            try:
                d = json.loads(raw)
                ts = int(d.get("ts", 0) or 0)
                cat = d.get("category", "")
                if ts >= since_ts and cat in {"investigate", "create_artifact", "read_artifacts", "write_code", "self_improve"}:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _duplicate_open_question(r, partner_id: str, question: str, char_id: str = "") -> bool:
    if r is None or not question:
        return False
    state = _pair_state(r, partner_id, char_id)
    last_question = state.get("last_open_question_sent_to_partner", "")
    if not last_question:
        return False
    try:
        last_ts = int(state.get("last_open_question_ts", 0) or 0)
    except Exception:
        last_ts = 0
    if not last_ts:
        return False
    if _partner_answered_open_question(r, partner_id, last_ts, char_id):
        return False
    if _question_similarity(question, last_question) < 0.75:
        return False
    if int(time.time()) - last_ts >= OPEN_QUESTION_REPEAT_HOURS * 3600 and _new_evidence_since(r, partner_id, last_ts):
        return False
    return True


def _open_question_from_partner(r, partner_id: str, char_id: str = "") -> dict | None:
    if r is None or not partner_id:
        return None
    state = _pair_state(r, partner_id, char_id)
    if not _state_question_from_partner(state, partner_id):
        return None
    question = state.get("open_question", "")
    try:
        ts = int(state.get("open_question_ts", 0) or state.get("last_message_ts", 0) or 0)
    except Exception:
        ts = 0
    if not question or not ts:
        return None
    if state.get("partner_answer") or state.get("partner_answer_ts"):
        return None
    return {"question": question, "ts": ts}


def _state_question_from_partner(state: dict, partner_id: str) -> bool:
    owner = state.get("open_question_from", "")
    if owner:
        return owner == partner_id
    question = state.get("open_question", "")
    if not question or state.get("last_message_from") != partner_id:
        return False
    preview = state.get("last_message_preview", "")
    if not preview:
        return False
    return question[:40] in preview or _question_similarity(question, preview) >= 0.65


def _has_work_after_open_question(r, partner_id: str, since_ts: int, char_id: str = "") -> bool:
    if r is None or not since_ts:
        return False
    for d in _recent_decisions(r, 12, char_id):
        try:
            ts = int(d.get("ts", 0) or 0)
            cat = d.get("category", "")
            if ts >= since_ts and cat in {"investigate", "create_artifact", "read_artifacts", "write_code", "self_improve"}:
                return True
        except Exception:
            continue
    return False


def _message_cooldown_remaining(r, partner_id: str = "", char_id: str = "") -> int:
    state = _pair_state(r, partner_id, char_id)
    cid = char_id or CHAR_ID
    if state.get("last_message_from") != cid:
        return 0
    try:
        last_ts = int(state.get("last_message_ts", 0) or 0)
    except Exception:
        last_ts = 0
    if not last_ts:
        return 0
    remaining = PAIR_MESSAGE_COOLDOWN - (int(time.time()) - last_ts)
    return max(0, remaining)


def _sync_pair_workspace(r, decision: dict, result: dict, npc_name: str = "", char_id: str = "") -> None:
    cid = char_id or CHAR_ID
    name = npc_name or os.environ.get("NPC_NAME", cid)
    pid = _partner_id(cid)
    if cid not in PAIR_IDS or pid not in PAIR_IDS:
        return
    cat = decision.get("category", result.get("category", "rest"))
    desc = decision.get("description", result.get("description", ""))
    reasoning = decision.get("reasoning", result.get("reasoning", ""))
    body = result.get("message_body") or decision.get("body", "")
    action_taken = result.get("action_taken", "none")
    message_target = result.get("target") or decision.get("target", "")
    is_partner_message = cat == "send_message" and message_target == pid
    focus = _compact_text(body if cat == "send_message" else desc, 180) or _compact_text(reasoning, 180) or cat
    state = _pair_state(r, pid, cid)
    now = int(result.get("ts") or time.time())
    answering_partner_question = _state_question_from_partner(state, pid)
    mapping = {
        "last_sync_ts": str(now),
        "last_actor": cid,
        "last_actor_name": name,
        f"focus_{cid}": focus,
        f"category_{cid}": cat,
        f"action_{cid}": action_taken,
        f"updated_{cid}": str(now),
        "current_topic": focus,
    }
    if not state.get("shared_goal") and cat in {"investigate", "create_artifact", "write_code", "self_improve"}:
        mapping["shared_goal"] = focus
    open_question = _extract_open_question(body, desc, reasoning)
    if is_partner_message and answering_partner_question:
        mapping["partner_answer"] = _compact_text(body, 300)
        mapping["partner_answer_ts"] = str(now)
        mapping["partner_answer_from"] = cid
        mapping["partner_answer_to"] = pid
        mapping["open_question"] = ""
        mapping["open_question_from"] = ""
        mapping["open_question_ts"] = ""
        mapping["last_open_question_sent_to_partner"] = ""
        mapping["last_open_question_ts"] = ""
    elif is_partner_message and open_question:
        mapping["open_question"] = open_question
        mapping["open_question_from"] = cid
        mapping["open_question_ts"] = str(now)
        mapping["last_open_question_sent_to_partner"] = open_question
        mapping["last_open_question_ts"] = str(now)
        mapping["partner_answer"] = ""
        mapping["partner_answer_ts"] = ""
        mapping["partner_answer_from"] = ""
        mapping["partner_answer_to"] = ""
    if result.get("artifact_title") and answering_partner_question:
        mapping["partner_answer"] = f"Artifact created: {result['artifact_title']}"
        mapping["partner_answer_ts"] = str(now)
        mapping["partner_answer_from"] = cid
        mapping["partner_answer_to"] = pid
        mapping["open_question"] = ""
        mapping["open_question_from"] = ""
        mapping["open_question_ts"] = ""
        mapping["last_open_question_sent_to_partner"] = ""
        mapping["last_open_question_ts"] = ""
    if is_partner_message:
        mapping["last_message_ts"] = str(now)
        mapping["last_message_from"] = cid
        mapping["last_message_preview"] = _compact_text(body, 160)
        if result.get("thread_id"):
            mapping["active_thread_id"] = result["thread_id"]
    if result.get("artifact_title"):
        mapping["last_artifact_title"] = result["artifact_title"]
        mapping["last_artifact_from"] = cid
        mapping["last_artifact_ts"] = str(now)
    _pair_hset(r, pid, mapping, cid)
    if action_taken == "artifact_deferred_dedup":
        journal_summary = f"{name} paused \u2014 already working on something very similar"
    elif cat == "send_message" and body:
        journal_summary = _compact_text(body, 120)
    elif cat == "create_artifact":
        art_title = result.get("artifact_title", "")
        if art_title:
            journal_summary = f'{name} wrote: "{art_title[:80]}"'
        else:
            journal_summary = _compact_text(desc, 120)
    elif cat == "read_artifacts":
        journal_summary = f"{name} read partner's latest work: {_compact_text(result.get('summary', ''), 80)}"
    elif cat == "investigate":
        journal_summary = f"{name} is digging deeper: {_compact_text(desc, 100)}"
    elif cat == "self_improve":
        journal_summary = f"{name} steps back to reflect"
    else:
        journal_summary = _compact_text(desc or reasoning, 120) or f"{name} is {cat}"
    _pair_append_journal(
        r,
        pid,
        {
            "ts": now,
            "actor": cid,
            "actor_name": name,
            "category": cat,
            "action": action_taken,
            "summary": journal_summary,
            "thread_id": result.get("thread_id", ""),
        },
        cid,
    )


def _log_llm_call(r, call_label, model, system_prompt, user_prompt, response, success, error, latency_ms, char_id: str = ""):
    cid = char_id or CHAR_ID
    entry = {
        "ts": int(time.time()),
        "call_label": call_label,
        "model": model,
        "system_prompt": _trunc(system_prompt, 300),
        "user_prompt": _trunc(user_prompt, 300),
        "response": _trunc(response, 500),
        "success": success,
        "error": error or "",
        "latency_ms": latency_ms,
    }
    try:
        key = f"npc_llm_logs:{cid}"
        r.lpush(key, json.dumps(entry))
        r.ltrim(key, 0, 199)
        r.hincrby(f"npc_stats:{cid}", "llm_calls", 1)
        if success:
            r.hincrby(f"npc_stats:{cid}", "llm_success", 1)
        else:
            r.hincrby(f"npc_stats:{cid}", "llm_failures", 1)
        r.hset(f"npc_stats:{cid}", "last_model", model)
        r.hset(f"npc_stats:{cid}", "last_call_label", call_label)
        r.hset(f"npc_stats:{cid}", "last_ts", str(int(time.time())))
    except Exception:
        pass


def _session_append(r, entry: dict, char_id: str = "") -> None:
    cid = char_id or CHAR_ID
    if r is None or not entry:
        return
    try:
        entry = dict(entry)
        entry["ts"] = int(time.time())
        key = f"npc_session:{cid}"
        r.rpush(key, json.dumps(entry, default=str))
        r.ltrim(key, -SESSION_CAP, -1)
    except Exception as e:
        logger.debug("[%s] session append failed: %s", cid, e)


def _acknowledge_inbox(r, partner_id: str = None, char_id: str = "") -> int:
    cid = char_id or CHAR_ID
    try:
        if not partner_id:
            partner_id = _partner_id(cid)
        inbox_key = f"npc_messages:{cid}:inbox"
        all_msgs = r.lrange(inbox_key, 0, -1)
        ack_count = 0
        for msg in all_msgs:
            try:
                m = json.loads(msg)
                if m.get("from_char_id") == partner_id:
                    r.lrem(inbox_key, 1, msg)
                    ack_count += 1
            except Exception:
                pass
        return ack_count
    except Exception:
        return 0


def _recent_artifact_dedup_count(r, char_id: str = "") -> int:
    cid = char_id or CHAR_ID
    try:
        val = r.get(f"npc_dedup_streak:{cid}")
        return int(val) if val is not None else 0
    except Exception:
        return 0


def _dedup_blocked_topic(r, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    try:
        key = f"npc_dedup_topic:{cid}"
        if not r.exists(key):
            return ""
        raw = r.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return (raw or "").strip()
    except Exception:
        return ""


def _recent_decision_shapes(r, n: int = 5, char_id: str = "") -> list[str]:
    out: list[str] = []
    try:
        recent = _recent_decisions(r, n, char_id)
    except Exception:
        return out
    for d in recent:
        try:
            out.append(str(d.get("category", "?")))
        except Exception:
            break
    return out


def _newest_first_streak(shapes: list[str]) -> int:
    if not shapes:
        return 0
    streak = 1
    target = shapes[0]
    for s in shapes[1:]:
        if s == target:
            streak += 1
        else:
            break
    return streak


def _session_transcript(r, contacts: dict | None = None, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    try:
        raw = r.lrange(f"npc_session:{cid}", 0, SESSION_CAP - 1)
    except Exception:
        return ""
    if not raw:
        return ""

    c = contacts or {}
    lines = []
    for entry_json in reversed(raw):
        try:
            e = json.loads(entry_json)
        except Exception:
            continue
        ts = int(e.get("ts", 0) or 0)
        clock = time.strftime("%H:%M:%S", time.gmtime(ts)) if ts else "??:??:??"
        actor = e.get("actor", "?")
        kind = e.get("kind", "?")
        body = e.get("body", "")
        if kind == "think":
            lines.append(f"  [{clock}] {actor} thought: {body[:80]}")
        elif kind == "decide":
            cat = e.get("category", "?")
            lines.append(f"  [{clock}] {actor} decided {cat}: {body[:80]}")
        elif kind == "message_sent":
            to = e.get("to_name", e.get("to", "?"))
            lines.append(f"  [{clock}] {actor} \u2192 {to}: {body[:120]}")
        elif kind == "message_received":
            src = e.get("from_name", e.get("from", "?"))
            lines.append(f"  [{clock}] {actor} \u2190 {src}: {body[:120]}")
        elif kind == "artifact_created":
            title = e.get("title", "?")
            lines.append(f"  [{clock}] {actor} published artifact: {title[:80]}")
        elif kind == "code_written":
            title = e.get("title", "?")
            lines.append(f"  [{clock}] {actor} wrote code: {title[:80]}")
        elif kind == "artifact_read":
            title = e.get("title", "?")
            src = e.get("from_name", e.get("from", "?"))
            lines.append(f"  [{clock}] {actor} read from {src}: {title[:80]}")
        elif kind == "artifact_published_by_partner":
            title = e.get("title", "?")
            src = c.get(e.get("from", ""), e.get("from", "partner"))
            lines.append(f"  [{clock}] {src} published artifact: {title[:80]}")
        elif kind == "workspace_sync":
            lines.append(f"  [{clock}] {actor} synced pair workspace: {body[:100]}")
        elif kind == "investigation":
            lines.append(f"  [{clock}] {actor} investigated: {body[:100]}")
        elif kind == "reflection":
            lines.append(f"  [{clock}] {actor} reflected: {body[:100]}")
        elif kind == "self_improve":
            lines.append(f"  [{clock}] {actor} improved itself: {body[:100]}")
        else:
            lines.append(f"  [{clock}] {actor} {kind}: {body[:80]}")

    text = "\n".join(lines)
    if len(text) > SESSION_TRANSCRIPT_CHARS:
        text = "\u2026\n" + text[-SESSION_TRANSCRIPT_CHARS:]
    return text
