import os
import json
import time
import random
import concurrent.futures
import threading
import logging
from typing import Dict, List, Any


logger = logging.getLogger(__name__)


_NPC_PARALLEL_WORKERS = 16
_TICK_LLM_BUDGET = 20
_tick_llm_calls = 0
_tick_llm_lock = threading.Lock()


EXTERNAL_AGENT_NPCS = {
    cid.strip()
    for cid in os.environ.get("EXTERNAL_AGENT_NPCS", "char_001,char_306").split(",")
    if cid.strip()
}


def _check_tick_llm_budget() -> bool:
    global _tick_llm_calls
    with _tick_llm_lock:
        if _tick_llm_calls >= _TICK_LLM_BUDGET:
            return False
        _tick_llm_calls += 1
        return True


def _reset_tick_llm_budget() -> None:
    global _tick_llm_calls
    with _tick_llm_lock:
        _tick_llm_calls = 0


def _process_single_npc(npc: Dict) -> Dict[str, Any]:
    from npc_activity_logger import log_npc_activity
    from npc_autonomy import (
        _get_redis, update_mood, make_decision,
        broadcast_decision_event,
        SIGNIFICANCE_PRIORITY, generate_thought, generate_action, update_opinion,
    )

    char_id = npc.get("char_id") or npc.get("id", "")
    char_name = npc.get("name", "Unknown")
    archetype = npc.get("archetype") or npc.get("personality_type", "scholar")
    affiliation = npc.get("affiliation", "independent")
    title = npc.get("title", "")
    description = npc.get("description", "")

    npc_result: Dict[str, Any] = {
        "thoughts": [], "actions": [], "moods": [],
        "opinions": [], "decisions": [], "errors": [],
    }

    if char_id in EXTERNAL_AGENT_NPCS:
        logger.debug("Skipping npc_autonomy ownership for external-agent NPC %s", char_id)
        return npc_result

    try:
        new_mood = update_mood(char_id, archetype)
        npc_result["moods"].append({"char_id": char_id, "mood": new_mood})
        decision = make_decision(
            char_id, char_name, archetype, affiliation, mood=new_mood
        )
        if decision:
            npc_result["decisions"].append(decision)
            try:
                broadcast_decision_event(decision, affiliation)
            except Exception:
                logger.debug("Decision broadcast failed for NPC decision event")
            log_npc_activity(char_id, "interaction", {
                "category": decision.get("category", ""),
                "description": decision.get("description", ""),
                "affiliation": affiliation,
            })
            category = decision.get("category", "")
            sig = SIGNIFICANCE_PRIORITY.get(category, "medium")
        if category in (
            "advance_goal", "investigate", "seek_resources",
            "self_improve", "explore",
        ):
            thought = generate_thought(
                char_id, char_name, archetype, affiliation,
                title, description, mood=new_mood,
                significance=sig, decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
            action = generate_action(
                char_id, char_name, archetype, affiliation, mood=new_mood
            )
            if action:
                npc_result["actions"].append(action)
        elif category in ("socialize", "help_ally", "confront_rival"):
            thought = generate_thought(
                char_id, char_name, archetype, affiliation,
                title, description, mood=new_mood,
                significance=sig, decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
        elif category == "rest":
            thought = generate_thought(
                char_id, char_name, archetype, affiliation,
                title, description, mood=new_mood,
                significance=sig, decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
        elif category == "react_to_events":
            action = generate_action(
                char_id, char_name, archetype, affiliation, mood=new_mood
            )
            if action:
                npc_result["actions"].append(action)
        else:
            if random.random() < 0.5:
                thought = generate_thought(
                    char_id, char_name, archetype, affiliation,
                    title, description, mood=new_mood,
                    significance=sig, decision_category=category,
                )
                if thought:
                    npc_result["thoughts"].append(thought)
        r = _get_redis()
        opinion_keys = list(r.scan_iter(f"npc_opinion:{char_id}:*"))
        for okey in opinion_keys[:2]:
            if random.random() < 0.3:
                player_id = okey.split(":")[-1]
                shift_type = random.choice(
                    ["friendly", "neutral", "neutral", "helpful"]
                )
                opinion_res = update_opinion(char_id, player_id, shift_type)
                npc_result["opinions"].append(
                    {"char_id": char_id, "player_id": player_id, "opinion": opinion_res}
                )
        r.set(f"npc_last_active:{char_id}", str(int(time.time())), ex=86400 * 7)
    except Exception as e:
        npc_result["errors"].append({"char_id": char_id, "error": str(e)})

    return npc_result


def simulation_tick(npc_list: List[Dict]) -> Dict[str, Any]:
    from npc_autonomy import (
        _get_redis, get_thought_cache_stats, _cache_stats_lock, _cache_stats,
        generate_npc_interaction, get_broadcast_events,
    )
    from faction_dynamics import (
        compute_faction_dynamics, compute_faction_stances, store_faction_dynamics,
    )

    results = {
        "thoughts": [], "actions": [], "moods": [], "opinions": [],
        "interactions": [], "decisions": [], "errors": [],
    }

    _reset_tick_llm_budget()
    tick_start = time.time()
    npc_results: List[Dict[str, Any]] = []
    active_npc_list = [
        npc for npc in npc_list
        if (npc.get("char_id") or npc.get("id", "")) not in EXTERNAL_AGENT_NPCS
    ]

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=_NPC_PARALLEL_WORKERS
    ) as executor:
        future_to_npc = {
            executor.submit(_process_single_npc, npc): npc for npc in active_npc_list
        }
        for future in concurrent.futures.as_completed(future_to_npc):
            npc = future_to_npc[future]
            try:
                npc_result = future.result(timeout=45)
                npc_results.append(npc_result)
            except Exception as exc:
                char_id = npc.get("char_id") or npc.get("id", "unknown")
                logger.warning("NPC %s parallel processing failed: %s", char_id, exc)
                results["errors"].append(
                    {"char_id": char_id, "error": f"parallel processing failed: {exc}"}
                )

    for nr in npc_results:
        for key in ("thoughts", "actions", "moods", "opinions", "decisions", "errors"):
            if nr.get(key):
                results[key].extend(nr[key])

    parallel_elapsed = time.time() - tick_start
    cache_stats = get_thought_cache_stats()
    total_cache_ops = cache_stats["hits"] + cache_stats["misses"]
    hit_rate = (
        (cache_stats["hits"] / total_cache_ops * 100) if total_cache_ops > 0 else 0.0
    )
    with _tick_llm_lock:
        llm_used = _tick_llm_calls
    logger.info(
        "Parallel NPC processing: %d NPCs in %.1fs (%d workers) | LLM budget: %d/%d | thought cache: %d hits/%d misses (%.0f%% hit rate, %d stored)",
        len(active_npc_list), parallel_elapsed, _NPC_PARALLEL_WORKERS,
        llm_used, _TICK_LLM_BUDGET,
        cache_stats["hits"], cache_stats["misses"], hit_rate, cache_stats["stores"],
    )
    with _cache_stats_lock:
        _cache_stats["hits"] = 0
        _cache_stats["misses"] = 0
        _cache_stats["stores"] = 0

    if len(active_npc_list) >= 2:
        num_interactions = random.randint(1, min(3, len(active_npc_list) // 2))
        for _ in range(num_interactions):
            pair = random.sample(active_npc_list, 2)
            try:
                event = generate_npc_interaction(pair[0], pair[1])
                if event:
                    results["interactions"].append(event)
            except Exception as e:
                results["errors"].append({"error": f"interaction failed: {str(e)}"})

    try:
        _fd_events = get_broadcast_events(limit=50)
        _fd = compute_faction_dynamics(
            npc_list, results.get("decisions", []), _fd_events
        )
        _fs = compute_faction_stances(_fd, _fd_events)
        store_faction_dynamics(_fd, _fs)
        results["faction_dynamics"] = {
            f: v["cohesion"] for f, v in _fd.items() if v.get("member_count", 0) > 0
        }
    except Exception as e:
        results["errors"].append({"error": f"faction dynamics failed: {str(e)}"})

    return results
