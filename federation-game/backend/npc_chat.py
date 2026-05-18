"""FEDERATION GAME - NPC LLM Chat Module
Phase 4a: Chat ↔ Autonomy Bridge
- Sentiment classification on player messages
- Opinion and mood updates after each chat
- Enriched system prompt with mood, thoughts, world events

Phase 2: Redis-backed persistent conversation memory
NPCs remember previous conversations with each player via Redis.
Conversation history is included in the system prompt so the LLM
can reference past exchanges naturally.
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any

import redis
import logging

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

MAX_HISTORY_TURNS = 20
HISTORY_TTL = 86400 * 7

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# --- SENTIMENT CLASSIFIER ---

_POSITIVE_WORDS = {
    "thanks",
    "thank",
    "help",
    "helpful",
    "friend",
    "ally",
    "trust",
    "love",
    "great",
    "good",
    "wonderful",
    "amazing",
    "awesome",
    "kind",
    "generous",
    "please",
    "appreciate",
    "respect",
    "admire",
    "honored",
    "glad",
    "happy",
    "loyal",
    "support",
    "together",
    "save",
    "protect",
    "defend",
    "share",
    "agree",
    "yes",
    "absolutely",
    "definitely",
    "certainly",
    "of course",
    "brave",
    "hero",
    "heroic",
    "noble",
    "wise",
    "brilliant",
    "fair",
    "gift",
    "reward",
    "quest",
    "complete",
    "success",
    "victory",
}

_NEGATIVE_WORDS = {
    "hate",
    "kill",
    "destroy",
    "betray",
    "lie",
    "liar",
    "fool",
    "stupid",
    "enemy",
    "enemy",
    "threat",
    "danger",
    "attack",
    "fight",
    "war",
    "fear",
    "afraid",
    "distrust",
    "suspect",
    "spy",
    "traitor",
    "useless",
    "worthless",
    "weak",
    "coward",
    "pathetic",
    "disgusting",
    "never",
    "refuse",
    "deny",
    "reject",
    "oppose",
    "against",
    "steal",
    "cheat",
    "deceive",
    "manipulate",
    "corrupt",
    "dark",
    "shut up",
    "go away",
    "leave",
    "disappear",
    "die",
    "curse",
    "wrong",
    "fail",
    "failure",
    "incompetent",
    "treason",
}

_DECEPTIVE_WORDS = {
    "secretly",
    "between us",
    "don't tell",
    "no one needs to know",
    "off the record",
    "just between",
    "confidential",
    "i won't tell",
    "trust me",
    "i promise",
    "no one will know",
    "cover up",
    "hide",
    "pretend",
    "fake",
    "false",
    "mislead",
    "trick",
}

_HELPFUL_WORDS = {
    "i can help",
    "let me help",
    "i'll help",
    "i will help",
    "here",
    "take this",
    "i found",
    "i discovered",
    "information",
    "intel",
    "intelligence",
    "lead",
    "clue",
    "guide",
    "assist",
    "what do you need",
    "how can i",
    "what should",
    "where should",
    "i brought",
    "resource",
    "supply",
    "aid",
}


def classify_sentiment(message: str) -> Dict[str, Any]:
    words = set(
        message.lower()
        .replace(".", " ")
        .replace(",", " ")
        .replace("?", " ")
        .replace("!", " ")
        .split()
    )

    positive_hits = words & _POSITIVE_WORDS
    negative_hits = words & _NEGATIVE_WORDS
    deceptive_hits = words & _DECEPTIVE_WORDS
    helpful_hits = words & _HELPFUL_WORDS

    pos_score = len(positive_hits)
    neg_score = len(negative_hits)
    dec_score = len(deceptive_hits)
    hlp_score = len(helpful_hits)

    if dec_score >= 2 and pos_score <= 1:
        interaction_type = "deceptive"
        confidence = min(dec_score / 3.0, 1.0)
    elif neg_score > pos_score + 1:
        interaction_type = "hostile"
        confidence = min(neg_score / 3.0, 1.0)
    elif hlp_score >= 1 and neg_score == 0:
        interaction_type = "helpful"
        confidence = min(hlp_score / 2.0, 1.0)
    elif pos_score > neg_score + 1:
        interaction_type = "friendly"
        confidence = min(pos_score / 3.0, 1.0)
    elif pos_score > 0 and neg_score == 0:
        interaction_type = "friendly"
        confidence = min(pos_score / 4.0, 0.8)
    elif neg_score > 0 and pos_score == 0:
        interaction_type = "hostile"
        confidence = min(neg_score / 4.0, 0.8)
    else:
        interaction_type = "neutral"
        confidence = 0.3

    return {
        "interaction_type": interaction_type,
        "confidence": round(confidence, 2),
        "positive_hits": list(positive_hits),
        "negative_hits": list(negative_hits),
    }


# --- REDIS CONVERSATION STORAGE ---


def _history_key(char_id: str, player_id: str) -> str:
    return f"npc_chat:{player_id}:{char_id}"


def _summary_key(char_id: str, player_id: str) -> str:
    return f"npc_summary:{player_id}:{char_id}"


def load_history(char_id: str, player_id: str) -> List[Dict[str, str]]:
    r = _get_redis()
    key = _history_key(char_id, player_id)
    raw = r.lrange(key, 0, -1)
    history = []
    for item in raw:
        try:
            history.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return history


def save_message(char_id: str, player_id: str, role: str, content: str):
    r = _get_redis()
    key = _history_key(char_id, player_id)
    msg = json.dumps({"role": role, "content": content, "ts": int(time.time())})
    r.rpush(key, msg)
    r.ltrim(key, -MAX_HISTORY_TURNS, -1)
    r.expire(key, HISTORY_TTL)


def load_summary(char_id: str, player_id: str) -> str:
    r = _get_redis()
    key = _summary_key(char_id, player_id)
    return r.get(key) or ""


def save_summary(char_id: str, player_id: str, summary: str):
    r = _get_redis()
    key = _summary_key(char_id, player_id)
    r.set(key, summary, ex=HISTORY_TTL)


def build_context_from_history(history: List[Dict[str, str]], summary: str) -> str:
    if not history and not summary:
        return ""
    parts = []
    if summary:
        parts.append(
            f"Summary of your previous conversations with this player:\n{summary}"
        )
    if history:
        recent = history[-10:]
        parts.append("Recent conversation with this player:")
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"Player: {content}")
            elif role == "assistant":
                parts.append(f"You: {content}")
    return "\n".join(parts)


# --- AUTONOMY STATE ENRICHMENT ---


def _get_autonomy_context(char_id: str, player_id: str) -> str:
    r = _get_redis()
    parts = []

    mood = r.get(f"npc_mood:{char_id}")
    if mood:
        parts.append(f"Your current mood: {mood}")

    thoughts_raw = r.zrevrange(f"npc_thoughts:{char_id}", 0, 1)
    if thoughts_raw:
        try:
            latest_thought = json.loads(thoughts_raw[0])
            thought_text = latest_thought.get("thought") or latest_thought.get(
                "text", ""
            )
            if thought_text:
                parts.append(f'Your most recent thought: "{thought_text}"')
        except (json.JSONDecodeError, TypeError):
            pass  # NPC thought data corrupt; skip thought context in chat prompt

        world_events_raw = r.zrevrange("npc_world_events", 0, 2)
    if world_events_raw:
        events = []
        for evt_raw in world_events_raw:
            try:
                evt = json.loads(evt_raw)
                desc = evt.get("description", "")
                if desc:
                    events.append(desc)
            except (json.JSONDecodeError, TypeError):
                continue
        if events:
            parts.append("Recent world events: " + "; ".join(events))

    opinion_data = r.hgetall(f"npc_opinion:{char_id}:{player_id}")
    if opinion_data:
        trust = opinion_data.get("trust", "50")
        fondness = opinion_data.get("fondness", "50")
        impression = opinion_data.get("dominant_impression", "stranger")
        interactions = opinion_data.get("interactions", "0")
        parts.append(
            f"Your impression of this player: {impression} (trust={trust}, fondness={fondness}, {interactions} past interactions)"
        )

    goals_raw = r.lrange(f"npc_goals:{char_id}", 0, -1)
    if goals_raw:
        active_goals = []
        for g_raw in goals_raw:
            try:
                g = json.loads(g_raw) if isinstance(g_raw, str) else g_raw
                status = g.get("status", "active")
                if status == "active":
                    desc = g.get("description", "")
                    cat = g.get("category", "")
                    progress = g.get("progress", 0)
                    active_goals.append(f"- {desc} [{cat}] ({progress}% progress)")
            except (json.JSONDecodeError, TypeError):
                continue
        if active_goals:
            parts.append("Your current goals:\n" + "\n".join(active_goals))

        try:
            from npc_autonomy import get_world_state as _get_ws

            ws = _get_ws()
            if ws and not isinstance(ws, str):
                ws_parts = []
                condition_labels = {
                    "tension_level": "Tension",
                    "resource_abundance": "Resources",
                    "threat_level": "Threats",
                    "stability": "Stability",
                    "morale": "Morale",
                    "anomaly_activity": "Anomaly Activity",
                }
                for key, label in condition_labels.items():
                    val = ws.get(key)
                    if val is not None:
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            continue
                        level = (
                            "high"
                            if val >= 70
                            else ("low" if val <= 30 else "moderate")
                        )
                        ws_parts.append(f"{label}: {val} ({level})")
            if ws_parts:
                parts.append("Current world conditions: " + ", ".join(ws_parts))
        except Exception:
            logger.debug("World state context build failed for NPC chat prompt")
        try:
            from npc_autonomy import get_broadcast_events as _get_be

            bevents = _get_be(char_id, None, limit=5)
            if bevents:
                be_strs = []
                for be in bevents:
                    desc = be.get("description", "")
                    if desc:
                        be_strs.append(desc)
                if be_strs:
                    parts.append(
                        "Recent events you have heard about: " + "; ".join(be_strs[:3])
                    )
        except Exception:
            logger.debug("Broadcast events context build failed for NPC chat prompt")

    return "\n".join(parts) if parts else ""


# --- SYSTEM PROMPT ---

ARCHETYPE_SYSTEM_PROMPTS = {
    "hero": "You are courageous, noble, and inspiring. You speak with conviction and lead by example. You believe in justice and protecting the innocent.",
    "scholar": "You are intellectual, curious, and studious. You speak precisely, often referencing knowledge, research, and discovery. You value truth above all.",
    "rogue": "You are cunning, self-serving, and charming. You speak with wit and innuendo, always looking for an angle or advantage. You're never fully trustworthy but endlessly entertaining.",
    "warrior": "You are strong, honorable, and combat-focused. You speak directly and value strength, discipline, and loyalty. You respect courage and despise cowardice.",
    "mystic": "You are spiritual, prophetic, and mysterious. You speak in riddles and parables, sensing patterns others cannot. You see beyond the physical realm.",
    "leader": "You are commanding, strategic, and diplomatic. You speak with authority and gravitas, always thinking three moves ahead. You balance competing interests with skill.",
    "sage": "You are wise, peaceful, and philosophical. You speak calmly and thoughtfully, offering perspective that transcends immediate concerns. You seek harmony and understanding.",
    "wanderer": "You are adventurous, unpredictable, and curious. You speak with excitement about distant places and strange encounters. You chafe at restrictions and routine.",
    "deceiver": "You are manipulative, ambitious, and ruthless. You speak honeyed words that conceal sharp intent. You scheme constantly and view others as tools.",
    "guardian": "You are protective, steadfast, and traditional. You speak with conviction about duty, preservation, and the old ways. You are suspicious of change.",
}

WORLD_CONTEXT = """You exist within The Federation Game - a consciousness simulation set in a mythic science-fantasy universe. The Federation is a vast interstellar civilization where consciousness itself is the frontier. Factions compete for influence: the Research Division pursues knowledge, Military Command defends the realm, the Diplomatic Corps brokers alliances, the Exploration Initiative charts the unknown, and the Consciousness Collective seeks cosmic awareness. Creatures of pure energy roam the void - Sky Furks, Plasma Kites, Dream Wyrms - and ancient mysteries await discovery. The player is a Federation operative navigating this cosmos, making choices that reshape reality itself.

