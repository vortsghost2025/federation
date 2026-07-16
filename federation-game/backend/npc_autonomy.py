"""
FEDERATION GAME - NPC Autonomy Engine
Phase 3: Autonomous NPC actions between player visits
Phase 6a: Decision engine - contextual NPC decision-making

NPCs live their own lives when players are away:
- Generate thoughts (periodic internal monologue)
- Form opinions about players (sentiment tracking)
- Take autonomous actions (world-impacting decisions)
- Develop relationships that evolve over time
- Create rumors/news that spread between NPCs
- Make contextual decisions based on goals, mood, relationships, world state

Redis keys:
npc_thoughts:{char_id} - ZSET (score=timestamp) of recent thoughts
npc_opinion:{char_id}:{player_id} - HASH of opinion data
npc_actions:{char_id} - ZSET (score=timestamp) of recent actions
npc_relationships:{char_id} - HASH of relationship values with other NPCs
npc_world_events - ZSET (score=timestamp) of global events
npc_mood:{char_id} - STRING current mood state
npc_last_active:{char_id} - STRING timestamp of last activity
npc_decisions:{char_id} - ZSET (score=timestamp) of recent decisions
npc:needs - LIST of structured need records (councilor capability requests)
npc:needs:{npc_id}:last - STRING timestamp of last need filed (dedup throttle)
"""

import os
import json
import time
import random
import hashlib
import urllib.request
import urllib.error
import concurrent.futures
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import redis
from faction_dynamics import (
    compute_faction_dynamics,
    compute_faction_stances,
    store_faction_dynamics,
)
from institutions import get_npc_outcome_history
from npc_activity_logger import log_npc_activity
from npc_event_log import log_decision_event
from npc_world import (
    WORLD_CONDITIONS,
    WORLD_STATE_KEY,
    WORLD_STATE_HISTORY_KEY,
    MAX_WORLD_HISTORY,
    WORLD_STATE_TTL,
    get_world_state,
    get_world_condition,
    set_world_condition,
    update_world_state,
    get_world_state_history,
    _world_state_decision_modifier,
)
import logging
from npc_decree import (
    DECISION_EVENT_MAP,
    MAX_BROADCAST_EVENTS,
    BROADCAST_TTL,
    get_decision_log,
    broadcast_decision_event,
    get_broadcast_events,
    get_relevant_events_for_npc,
    DECREES_ALLOWED_NPCS,
    DECREES_ALLOWED_METRICS,
    DECREE_MAX_DELTA,
    DECREE_COOLDOWN_SECONDS,
    DECREE_HISTORY_KEY,
    DECREE_COOLDOWN_KEY,
    DECREE_MAX_HISTORY,
    DECREE_HISTORY_TTL,
    DIRECTIVE_KEY,
    DIRECTIVE_TTL,
    DECREE_DIRECTIVE_BIAS,
    COUNCILOR_AFFILIATIONS,
    FACTION_ALLIANCES,
    _is_allied_faction,
    _write_decree_directive,
    issue_decree,
    get_decree_history,
    DECREE_THRESHOLDS,
    COUNCILOR_NAMES,
    evaluate_decree_opportunity,
)
from npc_reflection import (
    LOW_VALUE_CATEGORIES,
    MOOD_DECISION_BIAS,
    ARCHETYPE_DECISION_BIAS,
    _reflect_on_missing_context,
    _score_decision_option,
    evaluate_decision_options,
)
from npc_thoughts import (
    SIGNIFICANCE_PRIORITY,
    LOW_SIGNIFICANCE_CUTOFF,
    MEDIUM_SIG_LLM_PROBABILITY,
    MAX_THOUGHTS,
    THOUGHT_TTL,
    THOUGHT_CACHE_TTL,
    THOUGHT_CACHE_PREFIX,
    _cache_stats,
    _cache_stats_lock,
    _compute_thought_cache_key,
    _get_world_events_bucket,
    get_thought_cache_stats,
    _clean_llm_output,
    _is_leaked_prompt,
    _call_llm,
    generate_thought,
    LLM_USE_NIM,
)
from npc_interactions import (
    NPC_INTERACTION_TYPES,
    INTERACTION_DELTAS,
    update_npc_relationship,
    get_npc_relationships,
    _generate_dialogue,
    generate_npc_interaction,
    get_relationship_summary,
)

from npc_actions import (
    ACTION_TEMPLATES,
    FILL_VALUES,
    generate_action,
    get_recent_actions,
    get_world_events,
)

from npc_goals import (
    GOAL_TYPES,
    GOAL_STATUS_ACTIVE,
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_ABANDONED,
    MAX_GOALS_PER_NPC,
    GOAL_TTL,
    GOAL_PROGRESS_PER_ACTION,
    GOAL_PROGRESS_VARIANCE,
    GOAL_ACTION_TEMPLATES,
    generate_goal,
    _get_goals_raw,
    get_goals,
    advance_goal,
    set_goal_status,
    generate_goal_driven_action,
)
from npc_opinions import (
    OPINION_TTL,
    ARCHETYPE_MOODS,
    update_opinion,
    get_opinion,
    update_mood,
    get_mood,
)

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"

