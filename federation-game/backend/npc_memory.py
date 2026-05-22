"""
NPC Memory / History System
Long-term memory accumulation with LLM-generated reflective summaries.
NPCs remember significant events instead of forgetting everything when
the short-term thought ZSET rotates.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any

import redis

try:
    from llm_router import route_llm_call

    LLM_ROUTER_AVAILABLE = True
except ImportError:
    LLM_ROUTER_AVAILABLE = False

logger = logging.getLogger(__name__)

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MEMORY_ZSET_KEY = "npc_memory:{char_id}"
MEMORY_SUMMARY_KEY = "npc_memory_summary:{char_id}"
MEMORY_SUMMARY_TICK_KEY = "npc_memory_summary_tick:{char_id}"
MEMORY_MAX_EVENTS = 200
MEMORY_SIGNIFICANCE_THRESHOLD = 3
SUMMARY_INTERVAL_TICKS = 20
SUMMARY_MAX_CHARS = 2000


def _get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def _significance_score(event: Dict) -> int:
    score = 1
    etype = event.get("type", "")
    if etype in (
        "faction_change",
        "treaty",
        "war",
        "era_shift",
        "death",
        "birth",
        "promotion",
        "demotion",
        "quest_chain_advance",
    ):
        score += 4
    elif etype in (
        "quest_complete",
        "quest_fail",
        "research_breakthrough",
        "diplomacy_proposal",
    ):
        score += 3
    elif etype in ("mood_shift", "opinion_change", "action", "thought"):
        score += 1
    if event.get("faction_impact"):
        score += 2
    if event.get("relationship_change"):
        score += 1
    if event.get("emotional_intensity", 0) > 0.7:
        score += 2
    return score


def record_memory(char_id: str, event: Dict, score: Optional[int] = None) -> Dict:
    if score is None:
        score = _significance_score(event)
    if score < MEMORY_SIGNIFICANCE_THRESHOLD:
        return {"status": "below_threshold", "score": score, "recorded": False}
    r = _get_redis()
    key = MEMORY_ZSET_KEY.format(char_id=char_id)
    ts = event.get("ts") or int(time.time())
    event_copy = dict(event)
    event_copy["ts"] = ts
    event_copy["memory_score"] = score
    member = json.dumps(event_copy)
    r.zadd(key, {member: ts})
    r.zremrangebyrank(key, 0, -(MEMORY_MAX_EVENTS + 1))
    r.expire(key, 86400 * 90)
    return {"status": "recorded", "score": score, "ts": ts, "recorded": True}


def record_memories_batch(char_id: str, events: List[Dict]) -> Dict:
    recorded = 0
    skipped = 0
    for event in events:
        result = record_memory(char_id, event)
        if result.get("recorded"):
            recorded += 1
        else:
            skipped += 1
    return {"recorded": recorded, "skipped": skipped, "total": len(events)}


def get_memories(char_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
    r = _get_redis()
    key = MEMORY_ZSET_KEY.format(char_id=char_id)
    raw = r.zrevrange(key, offset, offset + limit - 1, withscores=True)
    memories = []
    for member, score in raw:
        try:
            mem = json.loads(member)
            memories.append(mem)
        except (json.JSONDecodeError, TypeError):
            continue
    return memories


def get_memory_summary(char_id: str) -> Optional[str]:
    r = _get_redis()
    key = MEMORY_SUMMARY_KEY.format(char_id=char_id)
    return r.get(key)


def generate_reflective_summary(char_id: str, npc_name: str = "") -> Dict:
    memories = get_memories(char_id, limit=60)
    if not memories:
        return {"status": "no_memories", "summary": None}
    existing = get_memory_summary(char_id) or ""
    memory_lines = []
    for m in memories[:40]:
        ts = m.get("ts", "?")
        etype = m.get("type", "event")
        desc = m.get("description", m.get("content", m.get("thought", str(m)[:120])))
        memory_lines.append(f"[{ts}] ({etype}) {desc}")
    memory_block = "\n".join(memory_lines)
    prompt = (
        f"You are generating a reflective memory summary for an NPC named {npc_name or char_id}.\n"
        f"Here is their previous summary:\n{existing[:800]}\n\n"
        f"Here are their recent significant memories:\n{memory_block}\n\n"
        f"Write a concise reflective summary (max {SUMMARY_MAX_CHARS} chars) of what this NPC has experienced, "
        f"learned, and how they've changed. Write in second person as the NPC's inner voice. "
        f"Focus on emotional arcs, key relationships, turning points."
    )
    new_summary = None
    if LLM_ROUTER_AVAILABLE:
        try:
            resp = route_llm_call(
                prompt=prompt,
                system="You write concise, evocative NPC memory summaries for a space federation simulation.",
                max_tokens=400,
            )
            new_summary = resp.strip()[:SUMMARY_MAX_CHARS]
        except Exception as exc:
            logger.warning("LLM summary generation failed for %s: %s", char_id, exc)
    if not new_summary:
        recent_types = {}
        for m in memories[:30]:
            t = m.get("type", "unknown")
            recent_types[t] = recent_types.get(t, 0) + 1
        dominant = sorted(recent_types.items(), key=lambda x: -x[1])[:5]
        dominant_str = ", ".join(f"{t}({c})" for t, c in dominant)
        new_summary = (
            f"[{npc_name or char_id}] Recalls {len(memories)} significant events. "
            f"Recent themes: {dominant_str}. {existing[:600]}"
        )[:SUMMARY_MAX_CHARS]
    r = _get_redis()
    summary_key = MEMORY_SUMMARY_KEY.format(char_id=char_id)
    r.set(summary_key, new_summary, ex=86400 * 30)
    return {
        "status": "generated",
        "summary": new_summary,
        "memories_processed": len(memories),
    }


def harvest_tick_memories(
    npc_list: List[Dict],
    tick_decisions: List[Dict],
    tick_ts: int,
    tick_results: Optional[Dict] = None,
) -> Dict:
    r = _get_redis()
    harvested = 0
    summaries_triggered = 0
    for npc, decision in zip(npc_list, tick_decisions):
        char_id = npc.get("char_id", npc.get("id", ""))
        if not char_id:
            continue
        events = []
        thought = decision.get("thought", "")
        action = decision.get("action", "")
        if thought:
            events.append(
                {
                    "type": "thought",
                    "content": thought[:300],
                    "ts": tick_ts,
                    "emotional_intensity": decision.get("emotional_intensity", 0.3),
                }
            )
        if action:
            events.append(
                {
                    "type": "action",
                    "content": action[:300],
                    "ts": tick_ts,
                    "faction_impact": decision.get("faction_impact", False),
                }
            )
        mood = decision.get("mood_change")
        if mood:
            events.append(
                {
                    "type": "mood_shift",
                    "content": f"Mood shifted: {mood}",
                    "ts": tick_ts,
                    "emotional_intensity": 0.6,
                }
            )
        opinion = decision.get("opinion_change")
        if opinion:
            events.append(
                {
                    "type": "opinion_change",
                    "content": f"Opinion changed: {opinion}",
                    "ts": tick_ts,
                    "relationship_change": True,
                }
            )
        faction_event = decision.get("faction_event")
        if faction_event:
            events.append(
                {
                    "type": "faction_change",
                    "content": str(faction_event)[:300],
                    "ts": tick_ts,
                    "faction_impact": True,
                }
            )
        quest_event = decision.get("quest_event")
        if quest_event:
            events.append(
                {
                    "type": "quest_event",
                    "content": str(quest_event)[:300],
                    "ts": tick_ts,
                }
            )
        # P24c: Harvest additional event types from tick results
        if tick_results:
            # Quest completions for this NPC
            quest_data = tick_results.get("step7_npc_quests", {})
            completed_quests = quest_data.get("completed_details", [])
            for cq in completed_quests:
                if cq.get("char_id") == char_id:
                    events.append(
                        {
                            "type": "quest_complete",
                            "content": f"Completed quest: {cq.get('quest_id', 'unknown')} - {cq.get('quest_title', '')[:100]}",
                            "ts": tick_ts,
                            "faction_impact": bool(
                                cq.get("rewards", {}).get("reputation")
                            ),
                        }
                    )
            # Diplomacy events (applies to all NPCs in affected factions)
            diplo_data = tick_results.get("step8_5_diplomacy", {})
            proposals = diplo_data.get("proposals", [])
            for prop in proposals:
                if isinstance(prop, dict):
                    factions_involved = (
                        prop.get("faction_a", "") + " " + prop.get("faction_b", "")
                    )
                    npc_faction = npc.get("faction_id", npc.get("faction", ""))
                    if npc_faction and npc_faction in factions_involved:
                        events.append(
                            {
                                "type": "diplomacy_proposal",
                                "content": f"Diplomacy: {prop.get('diplomacy_type', 'unknown')} proposed between {prop.get('faction_a', '?')} and {prop.get('faction_b', '?')}",
                                "ts": tick_ts,
                                "faction_impact": True,
                            }
                        )
            # Era transitions
            era_data = tick_results.get("step5_era_check", {})
            if era_data.get("era_advanced"):
                events.append(
                    {
                        "type": "era_shift",
                        "content": f"Era advanced to: {era_data.get('recommended_era', 'unknown')}",
                        "ts": tick_ts,
                        "faction_impact": True,
                    }
                )
        if events:
            result = record_memories_batch(char_id, events)
            harvested += result.get("recorded", 0)
            summary_tick_key = MEMORY_SUMMARY_TICK_KEY.format(char_id=char_id)
            last_summary_tick = r.get(summary_tick_key)
            if (
                last_summary_tick is None
                or (tick_ts - int(last_summary_tick)) >= SUMMARY_INTERVAL_TICKS
            ):
                npc_name = npc.get("name", char_id)
                try:
                    generate_reflective_summary(char_id, npc_name)
                    r.set(summary_tick_key, str(tick_ts), ex=86400 * 30)
                    summaries_triggered += 1
                except Exception as exc:
                    logger.warning("Auto-summary failed for %s: %s", char_id, exc)
    return {
        "harvested": harvested,
        "summaries_triggered": summaries_triggered,
        "npcs_processed": len(npc_list),
    }
