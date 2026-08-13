import os
import json
import time
import random
import logging
from difflib import SequenceMatcher
from typing import Dict, List, Any


logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

DECISION_CATEGORIES = [
    "advance_goal", "socialize", "investigate", "rest",
    "react_to_events", "seek_resources", "self_improve",
    "confront_rival", "help_ally", "explore", "request_capability",
]

# Per-category pools of varied phrasing for the OUTER decision description.
# The previous implementation used a single template string per category, so
# every time an NPC picked the same category the same sentence landed in
# memory verbatim (e.g. "Conquistador Drake decided to explore new territory"
# appearing at the oldest and newest ends of the npc_memory zset). Pools are
# picked from with an anti-repeat check against the NPC's most recent memory
# so the long-term history stops folding onto byte-identical beats.
DECISION_DESCRIPTIONS: Dict[str, List[str]] = {
    "advance_goal": [
        "decided to work toward their goal",
        "turned their attention to a long-running goal",
        "prioritized one of their standing goals",
        "made measurable progress on a goal",
    ],
    "socialize": [
        "decided to seek out conversation",
        "looked around for someone to talk with",
        "sought a brief exchange with a peer",
        "drifted toward a gathering where voices might be heard",
    ],
    "investigate": [
        "decided to look into something suspicious",
        "picked up a thread that didn't quite sit right",
        "decided to scrutinize a recent report more closely",
        "turned a casual observation into an investigation",
    ],
    "rest": [
        "decided to rest and reflect",
        "stepped back for a moment of quiet reflection",
        "paused to let a recent decision settle",
        "took a deliberate beat of rest before the next move",
    ],
    "react_to_events": [
        "decided to respond to recent events",
        "weighed how the latest developments affect them",
        "let a fresh piece of news shape their next move",
        "responded to a shift in the wider federation",
    ],
    "seek_resources": [
        "decided to acquire what they need",
        "set out to secure materials or favors",
        "looked around for what they were running low on",
        "decided to gather a small reserve of resources",
    ],
    "self_improve": [
        "decided to train and improve themselves",
        "carved out time to sharpen a skill",
        "worked on a weak point they'd noticed in themselves",
        "chose practice over idle time",
    ],
    "confront_rival": [
        "decided to confront an adversary",
        "made ready to face a rival",
        "decided it was time to push back against an opponent",
        "approached a long-standing antagonist",
    ],
    "help_ally": [
        "decided to aid a companion",
        "offered a hand to someone they trust",
        "moved to support an ally's effort",
        "checked in on a friend who needed it",
    ],
    "explore": [
        "decided to explore new territory",
        "felt the pull of unmapped space and leaned into it",
        "set out to see what lay past the known edge",
        "chose curiosity over caution for a turn",
        "drifted toward the frontier to see something new",
    ],
    "request_capability": [
        "requested missing capability or context",
        "asked for the context they felt was missing",
        "filed a request for a tool or insight they lacked",
        "named a concrete gap that was holding them back",
    ],
}

# Per-category pools of varied phrasing for the INNER action_desc — the
# concrete description that gets stored along with the action_type and ends
# up in the npc_memory zset. This is the channel where repetition was most
# visible because each category had exactly one hardcoded line.
ACTION_DESCRIPTION_VARIANTS: Dict[str, List[str]] = {
    "investigate": [
        "{name} began investigating a matter of concern",
        "{name} pulled on a thread that didn't seem right",
        "{name} paused to scrutinize a recent report",
        "{name} turned a hunch into an open investigation",
    ],
    "rest": [
        "{name} paused to let the last decision settle",
        "{name} took a deliberate beat of rest",
        "{name} stepped back to breathe before the next move",
        "{name} rested and let the noise recede for a moment",
    ],
    "react_to_events": [
        "{name} reacted to a fresh development",
        "{name} let the latest news shape their next step",
        "{name} weighed how recent events touched them",
        "{name} took a moment to absorb before responding",
    ],
    "seek_resources": [
        "{name} sought out resources and supplies",
        "{name} gathered what they were short on",
        "{name} secured a small reserve for the path ahead",
        "{name} traded a favor for something they needed",
    ],
    "self_improve": [
        "{name} focused on self-improvement and training",
        "{name} sharpened a skill that had been slipping",
        "{name} turned idle time into deliberate practice",
        "{name} worked a weak point until it felt less weak",
    ],
    "explore": [
        "{name} set out to explore uncharted territory",
        "{name} drifted past the familiar edge of the map",
        "{name} chose a direction they hadn't walked in a while",
        "{name} stepped into unmapped space without much fanfare",
        "{name} took a longer route just to see something new",
    ],
}


def _recent_action_desc(r, char_id):
    """Read the most recent action_desc recorded in npc_memory for this NPC.

    Returns an empty string if memory is empty or unreadable. Used by
    _pick_varied_phrase to pick the next phrase so it doesn't repeat.
    """
    try:
        key = f"npc_memory:{char_id}"
        recent = r.zrevrange(key, 0, 0, withscores=False)
        if not recent:
            return ""
        raw = recent[0]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        entry = json.loads(raw)
        return str(entry.get("action_desc") or entry.get("content") or "")
    except Exception:
        return ""


def _pick_varied_phrase(r, char_id, category, phrases, max_similarity=0.85):
    """Pick a phrase from `phrases` that differs from the NPC's most recent one.

    Falls back to a random pick when there is no recent memory, when all
 phrases look similar (short pools), or when the read fails — never blocks
 the decision path. """
    try:
        if not phrases:
            return "made a decision"
        if len(phrases) == 1:
            return phrases[0]
        recent = _recent_action_desc(r, char_id)
        if not recent:
            return random.choice(phrases)
        # Score each candidate by similarity to the recent phrase; pick the
        # least-similar one, breaking ties at random so the pool doesn't drift
        # toward a single deterministic order over time.
        scored = []
        for p in phrases:
            sim = SequenceMatcher(None, recent.lower(), p.lower()).ratio()
            scored.append((sim, p))
        min_sim = min(s for s, _ in scored)
        low = [p for s, p in scored if s <= min_sim + 0.02]
        return random.choice(low) if low else random.choice(phrases)
    except Exception:
        return random.choice(phrases) if phrases else "made a decision"


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
    # Pick a varied outer-decision phrasing that differs from the most recent
    # memory entry — prevents the same template being frozen into long-term
    # memory across two consecutive same-category decisions.
    decision_desc = _pick_varied_phrase(
        r, char_id, category,
        DECISION_DESCRIPTIONS.get(category, ["made a decision"]),
    )
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
            tmpl = _pick_varied_phrase(
                r, char_id, "investigate",
                ACTION_DESCRIPTION_VARIANTS["investigate"],
            )
            action_result["description"] = tmpl.format(name=char_name)
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
            tmpl = _pick_varied_phrase(
                r, char_id, "seek_resources",
                ACTION_DESCRIPTION_VARIANTS["seek_resources"],
            )
            action_result["description"] = tmpl.format(name=char_name)
    elif category == "self_improve":
        action_result = generate_action(
            char_id, char_name, archetype, affiliation, mood
        )
        if action_result:
            action_result["action_type"] = "training"
            tmpl = _pick_varied_phrase(
                r, char_id, "self_improve",
                ACTION_DESCRIPTION_VARIANTS["self_improve"],
            )
            action_result["description"] = tmpl.format(name=char_name)
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
            tmpl = _pick_varied_phrase(
                r, char_id, "explore",
                ACTION_DESCRIPTION_VARIANTS["explore"],
            )
            action_result["description"] = tmpl.format(name=char_name)
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
