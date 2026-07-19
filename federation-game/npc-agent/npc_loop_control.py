"""Deterministic NPC topic-loop control (bounded, shadow-safe).

This module adds a *deterministic* post-decision enforcement layer on top of
the existing artifact-dedup gate in ``npc_actions.py`` (``_is_repetitive_artifact``)
and the prompt-level anti-loop constraints inside ``decide_action``.

It does NOT weaken or replace those systems. The existing dedup gate remains the
primary safety layer ("prohibit another artifact on that topic"). This layer
guarantees enforcement even when the language model ignores the injected prompt
constraints, by rewriting the returned decision object before it reaches
``execute_decision``.

Design constraints (per directive):
  * Per-NPC state only; never store private message or artifact bodies.
  * Only normalized topic words (most_common_topic_word) and the decision
    category are persisted for loop tracking.
  * All Redis keys live under the dedicated ``npc_loopctrl:*`` namespace and
    carry bounded TTLs so state cannot accumulate forever.
  * Streak resets only after *genuinely different* completed work, not a
    reworded title of the same normalized topic.
  * Behavior is deterministic: identical sanitized state yields identical
    enforcement outputs.

Thresholds:
  * 2 consecutive same-topic artifact deferrals ->
        prohibit create_artifact on that topic for the current decision.
  * 3 consecutive same-topic artifact deferrals ->
        prohibit ALL create_artifact decisions; force investigate /
        read_artifacts / rest.
  * 4 repeated equivalent decision shapes ->
        force rest, or investigation of a deterministically selected
        different world topic.
"""

from __future__ import annotations

import json
import time

# Maximum number of normalized decision shapes we keep per NPC. Bounded to
# avoid unbounded growth. TTL on the list key also bounds total lifetime.
MAX_SHAPE_HISTORY = 8
SHAPE_LIST_TTL = 1800          # 30 minutes
DEFER_STREAK_TTL = 600         # 10 minutes (matches dedup streak TTL)
SHAPE_REPEAT_HARD_BREAK = 4    # repeated equivalent shapes -> forced break
DEFER_FORCE_ALTERNATIVE = 3    # deferrals -> force non-artifact action

# Deterministic rotation of "different world topics" used when a hard break
# forces investigation of something other than the trapped topic.
DIVERSE_TOPICS = [
    "local infrastructure resilience",
    "neighborhood trade disputes",
    "outer-rim navigation hazards",
    "cultural exchange programs",
    "resource allocation fairness",
    "signal-interpretation methodology",
    "archive preservation policy",
    "cross-faction mediation",
]


def _defer_key(char_id: str) -> str:
    return f"npc_loopctrl:defer:{char_id}"


def _topic_key(char_id: str) -> str:
    return f"npc_loopctrl:topic:{char_id}"


def _shape_key(char_id: str) -> str:
    return f"npc_loopctrl:shapes:{char_id}"


def _clock() -> int:
    """Wrapping point for time. Injected-indirectly; kept simple for tests."""
    return int(time.time())


def _safe_get(r, key: str):
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return raw


def _safe_set(r, key: str, value: str, ttl: int) -> None:
    if r is None:
        return
    try:
        r.set(key, value, ex=ttl)
    except Exception:
        pass


def _safe_incr(r, key: str, ttl: int) -> int:
    if r is None:
        return 0
    try:
        val = r.incr(key)
        try:
            r.expire(key, ttl)
        except Exception:
            pass
        return int(val)
    except Exception:
        return 0


def _safe_delete(r, key: str) -> None:
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        pass


def _safe_list(r, key: str) -> list[str]:
    if r is None:
        return []
    try:
        raw = r.lrange(key, 0, -1)
    except Exception:
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, bytes):
            try:
                item = item.decode("utf-8", errors="replace")
            except Exception:
                continue
        if item:
            out.append(str(item))
    return out


def _safe_push(r, key: str, value: str, cap: int, ttl: int) -> None:
    if r is None:
        return
    try:
        r.rpush(key, value)
        r.ltrim(key, -cap, -1)
        r.expire(key, ttl)
    except Exception:
        pass


def _normalize_topic(text: str) -> str:
    """Normalize a topic to its most-common word, lowercased, no private text."""
    from npc_context import most_common_topic_word
    word = most_common_topic_word([text or ""]) if text else ""
    return (word or "").strip().lower()


def _decision_shape(category: str, topic: str) -> str:
    """A sanitized, content-free shape signature of a decision."""
    cat = (category or "").strip().lower()
    topic = _normalize_topic(topic)
    return json.dumps({"c": cat, "t": topic}, sort_keys=True)


def record_deferral(r, char_id: str, topic: str) -> int:
    """Record one consecutive same-topic artifact deferral.

    Returns the new deferral streak count. Called from the existing dedup
    branch in ``npc_actions.execute_decision`` *alongside* the unchanged
    ``_is_repetitive_artifact`` gate (this never replaces it).
    """
    count = _safe_incr(r, _defer_key(char_id), DEFER_STREAK_TTL)
    _safe_set(r, _topic_key(char_id), _normalize_topic(topic), DEFER_STREAK_TTL)
    return int(count)


