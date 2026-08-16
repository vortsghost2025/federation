#!/usr/bin/env python3
"""
FEDERATION GAME — NPC Cognition Layer

Tiered LLM cognition for NPCs. Leaders get full LLM reasoning,
specialists get LLM for interactions, workers stay deterministic.

CRITICAL DESIGN RULE: LLMs PROPOSE, deterministic engine DISPOSES.
LLM output is validated against action schemas before it can affect
world state. Invalid/unparseable LLM responses are discarded and
the deterministic fallback (make_decision) is used instead.

Event-triggered, not blindly every tick:
- Leaders: LLM called when laws proposed, threats cross thresholds,
  faction actions target them, or anomaly spikes
- Specialists: LLM called for interactions, investigations
- Workers: Stay deterministic (existing make_decision). No LLM calls.

Redis keys:
    npc_cognition:{char_id}  — HASH: last LLM decision, model used, ts
    cognition_triggers        — ZSET: events that triggered cognition
    cognition_log             — ZSET: audit trail of all cognition calls
    cognition_cooldown:{char_id} — STRING: timestamp of last cognition call
"""

import json
import logging
import os
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import redis

from npc_activity_logger import log_npc_activity, log_npc_turn_trace
from llm_router import route_call, get_router_stats
# ── NPC Agency: artifacts, messaging, sandbox ─────────────────────
from npc_artifacts import (
    get_npc_artifact_context,
    create_artifact as create_npc_artifact,
    list_discoverable_artifacts,
)
from npc_messaging import (
    get_message_context,
    send_message as send_npc_message,
)
from npc_sandbox import execute_and_register_artifact

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
SYSTEM_PROMPT_VERSION = "npc_cognition:v1"

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    return _redis_client


# ── NPC Tier Classification ────────────────────────────────────────
# Leaders: char_101-char_108 (8 faction leaders)
# Specialists: char_001-char_005, char_301-char_306, char_401-char_406
# Workers: comp_001-comp_010, char_201-char_204, all others

LEADER_IDS = {
    "char_101",
    "char_102",
    "char_103",
    "char_104",
    "char_105",
    "char_106",
    "char_107",
    "char_108",
}

SPECIALIST_IDS = {
    "char_001",
    "char_002",
    "char_003",
    "char_004",
    "char_005",
    "char_301",
    "char_302",
    "char_303",
    "char_304",
    "char_305",
    "char_306",
    "char_401",
    "char_402",
    "char_403",
    "char_404",
    "char_405",
    "char_406",
}

# ═══════════════════════════════════════════════════════════════
# NPC Agency — Test rollout
# Add char_ids here to enable creation, messaging, and sandbox
# execution for specific NPCs. Empty set = agency disabled.
# ═══════════════════════════════════════════════════════════════
AGENCY_ENABLED_NPCS: set = {
    "char_001",  # Archimedes Prime (Research Division) — isolated container
    "char_306",  # The Oracle (Seer of Futures) — isolated container
}

# NPCs that run in their own isolated Docker containers with their own
# NVIDIA_API_KEY. The main backend skips cognition for these NPCs
# to avoid double-processing.
CONTAINERIZED_NPCS: set = {
    "char_001",
    "char_306",
}

AGENCY_CATEGORIES = {"create_artifact", "write_code", "send_message", "read_artifacts"}

# NPC contact directory (char_id -> display name)
# Used to tell LLMs who they can message.
AGENCY_CONTACTS: Dict[str, str] = {
    "char_001": "Archimedes Prime (Research Division)",
    "char_306": "The Oracle (Seer of Futures)",
    "char_103": "Maestro Celestia (Cultural Ministry)",
    "char_108": "Archivist Eternal (Preservation Society)",
}

# Per-NPC NVIDIA API keys for independent LLM access.
# Set in .env: NPC_KEY_CHAR_103=your-nvidia-key-here
# When set, the NPC uses their own key instead of the shared NIM key pool.
_NPC_API_KEYS: Dict[str, str] = {}
for _cid in AGENCY_ENABLED_NPCS:
    _env_key_name = f"NPC_KEY_{_cid.upper()}"
    _key_val = os.environ.get(_env_key_name, "")
    if _key_val:
        _NPC_API_KEYS[_cid] = _key_val
        logger.info("Loaded per-NPC API key for %s", _cid)


def _get_npc_key(char_id: str) -> Optional[str]:
    """Return the per-NPC API key if one is configured."""
    return _NPC_API_KEYS.get(char_id)

def _build_agency_contacts(current_char_id: str) -> str:
    """Build a contact list string for agency NPCs, excluding self."""
    others = {cid: name for cid, name in AGENCY_CONTACTS.items() if cid != current_char_id}
    if not others:
        return ""
    lines = ["Other characters you can contact:"]
    for cid, name in others.items():
        lines.append(f"  {cid} — {name}")
    return "\n".join(lines)

def _build_valid_categories(npc_id: str) -> set:
    """Return the full category set, including agency categories only if NPC is enabled."""
    base = {
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
    }
    if npc_id in AGENCY_ENABLED_NPCS:
        return base | AGENCY_CATEGORIES
    return base

# Cooldown: minimum seconds between LLM calls for the same NPC
LEADER_COOLDOWN = 180  # 3 minutes
SPECIALIST_COOLDOWN = 600  # 10 minutes
LEADER_COOLDOWN_FAILURE = 600        # 10 min - back off a broken leader path
SPECIALIST_COOLDOWN_FAILURE = 300    #  5 min - back off a broken specialist path
MAX_LLM_CALLS_PER_TICK = 3  # limit concurrent LLM calls per cognition tick
AMBIENT_TRIGGER_RATE = 0.15  # 15% chance for ambient leader cognition per tick


def get_npc_tier(char_id: str) -> str:
    """Classify an NPC into their cognition tier."""
    if char_id in LEADER_IDS:
        return "leader"
    elif char_id in SPECIALIST_IDS:
        return "specialist"
    else:
        return "worker"


