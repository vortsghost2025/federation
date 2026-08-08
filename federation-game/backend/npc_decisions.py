import os
import json
import time
import random
import logging
from typing import Dict, List, Any


logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

DECISION_CATEGORIES = [
    "advance_goal", "socialize", "investigate", "rest",
    "react_to_events", "seek_resources", "self_improve",
    "confront_rival", "help_ally", "explore", "request_capability",
]

DECISION_DESCRIPTIONS = {
    "advance_goal": "decided to work toward their goal",
    "socialize": "decided to seek out conversation",
    "investigate": "decided to look into something suspicious",
    "rest": "decided to rest and reflect",
    "react_to_events": "decided to respond to recent events",
    "seek_resources": "decided to acquire what they need",
    "self_improve": "decided to train and improve themselves",
    "confront_rival": "decided to confront an adversary",
    "help_ally": "decided to aid a companion",
    "explore": "decided to explore new territory",
    "request_capability": "requested missing capability or context",
}

MAX_DECISIONS = 10
DECISION_TTL = 86400 * 7


def _get_institution_context():
    from npc_autonomy import _get_redis

    try:
        _r = _get_redis()
        inst_ids = _r.smembers("institution:index")
        if not inst_ids:
            return {"institutions": [], "active_workflow_count": 0}
        institutions = []
        total_active = 0
        for iid in inst_ids:
            data = _r.hgetall(iid)
            name = data.get("name", "")
            kind = data.get("kind", "")
            status = data.get("status", "")
            active_count = int(_r.get(f"{iid}:active_workflows") or 0)
            total_active += active_count
            members = _r.smembers(f"{iid}:members") or set()
            institutions.append({
                "id": iid,
                "name": name,
                "kind": kind,
                "status": status,
                "active_workflows": active_count,
                "members": list(members),
            })
        return {"institutions": institutions, "active_workflow_count": total_active}
    except Exception:
        return {"institutions": [], "active_workflow_count": 0}


def _get_npc_outcome_ctx(npc_id):
    from npc_autonomy import _get_redis
    from institutions import get_npc_outcome_history

    try:
        _r = _get_redis()
        return get_npc_outcome_history(_r, npc_id)
    except Exception:
        return {"approved": 0, "rejected": 0, "total": 0, "consecutive_rejections": 0, "recent_rejected_types": set(), "recent": []}