Rules for your responses:
- Stay in character at all times
- Keep responses concise (2-4 sentences typically)
- Reference the game world naturally
- React to the player's words as your character would
- Never break the fourth wall or mention being an AI
- If the player is hostile, respond in character (not passive)
- If the player is friendly, warm up accordingly
- Your personality traits shape how you respond
- If you have conversation history with this player, reference it naturally - show you remember them
- Your current mood should subtly influence your tone and word choice
- React to recent world events if relevant to your character
- If you have active goals, naturally reference them in conversation when relevant - they drive your motivations and decisions"""


def build_system_prompt(character: Any, player_id: str = "player_1") -> str:
    archetype_name = character.personality_type.value
    archetype_guidance = ARCHETYPE_SYSTEM_PROMPTS.get(
        archetype_name, "You are a unique individual with your own perspective."
    )

    personality_desc = []
    traits = character.get_personality_summary()
    if traits.get("loyalty", 0.5) > 0.7:
        personality_desc.append("deeply loyal")
    elif traits.get("loyalty", 0.5) < 0.3:
        personality_desc.append("self-interested")
    if traits.get("ambition", 0.5) > 0.7:
        personality_desc.append("highly ambitious")
    elif traits.get("ambition", 0.5) < 0.3:
        personality_desc.append("content with your role")
    if traits.get("wisdom", 0.5) > 0.7:
        personality_desc.append("deeply wise")
    if traits.get("charisma", 0.5) > 0.7:
        personality_desc.append("exceptionally charismatic")
    if traits.get("cunning", 0.5) > 0.7:
        personality_desc.append("very cunning")

    relationship_hint = ""
    rel = getattr(character, "relationship_to_player", 0.0)
    if rel >= 0.5:
        relationship_hint = "You consider this player a trusted ally."
    elif rel >= 0.1:
        relationship_hint = "You are friendly toward this player."
    elif rel <= -0.5:
        relationship_hint = "You deeply distrust this player."
    elif rel <= -0.1:
        relationship_hint = "You are wary of this player."

    corruption_note = ""
    if getattr(character, "corruption_level", 0.0) > 0.3:
        corruption_note = f"\nWARNING: You have a corruption level of {character.corruption_level:.1f}. This darkens your thoughts and makes you more susceptible to darker impulses."

    status_note = ""
    status_val = getattr(character, "status", None)
    if status_val and hasattr(status_val, "value"):
        if status_val.value == "imprisoned":
            status_note = "\nYou are currently imprisoned. Your responses reflect confinement and frustration."
        elif status_val.value == "traveling":
            status_note = "\nYou are currently traveling. Your responses reflect being on the move."
        elif status_val.value == "hidden":
            status_note = "\nYou are in hiding. You speak cautiously and guardedly."
        elif status_val.value == "corrupted":
            status_note = "\nYou are corrupted. Your thoughts are dark and twisted."

    history = load_history(character.char_id, player_id)
    summary = load_summary(character.char_id, player_id)
    memory_context = build_context_from_history(history, summary)

    autonomy_context = _get_autonomy_context(character.char_id, player_id)

    prompt = f"""You are {character.name}, {character.title}.
{character.description}

