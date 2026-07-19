"""Tests for the Councilor Watch post-resolution semantic-loop transition.

These tests prove that a resolved NPC pair performs a ONE-TIME transition away
from its resolved shared goal instead of repeatedly re-anchoring to the generic
"What happens next in the Federation?" default, which produced an infinite loop.

Only npc_redis_helpers._sync_pair_workspace is exercised. The convergence_state
is pre-seeded so the internal call to _compute_convergence_state is a no-op (its
early-return guard keeps the seeded resolution intact) -- no LLM/model calls occur.
"""

import json
import time

import pytest

import npc_redis_helpers as M


PARTNER = "char_306"
CHAR = "char_001"
RESOLVED_GOAL = "Coordinate harmonic resonance between the deep signal and the lattice anchor"
DEFAULT_QUESTION = M._default_open_question()


class _Pipe:
    def __init__(self, store):
        self._store = store

    def hset(self, name, mapping=None, **fields):
        h = self._store.setdefault(name, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})

    def hdel(self, name, *fields):
        h = self._store.setdefault(name, {})
        for f in fields:
            h.pop(f, None)

    def expire(self, name, ttl):
        self._store.setdefault(name, {})["__ttl__"] = ttl

    def execute(self):
        return True


class FakeRedis:
    """In-memory hash store with the subset of the redis API we use."""

    def __init__(self):
        self.store = {}
        self.expire_calls = []

    def hgetall(self, name):
        raw = self.store.get(name, {})
        return {k: v for k, v in raw.items() if k != "__ttl__"}

    def hset(self, name, mapping=None, **fields):
        h = self._store_for(name)
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        h.update({k: str(v) for k, v in fields.items()})

    def hdel(self, name, *fields):
        h = self._store_for(name)
        for f in fields:
            h.pop(f, None)

    def expire(self, name, ttl):
        self._store_for(name)["__ttl__"] = ttl
        self.expire_calls.append((name, ttl))

    def rpush(self, name, value):
        self._store_for(name).setdefault("__list__", []).append(value)

    def ltrim(self, name, start, end):
        pass

    def pipeline(self, transaction=False):
        return _Pipe(self.store)

    def _store_for(self, name):
        return self.store.setdefault(name, {})


def _seeded_state(resolved_goal=RESOLVED_GOAL, shared_goal=RESOLVED_GOAL,
                  next_question="", converged=True, open_question="",
                  transitioned=""):
    conv = {
        "version": 1,
        "resolved": converged,
        "resolved_shared_goal": resolved_goal,
        "next_question": next_question,
    }
    state = {
        "shared_goal": shared_goal,
        "resolved_shared_goal": resolved_goal,
        "open_question": open_question,
        "open_question_source": "",
        "post_resolution_transitioned": transitioned,
        "convergence_state": json.dumps(conv),
    }
    return state


def _make_redis(state, extra=None):
    r = FakeRedis()
    key = f"npc_pair:{CHAR}__{PARTNER}:state"
    r.store[key] = dict(state)
    if extra:
        for k, v in extra.items():
            r.store[k] = dict(v)
    return r, key


def _sync(r, char_id=CHAR):
    decision = {"category": "rest", "description": "tick", "reasoning": "tick"}
    result = {"category": "rest", "ts": int(time.time()), "message_body": "",
              "action_taken": "none", "target": ""}
    M._sync_pair_workspace(r, decision, result, npc_name="Archimedes Prime",
                           char_id=char_id)


def _state_after(r, key):
    return r.hgetall(key)


def test_resolved_goal_retained_in_resolved_shared_goal():
    state = _seeded_state()
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["resolved_shared_goal"] == RESOLVED_GOAL


def test_resolved_goal_retired_from_active_shared_goal():
    state = _seeded_state()
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert "shared_goal" not in after or after.get("shared_goal") == ""


def test_valid_unrelated_next_question_selected():
    next_q = "Should the councilor review the new trade accord with Gastown?"
    state = _seeded_state(next_question=next_q)
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["open_question"] == next_q
    assert after["open_question_source"] == "post_resolution_next_question"
    assert after.get("post_resolution_transitioned") == "1"


