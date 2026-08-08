import json
import logging
import random

logger = logging.getLogger(__name__)

LOW_VALUE_CATEGORIES = frozenset({"rest", "wander", "noop"})

MOOD_DECISION_BIAS = {
    "contemplative": {"advance_goal": 1.5, "rest": 1.3, "self_improve": 1.2},
    "curious": {"explore": 1.8, "investigate": 1.5, "advance_goal": 1.2},
    "frustrated": {"confront_rival": 1.6, "investigate": 1.3, "advance_goal": 1.1},
    "inspired": {"advance_goal": 1.8, "self_improve": 1.4, "explore": 1.2},
    "distracted": {"rest": 1.5, "socialize": 1.3, "explore": 1.2},
    "analytical": {"investigate": 1.7, "advance_goal": 1.4, "self_improve": 1.2},
    "vigilant": {"investigate": 1.6, "react_to_events": 1.8, "help_ally": 1.3},
    "restless": {"explore": 1.6, "confront_rival": 1.3, "advance_goal": 1.2},
    "satisfied": {"socialize": 1.5, "rest": 1.4, "help_ally": 1.3},
    "aggressive": {"confront_rival": 2.0, "investigate": 1.3, "advance_goal": 1.2},
    "stoic": {"advance_goal": 1.4, "rest": 1.3, "self_improve": 1.2},
    "battle-ready": {"confront_rival": 1.8, "react_to_events": 1.6, "help_ally": 1.3},
    "calculating": {"advance_goal": 1.6, "investigate": 1.5, "seek_resources": 1.3},
    "amused": {"socialize": 1.7, "explore": 1.3, "rest": 1.2},
    "suspicious": {"investigate": 1.8, "react_to_events": 1.5, "confront_rival": 1.2},
    "opportunistic": {"seek_resources": 1.7, "advance_goal": 1.4, "explore": 1.3},
    "bored": {"explore": 1.6, "socialize": 1.4, "seek_resources": 1.3},
    "smug": {"socialize": 1.5, "advance_goal": 1.3, "rest": 1.4},
    "transcendent": {"self_improve": 1.8, "rest": 1.5, "advance_goal": 1.2},
    "troubled": {"investigate": 1.5, "react_to_events": 1.4, "help_ally": 1.2},
    "visionary": {"advance_goal": 1.7, "explore": 1.5, "self_improve": 1.3},
    "withdrawn": {"rest": 1.7, "self_improve": 1.4, "investigate": 1.2},
    "enlightened": {"help_ally": 1.6, "self_improve": 1.5, "advance_goal": 1.3},
    "unsettled": {"investigate": 1.6, "react_to_events": 1.5, "seek_resources": 1.2},
    "commanding": {"advance_goal": 1.6, "help_ally": 1.4, "confront_rival": 1.3},
    "concerned": {"react_to_events": 1.7, "help_ally": 1.6, "investigate": 1.3},
    "strategic": {"advance_goal": 1.7, "investigate": 1.5, "seek_resources": 1.3},
    "impatient": {"advance_goal": 1.5, "confront_rival": 1.4, "explore": 1.2},
    "diplomatic": {"socialize": 1.6, "help_ally": 1.5, "advance_goal": 1.3},
    "weary": {"rest": 2.0, "self_improve": 1.2, "socialize": 0.8},
    "serene": {"self_improve": 1.6, "rest": 1.5, "help_ally": 1.3},
    "pensive": {"advance_goal": 1.4, "rest": 1.3, "investigate": 1.3},
    "patient": {"advance_goal": 1.5, "self_improve": 1.4, "help_ally": 1.3},
    "worried": {"react_to_events": 1.7, "investigate": 1.5, "help_ally": 1.3},
    "peaceful": {"rest": 1.6, "socialize": 1.4, "self_improve": 1.3},
    "melancholic": {"rest": 1.5, "explore": 1.3, "self_improve": 1.2},
    "excited": {"explore": 1.7, "advance_goal": 1.5, "socialize": 1.4},
    "homesick": {"socialize": 1.5, "rest": 1.4, "explore": 1.2},
    "adventurous": {"explore": 2.0, "seek_resources": 1.4, "investigate": 1.3},
    "wistful": {"rest": 1.4, "socialize": 1.3, "explore": 1.2},
    "free": {"explore": 1.8, "socialize": 1.4, "advance_goal": 1.2},
    "determined": {"advance_goal": 2.0, "confront_rival": 1.4, "help_ally": 1.2},
    "hopeful": {"advance_goal": 1.6, "help_ally": 1.5, "socialize": 1.3},
    "burdened": {"rest": 1.5, "advance_goal": 1.3, "help_ally": 1.2},
    "resolute": {"advance_goal": 1.8, "confront_rival": 1.4, "react_to_events": 1.3},
    "valiant": {"help_ally": 1.8, "confront_rival": 1.5, "advance_goal": 1.3},
    "scheming": {"seek_resources": 1.6, "advance_goal": 1.5, "investigate": 1.4},
    "paranoid": {"investigate": 1.8, "react_to_events": 1.6, "confront_rival": 1.3},
    "confident": {"advance_goal": 1.6, "socialize": 1.4, "explore": 1.3},
    "anxious": {"investigate": 1.5, "react_to_events": 1.4, "seek_resources": 1.3},
    "protective": {"help_ally": 1.9, "react_to_events": 1.6, "advance_goal": 1.2},
    "watchful": {"investigate": 1.7, "react_to_events": 1.6, "help_ally": 1.3},
    "stern": {"advance_goal": 1.5, "confront_rival": 1.4, "help_ally": 1.2},
    "alarmed": {"react_to_events": 2.0, "investigate": 1.6, "help_ally": 1.4},
    "steadfast": {"advance_goal": 1.6, "help_ally": 1.4, "confront_rival": 1.3},
}

