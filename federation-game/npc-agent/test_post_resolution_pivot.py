"""Narrow isolated tests for the post-resolution open-question pivot
in npc_redis_helpers._sync_pair_workspace().

These tests mock Redis with FakeRedis and call _sync_pair_workspace
directly to validate the post-resolution branching logic.
"""
import importlib.util
import json
import os
import sys
import time
import types

class _DummyRedis:
    @staticmethod
    def from_url(*a, **k):
        return None
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=_DummyRedis))
sys.modules.setdefault("httpx", types.SimpleNamespace(
    Client=object, TimeoutException=Exception,
    RequestError=Exception, HTTPStatusError=Exception))

MODULE_PATH = os.path.join(os.path.dirname(__file__), "npc_redis_helpers.py")
spec = importlib.util.spec_from_file_location("npc_redis_helpers_under_test", MODULE_PATH)
nh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nh)


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}
        self.strings = {}
        self.expiries = {}
        self.counters = {}
        self.zsets = {}

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        if key not in self.hashes:
            self.hashes[key] = {}
        self.hashes[key][field] = value

    def hincrby(self, key, field, amount):
        if key not in self.hashes:
            self.hashes[key] = {}
        self.hashes[key][field] = str(int(self.hashes[key].get(field, 0)) + amount)
        return self.hashes[key][field]

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    def rpush(self, key, *values):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].extend(values)

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(len(items) + start, 0)
        self.lists[key] = items[start:] if start < len(items) else []

    def expire(self, key, seconds):
        self.expiries[key] = time.time() + seconds

    def zadd(self, key, mapping):
        if key not in self.zsets:
            self.zsets[key] = []
        for member, score in mapping.items():
            self.zsets[key].append((score, member))

    def zrevrange(self, key, start, end):
        items = self.zsets.get(key, [])
        items.sort(key=lambda x: x[0], reverse=True)
        return [m for s, m in items[start:end+1] if end >= 0]

    def zremrangebyrank(self, key, start, end):
        pass

    def set(self, key, value, ex=None):
        self.strings[key] = value

    def pipeline(self, transaction=False):
        return _Pipeline(self)

    def scan_iter(self, pattern):
        return []

    def exists(self, key):
        return 1 if (key in self.hashes or key in self.lists or key in self.strings) else 0


class _Pipeline:
    def __init__(self, r):
        self._r = r
        self._ops = []

    def hset(self, key, field=None, value=None, mapping=None):
        self._ops.append(("hset", key, field, value, mapping))

    def hdel(self, key, *fields):
        self._ops.append(("hdel", key, fields))

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))

    def zremrangebyrank(self, key, start, end):
        pass

    def expire(self, key, seconds):
        pass

    def execute(self):
        for op in self._ops:
            if op[0] == "hset":
                _, key, field, value, mapping = op
                if mapping:
                    self._r.hashes.setdefault(key, {}).update(mapping)
                elif field is not None:
                    self._r.hashes.setdefault(key, {})[field] = str(value)
            elif op[0] == "hdel":
                _, key, fields = op
                for f in fields:
                    self._r.hashes.get(key, {}).pop(f, None)
            elif op[0] == "zadd":
                _, key, mapping = op
                if key not in self._r.zsets:
                    self._r.zsets[key] = []
                for member, score in mapping.items():
                    self._r.zsets[key].append((score, member))


def _make_convergence_state(resolved=False, blocked=None, next_q=""):
    return json.dumps({
        "resolved": resolved,
        "resolved_shared_goal": "report on deep signals",
        "resolved_answer": "answer text",
        "resolved_question": next_q if next_q else "how?",
        "blocked_topic_terms": blocked or [],
        "next_question": next_q,
        "version": 1,
        "updated_at": int(time.time()),
    })


