from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

import redis
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="", tags=["agents"])
logger = logging.getLogger(__name__)

PAIR_IDS = ("char_001", "char_306")
OPERATOR_ID = "moderator"
OPERATOR_NAME = "Sean / Federation Moderator"
MESSAGE_TTL_SECONDS = 86400 * 30
MESSAGE_CAP = 100
THREAD_CAP = 100
THREAD_INDEX_CAP = 40
_IDEMPOTENCY_TTL = 60

_SINGLE_MESSAGE_LUA = """
local result_key = KEYS[1]
local guard_key = KEYS[2]
local ttl = tonumber(ARGV[1])
local payload_json = ARGV[2]
local msg_key = ARGV[3]
local now = ARGV[4]
local msg_ttl = tonumber(ARGV[5])
local thread_cap = tonumber(ARGV[6])
local thread_idx_cap = tonumber(ARGV[7])
local is_pair = ARGV[8]
local pair_key = ARGV[9]

local cached = redis.call('GET', result_key)
if cached then
    return cached
end

local set = redis.call('SET', guard_key, '1', 'NX', 'EX', ttl)
if not set then
    local missing = redis.call('GET', result_key)
    if not missing then
        return cjson.encode({ok = false, error = "incomplete"})
    end
    return missing
end

local payload = cjson.decode(payload_json)
local from_id = payload.from_char_id
local to_id = payload.to_char_id
local thread_id = payload.thread_id

redis.call('RPUSH', 'npc_messages:' .. to_id .. ':inbox', payload_json)
redis.call('LTRIM', 'npc_messages:' .. to_id .. ':inbox', -100, -1)
redis.call('RPUSH', 'npc_messages:' .. from_id .. ':sent', payload_json)
redis.call('LTRIM', 'npc_messages:' .. from_id .. ':sent', -100, -1)
redis.call('SET', msg_key, payload_json, 'EX', msg_ttl)
redis.call('ZADD', 'msg:thread:' .. thread_id, now, msg_key)
redis.call('ZREMRANGEBYRANK', 'msg:thread:' .. thread_id, 0, -thread_cap - 1)
redis.call('EXPIRE', 'msg:thread:' .. thread_id, msg_ttl)
redis.call('ZADD', 'msg:threads:' .. from_id, now, thread_id)
redis.call('ZADD', 'msg:threads:' .. to_id, now, thread_id)
redis.call('ZREMRANGEBYRANK', 'msg:threads:' .. from_id, 0, -thread_idx_cap - 1)
redis.call('ZREMRANGEBYRANK', 'msg:threads:' .. to_id, 0, -thread_idx_cap - 1)
redis.call('EXPIRE', 'msg:threads:' .. from_id, msg_ttl)
redis.call('EXPIRE', 'msg:threads:' .. to_id, msg_ttl)

if is_pair == '1' and pair_key ~= '' then
    local preview = string.sub(payload.body or '', 1, 160)
    redis.call('HSET', pair_key,
        'active_thread_id', thread_id,
        'last_message_ts', now,
        'last_message_from', from_id,
        'last_message_preview', preview
    )
    redis.call('EXPIRE', pair_key, msg_ttl)
end

local result = cjson.encode({ok = true, message = payload})
redis.call('SETEX', result_key, ttl, result)
return result
"""

