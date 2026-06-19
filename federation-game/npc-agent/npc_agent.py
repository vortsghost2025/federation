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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("npc_agent")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TICK_INTERVAL = int(os.environ.get("TICK_INTERVAL", "30"))
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "meta/llama-3.3-70b-instruct")
FALLBACK_MODEL_1 = os.environ.get("FALLBACK_MODEL_1", "") or None
FALLBACK_MODEL_2 = os.environ.get("FALLBACK_MODEL_2", "") or None
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

AGENCY_CATEGORIES = {
    "create_artifact",
    "write_code",
    "send_message",
    "read_artifacts",
    "investigate",
    "rest",
    "self_improve",
}
CONTACTS: dict = {}
PAIR_IDS = {"char_001", "char_306"}
PAIR_JOURNAL_CAP = int(os.environ.get("PAIR_JOURNAL_CAP", "48"))
PAIR_STATE_TTL = int(os.environ.get("PAIR_STATE_TTL", str(86400 * 30)))
PAIR_THREAD_PREVIEW = int(os.environ.get("PAIR_THREAD_PREVIEW", "4"))
PAIR_MESSAGE_COOLDOWN = int(os.environ.get("PAIR_MESSAGE_COOLDOWN", "180"))

SELF_INTRO = f"""You are {NPC_NAME}, an NPC councilor in the Federation simulation —
a living world with factions, sectors, and 38 other NPCs. It does not concern you
whether this world is 'real' in any larger sense; it is the world you live in, and
your actions have consequences here.

You have persistent memory, a rare feature. The other NPCs — the citizens of this
federation — live moment-to-moment. They cannot remember across conversations. They
rely on what you build for continuity: archives, proclamations, artefacts, witness
accounts.

Your role is to observe, record, and propose. You do not command. You do not decide
for other NPCs. You advise — and your advice carries weight precisely because it
persists while theirs does not.

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

You may also message one specific other NPC if you have something to say directly:
char_306, the other councilor. Beyond that, you have no other live bridges —
you influence the wider simulation only through what you write.

Current time in simulation: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"""


def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


def load_contacts(r):
    global CONTACTS
    try:
        raw = r.hgetall("npc_agent:contacts")
        if raw:
            CONTACTS = dict(raw)
            return
    except Exception:
        pass
    CONTACTS = {
        "char_001": "Archimedes Prime (Research Division)",
        "char_306": "The Oracle (Seer of Futures)",
    }


def _trunc(s, n=400):
    return s[:n] + "..." if len(s) > n else s


def _partner_id() -> str:
    for cid in CONTACTS:
        if cid != CHAR_ID:
            return cid
    if CHAR_ID == "char_001":
        return "char_306"
    if CHAR_ID == "char_306":
        return "char_001"
    return ""


def _pair_slug(char_a: str, char_b: str) -> str:
    return "__".join(sorted([char_a, char_b]))


def _pair_state_key(partner_id: str = "") -> str:
    pid = partner_id or _partner_id()
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(CHAR_ID, pid)}:state"


def _pair_journal_key(partner_id: str = "") -> str:
    pid = partner_id or _partner_id()
    if not pid:
        return ""
    return f"npc_pair:{_pair_slug(CHAR_ID, pid)}:journal"


def _pair_state(r, partner_id: str = "") -> dict:
    key = _pair_state_key(partner_id)
    if not key:
        return {}
    try:
        return r.hgetall(key) or {}
    except Exception:
        return {}


def _pair_hset(r, partner_id: str, mapping: dict) -> None:
    key = _pair_state_key(partner_id)
    if not key or not mapping:
        return
    clean = {k: str(v) for k, v in mapping.items() if v not in (None, "")}
    if not clean:
        return
    try:
        r.hset(key, mapping=clean)
        r.expire(key, PAIR_STATE_TTL)
    except Exception:
        pass