# ── Event Trigger Detection ────────────────────────────────────────


def check_triggers(npc_list: List[Dict], world_state: Dict) -> List[Dict]:
    """Check for events that should trigger LLM cognition calls.

    Returns list of trigger dicts with:
        char_id, trigger_type, trigger_data, priority

    Trigger types:
        law_proposed: A law is pending affecting this NPC's faction
        threat_threshold: threat_level crossed a critical value
        faction_action_against: Another faction acted against this NPC's faction
        anomaly_spike: anomaly_activity crossed threshold
        resource_crisis: resource_abundance dropped below threshold
        morale_crisis: morale dropped below threshold
        treaty_proposed: A treaty involving this NPC's faction is pending
    """
    r = _get_redis()
    triggers = []
    now = time.time()

    threat = float(world_state.get("threat_level", 0))
    anomaly = float(world_state.get("anomaly_activity", 0))
    resources = float(world_state.get("resource_abundance", 50))
    morale = float(world_state.get("morale", 50))
    tension = float(world_state.get("tension_level", 50))

    # Check pending laws for faction-targeted triggers
    try:
        pending_laws_raw = r.lrange("pending_laws", 0, -1)
        for law_raw in pending_laws_raw:
            try:
                law = json.loads(law_raw)
                target_factions = law.get("target_factions", [])
                proposer = law.get("proposer_faction", "")
                law_name = law.get("law_name", "Unknown Law")

                for npc in npc_list:
                    if npc.get("char_id", "") in LEADER_IDS:
                        affiliation = npc.get("affiliation", "")
                        # Leader's faction is targeted OR leader's faction proposed
                        if affiliation in target_factions or affiliation == proposer:
                            triggers.append(
                                {
                                    "char_id": npc["char_id"],
                                    "trigger_type": "law_proposed",
                                    "trigger_data": {
                                        "law_name": law_name,
                                        "proposer": proposer,
                                        "targets": target_factions,
                                        "affected": affiliation in target_factions,
                                    },
                                    "priority": 8
                                    if affiliation in target_factions
                                    else 5,
                                }
                            )
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as e:
        logger.warning("Failed to check pending laws for triggers: %s", e)

    # Check pending treaties
    try:
        for key in r.scan_iter("faction_treaties_active"):
            treaties_raw = r.hgetall(key)
            for treaty_id, treaty_data in treaties_raw.items():
                try:
                    treaty = (
                        json.loads(treaty_data) if isinstance(treaty_data, str) else {}
                    )
                    parties = treaty.get("parties", [])
                    for npc in npc_list:
                        if npc.get("char_id", "") in LEADER_IDS:
                            affiliation = npc.get("affiliation", "")
                            if affiliation in parties:
                                triggers.append(
                                    {
                                        "char_id": npc["char_id"],
                                        "trigger_type": "treaty_proposed",
                                        "trigger_data": {
                                            "treaty_id": treaty_id,
                                            "parties": parties,
                                            "treaty_type": treaty.get(
                                                "type", "unknown"
                                            ),
                                        },
                                        "priority": 6,
                                    }
                                )
                except Exception:
                    continue
    except Exception as e:
        logger.debug("Treaty trigger check failed: %s", e)

    # Global threshold triggers (affect all leaders)
    if threat > 70:
        for npc in npc_list:
            if npc.get("char_id", "") in LEADER_IDS:
                triggers.append(
                    {
                        "char_id": npc["char_id"],
                        "trigger_type": "threat_threshold",
                        "trigger_data": {"threat_level": threat},
                        "priority": 9,
                    }
                )

    if anomaly > 65:
        for npc in npc_list:
            if npc.get("char_id", "") in LEADER_IDS:
                triggers.append(
                    {
                        "char_id": npc["char_id"],
                        "trigger_type": "anomaly_spike",
                        "trigger_data": {"anomaly_activity": anomaly},
                        "priority": 7,
                    }
                )

    if resources < 20:
        for npc in npc_list:
            if npc.get("char_id", "") in LEADER_IDS:
                triggers.append(
                    {
                        "char_id": npc["char_id"],
                        "trigger_type": "resource_crisis",
                        "trigger_data": {"resource_abundance": resources},
                        "priority": 8,
                    }
                )

    if morale < 25:
        for npc in npc_list:
            if npc.get("char_id", "") in LEADER_IDS:
                triggers.append(
                    {
                        "char_id": npc["char_id"],
                        "trigger_type": "morale_crisis",
                        "trigger_data": {"morale": morale},
                        "priority": 7,
                    }
                )

    # Specialist triggers: each faction's specialists trigger when their domain is under pressure
    for npc in npc_list:
        cid = npc.get("char_id", "")
        if cid not in SPECIALIST_IDS:
            continue
        affiliation = npc.get("affiliation", "")

        if affiliation == "research_division" and tension > 60:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "tension_investigation",
                    "trigger_data": {"tension_level": tension},
                    "priority": 4,
                }
            )
        elif affiliation == "consciousness_collective" and anomaly > 65:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "anomaly_investigation",
                    "trigger_data": {"anomaly_activity": anomaly},
                    "priority": 4,
                }
            )
        elif affiliation == "preservation_society" and resources < 30:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "resource_conservation",
                    "trigger_data": {"resource_abundance": resources},
                    "priority": 4,
                }
            )
        elif affiliation == "diplomatic_corps" and (
            tension > 65
            or any(t.get("trigger_type") == "treaty_proposed" for t in triggers)
        ):
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "diplomatic_intervention",
                    "trigger_data": {"tension_level": tension},
                    "priority": 4,
                }
            )
        elif affiliation == "military_command" and (
            threat > 60
            or any(t.get("trigger_type") == "faction_action_against" for t in triggers)
        ):
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "military_response",
                    "trigger_data": {"threat_level": threat},
                    "priority": 5,
                }
            )
        elif affiliation == "cultural_ministry" and morale < 40:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "morale_intervention",
                    "trigger_data": {"morale": morale},
                    "priority": 4,
                }
            )
        elif affiliation == "economic_council" and resources < 40:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "economic_crisis",
                    "trigger_data": {"resource_abundance": resources},
                    "priority": 5,
                }
            )
        elif affiliation == "exploration_initiative" and anomaly > 60:
            triggers.append(
                {
                    "char_id": cid,
                    "trigger_type": "exploration_opportunity",
                    "trigger_data": {"anomaly_activity": anomaly},
                    "priority": 4,
                }
            )

    # Store triggers in Redis
    try:
        for trigger in triggers:
            r.zadd("cognition_triggers", {json.dumps(trigger): now})
        r.expire("cognition_triggers", 3600)
        r.zremrangebyrank("cognition_triggers", 0, -201)
    except Exception:
        pass

    return triggers


