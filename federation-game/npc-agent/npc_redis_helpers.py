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
# Triggerless post-resolution pivot: when the pair has stayed resolved long
# enough without a partner send_message (they're stuck in solo-artifact
# orbit around the resolved goal), the reducer clears open_question so the
# next _sync_pair_workspace call enters the _post_resolution_default
# branch and Edit A's loop-guard picks a novel shared goal.
POST_RESOLUTION_PIVOT_GAP_VERSIONS = int(os.environ.get("POST_RESOLUTION_PIVOT_GAP_VERSIONS", "4"))
POST_RESOLUTION_PIVOT_GAP_SECONDS = int(os.environ.get("POST_RESOLUTION_PIVOT_GAP_SECONDS", str(60 * 60)))
POST_RESOLUTION_PIVOT_REARM_VERSIONS = int(os.environ.get("POST_RESOLUTION_PIVOT_REARM_VERSIONS", "3"))


KNOWN_BLOCKED_TERMS = [
    "structured resonance lattice",
    "corruption-linked resonance",
    "anchor network",
    "resonance",
    "lattice",
    # Governance / influence-family terms the pair historically fixates on.
    "equitable stakeholder influence",
    "stakeholder influence",
    "trust-measurement framework",
    "network upgrade weighting",
    "weighted influence",
    "governance model",
    # Witness-layer research fixation family (emerged 2026-08-14). The pair
    # orbited "filter candidate layers" / "APVI deviation" / "spectral
    # coherence" for hours with near-identical write_code turns, and the
    # topic-fatigue cooldown + plateau counters never engaged because none of
    # these were recognised loop topics. The bare word "layer" must stay first
    # so the fatigue-detected topic ("layer") maps to a non-empty loop topic.
    "layer",
    "witness layer",
    "candidate layer",
    "spectral coherence",
    "apvi",
    "entropy flux",
    "sampling verification",
]

# Canonical fold targets for the fixed-loop topic family (mirrors the resonance
# fold in _matched_loop_topic). Any member of a family reduces to one token so
# _common_topic == _conv_topic comparisons hold regardless of which member the
# text matched first.
_RESONANCE_FOLD_TERMS = {
    "structured resonance lattice",
    "corruption-linked resonance",
    "resonance",
    "lattice",
}
_LAYER_FOLD_TERMS = {
    "layer",
    "witness layer",
    "candidate layer",
    "spectral coherence",
    "apvi",
    "entropy flux",
    "sampling verification",
}


def _is_no_substantive_disagreement(text: str) -> bool:
    t = (text or "").lower()
    return (
        "no substantive disagreement" in t
        or "no substantive" in t
        or "no disagreement" in t
        or "no substantive divergence" in t
        # Consensus phrasings the LLM convergence reducer emits that previously
        # slipped the fuzzy net ("no significant disagreement" kept oscillating
        # the plateau counter between 0 and 1 instead of climbing to the
        # resolution threshold of 3).
        or "no significant disagreement" in t
        or "no significant divergence" in t
        or "no meaningful disagreement" in t
        or "no meaningful divergence" in t
    )


