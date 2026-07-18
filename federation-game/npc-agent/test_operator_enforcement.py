"""Focused tests for Patch A: deterministic moderator-reply enforcement.

These tests run in isolation from Redis and the live LLM by monkeypatching
npc_decisions.call_llm and supplying a FakeRedis. They prove that a pending
moderator reply-directive forces a single send_message to "moderator" and
bypasses all ordinary anti-loop / dedup / partner controls, while leaving
ordinary behavior untouched when no qualifying directive exists.
"""
import importlib
import json
import sys
import os

import pytest

# Ensure sibling imports resolve when pytest runs from this dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import npc_decisions as nd


class FakeRedis:
    """Minimal Redis stub. Inbox contents are set per-test via set_inbox()."""

    def __init__(self):
        self._inbox = []

    def set_inbox(self, items):
        self._inbox = items

    def lrange(self, key, start, end):
        if key.endswith(":inbox"):
            return list(self._inbox)
        return []

    def lpush(self, key, value):
        return 0

    def rpush(self, key, value):
        return 0

    def lrem(self, key, count, value):
        return 0

    def ltrim(self, key, start, end):
        return None

    def get(self, key):
        return None

    def set(self, key, value):
        return None

    def hget(self, key, field):
        return None

    def hgetall(self, key):
        return {}

    def hset(self, key, *args, **kwargs):
        return None

    def hincrby(self, key, field, amount):
        return 0

    def zadd(self, key, mapping):
        return None

    def zrange(self, key, start, end, withscores=False):
        return []

    def zremrangebyrank(self, key, start, end):
        return 0

    def zscore(self, key, member):
        return None

    def exists(self, key):
        return 0


def _mod_msg(msg_id, body, subject="Directive"):
    return json.dumps({
        "id": msg_id,
        "msg_id": msg_id,
        "from_char_id": "moderator",
        "from_name": "Sean / Federation Moderator",
        "subject": subject,
        "body": body,
        "created_at": 1000,
    })


# The exact current 723-char follow-up directive (reply-type).
REPLY_BODY = (
    "Stop creating new artifacts for this task. Use the existing Oracle and "
    "Archimedes artifacts as source material and send the completed final "
    "synthesis directly to the Federation Moderator as one send_message response. "
    "The response must contain exactly these five labelled sections: "
    "1. Prioritized Criteria 2. Quantitative Metrics and Suggested Thresholds "
    "3. Sector Comparison Method 4. Risk and Ethical Safeguards "
    "5. Final Recommendation. Do not propose another plan, institution, "
    "investigation, artifact, timeline, or follow-up task. Do not ask for "
    "confirmation. If existing evidence is incomplete, make the strongest "
    "defensible recommendation using the available work and clearly identify "
    "assumptions inside the report."
)
REPLY_SUBJECT = "Completed final deep-signal analytical report"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")
    monkeypatch.setattr(nd, "NPC_NAME", "The Oracle")
    fr = FakeRedis()
    calls = []

    def fake_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
        calls.append((call_label, system_prompt, user_prompt))
        # default: a valid moderator send
        content = json.dumps({
            "category": "send_message",
            "target": "moderator",
            "body": "Here is the completed synthesis.",
            "description": "final report",
            "reasoning": "operator directive",
        })
        return {"content": content, "error": None}

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)
    return fr, calls


def test_no_directive_ordinary_path_unchanged(setup, monkeypatch):
    fr, calls = setup
    fr.set_inbox([])  # no moderator message

    # Mock the exact ordinary-decision LLM output so we can assert it is
    # returned verbatim.
    MOCKED = {
        "category": "investigate",
        "target": "char_001",
        "body": "ordinary body",
        "description": "ordinary description",
        "reasoning": "ordinary",
    }

    def fake_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
        calls.append((call_label, system_prompt, user_prompt))
        if call_label == "decide":
            return {"content": json.dumps(MOCKED), "error": None}
        # any other label must not happen on the ordinary path
        raise AssertionError(f"unexpected LLM call on ordinary path: {call_label}")

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)
    dec = nd.decide_action("ctx", r=fr)

    # ordinary path: no operator_directive_id, call_label is plain "decide"
    assert "operator_directive_id" not in dec
    assert calls and calls[0][0] == "decide"
    # no operator repair call
    assert not any(c[0].startswith("decide_operator") for c in calls)
    # exact mocked output returned, not merely a valid category
    assert dec["category"] == MOCKED["category"]
    assert dec.get("target") == MOCKED["target"]
    assert dec.get("body") == MOCKED["body"]
    assert dec.get("description") == MOCKED["description"]


def test_newest_non_reply_supersedes_older_reply(setup):
    """A newer moderator message that is NOT a reply request must win over an
    older reply-request directive. The stale older command must NOT activate
    enforcement."""
    fr, calls = setup
    older_reply = _mod_msg("old1", "please reply to the moderator with status", "Old reply")
    newer_non_reply = _mod_msg(
        "new1",
        "Cancelling the previous request. Continue your normal work; no reply needed.",
        "Supersede",
    )
    # older first, newer last (inbox is oldest-first)
    fr.set_inbox([older_reply, newer_non_reply])
    dec = nd.decide_action("ctx", r=fr)
    # ordinary path taken (no operator_directive_id)
    assert "operator_directive_id" not in dec
    # only the ordinary "decide" call, no operator label
    labels = [c[0] for c in calls]
    assert labels == ["decide"]
    # the mocked ordinary output would be returned; here we only assert the
    # operator path was not entered
    assert dec["category"] in nd.AGENCY_CATEGORIES