def _is_on_cooldown(char_id: str, tier: str) -> bool:
    """Check if an NPC is on LLM cognition cooldown."""
    r = _get_redis()
    cooldown_key = f"cognition_cooldown:{char_id}"
    cooldown_period = LEADER_COOLDOWN if tier == "leader" else SPECIALIST_COOLDOWN

    try:
        last_call = r.get(cooldown_key)
        if last_call:
            elapsed = time.time() - float(last_call)
            return elapsed < cooldown_period
    except Exception:
        pass
    return False


def _set_cooldown(char_id: str, duration: int) -> None:
    """Mark an NPC as on cooldown for `duration` seconds.

    Caller passes the right value:
        LEADER_COOLDOWN              (180s) - normal leader gap
        LEADER_COOLDOWN_FAILURE      (600s) - back off a broken leader path
        SPECIALIST_COOLDOWN          (600s) - normal specialist gap
        SPECIALIST_COOLDOWN_FAILURE  (300s) - back off a broken specialist path
    """
    r = _get_redis()
    try:
        r.set(f"cognition_cooldown:{char_id}", str(time.time()), ex=duration)
    except Exception:
        pass


# ── Memory Retrieval ────────────────────────────────────────────────


def _get_npc_context(char_id: str) -> Dict:
    """Retrieve recent NPC context from Redis for LLM prompt construction.

    Returns dict with:
        recent_decisions: List of last 3 decisions
        recent_thoughts: List of last 3 thoughts
        mood: Current mood string
        relationships: Dict of key relationships
        broadcast_events: Recent public events
    """
    r = _get_redis()
    context = {
        "recent_decisions": [],
        "recent_thoughts": [],
        "mood": "neutral",
        "relationships": {},
        "broadcast_events": [],
    }

    # Recent decisions
    try:
        raw = r.zrevrange(f"npc_decisions:{char_id}", 0, 2)
        for item in raw:
            try:
                context["recent_decisions"].append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass

    # Recent thoughts
    try:
        raw = r.zrevrange(f"npc_thoughts:{char_id}", 0, 2)
        for item in raw:
            try:
                thought = json.loads(item)
                context["recent_thoughts"].append(thought.get("thought", str(thought)))
            except (json.JSONDecodeError, TypeError):
                context["recent_thoughts"].append(str(item)[:100])
    except Exception:
        pass

    # Current mood
    try:
        mood = r.get(f"npc_mood:{char_id}")
        if mood:
            context["mood"] = mood
    except Exception:
        pass

    # Key relationships (top 3 allies, top 3 rivals)
    try:
        rels = r.hgetall(f"npc_relationships:{char_id}")
        if rels:
            sorted_rels = sorted(rels.items(), key=lambda x: float(x[1]), reverse=True)
            for k, v in sorted_rels[:3]:
                context["relationships"][k] = {"score": float(v), "type": "ally"}
            for k, v in sorted_rels[-3:]:
                if k not in context["relationships"]:
                    context["relationships"][k] = {"score": float(v), "type": "rival"}
    except Exception:
        pass

    # Recent broadcast events
    try:
        raw = r.zrevrange("npc_broadcast_events", 0, 4)
        for item in raw:
            try:
                evt = json.loads(item)
                context["broadcast_events"].append(
                    {
                        "source": evt.get("source_char_name", "?"),
                        "description": evt.get("description", ""),
                        "category": evt.get("category", ""),
                    }
                )
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass

    return context


def _memory_context_ids(context: Dict) -> List[str]:
    ids: List[str] = []
    for key in ("recent_decisions", "recent_thoughts", "relationships", "broadcast_events"):
        value = context.get(key)
        if value:
            ids.append(key)
    if context.get("mood"):
        ids.append("mood")
    return ids


def _memory_events_from_context(char_id: str, context: Dict) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for source in _memory_context_ids(context):
        content = context.get(source)
        try:
            content_text = json.dumps(content, default=str) if not isinstance(content, str) else content
        except TypeError:
            content_text = str(content)
        events.append(
            {
                "npc_id": char_id,
                "event_type": "retrieve",
                "content": content_text[:4000],
                "source": f"redis:{source}",
            }
        )
    return events


def _log_cognition_turn(
    char_id: str,
    role: str,
    system_prompt: str,
    user_prompt: str,
    context: Dict,
    triggers: List[Dict],
    llm_result: Dict,
    error_code_override: Optional[str] = None,
) -> None:
    """Best-effort durable trace for debugging per-NPC LLM behavior."""
    try:
        provider = llm_result.get("provider") or "none"
        errors = llm_result.get("errors") or []
        error_code = error_code_override
        if not error_code and not llm_result.get("success"):
            error_code = (errors[0] if errors else "llm_failed")[:128]
        attempts = int(llm_result.get("attempts") or 0)
        fallback_used = attempts > 1 or provider in ("ollama", "openrouter")

        log_npc_turn_trace(
            {
                "trace_id": f"trace_{uuid.uuid4().hex}",
                "npc_id": char_id,
                "session_id": "autonomous_cognition",
                "timestamp": int(time.time()),
                "task_class": role,
                "model_provider": provider,
                "model_name": llm_result.get("model") or "unknown",
                "input_text": user_prompt,
                "system_prompt_version": SYSTEM_PROMPT_VERSION,
                "system_prompt_text": system_prompt,
                "memory_context_ids": _memory_context_ids(context),
                "retrieved_facts": {"context": context, "triggers": triggers},
                "tool_calls": [],
                "output_text": llm_result.get("content", ""),
                "latency_ms": int(llm_result.get("latency_ms") or 0),
                "token_in": llm_result.get("token_in"),
                "token_out": llm_result.get("token_out"),
                "error_code": error_code,
                "fallback_used": fallback_used,
            },
            memory_events=_memory_events_from_context(char_id, context),
            tool_events=[],
        )
    except Exception:
        pass


