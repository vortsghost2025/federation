"""
NPC Context Builder — assembles world context for each tick.

Extracted from npc_agent.py during Phase 1 refactoring.
All functions that build the "what's happening around me" picture
live here: neighborhood snapshots, event promotion, topic fatigue,
cosmic horizon, and the main think_about_world() assembler.
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger("npc_context")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)


# ── Topic fatigue env vars ─────────────────────────────────────
TOPIC_FATIGUE_WINDOW_MINUTES = int(os.environ.get("TOPIC_FATIGUE_WINDOW_MINUTES", "60"))
TOPIC_FATIGUE_THRESHOLD = int(os.environ.get("TOPIC_FATIGUE_THRESHOLD", "3"))
TOPIC_COOLDOWN_MINUTES = int(os.environ.get("TOPIC_COOLDOWN_MINUTES", "60"))
PAIR_THREAD_PREVIEW = int(os.environ.get("PAIR_THREAD_PREVIEW", "4"))


# ── Full NPC roster for neighborhood awareness ──
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

_STATUS_WEIGHT = {
    "corrupted": 10,
    "scheming": 8,
    "alarmed": 6,
    "unsettled": 5,
    "hidden": 4,
    "traveling": 3,
    "dormant": 2,
    "active": 0,
}

_ALERT_MOODS = {
    "alarmed", "scheming", "calculating", "unsettled", "worried",
    "suspicious", "frustrated", "confidential", "restless",
    "battle-ready", "opportunistic", "troubled", "distracted",
}

_EVENT_KEYWORDS = {
    "betray", "corruption", "heist", "warning", "sabotage", "ritual",
    "disappearance", "cover-up", "undermine", "black market", "covert",
    "intel breach", "prophecy", "anomaly", "resource discovery",
    "exploration", "faction instability", "conflict", "attack", "defense",
}

_TOPIC_STOP_WORDS = {"the", "of", "and", "a", "an", "to", "in", "for", "on", "with",
                      "from", "by", "at", "is", "it", "as", "be", "or", "that", "this",
                      "its", "are", "was", "but", "not", "all", "report", "analysis",
                      "assessment", "strategic", "recommendation", "overview",
                      "comprehensive", "updated", "interim", "final", "review",
                      "implication", "response", "data", "summary", "integration",
                      "federation"}

_COSMIC_VISIONARY = {"char_306"}
_COSMIC_SCIENTIFIC = {"char_001", "char_104", "char_105", "char_404", "char_406"}
_COSMIC_FRONTIER = {"char_005", "char_107", "char_301", "char_403"}


# ── Lazy imports to avoid circular dependency ──
# npc_redis_helpers imports nothing from this module, but npc_agent.py
# imports from both. Lazy imports inside functions keep the import
# graph acyclic at load time.
def _rh():
    from npc_redis_helpers import (
        _partner_id,
        _recent_decisions,
        _compact_text,
        _pair_state,
        _pair_recent_journal,
        _recent_thread_messages,
        _session_transcript,
    )
    return _partner_id, _recent_decisions, _compact_text, _pair_state, _pair_recent_journal, _recent_thread_messages, _session_transcript


# ══════════════════════════════════════════════════════════════════
#  Neighborhood & world awareness
# ══════════════════════════════════════════════════════════════════

def neighborhood_snapshot(r, max_chars: int = 400, char_id: str = "") -> str:
    """Return a compact summary of what the OTHER NPCs are doing.

    Reads npc_state:* (status, corruption, last_updated) and npc_mood:* for
    all 39 NPCs.  Skips self and pair partner.  Ranks by threat-relevance.
    Returns up to max_chars of formatted text.
    """
    cid = char_id or CHAR_ID
    _partner_id, *_ = _rh()
    partner_id = _partner_id(char_id=cid)
    logger.info("[%s] neighborhood: starting snapshot...", cid)
    entries: list[tuple[int, str, str, str]] = []

    try:
        all_state_keys = list(r.scan_iter(match="npc_state:*"))
        logger.info("[%s] neighborhood: found %d npc_state keys", cid, len(all_state_keys))

        pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            pipe.hgetall(k)
        states = pipe.execute()

        mood_pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            kcid = k.split(":", 1)[1]
            mood_pipe.get(f"npc_mood:{kcid}")
        moods = mood_pipe.execute()

        for key, state, mood in zip(all_state_keys, states, moods):
            if not state:
                continue
            kcid = key.split(":", 1)[1]
            if kcid == cid or kcid == partner_id or kcid not in _NPC_ROSTER:
                continue

            name, faction = _NPC_ROSTER[kcid]
            status = state.get("status", "active")
            corruption = float(state.get("corruption_level", 0))
            rumor = float(state.get("rumor_level", 0))
            mood_str = (mood or "")

            score = _STATUS_WEIGHT.get(status, 0) * 2
            score += int(corruption * 6)
            score += int(rumor * 2)
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

            entries.append((score, kcid, name, line))

    except Exception as exc:
        logger.warning("[%s] neighborhood snapshot failed: %s", cid, exc)
        return ""

    if entries:
        logger.info("[%s] neighborhood: %d notable NPCs: %s", cid, len(entries),
                    "; ".join(e[3] for e in entries[:5]))

    if not entries:
        return ""

    entries.sort(key=lambda e: e[0], reverse=True)

    lines = ["Neighborhood (other NPCs, most notable first):"]
    budget = max_chars - len(lines[0]) - 2
    for _score, _cid, _name, line in entries:
        if budget - len(line) - 2 < 0:
            break
        lines.append(f"  {line}")
        budget -= len(line) + 2

    result = "\n".join(lines) if len(lines) > 1 else ""
    logger.info("[%s] neighborhood: returning %d chars", cid, len(result))
    return result


# ══════════════════════════════════════════════════════════════════
#  Event Promotion Bridge
# ══════════════════════════════════════════════════════════════════

def hash_event(event: dict) -> str:
    """Generate stable hash for event deduplication."""
    char_id = event.get("char_id", "") or event.get("source_char_id", "")
    action = event.get("action_type", "") or event.get("interaction_type", "") or event.get("event_type", "")
    ts = event.get("ts", 0) or event.get("timestamp", 0)
    ts_bucket = int(ts // 60)
    return f"{char_id}:{action}:{ts_bucket}"


def promote_events_to_inbox(r, max_events: int = 5, max_chars: int = 120, char_id: str = "") -> list[str]:
    """Read recent npc_world_events, filter significant ones, push to councilor inbox."""
    cid = char_id or CHAR_ID
    promoted = []
    try:
        events = r.zrange("npc_world_events", -20, -1, withscores=False)
        logger.info("[%s] event promotion: checking %d events", cid, len(events))
        for event_json in events:
            if len(promoted) >= max_events:
                break
            try:
                event = json.loads(event_json)
            except:
                continue

            action = event.get("action_type", "") or event.get("interaction_type", "") or event.get("event_type", "")
            desc = event.get("description", "")
            char_name = event.get("char_name") or event.get("source_char_name") or event.get("name", "Unknown")
            event_type = event.get("event_type", "")
            game_event_type = event.get("game_event_type", "")

            text_to_search = f"{action} {desc} {event_type} {game_event_type}".lower()

            if not any(kw in text_to_search for kw in _EVENT_KEYWORDS):
                continue

            event_hash = hash_event(event)
            dedup_key = f"councilor_promoted_event:{cid}:{event_hash}"
            if r.exists(dedup_key):
                logger.debug("[%s] event promotion: skipping duplicate %s", cid, event_hash)
                continue

            summary = f"{char_name}: {desc[:max_chars]}"
            promoted.append(summary)
            logger.info("[%s] event promotion: promoted '%s'", cid, summary[:50])

            r.set(dedup_key, "1", ex=86400)

        return promoted
    except Exception as e:
        logger.warning("[%s] event promotion failed: %s", cid, e)
        return []


# ══════════════════════════════════════════════════════════════════
#  Topic fatigue & cooldown
# ══════════════════════════════════════════════════════════════════

def most_common_topic_word(titles: list[str]) -> str:
    """Return the most frequently repeated content word across artifact titles."""
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


def normalize_topic_label(text: str) -> str:
    return most_common_topic_word([text]) if text else ""


def topic_counter_key(topic: str, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_topic_fatigue:{cid}:{topic}"


def topic_cooldown_key(topic: str, char_id: str = "") -> str:
    cid = char_id or CHAR_ID
    return f"npc_topic_cooldown:{cid}:{topic}"


def topic_cooldown_remaining(r, topic: str, char_id: str = "") -> int:
    if r is None or not topic:
        return 0
    try:
        ttl = int(r.ttl(topic_cooldown_key(topic, char_id)) or 0)
        return max(ttl, 0)
    except Exception:
        return 0


def active_topic_cooldowns(r, char_id: str = "", limit: int = 3) -> list[tuple[str, int]]:
    cid = char_id or CHAR_ID
    if r is None or not cid:
        return []
    prefix = f"npc_topic_cooldown:{cid}:"
    rows: list[tuple[str, int]] = []
    try:
        keys = list(r.scan_iter(match=f"{prefix}*"))
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


def record_topic_fatigue(r, topic: str, window_minutes: int = TOPIC_FATIGUE_WINDOW_MINUTES,
                          threshold: int = TOPIC_FATIGUE_THRESHOLD,
                          cooldown_minutes: int = TOPIC_COOLDOWN_MINUTES,
                          char_id: str = "") -> tuple[int, int]:
    cid = char_id or CHAR_ID
    if r is None or not topic:
        return 0, 0
    counter_key = topic_counter_key(topic, cid)
    cooldown_key = topic_cooldown_key(topic, cid)
    try:
        count = int(r.incr(counter_key) or 0)
        r.expire(counter_key, max(window_minutes, 1) * 60)
    except Exception:
        return 0, 0
    existing = topic_cooldown_remaining(r, topic, cid)
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
            cid, topic, cooldown_minutes,
        )
        return count, duration_seconds
    return count, 0


def text_mentions_topic(text: str, topic: str) -> bool:
    if not text or not topic:
        return False
    normalized = normalize_topic_label(text)
    if normalized:
        return normalized == topic
    return topic.lower() in text.lower()


def decision_mentions_topic(decision: dict, topic: str) -> bool:
    if not decision or not topic:
        return False
    fields = [
        decision.get("title", ""),
        decision.get("description", ""),
        decision.get("body", ""),
        decision.get("reasoning", ""),
    ]
    return any(text_mentions_topic(field, topic) for field in fields if field)


def collect_topic_sources(r, char_id: str, n: int = 5) -> list[str]:
    """Collect recent artifact titles AND decision descriptions for topic analysis."""
    sources = []
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


def new_evidence_for_topic(r, topic: str, char_id: str, partner_id: str, window_minutes: int = 120) -> str:
    """Check if fresh evidence exists for a topic. Returns reason string or empty."""
    cid = char_id or CHAR_ID
    topic_lower = topic.lower()
    now = time.time()
    window_sec = window_minutes * 60

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

    try:
        partner_arts = r.lrange(f"npc_artifacts:{partner_id}", -5, -1)
        for art in partner_arts:
            try:
                a = json.loads(art) if isinstance(art, str) else art
                title = (a.get("title", "") if isinstance(a, dict) else "")
                created = a.get("created_at", 0) if isinstance(a, dict) else 0
                normalized_partner_topic = normalize_topic_label(title)
                if topic_lower in title.lower() and (now - created) < window_sec:
                    if normalized_partner_topic == topic_lower or topic_lower in (a.get("description", "") if isinstance(a, dict) else "").lower():
                        logger.info(
                            "[%s] topic_fatigue_reset_blocked reason=same_partner_topic topic=%s",
                            cid, topic_lower,
                        )
                        continue
                    return "partner_artifact"
            except Exception:
                pass
    except Exception:
        pass

    try:
        msgs = r.lrange(f"npc_messages:{cid}:inbox", -5, -1)
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


# ══════════════════════════════════════════════════════════════════
#  Lightweight neighborhood (for anti-loop redirects)
# ══════════════════════════════════════════════════════════════════

def top_neighborhood_npcs(r, n: int = 3, char_id: str = "") -> str:
    """Return a short comma-separated string of the top N most notable NPCs."""
    cid = char_id or CHAR_ID
    _partner_id_fn, *_ = _rh()
    try:
        all_state_keys = list(r.scan_iter(match="npc_state:*"))
        pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            pipe.hgetall(k)
        states = pipe.execute()
        mood_pipe = r.pipeline(transaction=False)
        for k in all_state_keys:
            kcid = k.split(":", 1)[1]
            mood_pipe.get(f"npc_mood:{kcid}")
        moods = mood_pipe.execute()

        entries = []
        for key, state, mood in zip(all_state_keys, states, moods):
            if not state:
                continue
            kcid = key.split(":", 1)[1]
            if kcid == cid or kcid == _partner_id_fn(char_id=cid) or kcid not in _NPC_ROSTER:
                continue
            name, faction = _NPC_ROSTER[kcid]
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


# ══════════════════════════════════════════════════════════════════
#  Cosmic Horizon
# ══════════════════════════════════════════════════════════════════

def cosmic_horizon(char_id: str) -> str:
    """Return role-filtered cosmic context string, or empty string."""
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


# ══════════════════════════════════════════════════════════════════
#  Dedup helpers (used by both think_about_world and decide_action)
# ══════════════════════════════════════════════════════════════════

def recent_artifact_dedup_count(r, char_id: str = "") -> int:
    """Return consecutive artifact dedup block count (10 min TTL)."""
    cid = char_id or CHAR_ID
    try:
        val = r.get(f"npc_dedup_streak:{cid}")
        return int(val) if val is not None else 0
    except Exception:
        return 0


def dedup_blocked_topic(r, char_id: str = "") -> str:
    """Return the normalized topic of the most recent dedup-deferred artifact."""
    cid = char_id or CHAR_ID
    try:
        key = f"npc_dedup_topic:{cid}"
        if not r.exists(key):
            return ""
        raw = r.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return (raw or "").strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════
#  Councilor memory loading (Phase 1 bridge)
# ══════════════════════════════════════════════════════════════════

def load_councilor_memories(r, char_id: str = "") -> str:
    """Load councilor memories formatted for prompt injection.

    Returns a '## Your Memories' section string, or empty string if
    no memories exist or the bridge is not available.
    """
    cid = char_id or CHAR_ID
    try:
        from npc_memory_bridge import CouncilorMemory
        mem = CouncilorMemory(r, cid)
        tick = int(time.time())
        return mem.get_context_for_prompt(tick)
    except Exception as e:
        logger.debug("[%s] load_councilor_memories skipped: %s", cid, e)
        return ""


# ══════════════════════════════════════════════════════════════════
#  Main context assembler
# ══════════════════════════════════════════════════════════════════

def think_about_world(r, contacts: dict | None = None, char_id: str = "") -> str:
    """Gather recent events, messages, and artifacts for context.

    Target: <2000 chars total. Each tick surfaces:
      - mood + timestamp
      - 3 newest incoming messages (header + 80 char body)
      - 3 newest outgoing messages
      - last 3 decision categories with timestamps
      - artifact count, partner mood, pair workspace
      - cosmic horizon, neighborhood, event promotion, topic cooldowns
      - persistent session transcript
    """
    cid = char_id or CHAR_ID
    _contacts = contacts or {}
    _partner_id_fn, _recent_decisions, _compact_text, _pair_state, _pair_recent_journal, _recent_thread_messages_fn, _session_transcript = _rh()

    logger.info("[%s] think_about_world: building context...", cid)
    parts = [f"--- {NPC_NAME} ({cid}) — Tick@{time.strftime('%H:%M:%S')} ---"]

    try:
        mood = r.get(f"npc_mood:{cid}") or "neutral"
        parts.append(f"Mood: {mood}")
    except Exception:
        pass

    try:
        inbox = r.lrange(f"npc_messages:{cid}:inbox", -3, -1)
        inbox_total = r.llen(f"npc_messages:{cid}:inbox")
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

    try:
        sent = r.lrange(f"npc_messages:{cid}:sent", -3, -1)
        sent_total = r.llen(f"npc_messages:{cid}:sent")
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

    try:
        decs = _recent_decisions(r, 3, char_id=cid)
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

    try:
        arts = r.llen(f"npc_artifacts:{cid}")
        if arts:
            parts.append(f"You have produced {arts} artifacts.")
        else:
            parts.append("You have produced 0 artifacts yet.")
    except Exception:
        pass

    try:
        partner_id = _partner_id_fn(char_id=cid)
        partner_state = r.get(f"npc_mood:{partner_id}") or "unknown"
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
        partner_id = _partner_id_fn(char_id=cid)
        ps = _pair_state(r, partner_id, char_id=cid)
        if ps:
            parts.append("Shared pair workspace:")
            conv_raw = ps.get("convergence_state", "")
            conv = None
            if conv_raw and isinstance(conv_raw, str):
                try:
                    conv = json.loads(conv_raw)
                except Exception:
                    pass
            if conv:
                parts.append("  PAIR CONVERGENCE STATE (revise from here, do not restart from original question):")
                if conv.get("current_best_answer"):
                    parts.append(f"    Current best answer: {conv['current_best_answer'][:200]}")
                if conv.get("agreement"):
                    parts.append(f"    Agreement: {conv['agreement'][:200]}")
                if conv.get("disagreement"):
                    parts.append(f"    Disagreement: {conv['disagreement'][:200]}")
                if conv.get("next_question"):
                    parts.append(f"    Next question: {conv['next_question'][:200]}")
            if ps.get("shared_goal"):
                parts.append(f"  Goal: {ps['shared_goal'][:120]}")
            if ps.get("current_topic"):
                parts.append(f"  Current topic: {ps['current_topic'][:120]}")
            partner_focus = ps.get(f"focus_{partner_id}", "")
            if partner_focus:
                parts.append(f"  Partner focus: {partner_focus[:120]}")
            self_focus = ps.get(f"focus_{cid}", "")
            if self_focus:
                parts.append(f"  Your last focus: {self_focus[:120]}")
            if ps.get("open_question"):
                q_from = ps.get("open_question_from", "")
                q_label = _contacts.get(q_from, "Partner") if q_from else "Partner"
                parts.append(f"  Open question from {q_label}: {ps['open_question'][:120]}")
            if ps.get("last_open_question_sent_to_partner") and not ps.get("partner_answer"):
                parts.append(f"  Your open question awaiting answer: {ps['last_open_question_sent_to_partner'][:120]}")
            if ps.get("last_message_preview"):
                parts.append(f"  Last direct note: {ps['last_message_preview'][:120]}")

            recent_journal = _pair_recent_journal(r, partner_id, 3, char_id=cid)
            if recent_journal:
                parts.append("Shared journal:")
                for entry in recent_journal:
                    actor_id = entry.get("actor", "")
                    actor_label = "You" if actor_id == cid else _contacts.get(actor_id, entry.get("actor_name", actor_id or "?"))
                    parts.append(f"  - {actor_label}: {entry.get('summary', '')[:100]}")

            active_thread = ps.get("active_thread_id", "")
            thread_messages = _recent_thread_messages_fn(r, active_thread, PAIR_THREAD_PREVIEW, char_id=cid)
            if thread_messages:
                parts.append("Active direct thread:")
                for msg in thread_messages:
                    if msg.get("from_char_id") == cid:
                        parts.append(f"  → You to {msg.get('to_name', '?')}: {msg.get('body', '')[:80]}")
                    else:
                        parts.append(f"  ← {msg.get('from_name', '?')}: {msg.get('body', '')[:80]}")
    except Exception:
        pass

    contacts_str = "; ".join(f"{c}: {name}" for c, name in _contacts.items() if c != cid)
    parts.append(f"Contacts: {contacts_str}")

    horizon = cosmic_horizon(cid)
    if horizon:
        parts.append(horizon)

    neighborhood = neighborhood_snapshot(r, char_id=cid)
    if neighborhood:
        parts.append(neighborhood)

    logger.info("[%s] think_about_world: calling event promotion", cid)
    promoted = promote_events_to_inbox(r, char_id=cid)
    logger.info("[%s] think_about_world: event promotion returned %d", cid, len(promoted))
    if promoted:
        parts.append("Recent significant world events:\n" + "\n".join(f"  • {e}" for e in promoted))

    try:
        active_cooldowns = active_topic_cooldowns(r, cid)
        dedup_streak = recent_artifact_dedup_count(r, cid)
        dedup_topic = dedup_blocked_topic(r, cid)
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

    try:
        role_id = r.get(f"councilor:{cid}:role")
        inst_id = r.get(f"councilor:{cid}:institution")
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

    transcript = _session_transcript(r, contacts=_contacts, char_id=cid)
    if transcript:
        parts.append(f"── Your recent session (last few hours) ──\n{transcript}")

    councilor_memories = load_councilor_memories(r, cid)
    if councilor_memories:
        parts.append(councilor_memories)

    return "\n".join(parts)
