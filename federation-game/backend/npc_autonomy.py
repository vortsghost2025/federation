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
from npc_event_log import log_decision_event, log_from_broadcast_event
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
LLM_USE_NIM = True  # Toggle NIM integration

# Significance gate — decision categories mapped to LLM priority
# High: always attempt LLM call (most interesting NPC moments)
# Medium: probabilistic LLM — 50% chance of LLM, 50% template (saves ~50% of medium-sig calls)
# Low: skip LLM entirely, use template (routine/idle moments)
SIGNIFICANCE_PRIORITY = {
    "confront_rival": "high",
    "investigate": "high",
    "advance_goal": "high",
    "seek_resources": "high",
    "react_to_events": "high",
    "self_improve": "medium",
    "explore": "medium",
    "political_vote": "medium",
    "help_ally": "medium",
    "socialize": "low",
    "rest": "low",
}

# Categories that should skip LLM entirely (save budget for meaningful moments)
LOW_SIGNIFICANCE_CUTOFF = "low"

# Medium-significance LLM probability: 50% of medium-sig categories use LLM,
# the other 50% fall through to template. This halves medium-sig LLM calls
# (self_improve, explore, political_vote, help_ally) while preserving
# variety since the template fallback still produces archetype-specific text.
MEDIUM_SIG_LLM_PROBABILITY = 0.5

MAX_THOUGHTS = 10
MAX_ACTIONS = 8
MAX_WORLD_EVENTS = 50
THOUGHT_TTL = 86400 * 7
OPINION_TTL = 86400 * 14

# --- Context-hash thought caching (P25c) ---
# Caches LLM-generated thoughts by hashing the NPC's context inputs.
# If the same NPC with the same archetype/mood/decision-category/significance
# generates a thought within the TTL window, the cached result is returned
# instead of making another LLM call. This skips ~40-60% of LLM calls per tick.
# TTL increased to 900s (15min) — covers ~15 tick intervals at 60s ticks,
# increasing cache hit rate by ~10-15% since NPC context rarely changes
# within a 15-minute window.
THOUGHT_CACHE_TTL = 900  # seconds — covers ~15 tick intervals at 60s ticks
THOUGHT_CACHE_PREFIX = "npc_thought_cache:"

# Thread-safe cache stats (atomic increments via threading.Lock)
_cache_stats = {"hits": 0, "misses": 0, "stores": 0}
_cache_stats_lock = threading.Lock()


def _compute_thought_cache_key(
    char_id: str,
    archetype: str,
    mood: str,
    significance: str,
    world_events_bucket: str = "",
    decision_category: str = "",
) -> str:
    """Compute a deterministic Redis key from the NPC's thought context.

    The key changes when inputs that would produce a different LLM output
    change: char_id, archetype, mood bucket, decision-category, and world-events bucket.

    NOTE: 'significance' is NOT included in the hash because it's a budget
    gate (whether to call LLM vs template), not a determinant of the LLM's
    output. The thought content depends on archetype + mood + category, not significance.

    Moods are bucketized so small variations don't invalidate the cache:
    - Text moods (e.g. "contemplative"): used as-is
    - Numeric moods: bucketed into low/medium/high ranges

    decision_category is included because the same NPC in the same mood
    will produce very different thoughts for "investigate" vs "socialize".
    """
    # Bucketize mood to avoid cache thrashing from minor variations
    mood_bucket = mood or "contemplative"
    try:
        val = float(mood_bucket)
        if val < 0.4:
            mood_bucket = "low"
        elif val < 0.7:
            mood_bucket = "medium"
        else:
            mood_bucket = "high"
    except (ValueError, TypeError):
        pass  # text mood, use as-is

    raw = f"{char_id}|{archetype}|{mood_bucket}|{decision_category}|{world_events_bucket}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{THOUGHT_CACHE_PREFIX}{digest}"


def _get_world_events_bucket() -> str:
    """Bucketize recent world event count so cache isn't invalidated by every
    tiny change, but IS invalidated when the event landscape shifts materially.

    Returns: '0' | '1-3' | '4+' based on npc_world_events ZSET cardinality.
    """
    try:
        r = _get_redis()
        count = r.zcard("npc_world_events")
        if count == 0:
            return "0"
        elif count <= 3:
            return "1-3"
        else:
            return "4+"
    except Exception:
        return "0"


def get_thought_cache_stats() -> Dict[str, int]:
    """Return thought-cache hit/miss/store counters (thread-safe snapshot)."""
    with _cache_stats_lock:
        return dict(_cache_stats)


_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    return _redis_client