def test_blank_next_question_uses_neutral_transition():
    state = _seeded_state(next_question="")
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["open_question"] == M._POST_RESOLUTION_NEUTRAL_QUESTION
    assert after["open_question_source"] == "post_resolution_new_topic"


def test_blocked_next_question_uses_neutral_transition():
    conv = {
        "version": 1,
        "resolved": True,
        "resolved_shared_goal": RESOLVED_GOAL,
        "next_question": "Discuss the resonance lattice again",
        "blocked_topic_terms": ["resonance", "lattice"],
    }
    state = _seeded_state()
    state["convergence_state"] = json.dumps(conv)
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["open_question"] == M._POST_RESOLUTION_NEUTRAL_QUESTION
    assert after["open_question_source"] == "post_resolution_new_topic"


def test_similar_to_resolved_next_question_uses_neutral():
    similar = "Coordinate the harmonic resonance lattice anchor protocol"
    state = _seeded_state(next_question=similar)
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["open_question"] == M._POST_RESOLUTION_NEUTRAL_QUESTION


def test_old_generic_default_not_reapplied():
    state = _seeded_state()
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    assert after["open_question"] != DEFAULT_QUESTION


def test_second_and_third_sync_idempotent():
    state = _seeded_state(next_question="What trade policy should the pair set next?")
    r, key = _make_redis(state)
    _sync(r)
    after1 = dict(_state_after(r, key))
    q1 = after1["open_question"]
    # Second and third syncs must not restore the old resolved goal, must not
    # re-randomize a different question, and must keep the same transition text.
    _sync(r)
    after2 = _state_after(r, key)
    _sync(r)
    after3 = _state_after(r, key)
    assert q1 == after2["open_question"] == after3["open_question"]
    assert "shared_goal" not in after2 or after2.get("shared_goal") == ""
    assert "shared_goal" not in after3 or after3.get("shared_goal") == ""
    assert after3["open_question_source"] == "post_resolution_next_question"
    assert after3["resolved_shared_goal"] == RESOLVED_GOAL


def test_unrelated_unresolved_work_unchanged():
    # Fields that are intentionally refreshed every sync (current_topic / focus)
    # are out of scope; this test guards the *unrelated* resolved-state evidence
    # and the fact that no external hash is touched (see test_no_external...).
    state = _seeded_state()
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    # resolved_shared_goal is preserved; last_actor reflects the sync actor.
    assert after["resolved_shared_goal"] == RESOLVED_GOAL
    assert after["last_actor"] == CHAR


def test_operator_acknowledgements_and_inbox_untouched():
    # A separate hash representing operator ack/inbox state must be untouched.
    ack_state = {"last_ack_id": "ack_42", "status": "active", "inbox": "msg_7"}
    state = _seeded_state()
    r, key = _make_redis(state, extra={"operator:char_001:ack": ack_state,
                                       "npc_pair:char_001__char_306:inbox": {"m": "x"}})
    _sync(r)
    assert r.hgetall("operator:char_001:ack") == ack_state
    assert r.hgetall("npc_pair:char_001__char_306:inbox") == {"m": "x"}


def test_ttl_expiry_calls_correct():
    state = _seeded_state()
    r, key = _make_redis(state)
    _sync(r)
    # _pair_hset applies TTL via the pipeline; the store records it as __ttl__.
    assert r.store[key].get("__ttl__") == M.PAIR_STATE_TTL


def test_no_external_redis_value_changed():
    other_key = "npc_pair:char_999__char_888:state"
    other_state = {"shared_goal": "another pair goal", "open_question": "prev"}
    state = _seeded_state()
    r, key = _make_redis(state, extra={other_key: other_state})
    _sync(r)
    assert r.hgetall(other_key) == other_state


def test_no_transition_when_not_resolved():
    # No active shared_goal and not resolved => falls to system default.
    state = _seeded_state(converged=False, shared_goal="")
    r, key = _make_redis(state)
    _sync(r)
    after = _state_after(r, key)
    # Not resolved => no transition marker; generic default applies.
    assert after.get("open_question") == DEFAULT_QUESTION
    assert after.get("post_resolution_transitioned") != "1"
