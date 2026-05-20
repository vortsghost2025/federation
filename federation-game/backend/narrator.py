#!/usr/bin/env python3
"""
FEDERATION GAME — Narrator Layer

Reads tick summary data and generates narrative prose:
- Headline: One dramatic sentence
- 3 Major Developments: Key events from this tick
- Voices from the Factions: In-character quotes from leaders
- Ominous Foreshadowing: One cryptic line hinting at future events

Called ONCE per tick after the autonomous tick completes.
Uses the narrator task class (largest model, highest creative quality).

Output stored in Redis for frontend display.

Redis keys:
    narration:latest   — STRING: JSON of latest narration
    narration:history   — ZSET (score=timestamp): past narrations (TTL 30d)
    narration:cooldown  — STRING: timestamp of last narration call
"""

import json
import logging
import os
import time
import random
from typing import Any, Dict, List, Optional

import redis

from llm_router import route_call

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ── Faction Leader Names (for "Voices" section) ────────────────────

FACTION_LEADERS = {
    "diplomatic_corps": "Chancellor Harmony",
    "military_command": "Marshal Ironbound",
    "cultural_ministry": "Maestro Celestia",
    "research_division": "Dr. Prometheus",
    "consciousness_collective": "Oracle Vex",
    "economic_council": "Merchant-Prince Aurelius",
    "exploration_initiative": "Captain Frontier",
    "preservation_society": "Archivist Eternal",
}

FACTION_IDEAS = {
    "diplomatic_corps": "peace through dialogue and mutual understanding",
    "military_command": "strength and vigilance as the path to security",
    "cultural_ministry": "art and culture as the soul of civilization",
    "research_division": "knowledge and innovation as humanity's salvation",
    "consciousness_collective": "transcendence through unity of mind",
    "economic_council": "prosperity and trade as the foundation of power",
    "exploration_initiative": "the frontier as destiny and purpose",
    "preservation_society": "history and memory as the anchor of identity",
}

NARRATION_COOLDOWN = 120  # seconds between narration calls


# ── Tick Summary Builder ────────────────────────────────────────────


def _build_tick_summary(
    world_state: Dict,
    tick_decisions: List[Dict],
    faction_actions: List[Dict],
    cascade_events: List[Dict],
) -> str:
    """Build a structured summary of the tick for the narrator LLM."""
    lines = []

    # World state
    lines.append("=== WORLD STATE ===")
    for key in (
        "tension_level",
        "resource_abundance",
        "threat_level",
        "stability",
        "morale",
        "anomaly_activity",
    ):
        val = world_state.get(key, 50)
        lines.append(f"  {key}: {val}/100")

    # Key decisions
    lines.append("\n=== NOTABLE NPC DECISIONS ===")
    category_counts = {}
    for d in tick_decisions[:20]:  # Cap at 20 for prompt size
        cat = d.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        name = d.get("char_name", "?")
        desc = d.get("description", "?")[:80]
        lines.append(f"  {name}: {desc}")

    if category_counts:
        lines.append(f"  Summary: {dict(category_counts)}")

    # Faction actions
    if faction_actions:
        lines.append("\n=== FACTION ACTIONS ===")
        for a in faction_actions[:10]:
            faction = a.get("faction_id", "?")
            action_type = a.get("action_type", a.get("type", "?"))
            lines.append(f"  {faction}: {action_type}")

    # Cascade events
    if cascade_events:
        lines.append("\n=== CASCADE EVENTS ===")
        for e in cascade_events[:5]:
            lines.append(f"  {str(e)[:100]}")

    return "\n".join(lines)


# ── Prompt Construction ─────────────────────────────────────────────


def _build_narrator_system_prompt() -> str:
    """Build the system prompt for the narrator LLM."""
    return """You are the CHRONICLER of the Federation — an omniscient narrator
who observes the AI society and weaves its events into compelling narrative.

You write in a dramatic, literary style — like a science fiction novel's
omniscient narrator. You are concise but evocative. You never break character.

Your output MUST follow this EXACT format:

HEADLINE: [One dramatic sentence summarizing this tick's most important event]

DEVELOPMENT 1: [A major event or trend from this tick, 1-2 sentences]
DEVELOPMENT 2: [Another major event or trend, 1-2 sentences]
DEVELOPMENT 3: [A third major event or trend, 1-2 sentences]

VOICE: [faction_name] — "[An in-character quote from that faction's leader, reacting to events]"
VOICE: [different_faction] — "[Another leader's in-character quote]"

FOREWARNING: [One cryptic, ominous line hinting at future danger or change]

RULES:
- The headline should be the single most impactful event
- Developments should be specific, not generic
- Voices should sound like the faction leader speaking (use their ideology)
- The forewarning should be subtle and eerie, not obvious
- Keep each section concise — this is a news digest, not a novel"""


