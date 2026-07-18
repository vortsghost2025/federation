"""Focused tests for Patch B: message-specific operator directive acknowledgement.

These tests run in isolation from Redis and the live LLM. They prove that an
enforced operator response acknowledges exactly one directive by its message id
(exact-ID removal from the production ZSET or legacy LIST) without triggering the
generic sender-wide moderator acknowledgement, and that unrelated inbox members
and the underlying msg:{id} payload are preserved.

They also verify the bounded operator_ack:{cid} audit record and that ordinary
partner / non-enforced moderator traffic keeps its existing acknowledgement path.
"""
import importlib
import json
import sys
import os

import pytest

# Ensure sibling imports resolve when pytest runs from this dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import npc_decisions as nd
import npc_redis_helpers as rh

class FakeRedis:
    """Minimal Redis stub.

    Supports two inbox schemas:
      * legacy LIST at `npc_messages:{cid}:inbox` (set via set_inbox);
      * production ZSET at `msg:inbox:{cid}` of msg_ids + HASH at `msg:{msg_id}`
        (set via set_zset_inbox).
    """

    def __init__(self):
        self._inbox = []
        self._zset_inbox = []          # ordered newest-first list of msg_ids
        self._zset_scores = {}         # msg_id -> score (created_at)
        self._hashes = {}              # msg_id -> dict
        self._strings = {}             # simple SET/HASH-less key -> string store

    def set_inbox(self, items):
        self._inbox = items

    def set_zset_inbox(self, hashes):
        # hashes: list of dict message bodies, newest-first
        self._hashes = {h["id"]: dict(h) for h in hashes}
        self._zset_inbox = [h["id"] for h in hashes]
        self._zset_scores = {h["id"]: h.get("created_at", 0) for h in hashes}

    def lrange(self, key, start, end):
        if key.endswith(":inbox"):
            return list(self._inbox)
        return []

    def lpush(self, key, value):
        return 0

    def rpush(self, key, value):
        return 0

    def lrem(self, key, count, value):
        before = len(self._inbox)
        self._inbox = [x for x in self._inbox if x != value]
        return before - len(self._inbox)

    def ltrim(self, key, start, end):
        return None

    def get(self, key):
        return self._strings.get(key)

    def set(self, key, value):
        self._strings[key] = value
        return True

    def hget(self, key, field):
        return None

    def hgetall(self, key):
        # key like "msg:{msg_id}"
        if key.startswith("msg:") and key[4:] in self._hashes:
            return dict(self._hashes[key[4:]])
        return {}

    def hset(self, key, *args, **kwargs):
        return None

    def hincrby(self, key, field, amount):
        return 0

    def zadd(self, key, mapping):
        return None

    def zrange(self, key, start, end, withscores=False):
        return []

    def zrevrange(self, key, start, end):
        if key.startswith("msg:inbox:"):
            return list(self._zset_inbox)
        return []

    def zremrangebyrank(self, key, start, end):
        return 0

    def zscore(self, key, member):
        return None

    def exists(self, key):
        if key.startswith("msg:inbox:"):
            return 1 if self._zset_inbox else 0
        # legacy LIST key
        if key.endswith(":inbox"):
            return 1 if self._inbox else 0
        return 0

    def zrem(self, key, *members):
        removed = 0
        for m in members:
            if m in self._zset_inbox:
                self._zset_inbox.remove(m)
                removed += 1
        return removed


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
        # default: a valid moderator send whose body satisfies the 5 required
        # labelled sections extracted from REPLY_BODY.
        content = json.dumps({
            "category": "send_message",
            "target": "moderator",
            "body": (
                "1. Prioritized Criteria: signal depth over volume. "
                "2. Quantitative Metrics and Suggested Thresholds: score > 0.7. "
                "3. Sector Comparison Method: rank normalized deltas. "
                "4. Risk and Ethical Safeguards: anonymize sources. "
                "5. Final Recommendation: adopt the deep-signal rubric."
            ),
            "description": "final report",
            "reasoning": "operator directive",
        })
        return {"content": content, "error": None}

    monkeypatch.setattr(nd, "call_llm", fake_call_llm)