def test_malformed_newest_skipped_for_parseable(setup):
    """Malformed (non-JSON) inbox entries are skipped; the newest PARSEABLE
    moderator message controls behavior. When the newest parseable entry is a
    reply request, enforcement activates even if later entries are malformed."""
    fr, calls = setup
    # newest non-parseable entry must NOT suppress a valid older reply directive
    valid_reply = _mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)
    malformed = "this is not json at all {{{"
    fr.set_inbox([valid_reply, malformed])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    assert dec["operator_directive_id"] == "m1"


def test_reply_wording_activates_enforcement(setup):
    fr, calls = setup
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    assert "operator_directive_id" in dec
    assert dec["operator_directive_id"] == "m1"


def test_valid_moderator_send_passes(setup):
    fr, calls = setup
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    assert dec["body"] == "Here is the completed synthesis."


def test_partner_target_retargeted_to_moderator(setup, monkeypatch):
    fr, calls = setup

    def fake_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
        content = json.dumps({
            "category": "send_message",
            "target": "char_001",  # wrong target
            "body": "reply text",
            "description": "d",
            "reasoning": "r",
        })
        return {"content": content, "error": None}

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"  # deterministically fixed


def test_wrong_category_triggers_repair(setup, monkeypatch):
    fr, calls = setup
    seq = {
        "decide_operator": json.dumps({
            "category": "create_artifact", "title": "x", "description": "ignored"
        }),
        "decide_operator_repair": json.dumps({
            "category": "send_message", "target": "moderator",
            "body": "repaired reply", "description": "d", "reasoning": "r"
        }),
    }

    def fake_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
        calls.append((call_label, system_prompt, user_prompt))
        return {"content": seq.get(call_label, "{}"), "error": None}

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    labels = [c[0] for c in calls]
    assert "decide_operator" in labels
    assert "decide_operator_repair" in labels
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    assert dec["body"] == "repaired reply"


def test_repair_failure_truthful_message(setup, monkeypatch):
    fr, calls = setup

    def fake_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
        if call_label == "decide_operator":
            return {"content": json.dumps({"category": "rest"}), "error": None}
        # repair also invalid
        return {"content": "not json", "error": None}

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    body = dec["body"].lower()
    assert "could not" in body or "failed" in body or "invalid" in body
    # must not be rest / artifact / partner
    assert dec["category"] == "send_message"


def test_ordinary_controls_do_not_override_operator_path(setup, monkeypatch):
    """Send streak, cooldown, dedup, topic cooldown, partner obligation, and
    loop-break are ordinary-path concerns; with a directive present the
    operator path returns BEFORE they are even constructed. Each representative
    helper is monkeypatched to raise so the test fails if any are called."""

    # Representative ordinary-path helpers that must NOT run during an active
    # moderator directive.
    _RAISE = AssertionError("ordinary-path helper must not run during operator directive")

    def boom(*a, **k):
        raise _RAISE

    for helper in (
        "_consecutive_send_streak",
        "_artifact_count",
        "_send_count",
        "_message_cooldown_remaining",
        "recent_artifact_dedup_count",
        "dedup_blocked_topic",
        "active_topic_cooldowns",
        "_open_question_from_partner",
        "collect_topic_sources",
        "record_topic_fatigue",
        "topic_cooldown_remaining",
    ):
        if hasattr(nd, helper):
            monkeypatch.setattr(nd, helper, boom)

    fr, calls = setup
    fr.set_inbox([_mod_msg("m1", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    # only operator call labels, no "decide" (ordinary) call
    labels = [c[0] for c in calls]
    assert labels == ["decide_operator"]
    assert dec["target"] == "moderator"


def test_returned_decision_carries_newest_message_id(setup):
    fr, calls = setup
    # older directive first, newer directive second
    older = _mod_msg("old1", "please reply to the moderator with status", "Old")
    newer = _mod_msg("new1", REPLY_BODY, REPLY_SUBJECT)
    fr.set_inbox([older, newer])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["operator_directive_id"] == "new1"


def test_older_not_selected_when_newer_exists(setup):
    fr, calls = setup
    older = _mod_msg("old1", REPLY_BODY, REPLY_SUBJECT)
    newer = _mod_msg("new1", "another reply request to the moderator please", "Newer")
    fr.set_inbox([older, newer])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["operator_directive_id"] == "new1"


def test_msg_id_only_entry_supported(setup):
    """A moderator inbox entry may carry only 'msg_id' (no top-level 'id').
    The operator_directive_id must fall back to msg_id."""
    fr, calls = setup

    def msg_id_only(msg_id, body, subject="Directive"):
        return json.dumps({
            "msg_id": msg_id,  # no "id" key
            "from_char_id": "moderator",
            "from_name": "Sean / Federation Moderator",
            "subject": subject,
            "body": body,
            "created_at": 1000,
        })

    fr.set_inbox([msg_id_only("m-only", REPLY_BODY, REPLY_SUBJECT)])
    dec = nd.decide_action("ctx", r=fr)
    assert dec["category"] == "send_message"
    assert dec["target"] == "moderator"
    assert dec["operator_directive_id"] == "m-only"