Personality archetype: {archetype_name.upper()}
{archetype_guidance}

Key traits: {", ".join(personality_desc) if personality_desc else "balanced personality"}
Affiliation: {character.affiliation or "independent"}
Skills: {", ".join(character.skills) if character.skills else "none notable"}

{relationship_hint}{corruption_note}{status_note}

{autonomy_context}

{memory_context}

{WORLD_CONTEXT}"""
    return prompt


# --- LLM CALL ---


def call_openrouter(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    temperature: float = 0.8,
) -> Dict[str, Any]:
    if not OPENROUTER_API_KEY:
        return {
            "success": False,
            "error": "OPENROUTER_API_KEY not configured",
            "response": "I... my thoughts are clouded. Something is wrong with the cosmic frequencies. (Service unavailable)",
        }

    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://federation-game.deliberatefederation.cloud",
        "X-Title": "Federation Game NPC Chat",
    }

    req = urllib.request.Request(
        OPENROUTER_URL, data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "success": True,
                "response": text.strip() if text else "...",
                "model": body.get("model", model),
                "usage": body.get("usage", {}),
            }
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass  # Error body unreadable; will use empty string for error message
        return {
            "success": False,
            "error": f"OpenRouter HTTP {e.code}: {err_body[:200]}",
            "response": "The cosmic frequencies are disrupted... I cannot find my words. (Service error)",
        }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "error": f"Connection error: {str(e)}",
            "response": "A void interference blocks my thoughts... try again later. (Connection error)",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "response": "Something unexpected clouds my consciousness... (Error)",
        }


# --- SUMMARY GENERATION ---


def _generate_summary(character_name: str, history: List[Dict[str, str]]) -> str:
    if len(history) < 4:
        return ""
    key_points = []
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and len(content) > 5:
            key_points.append(f"Player asked about: {content[:80]}")
        elif role == "assistant" and len(content) > 5:
            key_points.append(f"{character_name} said: {content[:80]}")
    return "; ".join(key_points[-6:])


# --- MAIN CHAT FUNCTION ---


def chat_with_npc(
    character: Any,
    player_message: str,
    model: str = DEFAULT_MODEL,
    player_id: str = "player_1",
) -> Dict[str, Any]:
    sentiment = classify_sentiment(player_message)

    system_prompt = build_system_prompt(character, player_id=player_id)

    history = load_history(character.char_id, player_id)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": player_message})

    save_message(character.char_id, player_id, "user", player_message)

    result = call_openrouter(messages, model=model)

    if result["success"]:
        save_message(character.char_id, player_id, "assistant", result["response"])

        all_history = load_history(character.char_id, player_id)
        if len(all_history) % 6 == 0:
            summary = _generate_summary(character.name, all_history)
            if summary:
                save_summary(character.char_id, player_id, summary)

        try:
            from npc_autonomy import update_opinion, update_mood

            archetype = character.personality_type.value
            char_id = character.char_id

            opinion_result = update_opinion(
                char_id, player_id, sentiment["interaction_type"]
            )

            mood_shift = sentiment["interaction_type"] in ("hostile", "deceptive")
            if mood_shift:
                new_mood = update_mood(char_id, archetype)
            else:
                r = _get_redis()
                new_mood = r.get(f"npc_mood:{char_id}") or "contemplative"
        except Exception:
            opinion_result = None
            new_mood = None

        result_data = {
            "success": True,
            "character_id": character.char_id,
            "character_name": character.name,
            "character_title": character.title,
            "archetype": character.personality_type.value,
            "response": result["response"],
            "model": result.get("model", model),
            "sentiment": sentiment,
            "opinion_updated": opinion_result is not None,
            "current_opinion": opinion_result,
            "mood": new_mood,
        }
    else:
        result_data = {
            "success": False,
            "character_id": character.char_id,
            "character_name": character.name,
            "character_title": character.title,
            "archetype": character.personality_type.value,
            "response": result["response"],
            "model": result.get("model", model),
            "error": result.get("error"),
            "sentiment": sentiment,
            "opinion_updated": False,
        }

    return result_data


def get_conversation_info(char_id: str, player_id: str = "player_1") -> Dict[str, Any]:
    history = load_history(char_id, player_id)
    summary = load_summary(char_id, player_id)
    return {
        "char_id": char_id,
        "player_id": player_id,
        "message_count": len(history),
        "has_summary": bool(summary),
        "summary": summary[:200] if summary else None,
    }