# ────────────────────────────────────────────────────────────────────────────
# Patch B: message-specific acknowledgement by directive id.
# ────────────────────────────────────────────────────────────────────────────

def test_ack_removes_only_matching_zset_member():
    fr = FakeRedis()
    hashes = [
        {"id": "msg_a", "from_char_id": "moderator", "subject": "A",
         "body": "reply please", "created_at": 3},
        {"id": "msg_b", "from_char_id": "moderator", "subject": "B",
         "body": "another reply", "created_at": 2},
        {"id": "msg_c", "from_char_id": "moderator", "subject": "C",
         "body": "third", "created_at": 1},
    ]
    fr.set_zset_inbox(hashes)
    ok = rh._acknowledge_operator_directive(fr, "msg_b", "char_306", "complete")
    assert ok is True
    assert fr._zset_inbox == ["msg_a", "msg_c"]


def test_ack_removes_only_one_of_four_unrelated_remain():
    fr = FakeRedis()
    ids = [f"msg_{i}" for i in range(4)]
    fr.set_zset_inbox([
        {"id": x, "from_char_id": "moderator", "subject": f"S{x}",
         "body": "reply", "created_at": i} for i, x in enumerate(ids)
    ])
    ok = rh._acknowledge_operator_directive(fr, "msg_2", "char_306", "complete")
    assert ok is True
    # the other three moderator messages remain untouched
    assert fr._zset_inbox == ["msg_0", "msg_1", "msg_3"]


def test_ack_not_sender_wide():
    fr = FakeRedis()
    ids = [f"msg_{i}" for i in range(3)]
    fr.set_zset_inbox([
        {"id": x, "from_char_id": "moderator", "subject": f"S{x}",
         "body": "reply", "created_at": i} for i, x in enumerate(ids)
    ])
    # ack exactly msg_0; the fact that all are from "moderator" proves the
    # helper is NOT sender-wide (only one removed).
    rh._acknowledge_operator_directive(fr, "msg_0", "char_306")
    assert fr._zset_inbox == ["msg_1", "msg_2"]


def test_ack_preserves_msg_payload():
    """The underlying msg:{id} HASH/JSON payload is never deleted."""
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_a", "from_char_id": "moderator", "subject": "A",
         "body": "reply", "created_at": 5},
        {"id": "msg_b", "from_char_id": "moderator", "subject": "B",
         "body": "reply", "created_at": 4},
    ])
    # simulate a populated payload store
    payloads = {"msg_a": {"id": "msg_a", "body": "kept"}, "msg_b": {"id": "msg_b"}}
    fr._hashes = payloads
    rh._acknowledge_operator_directive(fr, "msg_a", "char_306")
    # payload store must be unchanged (helper never calls delete on msg:{id})
    assert fr._hashes == payloads


def test_ack_legacy_list_fallback():
    fr = FakeRedis()
    fr.set_inbox([
        _mod_msg("leg1", "reply please", "L1"),
        _mod_msg("leg2", "another reply", "L2"),
    ])
    ok = rh._acknowledge_operator_directive(fr, "leg2", "char_306")
    assert ok is True
    remaining = [json.loads(x)["id"] for x in fr._inbox]
    assert remaining == ["leg1"]


def test_ack_noop_when_incomplete_status_not_terminal():
    """Patch B's ack in npc_actions is gated on terminal status; the helper
    itself only requires a valid id. Verify it returns False on empty id."""
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_a", "from_char_id": "moderator", "subject": "A",
         "body": "reply", "created_at": 1},
    ])
    assert rh._acknowledge_operator_directive(fr, "", "char_306") is False
    assert fr._zset_inbox == ["msg_a"]


