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
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import redis
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
# --- NPC GOALS SYSTEM + GOAL-DRIVEN ACTIONS --- extracted to npc_goals.py [7] ---

from npc_simulation import (  # [8] extracted
    simulation_tick,
    _check_tick_llm_budget,
    _reset_tick_llm_budget,
    EXTERNAL_AGENT_NPCS,
)


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


from npc_decisions import (  # [9] extracted
    DECISION_CATEGORIES,
    DECISION_DESCRIPTIONS,
    MAX_DECISIONS,
    DECISION_TTL,
    _get_institution_context,
    _get_npc_outcome_ctx,
    make_decision,
    get_decision_log,
)

# --- PHASE 6C: NPC EVENT BROADCASTING ---

# --- PHASE 6C + COUNCILOR DECREES --- extracted to npc_decree.py [2.3] ---