def _matched_loop_topic(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return ""
    for term in KNOWN_BLOCKED_TERMS:
        if term in t:
            if term in _RESONANCE_FOLD_TERMS:
                return "resonance"
            if term in _LAYER_FOLD_TERMS:
                return "layer"
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
    except Exception as e:
        logger.warning("[%s] _pair_hset write failed for %s: %s", CHAR_ID, key, e)


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
    except Exception as e:
        logger.warning(
            "[%s] pair journal append failed for %s: %s",
            char_id or CHAR_ID, key, e,
        )


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
        logger.warning("[%s] thread message store failed: %s", cid, e)


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
    # Lazy import to avoid a circular import (npc_actions imports this module).
    try:
        from npc_actions import _clean_focus_text
    except Exception:
        _clean_focus_text = lambda t: _compact_text(t, 180)
    desc = _clean_focus_text(desc)
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
    # Loop guard (added): when the pair has RESOLVED a topic and convergence
    # has already staged a fresh next_question, force the post-resolution pivot
    # to consume it even while the headline open_question is still populated.
    # Without this, the pivot below only fired when open_question first cleared,
    # which could leave the pair's headline stuck on the resolved topic for
    # days even though the convergence reducer had already produced a new step.
    _cc_for_pivot = {}
    try:
        _raw_conv_piv = state.get("convergence_state")
        if _raw_conv_piv:
            _cc_for_pivot = json.loads(_raw_conv_piv) if isinstance(_raw_conv_piv, str) else {}
    except Exception:
        _cc_for_pivot = {}
    # A "retained resolution" means convergence_state still carries a
    # resolved_shared_goal for the CURRENT shared_goal (a past resolution that
    # was never consumed by a pivot). This is true even after `resolved` has
    # flipped False, which happens when a prior pivot reset convergence_state
    # but the reducer re-resolved or left residue. Firing the pivot on a
    # retained resolution advances the pair off the stuck theme exactly once;
    # the success path below wipes resolved_shared_goal so it cannot loop.
    _retained_resolution = (
        bool(_cc_for_pivot)
        and bool((_cc_for_pivot.get("resolved_shared_goal", "") or "").strip())
        and str(_cc_for_pivot.get("resolved_shared_goal", "") or "") == str(state.get("shared_goal", "") or "")
        and (state.get("open_question", "") or "") in (
            "",
            str(_cc_for_pivot.get("resolved_shared_goal", "") or ""),
        )
    )
    _pending_pivot = (
        _retained_resolution
        and bool((_cc_for_pivot.get("next_question", "") or "").strip())
    )
    if (not state.get("open_question") and mapping.get("open_question") != "") or _pending_pivot:
        # Stage 4D: after resolution, do not regenerate open_question from
        # the same resolved shared_goal — that re-anchors to the blocked topic.
        _post_resolution_default = False
        if state.get("convergence_state"):
            try:
                _cr = state["convergence_state"]
                _cc = json.loads(_cr) if isinstance(_cr, str) else {}
            except Exception:
                _cc = {}
            if _cc and ((_cc.get("resolved", False) or _retained_resolution)) and _cc.get("resolved_shared_goal") and \
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
            # Recent-theme cooldown: derive cooling terms from recently
            # completed goals so old families revive later instead of being
            # banned forever.
            _recent_terms = _recent_theme_terms(r, cid)
            _combined_blocked = list(dict.fromkeys(_blocked + _recent_terms))
            # Loop guard (added):  extend the blocked-term set with significant
            # tokens drawn directly from the resolved shared_goal AND the
            # resolved question.  Without this, the LLM can return a
            # next_question that semantically echoes the resolved topic
            # (same nouns/verbs) even when those terms were never added to
            # convergence_state.blocked_topic_terms — and the pivot branch at
            # line 619 will then accept it (writing open_question == shared_goal
            # and re-anchoring the pair to the resolved topic forever).
            # We strip short stopwords so we don't over-block common words
            # ("the", "and", "what", "across", etc.) but keep any meaningful
            # noun-ish/verb-ish token length >= 4.
            _resolved_topics_text = " ".join([
                str(state.get("shared_goal", "") or ""),
                str(_cc.get("resolved_shared_goal", "") or ""),
                str(_cc.get("resolved_question", "") or ""),
                str(_cc.get("resolved_answer", "") or ""),
            ]).lower()
            _STOPWORDS_RESOLVED = {
                "the", "and", "for", "with", "from", "that", "this", "what",
                "how", "should", "could", "would", "across", "between", "into",
                "their", "these", "those", "must", "mustn", "will", "shall",
                "have", "been", "were", "they", "them", "than", "when", "where",
                "which", "whose", "about", "above", "below", "after", "before",
                "diverse", "various", "ensure", "ensures",
            }
            for _tok in _resolved_topics_text.replace(",", " ").replace(".", " ").split():
                _t = _tok.strip("'-\".;:!?").lower()
                if len(_t) >= 4 and _t not in _STOPWORDS_RESOLVED and _t not in _combined_blocked:
                    _combined_blocked.append(_t)
            # Novelty gate: if the LLM's next_question re-enters recent themes,
            # fall back to an autonomous novel next-goal proposal.
            _novel_next, _novel_candidates = _propose_novel_next_goal(r, _cc, _combined_blocked, cid)
            _reenters_recent = bool(_next_q) and bool(_combined_blocked) and any(
                t and t.lower() in _next_q.lower() for t in _combined_blocked
            )
            if _reenters_recent and _novel_next:
                mapping["open_question"] = _novel_next
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_novel"
                # Advance the shared goal so the pair is not wed to the resolved
                # theme forever — the novel goal becomes the new shared_goal.
                mapping["shared_goal"] = _novel_next
            elif _next_q and not _reenters_recent:
                mapping["open_question"] = _next_q
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_pivot"
                # Same re-anchoring hazard as the novel branch: the pivot
                # question replaces the resolved goal as the pair's new shared
                # objective, so the stale resolved goal stops being re-derived.
                mapping["shared_goal"] = _next_q
            elif _novel_next:
                mapping["open_question"] = _novel_next
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_novel"
                # Advance the shared goal to the novel next objective.
                mapping["shared_goal"] = _novel_next
            else:
                mapping["open_question"] = _default_post_resolution_question()
                mapping["open_question_from"] = "system"
                mapping["open_question_ts"] = str(now)
                mapping["open_question_source"] = "post_resolution_default"
                # No next-question or novel proposal survived; adopt the default
                # pivot as the new shared objective so the pair still detaches
                # from the resolved theme instead of re-anchoring to it.
                mapping["shared_goal"] = mapping["open_question"]
            # The pair has now advanced to a NEW shared goal off the resolved
            # theme. The convergence reducer still sees the stale resolved=True
            # (and its resolved_shared_goal) from the OLD topic, which blocks it
            # from ever re-resolving or recording the new goal. Reset the
            # convergence_state so the new topic can build a fresh resolution
            # and get persisted to the completed_goals ledger.
            mapping["convergence_state"] = json.dumps({
                "resolved": False,
                "resolved_answer": "",
                "resolved_question": "",
                "resolved_at": 0,
                "resolved_shared_goal": "",
                "resolved_open_question": "",
                "blocked_topic_terms": [],
                "plateau_count": 0,
                "current_best_answer": "",
                "next_question": "",
                "version": int(json.loads(state["convergence_state"]).get("version", 0)) if isinstance(state.get("convergence_state"), str) else 0,
            }, default=str)
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

    # Record a concrete outcome when a real consequence is now visible, so the
    # outcome-feedback ledger is not left as a pile of "awaiting" placeholders.
    try:
        if answering_partner_question and mapping.get("partner_answer"):
            # The prior open question produced a concrete answer.
            _record_outcome_consequence(
                r,
                state.get("last_open_question_sent_to_partner", "") or focus,
                "partner answered: " + _compact_text(mapping["partner_answer"], 200),
                consequence={"kind": "partner_answer", "from": cid},
                char_id=cid,
            )
        elif result.get("artifact_title"):
            # A produced artifact is a durable outcome in itself.
            _record_outcome_consequence(
                r,
                result["artifact_title"],
                "produced durable work",
                consequence={"kind": "artifact", "chars": len(str(result.get("message_body") or ""))},
                char_id=cid,
            )
    except Exception:
        pass

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
            "next_question MUST open a genuinely new direction. "
            "RULES for next_question:\n"
            "  - Do NOT reuse nouns, verbs, or signature terms from the resolved question above.\n"
            "  - Do NOT echo the resolved answer or shared goal.\n"
            "  - Do NOT re-enter any term listed in 'avoid these terms'.\n"
            "  - next_question must be SHORT (<= 25 words) and must name a DIFFERENT "
            "sub-domain (audit, interoperability, cross-language consistency, "
            "enforcement, monitoring, cost, adoption, downstream impact, etc.) than the resolved topic.\n"
            "  - If you cannot propose something clearly new, return an empty string for next_question.\n"
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
            # Snapshot the version we are resolving at so the triggerless
            # post-resolution pivot can require N reducer runs to have
            # elapsed before forcing open_question blank.
            conv["resolved_version"] = (existing.get("version", 0) or 0) + 1
            # Reset any stale pivot_forced markers from prior cycles.
            conv["pivot_forced_version"] = 0
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
            # Durable completion memory: persist this resolved goal so the pair
            # cannot rediscover it later and so a recent-theme novelty gate can
            # steer the next goal into genuinely new territory.
            _record_goal_completion(r, conv, partner_id, cid)
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
            conv["resolved_version"] = prev_conv.get("resolved_version", 0) or 0
            conv["pivot_forced_version"] = prev_conv.get("pivot_forced_version", 0) or 0
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

        # Triggerless post-resolution pivot: see POST_RESOLUTION_PIVOT_GAP_*.
        try:
            _force_pivot = False
            if conv.get("resolved", False):
                _cur_open_q = state.get("open_question", "") or ""
                _resolved_at = int(conv.get("resolved_at", 0) or 0)
                _resolved_version = int(conv.get("resolved_version", 0) or 0)
                _pivot_forced_version = int(conv.get("pivot_forced_version", 0) or 0)
                try:
                    _last_msg_ts = int(state.get("last_message_ts", 0) or 0)
                except Exception:
                    _last_msg_ts = 0
                _cur_version = int(conv.get("version", 0) or 0)
                _gap_versions = _cur_version - _resolved_version
                _gap_seconds = now - _resolved_at if _resolved_at else 0
                _still_on_resolved = bool(_cur_open_q)
                _no_partner_msg_since = (_last_msg_ts <= _resolved_at)
                _versions_ready = (_gap_versions >= POST_RESOLUTION_PIVOT_GAP_VERSIONS)
                _wallclock_ready = (_gap_seconds >= POST_RESOLUTION_PIVOT_GAP_SECONDS)
                _rearmed = (
                    _pivot_forced_version == 0
                    or (_cur_version - _pivot_forced_version) >= POST_RESOLUTION_PIVOT_REARM_VERSIONS
                )
                if (_still_on_resolved and _no_partner_msg_since
                        and _versions_ready and _wallclock_ready and _rearmed):
                    _force_pivot = True
                if (_pivot_forced_version > 0
                        and (_cur_version - _pivot_forced_version) < POST_RESOLUTION_PIVOT_REARM_VERSIONS):
                    _force_pivot = False
            if _force_pivot:
                _pivot_trigger = {
                    "open_question": "",
                    "open_question_from": "",
                    "open_question_ts": "",
                    "open_question_source": "",
                    "last_open_question_sent_to_partner": "",
                    "last_open_question_ts": "",
                }
                _pair_hset(r, partner_id, _pivot_trigger, cid)
                conv["pivot_forced_version"] = int(conv.get("version", 0) or 0)
                _pair_hset(
                    r, partner_id,
                    {"convergence_state": json.dumps(conv, default=str)},
                    cid,
                )
                _pair_append_journal(
                    r, partner_id,
                    {
                        "ts": now,
                        "actor": cid,
                        "actor_name": "system",
                        "category": "force_pivot",
                        "action": "post_resolution_pivot_forced",
                        "summary": (
                            "system cleared open_question after "
                            f"{int(conv.get('version','0') or 0) - int(conv.get('resolved_version','0') or 0)} "
                            "reducer runs with no partner message since resolution; "
                            "next sync will propose a novel shared goal via the loop-guard."
                        ),
                        "thread_id": "",
                        "open_question_ref": "",
                        "open_question_source": "post_resolution_pivot_forced",
                    },
                    cid,
                )
                logger.info(
                    "[%s/%s] triggerless post-resolution pivot armed at v%d "
                    "(resolved at v%d, gap %d versions / %ds, no partner send_message)",
                    cid, partner_id,
                    int(conv.get("version", 0) or 0),
                    int(conv.get("resolved_version", 0) or 0),
                    int(conv.get("version", 0) or 0) - int(conv.get("resolved_version", 0) or 0),
                    now - int(conv.get("resolved_at", 0) or 0),
                )
        except Exception as _piv_exc:
            logger.debug("[%s/%s] triggerless pivot check failed: %s",
                         cid, partner_id, _piv_exc)
    except Exception as ex:
        logger.debug("[%s/%s] convergence reducer: %s", cid, partner_id, ex)


# ── Goal progression: durable completion memory + recent-theme novelty ──
# A completed goal is written to a durable list so the pair cannot "rediscover"
# it later. Recent-theme cooldown derives banned terms from recently completed
# goals (with a window), so old families cool off rather than being banned
# forever. Novelty scoring lets the agents choose genuinely different next goals.
COMPLETED_GOALS_MAX = 20            # cap on durable completion records kept
RECENT_COMPLETION_WINDOW = 8        # how many recent goals feed the novelty gate


def _completed_goals_key(char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    pid = _partner_id(cid)
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(cid, pid)}:completed_goals"


def _recent_completed_goals(r, char_id: str = "", limit: int = RECENT_COMPLETION_WINDOW) -> list:
    """Return the most recent completed-goal records (dicts), oldest first."""
    key = _completed_goals_key(char_id)
    if not key:
        return []
    try:
        # Records are appended via rpush (tail) and trimmed to the last N with
        # ltrim(key, -N, -1), so the START of the list holds the OLDEST goals.
        # Read from the tail (-limit..-1) to get the most recent.
        raw_list = r.lrange(key, -limit, -1)
    except Exception:
        return []
    out = []
    for line in raw_list or []:
        try:
            rec = json.loads(line) if isinstance(line, str) else line
            if isinstance(rec, dict):
                out.append(rec)
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _recent_theme_terms(r, char_id: str = "") -> list:
    """Derive recently-cooling theme terms from recently completed goals.

    These are the families to avoid re-entering as the NEXT shared goal. They
    are drawn only from the recent window, so an old family can return later
    once it falls out of the window (a cooldown, not a permanent ban)."""
    terms = []
    for rec in _recent_completed_goals(r, char_id):
        g = (rec.get("goal") or "")
        q = (rec.get("open_question") or "")
        a = (rec.get("conclusion") or "")
        text = f"{g} {q} {a}".lower()
        for term in KNOWN_BLOCKED_TERMS:
            if term and term in text and term not in terms:
                terms.append(term)
    return terms


def _record_goal_completion(r, conv: dict, partner_id: str, char_id: str = "") -> None:
    """Persist a durable completion record for a resolved shared goal.

    Written once per resolved goal (dedup by goal text) so the pair has lasting
    memory of what was finished and what resulted — even after the transient
    convergence_state is lost or the context window rolls over."""
    goal = conv.get("resolved_shared_goal") or ""
    if not goal:
        return
    key = _completed_goals_key(char_id)
    if not key:
        return
    # Dedup: skip if this exact goal is already recorded.
    for rec in _recent_completed_goals(r, char_id, limit=COMPLETED_GOALS_MAX):
        if (rec.get("goal") or "") == goal:
            return
    record = {
        "goal": goal,
        "conclusion": conv.get("resolved_answer") or conv.get("current_best_answer") or "",
        "resolved_question": conv.get("resolved_question") or "",
        "open_question": conv.get("resolved_open_question") or "",
        "agreement": conv.get("agreement") or "",
        "disagreement": conv.get("disagreement") or "",
        "blocked_topic_terms": conv.get("blocked_topic_terms") or [],
        "resolved_at": conv.get("resolved_at") or int(time.time()),
        "source_ids": conv.get("source_ids") or [],
    }
    try:
        r.rpush(key, json.dumps(record, default=str))
        r.ltrim(key, -COMPLETED_GOALS_MAX, -1)
        logger.info("[%s/%s] recorded completed goal: %s", char_id or CHAR_ID, partner_id,
                    _compact_text(goal, 80))
    except Exception as e:
        logger.debug("[%s] goal completion record failed: %s", char_id or CHAR_ID, e)


def _propose_novel_next_goal(r, conv: dict, blocked_terms: list, char_id: str = ""):
    """Autonomously propose + select a genuinely novel next shared goal.

    Returns (selected_goal_or_empty, candidates_list). Asks the councilors to
    propose candidate objectives that materially differ from recently resolved
    work, scores them against the recent-goal context for novelty, rejects
    obvious repetitions, and selects one. The agents choose *what* comes next;
    this only supplies memory, consequences, and anti-loop scaffolding."""
    recent = _recent_completed_goals(r, char_id)
    recent_text = " | ".join(
        f"{rec.get('goal','')} -> {rec.get('conclusion','')}" for rec in recent
    ) or "none yet"
    candidate_prompt = (
        "Propose 3 candidate next shared objectives for the Federation councilor "
        "pair. They must materially differ from the recently completed work below. "
        "Do NOT reuse those themes. Return JSON only: "
        '{"candidates":[{"objective":"...","why_novel":"..."} x3]}\n\n'
        f"Recently completed:\n{_compact_text(recent_text, 500)}\n"
        f"Blocked/cooling terms to avoid: {', '.join(blocked_terms) if blocked_terms else 'none'}\n"
    )
    candidate_system = (
        "You propose novel, distinct world-building objectives. Each must be a "
        "concrete, actionable next project, clearly different from the recently "
        "completed goals. Output ONLY a JSON object with a 'candidates' array of "
        "3 objects, each with 'objective' and 'why_novel'. Keep each objective "
        "under 120 chars."
    )
    candidates = []
    try:
        from npc_llm_client import call_llm, DECISION_MODEL
        raw = call_llm(candidate_system, candidate_prompt, model=DECISION_MODEL or "", r=r, call_label="propose_next_goals")
        content = (raw.get("content") or "").strip()
        js = content.find("{")
        je = content.rfind("}")
        if js >= 0 and je > js:
            content = content[js:je + 1]
        parsed = json.loads(content)
        for c in parsed.get("candidates", []):
            obj = (c.get("objective") or "").strip()
            if obj:
                candidates.append(c)
    except Exception:
        candidates = []

    # Novelty gate: reject candidates that re-enter recent themes or blocked terms.
    survivors = []
    for c in candidates:
        obj = (c.get("objective") or "").lower()
        if blocked_terms and any(t and t.lower() in obj for t in blocked_terms):
            continue
        if any(t and t.lower() in obj for t in KNOWN_BLOCKED_TERMS):
            continue
        survivors.append(c.get("objective"))

    if not survivors:
        return "", survivors
    # Prefer the first surviving candidate (agents already proposed them in
    # novelty order); keep the rest as options for the pair's own mechanism.
    return survivors[0], survivors


# ══════════════════════════════════════════════════════════════════
#  Semantic deduplication + outcome feedback
# ══════════════════════════════════════════════════════════════════
#
# The existing guards (topic fatigue, title Jaccard, dedup streak) only work
# on TITLES and single content words. The pair historically re-published the
# same *content* under slightly different titles ("Void Oracle Anomalies:
# A Comprehensive Analysis" then "Anomalies of the Void Oracle: Full Study").
# This adds:
#   1. Content-level semantic similarity (token overlap on the artifact body,
#      not just the title) so near-identical writing is caught.
#   2. Outcome feedback: a durable record of what CONSEQUENCE an artifact or
#      decision produced (world-state delta, partner response, quest progress).
#      That outcome is injected back into the decision prompt so the agent
#      learns from its own results instead of repeating blind attempts.
#   3. Cross-pair semantic memory: a shared ledger of "what produced what" so
#      both councilors converge on what works rather than both rediscovering
#      the same dead ends.

SEMANTIC_DEDUP_WINDOW = int(os.environ.get("SEMANTIC_DEDUP_WINDOW", "12"))
SEMANTIC_SIMILARITY_THRESHOLD = float(os.environ.get("SEMANTIC_SIMILARITY_THRESHOLD", "0.72"))
OUTCOME_TTL = int(os.environ.get("OUTCOME_TTL", str(86400 * 14)))
OUTCOME_FEEDBACK_CAP = int(os.environ.get("OUTCOME_FEEDBACK_CAP", "40"))

_SEMANTIC_STOP_WORDS = frozenset({
    "the", "of", "and", "a", "an", "to", "in", "for", "on", "with", "from",
    "by", "at", "is", "it", "as", "be", "or", "that", "this", "its", "are",
    "was", "but", "not", "all", "being", "have", "has", "been", "will",
    "would", "could", "should", "may", "might", "shall", "do", "does", "did",
    "no", "nor", "so", "up", "out", "about", "into", "over", "after", "before",
    "between", "under", "above", "below", "also", "very", "just", "more",
    "some", "any", "each", "every", "both", "few", "most", "other", "such",
    "only", "own", "same", "than", "too", "well", "now", "even", "back",
    "still", "here", "there", "then", "when", "where", "why", "how", "what",
    "which", "who", "whom", "analysis", "report", "overview", "summary",
    "data", "assessment", "recommendation", "implication", "strategy",
    "strategic", "response", "impact", "update", "review", "comprehensive",
    "final", "interim",
})


def _semantic_tokenize(text: str, min_len: int = 3) -> list[str]:
    """Tokenize text into lowercased content words (stop words removed)."""
    if not text:
        return []
    return [
        w for w in re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
        if w not in _SEMANTIC_STOP_WORDS
    ]


def _semantic_overlap(a_text: str, b_text: str) -> float:
    """Similarity between two texts by content-token overlap (0..1).

    Uses a blended similarity that resists false positives when one text is
    much shorter than the other. Pure `overlap / min(len)` would score a short
    artifact at 1.0 whenever its words are a subset of a longer, unrelated
    piece. Instead, blend the long-text containment (overlap / max) with the
    short-text coverage (overlap / min): a genuine near-duplicate still scores
    high on both, but a short generic text inside a long specific one scores
    low because the long text contains many extra tokens.
    """
    a_tokens = _semantic_tokenize(a_text)
    b_tokens = _semantic_tokenize(b_text)
    if not a_tokens or not b_tokens:
        return 0.0
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    overlap = len(a_set & b_set)
    larger = max(len(a_set), len(b_set))
    smaller = min(len(a_set), len(b_set))
    if smaller == 0 or larger == 0:
        return 0.0
    # Weighted blend: 60% containment of the larger text, 40% coverage of the
    # smaller. A contained short text scores ~0.4, well under the 0.72 gate,
    # while two near-identical artifacts score ~1.0 on both terms.
    containment = overlap / larger
    coverage = overlap / smaller
    return 0.6 * containment + 0.4 * coverage


def _older_artifact_records(r, char_id: str = "", limit: int = SEMANTIC_DEDUP_WINDOW) -> list[dict]:
    """Return recent artifact records (oldest-first) for a char, best-effort."""
    cid = char_id or CHAR_ID
    try:
        raw = r.lrange(f"npc_artifacts:{cid}", -max(limit, 1), -1)
    except Exception:
        return []
    out = []
    for item in raw or []:
        try:
            out.append(json.loads(item) if isinstance(item, str) else item)
        except Exception:
            continue
    return out


def _find_semantic_duplicate_artifact(
    r, title: str, content: str, char_id: str = "",
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> dict | None:
    """Return a prior artifact whose CONTENT is semantically near-identical.

    Checks both the proposing agent's own recent artifacts and the partner's,
    so neither councilor re-publishes the other's recent work under a new
    title. Returns the matched artifact dict or None.
    """
    if r is None:
        return None
    cid = char_id or CHAR_ID
    probe_text = f"{title or ''} {content or ''}"
    # Own artifacts
    for art in _older_artifact_records(r, cid):
        art_text = f"{art.get('title', '')} {art.get('content', '')}"
        if _semantic_overlap(probe_text, art_text) >= threshold:
            return art
    # Partner artifacts (cross-pair dedup)
    pid = _partner_id(cid)
    if pid:
        for art in _older_artifact_records(r, pid):
            art_text = f"{art.get('title', '')} {art.get('content', '')}"
            if _semantic_overlap(probe_text, art_text) >= threshold:
                return art
    return None


# ── Outcome feedback ──────────────────────────────────────────────
# A durable hash (per char) of recent {artifact_title, outcome, ts} plus a
# shared pair ledger. The outcome is whatever the artifact/decision produced:
# a world-state delta, a partner response, a quest completion, or a dead end.
# It is injected into context so the agent learns from results.

def _outcome_key(char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_outcomes:{cid}"


def _pair_outcome_key(char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    pid = _partner_id(cid)
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(cid, pid)}:outcomes"


def _record_outcome_feedback(
    r, artifact_title: str, outcome: str,
    consequence: dict | None = None, char_id: str = "",
) -> None:
    """Persist a durable outcome record for a produced artifact/decision.

    Stores a bounded list per char AND appends to the shared pair ledger so
    both councilors see what produced what. The outcome text is injected back
    into the cognition prompt by _load_outcome_feedback.
    """
    cid = char_id or CHAR_ID
    if r is None or not artifact_title:
        return
    entry = {
        "ts": int(time.time()),
        "artifact_title": artifact_title[:200],
        "outcome": _compact_text(outcome, 300),
        "consequence": {k: str(v) for k, v in (consequence or {}).items()},
    }
    try:
        key = _outcome_key(cid)
        r.lpush(key, json.dumps(entry, default=str))
        r.ltrim(key, 0, OUTCOME_FEEDBACK_CAP - 1)
        r.expire(key, OUTCOME_TTL)
    except Exception:
        pass
    pair_key = _pair_outcome_key(cid)
    if pair_key:
        try:
            r.lpush(pair_key, json.dumps(entry, default=str))
            r.ltrim(pair_key, 0, OUTCOME_FEEDBACK_CAP - 1)
            r.expire(pair_key, OUTCOME_TTL)
        except Exception:
            pass


# Atomic resolve-or-append for the outcome ledgers. The per-agent key is
# single-writer, but the shared pair key is written by BOTH agents; doing the
# lrange -> modify -> delete -> rewrite in Lua keeps concurrent writers from
# losing each other's updates or duplicating entries.
_OUTCOME_CONSEQUENCE_LUA = """
local key = KEYS[1]
local new_json = ARGV[1]
local cap = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local ok, new_entry = pcall(cjson.decode, new_json)
if not ok or type(new_entry) ~= 'table' then
  return -1
end
local title = new_entry['artifact_title']
local items = redis.call('LRANGE', key, 0, -1)
local resolved = 0
for i, raw in ipairs(items) do
  local pok, e = pcall(cjson.decode, raw)
  if pok and type(e) == 'table' and e['artifact_title'] == title
     and type(e['outcome']) == 'string'
     and string.find(e['outcome'], 'awaiting', 1, true) then
    items[i] = new_json
    resolved = 1
    break
  end
end
if resolved == 1 then
  redis.call('DEL', key)
  for _, v in ipairs(items) do
    redis.call('RPUSH', key, v)
  end
else
  redis.call('LPUSH', key, new_json)
  redis.call('LTRIM', key, 0, cap - 1)
end
redis.call('EXPIRE', key, ttl)
return resolved
"""


def _record_outcome_consequence(
    r, artifact_title: str, outcome: str,
    consequence: dict | None = None, char_id: str = "",
) -> None:
    """Record a concrete consequence for an artifact, resolving a prior
    placeholder entry in place when one exists.

    The creation path writes a static "awaiting downstream consequence"
    record. This is called once a real downstream effect is observed (partner
    answer, world-state delta, quest progress). To avoid the ledger filling
    with unresolved placeholders, it promotes a matching placeholder record to
    the concrete outcome instead of appending a new one.
    """
    cid = char_id or CHAR_ID
    if r is None or not artifact_title:
        return
    new_entry = {
        "ts": int(time.time()),
        "artifact_title": artifact_title[:200],
        "outcome": _compact_text(outcome, 300),
        "consequence": {k: str(v) for k, v in (consequence or {}).items()},
    }
    key = _outcome_key(cid)
    pair_key = _pair_outcome_key(cid)
    new_json = json.dumps(new_entry, default=str)
    for target in (key, pair_key):
        if not target:
            continue
        # Both agents write the shared pair ledger, so this read-modify-write
        # must be atomic: the Lua script does the whole resolve-or-append in
        # one step to avoid lost updates / duplicated entries under
        # concurrency.
        try:
            r.eval(_OUTCOME_CONSEQUENCE_LUA, 1, target, new_json,
                   OUTCOME_FEEDBACK_CAP, OUTCOME_TTL)
        except Exception as e:
            logger.warning(
                "[%s] outcome consequence record failed for %s: %s",
                cid, target, e,
            )


def _load_outcome_feedback(r, char_id: str = "", limit: int = 5) -> str:
    """Return a compact prompt-injection string of recent outcomes.

    Includes both the agent's own outcomes and the shared pair ledger so the
    next decision is informed by what previously worked or failed.
    """
    cid = char_id or CHAR_ID
    if r is None:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    try:
        for raw in r.lrange(_outcome_key(cid), 0, limit - 1):
            try:
                e = json.loads(raw)
                key = (e.get("artifact_title", "") + "|" + e.get("outcome", ""))[:80]
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"  • {e.get('artifact_title', '?')} → {e.get('outcome', '')}")
            except Exception:
                continue
    except Exception:
        pass
    pair_key = _pair_outcome_key(cid)
    if pair_key:
        try:
            for raw in r.lrange(pair_key, 0, limit - 1):
                try:
                    e = json.loads(raw)
                    key = (e.get("artifact_title", "") + "|" + e.get("outcome", ""))[:80]
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(f"  • [shared] {e.get('artifact_title', '?')} → {e.get('outcome', '')}")
                except Exception:
                    continue
        except Exception:
            pass
    if not lines:
        return ""
    return "## Outcomes you have produced\n" + "\n".join(lines[:10])


def _semantic_artifact_dedup_blocked(r, title: str, content: str, char_id: str = "") -> bool:
    """Best-effort guard: True when content is semantically near-identical to a
    recent artifact (breaks re-publishing under a new title)."""
    if r is None:
        return False
    hit = _find_semantic_duplicate_artifact(r, title, content, char_id)
    if hit and hit.get("title"):
        logger.info(
            "[%s] semantic dedup blocked '%s' ~ '%s'",
            char_id or CHAR_ID, title[:60], str(hit.get("title"))[:60],
        )
        return True
    return False


# ══════════════════════════════════════════════════════════════════
#  Reflection layer (from Generative Agents / Smallville)
# ══════════════════════════════════════════════════════════════════
# Generative agents feel alive partly because they REFLECT: instead of only
# recalling raw memories, they periodically synthesize recent experience into
# higher-level insights ("what have I learned?", "what is changing in the
# world around me?"). Those reflections are stored durably and retrieved
# alongside raw memories so the next decision is guided by distilled
# understanding rather than a flat log.
#
# This adds a lightweight, deterministic (no extra LLM call per tick) reflection
# that distills the pair's recent journal + outcomes into a small set of
# durable insights. It complements npc_memory_bridge.py (raw memory) and the
# outcome-feedback ledger (consequences) by abstracting upward.

REFLECTIONS_CAP = int(os.environ.get("REFLECTIONS_CAP", "12"))
REFLECTION_SOURCE_WINDOW = int(os.environ.get("REFLECTION_SOURCE_WINDOW", "10"))


def _reflections_key(char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_reflections:{cid}"


def _record_reflection(r, insight: str, char_id: str = "") -> None:
    """Persist a distilled insight (dedup by text, bounded list)."""
    cid = char_id or CHAR_ID
    if r is None or not insight:
        return
    entry = {
        "ts": int(time.time()),
        "insight": _compact_text(insight, 240),
    }
    try:
        key = _reflections_key(cid)
        existing = [json.loads(x).get("insight", "") for x in r.lrange(key, 0, -1)
                    if isinstance(x, str)]
    except Exception:
        existing = []
    if entry["insight"] in existing:
        return
    try:
        r.lpush(key, json.dumps(entry, default=str))
        r.ltrim(key, 0, REFLECTIONS_CAP - 1)
        r.expire(key, 86400 * 30)
    except Exception:
        pass


def _derive_reflections_from_journal(r, char_id: str = "") -> list:
    """Deterministically distill recent pair activity into a few insights.

    Follows the Generative Agents reflection spirit without an extra LLM call:
    cluster recent journal entries by category and surface the dominant
    patterns (what the pair is doing, whether it is progressing or repeating).
    """
    cid = char_id or CHAR_ID
    if r is None:
        return []
    pid = _partner_id(cid)
    if not pid:
        return []
    journal = _pair_recent_journal(r, pid, REFLECTION_SOURCE_WINDOW, cid)
    if not journal:
        return []
    counts: dict[str, int] = {}
    for entry in journal:
        cat = entry.get("category", "?")
        counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return []

    top_cat, top_count = max(counts.items(), key=lambda kv: kv[1])
    total = len(journal)
    insights = []
    if top_count >= 3:
        insights.append(
            f"Recent work has concentrated on {top_cat} ({top_count} of last {total} moves)."
        )
    # Progression vs repetition signal: if most entries are 'rest'/'investigate'
    # with no artifact, the pair may be circling without building.
    productive = sum(counts.get(c, 0) for c in
                     ("create_artifact", "write_code", "read_artifacts", "send_message"))
    if total >= 4 and productive <= 1:
        insights.append(
            "Little durable output recently — more reflecting than building."
        )
    elif productive >= (total * 0.5):
        insights.append(
            "Consistently producing durable work (artifacts/code/messages)."
        )

    dedup_seen = set()
    out = []
    for ins in insights:
        if ins not in dedup_seen:
            dedup_seen.add(ins)
            out.append(ins)
    return out


def _refresh_reflections(r, char_id: str = "") -> None:
    """Run the reflection derivation and persist any new insights.

    Called once per tick (cheap, bounded). Insights are deduped so they only
    appear when they meaningfully change.
    """
    cid = char_id or CHAR_ID
    if r is None:
        return
    try:
        for insight in _derive_reflections_from_journal(r, cid):
            _record_reflection(r, insight, cid)
    except Exception:
        pass


def _load_reflections(r, char_id: str = "", limit: int = 4) -> str:
    """Return a compact prompt-injection string of distilled insights."""
    cid = char_id or CHAR_ID
    if r is None:
        return ""
    try:
        raw = r.lrange(_reflections_key(cid), 0, max(limit, 1) - 1)
    except Exception:
        return ""
    if not raw:
        return ""
    lines = []
    for item in raw:
        try:
            e = json.loads(item)
            insight = e.get("insight", "")
            if insight:
                lines.append(f"  • {insight}")
        except Exception:
            continue
    if not lines:
        return ""
    return "## Reflections (what recent work taught you)\n" + "\n".join(lines)


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
        r.expire(key, 86400 * 30)
        r.hincrby(f"npc_stats:{cid}", "llm_calls", 1)
        if success:
            r.hincrby(f"npc_stats:{cid}", "llm_success", 1)
        else:
            r.hincrby(f"npc_stats:{cid}", "llm_failures", 1)
        r.hset(f"npc_stats:{cid}", "last_model", model)
        r.hset(f"npc_stats:{cid}", "last_call_label", call_label)
        r.hset(f"npc_stats:{cid}", "last_ts", str(int(time.time())))
        r.expire(f"npc_stats:{cid}", 86400 * 30)
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
        r.expire(key, 86400 * 30)
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
                ex=86400 * 30,
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
        r.expire(f"operator_ack_history:{cid}", 86400 * 30)
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