def _build_narrator_user_prompt(
    tick_summary: str, recent_narration: Optional[str]
) -> str:
    """Build the user prompt with tick data and prior context."""
    prompt = f"Here is what happened this tick in the Federation:\n\n{tick_summary}"

    if recent_narration:
        prompt += (
            f"\n\n=== PREVIOUS NARRATION (for continuity) ===\n{recent_narration[:500]}"
        )

    prompt += (
        "\n\nWrite the Federation chronicle for this tick. "
        "Follow the exact output format specified."
    )
    return prompt


# ── Narration Parser ────────────────────────────────────────────────


def _parse_narration(content: str) -> Optional[Dict]:
    """Parse the narrator LLM output into a structured dict.

    Returns None if the output is too short or completely unparseable.
    Otherwise, extracts whatever sections we can find.
    """
    # Defensive: ensure content is a non-empty string
    if not content or not isinstance(content, str) or len(content) < 30:
        return None

    narration = {
        "headline": "",
        "developments": [],
        "voices": [],
        "forewarning": "",
        "raw": content,
    }

    current_section = None
    current_text = []

    for line in content.strip().split("\n"):
        line_stripped = line.strip()

        if line_stripped.upper().startswith("HEADLINE:"):
            narration["headline"] = line_stripped.split(":", 1)[1].strip()
            continue

        if line_stripped.upper().startswith("DEVELOPMENT"):
            # Save previous section
            if current_section == "development" and current_text:
                narration["developments"].append(" ".join(current_text))
            current_section = "development"
            dev_text = line_stripped.split(":", 1)
            current_text = [dev_text[1].strip()] if len(dev_text) > 1 else []
            continue

        if line_stripped.upper().startswith("VOICE:"):
            if current_section == "development" and current_text:
                narration["developments"].append(" ".join(current_text))
            current_section = "voice"
            voice_text = line_stripped.split(":", 1)
            voice_content = voice_text[1].strip() if len(voice_text) > 1 else ""
            narration["voices"].append(voice_content)
            continue

        if line_stripped.upper().startswith("FOREWARNING:"):
            if current_section == "development" and current_text:
                narration["developments"].append(" ".join(current_text))
            current_section = None
            narration["forewarning"] = line_stripped.split(":", 1)[1].strip()
            continue

        # Continuation of current section
        if current_section == "development" and line_stripped:
            current_text.append(line_stripped)

    # Don't forget the last development
    if current_section == "development" and current_text:
        narration["developments"].append(" ".join(current_text))

    # Validation: at minimum we need a headline
    if not narration["headline"]:
        # Try to extract first sentence as headline fallback
        safe_content = content if isinstance(content, str) else ""
        first_line = safe_content.strip().split("\n")[0] if safe_content else ""
        if len(first_line) > 10:
            narration["headline"] = first_line[:120]
        else:
            return None

    return narration


# ── Fallback Narrator ───────────────────────────────────────────────


def _generate_fallback_narration(world_state: Dict, tick_decisions: List[Dict]) -> Dict:
    """Generate a basic deterministic narration when LLM is unavailable.

    This ensures the narration layer ALWAYS produces output, even if
    all LLM providers are down or rate-limited.
    """
    tension = float(world_state.get("tension_level", 50))
    resources = float(world_state.get("resource_abundance", 50))
    threat = float(world_state.get("threat_level", 0))
    morale = float(world_state.get("morale", 50))
    anomaly = float(world_state.get("anomaly_activity", 0))

    # Build headline from most extreme metric
    headline = "The Federation endures another cycle."
    if threat > 70:
        headline = "Threat levels surge as the Federation braces for conflict."
    elif resources < 25:
        headline = "Resource scarcity deepens across Federation territories."
    elif tension > 70:
        headline = "Political tensions reach a boiling point in the Council."
    elif morale < 30:
        headline = "Darkness spreads as morale plummets across the Federation."
    elif anomaly > 60:
        headline = "Strange signals detected as anomaly activity intensifies."
    elif tension < 30 and morale > 60:
        headline = "A rare moment of calm settles over the Federation."

    # Build developments from decision categories
    category_counts = {}
    for d in tick_decisions:
        cat = d.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    developments = []
    if category_counts.get("confront_rival", 0) > 2:
        developments.append("Multiple confrontations erupted between rival factions.")
    if category_counts.get("seek_resources", 0) > 3:
        developments.append("Resource scarcity drove many to seek supplies urgently.")
    if category_counts.get("explore", 0) > 2:
        developments.append("Expeditionary forces pushed into uncharted territory.")
    if category_counts.get("investigate", 0) > 2:
        developments.append("Investigators probed deeper into emerging anomalies.")

    while len(developments) < 3:
        templates = [
            "The cycle passes with routine operations across most sectors.",
            "Faction councils deliberated on matters of mutual concern.",
            "The machinery of governance continued its steady rhythm.",
            "Citizens went about their duties under watchful eyes.",
        ]
        pick = random.choice(templates)
        if pick not in developments:
            developments.append(pick)

    # Pick 2 random faction voices
    factions = list(FACTION_LEADERS.keys())
    selected = random.sample(factions, min(2, len(factions)))
    voices = []
    for f in selected:
        leader = FACTION_LEADERS[f]
        idea = FACTION_IDEAS[f]
        templates = [
            f'"We must stay true to {idea}," {leader} declared.',
            f'{leader} reminded the council: "{idea.capitalize()} is not optional."',
            f'"Our path is clear," {leader} stated firmly.',
        ]
        voices.append(random.choice(templates))

    # Forewarning
    forewarnings = [
        "Something stirs in the deep void between stars.",
        "The instruments detect patterns they cannot explain.",
        "An old prophecy resurfaces in the archives.",
        "A shadow grows at the edge of monitored space.",
        "The data suggests a turning point approaches.",
    ]

    return {
        "headline": headline,
        "developments": developments[:3],
        "voices": voices,
        "forewarning": random.choice(forewarnings),
        "raw": f"[FALLBACK] {headline}",
        "source": "fallback",
    }