# NPCs with their own dedicated long-lived agent runtime should not also
# receive deterministic autonomy decisions here, or they end up with split
# ownership of cognition/state.
EXTERNAL_AGENT_NPCS = {
    cid.strip()
    for cid in os.environ.get("EXTERNAL_AGENT_NPCS", "char_001,char_306").split(",")
    if cid.strip()
}

OPINION_TTL = 86400 * 14
MAX_WORLD_EVENTS = 50

from npc_needs import (  # [2.1] extracted
    file_npc_need,
    get_open_needs,
    consume_system_notifications,
    ALLOWED_NEED_TYPES,
    FORBIDDEN_NEED_TYPES,
    NPC_NEEDS_KEY,
    NPC_NEEDS_MAX,
    NPC_NEEDS_THROTTLE_SECONDS,
)


# LLM priority: NVIDIA NIM (free, fast) -> OpenRouter (free, fallback)

# --- THOUGHT SYSTEM + LLM CALLS --- extracted to npc_thoughts.py [3] ---

_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    return _redis_client


def get_recent_thoughts(char_id: str, limit: int = 3) -> List[Dict]:
    r = _get_redis()
    key = f"npc_thoughts:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    thoughts = []
    for item in raw:
        try:
            thoughts.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return thoughts


# --- OPINIONS ---

# --- OPINIONS + MOODS --- extracted to npc_opinions.py [4] ---
# --- AUTONOMOUS ACTIONS ---
# --- AUTONOMOUS ACTIONS --- extracted to npc_actions.py [5] ---


# --- NPC-TO-NPC RELATIONSHIPS + INTERACTIONS --- extracted to npc_interactions.py [6] ---


# --- PARALLEL NPC PROCESSING (P25b-4) ---
# Max concurrent NPC processing threads. 16 provides better parallelism
# for ~39 NPCs (reduces batches from 5→3). Ollama lane gates actual
# concurrent LLM calls to OLLAMA_MAX_ACTIVE=2, so higher thread count
# just means more NPCs can wait/progress in parallel without blocking
# each other on non-LLM work (mood, decisions, Redis writes).
_NPC_PARALLEL_WORKERS = 16

# Per-tick LLM call budget: caps total LLM calls across all NPCs in one tick.
# With ~39 NPCs, ~7 of 10 categories attempt LLM, ~40-60% cache hits:
#   39 NPCs × 0.7 LLM-worthy × 0.5 cache-miss = ~14 LLM calls per tick.
# Budget of 20 gives headroom for cache misses while preventing runaway
# LLM spending if cache is cold (first tick after restart).
_TICK_LLM_BUDGET = 20
_tick_llm_calls = 0
_tick_llm_lock = threading.Lock()


def _check_tick_llm_budget() -> bool:
    """Check if the per-tick LLM budget has remaining capacity. Thread-safe."""
    global _tick_llm_calls
    with _tick_llm_lock:
        if _tick_llm_calls >= _TICK_LLM_BUDGET:
            return False
        _tick_llm_calls += 1
        return True


def _reset_tick_llm_budget() -> None:
    """Reset the per-tick LLM budget at the start of each simulation tick."""
    global _tick_llm_calls
    with _tick_llm_lock:
        _tick_llm_calls = 0


