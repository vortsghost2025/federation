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

from fourth_wall import _enforce_fourth_wall, _fourth_wall_dirty, _startup_scrub_redis
from npc_llm_client import call_llm
from npc_context import (
    neighborhood_snapshot, hash_event, promote_events_to_inbox,
    most_common_topic_word, normalize_topic_label, topic_counter_key,
    topic_cooldown_key, topic_cooldown_remaining, active_topic_cooldowns,
    record_topic_fatigue, text_mentions_topic, decision_mentions_topic,
    collect_topic_sources, new_evidence_for_topic, top_neighborhood_npcs,
    cosmic_horizon, recent_artifact_dedup_count, dedup_blocked_topic,
    think_about_world
)
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
MODEL_EXTRA_BODY = os.environ.get("MODEL_EXTRA_BODY", "")

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
PAIR_MESSAGE_COOLDOWN = int(os.environ.get("PAIR_MESSAGE_COOLDOWN", "180"))
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
        dedup_count = recent_artifact_dedup_count(r)
        dedup_topic = dedup_blocked_topic(r)
        if dedup_count >= 2 and dedup_topic:
            _topic_blocked_for_dedup = dedup_topic
            top_npcs = top_neighborhood_npcs(r, 3)
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
        _active_cooldowns = active_topic_cooldowns(r, CHAR_ID)
        if _active_cooldowns:
            cooldown_text = ", ".join(
                f"{topic} (~{max(1, (ttl + 59) // 60)}m)" for topic, ttl in _active_cooldowns
            )
            force_constraint += (
                "\n\nTOPIC COOLDOWNS ACTIVE: Do NOT continue these topics until cooldown expires: "
                f"{cooldown_text}. Pick a different topic, NPC, or world problem."
            )
        partner_id_tf = _partner_id()
        sources = collect_topic_sources(r, CHAR_ID, 5) if r is not None else []
        if len(sources) >= 3:
            common = most_common_topic_word(sources)
            if common:
                topic_count = sum(1 for s in sources if common.lower() in s.lower())
                logger.info(
                    "[%s] topic_fatigue detected topic=%s count=%d window=%d",
                    CHAR_ID, common, topic_count, len(sources),
                )
                cooldown_remaining = topic_cooldown_remaining(r, common)
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
                        evidence_reason = new_evidence_for_topic(r, common, CHAR_ID, partner_id_tf)
                    if evidence_reason:
                        logger.info(
                            "[%s] topic_fatigue_reset topic=%s reason=%s",
                            CHAR_ID, common, evidence_reason,
                        )
                    else:
                        fatigue_count, started_cooldown = record_topic_fatigue(r, common)
                        _topic_blocked_for_cooldown = common
                        topic_words = " → ".join(
                            most_common_topic_word([s]) if most_common_topic_word([s]) else "?"
                            for s in sources[:5]
                        )
                        logger.info(
                            "[%s] topic_history topics=%s",
                            CHAR_ID, topic_words,
                        )
                        top_npcs = top_neighborhood_npcs(r, 3)
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
            proposed_topic = most_common_topic_word([proposed_title])
            if proposed_topic == _topic_blocked_for_dedup:
                alt_npc = ""
                try:
                    top_npcs_str = top_neighborhood_npcs(r, 1) if r is not None else ""
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
        if _topic_blocked_for_cooldown and decision.get("category") != "send_message" and decision_mentions_topic(decision, _topic_blocked_for_cooldown):
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
                msg_topic = normalize_topic_label(decision.get("topic", "") or desc or body)
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
            dedup_topic = most_common_topic_word([title])
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