def make_decision(char_id, char_name, archetype, affiliation, mood=""):
    from npc_autonomy import _get_redis
    from npc_needs import consume_system_notifications
    from npc_reflection import evaluate_decision_options
    from npc_actions import generate_action
    from npc_goals import generate_goal_driven_action
    from npc_interactions import generate_npc_interaction, get_npc_relationships
    from npc_world import get_world_state
    from npc_opinions import get_mood
    from npc_actions import get_world_events
    from npc_activity_logger import log_npc_activity
    from npc_needs import file_npc_need

    r = _get_redis()
    notifications = consume_system_notifications(r, char_id)
    notification_context = ""
    fulfilled_need_types = set()
    if notifications:
        parts = []
        for n in notifications:
            parts.append(
                f"[System Notice: Your request for {n.get('need_type','')} has been "
                f"{n.get('resolution','').replace('closed_','')}. {n.get('message','')}]"
            )
            if n.get("resolution", "").startswith("closed_fulfilled"):
                fulfilled_need_types.add(n.get("need_type", ""))
        notification_context = " ".join(parts)

    options, need_reflection = evaluate_decision_options(
        char_id, char_name, archetype, affiliation, mood,
        fulfilled_need_types=fulfilled_need_types,
    )
    if not options:
        return None

    top_n = min(3, len(options))
    top_options = options[:top_n]
    scores = [o["score"] for o in top_options]
    chosen = random.choices(top_options, weights=scores, k=1)[0]
    category = chosen["category"]
    decision_desc = DECISION_DESCRIPTIONS.get(category, "made a decision")
    reasoning = " + ".join(chosen.get("reasons", ["general inclination"]))

    action_result = None

    if category == "advance_goal":
        action_result = generate_goal_driven_action(
            char_id, char_name, archetype, affiliation, mood
        )
    elif category == "socialize":
        rel = get_npc_relationships(char_id)
        if rel:
            best_ally = max(rel.items(), key=lambda x: x[1])
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {"char_id": best_ally[0], "name": best_ally[0], "id": best_ally[0]},
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "investigate":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "investigation"
            action_result["description"] = (
                char_name + " began investigating a matter of concern"
            )
    elif category == "rest":
        action_result = {
            "char_id": char_id,
            "char_name": char_name,
            "action_type": "rest",
            "description": char_name + " " + decision_desc,
            "mood": mood or "contemplative",
            "ts": int(time.time()),
        }
        r = _get_redis()
        r.zadd(
            f"npc_actions:{char_id}", {json.dumps(action_result): action_result["ts"]}
        )
    elif category == "react_to_events":
        events = get_world_events(limit=3)
        if events:
            latest = events[0]
            evt_desc = latest.get("description", "recent events")
            if len(evt_desc) > 80:
                evt_desc = evt_desc[:77] + "..."
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
            if action_result:
                action_result["action_type"] = "reaction"
                action_result["description"] = char_name + " reacted to: " + evt_desc
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "seek_resources":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "acquisition"
            action_result["description"] = (
                char_name + " sought out resources and supplies"
            )
    elif category == "self_improve":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "training"
            action_result["description"] = (
                char_name + " focused on self-improvement and training"
            )
    elif category == "confront_rival":
        rel = get_npc_relationships(char_id)
        target_faction = None
        if rel:
            worst_rival = min(rel.items(), key=lambda x: x[1])
            rival_id = worst_rival[0]
            try:
                r = _get_redis()
                rival_data = r.hget(f"npc:{rival_id}", "affiliation")
                if rival_data:
                    target_faction = (
                        rival_data
                        if isinstance(rival_data, str)
                        else rival_data.decode("utf-8", errors="ignore")
                    )
            except Exception:
                pass
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {"char_id": worst_rival[0], "name": worst_rival[0], "id": worst_rival[0]},
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "help_ally":
        rel = get_npc_relationships(char_id)
        if rel:
            best_ally = max(rel.items(), key=lambda x: x[1])
            action_result = generate_npc_interaction(
                {"char_id": char_id, "name": char_name, "id": char_id},
                {"char_id": best_ally[0], "name": best_ally[0], "id": best_ally[0]},
            )
        else:
            action_result = generate_action(
                char_id, char_name, archetype, affiliation, mood
            )
    elif category == "explore":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "exploration"
            action_result["description"] = (
                char_name + " set out to explore uncharted territory"
            )
    elif category == "request_capability":
        need_type = "information_access"
        need_desc = "Context gap limiting effective action"
        if need_reflection:
            need_type = need_reflection.get("need_type", "information_access")
            need_desc = need_reflection.get("description", need_desc)
        r = _get_redis()
        related_inst = ""
        try:
            related_inst = r.get(f"councilor:{char_id}:institution") or ""
        except Exception:
            pass
        _snap_decisions = []
        try:
            for _sd in r.lrange(f"npc_decisions:{char_id}", 0, 2):
                try:
                    _snap_decisions.append(json.loads(_sd))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass
        need_result = file_npc_need(
            r, char_id, char_name, need_type, "medium",
            need_desc, reasoning, "context_enrichment", related_inst,
            context_snapshot={
                "world_state": get_world_state(),
                "recent_decisions": _snap_decisions,
                "trigger": need_reflection or {},
            },
        )
        action_result = {
            "char_id": char_id,
            "char_name": char_name,
            "action_type": "request_capability",
            "description": f"{char_name} filed a capability need: {need_type}",
            "need_filed": need_result.get("ok", False),
            "need_id": need_result.get("need_id", ""),
            "mood": mood or "reflective",
            "ts": int(time.time()),
        }

    decision = {
        "char_id": char_id,
        "char_name": char_name,
        "category": category,
        "description": char_name + " " + decision_desc,
        "reasoning": reasoning,
        "score": chosen["score"],
        "considered_options": len(options),
        "mood": mood or get_mood(char_id),
        "ts": int(time.time()),
    }
    if notification_context:
        decision["system_notifications"] = notification_context
    if category == "confront_rival":
        decision["target_faction"] = target_faction or affiliation or "unknown"
    if action_result and isinstance(action_result, dict):
        decision["action_taken"] = action_result.get("action_type", "none")
        decision["action_desc"] = action_result.get("description", "")

    r = _get_redis()
    key = f"npc_decisions:{char_id}"
    r.zadd(key, {json.dumps(decision): decision["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_DECISIONS + 1))
    r.expire(key, DECISION_TTL)

    log_npc_activity(char_id, "decision", {
        "category": category,
        "description": decision.get("description", ""),
        "reasoning": decision.get("reasoning", ""),
        "score": decision.get("score", 0),
        "options_considered": decision.get("considered_options", 0),
        "action_taken": decision.get("action_taken", "none"),
        "action_desc": decision.get("action_desc", ""),
    })

    return decision


def get_decision_log(char_id, limit=5):
    from npc_autonomy import _get_redis

    r = _get_redis()
    key = f"npc_decisions:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    decisions = []
    for item in raw:
        try:
            decisions.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return decisions