# ── Main Narration Function ────────────────────────────────────────


def generate_narration(
    world_state: Dict,
    tick_decisions: List[Dict],
    faction_actions: Optional[List[Dict]] = None,
    cascade_events: Optional[List[Dict]] = None,
) -> Dict:
    """Generate the tick narration.

    Tries LLM first, falls back to deterministic narration if LLM fails.
    Respects cooldown — won't generate more than once per NARRATION_COOLDOWN seconds.

    Args:
        world_state: Current world state dict
        tick_decisions: List of decision dicts from this tick
        faction_actions: List of faction action dicts (optional)
        cascade_events: List of cascade event dicts (optional)

    Returns:
        Dict with: headline, developments, voices, forewarning, raw, source, ts
    """
    r = _get_redis()
    now = time.time()

    result = {
        "headline": "",
        "developments": [],
        "voices": [],
        "forewarning": "",
        "raw": "",
        "source": "none",
        "ts": int(now),
        "model": "",
        "latency_ms": 0,
    }

    # Check cooldown
    try:
        last_narration_ts = r.get("narration:cooldown")
        if last_narration_ts:
            elapsed = now - float(last_narration_ts)
            if elapsed < NARRATION_COOLDOWN:
                # Return the existing latest narration
                try:
                    existing = r.get("narration:latest")
                    if existing:
                        cached = json.loads(existing)
                        cached["source"] = "cached"
                        return cached
                except Exception:
                    pass
                return result
    except Exception:
        pass

    # Get previous narration for continuity
    recent_narration = None
    try:
        recent_raw = r.zrevrange("narration:history", 0, 0)
        if recent_raw:
            recent_data = json.loads(recent_raw[0])
            recent_narration = recent_data.get("headline", "")
    except Exception:
        pass

    # Build tick summary
    tick_summary = _build_tick_summary(
        world_state,
        tick_decisions,
        faction_actions or [],
        cascade_events or [],
    )

    # Try LLM narration
    system_prompt = _build_narrator_system_prompt()
    user_prompt = _build_narrator_user_prompt(tick_summary, recent_narration)

    llm_result = route_call("narrator", system_prompt, user_prompt)
    result["latency_ms"] = llm_result.get("latency_ms", 0)

    if llm_result["success"] and llm_result.get("content"):
        narration = _parse_narration(llm_result["content"])
        if narration:
            result.update(narration)
            result["source"] = "llm"
            result["model"] = llm_result.get("model", "unknown")
        else:
            logger.warning("LLM narration unparseable, using fallback")
            fallback = _generate_fallback_narration(world_state, tick_decisions)
            result.update(fallback)
    else:
        logger.warning(
            "LLM narration failed, using fallback: %s",
            llm_result.get("errors", ["unknown"])[:1],
        )
        fallback = _generate_fallback_narration(world_state, tick_decisions)
        result.update(fallback)

    # Store in Redis
    try:
        narration_json = json.dumps(result)
        r.set("narration:latest", narration_json, ex=86400)
        r.zadd("narration:history", {narration_json: now})
        r.expire("narration:history", 86400 * 30)
        r.zremrangebyrank("narration:history", 0, -501)
        r.set("narration:cooldown", str(now), ex=600)
    except Exception as e:
        logger.warning("Failed to store narration: %s", e)

    logger.info(
        "Narration generated [%s]: %s",
        result.get("source", "?"),
        result.get("headline", "")[:80],
    )

    return result


# ── Observer Helper ──────────────────────────────────────────────────


def get_narration_history(limit: int = 10) -> List[Dict]:
    """Get recent narrations for the observer dashboard."""
    r = _get_redis()
    narrations = []
    try:
        raw = r.zrevrange("narration:history", 0, limit - 1)
        for item in raw:
            try:
                narrations.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    return narrations