ARCHETYPE_DECISION_BIAS = {
    "scholar": {"advance_goal": 1.4, "investigate": 1.6, "self_improve": 1.3},
    "warrior": {"confront_rival": 1.5, "help_ally": 1.4, "react_to_events": 1.3},
    "rogue": {"seek_resources": 1.6, "explore": 1.4, "investigate": 1.3},
    "mystic": {"self_improve": 1.6, "explore": 1.3, "react_to_events": 1.3},
    "leader": {"advance_goal": 1.5, "socialize": 1.4, "help_ally": 1.3},
    "sage": {"self_improve": 1.5, "help_ally": 1.4, "rest": 1.3},
    "wanderer": {"explore": 1.7, "seek_resources": 1.3, "socialize": 1.2},
    "hero": {"help_ally": 1.7, "confront_rival": 1.4, "react_to_events": 1.4},
    "deceiver": {"seek_resources": 1.5, "investigate": 1.4, "socialize": 1.3},
    "guardian": {"react_to_events": 1.5, "help_ally": 1.5, "investigate": 1.3},
}


def _reflect_on_missing_context(npc_id, recent_decisions, inst_ctx, world_ctx, fulfilled_need_types=None, outcome_ctx=None):
    if fulfilled_need_types is None:
        fulfilled_need_types = set()
    if not recent_decisions:
        return None
    if outcome_ctx and outcome_ctx.get("consecutive_rejections", 0) >= 2:
        rej_types = ", ".join(outcome_ctx.get("recent_rejected_types", set())[:3]) or "workflow"
        need_type = "pivot_strategy"
        if need_type not in fulfilled_need_types:
            return {
                "need_type": need_type,
                "priority": "high",
                "description": f"My recent {outcome_ctx['consecutive_rejections']} proposals were rejected ({rej_types}). I should coordinate with allies before proposing again.",
                "why_needed": "Repeated rejections indicate my approach needs adjustment — I need strategic context for a different approach.",
                "suggested_capability": "coalition_or_ally_review_before_proposal",
            }
    low_count = 0
    for dec in recent_decisions[-10:]:
        cat = dec.get("category", "")
        if cat in LOW_VALUE_CATEGORIES:
            low_count += 1
    low_ratio = low_count / max(len(recent_decisions[-10:]), 1)
    if low_ratio < 0.5:
        return None
    institutions = inst_ctx.get("institutions", []) if inst_ctx else []
    has_active_inst = any(i.get("status") == "active" and i.get("active_workflows", 0) > 0 for i in institutions)
    is_member = any(npc_id in i.get("members", []) for i in institutions)
    if has_active_inst and not is_member:
        need_type = "institution_support"
        if need_type in fulfilled_need_types:
            pass
        else:
            return {
                "need_type": need_type,
                "priority": "high",
                "description": "Active institution workflows exist but I have no membership or visibility into them.",
                "why_needed": "Over half my recent actions were low-value (rest/wander) — lacking institutional coordination context.",
                "suggested_capability": "institution_membership_or_observer_feed",
            }
    if has_active_inst and is_member:
        active_wfs = sum(i.get("active_workflows", 0) for i in institutions if npc_id in i.get("members", []))
        if active_wfs >= 3:
            need_type = "workflow_visibility"
            if need_type in fulfilled_need_types:
                pass
            else:
                return {
                    "need_type": need_type,
                    "priority": "high",
                    "description": f"My institution has {active_wfs} active workflows but I cannot see their progress or blockers.",
                    "why_needed": "I keep resting because I lack workflow status to act on.",
                    "suggested_capability": "npc_decision_summary_feed",
                }
        if active_wfs == 0:
            need_type = "coordination_help"
            if need_type in fulfilled_need_types:
                pass
            else:
                return {
                    "need_type": need_type,
                    "priority": "medium",
                    "description": "I am an institution member but no workflows are active despite world events.",
                    "why_needed": "Low action rate suggests I need better triggers to initiate institutional processes.",
                    "suggested_capability": "institution_trigger_context",
                }
    world_stable = all(
        world_ctx.get(k, 50) in range(30, 70)
        for k in ("stability", "morale", "resource_abundance")
        if k in world_ctx
    )
    if world_stable and low_ratio > 0.6:
        need_type = "world_state_gap"
        if need_type in fulfilled_need_types:
            pass
        else:
            return {
                "need_type": need_type,
                "priority": "medium",
                "description": "World state appears stable but I lack granular context to find productive actions.",
                "why_needed": "Stable world + high rest rate = missing decision-driving information.",
                "suggested_capability": "sector_or_faction_detail_feed",
            }
    need_type = "information_access"
    if need_type not in fulfilled_need_types:
        return {
            "need_type": need_type,
            "priority": "medium",
            "description": "I am under-acting relative to my role — I need better context about what is happening.",
            "why_needed": f"{low_count}/{len(recent_decisions[-10:])} recent actions were low-value.",
            "suggested_capability": "general_context_enrichment",
        }
    return None


