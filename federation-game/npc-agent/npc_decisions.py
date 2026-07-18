"""
NPC Decisions — decision-making logic extracted from npc_agent.py.

Contains:
- SELF_INTRO system prompt (councilor role + world description)
- decide_action() — main LLM decision function with anti-loop guards
- Helper functions: _consecutive_send_streak, _artifact_count,
  _send_count, _is_repetitive_artifact, _acknowledge_inbox
"""
import json
import logging
import os
import re
import time

from fourth_wall import _enforce_fourth_wall, _fourth_wall_dirty
from npc_llm_client import call_llm
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
    _matched_loop_topic,
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
from npc_context import (
    neighborhood_snapshot, hash_event, promote_events_to_inbox,
    most_common_topic_word, normalize_topic_label, topic_counter_key,
    topic_cooldown_key, topic_cooldown_remaining, active_topic_cooldowns,
    record_topic_fatigue, text_mentions_topic, decision_mentions_topic,
    collect_topic_sources, new_evidence_for_topic, top_neighborhood_npcs,
    cosmic_horizon, recent_artifact_dedup_count, dedup_blocked_topic,
    think_about_world
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("npc_decisions")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
OPERATOR_ID = "moderator"
OPERATOR_NAME = "Sean / Federation Moderator"
SESSION_CAP = int(os.environ.get("SESSION_CAP", "24"))
PAIR_MESSAGE_COOLDOWN = int(os.environ.get("PAIR_MESSAGE_COOLDOWN", "180"))

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


def _extract_json(text: str):
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 0:
                continue
            candidate = part
            if candidate.startswith("json"):
                candidate = candidate[4:]
            candidate = candidate.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    brace_start = text.find("{")
    if brace_start == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    for end in range(len(text) - 1, brace_start, -1):
        if text[end] == "}":
            candidate = text[brace_start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("no valid JSON object found", text, brace_start)


def _newest_moderator_directive(r, char_id: str = "") -> dict | None:
    """Return the newest parseable moderator message in the cognition inbox.

    The inbox is stored oldest-first, so the LAST parseable moderator
    message in the list is the newest. We first isolate the newest moderator
    message, then decide whether it is a reply-type directive. This means a
    newer non-reply moderator instruction is always seen in preference to an
    older reply request: we never enforce a stale older command while a newer
    moderator message exists.

    A "reply-type" directive is one whose body explicitly requests a reply /
    send_message to the moderator — the only directives the operator-priority
    path can enforce deterministically.

    Returns a dict with keys: id, from_char_id, from_name, subject, body,
    or None when no qualifying directive is present.
    """
    cid = char_id or CHAR_ID
    if r is None:
        return None

    msgs: list[tuple[dict, str]] = []

    # Primary schema (branch/legacy): inbox stored as a LIST of JSON strings.
    try:
        for raw in r.lrange(f"npc_messages:{cid}:inbox", 0, -1):
            try:
                m = json.loads(raw)
            except Exception:
                # malformed entries are skipped; newest parseable wins
                continue
            msgs.append((m, raw))
    except Exception:
        pass

    # Production schema: inbox is a ZSET of msg_ids at `msg:inbox:{cid}`,
    # with full message bodies stored as HASH objects at `msg:{msg_id}`.
    # zrevrange returns newest-first; reverse to oldest-first so the shared
    # "last moderator message wins" selection below yields the NEWEST.
    if not msgs:
        try:
            msg_ids = r.zrevrange(f"msg:inbox:{cid}", 0, -1)
            for mid in reversed(msg_ids):
                try:
                    h = r.hgetall(f"msg:{mid}")
                except Exception:
                    continue
                if not h:
                    continue
                msgs.append((dict(h), mid))
        except Exception:
            pass

    newest_moderator = None
    for m, raw_id in msgs:
        if m.get("from_char_id") != OPERATOR_ID:
            continue
        # keep overwriting -> newest parseable moderator message wins
        newest_moderator = {
            "id": m.get("id") or m.get("msg_id") or raw_id,
            "from_char_id": m.get("from_char_id", OPERATOR_ID),
            "from_name": m.get("from_name", OPERATOR_NAME),
            "subject": m.get("subject", ""),
            "body": m.get("body", ""),
        }
    if newest_moderator is None:
        return None
    body = (newest_moderator.get("body") or "").lower()
    is_reply_request = (
        "moderator" in body
        and (
            "send_message" in body
            or "reply" in body
            or "send the" in body
            or "send a" in body
        )
    )
    if not is_reply_request:
        # newest moderator message is not a reply request -> do not enforce
        return None
    return newest_moderator


def _norm_body(s: str) -> str:
    import re
    return re.sub(r"[\s\-_]+", " ", (s or "").strip().lower())


def _extract_required_labels(directive_body: str) -> list[str]:
    """Extract labelled/numbered section requirements from a directive body.

    Supports both:
      * one label per line (e.g. "1. Prioritized Criteria");
      * multiple numbered labels inside one paragraph.

    Comparison is normalized: case, whitespace, numbering, punctuation,
    and hyphen/underscore variants are collapsed so the moderator's wording
    (e.g. "Suggested Thresholds" vs "Suggest ed Thresholds") still matches.
    """
    if not directive_body:
        return []
    import re
    norm = lambda s: re.sub(r"[\s\-_]+", " ", s.strip().lower())
    # candidate label lines: leading "N." / "N)" or a numbered/lettered token
    labels: list[str] = []
    inline_pat = re.compile(r"(?:\d+[.)])\s*([A-Z][A-Za-z][^0-9(.)]{2,60}?)(?=(?:\s*\d+[.)])|\.\s+[A-Z]|\.?\s*\Z)")
    for raw_line in directive_body.splitlines():
        line = raw_line.strip()
        # Paragraph with inline numbered labels: "1) Foo 2) Bar 3) Baz"
        # Prefer this so a single line holding all five labels is not swallowed
        # whole by the line-level fallback below.
        inline = list(inline_pat.finditer(line))
        if inline:
            for mm in inline:
                captured = mm.group(1).rstrip(". ").strip()
                labels.append(norm(captured))
            continue
        m = re.match(r"^\s*(?:\d+[.)]|[a-z][.)])\s*(.+)$", line)
        if m:
            labels.append(norm(m.group(1)))
    # de-dup preserving order
    seen = set()
    out = []
    for l in labels:
        if l and l not in seen:
            seen.add(l)
            out.append(l)
    return out


def _body_satisfies_labels(body: str, labels: list[str]) -> bool:
    if not labels:
        return True
    norm = lambda s: re.sub(r"[\s\-_]+", " ", s.strip().lower())
    nb = norm(body or "")
    if not nb:
        return False
    return all(lbl in nb for lbl in labels)


def _decide_operator_response(directive: dict, context: str, r=None) -> dict:
    """Deterministic operator-reply path.

    Forces a single send_message to the moderator, bypassing all ordinary
    anti-loop / dedup / partner controls. Validates the returned decision
    and applies a constrained repair if it is invalid. Returns the decision
    dict with operator_directive_id metadata attached.
    """
    subject = directive.get("subject", "")
    body = directive.get("body", "")
    required_labels = _extract_required_labels(body)
    constraint = (
        "\n\nBINDING OPERATOR DIRECTIVE — COMPLETE THIS TURN.\n"
        "The Federation Moderator has issued a directive that explicitly "
        "requests a reply (send_message) to the moderator. Completing it is "
        "mandatory this turn. The ONLY valid action is:\n"
        '  {"category": "send_message", "target": "moderator", '
        '"body": "<your full reply to the moderator>", '
        '"description": "<short summary>", "reasoning": "<why>"}\n'
        "Rules for this turn only:\n"
        "- target MUST be exactly \"moderator\".\n"
        "- category MUST be exactly \"send_message\".\n"
        "- partner messages, create_artifact, create_institution, "
        "propose_role, submit_to_institution, investigate, read_artifacts, "
        "rest, self_improve, write_code, request_capability are ALL invalid.\n"
        "- Do not ask a question; deliver the requested response.\n"
        "- A claim that the report is \"complete\" WITHOUT the actual labelled "
        "sections below is INVALID. You must include the real content.\n"
    )
    if required_labels:
        constraint += "- Your reply body MUST contain every one of these labelled sections:\n"
        for i, lbl in enumerate(required_labels, 1):
            constraint += f"    {i}. {lbl}\n"
    constraint += (
        "Direct your reply to the moderator as follows.\n"
        f"DIRECTIVE SUBJECT: {subject}\n"
        f"DIRECTIVE BODY:\n{body}\n"
        "END DIRECTIVE. Respond now with the required send_message JSON only."
    )
    system_prompt = SELF_INTRO + constraint
    from npc_llm_client import DECISION_MODEL
    raw = call_llm(system_prompt, context, model=DECISION_MODEL or "", r=r, call_label="decide_operator")

    def _valid(dec):
        if not isinstance(dec, dict):
            return None
        if dec.get("category") != "send_message":
            return None
        if (dec.get("target") or "") != OPERATOR_ID:
            # retarget deterministically instead of discarding
            dec["target"] = OPERATOR_ID
        body_out = dec.get("body") or dec.get("description") or ""
        if not body_out.strip():
            return None
        # content-contract: when the directive required labelled sections,
        # the body must actually contain them. A meta-acknowledgement that
        # merely claims completion is INVALID.
        if required_labels and not _body_satisfies_labels(body_out, required_labels):
            return None
        return dec

    decision = None
    try:
        decision = _extract_json(raw["content"])
    except Exception:
        decision = None

    missing = []
    if _valid(decision) is None:
        # constrained repair call — name the missing labels explicitly
        if required_labels:
            body_for_check = (decision or {}).get("body") or (decision or {}).get("description") or ""
            missing = [l for l in required_labels if l not in _norm_body(body_for_check)]
        repair_system = (
            SELF_INTRO
            + "\n\nYou previously failed to produce the required moderator reply"
        )
        if required_labels:
            repair_system += (
                " — the following labelled sections were MISSING from your reply:\n"
            )
            for i, lbl in enumerate(missing, 1):
                repair_system += f"    {i}. {lbl}\n"
            repair_system += (
                "A message that only claims completion WITHOUT these actual sections "
                "is INVALID. Include the real content for each section.\n"
            )
        else:
            repair_system += " — return a valid non-empty reply.\n"
        repair_system += (
            'Return ONLY this JSON, filled in:\n'
            '{"category": "send_message", "target": "moderator", '
            '"body": "<your full reply to the moderator with every required section>", '
            '"description": "<short summary>", "reasoning": "<why>"}\n'
            "The target MUST be \"moderator\". The body MUST be non-empty"
        )
        if required_labels:
            repair_system += " and MUST contain every listed section."
        repair_raw = call_llm(
            repair_system, context, model=DECISION_MODEL or "", r=r, call_label="decide_operator_repair"
        )
        try:
            decision = _extract_json(repair_raw["content"])
        except Exception:
            decision = None

    # terminal status metadata
    if _valid(decision) is not None:
        operator_response_status = "complete"
        operator_missing = []
    else:
        operator_response_status = "failed"
        if required_labels:
            body_for_check = (decision or {}).get("body") or (decision or {}).get("description") or ""
            operator_missing = [l for l in required_labels if l not in _norm_body(body_for_check)]
        else:
            operator_missing = []
        # truthful fallback: never silently pick rest/artifact/partner
        decision = {
            "category": "send_message",
            "target": OPERATOR_ID,
            "body": (
                "Moderator, I received your directive but could not produce the "
                "requested response: the decision output was invalid and a repair "
                "attempt also failed. No artifact or partner action was taken in "
                "its place. Please reissue or clarify the directive."
            ),
            "description": "operator reply failed validation; reporting inability truthfully",
            "reasoning": "decision and repair both returned invalid output",
        }

    decision["operator_directive_id"] = directive.get("id") or directive.get("msg_id")
    decision["operator_response_status"] = operator_response_status
    decision["operator_missing_requirements"] = operator_missing
    return decision


def decide_action(context: str, r=None) -> dict:
    """Ask the LLM what to do next.

    Anti-loop logic: if the agent has done send_message the last 2 ticks
    AND has produced zero artifacts, we append a hard constraint to the
    system prompt forbidding a third message. This breaks the greeting
    spiral without needing parser tricks.
    """
    # Operator-priority enforcement (Patch A): when a moderator directive
    # explicitly requests a reply, complete it this turn and bypass all
    # ordinary anti-loop / dedup / partner controls. Lifecycle/acknowledgement
    # is intentionally left to a later, separate patch.
    _directive = _newest_moderator_directive(r)
    if _directive is not None:
        logger.info("[%s] operator directive active; entering binding reply path", CHAR_ID)
        return _decide_operator_response(_directive, context, r)

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
                    # Block partner_artifact fatigue reset for resolved or known
                    # loop topics once the recent topic window is already high.
                    if evidence_reason and "partner_artifact" in evidence_reason:
                        _cps = _pair_state(r, partner_id, CHAR_ID) if r else {}
                        _conv_raw = _cps.get("convergence_state", "") if _cps else ""
                        try:
                            _conv = json.loads(_conv_raw) if _conv_raw else {}
                        except Exception:
                            _conv = {}
                        _blocked_terms = _conv.get("blocked_topic_terms", []) if _conv else []
                        _resolved = bool(_conv.get("resolved", False)) if _conv else False
                        _conv_topic = _matched_loop_topic(" ".join([
                            _conv.get("disagreement", "") if _conv else "",
                            _conv.get("current_best_answer", "") if _conv else "",
                            _conv.get("agreement", "") if _conv else "",
                            _conv.get("next_question", "") if _conv else "",
                        ]))
                        _common_topic = _matched_loop_topic(common)
                        _blocked_match = _blocked_terms and any(
                            common == term or common in term or term in common
                            for term in _blocked_terms
                        )
                        _resolved_match = _resolved and _common_topic and _common_topic == _conv_topic
                        _loop_match = topic_count >= 3 and _common_topic and (
                            not _conv_topic or _common_topic == _conv_topic
                        )
                        if _blocked_match or _resolved_match or _loop_match:
                            evidence_reason = ""
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
                                "Do not pick create_artifact or investigate on this topic."
                            )
        partner_q = _open_question_from_partner(r, partner_id) if r is not None else None
        if partner_q:
            question_text = partner_q.get("question", "your open question")
            partner_name = partner_q.get("from_name", partner_id)
            force_constraint += (
                "\n\nPARTNER ANSWER OBLIGATION: Your partner "
                f"{partner_name} asked: \"{question_text}\". "
                "You should answer or address it this turn if you have "
                "not already. Prefer send_message with a direct answer, "
                "or investigate first then send_message."
            )
        existing_outgoing = ""
        if r is not None:
            _ps = _pair_state(r, partner_id, CHAR_ID)
            _last_q = _ps.get("last_open_question_sent_to_partner", "") if _ps else ""
            _last_q_ts = 0
            try:
                _last_q_ts = int(_ps.get("last_open_question_ts", 0) or 0) if _ps else 0
            except Exception:
                pass
            if _last_q and _last_q_ts and not _partner_answered_open_question(r, partner_id, _last_q_ts, CHAR_ID):
                existing_outgoing = _last_q
            if existing_outgoing:
                outgoing_question = existing_outgoing
                force_constraint += (
                    "\n\nOPEN QUESTION GUARD: You already have an open question "
                    f"outstanding (\"{existing_outgoing[:80]}\"). Do NOT send another "
                    "open question until this one is answered or superseded by new evidence. "
                    "Pick investigate, read_artifacts, or a different action."
                )
        if r is not None:
            _ps2 = _pair_state(r, partner_id, CHAR_ID) if r is not None else {}
            state_q = _state_question_from_partner(_ps2, partner_id)
            _since_ts = 0
            try:
                _since_ts = int(_ps2.get("last_open_question_ts", 0) or 0) if _ps2 else 0
            except Exception:
                pass
            if state_q and _has_work_after_open_question(r, partner_id, _since_ts, CHAR_ID):
                pass
            elif state_q and not _has_work_after_open_question(r, partner_id, _since_ts, CHAR_ID):
                force_constraint += (
                    "\n\nPARTNER STATE-QUESTION: Your partner asked a state question. "
                    "If you have already produced work (artifacts, code) since they asked, "
                    "you can ignore this. Otherwise, answer with send_message."
                )
        if r is not None:
            _cs = _pair_state(r, partner_id, CHAR_ID).get("convergence_state", "")
            _cc = None
            if _cs and isinstance(_cs, str):
                try:
                    _cc = json.loads(_cs)
                except Exception:
                    pass
            if _cc:
                _nq = _cc.get("next_question", "")
                _ans = _cc.get("current_best_answer", "")
                _dis = _cc.get("disagreement", "")
                _resolved = _cc.get("resolved", False)
                _blocked = _cc.get("blocked_topic_terms", [])

                if _resolved and _nq:
                    force_constraint += (
                        "\n\nRESOLUTION PRESSURE: The current question has been resolved. "
                        "You must advance beyond the resolved answer with a NEW downstream question. "
                        f"Resolved answer: \"{_ans[:100]}\""
                        f" Blocked topics: {', '.join(_blocked[:2]) if _blocked else 'none'}"
                    )
                else:
                    force_constraint += (
                        "\n\nPAIR CONVERGENCE STATE: You and your partner have established "
                        "a shared understanding. Revise from this convergence state, "
                        "do not restart from the original question."
                    )
                    if _nq:
                        force_constraint += (
                            f"\n  The open convergence question is: \"{_nq[:150]}\""
                        )
                    if _ans:
                        force_constraint += (
                            f"\n  Current best answer: \"{_ans[:150]}\""
                        )
                    if _dis:
                        force_constraint += (
                            f"\n  Remaining disagreement: \"{_dis[:150]}\""
                        )
                    force_constraint += (
                        "\n  Your task is to refine or challenge the current convergence "
                        "state using your partner's latest evidence."
                        "\n  Do not repeat the same investigation unless the convergence "
                        "state says evidence is missing."
                    )
        if r is not None:
            shapes = _recent_decision_shapes(r, 5)
            streak_len = _newest_first_streak(shapes)
            if streak_len >= 4:
                force_constraint += (
                    f"\n\nLOOP-BREAK: You have done '{shapes[0]}' {streak_len} times in a row. "
                    "You MUST NOT pick that category this turn. Pick something else."
                )
            elif streak_len >= 3:
                force_constraint += (
                    f"\n\nLOOP-BREAK (runtime): You have done '{shapes[0]}' 3 times in a row. "
                    "Strongly consider a different category this turn."
                )
    system_prompt = base_system + force_constraint

    from npc_llm_client import DECISION_MODEL
    raw = call_llm(system_prompt, context, model=DECISION_MODEL or "", r=r, call_label="decide")

    try:
        decision = _extract_json(raw["content"])
        cat = decision.get("category", "rest")
        if cat not in AGENCY_CATEGORIES:
            logger.warning("[%s] Unknown category '%s'; defaulting to rest", CHAR_ID, cat)
            decision = {"category": "rest", "reasoning": f"unknown category {cat}", "description": "resting after unknown action"}
        decision["description"] = _enforce_fourth_wall(decision.get("description", ""))
        decision["reasoning"] = _enforce_fourth_wall(decision.get("reasoning", ""))
        for key in ("body", "title", "mandate"):
            if key in decision:
                decision[key] = _enforce_fourth_wall(decision[key])
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
        logger.warning("Failed to parse LLM decision: %s | raw: %s", e, str(raw)[:200])
        return {"category": "rest", "reasoning": f"parse error: {e}", "description": "resting"}