def record_decision_shape(r, char_id: str, category: str, topic: str) -> int:
    """Record the normalized shape of a returned decision.

    Returns the count of *consecutive* identical shapes (including this one).
    TTL-bounded; list capped at MAX_SHAPE_HISTORY.
    """
    shape = _decision_shape(category, topic)
    key = _shape_key(char_id)
    history = _safe_list(r, key)
    # Count trailing consecutive identical shapes.
    repeat = 0
    for prev in reversed(history):
        if prev == shape:
            repeat += 1
        else:
            break
    repeat += 1
    _safe_push(r, key, shape, MAX_SHAPE_HISTORY, SHAPE_LIST_TTL)
    return int(repeat)


def record_completed_work(r, char_id: str, category: str, topic: str) -> None:
    """Reset loop-control state ONLY after genuinely different completed work.

    "Genuinely different" means the completed work's normalized topic differs
    from the deferred topic OR its category is not create_artifact. A reworded
    title of the same normalized topic does NOT reset the streak.
    """
    done_topic = _normalize_topic(topic)
    done_cat = (category or "").strip().lower()
    blocked_topic = (_safe_get(r, _topic_key(char_id)) or "").strip().lower()

    genuinely_different = (
        done_cat != "create_artifact"
        or (blocked_topic and done_topic and done_topic != blocked_topic)
    )
    if genuinely_different:
        _safe_delete(r, _defer_key(char_id))
        _safe_delete(r, _topic_key(char_id))
        # Clear shape history so a fresh pattern can begin.
        _safe_delete(r, _shape_key(char_id))


def _diverse_topic(char_id: str, exclude: str) -> str:
    """Deterministically pick a different world topic than the trapped one."""
    excl = (exclude or "").strip().lower()
    for i in range(len(DIVERSE_TOPICS)):
        cand = DIVERSE_TOPICS[(hash(char_id) % len(DIVERSE_TOPICS) + i) % len(DIVERSE_TOPICS)]
        if (cand.split(" ", 1)[0] if cand else "") != excl:
            return cand
    return DIVERSE_TOPICS[0]


def enforce(decision: dict, r, char_id: str) -> dict:
    """Deterministically enforce loop-control on a returned decision.

    ``decision`` is the parsed decision dict from the model. This function may
    rewrite it to a safe alternative. It never throws; on any internal error it
    returns the decision unchanged so the caller's existing path proceeds.

    Returns the (possibly rewritten) decision.
    """
    if not isinstance(decision, dict):
        return decision
    category = (decision.get("category") or "").strip().lower()
    topic = _normalize_topic(
        decision.get("title") or decision.get("description") or ""
    )
    blocked_topic = (_safe_get(r, _topic_key(char_id)) or "").strip().lower()
    defer_streak = 0
    try:
        raw = _safe_get(r, _defer_key(char_id))
        defer_streak = int(raw) if raw is not None else 0
    except Exception:
        defer_streak = 0

    # Threshold 2 (and above): same-topic artifact prohibited this decision.
    if category == "create_artifact" and topic and topic == blocked_topic and defer_streak >= 2:
        return _force_alternative(char_id, decision, reason="defer>=2 same topic")

    # Threshold 3: all create_artifact prohibited; force non-artifact action.
    if category == "create_artifact" and defer_streak >= DEFER_FORCE_ALTERNATIVE:
        return _force_alternative(char_id, decision, reason="defer>=3 all artifacts")

    # Threshold 4: repeated equivalent decision shapes -> hard break.
    shape_repeat = record_decision_shape(r, char_id, category, topic)
    if shape_repeat >= SHAPE_REPEAT_HARD_BREAK:
        return _force_rest_or_investigate(char_id, decision, blocked_topic,
                                          reason=f"shape_repeat={shape_repeat}")

    return decision


def _force_alternative(char_id: str, decision: dict, reason: str) -> dict:
    """Rewrite a create_artifact decision to a safe non-artifact alternative."""
    alt = {
        "category": "read_artifacts",
        "reasoning": (
            "Loop-control override: repeated artifact deferrals on this topic; "
            f"reading partner work instead ({reason})."
        ),
        "description": (
            "Reading artifacts after loop-control blocked further artifact "
            "creation on the repeated topic."
        ),
    }
    import logging
    logging.getLogger("npc_loop_control").info(
        "[%s] loopctl_forced_alternative reason=%s", char_id, reason
    )
    return alt


def _force_rest_or_investigate(char_id: str, decision: dict,
                               blocked_topic: str, reason: str) -> dict:
    """Force a hard break: rest, or investigate a deterministically different topic."""
    import logging
    log = logging.getLogger("npc_loop_control")
    # Deterministic choice: prefer investigate a different topic, else rest.
    diverse = _diverse_topic(char_id, blocked_topic)
    log.info(
        "[%s] loopctl_hard_break reason=%s diverse_topic=%s", char_id, reason, diverse
    )
    return {
        "category": "investigate",
        "reasoning": (
            "Loop-control hard break: equivalent decision shape repeated too "
            f"many times ({reason}). Investigating a different world topic."
        ),
        "description": f"Investigating: {diverse}",
    }