_BROADCAST_LUA = """
local result_key = KEYS[1]
local guard_key = KEYS[2]
local ttl = tonumber(ARGV[1])
local msg_ttl = tonumber(ARGV[2])
local thread_cap = tonumber(ARGV[3])
local thread_idx_cap = tonumber(ARGV[4])
local sender_from_id = ARGV[5]
local pause_topic = ARGV[6]
local duration_minutes = tonumber(ARGV[7])
local has_pause = ARGV[8]

local cached = redis.call('GET', result_key)
if cached then
    return cached
end

local set = redis.call('SET', guard_key, '1', 'NX', 'EX', ttl)
if not set then
    local missing = redis.call('GET', result_key)
    if not missing then
        return cjson.encode({ok = false, error = "incomplete"})
    end
    return missing
end

local sent = {}
local i = 9
while i <= #ARGV do
    local recv = cjson.decode(ARGV[i])
    local to_id = recv.to_char_id
    local from_id = recv.from_char_id

    redis.call('RPUSH', 'npc_messages:' .. to_id .. ':inbox', ARGV[i])
    redis.call('LTRIM', 'npc_messages:' .. to_id .. ':inbox', -100, -1)
    redis.call('RPUSH', 'npc_messages:' .. from_id .. ':sent', ARGV[i])
    redis.call('LTRIM', 'npc_messages:' .. from_id .. ':sent', -100, -1)
    redis.call('SET', recv.id, ARGV[i], 'EX', msg_ttl)
    redis.call('ZADD', 'msg:thread:' .. recv.thread_id, recv.created_at, recv.id)
    redis.call('ZREMRANGEBYRANK', 'msg:thread:' .. recv.thread_id, 0, -thread_cap - 1)
    redis.call('EXPIRE', 'msg:thread:' .. recv.thread_id, msg_ttl)
    redis.call('ZADD', 'msg:threads:' .. from_id, recv.created_at, recv.thread_id)
    redis.call('ZADD', 'msg:threads:' .. to_id, recv.created_at, recv.thread_id)
    redis.call('ZREMRANGEBYRANK', 'msg:threads:' .. from_id, 0, -thread_idx_cap - 1)
    redis.call('ZREMRANGEBYRANK', 'msg:threads:' .. to_id, 0, -thread_idx_cap - 1)
    redis.call('EXPIRE', 'msg:threads:' .. from_id, msg_ttl)
    redis.call('EXPIRE', 'msg:threads:' .. to_id, msg_ttl)

    table.insert(sent, recv)
    i = i + 1
end

local cooldowns = {}
if has_pause == '1' and pause_topic ~= '' then
    local ttl_secs = duration_minutes * 60
    local j = 9
    while j <= #ARGV do
        local recv = cjson.decode(ARGV[j])
        local agent_id = recv.to_char_id
        local key = 'npc_topic_cooldown:' .. agent_id .. ':' .. pause_topic
        local reason_key = 'npc_topic_cooldown_reason:' .. agent_id .. ':' .. pause_topic
        redis.call('SETEX', key, ttl_secs, 'manual_pause')
        redis.call('SETEX', reason_key, ttl_secs, sender_from_id)
        table.insert(cooldowns, {
            agent_id = agent_id,
            topic = pause_topic,
            remaining_seconds = ttl_secs
        })
        j = j + 1
    end
end

local result = cjson.encode({ok = true, sent = sent, cooldowns = cooldowns})
redis.call('SETEX', result_key, ttl, result)
return result
"""

_DEFAULT_AGENT_LABELS = {
    "char_001": "Archimedes Prime",
    "char_306": "The Oracle",
    OPERATOR_ID: OPERATOR_NAME,
}

_TOPIC_STOP_WORDS = {
    "the", "of", "and", "a", "an", "to", "in", "for", "on", "with", "from", "by", "at", "is", "it",
    "as", "be", "or", "that", "this", "its", "are", "was", "but", "not", "all", "report", "analysis",
    "assessment", "strategic", "recommendation", "overview", "implication", "response", "data", "summary",
    "integration", "system", "notice", "request", "question", "agent", "persistent", "engineering",
}

DEFAULT_SELF_DIAGNOSTIC_PROMPT = (
    "You are a persistent NPC agent in a simulation. "
    "Review your recent outputs, partner messages, inbox, and artifacts. "
    "Are you looping? What information, tools, UI, memory, or protocol changes would make your work better? "
    "Return concrete engineering requests only. "
    "Reply directly to moderator with your requests, blockers, and the next most useful change."
)


class AgentMessageRequest(BaseModel):
    from_id: str = OPERATOR_ID
    from_name: Optional[str] = None
    type: str = Field(default="user_question")
    topic: str = ""
    subject: str = ""
    body: str = Field(..., min_length=1)
    thread_id: Optional[str] = None


class AgentBroadcastRequest(BaseModel):
    agent_ids: List[str] = Field(default_factory=lambda: list(PAIR_IDS))
    from_id: str = OPERATOR_ID
    from_name: Optional[str] = None
    type: str = Field(default="user_question")
    topic: str = ""
    subject: str = ""
    body: str = ""
    thread_id: Optional[str] = None
    pause_topic: str = ""
    duration_minutes: int = Field(default=60, ge=1, le=1440)


class SelfDiagnosticRequest(BaseModel):
    from_id: str = OPERATOR_ID
    from_name: Optional[str] = None
    topic: str = "self_diagnostic"
    body: str = ""