def _score_decision_option(
    category,
    char_id,
    archetype,
    mood,
    has_active_goals,
    has_allies,
    has_rivals,
    recent_event_count,
    broadcast_event_count=0,
    has_active_quests=False,
    inst_ctx=None,
    need_reflection=None,
    fulfilled_need_types=None,
    affiliation=None,
    outcome_ctx=None,
):
    score = 1.0
    mood_biases = MOOD_DECISION_BIAS.get(mood, {})
    score *= mood_biases.get(category, 1.0)
    arch_biases = ARCHETYPE_DECISION_BIAS.get(archetype, {})
    score *= arch_biases.get(category, 1.0)
    if category == "advance_goal" and not has_active_goals:
        score *= 0.3
    if category == "help_ally" and not has_allies:
        score *= 0.4
    if category == "confront_rival" and not has_rivals:
        score *= 0.3
    if category == "react_to_events" and recent_event_count == 0:
        score *= 0.2
    elif category == "react_to_events" and recent_event_count > 3:
        score *= 1.3
    if category == "react_to_events" and broadcast_event_count > 0:
        score *= 1.0 + min(broadcast_event_count * 0.1, 0.5)
    try:
        from npc_autonomy import _get_redis
        _bias_r = _get_redis()
        _bias_raw = _bias_r.get(f"npc_decision_bias:{char_id}")
        if _bias_raw:
            _bias_data = json.loads(_bias_raw)
            _bias_val = _bias_data.get(category, 1.0)
            if _bias_val and _bias_val != 1.0:
                score *= _bias_val
    except Exception:
        pass

    try:
        from npc_autonomy import _get_redis
        _fmod_r = _get_redis()
        _fmod_raw = _fmod_r.get(f"npc_faction_modifier:{char_id}")
        if _fmod_raw:
            _fmod_data = json.loads(_fmod_raw)
            _fmod_val = _fmod_data.get(category, 1.0)
            if _fmod_val and float(_fmod_val) != 1.0:
                score *= float(_fmod_val)
    except Exception:
        pass

    try:
        from npc_autonomy import DIRECTIVE_KEY, DECREE_DIRECTIVE_BIAS, _is_allied_faction, _get_redis
        _dir_r = _get_redis()
        _dir_raw = _dir_r.get(DIRECTIVE_KEY)
        if _dir_raw and affiliation:
            _dir_data = json.loads(_dir_raw)
            _dir_metric = _dir_data.get("metric", "")
            _dir_faction = _dir_data.get("issuer_faction", "")
            _dir_bias_map = DECREE_DIRECTIVE_BIAS.get(_dir_metric, {})
            if _dir_faction and _dir_bias_map:
                if affiliation == _dir_faction:
                    _dir_cat_biases = _dir_bias_map.get("same_faction", {})
                elif _is_allied_faction(affiliation, _dir_faction):
                    _dir_cat_biases = _dir_bias_map.get("allied_faction", {})
                else:
                    _dir_cat_biases = _dir_bias_map.get("other_faction", {})
                _dir_mult = _dir_cat_biases.get(category, 1.0)
                if _dir_mult != 1.0:
                    score *= _dir_mult
    except Exception:
        pass

    if has_active_quests and category == "advance_goal":
        score *= 1.4
    if has_active_quests and category == "advance_goal" and score < 0.5:
        score = 0.5

    from npc_autonomy import _world_state_decision_modifier
    score *= _world_state_decision_modifier(category)

    if inst_ctx and inst_ctx.get("institutions"):
        for inst in inst_ctx["institutions"]:
            if inst.get("status") != "active":
                continue
            if inst.get("active_workflows", 0) > 0:
                if category == "advance_goal":
                    score *= 1.15
                if category == "help_ally" and char_id in inst.get("members", []):
                    score *= 1.3
                if category == "react_to_events" and inst.get("active_workflows", 0) >= 3:
                    score *= 1.1

    if category == "request_capability":
        if need_reflection:
            score *= 2.5
        else:
            score *= 0.05

    if outcome_ctx and outcome_ctx.get("total", 0) > 0:
        cons_rej = outcome_ctx.get("consecutive_rejections", 0)
        if cons_rej >= 2:
            if category == "advance_goal":
                score *= max(0.4, 1.0 - cons_rej * 0.15)
            if category in ("help_ally", "socialize"):
                score *= 1.0 + min(cons_rej * 0.15, 0.6)
        approved_count = outcome_ctx.get("approved", 0)
        if approved_count >= 2 and cons_rej == 0:
            if category == "advance_goal":
                score *= 1.0 + min(approved_count * 0.05, 0.3)

    score += random.uniform(-0.1, 0.1)
    return max(0.1, score)


