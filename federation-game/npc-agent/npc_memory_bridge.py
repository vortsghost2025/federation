"""
Councilor Memory Bridge — typed persistent memory for char_001 and char_306.

Phase 1 of the Genesis → Federation memory bridge.
Each councilor gets independent Redis-backed typed memory with importance
scoring, recency + importance retrieval, and auto-consolidation.

Usage:
    from npc_memory_bridge import CouncilorMemory, record_councilor_memory
    mem = CouncilorMemory(r, "char_001")
    mem.add_idea("I discovered an anomaly in sector 7.", tick=142, importance=0.8)
    memories = mem.get_context_for_prompt(tick=150)
    record_councilor_memory(decision, r, tick, char_id="char_001")
"""
import json
import logging
import os
import time
from difflib import SequenceMatcher

logger = logging.getLogger("npc_memory_bridge")

CHAR_ID = os.environ.get("CHAR_ID", "")

MAX_MEMORIES = 200
CONSOLIDATION_INTERVAL = 10
MAX_CONTEXT_MEMORIES = 8
CONTENT_MAX_LENGTH = 500

DISCOVERY_KEYWORDS = {"discover", "find", "uncover", "reveal", "detect", "locate", "expose"}
SOCIAL_KEYWORDS = {"relationship", "trust", "alliance", "betray", "negotiate", "collaborate", "discuss", "partner"}
CRITICAL_KEYWORDS = {"critical", "emergency", "warning", "urgent", "crisis", "breach", "alert"}
GENERIC_PATTERNS = [
    "i observe the federation",
    "i analyze the latest reports",
    "i observe the current situation",
    "i analyze the latest data",
    "i monitor the situation",
    "i analyze the current situation",
    "i observe the current state",
]


def _mem_key(char_id):
    return f"councilor_memory:{char_id}:memories"


def _imp_key(char_id):
    return f"councilor_memory:{char_id}:important"


def _seq_key(char_id):
    return f"councilor_memory:{char_id}:next_seq"


def _stats_key(char_id):
    return f"councilor_memory:{char_id}:stats"


def _char_id():
    return CHAR_ID or ""


def _compute_importance(thought, action):
    text = f"{thought} {action}".lower()
    importance = 0.5
    if any(kw in text for kw in DISCOVERY_KEYWORDS):
        importance += 0.3
    if any(kw in text for kw in CRITICAL_KEYWORDS):
        importance += 0.2
    if any(kw in text for kw in SOCIAL_KEYWORDS):
        importance += 0.1
    thought_lower = thought.lower().strip()
    for pat in GENERIC_PATTERNS:
        ratio = SequenceMatcher(None, thought_lower, pat).ratio()
        if ratio > 0.85:
            importance -= 0.15
            break
    return max(0.0, min(1.0, importance))


def _has_discovery_keywords(action):
    text = action.lower()
    return any(kw in text for kw in DISCOVERY_KEYWORDS)


def _has_social_keywords(action):
    text = action.lower()
    return any(kw in text for kw in SOCIAL_KEYWORDS)


def _truncate(text, max_len=CONTENT_MAX_LENGTH):
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