def test_ack_noop_on_send_failure():
    """If the operator response failed validation, the directive should still be
    archived (truthful failure reported); helper removes by id regardless."""
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_x", "from_char_id": "moderator", "subject": "X",
         "body": "reply", "created_at": 1},
        {"id": "msg_y", "from_char_id": "moderator", "subject": "Y",
         "body": "reply", "created_at": 2},
    ])
    ok = rh._acknowledge_operator_directive(fr, "msg_x", "char_306", "failed")
    assert ok is True
    assert fr._zset_inbox == ["msg_y"]


def test_ack_truthful_failure_archived_once():
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_t", "from_char_id": "moderator", "subject": "T",
         "body": "reply", "created_at": 1},
    ])
    # calling twice (e.g. idempotent re-run) should not error and only remove once
    first = rh._acknowledge_operator_directive(fr, "msg_t", "char_306", "failed")
    second = rh._acknowledge_operator_directive(fr, "msg_t", "char_306", "failed")
    assert first is True
    assert second is False
    assert fr._zset_inbox == []


def test_ack_wired_via_execute_decision(setup, monkeypatch):
    """End-to-end: a complete operator send with operator_directive_id calls
    execute_decision's exact-id acknowledgement and removes ONLY that message
    from the ZSET inbox (never the generic sender-wide moderator ack)."""
    import npc_actions as na
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_a", "from_char_id": "moderator", "subject": "A",
         "body": "reply", "created_at": 3},
        {"id": "msg_b", "from_char_id": "moderator", "subject": "B",
         "body": "reply", "created_at": 2},
    ])
    monkeypatch.setattr(na, "CHAR_ID", "char_306")
    monkeypatch.setattr(na, "_partner_id", lambda *a, **k: "char_001")

    generic_calls = []
    exact_calls = []

    def spy_generic(r, target, char_id=""):
        generic_calls.append((target, char_id))
        return 0

    def spy_exact(r, directive_id, char_id="", status="complete"):
        exact_calls.append((directive_id, char_id, status))
        return rh._acknowledge_operator_directive(r, directive_id, char_id, status)

    monkeypatch.setattr(na, "_acknowledge_inbox", spy_generic)
    monkeypatch.setattr(na, "_acknowledge_operator_directive", spy_exact)

    decision = {
        "category": "send_message",
        "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "report",
        "reasoning": "op",
        "operator_directive_id": "msg_a",
        "operator_response_status": "complete",
    }
    result = na.execute_decision(decision, fr,
                                 {"moderator": "Federation Moderator",
                                  "char_001": "Archimedes"})
    assert result.get("action_taken") == "message_sent"
    assert result.get("operator_directive_acked") == "msg_a"
    # exactly one exact-id ack, no generic moderator ack
    assert exact_calls == [("msg_a", "char_306", "complete")]
    assert generic_calls == []  # OPERATOR_ID never appended to ack_targets
    # only msg_a removed; msg_b remains
    assert fr._zset_inbox == ["msg_b"]


def test_archimedes_inbox_unaffected():
    """Acknowledging Oracle's directive must never touch Archimedes' inbox."""
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_306a", "from_char_id": "moderator", "subject": "A",
         "body": "reply", "created_at": 1},
    ])
    # Archimedes inbox is a separate key; helper is char-scoped
    ok = rh._acknowledge_operator_directive(fr, "msg_306a", "char_001")
    assert ok is True  # it removed from char_001's inbox, not char_306's
    # char_306 inbox untouched (separate FakeRedis would hold it)
    fr306 = FakeRedis()
    fr306.set_zset_inbox([
        {"id": "msg_306a", "from_char_id": "moderator", "subject": "A",
         "body": "reply", "created_at": 1},
    ])
    # nothing removed from char_306 because we only acked char_001
    assert fr306._zset_inbox == ["msg_306a"]


# ────────────────────────────────────────────────────────────────────────────
# Patch B: acknowledgement-control regression tests.
# ────────────────────────────────────────────────────────────────────────────