class TestPostResolutionPivot:
    """Validate post_resolution branch in _sync_pair_workspace."""

    def _setup(self, state_overrides=None):
        r = FakeRedis()
        pid = "char_306"
        cid = "char_001"
        now = int(time.time())
        state = {
            "shared_goal": "report on deep signals",
            "open_question": "",
            "updated_char_001": str(now),
            "updated_char_306": str(now),
        }
        if state_overrides:
            state.update(state_overrides)
        state_key = f"npc_pair:char_001__char_306:state"
        r.hashes[state_key] = dict(state)
        return r, pid, cid, now, state_key

    def test_next_question_accepted_when_no_blocked_terms(self):
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": _make_convergence_state(
                resolved=True, blocked=None,
                next_q="What new sensor modality could test these assumptions?")
        })
        decision = {"category": "create_artifact", "title": "Test Artifact"}
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Test Artifact", "ts": now}
        nh._sync_pair_workspace(r, decision, result, "Archimedes Prime", cid)
        state = r.hgetall(state_key)
        assert state.get("open_question") == "What new sensor modality could test these assumptions?"
        assert state.get("open_question_source") == "post_resolution_pivot"
        assert state.get("resolved_artifact") == "Test Artifact"
        assert state.get("resolved_action") == "artifact_created"
        assert state.get("resolved_at_sync")

    def test_next_question_accepted_when_blocked_terms_empty_list(self):
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": _make_convergence_state(
                resolved=True, blocked=[],
                next_q="How do witness layers beyond known space relate to this?")
        })
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Test Artifact", "ts": now}
        nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "Archimedes Prime", cid)
        state = r.hgetall(state_key)
        assert state.get("open_question") == "How do witness layers beyond known space relate to this?"
        assert state.get("open_question_source") == "post_resolution_pivot"

    def test_next_question_rejected_when_blocked_term_present(self):
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": _make_convergence_state(
                resolved=True, blocked=["resonance", "lattice"],
                next_q="How does resonance affect the lattice?")
        })
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Test Artifact", "ts": now}
        nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "Archimedes Prime", cid)
        state = r.hgetall(state_key)
        assert state.get("open_question") != "How does resonance affect the lattice?"
        assert state.get("open_question_source") == "post_resolution_default"

    def test_fallback_question_not_generic_default(self):
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": _make_convergence_state(
                resolved=True, blocked=["resonance"],
                next_q="How does resonance affect the lattice?")
        })
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Test Artifact", "ts": now}
        nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "Archimedes Prime", cid)
        state = r.hgetall(state_key)
        oq = state.get("open_question", "")
        assert oq != "What happens next in the Federation?"

    def test_resolved_metadata_recorded(self):
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": _make_convergence_state(
                resolved=True, blocked=[],
                next_q="What new evidence is available?")
        })
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Deep Signal Taxonomy", "ts": now}
        nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "The Oracle", cid)
        state = r.hgetall(state_key)
        assert state.get("resolved_artifact") == "Deep Signal Taxonomy"
        assert state.get("resolved_action") == "artifact_created"
        assert state.get("resolved_at_sync") == str(now)

    def test_blocked_terms_normalized_from_string(self):
        """If blocked_topic_terms is stored as a JSON string in Redis,
        it should be parsed, not iterated character by character."""
        conv = {
            "resolved": True,
            "resolved_shared_goal": "report on deep signals",
            "resolved_answer": "answer",
            "resolved_question": "how?",
            "blocked_topic_terms": "resonance",
            "next_question": "What about resonance?",
            "version": 1,
            "updated_at": int(time.time()),
        }
        r, pid, cid, now, state_key = self._setup({
            "convergence_state": json.dumps(conv),
        })
        result = {"category": "create_artifact", "action_taken": "artifact_created",
                  "artifact_title": "Test Artifact", "ts": now}
        nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "Archimedes Prime", cid)
        state = r.hgetall(state_key)
        assert state.get("open_question_source") == "post_resolution_default"
        assert "resonance" not in (state.get("open_question") or "")


def test_novel_goal_chosen_when_next_question_reenters_recent_theme(monkeypatch):
    """When the LLM's next_question re-enters a recent theme, the novelty gate
    replaces it with a novel proposed goal (post_resolution_novel)."""

    def fake_call_llm(system, prompt, model="", r=None, call_label=""):
        return {"content": '{"candidates":[{"objective":"Map the outer veil of known space","why_novel":"new"},{"objective":"resonance lattice survey","why_novel":"old"},{"objective":"Chart a trade corridor to the diaspora","why_novel":"different"}]}'}

    import npc_llm_client
    monkeypatch.setattr(npc_llm_client, "call_llm", fake_call_llm)

    r, pid, cid, now, state_key = TestPostResolutionPivot()._setup({
        "convergence_state": _make_convergence_state(
            resolved=True, blocked=["resonance", "lattice"],
            next_q="How does resonance affect the lattice?")
    })
    # Seed a recent completed goal so _recent_theme_terms has cooling terms.
    r.lists["npc_pair:char_001__char_306:completed_goals"] = [
        json.dumps({"goal": "report on deep signals", "conclusion": "resonance", "resolved_at": now})
    ]
    result = {"category": "create_artifact", "action_taken": "artifact_created",
              "artifact_title": "Test Artifact", "ts": now}
    nh._sync_pair_workspace(r, {"category": "create_artifact"}, result, "Archimedes Prime", cid)
    state = r.hgetall(state_key)
    oq = state.get("open_question", "")
    assert oq == "Map the outer veil of known space"
    assert state.get("open_question_source") == "post_resolution_novel"
    assert "resonance" not in oq.lower()


if __name__ == "__main__":
    t = TestPostResolutionPivot()
    t.test_next_question_accepted_when_no_blocked_terms()
    t.test_next_question_accepted_when_blocked_terms_empty_list()
    t.test_next_question_rejected_when_blocked_term_present()
    t.test_fallback_question_not_generic_default()
    t.test_resolved_metadata_recorded()
    t.test_blocked_terms_normalized_from_string()
    print("Post-resolution pivot tests passed.")
