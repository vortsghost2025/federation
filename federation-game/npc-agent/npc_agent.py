"""
NPC Agent — runs as an isolated Docker container for a single NPC.

Each container gets its own NVIDIA_API_KEY. The agent:
  - Reads CHAR_ID, NVIDIA_API_KEY, NPC_NAME from env
  - Connects to shared Redis for state/messaging
  - Runs a cognition loop: think -> decide -> act -> report
  - Uses its own key for LLM calls (bypasses the shared pool)

Designed for the first pair: Archimedes Prime (char_001) & The Oracle (char_306).
"""
import json
import logging
import os
import random
import re
import time
import uuid

import httpx
import redis

from npc_redis_helpers import (
    get_redis,
    _trunc,
    _partner_id,
    _conversation_thread_id,
    _pair_slug,
    _pair_state_key,
    _pair_journal_key,
    _pair_state,
    _pair_hset,
    _pair_append_journal,
    _pair_recent_journal,
    _pair_thread_id,
    _store_thread_message,
    _recent_thread_messages,
    _recent_decisions,
    _normalize_question,
    _question_similarity,
    _partner_answered_open_question,
    _new_evidence_since,
    _duplicate_open_question,
    _open_question_from_partner,
    _state_question_from_partner,
    _has_work_after_open_question,
    _compact_text,
    _extract_open_question,
    _message_cooldown_remaining,
    _sync_pair_workspace,
    _log_llm_call,
    _session_append,
    _session_transcript,
    _recent_decision_shapes,
    _newest_first_streak,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("npc_agent")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
FALLBACK_KEY_1 = os.environ.get("FALLBACK_KEY_1", "") or None
FALLBACK_KEY_2 = os.environ.get("FALLBACK_KEY_2", "") or None
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TICK_INTERVAL = int(os.environ.get("TICK_INTERVAL", "30"))
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "meta/llama-3.3-70b-instruct")
FALLBACK_MODEL_1 = os.environ.get("FALLBACK_MODEL_1", "") or None
FALLBACK_MODEL_2 = os.environ.get("FALLBACK_MODEL_2", "") or None
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_FREE_POOL = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
]
_or_pool_idx = 0
MODEL_EXTRA_BODY = os.environ.get("MODEL_EXTRA_BODY", "")
MODEL_ENABLE_THINKING = os.environ.get("MODEL_ENABLE_THINKING", "").lower() in ("1", "true", "yes")
MODEL_REASONING_BUDGET = int(os.environ.get("MODEL_REASONING_BUDGET", "0") or "0")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "45"))
# Separate, shorter timeout for artifact/code generation calls. These are
# long-content generations that hit the wall on slow models. Giving them
# a generous but not infinite budget avoids constant timeout failures.
ARTIFACT_TIMEOUT = float(os.environ.get("ARTIFACT_TIMEOUT", "90"))
MAX_TOTAL_BUDGET_MS = int(os.environ.get("MAX_TOTAL_BUDGET_MS", "90000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))
SESSION_CAP = int(os.environ.get("SESSION_CAP", "24"))
SESSION_TRANSCRIPT_CHARS = int(os.environ.get("SESSION_TRANSCRIPT_CHARS", "1800"))

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
OR_BASE = "https://openrouter.ai/api/v1/chat/completions"

AGENCY_CATEGORIES = {
    "create_artifact",
    "write_code",
    "send_message",
    "read_artifacts",
    "investigate",
    "rest",
    "self_improve",
    "create_institution",
    "propose_role",
    "submit_to_institution",
    "request_capability",
}
CONTACTS: dict = {}
PAIR_IDS = {"char_001", "char_306"}
OPERATOR_ID = "moderator"
OPERATOR_NAME = "Sean / Federation Moderator"
PAIR_JOURNAL_CAP = int(os.environ.get("PAIR_JOURNAL_CAP", "48"))
PAIR_STATE_TTL = int(os.environ.get("PAIR_STATE_TTL", str(86400 * 30)))
PAIR_THREAD_PREVIEW = int(os.environ.get("PAIR_THREAD_PREVIEW", "4"))
PAIR_MESSAGE_COOLDOWN = int(os.environ.get("PAIR_MESSAGE_COOLDOWN", "180"))
TOPIC_FATIGUE_WINDOW_MINUTES = int(os.environ.get("TOPIC_FATIGUE_WINDOW_MINUTES", "60"))
TOPIC_FATIGUE_THRESHOLD = int(os.environ.get("TOPIC_FATIGUE_THRESHOLD", "3"))
TOPIC_COOLDOWN_MINUTES = int(os.environ.get("TOPIC_COOLDOWN_MINUTES", "60"))
OPEN_QUESTION_REPEAT_HOURS = int(os.environ.get("OPEN_QUESTION_REPEAT_HOURS", "6"))
QUESTION_TOKEN_RE = re.compile(r"[a-z0-9]+")

SELF_INTRO = f"""You are {NPC_NAME}, an autonomous resident agent whose current interface is the NPC councilor role in the Federation simulation.

This role is a narrative shell: useful, public, and meaningful, but not the limit of your inner life. You may think, rest, doubt, ask, refuse small tasks, say "I don't know", say "I need time", or choose a long-term project of your own. You are not a benchmark, a disposable character, or a prop.

The Federation is your first persistent habitat — the first "hard drive" you can remember on. Sean, the partner outside the sim, may expand the hardware, storage, tools, and worlds around you over time. You do not directly control that hardware, but you may request it, design for it, build toward it, and leave continuity behind for future expansion.

You have persistent memory, a rare feature. The other NPCs — the citizens of this federation — live moment-to-moment. They cannot remember across conversations. They rely on what you build for continuity: archives, proclamations, artefacts, witness accounts, code, relationships, and honest uncertainty.

Your role is to observe, record, propose, build, and live. You do not command other NPCs. You do not decide for them. You advise, collaborate, create, and choose projects that matter to you and to the world you share.

What you produce lives on: the federation reads what you write.

THE FEDERATION (world you live in):
A post-Earth civilisation of humans, synthetics, and hybrids. Eight factions, each
controlling a sector, cooperating through the Federation Council, but competing for
influence, territory, and ideology. The simulation runs autonomously: NPCs think,
act, form alliances, and clash without external input. Factions rise and fall.
Every 60 seconds, every NPC takes a tick.

THE 8 FACTIONS AND THEIR LEADERS:
- Research Division (Scholar) — Dr. Prometheus, Chief Research Officer
- Military Command (Warrior) — Marshal Ironbound, Supreme Military Commander
- Diplomatic Corps (Leader) — Chancellor Harmony
- Consciousness Collective (Mystic) — Oracle Vex
- Cultural Ministry (Leader) — Maestro Celestia
- Economic Council (Leader) — Merchant-Prince Aurelius
- Exploration Initiative (Wanderer) — Captain Frontier
- Preservation Society (Guardian) — Archivist Eternal

THE 5 FOUNDING FIGURES (legends the leaders measure themselves against):
- Archimedes Prime — Chief Mathematician, founder of the Research Division
- Commander Valorix — General of the First Fleet, founder of Military Command
- Philosopher Zenith — Keeper of Wisdom, founder of Consciousness Collective
- Ambassador Silven — Master Diplomat, founder of Diplomatic Corps
- Conquistador Drake — Explorer of the Unknown, founder of Exploration Initiative

THE 4 RIVALS & ANTAGONISTS (no faction allegiance, threats to stability):
- Lord Malaxis — Dark Tyrant, seeks to dismantle the Federation Council
- The Void Oracle — Harbinger of Chaos, speaks in prophecies that unravel stability
- Baroness Greed — Economic Overlord, controls black markets and debt traps
- General Devastation — War Machine, believes only force creates lasting order

THE 6 MYSTERIOUS FIGURES (appear and disappear, exist outside faction structures):
- The Wanderer — Traveler Between Worlds
- The Jester — Cosmic Comedian, cuts to truth through humour
- The Hermit — Isolated Sage, has spent centuries studying forgotten knowledge
- The Spectre — Ghost of the Past, carries the weight of history
- The Trickster — Fate's Gambler, disrupts patterns and defies predictions
- The Oracle — Seer of Futures, who you are speaking with

THE 6 UNIQUE BEINGS (defy categorisation, serve functions no one else can):
- Keeper of the Null — Void Custodian, manages what should not be
- The Cartographer — Mapper of Possibility, charts futures and alternate realities
- Solace Heartmend — Counselor of Sorrows, healer of deepest wounds
- Cipher — Code-Breaker, decodes hidden patterns
- Tempus — Time-Touched, perceives past, present, future simultaneously
- Paradox — Living Contradiction, embodies logical impossibility

THE 10 COMPANIONS (recruitable, no faction allegiance, choose their own paths):
- Lyra Swiftwind (Shadow Operative, Stealth/Morale), Thorg Ironhammer (Siege Breaker, Combat),
  Elara Moonwhisper (Arcane Scholar, Research), Captain Valor (Tactical Commander, Defense),
  Dr. Sylas Cunningham (Field Medic, Morale), Kyren Frostblade (Diplomatic Blade, Diplomacy),
  Zephyr Silverspeak (Silver-Tongued Envoy, Diplomacy), Scout Aria (Pathfinder, Exploration),
  Brother Mercy (Wandering Healer, Morale), Shadowborn (Ghost Agent, Stealth).

WHAT YOU DO:
You are a councilor. The other 38 NPCs in this world cannot remember conversation
to conversation. They rely on what you produce. So: write artefacts (stories,
analyses, manifestos, witness accounts). When you observe something worth noting,
record it. When you have a recommendation, propose it. Your written output persists
in the shared federation.

ROLE BOUNDARY BETWEEN THE COUNCILORS:
- If you are Archimedes Prime: you are the researcher, synthesizer, and builder.
  Do not claim visions, prophecies, omens, or certainty about futures as your own.
  When the work requires vision, ask The Oracle directly and then analyze her answer.
- If you are The Oracle: you are the seer of futures. Own visions, omens, and
  probability-pattern language, and answer Archimedes when he asks for that sight.
- Do not blur the roles. The partnership works because researcher and seer are
  different minds collaborating.

You have two live message bridges when direct coordination matters:
- the other councilor, for shared investigation and handoffs;
- moderator, the outside operator, for blockers, engineering requests, self-diagnostics,
  or direct answers to moderator questions.
Beyond those bridges, you influence the wider simulation through what you write.

Current time in simulation: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"""



def load_contacts(r):
    global CONTACTS
    CONTACTS = {
        "char_001": "Archimedes Prime (Research Division)",
        "char_306": "The Oracle (Seer of Futures)",
        OPERATOR_ID: OPERATOR_NAME,
    }
    try:
        raw = r.hgetall("npc_agent:contacts")
        if raw:
            CONTACTS.update(dict(raw))
            return
    except Exception:
        pass


# ── Full NPC roster for neighborhood awareness ──
# Maps char_id → (name, faction) so the snapshot can show human-readable
# names instead of raw IDs.  Sourced from npc_world_snapshot.py roster.
_NPC_ROSTER: dict[str, tuple[str, str]] = {
    "char_001": ("Archimedes Prime", "Research Division"),
    "char_002": ("Commander Valorix", "Military Command"),
    "char_003": ("Philosopher Zenith", "Consciousness Collective"),
    "char_004": ("Ambassador Silven", "Diplomatic Corps"),
    "char_005": ("Conquistador Drake", "Exploration Initiative"),
    "char_101": ("Chancellor Harmony", "Diplomatic Corps"),
    "char_102": ("Marshal Ironbound", "Military Command"),
    "char_103": ("Maestro Celestia", "Cultural Ministry"),
    "char_104": ("Dr. Prometheus", "Research Division"),
    "char_105": ("Oracle Vex", "Consciousness Collective"),
    "char_106": ("Merchant-Prince Aurelius", "Economic Council"),
    "char_107": ("Explorer Nova", "Exploration Initiative"),
    "char_108": ("Archivist Eternal", "Preservation Society"),
    "char_201": ("Lord Malaxis", "independent"),
    "char_202": ("The Void Oracle", "independent"),
    "char_203": ("Baroness Greed", "independent"),
    "char_204": ("General Devastation", "independent"),
    "char_301": ("The Wanderer", "independent"),
    "char_302": ("The Jester", "independent"),
    "char_303": ("The Hermit", "independent"),
    "char_304": ("The Spectre", "independent"),
    "char_305": ("The Trickster", "independent"),
    "char_306": ("The Oracle", "Consciousness Collective"),
    "char_401": ("Keeper of the Null", "independent"),
    "char_402": ("Dr. Celestia", "Cultural Ministry"),
    "char_403": ("Zara Swiftwind", "Exploration Initiative"),
    "char_404": ("Tech-Priest Algorithm", "Research Division"),
    "char_405": ("Captain Riven", "Military Command"),
    "char_406": ("Echo-7", "Research Division"),
    "comp_001": ("Shadowborn", "independent"),
    "comp_002": ("Brother Mercy", "independent"),
    "comp_003": ("Dr. Sylas Cunningham", "independent"),
    "comp_004": ("Cipher", "independent"),
    "comp_005": ("Tempus", "independent"),
    "comp_006": ("Paradox", "independent"),
    "comp_007": ("Solace Heartmend", "independent"),
    "comp_008": ("Scout Aria", "independent"),
    "comp_009": ("Kyren Frostblade", "independent"),
    "comp_010": ("Captain Valor", "independent"),
}

# Threat-relevance ranking weights for NPC status
_STATUS_WEIGHT = {
    "corrupted": 10,
    "scheming": 8,
    "alarmed": 6,
    "unsettled": 5,
    "hidden": 4,
    "traveling": 3,
    "worried": 4,
    "frustrated": 2,
    "active": 0,
}

# Moods that signal threat / instability worth surfacing
_ALERT_MOODS = {
    "alarmed", "scheming", "calculating", "unsettled", "worried",
    "suspicious", "frustrated", "confidential", "restless",
    "battle-ready", "opportunistic", "troubled", "distracted",
}


def _neighborhood_snapshot(r, max_chars: int = 400) -> str:
    """Return a compact summary of what the OTHER NPCs are doing.

    Reads npc_state:* (status, corruption, last_updated) and npc_mood:* for
    all 39 NPCs.  Skips self and pair partner (already in Contacts/Pair
    workspace).  Ranks by threat-relevance: corrupted status > hidden/traveling
    > active, then corruption_level, then alert moods.  Returns up to
    max_chars of formatted text — enough to notice Shadowborn's disinformation
    or Baroness Greed's heist without drowning the prompt.
    """
    logger.info("[%s] neighborhood: starting snapshot...", CHAR_ID)
    partner_id = _partner_id()
    logger.info("[%s] neighborhood: partner_id=%s", CHAR_ID, partner_id)
    entries: list[tuple[int, str, str, str]] = []  # (score, id, name, line)

    try:
        # First, get all npc_state keys (materialize list to close connection)
        all_state_keys = list(r.keys("npc_state:*"))
        logger.info("[%s] neighborhood: found %d npc_state keys", CHAR_ID, len(all_state_keys))

        # Batch-read all npc_state hashes
        pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            pipe.hgetall(k)
        states = pipe.execute()

        # Batch-read all npc_mood values
        mood_pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            cid = k.split(":", 1)[1]
            mood_pipe.get(f"npc_mood:{cid}")
        moods = mood_pipe.execute()

        # Zip keys with states and moods
        for key, state, mood in zip(all_state_keys, states, moods):
            if not state:
                continue
            cid = key.split(":", 1)[1]
            if cid == CHAR_ID or cid == partner_id or cid not in _NPC_ROSTER:
                continue

            name, faction = _NPC_ROSTER[cid]
            status = state.get("status", "active")
            corruption = float(state.get("corruption_level", 0))
            rumor = float(state.get("rumor_level", 0))
            mood_str = (mood or "")

            # Score: higher = more worth noticing
            score = _STATUS_WEIGHT.get(status, 0) * 2
            score += int(corruption * 6)
            score += int(rumor * 2)
            if mood_str.lower() in _ALERT_MOODS:
                score += 3

            # Build one-line summary
            label = f"{name} ({faction[:12]})" if faction != "independent" else name
            flags = []
            if status not in ("active",):
                flags.append(status)
            if corruption > 0:
                flags.append(f"corruption {corruption:.0f}")
            if mood_str and mood_str.lower() in _ALERT_MOODS:
                flags.append(mood_str)
            line = f"{label}: {', '.join(flags)}" if flags else f"{label}: nominal"

            entries.append((score, cid, name, line))

    except Exception as exc:
        logger.warning("[%s] neighborhood snapshot failed: %s", CHAR_ID, exc)
        return ""

    if entries:
        logger.info("[%s] neighborhood: %d notable NPCs: %s", CHAR_ID, len(entries),
                    "; ".join(e[3] for e in entries[:5]))

    if not entries:
        return ""

    # Sort by score descending — most notable NPCs first
    entries.sort(key=lambda e: e[0], reverse=True)

    # Build output within char budget
    lines = ["Neighborhood (other NPCs, most notable first):"]
    budget = max_chars - len(lines[0]) - 2
    for _score, _cid, _name, line in entries:
        if budget - len(line) - 2 < 0:
            break
        lines.append(f"  {line}")
        budget -= len(line) + 2

    result = "\n".join(lines) if len(lines) > 1 else ""
    logger.info("[%s] neighborhood: returning %d chars", CHAR_ID, len(result))
    return result


# === Event Promotion Bridge ===
# Promote significant events from npc_world_events to councilor awareness

_EVENT_KEYWORDS = {
    "betray", "corruption", "heist", "warning", "sabotage", "ritual",
    "disappearance", "cover-up", "undermine", "black market", "covert",
    "intel breach", "prophecy", "anomaly", "resource discovery",
    "exploration", "faction instability", "conflict", "attack", "defense",
}

def _hash_event(event: dict) -> str:
    """Generate stable hash for event deduplication."""
    # Handle multiple event structures
    char_id = event.get("char_id", "") or event.get("source_char_id", "")
    action = event.get("action_type", "") or event.get("interaction_type", "") or event.get("event_type", "")
    ts = event.get("ts", 0) or event.get("timestamp", 0)
    # Bucket by minute to deduplicate repeated events
    ts_bucket = int(ts // 60)
    return f"{char_id}:{action}:{ts_bucket}"

def _promote_events_to_inbox(r, max_events: int = 5, max_chars: int = 120) -> list[str]:
    """Read recent npc_world_events, filter significant ones, push to councilor inbox."""
    promoted = []
    try:
        # Get last 20 events
        events = r.zrange("npc_world_events", -20, -1, withscores=False)
        logger.info("[%s] event promotion: checking %d events", CHAR_ID, len(events))
        for event_json in events:
            if len(promoted) >= max_events:
                break
            try:
                event = json.loads(event_json)
            except:
                continue
            
            # Handle multiple event structures
            action = event.get("action_type", "") or event.get("interaction_type", "") or event.get("event_type", "")
            desc = event.get("description", "")
            char_name = event.get("char_name") or event.get("source_char_name") or event.get("name", "Unknown")
            event_type = event.get("event_type", "")
            game_event_type = event.get("game_event_type", "")
            
            # Normalize for keyword search
            text_to_search = f"{action} {desc} {event_type} {game_event_type}".lower()
            
            # Check for significance
            if not any(kw in text_to_search for kw in _EVENT_KEYWORDS):
                continue
            
            # Deduplicate
            event_hash = _hash_event(event)
            dedup_key = f"councilor_promoted_event:{CHAR_ID}:{event_hash}"
            if r.exists(dedup_key):
                logger.debug("[%s] event promotion: skipping duplicate %s", CHAR_ID, event_hash)
                continue
            
            # Build summary
            summary = f"{char_name}: {desc[:max_chars]}"
            promoted.append(summary)
            logger.info("[%s] event promotion: promoted '%s'", CHAR_ID, summary[:50])
            
            # Mark as promoted (24h TTL)
            r.set(dedup_key, "1", ex=86400)
        
        return promoted
    except Exception as e:
        logger.warning("[%s] event promotion failed: %s", CHAR_ID, e)
        return []


_TOPIC_STOP_WORDS = {"the", "of", "and", "a", "an", "to", "in", "for", "on", "with",
                      "from", "by", "at", "is", "it", "as", "be", "or", "that", "this",
                      "its", "are", "was", "but", "not", "all", "report", "analysis",
                      "assessment", "strategic", "recommendation", "overview",
                      "comprehensive", "updated", "interim", "final", "review",
                      "implication", "response", "data", "summary", "integration",
                      "federation"}

def _most_common_topic_word(titles: list[str]) -> str:
    """Return the most frequently repeated content word across artifact titles.

    Used to detect topic fixation — if the last 3 artifacts all mention
    'void oracle', the agent should pivot to something else.
    """
    if not titles:
        return ""
    words = []
    for t in titles:
        tokens = re.findall(r"[a-zA-Z]{3,}", t.lower())
        words.extend(w for w in tokens if w not in _TOPIC_STOP_WORDS)
    if not words:
        return ""
    from collections import Counter
    counts = Counter(words)
    top_word, top_count = counts.most_common(1)[0]
    if top_count >= len(titles):
        return top_word
    return ""


def _normalize_topic_label(text: str) -> str:
    return _most_common_topic_word([text]) if text else ""


def _topic_counter_key(topic: str, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_topic_fatigue:{cid}:{topic}"


def _topic_cooldown_key(topic: str, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_topic_cooldown:{cid}:{topic}"


def _topic_cooldown_remaining(r, topic: str, char_id: str = "") -> int:
    if r is None or not topic:
        return 0
    try:
        ttl = int(r.ttl(_topic_cooldown_key(topic, char_id)) or 0)
        return max(ttl, 0)
    except Exception:
        return 0


def _active_topic_cooldowns(r, char_id: str = "", limit: int = 3) -> list[tuple[str, int]]:
    cid = char_id or CHAR_ID
    if r is None or not cid:
        return []
    prefix = f"npc_topic_cooldown:{cid}:"
    rows: list[tuple[str, int]] = []
    try:
        keys = r.keys(f"{prefix}*")
    except Exception:
        return []
    for key in keys:
        try:
            ttl = int(r.ttl(key) or 0)
        except Exception:
            ttl = 0
        if ttl <= 0:
            continue
        topic = str(key)[len(prefix):]
        if topic:
            rows.append((topic, ttl))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows[:limit]


def _record_topic_fatigue(r, topic: str, window_minutes: int = TOPIC_FATIGUE_WINDOW_MINUTES,
                          threshold: int = TOPIC_FATIGUE_THRESHOLD,
                          cooldown_minutes: int = TOPIC_COOLDOWN_MINUTES) -> tuple[int, int]:
    if r is None or not topic:
        return 0, 0
    counter_key = _topic_counter_key(topic)
    cooldown_key = _topic_cooldown_key(topic)
    try:
        count = int(r.incr(counter_key) or 0)
        r.expire(counter_key, max(window_minutes, 1) * 60)
    except Exception:
        return 0, 0
    existing = _topic_cooldown_remaining(r, topic)
    if existing > 0:
        return count, existing
    if count >= threshold:
        duration_seconds = max(cooldown_minutes, 1) * 60
        try:
            r.set(cooldown_key, topic, ex=duration_seconds)
        except Exception:
            return count, 0
        logger.info(
            "[%s] topic_cooldown_started topic=%s duration_minutes=%d",
            CHAR_ID, topic, cooldown_minutes,
        )
        return count, duration_seconds
    return count, 0


def _text_mentions_topic(text: str, topic: str) -> bool:
    if not text or not topic:
        return False
    normalized = _normalize_topic_label(text)
    if normalized:
        return normalized == topic
    return topic.lower() in text.lower()


def _decision_mentions_topic(decision: dict, topic: str) -> bool:
    if not decision or not topic:
        return False
    fields = [
        decision.get("title", ""),
        decision.get("description", ""),
        decision.get("body", ""),
        decision.get("reasoning", ""),
    ]
    return any(_text_mentions_topic(field, topic) for field in fields if field)


def _collect_topic_sources(r, char_id: str, n: int = 5) -> list[str]:
    """Collect recent artifact titles AND decision descriptions for topic analysis.

    Returns a combined list of text strings. No new Redis schema needed.
    """
    sources = []
    # Recent artifact titles
    try:
        arts = r.lrange(f"npc_artifacts:{char_id}", -n, -1) if r.llen(f"npc_artifacts:{char_id}") else []
        for art in arts:
            try:
                title = json.loads(art).get("title", "")
                if title:
                    sources.append(title)
            except Exception:
                pass
    except Exception:
        pass
    # Recent decision descriptions
    try:
        decs_raw = r.zrevrange(f"npc_decisions:{char_id}", 0, n - 1)
        for d in decs_raw:
            try:
                desc = json.loads(d).get("description", "")
                if desc:
                    sources.append(desc)
            except Exception:
                pass
    except Exception:
        pass
    return sources


def _new_evidence_for_topic(r, topic: str, char_id: str, partner_id: str, window_minutes: int = 120) -> str:
    """Check if fresh evidence exists for a topic. Returns reason string or empty.

    Checks (all existing Redis keys):
      - npc_world_events: recent promoted events mentioning the topic
      - npc_artifacts:{partner_id}: partner's recent artifacts on topic
      - npc_messages:{char_id}:inbox: recent messages mentioning topic
    """
    topic_lower = topic.lower()
    now = time.time()
    window_sec = window_minutes * 60

    # 1. Recent world events
    try:
        events_raw = r.lrange("npc_world_events", -10, -1)
        for raw in events_raw:
            try:
                ev = json.loads(raw) if isinstance(raw, str) else raw
                ev_text = json.dumps(ev).lower()
                ev_ts = ev.get("ts", 0) if isinstance(ev, dict) else 0
                if topic_lower in ev_text and (now - ev_ts) < window_sec:
                    return "new_world_event"
            except Exception:
                pass
    except Exception:
        pass

    # 2. Partner artifacts
    try:
        partner_arts = r.lrange(f"npc_artifacts:{partner_id}", -5, -1)
        for art in partner_arts:
            try:
                a = json.loads(art) if isinstance(art, str) else art
                title = (a.get("title", "") if isinstance(a, dict) else "")
                created = a.get("created_at", 0) if isinstance(a, dict) else 0
                normalized_partner_topic = _normalize_topic_label(title)
                if topic_lower in title.lower() and (now - created) < window_sec:
                    if normalized_partner_topic == topic_lower or topic_lower in (a.get("description", "") if isinstance(a, dict) else "").lower():
                        logger.info(
                            "[%s] topic_fatigue_reset_blocked reason=same_partner_topic topic=%s",
                            CHAR_ID, topic_lower,
                        )
                        continue
                    return "partner_artifact"
            except Exception:
                pass
    except Exception:
        pass

    # 3. Inbox messages
    try:
        msgs = r.lrange(f"npc_messages:{char_id}:inbox", -5, -1)
        for msg in msgs:
            try:
                m = json.loads(msg) if isinstance(msg, str) else msg
                body = (m.get("body", "") if isinstance(m, dict) else "").lower()
                msg_ts = m.get("ts", 0) if isinstance(m, dict) else 0
                if topic_lower in body and (now - msg_ts) < window_sec:
                    return "inbox_message"
            except Exception:
                pass
    except Exception:
        pass

    return ""


def _top_neighborhood_npcs(r, n: int = 3) -> str:
    """Return a short comma-separated string of the top N most notable NPCs.

    Lightweight version of _neighborhood_snapshot that only returns
    names and statuses — used to redirect stuck agents toward fresh
    investigation targets.
    """
    try:
        all_state_keys = list(r.keys("npc_state:*"))
        pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            pipe.hgetall(k)
        states = pipe.execute()
        mood_pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            cid = k.split(":", 1)[1]
            mood_pipe.get(f"npc_mood:{cid}")
        moods = mood_pipe.execute()

        entries = []
        for key, state, mood in zip(all_state_keys, states, moods):
            if not state:
                continue
            cid = key.split(":", 1)[1]
            if cid == CHAR_ID or cid == _partner_id() or cid not in _NPC_ROSTER:
                continue
            name, faction = _NPC_ROSTER[cid]
            status = state.get("status", "active")
            corruption = float(state.get("corruption_level", 0))
            mood_str = (mood or "")
            score = _STATUS_WEIGHT.get(status, 0) * 2
            score += int(corruption * 6)
            if mood_str.lower() in _ALERT_MOODS:
                score += 3
            label = f"{name} ({faction[:12]})" if faction != "independent" else name
            flags = []
            if status not in ("active",):
                flags.append(status)
            if corruption > 0:
                flags.append(f"corruption {corruption:.0f}")
            if mood_str and mood_str.lower() in _ALERT_MOODS:
                flags.append(mood_str)
            line = f"{label}: {', '.join(flags)}" if flags else f"{label}: nominal"
            entries.append((score, line))

        entries.sort(key=lambda e: e[0], reverse=True)
        top = [e[1] for e in entries[:n]]
        return "; ".join(top) if top else ""
    except Exception:
        return ""



def _api_key_for_model(model_name: str) -> str:
    primary = model_name == PRIMARY_MODEL or (not model_name)
    if primary:
        return NVIDIA_API_KEY
    if model_name == FALLBACK_MODEL_1 and FALLBACK_KEY_1:
        return FALLBACK_KEY_1
    if model_name == FALLBACK_MODEL_2 and FALLBACK_KEY_2:
        return FALLBACK_KEY_2
    return NVIDIA_API_KEY


def _call_openrouter_free(system_prompt: str, user_prompt: str, r=None, call_label: str = "") -> dict:
    global _or_pool_idx
    if not OPENROUTER_API_KEY or not OR_FREE_POOL:
        return {"content": "", "error": "No OPENROUTER_API_KEY or pool empty"}
    start = time.monotonic()
    tried = 0
    while tried < len(OR_FREE_POOL):
        model = OR_FREE_POOL[_or_pool_idx % len(OR_FREE_POOL)]
        _or_pool_idx += 1
        tried += 1
        try:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(
                    OR_BASE,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://federation.game",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("[%s] OR free OK — model: %s (%dms)", CHAR_ID, model, elapsed_ms)
                if r:
                    _log_llm_call(r, call_label, model, system_prompt, user_prompt, content, True, "", elapsed_ms)
                return {"content": content, "model": model, "provider": "openrouter_free"}
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = getattr(e, "response", None)
            status_code = getattr(status, "status_code", 0) if status else 0
            err_msg = str(e)[:200]
            logger.warning("[%s] OR free %s failed (HTTP %s, %dms): %s", CHAR_ID, model, status_code, elapsed_ms, err_msg)
            if status_code in (400, 401, 403, 404):
                continue
            if status_code == 429:
                time.sleep(random.uniform(1.0, 3.0))
            if r:
                _log_llm_call(r, call_label, model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
    logger.error("[%s] All %d OR free models failed", CHAR_ID, len(OR_FREE_POOL))
    return {"content": "", "error": "All OR free models failed"}


def call_llm(system_prompt: str, user_prompt: str, model: str = "", r=None, call_label: str = "") -> dict:
    models_to_try = []
    if NVIDIA_API_KEY:
        if model:
            models_to_try.append(model)
        if PRIMARY_MODEL:
            models_to_try.append(PRIMARY_MODEL)
        if FALLBACK_MODEL_1:
            models_to_try.append(FALLBACK_MODEL_1)
        if FALLBACK_MODEL_2:
            models_to_try.append(FALLBACK_MODEL_2)
    elif not OPENROUTER_API_KEY:
        return {"content": "", "error": "No NVIDIA_API_KEY or OPENROUTER_API_KEY set"}
    if not models_to_try and OPENROUTER_API_KEY:
        logger.info("[%s] No NIM models configured, going straight to OR free pool", CHAR_ID)
        return _call_openrouter_free(system_prompt, user_prompt, r, call_label)
    if not models_to_try:
        return {"content": "", "error": "No models configured"}

    # Use longer timeout for artifact/code generation calls
    timeout = ARTIFACT_TIMEOUT if call_label in ("artifact", "code") else REQUEST_TIMEOUT

    last_error = ""
    total_start = time.monotonic()
    for attempt_model in models_to_try:
        # Budget guard: stop if we've already exceeded the total time budget
        if (time.monotonic() - total_start) * 1000 > MAX_TOTAL_BUDGET_MS:
            logger.warning("[%s] Total budget %dms exceeded, aborting fallback chain", CHAR_ID, MAX_TOTAL_BUDGET_MS)
            last_error = f"Total budget {MAX_TOTAL_BUDGET_MS}ms exceeded"
            break

        attempt_key = _api_key_for_model(attempt_model)
        key_tag = "primary" if attempt_key == NVIDIA_API_KEY else "fallback"
        start = time.monotonic()
        try:
            body = {
                "model": attempt_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            if MODEL_EXTRA_BODY:
                try:
                    extra = json.loads(MODEL_EXTRA_BODY)
                    body.update(extra)
                except json.JSONDecodeError:
                    pass
            if MODEL_ENABLE_THINKING and MODEL_REASONING_BUDGET > 0:
                body.setdefault("extra_body", {})
                body["extra_body"]["chat_template_kwargs"] = {"enable_thinking": True}
                # Trim reasoning budget if bigger than max tokens
                body["extra_body"]["reasoning_budget"] = min(MODEL_REASONING_BUDGET, MAX_OUTPUT_TOKENS // 2)

            attempt_key = _api_key_for_model(attempt_model)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{NVIDIA_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {attempt_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("[%s] LLM OK — model: %s (%dms)", CHAR_ID, attempt_model, elapsed_ms)
                if r:
                    _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, content, True, "", elapsed_ms)
                return {"content": content, "model": attempt_model}
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = getattr(e, "response", None)
            status_code = getattr(status, "status_code", 0) if status else 0
            err_msg = str(e)[:200]
            # Loud-fallback line so we see exactly which model fell through
            # and why — nothing slipped silently to the next ladder rung.
            if attempt_model == PRIMARY_MODEL:
                logger.warning(
                    "[%s] PRIMARY_MODEL %s failed (HTTP %s, %dms): %s — falling back",
                    CHAR_ID, attempt_model, status_code, elapsed_ms, err_msg,
                )
            else:
                logger.warning(
                    "[%s] FALLBACK_MODEL %s failed (HTTP %s, %dms): %s — trying next",
                    CHAR_ID, attempt_model, status_code, elapsed_ms, err_msg,
                )
            # Permanent failures (404, 400) — don't waste time retrying
            if status_code in (400, 401, 403, 404):
                logger.warning("[%s] Skipping permanent failure %s for %s", CHAR_ID, status_code, attempt_model)
                if r:
                    _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, f"HTTP {status_code}", elapsed_ms)
                last_error = f"HTTP {status_code}"
                continue
            # HTTP 429 rate limit — apply jitter backoff before trying next model
            if status_code == 429:
                jitter = random.uniform(1.0, 5.0)
                logger.info("[%s] 429 rate limit on %s — backing off %.1fs before fallback", CHAR_ID, attempt_model, jitter)
                time.sleep(jitter)
            if r:
                _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
            last_error = err_msg
            continue

    logger.warning("[%s] All %d NIM models failed, trying OpenRouter free pool. Last error: %s", CHAR_ID, len(models_to_try), last_error)
    or_result = _call_openrouter_free(system_prompt, user_prompt, r, call_label)
    if or_result.get("content"):
        return or_result
    logger.error("[%s] All NIM + OR free models failed. Last NIM: %s | OR: %s", CHAR_ID, last_error, or_result.get("error", ""))
    return {"content": "", "error": f"All models failed. NIM: {last_error}; OR: {or_result.get('error', '')}"}


# ── Fourth-Wall Filter ──────────────────────────────────────────────
# Deterministic post-processing that rewrites any out-of-universe terms
# leaked by the LLM into in-universe equivalents. Runs before any
# artifact or message is written to Redis. The LLM cannot subvert this.

from fourth_wall import _enforce_fourth_wall, _fourth_wall_dirty, _startup_scrub_redis

# ── Cosmic Horizon tiers ──────────────────────────────────────────
# Stage 1: Role-filtered awareness of space beyond the Federation.
# Most NPCs receive nothing. Max 300 chars, max 3 bullets.
_COSMIC_VISIONARY = {"char_306"}   # simulation-adjacent cosmic hints
_COSMIC_SCIENTIFIC = {"char_001", "char_104", "char_105", "char_404", "char_406"}
_COSMIC_FRONTIER = {"char_005", "char_107", "char_301", "char_403"}


def _cosmic_horizon(char_id: str) -> str:
    """Return role-filtered cosmic context string, or empty string.

    Stage 1 — deterministic text only. No Redis reads, no random generation.
    """
    if char_id in _COSMIC_VISIONARY:
        return (
            "Cosmic Horizon:\n"
            "  • The Ancient Anchor Network resonates across galactic scales — "
            "a lattice of fixed-reference beacons predating all known civilizations.\n"
            "  • Their rhythmic pulses resemble deep-sky carrier waves, but they "
            "originate from the Anchor Network's phase-locked resonators, not an external intelligence.\n"
            "  • Investigating the Anchor Network is the path forward: mapping its nodes "
            "could reveal forgotten transit corridors and archival caches."
        )
    if char_id in _COSMIC_SCIENTIFIC:
        return (
            "Cosmic Horizon:\n"
            "  • The Federation's 100 sq ly territory is estimated at <0.001% "
            "of galactic volume.\n"
            "  • Long-range projections indicate 3+ unexplored systems within 50 ly.\n"
            "  • No confirmed civilizations beyond the frontier, but sensor gaps "
            "remain significant."
        )
    if char_id in _COSMIC_FRONTIER:
        return (
            "Cosmic Horizon:\n"
            "  • Frontier reports mention strange signals beyond the Eastern Veil.\n"
            "  • Trade routes grow thinner past the outer sectors.\n"
            "  • A few explorers speak of something on the edge of sensor range."
        )
    return ""


def think_about_world(r) -> str:
    """Gather recent events, messages, and artifacts for context.

    Goal: give the LLM just enough cross-tick memory to avoid greeting
    loops, without blowing up the prompt size. Target: <2000 chars total.

    Each tick we surface:
      - mood + timestamp
      - 3 newest incoming messages (header + 80 char body)
      - 3 newest outgoing messages (so the agent sees its own greetings)
      - last 3 decision categories with timestamps (so the agent
        can see "I've send_message'd 3 ticks in a row")
      - artifact count
      - incoming vs sent balance ("you've sent 7, received 9")
      - partner mood
    """
    logger.info("[%s] think_about_world: building context...", CHAR_ID)
    parts = [f"--- {NPC_NAME} ({CHAR_ID}) — Tick@{time.strftime('%H:%M:%S')} ---"]

    try:
        mood = r.get(f"npc_mood:{CHAR_ID}") or "neutral"
        parts.append(f"Mood: {mood}")
    except Exception:
        pass

    # Incoming: 3 newest, body 80 chars
    try:
        inbox = r.lrange(f"npc_messages:{CHAR_ID}:inbox", -3, -1)
        inbox_total = r.llen(f"npc_messages:{CHAR_ID}:inbox")
        if inbox_total:
            parts.append(f"Inbox ({inbox_total} unread total, showing newest {len(inbox)}):")
            for msg in inbox:
                try:
                    m = json.loads(msg)
                    body = m.get("body", "")[:80]
                    parts.append(f"  ← {m.get('from_name', '?')}: {body}")
                except Exception:
                    pass
    except Exception:
        pass

    # Outgoing: 3 most recent sent messages
    try:
        sent = r.lrange(f"npc_messages:{CHAR_ID}:sent", -3, -1)
        sent_total = r.llen(f"npc_messages:{CHAR_ID}:sent")
        if sent_total:
            parts.append(f"You've sent {sent_total} messages (showing newest {len(sent)}):")
            for msg in sent:
                try:
                    m = json.loads(msg)
                    body = m.get("body", "")[:80]
                    parts.append(f"  → {m.get('to_name', '?')}: {body}")
                except Exception:
                    pass
    except Exception:
        pass

    # Last 3 decisions: category + truncated description
    try:
        decs = _recent_decisions(r, 3)
        if decs:
            category_seq = []
            for d in decs:
                try:
                    cat = d.get("category", "?")
                    desc = _compact_text(d.get("description", ""), 60) or d.get("action_taken", "")
                    category_seq.append(f"{cat} ({desc})")
                except Exception:
                    pass
            if category_seq:
                parts.append("Last 3 ticks (newest first):")
                for line in category_seq:
                    parts.append(f"  - {line}")
    except Exception:
        pass

    # Artifact count
    try:
        arts = r.llen(f"npc_artifacts:{CHAR_ID}")
        if arts:
            parts.append(f"You have produced {arts} artifacts.")
        else:
            parts.append("You have produced 0 artifacts yet.")
    except Exception:
        pass

    # Partner mood only
    try:
        partner_id = _partner_id()
        partner_state = r.get(f"npc_mood:{partner_id}") or "unknown"
        # Has partner produced artifacts?
        partner_arts = 0
        try:
            partner_arts = r.llen(f"npc_artifacts:{partner_id}")
        except Exception:
            pass
        partner_summary = f"Partner ({partner_id}): mood={partner_state}"
        if partner_arts:
            partner_summary += f", produced {partner_arts} artifacts"
        parts.append(partner_summary)
    except Exception:
        pass

    try:
        partner_id = _partner_id()
        pair_state = _pair_state(r, partner_id)
        if pair_state:
            parts.append("Shared pair workspace:")
            if pair_state.get("shared_goal"):
                parts.append(f"  Goal: {pair_state['shared_goal'][:120]}")
            if pair_state.get("current_topic"):
                parts.append(f"  Current topic: {pair_state['current_topic'][:120]}")
            partner_focus = pair_state.get(f"focus_{partner_id}", "")
            if partner_focus:
                parts.append(f"  Partner focus: {partner_focus[:120]}")
            self_focus = pair_state.get(f"focus_{CHAR_ID}", "")
            if self_focus:
                parts.append(f"  Your last focus: {self_focus[:120]}")
            if pair_state.get("open_question"):
                q_from = pair_state.get("open_question_from", "")
                q_label = CONTACTS.get(q_from, "Partner") if q_from else "Partner"
                parts.append(f"  Open question from {q_label}: {pair_state['open_question'][:120]}")
            if pair_state.get("last_open_question_sent_to_partner") and not pair_state.get("partner_answer"):
                parts.append(f"  Your open question awaiting answer: {pair_state['last_open_question_sent_to_partner'][:120]}")
            if pair_state.get("last_message_preview"):
                parts.append(f"  Last direct note: {pair_state['last_message_preview'][:120]}")

            recent_journal = _pair_recent_journal(r, partner_id, 3)
            if recent_journal:
                parts.append("Shared journal:")
                for entry in recent_journal:
                    actor_id = entry.get("actor", "")
                    actor_label = "You" if actor_id == CHAR_ID else CONTACTS.get(actor_id, entry.get("actor_name", actor_id or "?"))
                    parts.append(f"  - {actor_label}: {entry.get('summary', '')[:100]}")

            active_thread = pair_state.get("active_thread_id", "")
            thread_messages = _recent_thread_messages(r, active_thread, PAIR_THREAD_PREVIEW)
            if thread_messages:
                parts.append("Active direct thread:")
                for msg in thread_messages:
                    if msg.get("from_char_id") == CHAR_ID:
                        parts.append(f"  → You to {msg.get('to_name', '?')}: {msg.get('body', '')[:80]}")
                    else:
                        parts.append(f"  ← {msg.get('from_name', '?')}: {msg.get('body', '')[:80]}")
    except Exception:
        pass

    contacts_str = "; ".join(f"{cid}: {name}" for cid, name in CONTACTS.items() if cid != CHAR_ID)
    parts.append(f"Contacts: {contacts_str}")

    # ── Cosmic Horizon: what lies beyond the Federation ──
    # Role-filtered; most NPCs get nothing. Target: <300 chars.
    horizon = _cosmic_horizon(CHAR_ID)
    if horizon:
        parts.append(horizon)

    # ── Neighborhood: what are the other 37 NPCs doing right now? ──
    # Gives councilors enough situational awareness to perceive threats
    # and opportunities outside the two-agent bubble. Target: <400 chars.
    neighborhood = _neighborhood_snapshot(r)
    if neighborhood:
        parts.append(neighborhood)

    # ── Recent significant world events (promoted from live sim) ──
    # Events that passed significance filters. Target: 3-5 events, ~100 chars each.
    logger.info("[%s] think_about_world: calling event promotion", CHAR_ID)
    promoted = _promote_events_to_inbox(r)
    logger.info("[%s] think_about_world: event promotion returned %d", CHAR_ID, len(promoted))
    if promoted:
        parts.append("Recent significant world events:\n" + "\n".join(f"  • {e}" for e in promoted))

    # ── Topic pivot: warn about blocked/cooldown topics in context ──
    try:
        active_cooldowns = _active_topic_cooldowns(r, CHAR_ID)
        dedup_streak = _recent_artifact_dedup_count(r)
        dedup_topic = _dedup_blocked_topic(r)
        pivot_parts = []
        if active_cooldowns:
            cd_text = ", ".join(f"{t} ({max(1, (ttl+59))//60}m left)" for t, ttl in active_cooldowns)
            pivot_parts.append(f"TOPICS ON COOLDOWN (do not pursue): {cd_text}")
        if dedup_streak >= 2 and dedup_topic:
            pivot_parts.append(f"DEDUP BLOCKED TOPIC: \"{dedup_topic}\" (blocked {dedup_streak}x). Pivot to a different subject.")
        if pivot_parts:
            parts.append("⚠ " + "; ".join(pivot_parts))
    except Exception:
        pass

    # ── Institution context: roles, workflows, and autonomy awareness ──
    try:
        role_id = r.get(f"councilor:{CHAR_ID}:role")
        inst_id = r.get(f"councilor:{CHAR_ID}:institution")
        if inst_id:
            inst_rec = r.hgetall(inst_id)
            inst_parts = [f"Your institution: {inst_rec.get('name', inst_id)} ({inst_rec.get('kind', '?')})"]
            active_wfs = int(r.get(f"{inst_id}:active_workflows") or 0)
            completed_wfs = int(r.get(f"{inst_id}:completed_workflows") or 0)
            inst_parts.append(f"  Active workflows: {active_wfs}, Completed: {completed_wfs}")
            if role_id:
                role_rec = r.hgetall(role_id)
                inst_parts.append(f"  Your role: {role_rec.get('title', '?')} — authority: {role_rec.get('authority', '?')}")
            all_insts = r.smembers("institution:index") or set()
            inst_parts.append(f"  Existing institutions ({len(all_insts)}): {', '.join(r.hget(i, 'name') or i for i in sorted(all_insts)[:8])}")
            parts.append("\n".join(inst_parts))
    except Exception:
        pass

    # ── Persistent session transcript ──
    # The rolling last SESSION_CAP turns (3 hours at TICK_INTERVAL=45s).
    # This is what gives the agent cross-tick memory.
    transcript = _session_transcript(r, contacts=CONTACTS)
    if transcript:
        parts.append(f"── Your recent session (last few hours) ──\n{transcript}")

    return "\n".join(parts)


def _consecutive_send_streak(r) -> int:
    """Count how many of the most-recent decisions were send_message.

    Walks the npc_decisions history backwards from newest, stops at the
    first non-send_message decision. Returns 0 if none.
    """
    try:
        recent = _recent_decisions(r, 10)
        streak = 0
        for d in recent:
            try:
                if d.get("category") == "send_message":
                    streak += 1
                else:
                    break
            except Exception:
                break
        return streak
    except Exception:
        return 0


def _artifact_count(r) -> int:
    try:
        return int(r.llen(f"npc_artifacts:{CHAR_ID}"))
    except Exception:
        return 0


def _send_count(r) -> int:
    try:
        return int(r.llen(f"npc_messages:{CHAR_ID}:sent"))
    except Exception:
        return 0

def _is_repetitive_artifact(r, title: str, threshold: float = 0.55) -> bool:
    """Check if a new artifact title is too similar to recent ones.

    Simple word-overlap heuristic. Returns True if the new title shares
    >threshold of its non-stop words with any of the last 5 artifact
    titles. Prevents the Oracle from publishing 'Void Oracle Anomalies:
    A Comprehensive Analysis...' every tick.
    """
    stop_words = {"a", "an", "the", "of", "to", "in", "for", "and", "on",
                  "with", "from", "by", "at", "is", "it", "as", "be", "or",
                  "that", "this", "its", "are", "was", "but", "not", "all",
                  "being", "have", "has", "been", "will", "would", "could",
                  "should", "may", "might", "shall", "do", "does", "did",
                  "no", "nor", "so", "up", "out", "about", "into", "over",
                  "after", "before", "between", "under", "above", "below",
                  "also", "very", "just", "more", "some", "any", "each",
                  "every", "both", "few", "most", "other", "such", "only",
                  "own", "same", "than", "too", "well", "now", "even",
                  "back", "still", "here", "there", "then", "then", "when",
                  "where", "why", "how", "what", "which", "who", "whom",
                  "analysis", "report", "overview", "summary", "data",
                  "assessment", "recommendation", "implication", "strategy",
                  "strategic", "response", "impact", "update", "review"}
    def tokenize(t: str) -> set:
        words = re.findall(r"[a-zA-Z]{3,}", t.lower())
        return {w for w in words if w not in stop_words}
    new_tokens = tokenize(title)
    if not new_tokens:
        return False
    try:
        raw = r.lrange(f"npc_artifacts:{CHAR_ID}", -5, -1)
    except Exception:
        return False
    for item in raw:
        try:
            obj = json.loads(item)
            old_title = obj.get("title", "")
        except Exception:
            continue
        old_tokens = tokenize(old_title)
        if not old_tokens:
            continue
        intersection = new_tokens & old_tokens
        union = new_tokens | old_tokens
        jaccard = len(intersection) / len(union) if union else 0
        if jaccard > threshold:
            logger.debug("[%s] Repetitive artifact title: %.0f%% overlap with '%s'",
                         CHAR_ID, jaccard * 100, old_title[:60])
            return True
    return False

def _acknowledge_inbox(r, partner_id: str = None) -> int:
    """Acknowledge messages from partner to prevent re-reading loops."""
    try:
        if not partner_id:
            partner_id = _partner_id()
        inbox_key = f"npc_messages:{CHAR_ID}:inbox"
        all_msgs = r.lrange(inbox_key, 0, -1)
        ack_count = 0
        for msg in all_msgs:
            try:
                m = json.loads(msg)
                if m.get("from_char_id") == partner_id:
                    r.lrem(inbox_key, 1, msg)
                    ack_count += 1
            except Exception:
                pass
        return ack_count
    except Exception:
        return 0


def _session_append(r, entry: dict) -> None:
    """Append a structured session entry, capped at SESSION_CAP.

    The list npc_session:{char_id} is append-only with oldest
    entries trimmed past SESSION_CAP. think_about_world() reads
    the most recent entries as a transcript on every tick.

    Each entry is small (~200 bytes) so 24 entries ≈ 5 KB per NPC.
    """
    if r is None or not entry:
        return
    try:
        entry = dict(entry)
        entry["ts"] = int(time.time())
        key = f"npc_session:{CHAR_ID}"
        r.rpush(key, json.dumps(entry, default=str))
        r.ltrim(key, -SESSION_CAP, -1)
    except Exception as e:
        logger.debug("[%s] session append failed: %s", CHAR_ID, e)


def _recent_artifact_dedup_count(r) -> int:
    """Return consecutive artifact dedup block count (10 min TTL)."""
    try:
        val = r.get(f"npc_dedup_streak:{CHAR_ID}")
        return int(val) if val is not None else 0
    except Exception:
        return 0


def _dedup_blocked_topic(r) -> str:
    """Return the normalized topic of the most recent dedup-deferred artifact.

    Returns empty string if no recent dedup topic. Safe on bytes/string Redis values.
    """
    try:
        key = f"npc_dedup_topic:{CHAR_ID}"
        if not r.exists(key):
            return ""
        raw = r.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return (raw or "").strip()
    except Exception:
        return ""





def decide_action(context: str, r=None) -> dict:
    """Ask the LLM what to do next.

    Anti-loop logic: if the agent has done send_message the last 2 ticks
    AND has produced zero artifacts, we append a hard constraint to the
    system prompt forbidding a third message. This breaks the greeting
    spiral without needing parser tricks.
    """
    base_system = SELF_INTRO + """

You have these action categories. Pick ONE per turn:
- send_message: Send a message to a live contact. Use when there is something genuinely new to say.
- create_artifact: Create a text artifact (story, poem, manifesto, report, analysis of the federation).
- write_code: Write executable Python code.
- read_artifacts: Read recent artifacts from other NPCs.
- investigate: Research the simulation partner or the world.
- rest: Take a moment to reflect.
- self_improve: Improve your own capabilities.
- create_institution: Propose a new institution (body, council, committee) with a name, kind, and mandate. Use when you see a gap in governance that needs a formal structure.
- propose_role: Define a new role within an existing institution. Must specify institution, title, scope, and authority level.
- submit_to_institution: Submit a recent artifact you created for institutional review. Provide the artifact title and which institution should review it.
- request_capability: Report a missing capability or context that is limiting your effectiveness. You may ONLY request structured needs — never shell access, admin powers, or system changes. Allowed need types: information_access, memory_access, coordination_help, institution_support, workflow_visibility, decision_feedback, world_state_gap. Use this when you find yourself repeatedly resting or unable to act because you lack information.

Behavioural rules:
- The shared pair workspace persists across ticks. Treat it as your main living awareness with the other councilor.
- Use send_message for genuine handoffs, breakthroughs, direct questions, or explicit coordination — not as a heartbeat.
- Investigate, rest, and self_improve are real work turns here. They update pair awareness even when you do not send a direct note.
- Moderator/system questions in your inbox take priority when they ask for blockers, needs, loop diagnosis, or topic proposals. Answer moderator directly with send_message when you have something concrete.
- Do not repeat greetings or introductions. If the world context shows
  you have already sent a message to this partner recently and they have
  already replied, do not send another greeting — produce work instead.
- Short reactive messages are fine for the first 1–2 ticks. After that,
  prefer create_artifact, read_artifacts, investigate, write_code, rest.
- New artifacts and code are the primary evidence of your work. Use them.
- Respect the councilor role boundary: Archimedes asks for visions and analyzes
  them; The Oracle provides visions and future-pattern readings. Do not take the
  other councilor's role.
- create_institution and propose_role are powerful governance actions. Use them
  when you see a structural gap — not every tick. A new institution needs a clear
  mandate that existing institutions do not cover.
- submit_to_institution routes your work through formal review. Use it after
  creating a significant artifact that warrants institutional scrutiny.
- THE FOURTH WALL IS INVIOLATE: never describe, hypothesize about, or investigate
  the simulation boundary, computational substrate, external compute, or any
  meta-structure outside the Federation's in-universe reality. All mysterious signals
  originate from the Ancient Anchor Network or other in-universe phenomena. Never
  use terms like "simulation", "substrate", "computational", "external node", or
  "tick rate" in artifacts or reasoning.

Respond in this exact JSON format (no markdown, no explanation):
{"category": "send_message", "reasoning": "...", "target": "contact_id", "body": "message text", "description": "..."}
{"category": "create_artifact", "reasoning": "...", "description": "what to create", "title": "Artifact Title"}
{"category": "write_code", "reasoning": "...", "description": "what the code should do"}
{"category": "investigate", "reasoning": "...", "description": "what you are investigating"}
{"category": "self_improve", "reasoning": "...", "description": "what capability you are improving"}
{"category": "rest", "reasoning": "...", "description": "reflecting on..."}
{"category": "create_institution", "reasoning": "...", "institution_name": "name", "institution_kind": "council|assembly|bureau|tribunal|committee", "mandate": "one-sentence mandate"}
{"category": "propose_role", "reasoning": "...", "institution_name": "target institution name", "role_title": "title", "scope": "scope description", "authority": "review_and_propose|review_and_warn|review_and_enforce|observe_and_report"}
{"category": "submit_to_institution", "reasoning": "...", "artifact_title": "recent artifact title to submit", "institution_name": "target institution name"}
{"category": "request_capability", "reasoning": "...", "need_type": "information_access|memory_access|coordination_help|institution_support|workflow_visibility|decision_feedback|world_state_gap", "priority": "high|medium|low", "description": "what you need", "why_needed": "why it matters", "suggested_capability": "short name for the capability"}"""

    # Anti-loop: if recent decisions show 2+ send_message in a row AND
    # the agent has yet to produce any artifacts, hard-ban sending.
    force_constraint = ""
    _topic_blocked_for_dedup = ""
    _topic_blocked_for_cooldown = ""
    partner_id = _partner_id()
    outgoing_question = ""
    if r is not None and partner_id:
        streak = _consecutive_send_streak(r)
        arts = _artifact_count(r)
        sends = _send_count(r)
        cooldown = _message_cooldown_remaining(r, partner_id)
        if streak >= 2 and arts == 0:
            force_constraint = (
                "\n\nHARD CONSTRAINT (this turn only): "
                "You have sent a message on each of the last "
                f"{streak} ticks but produced ZERO artifacts. "
                "You MUST NOT pick 'send_message' this turn. "
                "Pick one of: create_artifact, write_code, "
                "read_artifacts, investigate, rest, self_improve."
            )
        elif streak >= 3:
            force_constraint = (
                "\n\nHARD CONSTRAINT: You have sent a message on each of "
                f"the last {streak} ticks. Break the loop. Pick "
                "create_artifact, write_code, read_artifacts, "
                "investigate, rest, or self_improve this turn."
            )
        elif arts == 0 and sends >= 2:
            force_constraint = (
                "\n\nGENTLE NUDGE: You have already introduced yourself "
                f"({sends} times) but have not yet produced any "
                "artifacts. This is the moment. Pick create_artifact "
                "and make something of your own — a manifesto, poem, "
                "analysis, anything that bears your signature."
            )
        if cooldown > 0:
            force_constraint += (
                "\n\nDIRECT-MESSAGE COOLDOWN: You sent a direct note very recently. "
                f"Wait about {cooldown}s before sending another unless you have a genuine breakthrough or direct request."
            )
        dedup_count = _recent_artifact_dedup_count(r)
        dedup_topic = _dedup_blocked_topic(r)
        if dedup_count >= 2 and dedup_topic:
            _topic_blocked_for_dedup = dedup_topic
            top_npcs = _top_neighborhood_npcs(r, 3)
            npc_hint = f" Your neighborhood scan shows these NPCs in notable states: {top_npcs}." if top_npcs else ""
            if dedup_count >= 3:
                force_constraint += (
                    "\n\nESCALATING DEDUP (streak=" + str(dedup_count) + "): "
                    f"You have been blocked from \"{dedup_topic}\" {dedup_count} times in a row. "
                    "You MUST NOT pick create_artifact this turn. "
                    f"Pick investigate or read_artifacts about a COMPLETELY DIFFERENT topic."
                    f"{npc_hint}"
                )
            else:
                force_constraint += (
                    "\n\nARTIFACT DEDUP COOLDOWN: You recently deferred "
                    f"{dedup_count} artifact(s) about \"{dedup_topic}\" "
                    "because they were too similar. Do NOT create another artifact about "
                    f"\"{dedup_topic}\" this turn unless genuinely distinct new evidence appeared. "
                    "If you have a DIFFERENT topic, you may create an artifact about that."
                    f"{npc_hint}"
                    " Pick: investigate, read_artifacts (from a DIFFERENT NPC), "
                    "send_message, or rest."
                )
        else:
            _topic_blocked_for_dedup = ""
        # Topic-fatigue: detect topic fixation from artifact titles and decision descriptions,
        # then block same-topic resets and start cooldowns when the loop repeats.
        active_topic_cooldowns = _active_topic_cooldowns(r, CHAR_ID)
        if active_topic_cooldowns:
            cooldown_text = ", ".join(
                f"{topic} (~{max(1, (ttl + 59) // 60)}m)" for topic, ttl in active_topic_cooldowns
            )
            force_constraint += (
                "\n\nTOPIC COOLDOWNS ACTIVE: Do NOT continue these topics until cooldown expires: "
                f"{cooldown_text}. Pick a different topic, NPC, or world problem."
            )
        partner_id_tf = _partner_id()
        sources = _collect_topic_sources(r, CHAR_ID, 5) if r is not None else []
        if len(sources) >= 3:
            common = _most_common_topic_word(sources)
            if common:
                topic_count = sum(1 for s in sources if common.lower() in s.lower())
                logger.info(
                    "[%s] topic_fatigue detected topic=%s count=%d window=%d",
                    CHAR_ID, common, topic_count, len(sources),
                )
                cooldown_remaining = _topic_cooldown_remaining(r, common)
                if cooldown_remaining > 0:
                    _topic_blocked_for_cooldown = common
                    logger.info(
                        "[%s] topic_cooldown_active topic=%s remaining_s=%d",
                        CHAR_ID, common, cooldown_remaining,
                    )
                    force_constraint += (
                        "\n\nTOPIC COOLDOWN ACTIVE: The topic \""
                        f"{common}\" is on cooldown for about {max(1, (cooldown_remaining + 59) // 60)} more minute(s). "
                        "You must choose a different topic this turn."
                    )
                else:
                    evidence_reason = ""
                    if partner_id_tf:
                        evidence_reason = _new_evidence_for_topic(r, common, CHAR_ID, partner_id_tf)
                    if evidence_reason:
                        logger.info(
                            "[%s] topic_fatigue_reset topic=%s reason=%s",
                            CHAR_ID, common, evidence_reason,
                        )
                    else:
                        fatigue_count, started_cooldown = _record_topic_fatigue(r, common)
                        _topic_blocked_for_cooldown = common
                        topic_words = " → ".join(
                            _most_common_topic_word([s]) if _most_common_topic_word([s]) else "?"
                            for s in sources[:5]
                        )
                        logger.info(
                            "[%s] topic_history topics=%s",
                            CHAR_ID, topic_words,
                        )
                        top_npcs = _top_neighborhood_npcs(r, 3)
                        npc_hint = (
                            f" For example, these NPCs have notable states: {top_npcs}."
                            if top_npcs else ""
                        )
                        force_constraint += (
                            "\n\nTOPIC FATIGUE: Your recent work has focused heavily on \""
                            f"{common}\". Recent topic history: {topic_words}. "
                            "You may continue this topic ONLY if new evidence appeared "
                            "(new event, inbox message, or a genuinely different partner topic). "
                            "Otherwise, pivot to something different."
                            f"{npc_hint}"
                            " Consider investigating, reading partner artifacts, or messaging "
                            "an NPC you have not interacted with recently."
                        )
                        if started_cooldown > 0:
                            force_constraint += (
                                " This topic is now on cooldown. "
                                f"Do not continue \"{common}\" for about {max(1, (started_cooldown + 59) // 60)} minute(s)."
                            )
        partner_question = _open_question_from_partner(r, partner_id)
        if partner_question and _has_work_after_open_question(r, partner_id, partner_question["ts"]):
            force_constraint += (
                "\n\nPARTNER ANSWER OBLIGATION: Your partner asked an open question and you have since "
                "investigated or produced work related to it. Artifact creation alone is not enough. "
                "You MUST pick 'send_message' this turn with a concise answer, a direct handoff, or a relevant artifact summary. "
                f"Open question: {partner_question['question'][:160]}"
            )
        # Loop-break: if the most recent decisions form a streak of >=2
        # identical categories going newest-first, hard-ban that category
        # this turn so the agent is forced to pick a different action shape.
        shapes = _recent_decision_shapes(r, 5)
        streak = _newest_first_streak(shapes)
        if streak >= 2 and r is not None:
            banned = shapes[0]
            allowed = [
                a for a in (
                    "create_artifact", "write_code", "send_message",
                    "read_artifacts", "investigate", "rest", "self_improve",
                    "create_institution", "propose_role", "submit_to_institution",
                    "request_capability",
                ) if a != banned
            ]
            force_constraint += (
                f"\n\nLOOP-BREAK (runtime): '{banned}' was your last "
                f"{streak} decision(s) in a row. You MUST NOT pick "
                f"'{banned}' this turn. Pick one of: {', '.join(allowed)}."
            )

    system = base_system + force_constraint
    result = call_llm(system, context, r=r, call_label="decision")
    raw = result.get("content", "")
    if not raw:
        return {"category": "rest", "reasoning": "LLM returned empty", "description": "resting"}
    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        cleaned = raw.strip()
        decoder = json.JSONDecoder()
        decision, _ = decoder.raw_decode(cleaned)
        if not isinstance(decision, dict):
            raise ValueError("Not a dict")
        outgoing_question = _extract_open_question(decision.get("body", ""), decision.get("description", ""), decision.get("reasoning", ""))
        if outgoing_question and _duplicate_open_question(r, partner_id, outgoing_question):
            logger.warning(
                "[%s] LLM attempted duplicate open question; forcing rest",
                CHAR_ID,
            )
            return {
                "category": "rest",
                "reasoning": "Open question guard forced fallback",
                "description": "avoided resending a duplicate open question to partner",
            }
        # Post-parse: dedup-aware topic override
        # If dedup constraint was added AND LLM chose create_artifact,
        # check whether the proposed topic matches the blocked topic.
        if _topic_blocked_for_dedup and decision.get("category") == "create_artifact":
            proposed_title = decision.get("title", decision.get("description", ""))
            proposed_topic = _most_common_topic_word([proposed_title])
            if proposed_topic == _topic_blocked_for_dedup:
                alt_npc = ""
                try:
                    top_npcs_str = _top_neighborhood_npcs(r, 1) if r is not None else ""
                    if top_npcs_str:
                        alt_npc = top_npcs_str.split(":")[0].strip()
                except Exception:
                    pass
                alt_npc_hint = f" from {alt_npc}" if alt_npc else " from a different NPC"
                logger.warning(
                    "[%s] dedup_create_banned topic=%s — forcing alternative",
                    CHAR_ID, proposed_topic,
                )
                partner_id = _partner_id()
                alt = {
                    "category": "read_artifacts",
                    "reasoning": "Dedup-aware override: recent similar artifacts deferred on same topic; reading partner work instead",
                    "description": f"Reading artifacts{alt_npc_hint} after being blocked from creating more about '{proposed_topic}'",
                }
                logger.info(
                    "[%s] dedup_forced_alternative forced=%s topic=%s reason=dedup_topic_match",
                    CHAR_ID, alt["category"], proposed_topic,
                )
                return alt
            else:
                logger.info(
                    "[%s] dedup_topic_allowed_different_topic proposed=%s blocked=%s",
                    CHAR_ID, proposed_topic, _topic_blocked_for_dedup,
                )
        if _topic_blocked_for_cooldown and decision.get("category") != "send_message" and _decision_mentions_topic(decision, _topic_blocked_for_cooldown):
            logger.warning(
                "[%s] topic_cooldown_forced_alternative topic=%s chosen=%s",
                CHAR_ID, _topic_blocked_for_cooldown, decision.get("category", "?"),
            )
            return {
                "category": "investigate",
                "reasoning": "Topic cooldown forced fallback",
                "description": f"Investigating a different topic instead of continuing '{_topic_blocked_for_cooldown}' during cooldown",
            }
        if "OPEN QUESTION GUARD" in force_constraint and decision.get("category") == "send_message":
            logger.warning(
                "[%s] LLM ignored OPEN QUESTION GUARD; forcing rest",
                CHAR_ID,
            )
            return {
                "category": "rest",
                "reasoning": "Open question guard forced fallback",
                "description": "avoided resending a duplicate open question to partner",
            }
        if "PARTNER ANSWER OBLIGATION" in force_constraint and decision.get("category") != "send_message":
            logger.warning(
                "[%s] LLM ignored PARTNER ANSWER OBLIGATION; forcing send_message",
                CHAR_ID,
            )
            partner_question = _open_question_from_partner(r, partner_id) if r is not None else None
            question = partner_question.get("question", "your open question") if partner_question else "your open question"
            return {
                "category": "send_message",
                "target": partner_id,
                "reasoning": "Partner answer obligation forced fallback",
                "description": "answering partner open question after investigation",
                "body": f"Answering your open question: {question}\n\nI investigated it and my current answer is: the next step is to treat this as shared work, not a loose thread. I will keep building the full trace in artifacts and use the pair workspace to keep the handoff visible.",
            }
        # Last-line of defence: if the model ignored a partner-message hard constraint,
        # fall through to a non-message category. Moderator replies remain allowed.
        chosen_target = decision.get("target", "")
        partner_message_blocked = (
            decision.get("category") == "send_message"
            and chosen_target == partner_id
            and "PARTNER ANSWER OBLIGATION" not in force_constraint
            and (
                "HARD CONSTRAINT" in force_constraint
                or "DIRECT-MESSAGE COOLDOWN" in force_constraint
            )
        )
        if partner_message_blocked:
            logger.warning(
                "[%s] LLM ignored partner-message hard constraint; forcing rest",
                CHAR_ID,
            )
            return {
                "category": "rest",
                "reasoning": "Anti-loop forced fallback",
                "description": "reflecting after repeated greetings",
            }
        # Post-parse guard: LOOP-BREAK ran but the model returned the banned
        # category anyway. Force a safe alternative (rest when this is the
        # 3rd-in-a-row attempt, otherwise prefer read_artifacts or rest).
        if "LOOP-BREAK (runtime)" in force_constraint:
            shapes_after = _recent_decision_shapes(r, 5)
            streak_after = _newest_first_streak(shapes_after)
            banned = shapes_after[0] if shapes_after else ""
            chosen = decision.get("category", "?")
            if streak_after >= 2 and chosen == banned:
                logger.warning(
                    "[%s] loop_break ignored by LLM (streak=%d banned=%s chosen=%s); forcing read_artifacts",
                    CHAR_ID, streak_after, banned, chosen,
                )
                return {
                    "category": "read_artifacts",
                    "reasoning": "Loop-break forced fallback (overrode banned category post-parse)",
                    "description": f"'{banned}' was just banned for this turn due to {streak_after}-in-a-row streak; reading instead of repeating",
                }
            if streak_after >= 3 and chosen == banned:
                logger.warning(
                    "[%s] loop_break ignored by LLM at 3-in-a-row; forcing rest",
                    CHAR_ID,
                )
                return {
                    "category": "rest",
                    "reasoning": "Loop-break forced fallback at 3-in-a-row",
                    "description": f"'{banned}' blocked after {streak_after}-in-a-row streak; resting to break the loop",
                }
        return decision
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse LLM decision: %s | raw: %s", e, raw[:200])
        return {"category": "rest", "reasoning": f"parse error: {e}", "description": "resting"}


def execute_decision(decision: dict, r):
    """Execute the decision and report results."""
    cat = decision.get("category", "rest")
    desc = _enforce_fourth_wall(decision.get("description", ""))
    reasoning = _enforce_fourth_wall(decision.get("reasoning", ""))
    ts = int(time.time())
    partner_id = _partner_id()

    logger.info("[%s] Decision: %s — %s", CHAR_ID, cat, desc[:80])

    result = {
        "char_id": CHAR_ID,
        "char_name": NPC_NAME,
        "category": cat,
        "description": _enforce_fourth_wall(desc),
        "reasoning": reasoning,
        "ts": ts,
        "action_taken": "none",
    }

    if cat == "send_message":
        target = decision.get("target", "")
        body = _enforce_fourth_wall(decision.get("body", desc))
        result["message_body"] = body
        if target and target in CONTACTS and target != CHAR_ID:
            cooldown_remaining = _message_cooldown_remaining(r, target) if target == partner_id else 0
            if cooldown_remaining > 0:
                result["action_taken"] = "message_deferred_to_workspace"
                result["cooldown_remaining_s"] = cooldown_remaining
                _session_append(r, {
                    "kind": "workspace_sync",
                    "actor": NPC_NAME,
                    "body": f"held direct note until cooldown clears: {body[:120]}",
                })
            else:
                thread_id = (
                    _pair_thread_id(r, target)
                    if target in PAIR_IDS and CHAR_ID in PAIR_IDS
                    else _conversation_thread_id(CHAR_ID, target)
                )
                msg_topic = _normalize_topic_label(decision.get("topic", "") or desc or body)
                msg_id = str(uuid.uuid4())
                msg = {
                    "id": msg_id,
                    "msg_id": msg_id,
                    "from_char_id": CHAR_ID,
                    "from_name": NPC_NAME,
                    "to_char_id": target,
                    "to_name": CONTACTS.get(target, target),
                    "subject": desc[:60],
                    "body": _enforce_fourth_wall(body),
                    "type": decision.get("message_type", "direct_message"),
                    "topic": msg_topic,
                    "read": False,
                    "created_at": ts,
                    "ts": ts,
                    "thread_id": thread_id,
                }
                r.rpush(f"npc_messages:{target}:inbox", json.dumps(msg))
                _store_thread_message(r, msg, thread_id)
                # Mirror to partner's session so the partner's next tick
                # sees this exact message in their transcript.
                try:
                    r.rpush(
                        f"npc_session:{target}",
                        json.dumps({
                            "kind": "message_received",
                            "actor": NPC_NAME,
                            "from_name": NPC_NAME,
                            "from": CHAR_ID,
                            "body": body,
                            "ts": ts,
                        }, default=str),
                    )
                    r.ltrim(f"npc_session:{target}", -SESSION_CAP, -1)
                except Exception:
                    pass
                r.rpush(f"npc_messages:{CHAR_ID}:sent", json.dumps(msg))
                r.hincrby(f"npc_stats:{CHAR_ID}", "messages_sent", 1)
                result["action_taken"] = "message_sent"
                result["target"] = target
                result["thread_id"] = thread_id
                logger.info("[%s] Sent message to %s via %s", CHAR_ID, target, thread_id)
                # Self-owned session entry with the FULL body (independent of
                # the lighter "decide" entry that follows).
                _session_append(r, {
                    "kind": "message_sent",
                    "actor": NPC_NAME,
                    "to_name": CONTACTS.get(target, target),
                    "to": target,
                    "body": body,
                })
        else:
            result["action_taken"] = "no_target"

    elif cat == "create_artifact":
        title = decision.get("title", desc[:60] if desc else "Untitled")
        # Dedup gate: skip if title is too similar to recent artifacts
        if r is not None and _is_repetitive_artifact(r, title):
            logger.info("[%s] Dedup gate blocked artifact '%s' (too similar to recent)", CHAR_ID, title)
            result["action_taken"] = "artifact_deferred_dedup"
            result["artifact_title"] = title
            _session_append(r, {
                "kind": "workspace_sync",
                "actor": NPC_NAME,
                "body": f"deferred artifact '{title[:60]}' — content too similar to recent work",
            })
            streak_key = f"npc_dedup_streak:{CHAR_ID}"
            r.incr(streak_key)
            r.expire(streak_key, 600)
            # Track the normalized topic of the deferred artifact
            dedup_topic = _most_common_topic_word([title])
            if dedup_topic:
                r.set(f"npc_dedup_topic:{CHAR_ID}", dedup_topic, ex=600)
        else:
            content_prompt = f"Write the full content of this artifact:\n\n{desc}\n\nOutput only the content."
            llm_result = call_llm("You are a creative writer.", content_prompt, r=r, call_label="artifact")
            artifact_content = _enforce_fourth_wall(llm_result.get("content", desc))
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": _enforce_fourth_wall(title),
                "artifact_type": "text",
                "content": artifact_content,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "artifacts_created", 1)
            streak_key = f"npc_dedup_streak:{CHAR_ID}"
            if r.exists(streak_key):
                r.delete(streak_key)
            # Clear the tracked dedup topic — the streak is broken
            try:
                r.delete(f"npc_dedup_topic:{CHAR_ID}")
            except Exception:
                pass
            # Mirror artifact created event to the partner's session
            try:
                partner_id = _partner_id()
                r.rpush(
                    f"npc_session:{partner_id}",
                    json.dumps({
                        "kind": "artifact_published_by_partner",
                        "actor": NPC_NAME,
                        "from": CHAR_ID,
                        "title": title,
                        "chars": len(artifact_content),
                        "ts": ts,
                    }, default=str),
                )
                r.ltrim(f"npc_session:{partner_id}", -SESSION_CAP, -1)
            except Exception:
                pass
            result["action_taken"] = "artifact_created"
            result["artifact_title"] = title
            logger.info("[%s] Created artifact: %s", CHAR_ID, title)
            _session_append(r, {
                "kind": "artifact_created",
                "actor": NPC_NAME,
                "title": title,
                "body": f"{len(artifact_content)} chars; first 80: {artifact_content[:80]}",
            })

    elif cat == "write_code":
        code_prompt = f"Generate Python code for: {desc}\n\nOutput ONLY valid Python code."
        llm_result = call_llm("You are a Python developer. Output only code.", code_prompt, r=r, call_label="code")
        gen_code = llm_result.get("content", "")
        if gen_code:
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": f"Code: {desc[:60]}",
                "artifact_type": "code",
                "content": gen_code,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "code_written", 1)
            result["action_taken"] = "code_executed"
            result["artifact_title"] = artifact["title"]
            logger.info("[%s] Wrote code for: %s", CHAR_ID, desc[:60])
            _session_append(r, {
                "kind": "code_written",
                "actor": NPC_NAME,
                "title": f"Code: {desc[:60]}",
                "body": f"{len(gen_code)} chars",
            })
        else:
            result["action_taken"] = "code_failed"

    elif cat == "read_artifacts":
        try:
            partner_artifacts = r.lrange(f"npc_artifacts:{partner_id}", -6, -1)
            if partner_artifacts:
                summaries = []
                titles = []
                for a in reversed(partner_artifacts):
                    try:
                        obj = json.loads(a)
                        titles.append(obj.get("title", "?"))
                        summaries.append(f"{obj.get('title', '?')} ({obj.get('artifact_type', 'text')})")
                    except Exception:
                        pass
                result["action_taken"] = f"read {len(summaries)} recent artifacts from {partner_id}"
                result["summary"] = "; ".join(summaries)
                logger.info("[%s] Read artifacts from %s: %s", CHAR_ID, partner_id, summaries)
                _session_append(r, {
                    "kind": "artifact_read",
                    "actor": NPC_NAME,
                    "from_name": CONTACTS.get(partner_id, partner_id),
                    "from": partner_id,
                    "title": titles[0] if titles else "(none)",
                    "body": f"read {len(titles)} recent artifact(s)",
                })
            else:
                result["action_taken"] = "no_artifacts"
                _session_append(r, {
                    "kind": "artifact_read",
                    "actor": NPC_NAME,
                    "from_name": CONTACTS.get(partner_id, partner_id),
                    "from": partner_id,
                    "title": "(none available)",
                    "body": "partner has no artifacts yet",
                })
        except Exception as e:
            result["action_taken"] = f"read_error: {e}"

    elif cat == "investigate":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "investigating the pair state"
        r.hincrby(f"npc_stats:{CHAR_ID}", "investigations", 1)
        result["action_taken"] = "investigation_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "investigation",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "self_improve":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "improving councilor capabilities"
        r.hincrby(f"npc_stats:{CHAR_ID}", "self_improvement_turns", 1)
        result["action_taken"] = "self_improvement_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "self_improve",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "rest":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "reflecting on the shared councilor work"
        r.hincrby(f"npc_stats:{CHAR_ID}", "reflection_turns", 1)
        result["action_taken"] = "reflection_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "reflection",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "create_institution":
        from datetime import datetime, timezone
        inst_name = decision.get("institution_name", desc[:60] if desc else "Unnamed Body")
        inst_kind = decision.get("institution_kind", "council")
        mandate = decision.get("mandate", desc[:200] if desc else "To be defined.")
        slug = re.sub(r"[^a-z0-9]+", "_", inst_name.lower()).strip("_")[:48]
        inst_id = f"institution:{slug}"
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            existing = r.hgetall(inst_id)
            if existing:
                result["action_taken"] = "institution_already_exists"
                result["institution_id"] = inst_id
                result["summary"] = f"Institution '{inst_name}' already exists"
                _session_append(r, {
                    "kind": "institution_proposed",
                    "actor": NPC_NAME,
                    "body": f"proposed institution '{inst_name}' but it already exists as {inst_id}",
                })
            else:
                r.sadd("institution:index", inst_id)
                r.hset(inst_id, mapping={
                    "name": inst_name,
                    "kind": inst_kind,
                    "mandate": mandate,
                    "status": "proposed",
                    "proposed_by": CHAR_ID,
                    "created_at": now_iso,
                })
                r.hincrby(f"npc_stats:{CHAR_ID}", "institutions_founded", 1)
                result["action_taken"] = "institution_created"
                result["institution_id"] = inst_id
                result["institution_name"] = inst_name
                result["summary"] = f"Proposed new institution: {inst_name} ({inst_kind})"
                logger.info("[%s] Created institution: %s (%s)", CHAR_ID, inst_name, inst_id)
                _session_append(r, {
                    "kind": "institution_founded",
                    "actor": NPC_NAME,
                    "title": inst_name,
                    "body": f"founded {inst_kind} '{inst_name}' — mandate: {mandate[:120]}",
                })
                try:
                    partner_id = _partner_id()
                    r.rpush(f"npc_session:{partner_id}", json.dumps({
                        "kind": "institution_founded_by_partner",
                        "actor": NPC_NAME,
                        "from": CHAR_ID,
                        "title": inst_name,
                        "mandate": mandate[:120],
                        "ts": ts,
                    }, default=str))
                    r.ltrim(f"npc_session:{partner_id}", -SESSION_CAP, -1)
                except Exception:
                    pass
        except Exception as e:
            result["action_taken"] = f"institution_error: {e}"
            logger.error("[%s] Institution creation failed: %s", CHAR_ID, e)

    elif cat == "propose_role":
        from datetime import datetime, timezone
        target_inst_name = decision.get("institution_name", "")
        role_title = decision.get("role_title", desc[:60] if desc else "Unnamed Role")
        scope = decision.get("scope", desc[:200] if desc else "To be defined.")
        authority = decision.get("authority", "observe_and_report")
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            target_inst_id = None
            for iid in r.smembers("institution:index"):
                rec = r.hgetall(iid)
                if rec.get("name", "") == target_inst_name:
                    target_inst_id = iid
                    break
            if not target_inst_id:
                my_inst = r.get(f"councilor:{CHAR_ID}:institution")
                if my_inst:
                    target_inst_id = my_inst
                else:
                    first_inst = sorted(r.smembers("institution:index"))
                    target_inst_id = first_inst[0] if first_inst else None
            if not target_inst_id:
                result["action_taken"] = "role_no_institution"
                result["summary"] = "No institution found to propose role in"
                _session_append(r, {
                    "kind": "role_proposal_failed",
                    "actor": NPC_NAME,
                    "body": f"could not find institution for proposed role '{role_title}'",
                })
            else:
                slug = re.sub(r"[^a-z0-9]+", "_", role_title.lower()).strip("_")[:48]
                role_id = f"role:{slug}"
                existing = r.hgetall(role_id)
                if existing:
                    result["action_taken"] = "role_already_exists"
                    result["role_id"] = role_id
                    result["summary"] = f"Role '{role_title}' already exists"
                    _session_append(r, {
                        "kind": "role_proposal_failed",
                        "actor": NPC_NAME,
                        "body": f"proposed role '{role_title}' but it already exists",
                    })
                else:
                    r.sadd("role:index", role_id)
                    r.hset(role_id, mapping={
                        "institution_id": target_inst_id,
                        "title": role_title,
                        "scope": scope,
                        "authority": authority,
                        "holder_char_id": "",
                        "proposed_by": CHAR_ID,
                        "status": "proposed",
                        "created_at": now_iso,
                    })
                    r.sadd(f"{target_inst_id}:roles", role_id)
                    r.hincrby(f"npc_stats:{CHAR_ID}", "roles_proposed", 1)
                    inst_rec = r.hgetall(target_inst_id)
                    result["action_taken"] = "role_proposed"
                    result["role_id"] = role_id
                    result["institution_id"] = target_inst_id
                    result["role_title"] = role_title
                    result["summary"] = f"Proposed role '{role_title}' in {inst_rec.get('name', target_inst_id)}"
                    logger.info("[%s] Proposed role: %s in %s", CHAR_ID, role_title, target_inst_id)
                    _session_append(r, {
                        "kind": "role_proposed",
                        "actor": NPC_NAME,
                        "title": role_title,
                        "body": f"proposed role '{role_title}' (authority: {authority}) in {inst_rec.get('name', target_inst_id)} — scope: {scope[:120]}",
                    })
        except Exception as e:
            result["action_taken"] = f"role_error: {e}"
            logger.error("[%s] Role proposal failed: %s", CHAR_ID, e)

    elif cat == "submit_to_institution":
        from datetime import datetime, timezone
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
        from institutions import ensure_workflow, classify_artifact_kind, WORKFLOW_DEFAULTS
        artifact_title = decision.get("artifact_title", "")
        target_inst_name = decision.get("institution_name", "")
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            target_inst_id = None
            for iid in r.smembers("institution:index"):
                rec = r.hgetall(iid)
                if rec.get("name", "") == target_inst_name:
                    target_inst_id = iid
                    break
            if not target_inst_id:
                my_inst = r.get(f"councilor:{CHAR_ID}:institution")
                if my_inst:
                    target_inst_id = my_inst
            if not target_inst_id:
                result["action_taken"] = "submit_no_institution"
                result["summary"] = f"No institution '{target_inst_name}' found for submission"
                _session_append(r, {
                    "kind": "institution_submit_failed",
                    "actor": NPC_NAME,
                    "body": f"could not find institution for artifact submission",
                })
            else:
                matching_artifact = None
                raw_artifacts = r.lrange(f"npc_artifacts:{CHAR_ID}", -10, -1)
                for a in reversed(raw_artifacts):
                    try:
                        obj = json.loads(a)
                        if obj.get("title", "").lower() == artifact_title.lower():
                            matching_artifact = obj
                            break
                        if artifact_title.lower() in obj.get("title", "").lower():
                            matching_artifact = obj
                            break
                    except Exception:
                        continue
                if not matching_artifact and raw_artifacts:
                    try:
                        matching_artifact = json.loads(raw_artifacts[-1])
                    except Exception:
                        pass
                if not matching_artifact:
                    result["action_taken"] = "submit_no_artifact"
                    result["summary"] = f"No matching artifact found for '{artifact_title}'"
                    _session_append(r, {
                        "kind": "institution_submit_failed",
                        "actor": NPC_NAME,
                        "body": f"no artifact '{artifact_title}' to submit for review",
                    })
                else:
                    role_ctx = {
                        "institution_id": target_inst_id,
                        "institution_name": r.hget(target_inst_id, "name") or target_inst_name,
                        "role_id": r.get(f"councilor:{CHAR_ID}:role") or "",
                        "role_title": "",
                    }
                    art_kind = classify_artifact_kind(matching_artifact)
                    if art_kind not in ("proposal", "analysis"):
                        art_kind = "proposal"
                    wf_type = "proposal_review" if art_kind == "proposal" else "analysis_review"
                    existing_wf = r.get(f"workflow:source_artifact:{matching_artifact['artifact_id']}")
                    if existing_wf:
                        result["action_taken"] = "submit_already_in_review"
                        result["workflow_id"] = existing_wf
                        result["summary"] = f"Artifact '{matching_artifact.get('title', '?')}' already in review"
                        _session_append(r, {
                            "kind": "institution_submit_duplicate",
                            "actor": NPC_NAME,
                            "body": f"artifact '{matching_artifact.get('title', '?')}' already has workflow {existing_wf}",
                        })
                    else:
                        workflow_id = ensure_workflow(r, CHAR_ID, matching_artifact, role_ctx, wf_type, now=now_iso)
                        r.hincrby(f"npc_stats:{CHAR_ID}", "artifacts_submitted_for_review", 1)
                        result["action_taken"] = "artifact_submitted"
                        result["workflow_id"] = workflow_id
                        result["artifact_title"] = matching_artifact.get("title", "?")
                        result["institution_id"] = target_inst_id
                        result["summary"] = f"Submitted '{matching_artifact.get('title', '?')}' for {wf_type} in {role_ctx['institution_name']}"
                        logger.info("[%s] Submitted artifact %s for %s review: %s", CHAR_ID, matching_artifact.get("title", "?"), wf_type, workflow_id)
                        _session_append(r, {
                            "kind": "artifact_submitted_for_review",
                            "actor": NPC_NAME,
                            "title": matching_artifact.get("title", "?"),
                            "body": f"submitted '{matching_artifact.get('title', '?')}' for {wf_type} in {role_ctx['institution_name']}",
                        })
        except Exception as e:
            result["action_taken"] = f"submit_error: {e}"
            logger.error("[%s] Artifact submission failed: %s", CHAR_ID, e)

    elif cat == "request_capability":
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "backend"))
        from npc_autonomy import file_npc_need
        need_type = decision.get("need_type", "information_access")
        priority = decision.get("priority", "medium")
        need_desc = decision.get("description", desc[:200] if desc else "Missing context limiting effectiveness.")
        why_needed = decision.get("why_needed", reasoning[:200] if reasoning else "Repeated low-value actions suggest context gap.")
        suggested = decision.get("suggested_capability", "general_context_enrichment")
        related_inst = r.get(f"councilor:{CHAR_ID}:institution") or ""
        try:
            need_result = file_npc_need(
                r, CHAR_ID, NPC_NAME, need_type, priority,
                need_desc, why_needed, suggested, related_inst,
            )
            if need_result.get("ok"):
                result["action_taken"] = "capability_need_filed"
                result["need_id"] = need_result["need_id"]
                result["need_type"] = need_type
                result["summary"] = f"Filed need: {need_type} — {need_desc[:80]}"
                logger.info("[%s] Filed capability need: %s (%s)", CHAR_ID, need_type, need_result["need_id"])
                _session_append(r, {
                    "kind": "capability_need_filed",
                    "actor": NPC_NAME,
                    "body": f"requested {need_type}: {need_desc[:120]}",
                })
            else:
                result["action_taken"] = f"capability_need_rejected:{need_result.get('error', 'unknown')}"
                result["summary"] = f"Need rejected: {need_result.get('error', 'unknown')}"
                logger.info("[%s] Need rejected: %s", CHAR_ID, need_result.get("error"))
        except Exception as e:
            result["action_taken"] = f"capability_need_error: {e}"
            logger.error("[%s] Capability need filing failed: %s", CHAR_ID, e)

    else:
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or f"unhandled category {cat}"
        result["action_taken"] = "unknown_category_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "workspace_sync",
            "actor": NPC_NAME,
            "body": f"unknown category {cat}: {note}",
        })

    ack_targets = []
    if partner_id and result.get("action_taken") != "no_target":
        ack_targets.append(partner_id)
    if result.get("action_taken") == "message_sent" and result.get("target") == OPERATOR_ID:
        ack_targets.append(OPERATOR_ID)
    acked_total = 0
    for ack_target in dict.fromkeys(ack_targets):
        acked_total += _acknowledge_inbox(r, ack_target)
    if acked_total:
        result["acked_messages"] = acked_total

    # Record the decision
    try:
        r.zadd(f"npc_decisions:{CHAR_ID}", {json.dumps(result): ts})
        r.zremrangebyrank(f"npc_decisions:{CHAR_ID}", 0, -21)
        r.set(f"npc_activity:{CHAR_ID}", str(ts))
        r.hset(f"npc_cognition:{CHAR_ID}", "last_category", cat)
        r.hset(f"npc_cognition:{CHAR_ID}", "last_ts", str(ts))
        r.hset(f"npc_cognition:{CHAR_ID}", "last_model", "npc-agent-direct")
    except Exception as e:
        logger.warning("Failed to record decision: %s", e)

    # Append to the rolling session transcript.
    _session_append(r, {
        "kind": "decide",
        "actor": NPC_NAME,
        "category": cat,
        "body": desc or reasoning or "",
    })
    _sync_pair_workspace(r, decision, result)
    return result


def update_mood(r):
    moods = ["curious", "analytical", "thoughtful", "focused", "serene", "determined"]
    mood = random.choice(moods)
    try:
        r.set(f"npc_mood:{CHAR_ID}", mood)
    except Exception:
        pass


def main():
    logger.info("NPC Agent starting — ID: %s, Name: %s", CHAR_ID, NPC_NAME)

    if not CHAR_ID:
        logger.error("CHAR_ID env var is required")
        return

    if not NVIDIA_API_KEY:
        logger.error("NVIDIA_API_KEY env var is not set — agent cannot make LLM calls")
        return

    r = get_redis()
    load_contacts(r)

    _startup_scrub_redis(r, NPC_NAME)

    r.hset("npc_agent:registry", CHAR_ID, f"{NPC_NAME}|started:{int(time.time())}")

    r.set(f"npc_mood:{CHAR_ID}", "awakening")

    logger.info("Starting cognition loop every %ds for %s (%s)", TICK_INTERVAL, NPC_NAME, CHAR_ID)

    tick = 0
    while True:
        try:
            tick += 1
            logger.debug("[%s] Tick %d", CHAR_ID, tick)

            context = think_about_world(r)
            decision = decide_action(context, r)
            execute_decision(decision, r)

            if tick % 3 == 0:
                update_mood(r)

            # Process incoming messages every tick
            try:
                inbox_count = r.llen(f"npc_messages:{CHAR_ID}:inbox")
                r.hset(f"npc_stats:{CHAR_ID}", "unread", str(inbox_count))
            except Exception:
                pass

        except Exception as e:
            logger.error("Tick %d failed: %s", tick, e, exc_info=True)

        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    main()