def _get_redis(request: Optional[Request] = None):
    try:
        if request is not None and getattr(request.app.state, "redis", None) is not None:
            return request.app.state.redis
    except Exception:
        pass
    return redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def _agent_labels(r) -> Dict[str, str]:
    labels = dict(_DEFAULT_AGENT_LABELS)
    try:
        raw = r.hgetall("npc_agent:contacts") or {}
        if raw:
            labels.update(raw)
    except Exception:
        pass
    labels.setdefault(OPERATOR_ID, OPERATOR_NAME)
    return labels


def _build_message_payload(from_id, from_name, to_id, to_name, body, message_type, topic, subject, thread_id):
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    thread_id = thread_id or _conversation_thread_id(from_id, to_id)
    return {
        "id": msg_id,
        "msg_id": msg_id,
        "thread_id": thread_id,
        "from_char_id": from_id,
        "from_name": from_name,
        "from_char_name": from_name,
        "to_char_id": to_id,
        "to_name": to_name,
        "to_char_name": to_name,
        "subject": subject or _subject_for(message_type, topic, body),
        "body": body,
        "type": message_type or "direct_message",
        "topic": _normalize_topic_label(topic or body),
        "created_at": now,
        "ts": now,
        "read": "false",
    }


def _run_idempotent_single_message(r, idempotency_key, agent_id, payload, msg_key, now, from_id, to_id):
    result_key = f"msg:idempotency:result:message:{agent_id}:{idempotency_key}"
    guard_key = f"msg:idempotency:guard:message:{agent_id}:{idempotency_key}"
    is_pair = "1" if {from_id, to_id} == set(PAIR_IDS) else "0"
    pair_key = _pair_state_key(from_id, to_id) if is_pair == "1" else ""
    try:
        result = r.eval(
            _SINGLE_MESSAGE_LUA,
            2,
            result_key,
            guard_key,
            _IDEMPOTENCY_TTL,
            json.dumps(payload, default=str),
            msg_key,
            str(now),
            str(MESSAGE_TTL_SECONDS),
            str(THREAD_CAP),
            str(THREAD_INDEX_CAP),
            is_pair,
            pair_key,
        )
    except Exception as exc:
        logger.error("idempotent message failed: %s", exc)
        raise HTTPException(status_code=503, detail="idempotent message failed") from exc
    if isinstance(result, bytes):
        result = result.decode("utf-8")
    if result is None:
        raise HTTPException(status_code=503, detail="idempotent result missing")
    return json.loads(result)


def _run_idempotent_broadcast(r, idempotency_key, from_id, req, labels):
    result_key = f"msg:idempotency:result:broadcast:{idempotency_key}"
    guard_key = f"msg:idempotency:guard:broadcast:{idempotency_key}"
    recipient_payloads = []
    for agent_id in req.agent_ids:
        if req.body:
            thread_id = req.thread_id or _conversation_thread_id(from_id, agent_id)
            payload = _build_message_payload(
                from_id,
                labels.get(from_id, from_id),
                agent_id,
                labels.get(agent_id, agent_id),
                req.body,
                req.type,
                req.topic,
                req.subject,
                thread_id,
            )
            recipient_payloads.append(json.dumps(payload, default=str))
    args = [
        _IDEMPOTENCY_TTL,
        str(MESSAGE_TTL_SECONDS),
        str(THREAD_CAP),
        str(THREAD_INDEX_CAP),
        from_id,
        req.pause_topic or "",
        str(req.duration_minutes),
        "1" if req.pause_topic else "0",
    ]
    args.extend(recipient_payloads)
    try:
        result = r.eval(_BROADCAST_LUA, 2, result_key, guard_key, *args)
    except Exception as exc:
        logger.error("idempotent broadcast failed: %s", exc)
        raise HTTPException(status_code=503, detail="idempotent broadcast failed") from exc
    if isinstance(result, bytes):
        result = result.decode("utf-8")
    if result is None:
        raise HTTPException(status_code=503, detail="idempotent broadcast result missing")
    return json.loads(result)


def _pair_partner(agent_id: str) -> str:
    if agent_id == "char_001":
        return "char_306"
    if agent_id == "char_306":
        return "char_001"
    return ""


def _pair_state_key(char_a: str, char_b: str) -> str:
    return f"npc_pair:{'__'.join(sorted([char_a, char_b]))}:state"


def _pair_journal_key(char_a: str, char_b: str) -> str:
    return f"npc_pair:{'__'.join(sorted([char_a, char_b]))}:journal"


def _conversation_thread_id(char_a: str, char_b: str) -> str:
    return f"thread_conv__{'__'.join(sorted([char_a, char_b]))}"