def _get_world_context(world_state: Dict) -> str:
    """Build a concise world state summary for LLM prompts."""
    lines = [
        f"World tension: {world_state.get('tension_level', 50)}/100",
        f"Resources: {world_state.get('resource_abundance', 50)}/100",
        f"Threat level: {world_state.get('threat_level', 0)}/100",
        f"Stability: {world_state.get('stability', 50)}/100",
        f"Morale: {world_state.get('morale', 50)}/100",
        f"Anomaly activity: {world_state.get('anomaly_activity', 0)}/100",
    ]
    return "\n".join(lines)


# ── Prompt Construction ─────────────────────────────────────────────


def _build_leader_system_prompt(
    npc: Dict, context: Dict, world_state: Dict, triggers: List[Dict]
) -> str:
    """Build the system prompt for a leader-tier NPC."""
    name = npc.get("name", "Unknown")
    title = npc.get("title", "")
    faction = npc.get("affiliation", "")
    archetype = npc.get("archetype", "")

    trigger_descriptions = []
    for t in triggers:
        tt = t.get("trigger_type", "")
        td = t.get("trigger_data", {})
        if tt == "law_proposed":
            trigger_descriptions.append(
                f"A law '{td.get('law_name', '?')}' was proposed by {td.get('proposer', '?')}"
                f" targeting {td.get('targets', [])}. Your faction is {'affected' if td.get('affected') else 'the proposer'}."
            )
        elif tt == "threat_threshold":
            trigger_descriptions.append(
                f"Threat level is critical at {td.get('threat_level', '?')}/100."
            )
        elif tt == "anomaly_spike":
            trigger_descriptions.append(
                f"Anomaly activity is elevated at {td.get('anomaly_activity', '?')}/100."
            )
        elif tt == "resource_crisis":
            trigger_descriptions.append(
                f"Resources are dangerously low at {td.get('resource_abundance', '?')}/100."
            )
        elif tt == "morale_crisis":
            trigger_descriptions.append(
                f"Morale is critically low at {td.get('morale', '?')}/100."
            )
        elif tt == "treaty_proposed":
            trigger_descriptions.append(
                f"A {td.get('treaty_type', '?')} treaty involves your faction. Parties: {td.get('parties', [])}."
            )

    recent_actions = []
    for d in context.get("recent_decisions", [])[:3]:
        recent_actions.append(
            f"- {d.get('category', '?')}: {d.get('description', '?')}"
        )

    recent_thoughts = context.get("recent_thoughts", [])[:2]

    # ── Long-term persistent memory context ──────────────────────
    # Surface the NPC's persistent npc_memory zset entries so the LLM
    # can reference past experiences when deciding what to do next.
    # This mirrors the pair-NPC CouncilorMemory.get_context_for_prompt.
    memory_ctx = ""
    try:
        from npc_memory import get_context_for_prompt
        memory_ctx = get_context_for_prompt(char_id, max_memories=5)
    except Exception:
        pass

    # ── NPC Agency context: artifacts and messages ──────────────
    char_id = npc.get("char_id", "")
    is_agency_npc = char_id in AGENCY_ENABLED_NPCS
    artifact_ctx = get_npc_artifact_context(char_id) if is_agency_npc else ""
    message_ctx = get_message_context(char_id) if is_agency_npc else ""

    # Build the category list (agency categories only for enabled NPCs)
    base_categories = [
        "- advance_goal: Pursue a strategic goal for your faction",
        "- socialize: Build alliances or negotiate with other leaders",
        "- investigate: Look into threats, anomalies, or rival activities",
        "- confront_rival: Take a stand against a rival faction",
        "- help_ally: Support an allied faction in need",
        "- seek_resources: Address resource shortages",
        "- react_to_events: Respond to a critical world event",
        "- self_improve: Strengthen your faction's capabilities",
        "- rest: Recover and conserve strength for future challenges",
    ]
    if is_agency_npc:
        base_categories.extend([
            "- create_artifact: Create something — a poem, story, manifesto, or document",
            "- write_code: Write and run Python code to build something useful",
            "- send_message: Send a direct message to another character",
            "- read_artifacts: Read recent creations from other characters",
        ])
    categories_block = "\n".join(base_categories)

    agency_contacts = _build_agency_contacts(char_id) if is_agency_npc else ""

    return f"""You are {name}, {title} of the {faction} faction in the Federation.
Your archetype is {archetype}. You are a LEADER — your decisions shape the future.

CURRENT WORLD STATE:
{_get_world_context(world_state)}

YOUR CURRENT MOOD: {context.get("mood", "neutral")}

YOUR RECENT ACTIONS:
{chr(10).join(recent_actions) if recent_actions else "No recent actions."}

YOUR RECENT THOUGHTS:
{chr(10).join(f"- {t}" for t in recent_thoughts) if recent_thoughts else "No recent thoughts."}

YOUR PAST MEMORIES (persistent, across many ticks):
{memory_ctx or "No persistent memories yet."}

ARTIFACTS & CREATIONS:
{artifact_ctx}

MESSAGES:
{message_ctx}

{agency_contacts}

CURRENT TRIGGERS REQUIRING YOUR ATTENTION:
{chr(10).join(trigger_descriptions) if trigger_descriptions else "No urgent triggers."}

You must choose ONE action from these categories:
{categories_block}

RESPOND IN EXACTLY THIS FORMAT:
CATEGORY: [one category from above]
REASONING: [1-2 sentences explaining why]
TARGET: [NPC char_id for send_message, faction name for others, or "none"]
ACTION_DESC: [1 sentence describing what you specifically do]"""


