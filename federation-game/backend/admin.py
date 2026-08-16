"""
Admin observability dashboard — read-only. Do NOT add any active intervention.
Exposes NPC health, model stats, decisions, artifacts, and pair narrative state.
"""
import json
import logging
import os
import time
from fastapi import APIRouter, Depends
from datetime import datetime

from operator_auth import require_operator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["admin"])

PAIR_IDS = ("char_001", "char_306")
HEALTHY_SECONDS = 120
WARNING_SECONDS = 300


def _r():
    import redis as _r
    return _r.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _health(c: dict) -> str:
    now = c.get("last_tick_ts", 0)
    age = time.time() - now if now else 9999
    if age > WARNING_SECONDS or c.get("error_rate", 0) >= 30:
        return "red"
    if age > HEALTHY_SECONDS or c.get("error_rate", 0) >= 10:
        return "yellow"
    return "green"


def _agent_ids(r) -> list[str]:
    ids = []
    try:
        raw = r.hgetall("npc_agent:registry") or {}
        ids = sorted(raw.keys())
    except Exception:
        pass
    if not ids:
        try:
            for key in r.scan_iter("npc_stats:*"):
                cid = key.split(":", 1)[1] if ":" in key else ""
                if cid and cid not in ids:
                    ids.append(cid)
        except Exception:
            pass
    return ids or list(PAIR_IDS)


def _pull_llm_logs(r, char_id: str) -> list[dict]:
    try:
        raw = r.lrange(f"npc_llm_logs:{char_id}", 0, 49)
        return [json.loads(x) for x in raw if x]
    except Exception:
        return []


def _pull_decisions(r, char_id: str) -> list[dict]:
    try:
        raw = r.zrevrange(f"npc_decisions:{char_id}", 0, 49)
        return [json.loads(x) for x in raw if x]
    except Exception:
        return []


def _pull_stats(r, char_id: str) -> dict:
    try:
        return r.hgetall(f"npc_stats:{char_id}") or {}
    except Exception:
        return {}


def _compute_agent_status(r, char_id: str, ids: list[str]) -> dict:
    logs = _pull_llm_logs(r, char_id)
    decisions = _pull_decisions(r, char_id)
    stats = _pull_stats(r, char_id)

    name = stats.get("npc_name", char_id)
    try:
        reg = r.hget("npc_agent:registry", char_id) or ""
        if reg:
            name = reg.split("|")[0] or name
    except Exception:
        pass

    model = stats.get("last_model", "")
    last_ts = int(stats.get("last_ts", 0) or 0)

    total = len(logs)
    failures = [x for x in logs if not x.get("success")]
    errors_429 = [x for x in failures if "429" in (x.get("error") or "")]
    errors_timeout = [
        x for x in failures
        if "timed out" in (x.get("error") or "").lower()
        or "timeout" in (x.get("error") or "").lower()
        or "read operation timed out" in (x.get("error") or "").lower()
    ]
    errors_other = [
        x for x in failures
        if x not in errors_429 and x not in errors_timeout
    ]

    parse_failures = [
        d for d in decisions
        if "parse error" in (d.get("reasoning") or "").lower()
        or d.get("action_taken") == "unknown_category_logged"
    ]

    error_rate = round(len(failures) / total * 100, 1) if total else 0

    last_decision = decisions[0] if decisions else None

    artifacts = []
    try:
        raw = r.lrange(f"npc_artifacts:{char_id}", 0, 4)
        for a in raw:
            try:
                artifacts.append(json.loads(a))
            except Exception:
                pass
    except Exception:
        pass
    artifact_count = int(stats.get("artifacts_created", 0) or 0) or len(artifacts)
    last_artifact_title = artifacts[0].get("title", "") if artifacts else ""

    mood = ""
    try:
        mood = r.get(f"npc_mood:{char_id}") or ""
    except Exception:
        pass

    c = {
        "char_id": char_id,
        "name": name,
        "model": model,
        "last_tick_ts": last_ts,
        "last_tick_ago_s": int(time.time() - last_ts) if last_ts else None,
        "mood": mood,
        "last_decision": last_decision,
        "llm_calls_total": total,
        "llm_failures_429": len(errors_429),
        "llm_failures_timeout": len(errors_timeout),
        "llm_failures_other": len(errors_other),
        "parse_failures": len(parse_failures),
        "error_rate_pct": error_rate,
        "artifact_count": artifact_count,
        "last_artifact_title": last_artifact_title,
    }
    c["health"] = _health(c)
    return c


def _pull_pair(r) -> dict:
    slug = "__".join(sorted(PAIR_IDS))
    state = {}
    journal = []
    thread = []
    try:
        state = r.hgetall(f"npc_pair:{slug}:state") or {}
    except Exception:
        pass
    try:
        raw = r.lrange(f"npc_pair:{slug}:journal", -8, -1)
        journal = [json.loads(x) for x in raw if x]
    except Exception:
        pass
    tid = state.get("active_thread_id", "")
    if tid:
        try:
            keys = r.zrevrange(f"msg:thread:{tid}", 0, 9)
            for k in reversed(keys):
                raw = r.get(k)
                if raw:
                    thread.append(json.loads(raw))
        except Exception:
            pass
    return {
        "pair_ids": list(PAIR_IDS),
        "shared_goal": state.get("shared_goal", ""),
        "current_topic": state.get("current_topic", ""),
        "open_question": state.get("open_question", ""),
        "last_message_preview": state.get("last_message_preview", ""),
        "last_message_from": state.get("last_message_from", ""),
        "last_message_ts": int(state.get("last_message_ts", 0) or 0),
        "partner_answer": state.get("partner_answer", ""),
        "focus_by_char": {
            c: state.get(f"focus_{c}", "") for c in PAIR_IDS
        },
        "action_by_char": {
            c: state.get(f"action_{c}", "") for c in PAIR_IDS
        },
        "category_by_char": {
            c: state.get(f"category_{c}", "") for c in PAIR_IDS
        },
        "journal": journal,
        "active_thread": thread,
    }


@router.get("/admin/status")
def admin_status(_: None = Depends(require_operator)):
    r = _r()
    if not r:
        return {"status": "error", "error": "Redis unavailable"}
    ids = _agent_ids(r)
    agents = [_compute_agent_status(r, cid, ids) for cid in ids]
    agents.sort(key=lambda a: (0 if a["health"] == "red" else 1 if a["health"] == "yellow" else 2, a["char_id"]))
    pair = _pull_pair(r)
    try:
        now_iso = datetime.utcnow().isoformat() + "Z"
    except Exception:
        now_iso = ""
    try:
        institution_count = r.scard("institution:index")
        role_count = r.scard("role:index")
    except Exception:
        institution_count = None
        role_count = None
    return {
        "status": "ok",
        "agents": agents,
        "pair": pair,
        "institution_count": institution_count,
        "role_count": role_count,
        "updated_at": now_iso,
        "ts": int(time.time()),
    }