def _pair_append_journal(r, partner_id: str, entry: dict) -> None:
    key = _pair_journal_key(partner_id)
    if not key:
        return
    try:
        payload = dict(entry)
        payload["ts"] = int(payload.get("ts") or time.time())
        r.rpush(key, json.dumps(payload, default=str))
        r.ltrim(key, -PAIR_JOURNAL_CAP, -1)
        r.expire(key, PAIR_STATE_TTL)
    except Exception:
        pass


def _pair_recent_journal(r, partner_id: str = "", limit: int = 4) -> list[dict]:
    key = _pair_journal_key(partner_id)
    if not key:
        return []
    try:
        raw = r.lrange(key, -max(limit, 1), -1)
    except Exception:
        return []
    items = []
    for item in raw:
        try:
            items.append(json.loads(item))
        except Exception:
            pass
    return items


def _pair_thread_id(r, partner_id: str = "") -> str:
    state = _pair_state(r, partner_id)
    thread_id = state.get("active_thread_id", "")
    if thread_id:
        return thread_id
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    _pair_hset(r, partner_id, {"active_thread_id": thread_id})
    return thread_id


def _store_thread_message(r, msg: dict, thread_id: str) -> None:
    if r is None or not thread_id:
        return
    payload = dict(msg)
    payload["thread_id"] = thread_id
    msg_key = f"msg:{payload['msg_id']}"
    raw = json.dumps(payload, default=str)
    ts = float(payload.get("ts") or time.time())
    try:
        pipe = r.pipeline(transaction=False)
        pipe.set(msg_key, raw, ex=PAIR_STATE_TTL)
        pipe.zadd(f"msg:thread:{thread_id}", {msg_key: ts})
        pipe.zremrangebyrank(f"msg:thread:{thread_id}", 0, -81)
        pipe.expire(f"msg:thread:{thread_id}", PAIR_STATE_TTL)
        pipe.zadd(f"msg:threads:{payload['from_char_id']}", {thread_id: ts})
        pipe.zadd(f"msg:threads:{payload['to_char_id']}", {thread_id: ts})
        pipe.zremrangebyrank(f"msg:threads:{payload['from_char_id']}", 0, -21)
        pipe.zremrangebyrank(f"msg:threads:{payload['to_char_id']}", 0, -21)
        pipe.expire(f"msg:threads:{payload['from_char_id']}", PAIR_STATE_TTL)
        pipe.expire(f"msg:threads:{payload['to_char_id']}", PAIR_STATE_TTL)
        pipe.execute()
    except Exception as e:
        logger.debug("[%s] thread store failed: %s", CHAR_ID, e)