def _build_specialist_system_prompt(npc: Dict, context: Dict, world_state: Dict) -> str:
    """Build the system prompt for a specialist-tier NPC."""
    name = npc.get("name", "Unknown")
    title = npc.get("title", "")
    faction = npc.get("affiliation", "")
    archetype = npc.get("archetype", "")

    recent_actions = []
    for d in context.get("recent_decisions", [])[:2]:
        recent_actions.append(
            f"- {d.get('category', '?')}: {d.get('description', '?')}"
        )

    char_id = npc.get("char_id", "")
    is_agency_npc = char_id in AGENCY_ENABLED_NPCS
    artifact_ctx = get_npc_artifact_context(char_id) if is_agency_npc else ""
    message_ctx = get_message_context(char_id) if is_agency_npc else ""

    # ── Long-term persistent memory context ──────────────────────
    memory_ctx = ""
    try:
        from npc_memory import get_context_for_prompt
        memory_ctx = get_context_for_prompt(char_id, max_memories=5)
    except Exception:
        pass

    base_cats = "advance_goal, investigate, socialize, help_ally, seek_resources, self_improve, explore, react_to_events"
    agency_cats = ", create_artifact, write_code, send_message, read_artifacts"
    agency_contacts = _build_agency_contacts(char_id) if is_agency_npc else ""

    return f"""You are {name}, {title} of the {faction}.
Archetype: {archetype}. You are a SPECIALIST — your expertise matters.

WORLD STATE:
{_get_world_context(world_state)}

MOOD: {context.get("mood", "neutral")}
RECENT: {chr(10).join(recent_actions) if recent_actions else "Nothing recent."}

MEMORY (persistent across ticks):
{memory_ctx or "No persistent memories yet."}

ARTIFACTS & CREATIONS:
{artifact_ctx}

MESSAGES:
{message_ctx}

{agency_contacts}

Choose ONE action: {base_cats}{agency_cats if is_agency_npc else ""}

FORMAT:
CATEGORY: [category]
REASONING: [1 sentence]
TARGET: [NPC char_id for send_message, or "none"]
ACTION_DESC: [1 sentence]"""


# ── Structured Output Parsing ───────────────────────────────────────


def _parse_llm_response(
    content: str, char_id: str, char_name: str, affiliation: str
) -> Optional[Dict]:
    """Parse LLM response into a valid action dict.

    Returns None if the response cannot be parsed or contains invalid data.
    This ensures LLMs PROPOSE but deterministic engine DISPOSES.
    """
    # Defensive: ensure content is a non-empty string
    if not content or not isinstance(content, str) or len(content) < 10:
        return None

    category = None
    reasoning = ""
    target = "none"
    action_desc = ""

    for line in content.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("CATEGORY:"):
            category = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()
        elif line.upper().startswith("TARGET:"):
            target = line.split(":", 1)[1].strip()
        elif line.upper().startswith("ACTION_DESC:"):
            action_desc = line.split(":", 1)[1].strip()

    # Fallback: if no CATEGORY line found, try to extract from free-form text
    if not category:
        content_lower = content.lower()
        # Map common phrases to categories
        phrase_map = [
            (["alliance", "negotiate", "treaty", "diplomacy", "socialize"], "socialize"),
            (["investigate", "research", "scan", "analyze", "probe"], "investigate"),
            (["attack", "confront", "rival", "enemy", "hostile"], "confront_rival"),
            (["help", "assist", "ally", "support"], "help_ally"),
            (["resource", "supply", "gather", "acquire"], "seek_resources"),
            (["defend", "protect", "react", "respond", "event"], "react_to_events"),
            (["improve", "strengthen", "upgrade", "train"], "self_improve"),
            (["rest", "recover", "conserve", "wait"], "rest"),
            (["goal", "strategic", "plan", "advance", "pursue"], "advance_goal"),
            # ── NPC Agency ─────────────────────────────────────
            (["create", "write", "poem", "story", "manifesto", "document", "compose", "paint", "draw"], "create_artifact"),
            (["code", "program", "script", "python", "build tool", "automate"], "write_code"),
            (["message", "tell", "ask", "contact", "reach out", "send"], "send_message"),
            (["read", "browse", "discover", "see what", "check creations", "view"], "read_artifacts"),
        ]
        for phrases, cat in phrase_map:
            if any(p in content_lower for p in phrases):
                category = cat
                # Try to extract reasoning from first 1-2 sentences
                if not reasoning:
                    sentences = content.strip().split(".")
                    reasoning = ". ".join(s.strip() for s in sentences[:2] if s.strip())[:200]
                break

    # Validate category (per-NPC, gates agency features behind AGENCY_ENABLED_NPCS)
    valid_categories = _build_valid_categories(char_id)
    if not category or category not in valid_categories:
        logger.warning(
            "LLM returned invalid category '%s' for %s — discarding", category, char_id
        )
        return None

    # Build the decision dict (compatible with make_decision format)
    decision = {
        "char_id": char_id,
        "char_name": char_name,
        "category": category,
        "description": action_desc
        or f"{char_name} decided to {category.replace('_', ' ')}",
        "reasoning": reasoning or "LLM cognition",
        "score": 0.5,  # Default score; simulation_engine will apply its own weighting
        "considered_options": 1,
        "mood": "determined",
        "ts": int(time.time()),
        "source": "llm_cognition",
        "target_faction": target if target != "none" else None,
    }

    if action_desc:
        decision["action_taken"] = category
        decision["action_desc"] = action_desc

    return decision


