import json
import logging
import os
import random
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


KNOWN_BLOCKED_TERMS = [
    "structured resonance lattice",
    "corruption-linked resonance",
    "anchor network",
    "resonance",
    "lattice",
]


def _is_no_substantive_disagreement(text: str) -> bool:
    t = (text or "").lower()
    return (
        "no substantive disagreement" in t
        or "no substantive" in t
        or "no disagreement" in t
        or "no substantive divergence" in t
    )


def _matched_loop_topic(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return ""
    for term in KNOWN_BLOCKED_TERMS:
        if term in t:
            if term in {"structured resonance lattice", "corruption-linked resonance", "resonance", "lattice"}:
                return "resonance"
            return term
    return ""


def _is_pseudo_framing_disagreement(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    hard_conflict_terms = (
        "contradict",
        "conflict",
        "incompatible",
        "rejects",
        "opposes",
        "cannot both",
        "mutually exclusive",
    )
    if any(term in t for term in hard_conflict_terms):
        return False
    pseudo_framing_terms = (
        "emphasizes",
        "stresses",
        "proposes",
        "focuses",
        "differing only in emphasis",
        "report",
        "investigation",
        "metrics",
        "policy",
        "governance",
    )
    return any(term in t for term in pseudo_framing_terms)


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


def _derive_question_from_goal(goal: str) -> str:
    """Derive a short open_question from a shared_goal statement."""
    goal = goal.strip()
    if not goal:
        return ""
    normalized = goal.lower()
    for prefix in (
        "a report on ",
        "an analysis of ",
        "a study of ",
        "an investigation of ",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    for sep in (" and ", " or ", ", "):
        if sep in normalized:
            normalized = normalized.split(sep)[0].strip()
            break
    core = _trunc(normalized, 120).rstrip(".,;")
    if core.lower().startswith(("what ", "why ", "how ", "where ", "when ", "who ")):
        return _trunc(core.rstrip(".") + "?", 180)
    return _trunc("What about " + core + "?", 180)


def _default_open_question() -> str:
    return "What happens next in the Federation?"


def _default_post_resolution_question() -> str:
    """Question used after a convergence-topic is resolved, to break the loop
    of re-entering the same blocked topic family."""
    pivots = [
        "What evidence from outside the current domain supports or contradicts this resolution?",
        "What witness layer beyond known space has not yet been sampled?",
        "Which adjacent NPC's testimony has not been heard on this matter?",
        "What new sensor modality could test the assumptions behind this resolution?",
    ]
    return random.choice(pivots)


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
    if not keys:
        return []
    try:
        values = r.mget(keys)
    except Exception:
        return []
    items = []
    for raw in reversed(values):
        try:
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
    # Ensure open_question is always non-blank so the councilors always have
    # an active inquiry to orbit around. Skip if state already has a real
    # open_question, or if this action intentionally cleared it.
    if not state.get("open_question") and mapping.get("open_question") != "":
        # Stage 4D: after resolution, do not regenerate open_question from
        # the same resolved shared_goal — that re-anchors to the blocked topic.
        _post_resolution_default = False
        if state.get("convergence_state"):
            try:
                _cr = state["convergence_state"]
                _cc = json.loads(_cr) if isinstance(_cr, str) else {}
            except Exception:
                _cc = {}
            if _cc and _cc.get("resolved", False) and _cc.get("resolved_shared_goal") and \
               state.get("shared_goal", "") == _cc["resolved_shared_goal"]:
                _post_resolution_default = True
        if _post_resolution_default:
            mapping["resolved_artifact"] = _compact_text(
                result.get("artifact_title", ""), 120) if result.get("artifact_title") else ""
            mapping["resolved_action"] = action_taken
            mapping["resolved_at_sync"] = str(now)
            _next_q = _cc.get("next_question", "")
            _blocked_raw = _cc.get("blocked_topic_terms", [])
            if isinstance(_blocked_raw, str) and _blocked_raw.strip():
                try:
                    _blocked = json.loads(_blocked_raw)
                except (json.JSONDecodeError, ValueError):
                    _blocked = [_blocked_raw] if _blocked_raw.strip() else []
            elif isinstance(_blocked_raw, (list, tuple, set)):
                _blocked = [t for t in _blocked_raw if isinstance(t, str) and t.strip()]
            else:
                _blocked = []
            if _next_q and (not _blocked or not any(
                    t and t.lower() in _next_q.lower() for t in _blocked)):
                mapping["open_question"] = _next_q
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_pivot"
            else:
                mapping["open_question"] = _default_post_resolution_question()
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_default"
        elif state.get("shared_goal"):
            derived = _derive_question_from_goal(state["shared_goal"])
            if derived:
                mapping["open_question"] = derived
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "derived_from_shared_goal"
        if not mapping.get("open_question"):
            mapping["open_question"] = _default_open_question()
            mapping["open_question_from"] = "system"
            mapping["open_question_ts"] = str(now)
            mapping["open_question_source"] = "system_default"
    _pair_hset(r, pid, mapping, cid)
    # Lightweight artifact-to-question linkage: if open_question exists and this
    # action isn't a no-op/skip, record which question the action is addressing.
    effective_open_question = state.get("open_question") or mapping.get("open_question", "")
    effective_open_question_source = state.get("open_question_source") or mapping.get("open_question_source", "")
    if effective_open_question and action_taken not in (
        "none", "no_target", "message_skipped_empty",
        "institution_cap_reached", "institution_total_cap_reached",
        "institution_similar_exists", "institution_already_exists",
        "institution_error",
    ):
        result["open_question_ref"] = effective_open_question
        result["open_question_source"] = effective_open_question_source
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
    journal_entry = {
        "ts": now,
        "actor": cid,
        "actor_name": name,
        "category": cat,
        "action": action_taken,
        "summary": journal_summary,
        "thread_id": result.get("thread_id", ""),
    }
    if result.get("open_question_ref"):
        journal_entry["open_question_ref"] = result["open_question_ref"]
        journal_entry["open_question_source"] = result.get("open_question_source", "")
    _pair_append_journal(
        r,
        pid,
        journal_entry,
        cid,
    )

    # Stage 4A: pair convergence state reducer — runs after both chars have
    # fresh output since the last convergence update. Overwrites in place.
    _compute_convergence_state(r, pid, cid, now)


def _compute_convergence_state(r, partner_id: str, cid: str, now: int) -> None:
    state = _pair_state(r, partner_id, cid)
    if not state:
        return
    existing_raw = state.get("convergence_state", "")
    existing = {}
    if existing_raw and isinstance(existing_raw, str):
        try:
            existing = json.loads(existing_raw)
        except (json.JSONDecodeError, ValueError):
            pass
    last_conv_ts = existing.get("updated_at", 0)
    ts_001 = int(state.get("updated_char_001", 0) or 0)
    ts_306 = int(state.get("updated_char_306", 0) or 0)
    if ts_001 <= last_conv_ts or ts_306 <= last_conv_ts:
        return
    shared_goal = state.get("shared_goal", "")
    open_q = state.get("open_question", "")
    focus_001 = state.get("focus_char_001", "")
    focus_306 = state.get("focus_char_306", "")
    cat_001 = state.get("category_char_001", "")
    cat_306 = state.get("category_char_306", "")
    action_001 = state.get("action_char_001", "")
    action_306 = state.get("action_char_306", "")
    last_msg = state.get("last_message_preview", "")
    last_artifact = state.get("last_artifact_title", "")
    prompt_parts = [
        "Extract convergence from this councilor pair exchange. Respond in JSON only.\n\n",
        f"Shared goal: {_compact_text(shared_goal, 120)}\n",
        f"Open question: {_compact_text(open_q, 120)}\n",
        f"char_001: {cat_001} — {_compact_text(focus_001, 120)} ({action_001})\n",
        f"char_306: {cat_306} — {_compact_text(focus_306, 120)} ({action_306})\n",
        f"Last message: {_compact_text(last_msg, 120)}\n",
        f"Last artifact: {_compact_text(last_artifact, 120)}\n",
    ]
    if existing.get("resolved", False):
        _blocked_for_prompt = existing.get("blocked_topic_terms", [])
        if _blocked_for_prompt:
            prompt_parts.append(
                f"RESOLVED TOPIC — avoid these terms in next_question: {', '.join(_blocked_for_prompt)}\n"
            )
        _resolved_answer = existing.get("resolved_answer", "")
        _resolved_question = existing.get("resolved_question", "")
        if _resolved_answer:
            prompt_parts.append(f"Previous resolved answer: {_compact_text(_resolved_answer, 120)}\n")
        if _resolved_question:
            prompt_parts.append(f"Previous resolved question: {_compact_text(_resolved_question, 120)}\n")
        prompt_parts.append(
            "IMPORTANT: The councilors have already resolved this topic. "
            "next_question must open a genuinely new direction, not re-enter the resolved topic or its blocked terms.\n"
        )
    prompt_parts.append(
        '{"current_best_answer":"","evidence_from_char_001":"","evidence_from_char_306":"","agreement":"","disagreement":"","next_question":""}'
    )
    prompt = "".join(prompt_parts)
    system = (
        "You extract convergence state from two councilors in a Federation simulation. "
        "Output ONLY a single JSON object. Fields: current_best_answer (shared understanding), "
        "evidence_from_char_001, evidence_from_char_306, agreement (overlap), "
        "disagreement (divergence), next_question (best next inquiry). "
        "Keep each field under 200 chars. If uncertain, set field to 'see evidence'."
    )
    try:
        from npc_llm_client import call_llm, DECISION_MODEL
        raw = call_llm(system, prompt, model=DECISION_MODEL or "", r=r, call_label="convergence")
        content = raw.get("content", "").strip()
        json_start = content.find("{")
        json_end = content.rfind("}")
        if json_start >= 0 and json_end > json_start:
            content = content[json_start:json_end + 1]
        conv = json.loads(content)
        for key in ("current_best_answer", "evidence_from_char_001", "evidence_from_char_306",
                     "agreement", "disagreement", "next_question"):
            if key not in conv:
                conv[key] = ""
            if isinstance(conv.get(key), str) and len(conv[key]) > 300:
                conv[key] = conv[key][:300]
        # Plateau tracking for resolution pressure
        prev_conv = existing  # Already parsed from state.get("convergence_state", "")
        prev_resolved = prev_conv.get("resolved", False)
        prev_plateau = prev_conv.get("plateau_count", 0)

        # Check for "no substantive disagreement" (fuzzy match) or repeated
        # same-topic framing differences that otherwise avoid closure forever.
        disagreement = conv.get("disagreement", "")
        is_no_disagreement = _is_no_substantive_disagreement(disagreement)
        current_topic = _matched_loop_topic(" ".join([
            disagreement,
            conv.get("current_best_answer", ""),
            conv.get("evidence_from_char_001", ""),
            conv.get("evidence_from_char_306", ""),
            conv.get("agreement", ""),
            conv.get("next_question", ""),
        ]))
        previous_topic = _matched_loop_topic(" ".join([
            prev_conv.get("disagreement", ""),
            prev_conv.get("current_best_answer", ""),
            prev_conv.get("evidence_from_char_001", ""),
            prev_conv.get("evidence_from_char_306", ""),
            prev_conv.get("agreement", ""),
            prev_conv.get("next_question", ""),
        ]))
        same_topic_pseudo_disagreement = (
            bool(current_topic)
            and current_topic == previous_topic
            and _is_pseudo_framing_disagreement(disagreement)
        )
        if is_no_disagreement:
            plateau_reason = "no_substantive"
            plateau_topic = current_topic or previous_topic
        elif same_topic_pseudo_disagreement:
            plateau_reason = "pseudo_framing"
            plateau_topic = current_topic
        else:
            plateau_reason = "none"
            plateau_topic = ""
        counts_as_plateau = is_no_disagreement or same_topic_pseudo_disagreement

        if counts_as_plateau and not prev_resolved:
            new_plateau = prev_plateau + 1
        else:
            # Reset plateau if disagreement exists or already resolved
            new_plateau = 0 if not prev_resolved else prev_plateau

        # Trigger resolution at 3 versions of no disagreement
        if new_plateau >= 3 and not prev_resolved:
            conv["resolved"] = True
            conv["resolved_answer"] = conv.get("current_best_answer", "")
            conv["resolved_question"] = conv.get("next_question", "")
            conv["resolved_at"] = now
            conv["plateau_count"] = new_plateau
            # Extract blocked topic terms from resolved content
            resolved_text = (conv.get("resolved_question", "") + " " + conv.get("resolved_answer", "")).lower()
            # Extract known blocked terms for blocking (resonance) topics
            blocked_terms = [
                term for term in KNOWN_BLOCKED_TERMS
                if term in resolved_text
            ]
            # Note: If no terms match, blocked_terms will be empty list (no fallback to "resonance")
            conv["blocked_topic_terms"] = blocked_terms
            # Stage 4D: snapshot the shared_goal and open_question at resolution time
            conv["resolved_shared_goal"] = shared_goal
            conv["resolved_open_question"] = open_q
        else:
            # Preserve existing resolution state
            conv["resolved"] = prev_resolved
            conv["resolved_answer"] = prev_conv.get("resolved_answer", "")
            conv["resolved_question"] = prev_conv.get("resolved_question", "")
            conv["resolved_at"] = prev_conv.get("resolved_at", 0)
            conv["blocked_topic_terms"] = prev_conv.get("blocked_topic_terms", [])
            conv["resolved_shared_goal"] = prev_conv.get("resolved_shared_goal", "") or shared_goal
            conv["resolved_open_question"] = prev_conv.get("resolved_open_question", "") or open_q
            conv["plateau_count"] = new_plateau
        conv["plateau_topic"] = plateau_topic
        conv["plateau_reason"] = plateau_reason

        # Stage 4D: Suppress next_question if it re-enters blocked terms after resolution
        if conv.get("resolved") and conv.get("next_question"):
            prohibited = conv.get("blocked_topic_terms", [])
            if any(term in conv["next_question"].lower() for term in prohibited if term):
                conv["next_question"] = ""
                conv["next_question_blocked_reason"] = "blocked_topic_after_resolution"
        if "next_question_blocked_reason" not in conv:
            conv["next_question_blocked_reason"] = ""

        conv["source_ids"] = [
            state.get("last_message_ts", ""),
            state.get("last_artifact_ts", ""),
        ]
        conv["updated_at"] = now
        conv["version"] = existing.get("version", 0) + 1
        _pair_hset(r, partner_id, {"convergence_state": json.dumps(conv, default=str)}, cid)
        logger.info("[%s/%s] convergence_state updated v%d", cid, partner_id, conv["version"])
    except Exception as ex:
        logger.debug("[%s/%s] convergence reducer: %s", cid, partner_id, ex)


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


def _acknowledge_operator_directive(r, directive_id: str = "", char_id: str = "", status: str = "complete", attribution: dict | None = None) -> bool:
    """Archive exactly one moderator directive by its message id.

    This is the message-specific replacement for the sender-wide
    `_acknowledge_inbox(r, "moderator")`. It removes ONLY the ZSET
    member (or legacy LIST entry) that matches `directive_id`, never every
    message from the moderator, and never deletes the underlying
    `msg:{id}` payload (preserved for history/audit).

    Production schema: inbox is the ZSET `msg:inbox:{cid}` whose members
    are `msg_{uuid}`; the body lives at `msg:{msg_id}` (HASH or JSON
    string). Legacy schema: inbox is the LIST `npc_messages:{cid}:inbox`
    of JSON strings carrying `id`/`msg_id`.
    """
    if not directive_id:
        return False
    cid = char_id or CHAR_ID
    try:
        target = directive_id if directive_id.startswith("msg_") else f"msg_{directive_id}"
        zset_key = f"msg:inbox:{cid}"
        removed = False
        if r.exists(zset_key):
            # production ZSET: remove only the matching member by id
            if r.zrem(zset_key, target):
                removed = True
            # legacy member may have been stored without the msg_ prefix
            elif r.zrem(zset_key, directive_id):
                removed = True

        if not removed:
            # legacy LIST fallback
            list_key = f"npc_messages:{cid}:inbox"
            if r.exists(list_key):
                for raw in r.lrange(list_key, 0, -1):
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    mid = m.get("id") or m.get("msg_id") or ""
                    if mid == directive_id or mid == target:
                        r.lrem(list_key, 1, raw)
                        removed = True
                        break

        # ONLY after the exact directive was successfully removed do we record
        # acknowledgement. A failed removal writes neither the latest ack nor
        # the bounded history, so a failed ack can never leave a false record.
        if not removed:
            return False

        try:
            r.set(
                f"operator_ack:{cid}",
                json.dumps({
                    "directive_id": target,
                    "status": status,
                    "ts": _now_ts(),
                }, default=str),
            )
        except Exception:
            pass
        _record_operator_ack_history(r, target, status, attribution or {}, cid=cid)
        return True
    except Exception:
        return False


def _record_operator_ack_history(r, directive_id: str = "", status: str = "complete", attribution: dict | None = None, cid: str = "") -> None:
    """Bounded forensic audit LIST for operator acknowledgements.

    The single `operator_ack:{cid}` record is overwritten on every ack and
    therefore erases the identities of earlier acknowledgements (observed
    during the oracle crash loop). This separate LIST keeps up to 20 lightweight
    entries (LPUSH + LTRIM 0 19) so recent acknowledgement history survives
    while remaining bounded. Each entry carries only an id, status, ts, and the
    requested/actual model for clean attribution — never a directive body.
    Called only after a successful exact acknowledgement.
    """
    if not directive_id:
        return
    attribution = attribution or {}
    try:
        r.lpush(
            f"operator_ack_history:{cid}",
            json.dumps({
                "directive_id": directive_id,
                "status": status,
                "ts": _now_ts(),
                "requested_model": attribution.get("requested_model", ""),
                "actual_model": attribution.get("actual_model", ""),
            }, default=str),
        )
        r.ltrim(f"operator_ack_history:{cid}", 0, 19)
    except Exception:
        pass


def _now_ts() -> float:
    import time
    return time.time()


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