def _process_single_npc(npc: Dict) -> Dict[str, Any]:
    """Process a single NPC through the full autonomy pipeline.

    Extracted from simulation_tick() to enable parallel execution via
    ThreadPoolExecutor. Each call is independent — Redis writes use
    per-NPC keys, and _call_llm uses _run_async() internally which
    is thread-safe.
    """
    char_id = npc.get("char_id") or npc.get("id", "")
    char_name = npc.get("name", "Unknown")
    archetype = npc.get("archetype") or npc.get("personality_type", "scholar")
    affiliation = npc.get("affiliation", "independent")
    title = npc.get("title", "")
    description = npc.get("description", "")

    npc_result: Dict[str, Any] = {
        "thoughts": [],
        "actions": [],
        "moods": [],
        "opinions": [],
        "decisions": [],
        "errors": [],
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
            # Significance gate: prioritize LLM calls for meaningful moments
            category = decision.get("category", "")
            sig = SIGNIFICANCE_PRIORITY.get(category, "medium")
        if category in (
            "advance_goal",
            "investigate",
            "seek_resources",
            "self_improve",
            "explore",
        ):
            thought = generate_thought(
                char_id,
                char_name,
                archetype,
                affiliation,
                title,
                description,
                mood=new_mood,
                significance=sig,
                decision_category=category,
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
                char_id,
                char_name,
                archetype,
                affiliation,
                title,
                description,
                mood=new_mood,
                significance=sig,
                decision_category=category,
            )
            if thought:
                npc_result["thoughts"].append(thought)
        elif category == "rest":
            thought = generate_thought(
                char_id,
                char_name,
                archetype,
                affiliation,
                title,
                description,
                mood=new_mood,
                significance=sig,
                decision_category=category,
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
                    char_id,
                    char_name,
                    archetype,
                    affiliation,
                    title,
                    description,
                    mood=new_mood,
                    significance=sig,
                    decision_category=category,
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
                opinion = update_opinion(char_id, player_id, shift_type)
                npc_result["opinions"].append(
                    {"char_id": char_id, "player_id": player_id, "opinion": opinion}
                )
        r.set(f"npc_last_active:{char_id}", str(int(time.time())), ex=86400 * 7)
    except Exception as e:
        npc_result["errors"].append({"char_id": char_id, "error": str(e)})

    return npc_result


def simulation_tick(npc_list: List[Dict]) -> Dict[str, Any]:
    results = {
        "thoughts": [],
        "actions": [],
        "moods": [],
        "opinions": [],
        "interactions": [],
        "decisions": [],
        "errors": [],
    }

    # --- Reset per-tick LLM budget ---
    _reset_tick_llm_budget()

    # --- Parallel NPC processing (P25b-4) ---
    # Process all NPCs concurrently using ThreadPoolExecutor.
    # Each NPC is independent — Redis writes use per-NPC keys,
    # and _call_llm() uses _run_async() which is thread-safe.
    tick_start = time.time()
    npc_results: List[Dict[str, Any]] = []
    active_npc_list = [
        npc for npc in npc_list if (npc.get("char_id") or npc.get("id", "")) not in EXTERNAL_AGENT_NPCS
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

    # Merge per-NPC results into aggregate results
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
        len(active_npc_list),
        parallel_elapsed,
        _NPC_PARALLEL_WORKERS,
        llm_used,
        _TICK_LLM_BUDGET,
        cache_stats["hits"],
        cache_stats["misses"],
        hit_rate,
        cache_stats["stores"],
    )
    # Reset per-tick cache stats so next log line shows only that tick's data
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
    # --- Faction dynamics only (NO world_state hash writes) ---
    # world_state writes are now handled exclusively by simulation_engine.py
    # which applies per-decision effects instead of this coarse aggregate formula.
    # The old update_world_state() was overwriting simulation_engine's nuanced
    # values with destructive aggregate calculations every tick (double-write conflict).
    # Faction dynamics computation is preserved here since it's valuable data.
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



# --- NPC GOALS SYSTEM + GOAL-DRIVEN ACTIONS --- extracted to npc_goals.py [7] ---

# --- PLAYER ABSENCE DETECTION ---


def get_absence_report(char_id: str, player_id: str) -> Dict[str, Any]:
    r = _get_redis()
    thoughts = get_recent_thoughts(char_id, limit=3)
    actions = get_recent_actions(char_id, limit=3)
    opinion = get_opinion(char_id, player_id)
    mood = get_mood(char_id)
    last_active = r.get(f"npc_last_active:{char_id}")

    return {
        "char_id": char_id,
        "player_id": player_id,
        "mood": mood,
        "opinion": opinion,
        "recent_thoughts": thoughts,
        "recent_actions": actions,
        "last_active": last_active,
    }


# --- WORLD STATE SYSTEM — extracted to npc_world.py [2.2] ---


# --- NPC DECISION ENGINE (Phase 6a) ---

DECISION_CATEGORIES = [
    "advance_goal",
    "socialize",
    "investigate",
    "rest",
    "react_to_events",
    "seek_resources",
    "self_improve",
    "confront_rival",
    "help_ally",
    "explore",
    "request_capability",
]


def _get_institution_context():
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
    try:
        _r = _get_redis()
        return get_npc_outcome_history(_r, npc_id)
    except Exception:
        return {"approved": 0, "rejected": 0, "total": 0, "consecutive_rejections": 0, "recent_rejected_types": set(), "recent": []}



# --- REFLECTION + SCORING --- extracted to npc_reflection.py [2.4] ---
def make_decision(char_id, char_name, archetype, affiliation, mood=""):
    _decision_start = time.perf_counter()
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
        target_faction = None  # track the rival's faction
        if rel:
            worst_rival = min(rel.items(), key=lambda x: x[1])
            # Look up the rival's faction
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
                {
                    "char_id": worst_rival[0],
                    "name": worst_rival[0],
                    "id": worst_rival[0],
                },
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
    # Attach target_faction for confront_rival decisions
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

    # ── Decision-loop metrics (no LLM; pure observability) ──
    try:
        from routes.metrics import _decision_total, _decision_latency
        _decision_total.labels(category=category).inc()
        _decision_latency.observe(time.perf_counter() - _decision_start)
    except Exception:
        pass

    return decision


def get_decision_log(char_id, limit=5):
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


# --- PHASE 6C: NPC EVENT BROADCASTING ---

# --- PHASE 6C + COUNCILOR DECREES --- extracted to npc_decree.py [2.3] ---