def _run_execute_decision_with_acks(monkeypatch, fr, decision, char_id="char_306"):
    import npc_actions as na
    monkeypatch.setattr(na, "CHAR_ID", char_id)
    monkeypatch.setattr(na, "_partner_id", lambda *a, **k: "char_001")
    generic_calls = []
    exact_calls = []

    def spy_generic(r, target, char_id=""):
        generic_calls.append((target, char_id))
        return 0

    def spy_exact(r, directive_id, char_id="", status="complete"):
        exact_calls.append((directive_id, char_id, status))
        return rh._acknowledge_operator_directive(r, directive_id, char_id, status)

    monkeypatch.setattr(na, "_acknowledge_inbox", spy_generic)
    monkeypatch.setattr(na, "_acknowledge_operator_directive", spy_exact)
    result = na.execute_decision(decision, fr,
                                 {"moderator": "Federation Moderator",
                                  "char_001": "Archimedes"})
    return result, generic_calls, exact_calls


def test_terminal_operator_response_invokes_exact_ack_once(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "msg_a", "operator_response_status": "complete",
    }
    _, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    assert len(exact) == 1
    assert exact[0][0] == "msg_a"


def test_generic_moderator_ack_not_called_for_operator(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "msg_a", "operator_response_status": "complete",
    }
    _, generic, _ = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    # OPERATOR_ID ("moderator") must never reach the generic ack path
    assert all(t != "moderator" for (t, _) in generic)
    assert generic == []


def test_legacy_list_only_selected_directive_removed(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_inbox([
        _mod_msg("leg1", "reply please", "L1"),
        _mod_msg("leg2", "another reply", "L2"),
    ])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "leg2", "operator_response_status": "complete",
    }
    _, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    assert exact and exact[0][0] == "leg2"
    assert generic == []
    # legacy list retains the unselected moderator message
    remaining = [json.loads(x)["id"] for x in fr.lrange("npc_messages:char_306:inbox", 0, -1)]
    assert remaining == ["leg1"]


def test_production_zset_only_selected_member_removed(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_1", "from_char_id": "moderator", "subject": "1", "body": "reply", "created_at": 5},
        {"id": "msg_2", "from_char_id": "moderator", "subject": "2", "body": "reply", "created_at": 4},
        {"id": "msg_3", "from_char_id": "moderator", "subject": "3", "body": "reply", "created_at": 3},
        {"id": "msg_4", "from_char_id": "moderator", "subject": "4", "body": "reply", "created_at": 2},
        {"id": "msg_5", "from_char_id": "moderator", "subject": "5", "body": "reply", "created_at": 1},
    ])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "msg_3", "operator_response_status": "complete",
    }
    _, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    assert exact and exact[0][0] == "msg_3"
    assert generic == []
    assert fr._zset_inbox == ["msg_1", "msg_2", "msg_4", "msg_5"]


def test_remaining_zset_entries_preserved_order_scores(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_1", "from_char_id": "moderator", "subject": "1", "body": "reply", "created_at": 5},
        {"id": "msg_2", "from_char_id": "moderator", "subject": "2", "body": "reply", "created_at": 4},
        {"id": "msg_3", "from_char_id": "moderator", "subject": "3", "body": "reply", "created_at": 3},
        {"id": "msg_4", "from_char_id": "moderator", "subject": "4", "body": "reply", "created_at": 2},
        {"id": "msg_5", "from_char_id": "moderator", "subject": "5", "body": "reply", "created_at": 1},
    ])
    scores_before = {m: fr._zset_scores.get(m) for m in fr._zset_inbox}
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "msg_3", "operator_response_status": "complete",
    }
    _run_execute_decision_with_acks(monkeypatch, fr, decision)
    for kept in ("msg_1", "msg_2", "msg_4", "msg_5"):
        assert kept in fr._zset_inbox
        assert fr._zset_scores.get(kept) == scores_before[kept]


def test_underlying_msg_payload_preserved(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    fr._hashes["msg_a"] = {"id": "msg_a", "body": "full payload"}
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        "operator_directive_id": "msg_a", "operator_response_status": "complete",
    }
    _run_execute_decision_with_acks(monkeypatch, fr, decision)
    # the msg:{id} HASH/string is preserved for audit
    assert fr._hashes.get("msg_a") == {"id": "msg_a", "body": "full payload"}


