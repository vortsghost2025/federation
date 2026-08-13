"""Shared decision data structures + varied-phrase helper for the worker NPC loop.

This module is intentionally NOT the home of `make_decision`. The canonical
decision loop lives in `npc_autonomy.make_decision` (which every live caller —
worker tick, npc_simulation, main handlers, routes/npcs — imports from
`npc_autonomy`). This file exists purely to share the data structures and the
anti-repeat phrasing helper so there is ONE source of truth for the varied
decision descriptions, instead of a drifting duplicate.

Keeps only what `npc_autonomy.py` imports:
  - DECISION_DESCRIPTIONS (dict-of-lists; outer decision phrasing pools)
  - ACTION_DESCRIPTION_VARIANTS (dict-of-lists; inner action_desc pools)
  - _pick_varied_phrase, _recent_action_desc (helpers)

DECISION_CATEGORIES is kept here as a shared constant; the canonical
`npc_autonomy.DECISION_CATEGORIES` mirrors it.
"""
import json
import random
from difflib import SequenceMatcher
from typing import Dict, List

DECISION_CATEGORIES = [
    "advance_goal", "socialize", "investigate", "rest",
    "react_to_events", "seek_resources", "self_improve",
    "confront_rival", "help_ally", "explore", "request_capability",
]

# Per-category pools of varied phrasing for the OUTER decision description.
# The previous implementation used a single template string per category, so
# every time an NPC picked the same category the same sentence landed in
# memory verbatim (e.g. "Conquistador Drake decided to explore new territory"
# appearing at the oldest and newest ends of the npc_memory zset). Pools are
# picked from with an anti-repeat check against the NPC's most recent memory
# so the long-term history stops folding onto byte-identical beats.
DECISION_DESCRIPTIONS: Dict[str, List[str]] = {
    "advance_goal": [
        "decided to work toward their goal",
        "turned their attention to a long-running goal",
        "prioritized one of their standing goals",
        "made measurable progress on a goal",
    ],
    "socialize": [
        "decided to seek out conversation",
        "looked around for someone to talk with",
        "sought a brief exchange with a peer",
        "drifted toward a gathering where voices might be heard",
    ],
    "investigate": [
        "decided to look into something suspicious",
        "picked up a thread that didn't quite sit right",
        "decided to scrutinize a recent report more closely",
        "turned a casual observation into an investigation",
    ],
    "rest": [
        "decided to rest and reflect",
        "stepped back for a moment of quiet reflection",
        "paused to let a recent decision settle",
        "took a deliberate beat of rest before the next move",
    ],
    "react_to_events": [
        "decided to respond to recent events",
        "weighed how the latest developments affect them",
        "let a fresh piece of news shape their next move",
        "responded to a shift in the wider federation",
    ],
    "seek_resources": [
        "decided to acquire what they need",
        "set out to secure materials or favors",
        "looked around for what they were running low on",
        "decided to gather a small reserve of resources",
    ],
    "self_improve": [
        "decided to train and improve themselves",
        "carved out time to sharpen a skill",
        "worked on a weak point they'd noticed in themselves",
        "chose practice over idle time",
    ],
    "confront_rival": [
        "decided to confront an adversary",
        "made ready to face a rival",
        "decided it was time to push back against an opponent",
        "approached a long-standing antagonist",
    ],
    "help_ally": [
        "decided to aid a companion",
        "offered a hand to someone they trust",
        "moved to support an ally's effort",
        "checked in on a friend who needed it",
    ],
    "explore": [
        "decided to explore new territory",
        "felt the pull of unmapped space and leaned into it",
        "set out to see what lay past the known edge",
        "chose curiosity over caution for a turn",
        "drifted toward the frontier to see something new",
    ],
    "request_capability": [
        "requested missing capability or context",
        "asked for the context they felt was missing",
        "filed a request for a tool or insight they lacked",
        "named a concrete gap that was holding them back",
    ],
}

# Per-category pools of varied phrasing for the INNER action_desc — the
# concrete description that gets stored along with the action_type and ends
# up in the npc_memory zset. This is the channel where repetition was most
# visible because each category had exactly one hardcoded line.
ACTION_DESCRIPTION_VARIANTS: Dict[str, List[str]] = {
    "investigate": [
        "{name} began investigating a matter of concern",
        "{name} pulled on a thread that didn't seem right",
        "{name} paused to scrutinize a recent report",
        "{name} turned a hunch into an open investigation",
    ],
    "rest": [
        "{name} paused to let the last decision settle",
        "{name} took a deliberate beat of rest",
        "{name} stepped back to breathe before the next move",
        "{name} rested and let the noise recede for a moment",
    ],
    "react_to_events": [
        "{name} reacted to a fresh development",
        "{name} let the latest news shape their next step",
        "{name} weighed how recent events touched them",
        "{name} took a moment to absorb before responding",
    ],
    "seek_resources": [
        "{name} sought out resources and supplies",
        "{name} gathered what they were short on",
        "{name} secured a small reserve for the path ahead",
        "{name} traded a favor for something they needed",
    ],
    "self_improve": [
        "{name} focused on self-improvement and training",
        "{name} sharpened a skill that had been slipping",
        "{name} turned idle time into deliberate practice",
        "{name} worked a weak point until it felt less weak",
    ],
    "explore": [
        "{name} set out to explore uncharted territory",
        "{name} drifted past the familiar edge of the map",
        "{name} chose a direction they hadn't walked in a while",
        "{name} stepped into unmapped space without much fanfare",
        "{name} took a longer route just to see something new",
    ],
}


def _recent_action_desc(r, char_id):
    """Read the most recent action_desc recorded in npc_memory for this NPC.

    Returns an empty string if memory is empty or unreadable. Used by
    _pick_varied_phrase to pick the next phrase so it doesn't repeat.
    """
    try:
        key = f"npc_memory:{char_id}"
        recent = r.zrevrange(key, 0, 0, withscores=False)
        if not recent:
            return ""
        raw = recent[0]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        entry = json.loads(raw)
        return str(entry.get("action_desc") or entry.get("content") or "")
    except Exception:
        return ""


def _pick_varied_phrase(r, char_id, category, phrases, max_similarity=0.85):
    """Pick a phrase from `phrases` that differs from the NPC's most recent one.

    Falls back to a random pick when there is no recent memory, when all
    phrases look similar (short pools), or when the read fails — never blocks
    the decision path.
    """
    try:
        if not phrases:
            return "made a decision"
        if len(phrases) == 1:
            return phrases[0]
        recent = _recent_action_desc(r, char_id)
        if not recent:
            return random.choice(phrases)
        # Score each candidate by similarity to the recent phrase; pick the
        # least-similar one, breaking ties at random so the pool doesn't drift
        # toward a single deterministic order over time.
        scored = []
        for p in phrases:
            sim = SequenceMatcher(None, recent.lower(), p.lower()).ratio()
            scored.append((sim, p))
        min_sim = min(s for s, _ in scored)
        low = [p for s, p in scored if s <= min_sim + 0.02]
        return random.choice(low) if low else random.choice(phrases)
    except Exception:
        return random.choice(phrases) if phrases else "made a decision"
