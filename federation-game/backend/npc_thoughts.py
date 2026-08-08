import hashlib
import json
import logging
import random
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

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

LOW_SIGNIFICANCE_CUTOFF = "low"
MEDIUM_SIG_LLM_PROBABILITY = 0.5
MAX_THOUGHTS = 10
THOUGHT_TTL = 86400 * 7
LLM_USE_NIM = True
THOUGHT_CACHE_TTL = 900
THOUGHT_CACHE_PREFIX = "npc_thought_cache:"

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
        pass

    raw = f"{char_id}|{archetype}|{mood_bucket}|{decision_category}|{world_events_bucket}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{THOUGHT_CACHE_PREFIX}{digest}"


def _get_world_events_bucket() -> str:
    try:
        from npc_autonomy import _get_redis
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
    with _cache_stats_lock:
        return dict(_cache_stats)


def _clean_llm_output(text: str) -> str:
    if not text:
        return ""
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
    for prefix in ("Okay, ", "Sure, ", "Well, ", "Alright, "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip().strip('"').strip("'").strip()
    return text


def _is_leaked_prompt(text: str) -> bool:
    if not text:
        return False
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
    char_id: str = "",
    source: str = "thought",
    system_path: str = "backend.npc_thoughts._call_llm",
) -> str:
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
            char_id=char_id,
            source=source,
            system_path=system_path,
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
    from npc_autonomy import _get_redis, _check_tick_llm_budget

    world_bucket = _get_world_events_bucket()
    cache_key = _compute_thought_cache_key(
        char_id, archetype, mood, significance, world_bucket,
        decision_category=decision_category,
    )
    r = _get_redis()

    thought_text = ""
    cache_hit = False

    if significance != LOW_SIGNIFICANCE_CUTOFF:
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
                char_id=char_id,
            )
        if thought_text and _is_leaked_prompt(thought_text):
            logger.warning(
                "Rejected leaked prompt in thought for %s: %.80s...",
                char_id,
                thought_text,
            )
            thought_text = ""

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
        "cached": cache_hit,
    }
    key = f"npc_thoughts:{char_id}"
    r.zadd(key, {json.dumps(thought): thought["ts"]})
    r.zremrangebyrank(key, 0, -(MAX_THOUGHTS + 1))
    r.expire(key, THOUGHT_TTL)
    return thought