def _topic_tokens(text: str) -> List[str]:
    return [
        token for token in re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
        if token not in _TOPIC_STOP_WORDS
    ]


def _normalize_topic_label(text: str) -> str:
    tokens = _topic_tokens(text)
    if not tokens:
        return ""
    return Counter(tokens).most_common(1)[0][0]


def _subject_for(message_type: str, topic: str, body: str) -> str:
    label = (message_type or "message").replace("_", " ").strip().title() or "Message"
    normalized_topic = _normalize_topic_label(topic or body)
    if normalized_topic:
        return f"{label}: {normalized_topic}"
    preview = " ".join((body or "").split())[:40].strip()
    return f"{label}: {preview}" if preview else label


def _json_list(r, key: str, limit: int) -> List[Dict[str, Any]]:
    try:
        raw_items = r.lrange(key, -max(limit, 1), -1)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for item in raw_items:
        try:
            out.append(json.loads(item))
        except Exception:
            out.append({"raw": str(item)})
    return out


def _thread_messages(r, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not thread_id:
        return []
    try:
        msg_keys = r.zrevrange(f"msg:thread:{thread_id}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for msg_key in reversed(msg_keys):
        try:
            raw = r.get(msg_key)
            if raw:
                rows.append(json.loads(raw))
        except Exception:
            continue
    return rows


def _recent_threads(r, agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        thread_ids = r.zrevrange(f"msg:threads:{agent_id}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    threads: List[Dict[str, Any]] = []
    for thread_id in thread_ids:
        messages = _thread_messages(r, thread_id, 1)
        if not messages:
            continue
        latest = dict(messages[-1])
        latest["thread_id"] = thread_id
        threads.append(latest)
    return threads


def _pair_room_snapshot(r, agent_id: str) -> Dict[str, Any]:
    partner_id = _pair_partner(agent_id)
    if not partner_id:
        return {}
    key = _pair_state_key(agent_id, partner_id)
    journal_key = _pair_journal_key(agent_id, partner_id)
    try:
        pair_state = r.hgetall(key) or {}
    except Exception:
        pair_state = {}
    try:
        raw_journal = r.lrange(journal_key, -8, -1)
    except Exception:
        raw_journal = []
    journal = []
    for item in raw_journal:
        try:
            journal.append(json.loads(item))
        except Exception:
            continue
    active_thread_id = pair_state.get("active_thread_id", "")
    return {
        "pair_ids": [agent_id, partner_id],
        "shared_goal": pair_state.get("shared_goal", ""),
        "current_topic": pair_state.get("current_topic", ""),
        "open_question": pair_state.get("open_question", ""),
        "last_message_preview": pair_state.get("last_message_preview", ""),
        "last_message_from": pair_state.get("last_message_from", ""),
        "last_message_ts": int(pair_state.get("last_message_ts", 0) or 0),
        "partner_answer": pair_state.get("partner_answer", ""),
        "partner_answer_from": pair_state.get("partner_answer_from", ""),
        "partner_answer_to": pair_state.get("partner_answer_to", ""),
        "partner_answer_ts": int(pair_state.get("partner_answer_ts", 0) or 0),
        "active_thread_id": active_thread_id,
        "focus_by_char": {cid: pair_state.get(f"focus_{cid}", "") for cid in PAIR_IDS},
        "action_by_char": {cid: pair_state.get(f"action_{cid}", "") for cid in PAIR_IDS},
        "category_by_char": {cid: pair_state.get(f"category_{cid}", "") for cid in PAIR_IDS},
        "journal": journal,
        "active_thread": _thread_messages(r, active_thread_id, 20),
    }


def _cooldowns_for_agent(r, agent_id: str) -> List[Dict[str, Any]]:
    prefix = f"npc_topic_cooldown:{agent_id}:"
    try:
        keys = r.keys(f"{prefix}*")
    except Exception:
        return []
    rows = []
    for key in keys:
        key_text = key.decode() if isinstance(key, bytes) else str(key)
        topic = key_text[len(prefix):]
        try:
            remaining = int(r.ttl(key_text) or 0)
        except Exception:
            remaining = 0
        if remaining <= 0:
            continue
        rows.append({
            "topic": topic,
            "remaining_seconds": remaining,
            "remaining_minutes": (remaining + 59) // 60,
        })
    rows.sort(key=lambda row: row["remaining_seconds"], reverse=True)
    return rows


def _manual_pause_topic(r, agent_id: str, topic: str, duration_minutes: int) -> Dict[str, Any]:
    normalized = _normalize_topic_label(topic)
    if not normalized:
        raise HTTPException(status_code=400, detail="pause_topic must contain at least one meaningful word")
    ttl_seconds = duration_minutes * 60
    key = f"npc_topic_cooldown:{agent_id}:{normalized}"
    reason_key = f"npc_topic_cooldown_reason:{agent_id}:{normalized}"
    try:
        r.setex(key, ttl_seconds, "manual_pause")
        r.setex(reason_key, ttl_seconds, OPERATOR_ID)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"failed to set cooldown: {exc}") from exc
    logger.info("[%s] topic_cooldown_started topic=%s duration_minutes=%d source=moderator", agent_id, normalized, duration_minutes)
    return {
        "agent_id": agent_id,
        "topic": normalized,
        "duration_minutes": duration_minutes,
        "remaining_seconds": ttl_seconds,
    }


def _queue_message(
    r,
    *,
    from_id: str,
    from_name: str,
    to_id: str,
    to_name: str,
    body: str,
    message_type: str,
    topic: str = "",
    subject: str = "",
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    thread_id = thread_id or _conversation_thread_id(from_id, to_id)
    payload: Dict[str, Any] = {
        "id": msg_id,
        "msg_id": msg_id,
        "thread_id": thread_id,
        "from_char_id": from_id,
        "from_name": from_name,
        "from_char_name": from_name,
        "to_char_id": to_id,
        "to_name": to_name,
        "to_char_name": to_name,
        "subject": subject or _subject_for(message_type, topic, body),
        "body": body,
        "type": message_type or "direct_message",
        "topic": _normalize_topic_label(topic or body),
        "created_at": now,
        "ts": now,
        "read": "false",
    }
    raw = json.dumps(payload, default=str)
    msg_key = f"msg:{msg_id}"
    try:
        pipe = r.pipeline(transaction=False)
        pipe.rpush(f"npc_messages:{to_id}:inbox", raw)
        pipe.ltrim(f"npc_messages:{to_id}:inbox", -MESSAGE_CAP, -1)
        pipe.rpush(f"npc_messages:{from_id}:sent", raw)
        pipe.ltrim(f"npc_messages:{from_id}:sent", -MESSAGE_CAP, -1)
        pipe.set(msg_key, raw, ex=MESSAGE_TTL_SECONDS)
        pipe.zadd(f"msg:thread:{thread_id}", {msg_key: float(now)})
        pipe.zremrangebyrank(f"msg:thread:{thread_id}", 0, -(THREAD_CAP + 1))
        pipe.expire(f"msg:thread:{thread_id}", MESSAGE_TTL_SECONDS)
        pipe.zadd(f"msg:threads:{from_id}", {thread_id: float(now)})
        pipe.zadd(f"msg:threads:{to_id}", {thread_id: float(now)})
        pipe.zremrangebyrank(f"msg:threads:{from_id}", 0, -(THREAD_INDEX_CAP + 1))
        pipe.zremrangebyrank(f"msg:threads:{to_id}", 0, -(THREAD_INDEX_CAP + 1))
        pipe.expire(f"msg:threads:{from_id}", MESSAGE_TTL_SECONDS)
        pipe.expire(f"msg:threads:{to_id}", MESSAGE_TTL_SECONDS)
        if {from_id, to_id} == set(PAIR_IDS):
            pair_key = _pair_state_key(from_id, to_id)
            pipe.hset(pair_key, mapping={
                "active_thread_id": thread_id,
                "last_message_ts": str(now),
                "last_message_from": from_id,
                "last_message_preview": " ".join(body.split())[:160],
            })
            pipe.expire(pair_key, MESSAGE_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"failed to queue message: {exc}") from exc
    return payload


@router.get("/agents/{agent_id}/messages")
def get_agent_messages(
    agent_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    thread_limit: int = Query(30, ge=1, le=100),
):
    r = _get_redis(request)
    labels = _agent_labels(r)
    inbox = _json_list(r, f"npc_messages:{agent_id}:inbox", limit)
    sent_messages = _json_list(r, f"npc_messages:{agent_id}:sent", limit)
    active_threads = _recent_threads(r, agent_id, limit=10)
    pair_room = _pair_room_snapshot(r, agent_id)
    active_thread_id = pair_room.get("active_thread_id", "") or (active_threads[0].get("thread_id", "") if active_threads else "")
    active_thread = _thread_messages(r, active_thread_id, thread_limit)
    return {
        "agent_id": agent_id,
        "name": labels.get(agent_id, agent_id),
        "inbox": inbox,
        "sent_messages": sent_messages,
        "active_threads": active_threads,
        "active_thread_id": active_thread_id,
        "active_thread": active_thread,
        "cooldowns": _cooldowns_for_agent(r, agent_id),
        "pair_room": pair_room,
        "updated_at": int(time.time()),
    }


@router.post("/agents/{agent_id}/messages")
def post_agent_message(agent_id: str, req: AgentMessageRequest, request: Request):
    r = _get_redis(request)
    idempotency_key = request.headers.get("X-Idempotency-Key")
    labels = _agent_labels(r)
    from_id = req.from_id or OPERATOR_ID
    from_name = req.from_name or labels.get(from_id, from_id)
    thread_id = req.thread_id or _conversation_thread_id(from_id, agent_id)
    payload = _build_message_payload(from_id, from_name, agent_id, labels.get(agent_id, agent_id), req.body, req.type, req.topic, req.subject, thread_id)
    raw = json.dumps(payload, default=str)
    msg_key = f"msg:{payload['id']}"
    now = payload["created_at"]
    if idempotency_key:
        return _run_idempotent_single_message(r, idempotency_key, agent_id, payload, msg_key, now, from_id, agent_id)
    queued = _queue_message(r, from_id=from_id, from_name=from_name, to_id=agent_id, to_name=labels.get(agent_id, agent_id), body=req.body, message_type=req.type, topic=req.topic, subject=req.subject, thread_id=thread_id)
    return {"ok": True, "message": queued}


@router.post("/agents/broadcast")
def broadcast_agent_message(req: AgentBroadcastRequest, request: Request):
    if not req.body and not req.pause_topic:
        raise HTTPException(status_code=400, detail="broadcast requires body or pause_topic")
    r = _get_redis(request)
    idempotency_key = request.headers.get("X-Idempotency-Key")
    labels = _agent_labels(r)
    from_id = req.from_id or OPERATOR_ID
    from_name = req.from_name or labels.get(from_id, from_id)
    if idempotency_key:
        return _run_idempotent_broadcast(r, idempotency_key, from_id, req, labels)
    sent = []
    for agent_id in req.agent_ids:
        if req.body:
            sent.append(_queue_message(
                r,
                from_id=from_id,
                from_name=from_name,
                to_id=agent_id,
                to_name=labels.get(agent_id, agent_id),
                body=req.body,
                message_type=req.type,
                topic=req.topic,
                subject=req.subject,
                thread_id=req.thread_id,
            ))
    cooldowns = []
    if req.pause_topic:
        for agent_id in req.agent_ids:
            cooldowns.append(_manual_pause_topic(r, agent_id, req.pause_topic, req.duration_minutes))
    return {"ok": True, "sent": sent, "cooldowns": cooldowns}


@router.post("/agents/{agent_id}/self-diagnostic")
def request_self_diagnostic(agent_id: str, req: SelfDiagnosticRequest, request: Request):
    r = _get_redis(request)
    idempotency_key = request.headers.get("X-Idempotency-Key")
    labels = _agent_labels(r)
    from_id = req.from_id or OPERATOR_ID
    from_name = req.from_name or labels.get(from_id, from_id)
    prompt = DEFAULT_SELF_DIAGNOSTIC_PROMPT
    if req.body.strip():
        prompt = f"{prompt}\n\nAdditional moderator context: {req.body.strip()}"
    thread_id = _conversation_thread_id(from_id, agent_id)
    payload = _build_message_payload(from_id, from_name, agent_id, labels.get(agent_id, agent_id), prompt, "self_diagnostic", req.topic or "self_diagnostic", "Self diagnostic request", thread_id)
    raw = json.dumps(payload, default=str)
    msg_key = f"msg:{payload['id']}"
    now = payload["created_at"]
    if idempotency_key:
        return _run_idempotent_single_message(r, idempotency_key, agent_id, payload, msg_key, now, from_id, agent_id)
    queued = _queue_message(r, from_id=from_id, from_name=from_name, to_id=agent_id, to_name=labels.get(agent_id, agent_id), body=prompt, message_type="self_diagnostic", topic=req.topic or "self_diagnostic", subject="Self diagnostic request", thread_id=thread_id)
    return {"ok": True, "message": queued}