class CouncilorMemory:

    def __init__(self, r, char_id=None):
        self.r = r
        self.char_id = char_id or _char_id()
        if not self.char_id:
            raise ValueError("char_id is required for CouncilorMemory")

    def add(self, mem_type, content, tick, importance=None):
        if importance is None:
            importance = 0.5
        importance = max(0.0, min(1.0, importance))
        content = _truncate(content)
        if not content or len(content) < 3:
            return None
        seq = int(self.r.incr(_seq_key(self.char_id)))
        mem_id = f"{self.char_id}_mem_{seq}"
        memory = {
            "id": mem_id,
            "type": mem_type,
            "content": content,
            "tick": tick,
            "importance": importance,
            "accessed_count": 0,
            "created_at": int(time.time()),
        }
        mem_json = json.dumps(memory, default=str)
        self.r.zadd(_mem_key(self.char_id), {mem_json: tick})
        self.r.zadd(_imp_key(self.char_id), {mem_json: importance})
        self.r.hincrby(_stats_key(self.char_id), "total", 1)
        self.r.hincrby(_stats_key(self.char_id), f"type:{mem_type}", 1)
        self.r.hset(_stats_key(self.char_id), "last_tick", str(tick))
        return memory

    def add_event(self, content, tick, importance=0.4):
        return self.add("event", content, tick, importance)

    def add_idea(self, content, tick, importance=0.5):
        return self.add("idea", content, tick, importance)

    def add_observation(self, content, tick, importance=0.7):
        return self.add("observation", content, tick, importance)

    def add_relationship(self, content, tick, importance=0.3):
        return self.add("relationship", content, tick, importance)

    def add_skill(self, content, tick, importance=0.5):
        return self.add("skill", content, tick, importance)

    def get_context_for_prompt(self, tick, max_memories=MAX_CONTEXT_MEMORIES):
        if not self.r.exists(_mem_key(self.char_id)):
            return ""
        candidate_raw = self.r.zrevrange(_mem_key(self.char_id), 0, max_memories * 2 - 1)
        candidate_mems = []
        for m in candidate_raw:
            try:
                mem = json.loads(m)
                candidate_mems.append(mem)
            except Exception:
                pass
        candidate_ids = {m.get("id") for m in candidate_mems}
        n_high = max_memories - len(candidate_mems)
        if n_high > 0:
            important_raw = self.r.zrevrangebyscore(
                _imp_key(self.char_id), 1.0, 0.7,
                start=0, num=n_high
            )
            for m in important_raw:
                try:
                    mem = json.loads(m)
                    if mem.get("id") not in candidate_ids:
                        candidate_mems.append(mem)
                        candidate_ids.add(mem.get("id"))
                except Exception:
                    pass
        candidate_mems.sort(key=lambda m: m.get("tick", 0), reverse=True)
        candidate_mems = candidate_mems[:max_memories]
        if not candidate_mems:
            return ""
        lines = ["## Your Memories"]
        for mem in candidate_mems:
            mtype = mem.get("type", "note")
            mtick = mem.get("tick", 0)
            imp = mem.get("importance", 0.0)
            content = mem.get("content", "")
            lines.append(f"  - [{mtype}] (tick {mtick}, imp {imp:.1f}): {content}")
        return "\n".join(lines)

    def get_stats(self):
        return self.r.hgetall(_stats_key(self.char_id))

    def consolidate(self, max_memories=MAX_MEMORIES):
        mem_key = _mem_key(self.char_id)
        imp_key = _imp_key(self.char_id)
        count = self.r.zcard(mem_key)
        if count <= max_memories:
            return count
        raw = self.r.zrange(mem_key, 0, -1, withscores=True)
        scored = []
        current_tick = int(self.r.hget(_stats_key(self.char_id), "last_tick") or 0)
        for mem_json, tick in raw:
            try:
                mem = json.loads(mem_json)
                imp = float(mem.get("importance", 0.0))
                age = max(current_tick - int(mem.get("tick", 0)), 1)
                recency = 1.0 / age
                score = imp * 0.6 + recency * 0.4
                mem_str = mem_json.decode("utf-8") if isinstance(mem_json, bytes) else mem_json
                scored.append((score, mem_str, mem))
            except Exception:
                pass
        scored.sort(key=lambda x: x[0], reverse=True)
        keep = scored[:max_memories]
        self.r.delete(mem_key)
        self.r.delete(imp_key)
        for _score, mem_json, mem in keep:
            self.r.zadd(mem_key, {mem_json: mem.get("tick", 0)})
            self.r.zadd(imp_key, {mem_json: mem.get("importance", 0.0)})
        removed = count - len(keep)
        if removed > 0:
            logger.info("[%s] Memory consolidation: %d -> %d (%d removed)", self.char_id, count, len(keep), removed)
        return len(keep)

    def clear(self):
        self.r.delete(_mem_key(self.char_id))
        self.r.delete(_imp_key(self.char_id))
        self.r.delete(_seq_key(self.char_id))
        self.r.delete(_stats_key(self.char_id))


def record_councilor_memory(decision, r, tick, char_id=None):
    cid = char_id or _char_id()
    if not cid:
        return
    try:
        mem = CouncilorMemory(r, cid)
        thought = decision.get("thought", decision.get("reasoning", ""))
        action = decision.get("action", decision.get("description", ""))
        if len(str(thought)) > 10:
            importance = _compute_importance(str(thought), str(action))
            mem.add_idea(str(thought), tick, importance)
        if action:
            mem.add_event(str(action), tick, 0.4)
        if _has_discovery_keywords(str(action)):
            mem.add_observation(str(action), tick, 0.7)
        if decision.get("to") or _has_social_keywords(str(action)):
            mem.add_relationship(str(action), tick, 0.3)
        if tick > 0 and tick % CONSOLIDATION_INTERVAL == 0:
            mem.consolidate()
        logger.info("[%s] Memory bridge: recorded memories at tick %d", cid, tick)
    except Exception as e:
        logger.warning("[%s] Memory bridge recording failed (best-effort): %s", cid, e)