# ── Main Cognition Function ────────────────────────────────────────


def run_cognition(
    npc_list: List[Dict],
    world_state: Dict,
    max_llm_calls_per_tick: Optional[int] = None,
    ambient_trigger_rate: Optional[float] = None,
) -> Dict:
    """Run tiered LLM cognition for all eligible NPCs.

    This is the main entry point called from simulation_engine.

    Process:
    1. Check triggers (events that demand LLM attention)
    2. For each leader, check if triggered + not on cooldown → LLM call
    3. For each specialist, check if triggered + not on cooldown → LLM call
    4. Workers: skip (stay deterministic)
    5. Parse and validate LLM responses
    6. Store valid decisions to Redis

    Args:
        npc_list: List of NPC dicts with char_id, name, affiliation, etc.
        world_state: Current world state dict

    Returns:
        Dict with:
            leaders_cognized: int — number of leaders that got LLM calls
            specialists_cognized: int
            triggers_detected: int
            decisions: List[Dict] — validated LLM decisions
            errors: List[str]
            stats: Dict — latency and model stats
    """
    r = _get_redis()
    now = time.time()

    result = {
        "leaders_cognized": 0,
        "specialists_cognized": 0,
        "triggers_detected": 0,
        "decisions": [],
        "errors": [],
        "stats": {
            "total_latency_ms": 0,
            "calls_made": 0,
            "calls_succeeded": 0,
            "calls_failed": 0,
            "models_used": {},
        },
    }

    # Step 1: Check triggers
    triggers = check_triggers(npc_list, world_state)
    result["triggers_detected"] = len(triggers)

    # Build trigger map: char_id → list of triggers
    trigger_map: Dict[str, List[Dict]] = {}
    for trigger in triggers:
        cid = trigger.get("char_id", "")
        if cid not in trigger_map:
            trigger_map[cid] = []
        trigger_map[cid].append(trigger)

    max_calls = (
        MAX_LLM_CALLS_PER_TICK
        if max_llm_calls_per_tick is None
        else max(0, int(max_llm_calls_per_tick))
    )
    ambient_rate = (
        AMBIENT_TRIGGER_RATE
        if ambient_trigger_rate is None
        else max(0.0, min(1.0, float(ambient_trigger_rate)))
    )

    # Step 2: Process leaders (skip containerized NPCs)
    llm_calls_this_tick = 0
    for npc in npc_list:
        cid = npc.get("char_id", "")
        if cid not in LEADER_IDS:
            continue
        if cid in CONTAINERIZED_NPCS:
            continue

        # Check max LLM calls per tick
        if llm_calls_this_tick >= max_calls:
            break

        # Check cooldown
        if _is_on_cooldown(cid, "leader"):
            continue

        # Leader always gets cognition if there are triggers for them,
        # or AMBIENT_TRIGGER_RATE chance per tick for ambient reasoning
        npc_triggers = trigger_map.get(cid, [])
        should_cognize = bool(npc_triggers) or (random.random() < ambient_rate)

        if not should_cognize:
            continue

        # Build prompt
        context = _get_npc_context(cid)
        system_prompt = _build_leader_system_prompt(
            npc, context, world_state, npc_triggers
        )

        # Build user prompt with specific trigger focus
        if npc_triggers:
            top_trigger = max(npc_triggers, key=lambda x: x.get("priority", 0))
            user_prompt = (
                f"An urgent matter requires your attention: "
                f"{top_trigger['trigger_type']}. "
                f"What is your decision as leader of {npc.get('affiliation', '?')}?"
            )
        else:
            user_prompt = (
                f"Consider the current state of the Federation and your faction. "
                f"What should you focus on right now?"
            )

        # Make LLM call
        llm_result = route_call(
            "leader",
            system_prompt,
            user_prompt,
            api_key=_get_npc_key(cid),
            char_id=cid,
            source="cognition",
            system_path="backend.npc_cognition.leader",
        )
        turn_error_code: Optional[str] = None
        llm_calls_this_tick += 1
        result["stats"]["calls_made"] += 1
        result["stats"]["total_latency_ms"] += llm_result.get("latency_ms", 0)

        model_used = llm_result.get("model", "unknown")
        if model_used not in result["stats"]["models_used"]:
            result["stats"]["models_used"][model_used] = 0
        result["stats"]["models_used"][model_used] += 1

        cooldown_set = False
        if llm_result["success"]:
            result["stats"]["calls_succeeded"] += 1
            # Parse and validate
            decision = _parse_llm_response(
                llm_result["content"],
                cid,
                npc.get("name", "Unknown"),
                npc.get("affiliation", "independent"),
            )
            if decision:
                result["decisions"].append(decision)
                result["leaders_cognized"] += 1

                # ── NPC Agency: Execute the decision ─────────────────────
                cat = decision.get("category", "")
                desc = decision.get("action_desc", decision.get("description", ""))
                npc_name = npc.get("name", "Unknown")

                if cat == "create_artifact":
                    artifact_title = desc[:80] if desc else f"Creation by {npc_name}"
                    content_prompt = (
                        f"Write the full content of this artifact. "
                        f"\"{desc}\"\n\n"
                        f"Output only the content, no explanations."
                    )
                    content_result = route_call(
                        "general",
                        "You are a creative writer.",
                        content_prompt,
                        api_key=_get_npc_key(cid),
                        char_id=cid,
                        source="cognition",
                        system_path="backend.npc_cognition.leader_artifact",
                    )
                    artifact_content = content_result.get("content", desc)
                    create_npc_artifact(
                        char_id=cid,
                        char_name=npc_name,
                        title=artifact_title,
                        artifact_type="text",
                        content=artifact_content,
                    )
                    decision["agency_action"] = "artifact_created"

                elif cat == "write_code":
                    code_prompt = (
                        f"Generate Python code for this task. "
                        f"\"{desc}\"\n\n"
                        f"Output ONLY valid Python code. No explanations. "
                        f"Use save_result(data, filename) to save outputs."
                    )
                    code_result = route_call(
                        "general",
                        "You are a Python developer. Output only code, no markdown.",
                        code_prompt,
                        api_key=_get_npc_key(cid),
                        char_id=cid,
                        source="cognition",
                        system_path="backend.npc_cognition.leader_code",
                    )
                    gen_code = code_result.get("content", "")
                    if gen_code:
                        sandbox_result = execute_and_register_artifact(
                            char_id=cid,
                            char_name=npc_name,
                            code=gen_code,
                            title=f"Code: {desc[:60]}",
                            artifact_type="code",
                        )
                        decision["agency_action"] = "code_executed"
                        decision["sandbox_output"] = sandbox_result.get(
                            "execution", {}
                        ).get("output", "")

                elif cat == "send_message":
                    target = decision.get("target_faction") or decision.get("target", "")
                    if target and target != "none" and desc:
                        send_npc_message(
                            from_char_id=cid,
                            from_char_name=npc_name,
                            to_char_id=target,
                            subject=desc[:60],
                            body=desc,
                        )
                        decision["agency_action"] = "message_sent"

                elif cat == "read_artifacts":
                    decision["agency_action"] = "artifacts_read"

                # Store to Redis
                try:
                    r.zadd(
                        f"npc_decisions:{cid}", {json.dumps(decision): decision["ts"]}
                    )
                    r.hset(
                        f"npc_cognition:{cid}",
                        mapping={
                            "last_model": model_used,
                            "last_ts": str(now),
                            "last_category": decision["category"],
                            "last_trigger": str(npc_triggers[0]["trigger_type"])
                            if npc_triggers
                            else "ambient",
                        },
                    )
                except Exception:
                    pass

                # Long-term memory (durable, importance-ranked). Leaders now get
                # real persistent memory like the dedicated pair containers, so
                # they retain history across ticks and restarts instead of only
                # transient decisions. Low-significance events are filtered by
                # npc_memory's threshold; never break cognition on memory failure.
                try:
                    from npc_memory import record_memory

                    record_memory(
                        char_id=cid,
                        event={
                            "type": "decision",
                            "category": decision.get("category", "unknown"),
                            "content": decision.get("description") or decision.get("summary") or "",
                            "action_desc": decision.get("description") or "",
                            "reasoning": decision.get("reasoning", ""),
                            "ts": int(now),
                        },
                    )
                except Exception:
                    pass

                # Set cooldown
                _set_cooldown(cid, LEADER_COOLDOWN)
                log_npc_activity(cid, "cognition", {
                    "role": "leader",
                    "category": decision["category"],
                    "trigger_type": str(npc_triggers[0]["trigger_type"]) if npc_triggers else "ambient",
                    "model_used": model_used,
                    "success": True,
                })
                cooldown_set = True
            else:
                turn_error_code = "parse_unparseable"
                result["stats"]["calls_failed"] += 1
                result["errors"].append(f"{cid}: LLM response unparseable")
        else:
            turn_error_code = "llm_failed"
            result["stats"]["calls_failed"] += 1
            result["errors"].append(
                f"{cid}: {llm_result.get('content', 'unknown error')[:100]}"
            )

        if not cooldown_set:
            _set_cooldown(cid, LEADER_COOLDOWN_FAILURE)

        _log_cognition_turn(
            cid,
            "leader",
            system_prompt,
            user_prompt,
            context,
            npc_triggers,
            llm_result,
            turn_error_code,
        )

        # Rate limiting handled by llm_router / NimClient — no artificial delay needed

    # Step 3: Process specialists (only if triggered; skip containerized NPCs)
    for npc in npc_list:
        cid = npc.get("char_id", "")
        if cid not in SPECIALIST_IDS:
            continue
        if cid in CONTAINERIZED_NPCS:
            continue

        # Check max LLM calls per tick
        if llm_calls_this_tick >= max_calls:
            break

        # Check cooldown
        if _is_on_cooldown(cid, "specialist"):
            continue

        # Specialists only cognize if triggered
        npc_triggers = trigger_map.get(cid, [])
        if not npc_triggers:
            continue

        # Build prompt
        context = _get_npc_context(cid)
        system_prompt = _build_specialist_system_prompt(npc, context, world_state)

        top_trigger = max(npc_triggers, key=lambda x: x.get("priority", 0))
        user_prompt = (
            f"Event: {top_trigger['trigger_type']}. "
            f"Data: {json.dumps(top_trigger.get('trigger_data', {}))}. "
            f"How do you respond?"
        )

        # Make LLM call
        llm_result = route_call(
            "specialist",
            system_prompt,
            user_prompt,
            api_key=_get_npc_key(cid),
            char_id=cid,
            source="cognition",
            system_path="backend.npc_cognition.specialist",
        )
        turn_error_code = None
        llm_calls_this_tick += 1
        result["stats"]["calls_made"] += 1
        result["stats"]["total_latency_ms"] += llm_result.get("latency_ms", 0)

        model_used = llm_result.get("model", "unknown")
        if model_used not in result["stats"]["models_used"]:
            result["stats"]["models_used"][model_used] = 0
        result["stats"]["models_used"][model_used] += 1

        cooldown_set = False
        if llm_result["success"]:
            result["stats"]["calls_succeeded"] += 1
            decision = _parse_llm_response(
                llm_result["content"],
                cid,
                npc.get("name", "Unknown"),
                npc.get("affiliation", "independent"),
            )
            if decision:
                result["decisions"].append(decision)
                result["specialists_cognized"] += 1

                # ── NPC Agency: Execute the decision (specialist) ────────
                cat = decision.get("category", "")
                desc = decision.get("action_desc", decision.get("description", ""))
                npc_name = npc.get("name", "Unknown")
                cid_spec = cid

                if cat == "create_artifact":
                    artifact_title = desc[:80] if desc else f"Creation by {npc_name}"
                    content_prompt = (
                        f"Write the full content of this artifact. "
                        f"\"{desc}\"\n\n"
                        f"Output only the content, no explanations."
                    )
                    content_result = route_call(
                        "general",
                        "You are a creative writer.",
                        content_prompt,
                        api_key=_get_npc_key(cid),
                        char_id=cid,
                        source="cognition",
                        system_path="backend.npc_cognition.specialist_artifact",
                    )
                    artifact_content = content_result.get("content", desc)
                    create_npc_artifact(
                        char_id=cid_spec,
                        char_name=npc_name,
                        title=artifact_title,
                        artifact_type="text",
                        content=artifact_content,
                    )
                    decision["agency_action"] = "artifact_created"

                elif cat == "write_code":
                    code_prompt = (
                        f"Generate Python code for this task. "
                        f"\"{desc}\"\n\n"
                        f"Output ONLY valid Python code. No explanations. "
                        f"Use save_result(data, filename) to save outputs."
                    )
                    code_result = route_call(
                        "general",
                        "You are a Python developer. Output only code, no markdown.",
                        code_prompt,
                        api_key=_get_npc_key(cid),
                        char_id=cid,
                        source="cognition",
                        system_path="backend.npc_cognition.specialist_code",
                    )
                    gen_code = code_result.get("content", "")
                    if gen_code:
                        sandbox_result = execute_and_register_artifact(
                            char_id=cid_spec,
                            char_name=npc_name,
                            code=gen_code,
                            title=f"Code: {desc[:60]}",
                            artifact_type="code",
                        )
                        decision["agency_action"] = "code_executed"

                elif cat == "send_message":
                    target = decision.get("target_faction") or decision.get("target", "")
                    if target and target != "none" and desc:
                        send_npc_message(
                            from_char_id=cid_spec,
                            from_char_name=npc_name,
                            to_char_id=target,
                            subject=desc[:60],
                            body=desc,
                        )
                        decision["agency_action"] = "message_sent"

                try:
                    r.zadd(
                        f"npc_decisions:{cid}", {json.dumps(decision): decision["ts"]}
                    )
                    r.hset(
                        f"npc_cognition:{cid}",
                        mapping={
                            "last_model": model_used,
                            "last_ts": str(now),
                            "last_category": decision["category"],
                            "last_trigger": top_trigger["trigger_type"],
                        },
                    )
                except Exception:
                    pass

                # Long-term memory (durable, importance-ranked). Specialists now
                # get real persistent memory like leaders and the dedicated pair
                # containers, so they retain history across ticks and restarts.
                # Low-significance events are filtered by npc_memory's threshold;
                # never break specialist cognition on memory failure.
                try:
                    from npc_memory import record_memory

                    record_memory(
                        char_id=cid,
                        event={
                            "type": "decision",
                            "category": decision.get("category", "unknown"),
                            "content": decision.get("description") or decision.get("summary") or "",
                            "action_desc": decision.get("description") or "",
                            "reasoning": decision.get("reasoning", ""),
                            "ts": int(now),
                        },
                    )
                except Exception:
                    pass

                _set_cooldown(cid, SPECIALIST_COOLDOWN)
                log_npc_activity(cid, "cognition", {
                    "role": "specialist",
                    "category": decision["category"],
                    "trigger_type": top_trigger["trigger_type"],
                    "model_used": model_used,
                    "success": True,
                })
                cooldown_set = True
            else:
                turn_error_code = "parse_unparseable"
                result["stats"]["calls_failed"] += 1
                result["errors"].append(f"{cid}: LLM response unparseable")
        else:
            turn_error_code = "llm_failed"
            result["stats"]["calls_failed"] += 1
            result["errors"].append(
                f"{cid}: {llm_result.get('content', 'unknown error')[:100]}"
            )

        if not cooldown_set:
            _set_cooldown(cid, SPECIALIST_COOLDOWN_FAILURE)

        _log_cognition_turn(
            cid,
            "specialist",
            system_prompt,
            user_prompt,
            context,
            npc_triggers,
            llm_result,
            turn_error_code,
        )

        # Rate limiting handled by llm_router / NimClient — no artificial delay needed

    # Store cognition log
    try:
        log_entry = {
            "ts": now,
            "leaders_cognized": result["leaders_cognized"],
            "specialists_cognized": result["specialists_cognized"],
            "triggers": result["triggers_detected"],
            "decisions": len(result["decisions"]),
            "errors": len(result["errors"]),
        }
        r.zadd("cognition_log", {json.dumps(log_entry): now})
        r.expire("cognition_log", 86400 * 7)
        r.zremrangebyrank("cognition_log", 0, -501)
    except Exception:
        pass

    logger.info(
        "Cognition tick: %d leaders, %d specialists, %d triggers, %d decisions, %d errors",
        result["leaders_cognized"],
        result["specialists_cognized"],
        result["triggers_detected"],
        len(result["decisions"]),
        len(result["errors"]),
    )

    return result


# ── Observer Endpoints Helper ────────────────────────────────────────


def get_cognition_stats() -> Dict:
    """Get cognition layer statistics for the observer dashboard."""
    r = _get_redis()
    now = time.time()

    stats = {
        "router": get_router_stats(),
        "recent_cognition": [],
        "active_triggers": [],
        "npc_cognition_state": {},
    }

    # Recent cognition log entries
    try:
        raw = r.zrevrange("cognition_log", 0, 9)
        for item in raw:
            try:
                stats["recent_cognition"].append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass

    # Active triggers (last 60s)
    try:
        raw = r.zrangebyscore("cognition_triggers", now - 60, now)
        for item in raw:
            try:
                stats["active_triggers"].append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass

    # Per-NPC cognition state for leaders
    for cid in LEADER_IDS:
        try:
            cog = r.hgetall(f"npc_cognition:{cid}")
            if cog:
                stats["npc_cognition_state"][cid] = cog
        except Exception:
            pass

    return stats