def evaluate_decision_options(char_id, char_name, archetype, affiliation, mood="", fulfilled_need_types=None):
    from npc_autonomy import get_mood, get_goals, GOAL_STATUS_ACTIVE, get_relationship_summary, get_world_events, get_broadcast_events, _get_institution_context, _get_npc_outcome_ctx, DECISION_CATEGORIES
    mood = mood or get_mood(char_id)
    active_goals = get_goals(char_id, status=GOAL_STATUS_ACTIVE)
    has_active_goals = len(active_goals) > 0
    rel_summary = get_relationship_summary(char_id)
    has_allies = len(rel_summary.get("allies", [])) > 0
    has_rivals = len(rel_summary.get("rivals", [])) > 0
    recent_events = get_world_events(limit=5)
    recent_event_count = len(recent_events)
    broadcast_events = []
    try:
        broadcast_events = get_broadcast_events(char_id, affiliation, limit=10)
    except Exception:
        logger.debug(
            f"Broadcast events retrieval failed for {char_id}; proceeding without broadcast context"
        )
    broadcast_event_count = len(broadcast_events)

    has_active_quests = False
    try:
        from npc_autonomy import _get_redis
        _qr = _get_redis()
        _quest_data = _qr.get(f"npc_quests:active:{char_id}")
        if _quest_data:
            _quest_list = json.loads(_quest_data)
            has_active_quests = len(_quest_list) > 0
    except Exception:
        pass

    inst_ctx = _get_institution_context()
    outcome_ctx = _get_npc_outcome_ctx(char_id)

    need_reflection = None
    try:
        from npc_autonomy import _get_redis
        _nr = _get_redis()
        _recent_raw = _nr.lrange(f"npc_decisions:{char_id}", 0, 9)
        _recent_decisions = []
        for _rd in _recent_raw:
            try:
                _recent_decisions.append(json.loads(_rd))
            except (json.JSONDecodeError, TypeError):
                pass
        _world_raw = _nr.get("world_state")
        _world_ctx = json.loads(_world_raw) if _world_raw else {}
        need_reflection = _reflect_on_missing_context(
            char_id, _recent_decisions, inst_ctx, _world_ctx,
            fulfilled_need_types=fulfilled_need_types,
            outcome_ctx=outcome_ctx,
        )
    except Exception:
        pass

    options = []
    for cat in DECISION_CATEGORIES:
        score = _score_decision_option(
            cat,
            char_id,
            archetype,
            mood,
            has_active_goals,
            has_allies,
            has_rivals,
            recent_event_count,
            broadcast_event_count,
            has_active_quests=has_active_quests,
            inst_ctx=inst_ctx,
            need_reflection=need_reflection,
            fulfilled_need_types=fulfilled_need_types,
            affiliation=affiliation,
            outcome_ctx=outcome_ctx,
        )
        reasons = []
        mood_biases = MOOD_DECISION_BIAS.get(mood, {})
        if mood_biases.get(cat, 1.0) > 1.2:
            reasons.append("feeling " + mood)
        arch_biases = ARCHETYPE_DECISION_BIAS.get(archetype, {})
        if arch_biases.get(cat, 1.0) > 1.2:
            reasons.append(archetype + " nature")
        if cat == "advance_goal" and has_active_goals:
            top_goal = active_goals[0]
            reasons.append(
                "pursuing: " + top_goal.get("description", "unknown goal")[:50]
            )
        if cat == "help_ally" and has_allies:
            ally = rel_summary["allies"][0].get("char_id", "an ally")
            reasons.append("ally: " + ally)
        if cat == "confront_rival" and has_rivals:
            rival = rel_summary["rivals"][0].get("char_id", "a rival")
            reasons.append("rival: " + rival)
        if cat == "react_to_events" and recent_event_count > 0:
            reasons.append(str(recent_event_count) + " recent events")
        if inst_ctx and inst_ctx.get("institutions"):
            for inst in inst_ctx["institutions"]:
                if inst.get("status") != "active":
                    continue
                if inst.get("active_workflows", 0) > 0:
                    if cat == "advance_goal" and char_id in inst.get("members", []):
                        reasons.append(inst["name"] + " duty")
                    if cat == "react_to_events" and inst.get("active_workflows", 0) >= 3:
                        reasons.append(inst["name"] + " busy")
        if cat == "request_capability" and need_reflection:
            reasons.append("missing: " + need_reflection.get("need_type", "context"))
        if cat == "request_capability" and fulfilled_need_types:
            nr_type = need_reflection.get("need_type", "") if need_reflection else ""
            if nr_type in fulfilled_need_types:
                score *= 0.1
                reasons.append("already_fulfilled: " + nr_type)
            else:
                for ft in fulfilled_need_types:
                    if ft in ("information_access", "world_state_gap", "context_enrichment"):
                        score *= 0.5
                        reasons.append("recent_fulfillment")
                        break
        if outcome_ctx and outcome_ctx.get("total", 0) > 0:
            cons_rej = outcome_ctx.get("consecutive_rejections", 0)
            if cons_rej >= 2 and cat == "advance_goal":
                reasons.append(f"rejection_cautious({cons_rej})")
            if cons_rej >= 2 and cat in ("help_ally", "socialize"):
                reasons.append("pivoting_to_collaborate")
            if outcome_ctx.get("approved", 0) >= 2 and cons_rej == 0 and cat == "advance_goal":
                reasons.append("approval_confidence")
        options.append({"category": cat, "score": round(score, 2), "reasons": reasons})

    options.sort(key=lambda x: x["score"], reverse=True)
    return options, need_reflection