def test_non_terminal_operator_response_no_ack(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "r", "reasoning": "o",
        # status "pending" => non-terminal, must NOT acknowledge
        "operator_directive_id": "msg_a", "operator_response_status": "pending",
    }
    result, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    assert exact == []
    assert generic == []
    assert "operator_directive_acked" not in result
    assert fr._zset_inbox == ["msg_a"]


def test_ordinary_partner_response_retains_generic_ack(setup, monkeypatch):
    fr = FakeRedis()
    decision = {
        "category": "send_message", "target": "char_001",
        "body": "hello partner", "description": "d", "reasoning": "r",
    }
    _, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    # partner ack still uses generic inbox ack; no operator exact ack
    assert exact == []
    assert generic == [("char_001", "")]


def test_non_enforced_moderator_message_no_exact_ack(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    # ordinary (non-enforced) reply to moderator: no operator_directive_id
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "understood, working on it", "description": "d", "reasoning": "r",
    }
    result, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    assert exact == []
    # the generic sender-wide ack SHOULD still run for ordinary moderator replies
    # (partner inbox is also acked historically; both are no-op stubs on ZSET)
    assert generic == [("char_001", ""), ("moderator", "")]
    # message remains (FakeRedis generic ack is a no-op stub returning 0)
    assert fr._zset_inbox == ["msg_a"]


def test_failed_status_acked_only_after_send(setup, monkeypatch):
    fr = FakeRedis()
    fr.set_zset_inbox([{"id": "msg_a", "from_char_id": "moderator", "subject": "A",
                        "body": "reply", "created_at": 1}])
    decision = {
        "category": "send_message", "target": "moderator",
        "body": "1. Prioritized Criteria: x. 2. Quantitative Metrics and Suggested Thresholds: y. 3. Sector Comparison Method: z. 4. Risk and Ethical Safeguards: w. 5. Final Recommendation: v.",
        "description": "truthful failure notice", "reasoning": "o",
        "operator_directive_id": "msg_a", "operator_response_status": "failed",
    }
    result, generic, exact = _run_execute_decision_with_acks(monkeypatch, fr, decision)
    # failed terminal response must still be acknowledged by exact id
    assert exact and exact[0] == ("msg_a", "char_306", "failed")
    assert generic == []
    assert result.get("operator_directive_acked") == "msg_a"
    assert fr._zset_inbox == []

def test_operator_ack_record_is_bounded_latest_only(setup, monkeypatch):
    """The operator_ack:{cid} audit record must overwrite (SET), never grow.

    It represents only the single latest acknowledgement for the NPC, so the
    Redis key cannot accumulate one field per directive (unbounded HASH/LIST).
    """
    fr = FakeRedis()
    fr.set_zset_inbox([
        {"id": "msg_a", "from_char_id": "moderator", "body": "1", "created_at": 1},
        {"id": "msg_b", "from_char_id": "moderator", "body": "2", "created_at": 2},
        {"id": "msg_c", "from_char_id": "moderator", "body": "3", "created_at": 3},
    ])
    rh._now_ts = lambda: 1000.0
    assert rh._acknowledge_operator_directive(fr, "a", char_id="char_306", status="complete") is True
    assert rh._acknowledge_operator_directive(fr, "b", char_id="char_306", status="complete") is True
    assert rh._acknowledge_operator_directive(fr, "c", char_id="char_306", status="failed") is True
    key = "operator_ack:char_306"
    raw = fr.get(key)
    assert raw is not None, "operator_ack record must be written"
    rec = json.loads(raw)
    assert rec["directive_id"] == "msg_c"
    assert rec["status"] == "failed"
    assert rec["ts"] == 1000.0
    assert set(rec.keys()) == {"directive_id", "status", "ts"}
    assert isinstance(raw, str) and raw.startswith("{")