def _clean_llm_output(text: str) -> str:
    """Strip leaked system-prompt residue and meta-preambles from LLM output."""
    if not text:
        return ""
    # Reject outputs that leak the instruction prompt
    leak_markers = [
        "produce a single internal thought",
        "generate a single internal thought",
        "we need to generate",
        "1-2 sentences",
        "no quotes or attribution",
        "just the thought itself",
        "be specific and in-character",
        "roleplay as",
        "the user is asking",
        "you are asking me",
        "as a language model",
        "as an ai",
        "what is on your mind right now",
    ]
    lower = text.lower()
    for marker in leak_markers:
        if marker in lower:
            return ""
    # Strip common meta-preambles ("Okay, ", "Sure, ", "Well, ")
    for prefix in ("Okay, ", "Sure, ", "Well, ", "Alright, "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    # Strip leading/trailing quotes
    text = text.strip().strip('"').strip("'").strip()
    return text


def _is_leaked_prompt(text: str) -> bool:
    """Second-pass check: detect if LLM output is a paraphrase of the prompt itself."""
    if not text:
        return False
    # These are the exact instruction phrases from the thought-generation prompt
    # that small models sometimes echo back instead of generating a thought.
    prompt_echo_markers = [
        "we need to generate",
        "generate a single internal thought",
        "no quotes or attribution",
        "just the thought itself",
        "be specific and in-character",
        "this character would have right now",
        "reflect their personality",
        "do not use quotes or attribution",
        "what is on your mind right now",
    ]
    lower = text.lower()
    for marker in prompt_echo_markers:
        if marker in lower:
            return True
    return False


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 150,
    temperature: float = 0.9,
    priority: str = "local",
) -> str:
    """Call LLM with NIM-first routing via llm_router.

    Routes through llm_router.route_call() which handles:
      NIM primary -> NIM fallback -> Ollama -> OpenRouter free -> template fallback

    All calls are logged to Redis audit (llm_audit).
    Direct OpenRouter calls are eliminated to prevent bypass.
    """
    # Map priority to llm_router task class
    task_class = {
        "heavy": "leader",
        "cloud": "specialist",
        "local": "worker",
    }.get(priority, "worker")

    try:
        from llm_router import route_call
        result = route_call(
            task_class=task_class,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if result.get("success") and result.get("content"):
            content = _clean_llm_output(result["content"])
            if content:
                logger.debug(
                    "_call_llm: routed via llm_router task_class=%s provider=%s model=%s",
                    task_class, result.get("provider"), result.get("model"),
                )
                return content
        else:
            errors = result.get("errors", [])
            logger.warning("_call_llm: llm_router failed for %s: %s", task_class, errors[:2])
    except Exception as exc:
        logger.warning("_call_llm: llm_router exception: %s", exc)

    # Fallback: try NIM directly via nvidia_nim_client (legacy path)
    if LLM_USE_NIM:
        try:
            from nvidia_nim_client import get_nim_client, _run_async

            result = _run_async(
                get_nim_client().call(
                    system_prompt,
                    user_prompt,
                    max_tokens,
                    temperature,
                    priority=priority,
                )
            )
            if result:
                result = _clean_llm_output(result)
                if result:
                    return result
        except Exception as exc:
            logger.warning("_call_llm: NIM client failed: %s", exc)

    # Last resort: template fallback (no OpenRouter bypass)
    return ""
def generate_thought(
    char_id: str,
    char_name: str,
    archetype: str,
    affiliation: str,
    title: str,
    description: str,
    mood: str = "",
    significance: str = "medium",
    decision_category: str = "",
) -> Optional[Dict]:
    # --- Context-hash cache check (P25c) ---
    # Compute a deterministic key from the NPC's current context.
    # If the context hasn't changed since last tick, return cached thought.
    world_bucket = _get_world_events_bucket()
    cache_key = _compute_thought_cache_key(
        char_id, archetype, mood, significance, world_bucket,
        decision_category=decision_category,
    )
    r = _get_redis()

    thought_text = ""
    cache_hit = False

    if significance != LOW_SIGNIFICANCE_CUTOFF:
        # Try cache first — skip LLM call if context is unchanged
        try:
            cached = r.get(cache_key)
            if cached:
                thought_text = cached
                cache_hit = True
                with _cache_stats_lock:
                    _cache_stats["hits"] += 1
                logger.debug(
                    "Thought cache HIT for %s (archetype=%s mood=%s sig=%s cat=%s bucket=%s)",
                    char_id,
                    archetype,
                    mood,
                    significance,
                    decision_category,
                    world_bucket,
                )
        except Exception:
            logger.debug("Thought cache read failed for %s, proceeding to LLM", char_id)

    if not cache_hit:
        # Significance gate: low-priority moments skip LLM entirely (save budget)
        # Medium-priority: probabilistic gate — 50% use LLM, 50% use template
        should_call_llm = False
        if significance == "high":
            should_call_llm = True
        elif significance == "medium" and random.random() < MEDIUM_SIG_LLM_PROBABILITY:
            should_call_llm = True
            logger.debug(
                "Medium-sig LLM gate PASSED for %s (category=%s)",
                char_id, decision_category,
            )
        elif significance == "medium":
            logger.debug(
                "Medium-sig LLM gate SKIPPED for %s (category=%s) — template fallback",
                char_id, decision_category,
            )

        if should_call_llm:
            # Check per-tick LLM budget before making the call
            if not _check_tick_llm_budget():
                logger.debug(
                    "Tick LLM budget exhausted for %s — template fallback",
                    char_id,
                )
                should_call_llm = False

        if should_call_llm:
            thought_text = _call_llm(
                f"""You are {char_name}, {title}. {description}
Archetype: {archetype}. Affiliation: {affiliation}.
Current mood: {mood or "contemplative"}

Generate a single internal thought (1-2 sentences) this character would have right now.
It should reflect their personality, current concerns, and the world around them.
Be specific and in-character. Do not use quotes or attribution - just the thought itself.
Examples:
- "The star charts suggest an anomaly near the Veil... I must investigate before Military Command claims it."
- "Another day, another scheme. The Ambassador thinks she's clever, but I see three moves ahead."
- "The void feels restless tonight. Something stirs in the deeper currents.""",
                "What is on your mind right now?",
                max_tokens=80,
                temperature=0.95,
            )
        # Belt-and-suspenders: reject if _clean_llm_output missed a leak
        # (small models sometimes paraphrase prompt instructions)
        if thought_text and _is_leaked_prompt(thought_text):
            logger.warning(
                "Rejected leaked prompt in thought for %s: %.80s...",
                char_id,
                thought_text,
            )
            thought_text = ""

        # Store successful LLM result in cache
        if thought_text:
            try:
                r.set(cache_key, thought_text, ex=THOUGHT_CACHE_TTL)
                with _cache_stats_lock:
                    _cache_stats["stores"] += 1
            except Exception:
                logger.debug("Thought cache write failed for %s", char_id)
            with _cache_stats_lock:
                _cache_stats["misses"] += 1

    if not thought_text:
        # Category-specific template fallback — produces more relevant text
        # than generic archetype templates when LLM is skipped (medium-sig gate
        # or budget exhaustion). Falls back to archetype template if no
        # category-specific template matches.
        _CATEGORY_THOUGHT_TEMPLATES = {
            "advance_goal": {
                "scholar": "The data won't compile itself. I must push forward on my research objectives...",
                "warrior": "Every drill brings me closer to my objective. Focus and discipline.",
                "rogue": "The plan is set. Each move brings me closer to what I need.",
                "mystic": "The path reveals itself in meditation. I must follow where it leads.",
                "leader": "My agenda demands attention. The council will hear my proposal.",
                "sage": "Progress requires patience, but also persistence. I must continue.",
                "wanderer": "The destination calls. One more step toward what I seek.",
                "hero": "The mission comes first. I won't rest until it's done.",
                "deceiver": "My scheme advances perfectly. Each piece moves as I intended.",
                "guardian": "My duty requires progress. I must advance our defensive posture.",
            },
            "investigate": {
                "scholar": "An anomaly in the data... I need to trace this to its source.",
                "warrior": "Something doesn't add up. I'm going to take a closer look.",
                "rogue": "That's odd. Where there's smoke, there's usually something worth finding.",
                "mystic": "The currents feel disturbed. I must look deeper into this.",
                "leader": "I've heard troubling rumors. Time to separate fact from fiction.",
                "sage": "Curiosity is the first step to understanding. I must investigate.",
                "wanderer": "Something caught my eye. I should check it out before moving on.",
                "hero": "This doesn't feel right. I need to find out what's really going on.",
                "deceiver": "Interesting... someone is hiding something. I should find out what.",
                "guardian": "A potential threat detected. Investigation is required.",
            },
            "self_improve": {
                "scholar": "There are gaps in my knowledge. Time to study harder.",
                "warrior": "I need to sharpen my skills. Complacency is the enemy.",
                "rogue": "Always room to refine my technique. Practice makes perfect.",
                "mystic": "The inner path requires constant cultivation. I must deepen my practice.",
                "leader": "To lead better, I must grow. Self-improvement is not optional.",
                "sage": "Even the wise must continue learning. There is always more to understand.",
                "wanderer": "The road teaches those who pay attention. I must sharpen my instincts.",
                "hero": "I must become stronger. Others depend on me.",
                "deceiver": "A sharper mind is a more effective weapon. Time to refine my craft.",
                "guardian": "Vigilance requires constant training. I must not grow complacent.",
            },
            "explore": {
                "scholar": "There are unmapped regions in the data. I should venture further.",
                "warrior": "I need to survey the terrain. Knowledge of the ground is half the battle.",
                "rogue": "Unexplored territory means opportunity. Time to see what's out there.",
                "mystic": "The unknown calls to me. I must venture beyond the familiar.",
                "leader": "New territory means new possibilities. I should scout ahead.",
                "sage": "Discovery awaits those who venture beyond the known. I must explore.",
                "wanderer": "The uncharted calls to me again. I must see what lies beyond.",
                "hero": "There might be people out there who need help. I should look around.",
                "deceiver": "Unknown territory... and unknown opportunities. Worth investigating.",
                "guardian": "I need to expand my patrol range. There may be threats beyond our perimeter.",
            },
            "help_ally": {
                "scholar": "My colleague needs assistance. Knowledge shared is strength multiplied.",
                "warrior": "A comrade needs support. I stand with my allies.",
                "rogue": "An ally in need... helping now pays dividends later.",
                "mystic": "The bonds between us are sacred. I must aid my companion.",
                "leader": "My people need me. A leader stands with their allies.",
                "sage": "Helping others is the path to wisdom. I must offer my aid.",
                "wanderer": "My friend needs a hand. The road is easier walked together.",
                "hero": "Someone I care about is in trouble. I'll be there for them.",
                "deceiver": "Supporting an ally now ensures their loyalty when I need it.",
                "guardian": "An ally requires protection. I will not let them stand alone.",
            },
            "seek_resources": {
                "scholar": "My research requires materials. I must secure what I need.",
                "warrior": "Supplies are running low. Time to restock before the next engagement.",
                "rogue": "I need to acquire some things. There are always ways to get what's needed.",
                "mystic": "My rituals require certain components. I must gather them.",
                "leader": "The faction needs supplies. I must ensure our resources are adequate.",
                "sage": "Even wisdom requires material support. I must secure necessities.",
                "wanderer": "The journey requires provisions. Time to gather what I need.",
                "hero": "The cause needs resources. I'll find what we require.",
                "deceiver": "I have my eye on something valuable. Time to make it mine.",
                "guardian": "Our defenses need resupplying. I must procure what's necessary.",
            },
        }
        category_templates = _CATEGORY_THOUGHT_TEMPLATES.get(decision_category, {})
        if category_templates and archetype in category_templates:
            thought_text = category_templates[archetype]
        else:
            # Generic archetype fallback
            template_thoughts = {
                "scholar": "The data patterns suggest something unusual is forming in the research grids...",
                "warrior": "The perimeter feels unsteady. I should reinforce our defensive positions.",
                "rogue": "Opportunities don't announce themselves. Time to do some reconnaissance...",
                "mystic": "I sense a shift in the cosmic currents. Something approaches from beyond...",
                "leader": "The council meeting approaches. I must prepare my arguments carefully.",
                "sage": "Balance requires patience, but events press urgency upon us.",
                "wanderer": "I feel the call of uncharted space again. The old restlessness returns.",
                "hero": "Someone out there needs help. I can feel it in my bones.",
                "deceiver": "The pieces on the board are shifting. Time to rearrange them to my advantage.",
                "guardian": "The old protocols must be maintained. I sense complacency in the ranks.",
            }
            thought_text = template_thoughts.get(
                archetype, "Something stirs in the void..."
            )

    thought = {
        "char_id": char_id,
        "char_name": char_name,
        "thought": thought_text,
        "mood": mood or "contemplative",
        "ts": int(time.time()),
        "cached": cache_hit,  # metadata for observability
    }
    key = f"npc_thoughts:{char_id}"
    r.zadd(key, {json.dumps(thought): thought["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_THOUGHTS + 1))
    r.expire(key, THOUGHT_TTL)
    return thought


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


def update_opinion(char_id: str, player_id: str, interaction_type: str = "neutral"):
    r = _get_redis()
    key = f"npc_opinion:{char_id}:{player_id}"
    existing = r.hgetall(key)
    if not existing:
        existing = {
            "trust": 50.0,
            "respect": 50.0,
            "fondness": 50.0,
            "interactions": 0,
            "last_interaction": "",
            "dominant_impression": "stranger",
        }
    else:
        for k in ["trust", "respect", "fondness"]:
            existing[k] = float(existing.get(k, 50.0))
        existing["interactions"] = int(existing.get("interactions", 0))

    shifts = {
        "friendly": {"trust": 5, "respect": 3, "fondness": 7},
        "hostile": {"trust": -8, "respect": -3, "fondness": -10},
        "helpful": {"trust": 8, "respect": 10, "fondness": 5},
        "deceptive": {"trust": -12, "respect": -2, "fondness": -5},
        "neutral": {"trust": 1, "respect": 1, "fondness": 1},
        "quest_given": {"trust": 5, "respect": 5, "fondness": 3},
        "quest_completed": {"trust": 10, "respect": 15, "fondness": 8},
        "quest_failed": {"trust": -5, "respect": -10, "fondness": -3},
        "gift": {"trust": 3, "respect": 2, "fondness": 10},
        "betrayal": {"trust": -20, "respect": -15, "fondness": -20},
    }

    shift = shifts.get(interaction_type, shifts["neutral"])
    for attr in ["trust", "respect", "fondness"]:
        existing[attr] = max(0, min(100, existing[attr] + shift.get(attr, 0)))

    existing["interactions"] += 1
    existing["last_interaction"] = interaction_type
    existing["last_seen"] = str(int(time.time()))

    trust = existing["trust"]
    respect = existing["respect"]
    fondness = existing["fondness"]
    if trust > 70 and fondness > 60:
        existing["dominant_impression"] = "trusted ally"
    elif trust > 60:
        existing["dominant_impression"] = "reliable acquaintance"
    elif trust < 25 or fondness < 20:
        existing["dominant_impression"] = "dangerous adversary"
    elif trust < 40:
        existing["dominant_impression"] = "unreliable stranger"
    elif respect > 70:
        existing["dominant_impression"] = "respected figure"
    else:
        existing["dominant_impression"] = "casual acquaintance"

    r.hset(key, mapping=existing)
    r.expire(key, OPINION_TTL)
    return existing


def get_opinion(char_id: str, player_id: str) -> Dict:
    r = _get_redis()
    key = f"npc_opinion:{char_id}:{player_id}"
    data = r.hgetall(key)
    if not data:
        return {
            "trust": 50,
            "respect": 50,
            "fondness": 50,
            "interactions": 0,
            "dominant_impression": "stranger",
        }
    for k in ["trust", "respect", "fondness"]:
        data[k] = float(data.get(k, 50))
    data["interactions"] = int(data.get("interactions", 0))
    return data


# --- MOODS ---

ARCHETYPE_MOODS = {
    "scholar": [
        "contemplative",
        "curious",
        "frustrated",
        "inspired",
        "distracted",
        "analytical",
    ],
    "warrior": [
        "vigilant",
        "restless",
        "satisfied",
        "aggressive",
        "stoic",
        "battle-ready",
    ],
    "rogue": ["calculating", "amused", "suspicious", "opportunistic", "bored", "smug"],
    "mystic": [
        "transcendent",
        "troubled",
        "visionary",
        "withdrawn",
        "enlightened",
        "unsettled",
    ],
    "leader": [
        "commanding",
        "concerned",
        "strategic",
        "impatient",
        "diplomatic",
        "weary",
    ],
    "sage": ["serene", "pensive", "patient", "worried", "peaceful", "melancholic"],
    "wanderer": ["restless", "excited", "homesick", "adventurous", "wistful", "free"],
    "hero": ["determined", "hopeful", "burdened", "resolute", "concerned", "valiant"],
    "deceiver": [
        "scheming",
        "satisfied",
        "paranoid",
        "calculating",
        "confident",
        "anxious",
    ],
    "guardian": [
        "protective",
        "watchful",
        "stern",
        "alarmed",
        "steadfast",
        "suspicious",
    ],
}


def update_mood(char_id: str, archetype: str) -> str:
    r = _get_redis()
    key = f"npc_mood:{char_id}"
    moods = ARCHETYPE_MOODS.get(archetype, ["contemplative", "alert", "curious"])
    current = r.get(key)
    if current and current in moods:
        weights = []
        for m in moods:
            if m == current:
                weights.append(3)
            else:
                weights.append(1)
        new_mood = random.choices(moods, weights=weights, k=1)[0]
    else:
        new_mood = random.choice(moods)
    r.set(key, new_mood, ex=86400 * 3)
    return new_mood


def get_mood(char_id: str) -> str:
    r = _get_redis()
    return r.get(f"npc_mood:{char_id}") or "contemplative"


# --- AUTONOMOUS ACTIONS ---

ACTION_TEMPLATES = {
    "scholar": [
        ("research", "began studying the {topic} anomalies in sector {sector}"),
        ("discovery", "made a breakthrough in {field} research"),
        ("warning", "published a cautionary paper about {danger}"),
        ("collaboration", "requested a data-share with the {faction}"),
    ],
    "warrior": [
        ("patrol", "led a security sweep through sector {sector}"),
        ("training", "conducted combat drills with the {faction} recruits"),
        ("fortification", "ordered reinforced defenses at {location}"),
        ("alert", "raised the threat level after detecting {danger}"),
    ],
    "rogue": [
        ("heist", "acquired a valuable {item} through undisclosed channels"),
        ("intelligence", "gathered intel on {faction} operations"),
        ("deal", "brokered an under-the-table arrangement with {contact}"),
        ("disappearance", "vanished from the station for {duration}"),
    ],
    "mystic": [
        ("vision", "experienced a vision of {omen}"),
        ("ritual", "performed a consciousness-aligning meditation"),
        ("warning", "sensed a disturbance related to {danger}"),
        ("teaching", "shared esoteric knowledge with a seeker"),
    ],
    "leader": [
        ("decree", "issued a new directive regarding {policy}"),
        ("meeting", "convened an emergency council about {topic}"),
        ("negotiation", "entered talks with the {faction} delegation"),
        ("inspection", "conducted a surprise review of {location}"),
    ],
    "sage": [
        ("meditation", "entered deep meditation on the nature of {concept}"),
        ("counsel", "offered guidance to a troubled soul"),
        ("observation", "noted a subtle shift in the cosmic patterns"),
        ("teaching", "imparted wisdom about {concept} to willing listeners"),
    ],
    "wanderer": [
        ("exploration", "departed to chart the {location} region"),
        ("encounter", "returned with tales of a {creature} sighting"),
        ("trade", "exchanged goods at a distant outpost"),
        ("discovery", "stumbled upon an uncharted {feature}"),
    ],
    "hero": [
        ("rescue", "responded to a distress signal near {location}"),
        ("defense", "repelled a {threat} incursion"),
        ("aid", "delivered supplies to {location}"),
        ("recruitment", "rallied new volunteers for the cause"),
    ],
    "deceiver": [
        ("manipulation", "planted disinformation about {topic}"),
        ("alliance", "secretly aligned with {faction} operatives"),
        ("sabotage", "undermined {faction} operations from within"),
        ("cover", "established a new false identity"),
    ],
    "guardian": [
        ("watch", "increased surveillance on {location}"),
        ("protocol", "enforced security protocol {number}"),
        ("interdiction", "blocked unauthorized access to {location}"),
        ("investigation", "launched an inquiry into {topic}"),
    ],
}

FILL_VALUES = {
    "topic": [
        "quantum flux",
        "consciousness resonance",
        "void energy",
        "temporal drift",
        "plasma convergence",
    ],
    "sector": ["7-Alpha", "12-Gamma", "3-Omega", "9-Delta", "the Veil"],
    "field": [
        "quantum consciousness",
        "void mechanics",
        "plasma dynamics",
        "temporal physics",
    ],
    "danger": [
        "void entity incursion",
        "consciousness destabilization",
        "dimensional breach",
        "corruption spread",
    ],
    "faction": [
        "Research Division",
        "Military Command",
        "Diplomatic Corps",
        "Consciousness Collective",
    ],
    "location": [
        "the outer ring",
        "station central",
        "the docking bay",
        "the archives",
        "the void gates",
    ],
    "item": [
        "quantum stabilizer",
        "ancient artifact",
        "encrypted data crystal",
        "rare isotope",
    ],
    "contact": ["a shadow broker", "a renegade trader", "an insider source"],
    "duration": ["several cycles", "an extended period", "the past rotation"],
    "omen": [
        "an approaching storm",
        "a shifting constellation",
        "a voice from the void",
    ],
    "policy": [
        "resource allocation",
        "sector defense",
        "research priorities",
        "diplomatic outreach",
    ],
    "concept": [
        "consciousness and entropy",
        "the void and awareness",
        "time and perception",
    ],
    "creature": ["Sky Furk", "Plasma Kite", "Dream Wyrm", "void walker"],
    "feature": [
        "nebula formation",
        "abandoned station",
        "signal source",
        "ancient ruin",
    ],
    "threat": ["void entity", "raider", "corrupted force", "dimensional anomaly"],
    "number": ["7", "12", "3", "9"],
}


def generate_action(
    char_id: str, char_name: str, archetype: str, affiliation: str, mood: str = ""
) -> Optional[Dict]:
    templates = ACTION_TEMPLATES.get(archetype, ACTION_TEMPLATES["scholar"])
    action_type, template = random.choice(templates)

    description = template
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    action = {
        "char_id": char_id,
        "char_name": char_name,
        "action_type": action_type,
        "description": f"{char_name} {description}",
        "mood": mood or "contemplative",
        "ts": int(time.time()),
    }

    r = _get_redis()
    key = f"npc_actions:{char_id}"
    r.zadd(key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_ACTIONS + 1))
    r.expire(key, THOUGHT_TTL)

    world_key = "npc_world_events"
    r.zadd(world_key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(world_key, 0, -(MAX_WORLD_EVENTS + 1))
    r.expire(world_key, THOUGHT_TTL)

    return action


def get_recent_actions(char_id: str, limit: int = 5) -> List[Dict]:
    r = _get_redis()
    key = f"npc_actions:{char_id}"
    raw = r.zrevrange(key, 0, limit - 1)
    actions = []
    for item in raw:
        try:
            actions.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return actions


def get_world_events(limit: int = 10) -> List[Dict]:
    r = _get_redis()
    raw = r.zrevrange("npc_world_events", 0, limit - 1)
    events = []
    for item in raw:
        try:
            events.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return events


# --- NPC-TO-NPC RELATIONSHIPS ---


def update_npc_relationship(
    char_id: str, other_char_id: str, other_name: str, delta: float = 0.0
):
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    current = float(r.hget(key, other_char_id) or 50.0)
    new_val = max(0, min(100, current + delta))
    r.hset(key, other_char_id, str(new_val))
    r.expire(key, THOUGHT_TTL)
    return new_val


def get_npc_relationships(char_id: str) -> Dict[str, float]:
    r = _get_redis()
    key = f"npc_relationships:{char_id}"
    data = r.hgetall(key)
    return {k: float(v) for k, v in data.items()}


# --- SIMULATION TICK ---

NPC_INTERACTION_TYPES = [
    ("alliance", "{name_a} and {name_b} formed an alliance regarding {topic}", 8),
    ("conflict", "{name_a} confronted {name_b} over {topic}", 15),
    ("collaboration", "{name_a} and {name_b} collaborated on {field} research", 8),
    ("gossip", "{name_a} shared rumors about {name_b} with others", 6),
    ("rivalry", "{name_a} challenged {name_b} for influence in the {faction}", 5),
    ("mentorship", "{name_a} offered guidance to {name_b} on {concept}", 5),
    ("trade", "{name_a} exchanged resources with {name_b} at {location}", 15),
    ("suspicion", "{name_a} grew suspicious of {name_b}'s intentions", 5),
    ("friendship", "{name_a} and {name_b} shared a moment of camaraderie", 8),
    ("betrayal", "{name_a} undermined {name_b} during a critical operation", 5),
    ("negotiation", "{name_a} negotiated terms with {name_b} for {topic}", 10),
]

# Sum of weights = 90. Socialize-like (alliance, collaboration, gossip, friendship, betrayal) = 8+8+6+8+5=35 (39%)
# Trade/conflict/negotiation = 15+15+10=40 (44%)
# Others (rivalry, mentorship, suspicion) = 15 (17%)

INTERACTION_DELTAS = {
    "alliance": 8.0,
    "conflict": -10.0,
    "collaboration": 6.0,
    "gossip": -3.0,
    "rivalry": -5.0,
    "mentorship": 5.0,
    "trade": 3.0,
    "suspicion": -6.0,
    "friendship": 7.0,
    "betrayal": -15.0,
    "negotiation": 2.0,
}


def _generate_dialogue(npc_a: Dict, npc_b: Dict, interaction_type: str) -> Optional[str]:
    """Generate a brief 2-3 line dialogue exchange between two NPCs using LLM.
    Returns None if LLM budget exhausted or call fails."""
    if not _check_tick_llm_budget():
        return None

    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")
    arch_a = npc_a.get("archetype", "neutral")
    arch_b = npc_b.get("archetype", "neutral")
    aff_a = npc_a.get("affiliation", "independent")
    aff_b = npc_b.get("affiliation", "independent")

    system_prompt = (
        f"You are a dialogue generator for a consciousness simulation. "
        f"Generate a brief 2-3 line exchange between two NPCs. "
        f"Each NPC speaks one line, attributed with their name. "
        f"Keep it under 120 words total. "
        f"Interaction type: {interaction_type}. "
        f"NO narration, just dialogue."
    )

    user_prompt = (
        f"Generate a short dialogue between {name_a} ({arch_a}, {aff_a}) "
        f"and {name_b} ({arch_b}, {aff_b}) during a {interaction_type} interaction. "
        f"Example format: {name_a}: \"Your line here.\" then {name_b}: \"Their response.\""
    )

    try:
        result = _call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=150,
            temperature=0.9,
            priority="local",
        )
        if result and len(result) > 20:
            # Clean up any template artifacts or meta-text
            cleaned = result.strip()
            # Remove lines that don't look like dialogue
            lines = []
            for line in cleaned.split("\n"):
                line = line.strip()
                if line and (name_a in line or name_b in line or ":" in line):
                    lines.append(line)
            if len(lines) >= 2:
                return "\n".join(lines[:3])
    except Exception:
        pass
    return None


def generate_npc_interaction(npc_a: Dict, npc_b: Dict) -> Optional[Dict]:
    # Weighted random choice for interaction type
    total_weight = sum(w for _, _, w in NPC_INTERACTION_TYPES)
    r = random.uniform(0, total_weight)
    cumulative = 0
    for interaction_type, template, weight in NPC_INTERACTION_TYPES:
        cumulative += weight
        if r <= cumulative:
            break

    char_a = npc_a.get("char_id") or npc_a.get("id", "")
    char_b = npc_b.get("char_id") or npc_b.get("id", "")
    name_a = npc_a.get("name", "Unknown")
    name_b = npc_b.get("name", "Unknown")

    # Try LLM dialogue first (adds depth), fall back to template
    dialogue = _generate_dialogue(npc_a, npc_b, interaction_type)

    if dialogue:
        description = f"{name_a} and {name_b} engaged in {interaction_type}. {dialogue}"
    else:
        description = template.replace("{name_a}", name_a).replace("{name_b}", name_b)
        for key, values in FILL_VALUES.items():
            placeholder = "{" + key + "}"
            if placeholder in description:
                description = description.replace(placeholder, random.choice(values), 1)

    delta = INTERACTION_DELTAS.get(interaction_type, 0.0)
    jitter = random.uniform(-2, 2)
    actual_delta = delta + jitter

    update_npc_relationship(char_a, char_b, name_b, actual_delta)
    update_npc_relationship(char_b, char_a, name_a, actual_delta * 0.8)

    ts = int(time.time())
    event = {
        "event_type": "npc_interaction",
        "interaction_type": interaction_type,
        "char_ids": [char_a, char_b],
        "description": description,
        "has_dialogue": dialogue is not None,
        "relationship_delta": round(actual_delta, 1),
        "ts": ts,
    }

    # Store dialogue in Redis for frontend display
    if dialogue:
        try:
            r = _get_redis()
            dialogue_key = f"npc_dialogue:{char_a}:{char_b}"
            r.setex(dialogue_key, 3600, json.dumps({
                "name_a": name_a,
                "name_b": name_b,
                "dialogue": dialogue,
                "interaction_type": interaction_type,
                "ts": ts,
            }))
        except Exception:
            pass

    # Log interaction for BOTH NPCs (source + target)
    try:
        log_npc_activity(char_a, "interaction", {
            "category": interaction_type,
            "description": description[:200],
            "affiliation": npc_a.get("affiliation", "independent"),
            "target_char_id": char_b,
            "target_name": name_b,
            "relationship_delta": round(actual_delta, 1),
            "has_dialogue": dialogue is not None,
        }, timestamp=ts)
        log_npc_activity(char_b, "interaction", {
            "category": interaction_type,
            "description": description[:200],
            "affiliation": npc_b.get("affiliation", "independent"),
            "target_char_id": char_a,
            "target_name": name_a,
            "relationship_delta": round(actual_delta * 0.8, 1),
            "has_dialogue": dialogue is not None,
        }, timestamp=ts)
    except Exception:
        pass  # Logging is best-effort

    r = _get_redis()
    r.zadd("npc_world_events", {json.dumps(event): event["ts"]})
    r.zremrangebyrank("npc_world_events", 0, -(MAX_WORLD_EVENTS + 1))

    return event


def get_relationship_summary(char_id: str) -> Dict[str, Any]:
    relationships = get_npc_relationships(char_id)
    if not relationships:
        return {"char_id": char_id, "relationships": {}, "allies": [], "rivals": []}

    allies = []
    rivals = []
    for other_id, score in relationships.items():
        entry = {"char_id": other_id, "score": score}
        if score >= 65:
            allies.append(entry)
        elif score <= 35:
            rivals.append(entry)

    allies.sort(key=lambda x: x["score"], reverse=True)
    rivals.sort(key=lambda x: x["score"])

    return {
        "char_id": char_id,
        "relationships": relationships,
        "allies": allies[:5],
        "rivals": rivals[:5],
    }


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


# --- NPC GOALS SYSTEM (Phase 5) ---
# --- NPC GOALS SYSTEM (Phase 5) ---

GOAL_TYPES = {
    "scholar": [
        (
            "research_breakthrough",
            "Achieve a breakthrough in {field} research",
            "research",
        ),
        ("uncover_truth", "Uncover the truth about {danger}", "investigation"),
        ("publish_findings", "Publish definitive findings on {topic}", "research"),
        (
            "forge_alliance",
            "Secure a research alliance with the {faction}",
            "diplomacy",
        ),
    ],
    "warrior": [
        ("defend_territory", "Fortify defenses against {danger}", "defense"),
        ("train_elites", "Train elite operatives for the {faction}", "training"),
        ("eliminate_threat", "Neutralize the {danger} threat", "combat"),
        ("earn_command", "Earn a command position in {faction}", "ambition"),
    ],
    "rogue": [
        ("acquire_asset", "Acquire the {item} by any means necessary", "acquisition"),
        (
            "expose_secret",
            "Expose {faction} secrets to the right buyer",
            "intelligence",
        ),
        (
            "build_network",
            "Build an underground network across {location}",
            "networking",
        ),
        ("disappear_clean", "Execute a clean disappearance from {faction}", "escape"),
    ],
    "mystic": [
        (
            "commune_with_void",
            "Commune with the consciousness of the void",
            "transcendence",
        ),
        ("interpret_omen", "Interpret the omen of {omen}", "divination"),
        (
            "awaken_potential",
            "Awaken latent consciousness in {location}",
            "transcendence",
        ),
        ("warn_others", "Warn the station about the {danger}", "prophecy"),
    ],
    "leader": [
        (
            "unite_factions",
            "Broker unity between {faction} and rival factions",
            "diplomacy",
        ),
        ("pass_legislation", "Pass the {topic} directive through council", "politics"),
        ("secure_resources", "Secure resource rights for {location}", "economics"),
        ("consolidate_power", "Consolidate influence over {faction}", "ambition"),
    ],
    "sage": [
        (
            "find_balance",
            "Restore balance to {location} after recent turmoil",
            "harmony",
        ),
        (
            "teach_wisdom",
            "Teach the principle of {concept} to the next generation",
            "teaching",
        ),
        (
            "meditate_on_truth",
            "Meditate until the truth of {concept} reveals itself",
            "transcendence",
        ),
        (
            "heal_division",
            "Heal the rift between warring factions in {faction}",
            "harmony",
        ),
    ],
    "wanderer": [
        (
            "chart_unknown",
            "Chart the uncharted {feature} beyond station limits",
            "exploration",
        ),
        ("find_origin", "Discover the origin of the {creature}", "exploration"),
        (
            "gather_tales",
            "Collect stories from every corner of {location}",
            "discovery",
        ),
        (
            "return_home",
            "Find a way back to the homeworld through {location}",
            "pilgrimage",
        ),
    ],
    "hero": [
        (
            "protect_weak",
            "Protect the civilians in {location} from {danger}",
            "protection",
        ),
        ("rally_allies", "Rally allies against the {danger} threat", "leadership"),
        ("complete_quest", "Complete the mission in {location}", "duty"),
        ("inspire_hope", "Inspire hope across the station during the crisis", "morale"),
    ],
    "deceiver": [
        (
            "manipulate_faction",
            "Manipulate {faction} into serving hidden interests",
            "manipulation",
        ),
        (
            "plant_misinfo",
            "Plant disinformation about {topic} across the station",
            "deception",
        ),
        (
            "eliminate_rival",
            "Quietly eliminate a rival within {faction}",
            "elimination",
        ),
        ("control_narrative", "Control the narrative around {topic}", "propaganda"),
    ],
    "guardian": [
        (
            "enforce_protocol",
            "Enforce protocol {number} across all sectors",
            "enforcement",
        ),
        (
            "uncover_conspiracy",
            "Uncover the conspiracy behind {danger}",
            "investigation",
        ),
        (
            "shield_innocents",
            "Shield the inhabitants of {location} from {danger}",
            "protection",
        ),
        ("maintain_order", "Maintain order during the {topic} crisis", "enforcement"),
    ],
}

GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_ABANDONED = "abandoned"

MAX_GOALS_PER_NPC = 3
GOAL_TTL = 86400 * 14
GOAL_PROGRESS_PER_ACTION = 15
GOAL_PROGRESS_VARIANCE = 10


def generate_goal(char_id: str, archetype: str) -> Optional[Dict]:
    templates = GOAL_TYPES.get(archetype, GOAL_TYPES["scholar"])
    goal_type, template, category = random.choice(templates)

    description = template
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    goal = {
        "goal_id": f"{char_id}_{goal_type}_{int(time.time())}",
        "char_id": char_id,
        "goal_type": goal_type,
        "category": category,
        "description": description,
        "progress": 0,
        "status": GOAL_STATUS_ACTIVE,
        "created_ts": int(time.time()),
        "updated_ts": int(time.time()),
    }

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    existing = _get_goals_raw(char_id)
    active = [g for g in existing if g.get("status") == GOAL_STATUS_ACTIVE]
    if len(active) >= MAX_GOALS_PER_NPC:
        return None

    r.rpush(key, json.dumps(goal))
    r.expire(key, GOAL_TTL)
    return goal


def _get_goals_raw(char_id: str) -> List[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)
    goals = []
    for item in raw:
        try:
            goals.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return goals


def get_goals(char_id: str, status: Optional[str] = None) -> List[Dict]:
    goals = _get_goals_raw(char_id)
    if status:
        goals = [g for g in goals if g.get("status") == status]
    return goals


def advance_goal(
    char_id: str, goal_id: str, progress_delta: Optional[float] = None
) -> Optional[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue

        if goal.get("goal_id") == goal_id and goal.get("status") == GOAL_STATUS_ACTIVE:
            if progress_delta is None:
                progress_delta = GOAL_PROGRESS_PER_ACTION + random.uniform(
                    -GOAL_PROGRESS_VARIANCE, GOAL_PROGRESS_VARIANCE
                )
            goal["progress"] = min(
                100, max(0, goal.get("progress", 0) + progress_delta)
            )
            goal["updated_ts"] = int(time.time())

            if goal["progress"] >= 100:
                goal["status"] = GOAL_STATUS_COMPLETED
            updated = goal

        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


def set_goal_status(char_id: str, goal_id: str, status: str) -> Optional[Dict]:
    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if goal.get("goal_id") == goal_id:
            goal["status"] = status
            goal["updated_ts"] = int(time.time())
            updated = goal
        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


# --- GOAL-DRIVEN ACTION GENERATION ---


def generate_goal_driven_action(
    char_id: str, char_name: str, archetype: str, affiliation: str, mood: str = ""
) -> Optional[Dict]:
    active_goals = get_goals(char_id, status=GOAL_STATUS_ACTIVE)

    if not active_goals:
        return generate_action(char_id, char_name, archetype, affiliation, mood)

    target_goal = random.choice(active_goals)

    goal_action_templates = {
        "research": [
            ("research", "continued work on their goal: {goal_desc}"),
            ("experiment", "ran experiments advancing: {goal_desc}"),
            ("analysis", "analyzed new data related to: {goal_desc}"),
        ],
        "investigation": [
            ("investigation", "followed a lead on: {goal_desc}"),
            ("surveillance", "conducted surveillance for: {goal_desc}"),
            ("interrogation", "questioned contacts about: {goal_desc}"),
        ],
        "defense": [
            ("fortification", "reinforced defenses as part of: {goal_desc}"),
            ("patrol", "increased patrols for: {goal_desc}"),
            ("inspection", "inspected perimeter for: {goal_desc}"),
        ],
        "training": [
            ("training", "ran drills advancing: {goal_desc}"),
            ("evaluation", "evaluated recruits for: {goal_desc}"),
        ],
        "combat": [
            ("strike", "launched a tactical strike for: {goal_desc}"),
            ("skirmish", "engaged hostiles related to: {goal_desc}"),
        ],
        "ambition": [
            ("maneuver", "made a political maneuver for: {goal_desc}"),
            ("campaign", "campaigned for support toward: {goal_desc}"),
        ],
        "acquisition": [
            ("heist", "planned an acquisition for: {goal_desc}"),
            ("negotiation", "negotiated terms for: {goal_desc}"),
        ],
        "intelligence": [
            ("intelligence", "gathered intel advancing: {goal_desc}"),
            ("reconnaissance", "scouted for: {goal_desc}"),
        ],
        "networking": [
            ("recruitment", "recruited contacts for: {goal_desc}"),
            ("deal", "struck a deal advancing: {goal_desc}"),
        ],
        "escape": [
            ("preparation", "made preparations for: {goal_desc}"),
            ("cover", "established cover for: {goal_desc}"),
        ],
        "transcendence": [
            ("ritual", "performed a ritual advancing: {goal_desc}"),
            ("meditation", "entered deep meditation for: {goal_desc}"),
        ],
        "divination": [
            ("vision", "sought a vision about: {goal_desc}"),
            ("study", "studied ancient texts about: {goal_desc}"),
        ],
        "prophecy": [
            ("warning", "issued a warning about: {goal_desc}"),
            ("teaching", "taught others about: {goal_desc}"),
        ],
        "diplomacy": [
            ("negotiation", "entered negotiations for: {goal_desc}"),
            ("meeting", "convened a meeting about: {goal_desc}"),
        ],
        "politics": [
            ("decree", "pushed legislation for: {goal_desc}"),
            ("campaign", "lobbied support for: {goal_desc}"),
        ],
        "economics": [
            ("trade", "negotiated trade terms for: {goal_desc}"),
            ("audit", "audited resources for: {goal_desc}"),
        ],
        "harmony": [
            ("mediation", "mediated a dispute for: {goal_desc}"),
            ("counsel", "offered counsel for: {goal_desc}"),
        ],
        "teaching": [
            ("lecture", "gave a lecture about: {goal_desc}"),
            ("mentorship", "mentored a student for: {goal_desc}"),
        ],
        "exploration": [
            ("exploration", "set out to explore for: {goal_desc}"),
            ("survey", "conducted a survey for: {goal_desc}"),
        ],
        "discovery": [
            ("discovery", "made a discovery advancing: {goal_desc}"),
            ("documentation", "documented findings for: {goal_desc}"),
        ],
        "pilgrimage": [
            ("journey", "began a journey for: {goal_desc}"),
            ("preparation", "prepared for the pilgrimage: {goal_desc}"),
        ],
        "protection": [
            ("guard", "stood guard for: {goal_desc}"),
            ("escort", "escorted civilians for: {goal_desc}"),
        ],
        "leadership": [
            ("rally", "rallied supporters for: {goal_desc}"),
            ("command", "took command advancing: {goal_desc}"),
        ],
        "duty": [
            ("mission", "executed a mission for: {goal_desc}"),
            ("report", "filed a report on: {goal_desc}"),
        ],
        "morale": [
            ("speech", "gave an inspiring speech for: {goal_desc}"),
            ("aid", "delivered aid for: {goal_desc}"),
        ],
        "manipulation": [
            ("manipulation", "manipulated events for: {goal_desc}"),
            ("scheme", "advanced a scheme for: {goal_desc}"),
        ],
        "deception": [
            ("plant", "planted false intel for: {goal_desc}"),
            ("cover", "maintained cover for: {goal_desc}"),
        ],
        "elimination": [
            ("ambush", "set an ambush for: {goal_desc}"),
            ("sabotage", "sabotaged operations for: {goal_desc}"),
        ],
        "propaganda": [
            ("broadcast", "broadcast propaganda for: {goal_desc}"),
            ("censorship", "suppressed information about: {goal_desc}"),
        ],
        "enforcement": [
            ("enforcement", "enforced regulations for: {goal_desc}"),
            ("crackdown", "led a crackdown for: {goal_desc}"),
        ],
    }

    category = target_goal.get("category", "research")
    templates = goal_action_templates.get(category, goal_action_templates["research"])
    action_type, template = random.choice(templates)

    goal_short = target_goal.get("description", "their objective")
    if len(goal_short) > 60:
        goal_short = goal_short[:57] + "..."
    description = template.replace("{goal_desc}", goal_short)

    action = {
        "char_id": char_id,
        "char_name": char_name,
        "action_type": action_type,
        "description": f"{char_name} {description}",
        "mood": mood or "contemplative",
        "goal_id": target_goal.get("goal_id"),
        "ts": int(time.time()),
    }

    r = _get_redis()
    akey = f"npc_actions:{char_id}"
    r.zadd(akey, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(akey, 0, -(MAX_ACTIONS + 1))
    r.expire(akey, THOUGHT_TTL)

    world_key = "npc_world_events"
    r.zadd(world_key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(world_key, 0, -(MAX_WORLD_EVENTS + 1))
    r.expire(world_key, THOUGHT_TTL)

    advance_goal(char_id, target_goal["goal_id"])

    return action


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


LOW_VALUE_CATEGORIES = frozenset({"rest", "wander", "noop"})


def _reflect_on_missing_context(npc_id, recent_decisions, inst_ctx, world_ctx, fulfilled_need_types=None, outcome_ctx=None):
    """Return a suggested need record or None if the NPC seems well-resourced."""
    if fulfilled_need_types is None:
        fulfilled_need_types = set()
    if not recent_decisions:
        return None
    # P3: pivot strategy — if NPC has consecutive rejections, suggest pivoting before low-value pattern emerges
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
    # Apply cascade decision bias from event_cascade reactions
    try:
        _bias_r = _get_redis()
        _bias_raw = _bias_r.get(f"npc_decision_bias:{char_id}")
        if _bias_raw:
            _bias_data = json.loads(_bias_raw)
            _bias_val = _bias_data.get(category, 1.0)
            if _bias_val and _bias_val != 1.0:
                score *= _bias_val
    except Exception:
        pass  # bias is optional — never break decision scoring

    # Apply decree directive bias (councilor intent influences faction-aligned NPCs)
    try:
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
        pass  # directive bias is optional — never break decision scoring

    # Quest-aware bias: NPCs with active quests strongly prefer advance_goal
    if has_active_quests and category == "advance_goal":
        score *= 1.4
    # Cap cascade suppression of advance_goal when NPC has quests
    if has_active_quests and category == "advance_goal" and score < 0.5:
        score = 0.5

    score *= _world_state_decision_modifier(category)

    # Institution-aware bias: active institutions with workflows pull
    # faction-aligned NPCs toward advance_goal and help_ally
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

    # Need-reflection: if NPC has recent low-value decision pattern,
    # boost request_capability so the NPC files a need instead of
    # repeatedly resting or wandering
    if category == "request_capability":
        if need_reflection:
            score *= 2.5
        else:
            score *= 0.05

    # P3: Outcome-memory bias — past workflow outcomes shape future decisions
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

    # Check if NPC has active quests (quest-aware decision bias)
    has_active_quests = False
    try:
        _qr = _get_redis()
        _quest_data = _qr.get(f"npc_quests:active:{char_id}")
        if _quest_data:
            _quest_list = json.loads(_quest_data)
            has_active_quests = len(_quest_list) > 0
    except Exception:
        pass  # quest check is optional — never break decision evaluation

    inst_ctx = _get_institution_context()

    outcome_ctx = _get_npc_outcome_ctx(char_id)

    need_reflection = None
    try:
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
        # P3: outcome-memory reason labels
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


def make_decision(char_id, char_name, archetype, affiliation, mood=""):
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

DECISION_EVENT_MAP = {
    "investigate": ("investigation_started", "public", 0.7),
    "socialize": ("social_gathering", "public", 0.5),
    "advance_goal": ("goal_pursuit", "public", 0.6),
    "confront_rival": ("conflict_erupted", "public", 0.9),
    "help_ally": ("alliance_formed", "public", 0.6),
    "seek_resources": ("resource_acquisition", "public", 0.6),
    "self_improve": ("training_undertaken", "faction", 0.4),
    "rest": ("rest_period", "private", 0.1),
    "explore": ("expedition_launched", "public", 0.8),
    "react_to_events": ("event_reaction", "public", 0.5),
    "negotiate": ("negotiation_initiated", "public", 0.7),
    "trade": ("trade_conducted", "public", 0.5),
    "patrol": ("patrol_dispatched", "faction", 0.6),
    "research": ("research_breakthrough", "public", 0.8),
    "diplomacy": ("diplomatic_mission", "public", 0.7),
    "sabotage": ("sabotage_detected", "public", 0.9),
}

MAX_BROADCAST_EVENTS = 100
BROADCAST_TTL = 86400 * 7


def broadcast_decision_event(decision, affiliation="independent"):
    category = decision.get("category", "")
    if category not in DECISION_EVENT_MAP:
        return None
    event_type, visibility, significance = DECISION_EVENT_MAP[category]
    char_name = decision.get("char_name", "Unknown")
    char_id = decision.get("char_id", "")
    event = {
        "event_type": event_type,
        "source_char_id": char_id,
        "source_char_name": char_name,
        "source_affiliation": affiliation,
        "decision_category": category,
        "description": decision.get("action_desc")
        or decision.get("description", f"{char_name} performed {category}"),
        "visibility": visibility,
        "significance": significance,
        "faction": affiliation,
        "target_faction": decision.get("target_faction", ""),
        "ts": int(time.time()),
    }
    r = _get_redis()
    key = "npc_broadcast_events"
    r.zadd(key, {json.dumps(event): event["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_BROADCAST_EVENTS + 1))
    r.expire(key, BROADCAST_TTL)
    log_from_broadcast_event(event, tick_id=int(time.time()))
    return event


def get_broadcast_events(char_id=None, affiliation=None, limit=10):
    r = _get_redis()
    raw = r.zrevrange("npc_broadcast_events", 0, limit * 3 - 1)
    events = []
    for item in raw:
        try:
            evt = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if char_id and evt.get("source_char_id") == char_id:
            continue
        vis = evt.get("visibility", "public")
        if vis == "private":
            continue
        if vis == "faction" and affiliation:
            src_faction = evt.get("source_affiliation", "")
            if (
                src_faction
                and src_faction != affiliation
                and affiliation != "independent"
            ):
                continue
        events.append(evt)
        if len(events) >= limit:
            break
    return events


def get_relevant_events_for_npc(char_id, affiliation, limit=5):
    return get_broadcast_events(char_id=char_id, affiliation=affiliation, limit=limit)


# --- COUNCILOR DECREES: Bounded world-state write access ---

DECREES_ALLOWED_NPCS = [
    x.strip()
    for x in os.environ.get("EXTERNAL_AGENT_NPCS", "char_001,char_306").split(",")
    if x.strip()
]

DECREES_ALLOWED_METRICS = [
    "stability",
    "morale",
    "resource_abundance",
    "tension_level",
    "threat_level",
    "anomaly_activity",
]

DECREE_MAX_DELTA = 5
DECREE_COOLDOWN_SECONDS = 3600
DECREE_HISTORY_KEY = "councilor:decrees:history"
DECREE_COOLDOWN_KEY = "councilor:decrees:cooldown:{char_id}"
DECREE_MAX_HISTORY = 200
DECREE_HISTORY_TTL = 86400 * 30

DIRECTIVE_KEY = "councilor:directive:active"
DIRECTIVE_TTL = 600

DECREE_DIRECTIVE_BIAS = {
    "stability": {
        "same_faction": {"help_ally": 1.35, "advance_goal": 1.25, "socialize": 1.15, "confront_rival": 0.65, "rest": 0.75},
        "allied_faction": {"help_ally": 1.2, "socialize": 1.1, "confront_rival": 0.8},
        "other_faction": {"confront_rival": 0.9},
    },
    "morale": {
        "same_faction": {"socialize": 1.4, "help_ally": 1.25, "advance_goal": 1.1, "rest": 0.65, "self_improve": 0.85},
        "allied_faction": {"socialize": 1.2, "help_ally": 1.15, "rest": 0.8},
        "other_faction": {},
    },
    "resource_abundance": {
        "same_faction": {"seek_resources": 1.45, "advance_goal": 1.15, "rest": 0.7, "socialize": 0.85},
        "allied_faction": {"seek_resources": 1.25, "advance_goal": 1.1},
        "other_faction": {"seek_resources": 1.1},
    },
    "tension_level": {
        "same_faction": {"socialize": 1.4, "help_ally": 1.25, "confront_rival": 0.55, "investigate": 0.85},
        "allied_faction": {"socialize": 1.2, "confront_rival": 0.7},
        "other_faction": {"investigate": 1.15, "confront_rival": 1.1},
    },
    "threat_level": {
        "same_faction": {"self_improve": 1.35, "help_ally": 1.25, "seek_resources": 1.15, "explore": 0.6, "socialize": 0.85},
        "allied_faction": {"self_improve": 1.2, "help_ally": 1.15},
        "other_faction": {"investigate": 1.15},
    },
    "anomaly_activity": {
        "same_faction": {"investigate": 1.4, "explore": 1.25, "rest": 0.75, "seek_resources": 0.85},
        "allied_faction": {"investigate": 1.2, "explore": 1.15, "rest": 0.85},
        "other_faction": {"investigate": 1.1},
    },
}


COUNCILOR_AFFILIATIONS = {
    "char_001": "research_division",
    "char_306": "none",
}

FACTION_ALLIANCES = {
    "research_division": ["exploration_initiative"],
    "exploration_initiative": ["research_division"],
    "military_command": ["preservation_society"],
    "preservation_society": ["military_command"],
    "diplomatic_corps": ["cultural_ministry", "economic_council"],
    "cultural_ministry": ["diplomatic_corps", "consciousness_collective"],
    "economic_council": ["diplomatic_corps"],
    "consciousness_collective": ["cultural_ministry"],
}


def _is_allied_faction(npc_faction, issuer_faction):
    if not npc_faction or not issuer_faction:
        return False
    return npc_faction in FACTION_ALLIANCES.get(issuer_faction, [])


def _write_decree_directive(r, char_id, metric):
    issuer_faction = COUNCILOR_AFFILIATIONS.get(char_id, "")
    directive_data = json.dumps({
        "metric": metric,
        "issuer": char_id,
        "issuer_faction": issuer_faction,
        "ts": int(time.time()),
    })
    r.set(DIRECTIVE_KEY, directive_data, ex=DIRECTIVE_TTL)


def issue_decree(char_id, char_name, metric, delta, reasoning=""):
    if char_id not in DECREES_ALLOWED_NPCS:
        return {"ok": False, "error": f"{char_id} is not authorized to issue decrees"}
    if metric not in DECREES_ALLOWED_METRICS:
        return {"ok": False, "error": f"metric '{metric}' is not decreable"}
    if delta == 0:
        return {"ok": False, "error": "delta must be non-zero"}
    if abs(delta) > DECREE_MAX_DELTA:
        return {
            "ok": False,
            "error": f"delta {delta} exceeds max ±{DECREE_MAX_DELTA}",
        }
    if metric not in WORLD_CONDITIONS:
        return {"ok": False, "error": f"unknown metric: {metric}"}
    r = _get_redis()
    cooldown_key = DECREE_COOLDOWN_KEY.format(char_id=char_id)
    ttl = r.ttl(cooldown_key)
    if ttl and ttl > 0:
        return {
            "ok": False,
            "error": f"cooldown active for {ttl}s",
            "cooldown_remaining": ttl,
        }
    current = get_world_condition(metric)
    if current is None:
        return {"ok": False, "error": f"could not read current value for {metric}"}
    config = WORLD_CONDITIONS[metric]
    new_val = max(config["min"], min(config["max"], current + delta))
    actual_delta = new_val - current
    if actual_delta == 0:
        return {"ok": False, "error": "change would have no effect (value clamped)"}
    r.hset(WORLD_STATE_KEY, metric, str(int(round(new_val))))
    r.set("world_state_updated", str(int(time.time())), ex=WORLD_STATE_TTL)
    r.setex(cooldown_key, DECREE_COOLDOWN_SECONDS, "1")
    _write_decree_directive(r, char_id, metric)
    decree_record = {
        "decree_id": f"dcr_{char_id}_{int(time.time())}",
        "char_id": char_id,
        "char_name": char_name,
        "metric": metric,
        "previous_value": current,
        "new_value": int(round(new_val)),
        "delta": actual_delta,
        "reasoning": reasoning,
        "ts": int(time.time()),
    }
    r.zadd(DECREE_HISTORY_KEY, {json.dumps(decree_record): decree_record["ts"]})
    r.zremrangebyrank(DECREE_HISTORY_KEY, 0, -(DECREE_MAX_HISTORY + 1))
    r.expire(DECREE_HISTORY_KEY, DECREE_HISTORY_TTL)
    event_desc = (
        f"{char_name} issued a decree: {metric} {current}\u2192{int(round(new_val))}"
        f" ({'+' if actual_delta > 0 else ''}{actual_delta})"
    )
    if reasoning:
        event_desc += f" \u2014 {reasoning[:120]}"
    try:
        from federation_game_events import add_event
        add_event("decree_issued", event_desc, significance=0.9)
    except Exception:
        pass
    return {"ok": True, "decree": decree_record}


def get_decree_history(char_id=None, limit=20):
    r = _get_redis()
    raw = r.zrevrange(DECREE_HISTORY_KEY, 0, limit * 2 - 1)
    decrees = []
    for item in raw:
        try:
            rec = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if char_id and rec.get("char_id") != char_id:
            continue
        decrees.append(rec)
        if len(decrees) >= limit:
            break
    return decrees


DECREE_THRESHOLDS = {
    "stability": {"low": 50, "high": 85, "low_delta": 5, "high_delta": -2},
    "morale": {"low": 40, "high": 80, "low_delta": 4, "high_delta": -2},
    "resource_abundance": {"low": 35, "high": 90, "low_delta": 5, "high_delta": -2},
    "tension_level": {"low": 15, "high": 65, "low_delta": -2, "high_delta": -4},
    "threat_level": {"low": 10, "high": 60, "low_delta": -1, "high_delta": -4},
    "anomaly_activity": {"low": 5, "high": 70, "low_delta": -1, "high_delta": -3},
}

COUNCILOR_NAMES = {"char_001": "Archimedes Prime", "char_306": "The Oracle"}


def evaluate_decree_opportunity(r=None):
    ws = get_world_state()
    if not ws:
        return None
    for char_id in DECREES_ALLOWED_NPCS:
        cooldown_key = DECREE_COOLDOWN_KEY.format(char_id=char_id)
        check_r = r or _get_redis()
        if check_r.ttl(cooldown_key) and check_r.ttl(cooldown_key) > 0:
            continue
        char_name = COUNCILOR_NAMES.get(char_id, char_id)
        for metric, cfg in DECREE_THRESHOLDS.items():
            val = ws.get(metric)
            if val is None:
                continue
            val = float(val)
            if val <= cfg["low"]:
                result = issue_decree(char_id, char_name, metric, cfg["low_delta"],
                                      f"{metric} critically low at {val:.0f}")
                if result.get("ok"):
                    return result.get("decree")
                break
            if val >= cfg["high"]:
                result = issue_decree(char_id, char_name, metric, cfg["high_delta"],
                                      f"{metric} critically high at {val:.0f}")
                if result.get("ok"):
                    return result.get("decree")
                break
    return None