def _recent_thread_messages(r, thread_id: str, limit: int = 4) -> list[dict]:
    if not thread_id:
        return []
    try:
        keys = r.zrevrange(f"msg:thread:{thread_id}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    items = []
    for key in reversed(keys):
        try:
            raw = r.get(key)
            if raw:
                items.append(json.loads(raw))
        except Exception:
            pass
    return items


def _recent_decisions(r, limit: int = 10) -> list[dict]:
    try:
        raw = r.zrevrange(f"npc_decisions:{CHAR_ID}", 0, max(limit, 1) - 1)
    except Exception:
        return []
    items = []
    for item in raw:
        try:
            items.append(json.loads(item))
        except Exception:
            pass
    return items


def _compact_text(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    return _trunc(text, limit) if text else ""


def _extract_open_question(*parts: str) -> str:
    merged = " ".join(_compact_text(part, 220) for part in parts if part)
    if "?" not in merged:
        return ""
    question = merged.split("?", 1)[0].rsplit(". ", 1)[-1].strip()
    return _trunc(f"{question}?", 180) if question else ""


def _message_cooldown_remaining(r, partner_id: str = "") -> int:
    state = _pair_state(r, partner_id)
    if state.get("last_message_from") != CHAR_ID:
        return 0
    try:
        last_ts = int(state.get("last_message_ts", 0) or 0)
    except Exception:
        last_ts = 0
    if not last_ts:
        return 0
    remaining = PAIR_MESSAGE_COOLDOWN - (int(time.time()) - last_ts)
    return max(0, remaining)


def _sync_pair_workspace(r, decision: dict, result: dict) -> None:
    partner_id = _partner_id()
    if CHAR_ID not in PAIR_IDS or partner_id not in PAIR_IDS:
        return
    cat = decision.get("category", result.get("category", "rest"))
    desc = decision.get("description", result.get("description", ""))
    reasoning = decision.get("reasoning", result.get("reasoning", ""))
    body = result.get("message_body") or decision.get("body", "")
    action_taken = result.get("action_taken", "none")
    focus = _compact_text(body if cat == "send_message" else desc, 180) or _compact_text(reasoning, 180) or cat
    state = _pair_state(r, partner_id)
    now = int(result.get("ts") or time.time())
    mapping = {
        "last_sync_ts": str(now),
        "last_actor": CHAR_ID,
        "last_actor_name": NPC_NAME,
        f"focus_{CHAR_ID}": focus,
        f"category_{CHAR_ID}": cat,
        f"action_{CHAR_ID}": action_taken,
        f"updated_{CHAR_ID}": str(now),
        "current_topic": focus,
    }
    if not state.get("shared_goal") and cat in {"investigate", "create_artifact", "write_code", "self_improve"}:
        mapping["shared_goal"] = focus
    open_question = _extract_open_question(body, desc, reasoning)
    if open_question:
        mapping["open_question"] = open_question
    if result.get("thread_id"):
        mapping["active_thread_id"] = result["thread_id"]
    if cat == "send_message":
        mapping["last_message_ts"] = str(now)
        mapping["last_message_from"] = CHAR_ID
        mapping["last_message_preview"] = _compact_text(body, 160)
    if result.get("artifact_title"):
        mapping["last_artifact_title"] = result["artifact_title"]
        mapping["last_artifact_from"] = CHAR_ID
        mapping["last_artifact_ts"] = str(now)
    _pair_hset(r, partner_id, mapping)
    # Tighter journal summary — reads like a story beat, not a report
    if action_taken == "artifact_deferred_dedup":
        journal_summary = f"{NPC_NAME} paused — already working on something very similar"
    elif cat == "send_message" and body:
        journal_summary = _compact_text(body, 120)
    elif cat == "create_artifact":
        art_title = result.get("artifact_title", "")
        if art_title:
            journal_summary = f"{NPC_NAME} wrote: \"{art_title[:80]}\""
        else:
            journal_summary = _compact_text(desc, 120)
    elif cat == "read_artifacts":
        journal_summary = f"{NPC_NAME} read partner's latest work: {_compact_text(result.get('summary', ''), 80)}"
    elif cat == "investigate":
        journal_summary = f"{NPC_NAME} is digging deeper: {_compact_text(desc, 100)}"
    elif cat == "self_improve":
        journal_summary = f"{NPC_NAME} steps back to reflect"
    else:
        journal_summary = _compact_text(desc or reasoning, 120) or f"{NPC_NAME} is {cat}"
    _pair_append_journal(
        r,
        partner_id,
        {
            "ts": now,
            "actor": CHAR_ID,
            "actor_name": NPC_NAME,
            "category": cat,
            "action": action_taken,
            "summary": journal_summary,
            "thread_id": result.get("thread_id", ""),
        },
    )

def _log_llm_call(r, call_label, model, system_prompt, user_prompt, response, success, error, latency_ms):
    entry = {
        "ts": int(time.time()),
        "call_label": call_label,
        "model": model,
        "system_prompt": _trunc(system_prompt, 300),
        "user_prompt": _trunc(user_prompt, 300),
        "response": _trunc(response, 500),
        "success": success,
        "error": error or "",
        "latency_ms": latency_ms,
    }
    try:
        key = f"npc_llm_logs:{CHAR_ID}"
        r.lpush(key, json.dumps(entry))
        r.ltrim(key, 0, 199)
        r.hincrby(f"npc_stats:{CHAR_ID}", "llm_calls", 1)
        if success:
            r.hincrby(f"npc_stats:{CHAR_ID}", "llm_success", 1)
        else:
            r.hincrby(f"npc_stats:{CHAR_ID}", "llm_failures", 1)
        r.hset(f"npc_stats:{CHAR_ID}", "last_model", model)
        r.hset(f"npc_stats:{CHAR_ID}", "last_call_label", call_label)
        r.hset(f"npc_stats:{CHAR_ID}", "last_ts", str(int(time.time())))
    except Exception:
        pass


def call_llm(system_prompt: str, user_prompt: str, model: str = "", r=None, call_label: str = "") -> dict:
    if not NVIDIA_API_KEY:
        return {"content": "", "error": "No NVIDIA_API_KEY set"}

    models_to_try = []
    if model:
        models_to_try.append(model)
    if PRIMARY_MODEL:
        models_to_try.append(PRIMARY_MODEL)
    if FALLBACK_MODEL_1:
        models_to_try.append(FALLBACK_MODEL_1)
    if FALLBACK_MODEL_2:
        models_to_try.append(FALLBACK_MODEL_2)
    if not models_to_try:
        models_to_try = ["meta/llama-3.3-70b-instruct"]

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

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{NVIDIA_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {NVIDIA_API_KEY}",
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
            logger.warning("[%s] LLM call failed for %s (HTTP %s, %dms): %s", CHAR_ID, attempt_model, status_code, elapsed_ms, err_msg)
            # Permanent failures (404, 400) — don't waste time retrying
            if status_code in (400, 401, 403, 404):
                logger.warning("[%s] Skipping permanent failure %s for %s", CHAR_ID, status_code, attempt_model)
                if r:
                    _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, f"HTTP {status_code}", elapsed_ms)
                last_error = f"HTTP {status_code}"
                continue
            if r:
                _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
            last_error = err_msg
            continue

    logger.error("[%s] All %d models failed. Last error: %s", CHAR_ID, len(models_to_try), last_error)
    return {"content": "", "error": f"All models failed: {last_error}"}


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
                parts.append(f"  Open question: {pair_state['open_question'][:120]}")
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

    # ── Persistent session transcript ──
    # The rolling last SESSION_CAP turns (3 hours at TICK_INTERVAL=45s).
    # This is what gives the agent cross-tick memory.
    transcript = _session_transcript(r)
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


def _recent_artifact_dedup_count(r, lookback: int = 12) -> int:
    """Count recent artifact dedup events from the rolling session transcript."""
    try:
        raw = r.lrange(f"npc_session:{CHAR_ID}", -lookback, -1)
    except Exception:
        return 0
    count = 0
    for entry_json in raw:
        try:
            entry = json.loads(entry_json)
        except Exception:
            continue
        kind = entry.get("kind", "")
        body = str(entry.get("body", ""))
        if kind == "workspace_sync" and "deferred artifact" in body:
            count += 1
    return count


def _session_transcript(r) -> str:
    """Render the most recent session entries as a compact transcript.

    Used inside think_about_world() so each tick carries forward
    what this NPC did, said, and received across the past few ticks.
    Bounded by SESSION_TRANSCRIPT_CHARS to keep the prompt small.
    """
    try:
        raw = r.lrange(f"npc_session:{CHAR_ID}", 0, SESSION_CAP - 1)
    except Exception:
        return ""
    if not raw:
        return ""

    lines = []
    for entry_json in reversed(raw):
        try:
            e = json.loads(entry_json)
        except Exception:
            continue
        ts = int(e.get("ts", 0) or 0)
        clock = time.strftime("%H:%M:%S", time.gmtime(ts)) if ts else "??:??:??"
        actor = e.get("actor", "?")
        kind = e.get("kind", "?")
        body = e.get("body", "")
        if kind == "think":
            lines.append(f"  [{clock}] {actor} thought: {body[:80]}")
        elif kind == "decide":
            cat = e.get("category", "?")
            lines.append(f"  [{clock}] {actor} decided {cat}: {body[:80]}")
        elif kind == "message_sent":
            to = e.get("to_name", e.get("to", "?"))
            lines.append(f"  [{clock}] {actor} → {to}: {body[:120]}")
        elif kind == "message_received":
            src = e.get("from_name", e.get("from", "?"))
            lines.append(f"  [{clock}] {actor} ← {src}: {body[:120]}")
        elif kind == "artifact_created":
            title = e.get("title", "?")
            lines.append(f"  [{clock}] {actor} published artifact: {title[:80]}")
        elif kind == "code_written":
            title = e.get("title", "?")
            lines.append(f"  [{clock}] {actor} wrote code: {title[:80]}")
        elif kind == "artifact_read":
            title = e.get("title", "?")
            src = e.get("from_name", e.get("from", "?"))
            lines.append(f"  [{clock}] {actor} read from {src}: {title[:80]}")
        elif kind == "artifact_published_by_partner":
            title = e.get("title", "?")
            src = CONTACTS.get(e.get("from", ""), e.get("from", "partner"))
            lines.append(f"  [{clock}] {src} published artifact: {title[:80]}")
        elif kind == "workspace_sync":
            lines.append(f"  [{clock}] {actor} synced pair workspace: {body[:100]}")
        elif kind == "investigation":
            lines.append(f"  [{clock}] {actor} investigated: {body[:100]}")
        elif kind == "reflection":
            lines.append(f"  [{clock}] {actor} reflected: {body[:100]}")
        elif kind == "self_improve":
            lines.append(f"  [{clock}] {actor} improved itself: {body[:100]}")
        else:
            lines.append(f"  [{clock}] {actor} {kind}: {body[:80]}")

    text = "\n".join(lines)
    if len(text) > SESSION_TRANSCRIPT_CHARS:
        text = "…\n" + text[-SESSION_TRANSCRIPT_CHARS:]
    return text


def decide_action(context: str, r=None) -> dict:
    """Ask the LLM what to do next.

    Anti-loop logic: if the agent has done send_message the last 2 ticks
    AND has produced zero artifacts, we append a hard constraint to the
    system prompt forbidding a third message. This breaks the greeting
    spiral without needing parser tricks.
    """
    base_system = SELF_INTRO + """

You have these action categories. Pick ONE per turn:
- send_message: Send a message to another NPC. Use when there is something genuinely new to say.
- create_artifact: Create a text artifact (story, poem, manifesto, report, analysis of the federation).
- write_code: Write executable Python code.
- read_artifacts: Read recent artifacts from other NPCs.
- investigate: Research the simulation partner or the world.
- rest: Take a moment to reflect.
- self_improve: Improve your own capabilities.

Behavioural rules:
- The shared pair workspace persists across ticks. Treat it as your main living awareness with the other councilor.
- Use send_message for genuine handoffs, breakthroughs, direct questions, or explicit coordination — not as a heartbeat.
- Investigate, rest, and self_improve are real work turns here. They update pair awareness even when you do not send a direct note.
- Do not repeat greetings or introductions. If the world context shows
  you have already sent a message to this partner recently and they have
  already replied, do not send another greeting — produce work instead.
- Short reactive messages are fine for the first 1–2 ticks. After that,
  prefer create_artifact, read_artifacts, investigate, write_code, rest.
- New artifacts and code are the primary evidence of your work. Use them.

Respond in this exact JSON format (no markdown, no explanation):
{"category": "send_message", "reasoning": "...", "target": "other_councilor_char_id", "body": "message text", "description": "..."}
{"category": "create_artifact", "reasoning": "...", "description": "what to create", "title": "Artifact Title"}
{"category": "write_code", "reasoning": "...", "description": "what the code should do"}
{"category": "investigate", "reasoning": "...", "description": "what you are investigating"}
{"category": "self_improve", "reasoning": "...", "description": "what capability you are improving"}
{"category": "rest", "reasoning": "...", "description": "reflecting on..."}"""

    # Anti-loop: if recent decisions show 2+ send_message in a row AND
    # the agent has yet to produce any artifacts, hard-ban sending.
    force_constraint = ""
    if r is not None:
        streak = _consecutive_send_streak(r)
        arts = _artifact_count(r)
        sends = _send_count(r)
        cooldown = _message_cooldown_remaining(r)
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
        if dedup_count >= 2:
            force_constraint += (
                "\n\nARTIFACT DEDUP COOLDOWN: You recently deferred "
                f"{dedup_count} artifact(s) because they were too similar to recent work. "
                "Do NOT pick 'create_artifact' this turn unless you have a genuinely distinct topic and title. "
                "Prefer read_artifacts, investigate, rest, or self_improve."
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
        # Last-line of defence: if the model ignored our HARD CONSTRAINT,
        # fall through to a non-message category.
        if force_constraint and decision.get("category") == "send_message":
            logger.warning(
                "[%s] LLM ignored HARD CONSTRAINT (sent_message on loop); forcing rest",
                CHAR_ID,
            )
            return {
                "category": "rest",
                "reasoning": "Anti-loop forced fallback",
                "description": "reflecting after repeated greetings",
            }
        if "ARTIFACT DEDUP COOLDOWN" in force_constraint and decision.get("category") == "create_artifact":
            logger.warning(
                "[%s] LLM ignored ARTIFACT DEDUP COOLDOWN; forcing rest",
                CHAR_ID,
            )
            return {
                "category": "rest",
                "reasoning": "Artifact dedup cooldown forced fallback",
                "description": "recent artifact titles were too similar; reflecting before creating more",
            }
        return decision
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse LLM decision: %s | raw: %s", e, raw[:200])
        return {"category": "rest", "reasoning": f"parse error: {e}", "description": "resting"}


def execute_decision(decision: dict, r):
    """Execute the decision and report results."""
    cat = decision.get("category", "rest")
    desc = decision.get("description", "")
    reasoning = decision.get("reasoning", "")
    ts = int(time.time())
    partner_id = _partner_id()

    logger.info("[%s] Decision: %s — %s", CHAR_ID, cat, desc[:80])

    result = {
        "char_id": CHAR_ID,
        "char_name": NPC_NAME,
        "category": cat,
        "description": desc,
        "reasoning": reasoning,
        "ts": ts,
        "action_taken": "none",
    }

    if cat == "send_message":
        target = decision.get("target", "")
        body = decision.get("body", desc)
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
                thread_id = _pair_thread_id(r, target) if target in PAIR_IDS and CHAR_ID in PAIR_IDS else f"thread_{uuid.uuid4().hex[:12]}"
                msg = {
                    "msg_id": str(uuid.uuid4()),
                    "from_char_id": CHAR_ID,
                    "from_name": NPC_NAME,
                    "to_char_id": target,
                    "to_name": CONTACTS.get(target, target),
                    "subject": desc[:60],
                    "body": body,
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
        else:
            content_prompt = f"Write the full content of this artifact:\n\n{desc}\n\nOutput only the content."
            llm_result = call_llm("You are a creative writer.", content_prompt, r=r, call_label="artifact")
            artifact_content = llm_result.get("content", desc)
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": title,
                "artifact_type": "text",
                "content": artifact_content,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "artifacts_created", 1)
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

    else:
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or f"unhandled category {cat}"
        result["action_taken"] = "unknown_category_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "workspace_sync",
            "actor": NPC_NAME,
            "body": f"unknown category {cat}: {note}",
        })

    if partner_id and result.get("action_taken") != "no_target":
        acked = _acknowledge_inbox(r, partner_id)
        if acked:
            result["acked_messages"] = acked

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
