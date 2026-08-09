"""Tests for semantic deduplication + outcome feedback in npc_redis_helpers.py.

Proves:
  · _semantic_overlap — content-level similarity (not just title) scores
    near-identical bodies high even under different titles.
  · _find_semantic_duplicate_artifact — catches a re-published body under a
    new title, across both the agent's own artifacts and the partner's.
  · _record_outcome_feedback / _load_outcome_feedback — a durable outcome
    record is written per-char and to the shared pair list, and reloaded for
    prompt injection.

No live Redis. A small FakeRedis provides the list/hash primitives used.
"""
import importlib.util
import json
import os
import sys
import types

# Stub redis so importing npc_redis_helpers does not require a live server.
class _DummyRedis:
    @staticmethod
    def from_url(*a, **k):
        return None
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=_DummyRedis))

MODULE_PATH = os.path.join(os.path.dirname(__file__), "npc_redis_helpers.py")
spec = importlib.util.spec_from_file_location("npc_redis_helpers_sem", MODULE_PATH)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


class FakeRedis:
    """Minimal fake exposing the list primitives used by the helpers."""

    def __init__(self):
        self.lists = {}
        self.hashes = {}

    def lrange(self, key, start, stop):
        items = self.lists.get(key, [])
        n = len(items)
        if start < 0 or stop < 0:
            s = max(0, n + start) if start < 0 else start
            e = n + stop + 1 if stop < 0 else stop + 1
            return items[s:e]
        return items[start:stop]

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def ltrim(self, key, start, stop):
        items = self.lists.get(key, [])
        self.lists[key] = items[start:stop + 1]

    def expire(self, *a, **k):
        return True

    def set(self, *a, **k):
        return True

    def get(self, *a, **k):
        return None

    def delete(self, *a, **k):
        for key in a:
            self.lists.pop(key, None)
        return True

    def eval(self, script, numkeys, key, new_json, cap, ttl):
        """Mirror of the resolve-or-append Lua used by
        _record_outcome_consequence (atomic in real Redis; single-threaded
        here, so the same semantics apply)."""
        try:
            new_entry = json.loads(new_json)
        except Exception:
            return -1
        items = self.lists.get(key, [])
        title = new_entry.get("artifact_title")
        resolved = 0
        for i, raw in enumerate(items):
            try:
                e = json.loads(raw)
            except Exception:
                continue
            if (e.get("artifact_title") == title
                    and "awaiting" in e.get("outcome", "")):
                items[i] = new_json
                resolved = 1
                break
        if resolved:
            self.lists[key] = items
        else:
            self.lists.setdefault(key, []).insert(0, new_json)
            self.lists[key] = self.lists[key][:cap]
        return resolved


def _art(art_id, title, content):
    return {
        "artifact_id": art_id,
        "title": title,
        "content": content,
        "created_at": 1000,
    }


class TestSemanticOverlap:
    def test_identical_scores_one(self):
        assert helpers._semantic_overlap(
            "The Void Oracle Anomalies A Comprehensive Analysis",
            "The Void Oracle Anomalies A Comprehensive Analysis",
        ) == 1.0

    def test_near_duplicate_under_new_title_scores_high(self):
        # Same content re-framed under a different title.
        a = "Void Oracle anomalies detailed study of resonance corruption"
        b = "Anomalies of the Void Oracle full study resonance and corruption"
        score = helpers._semantic_overlap(a, b)
        assert score >= 0.7

    def test_distinct_content_scores_low(self):
        score = helpers._semantic_overlap(
            "Economic trade routes and galactic commerce",
            "Mystic prophecies of the deep null",
        )
        assert score < 0.3

    def test_short_inside_long_not_blocked(self):
        # Regression: a short generic artifact whose words are a subset of a
        # longer, unrelated piece must NOT score 1.0 (false-positive dedup).
        a = "analyzing the current state of the federation"
        b = ("analyzing the current state of the federation and the deep "
             "resonance corruption drift lattice anomaly signal in the void oracle")
        score = helpers._semantic_overlap(a, b)
        assert score < 0.7


class TestFindSemanticDuplicate:
    def test_catches_own_republish(self):
        r = FakeRedis()
        r.lists["npc_artifacts:char_001"] = [json.dumps(_art(
            "a1", "Void Anomalies Comprehensive", "analysis of void oracle anomalies resonance corruption drift lattice"
        ))]
        hit = helpers._find_semantic_duplicate_artifact(
            r, "Anomalies of the Void: Full Study",
            "a full study of void oracle anomalies and resonance corruption drift and the lattice",
            "char_001",
        )
        assert hit is not None
        assert hit.get("artifact_id") == "a1"

    def test_catches_partner_republish(self):
        # char_001 tries to publish content char_306 already wrote.
        r = FakeRedis()
        r.lists["npc_artifacts:char_306"] = [json.dumps(_art(
            "a306", "Oracle Resonance Study", "resonance lattice corruption drift in the void oracle study"
        ))]
        hit = helpers._find_semantic_duplicate_artifact(
            r, "Study of Resonance Corruption",
            "resonance lattice and corruption drift in the void oracle",
            "char_001",
        )
        assert hit is not None
        assert hit.get("artifact_id") == "a306"

    def test_distinct_allowed(self):
        r = FakeRedis()
        r.lists["npc_artifacts:char_001"] = [json.dumps(_art(
            "a1", "Trade Routes", "economic trade routes and commerce across the galaxy"
        ))]
        hit = helpers._find_semantic_duplicate_artifact(
            r, "Omen of the Deep Null", "mystic prophecy about the deep null and the void",
            "char_001",
        )
        assert hit is None


class TestReflection:
    def test_record_and_load(self):
        r = FakeRedis()
        helpers._record_reflection(r, "Recent work has concentrated on create_artifact.", "char_001")
        loaded = helpers._load_reflections(r, "char_001")
        assert "Reflections" in loaded
        assert "create_artifact" in loaded

    def test_dedup_prevents_repeat(self):
        r = FakeRedis()
        helpers._record_reflection(r, "Consistently producing durable work.", "char_001")
        helpers._record_reflection(r, "Consistently producing durable work.", "char_001")
        raw = r.lists.get("npc_reflections:char_001", [])
        assert len(raw) == 1

    def test_derive_from_repetitive_journal(self):
        # A journal full of 'rest' with no artifact triggers the low-output insight.
        r = FakeRedis()
        pid = helpers._partner_id("char_001")
        journal_key = f"npc_pair:{helpers._pair_slug('char_001', pid)}:journal"
        for i in range(5):
            r.rpush(journal_key, json.dumps({
                "ts": 1000 + i, "actor": "char_001", "category": "rest",
                "summary": f"reflected {i}",
            }))
        insights = helpers._derive_reflections_from_journal(r, "char_001")
        assert any("Little durable output" in i for i in insights)


class TestOutcomeFeedback:
    def test_record_and_load(self):
        r = FakeRedis()
        helpers._record_outcome_feedback(
            r, "Void Anomalies Study", "partner answered with a new question",
            consequence={"chars": 500}, char_id="char_001",
        )
        loaded = helpers._load_outcome_feedback(r, "char_001")
        assert "Outcomes you have produced" in loaded
        assert "Void Anomalies Study" in loaded
        assert "partner answered" in loaded

    def test_pair_ledger_shared(self):
        r = FakeRedis()
        helpers._record_outcome_feedback(
            r, "Resonance Mapping", "world morale rose",
            char_id="char_306",
        )
        # char_001 should see the shared outcome too.
        loaded = helpers._load_outcome_feedback(r, "char_001")
        assert "Resonance Mapping" in loaded
        per_char = r.lists.get("npc_outcomes:char_306", [])
        pair = r.lists.get("npc_pair:char_001__char_306:outcomes", [])
        assert len(per_char) == 1
        assert len(pair) == 1

    def test_consequence_resolves_placeholder_in_place(self):
        # A placeholder "awaiting" entry is promoted to the real consequence
        # rather than appended, so the ledger does not fill with stale text.
        r = FakeRedis()
        helpers._record_outcome_feedback(
            r, "Void Study", "artifact published; awaiting downstream consequence",
            char_id="char_001",
        )
        helpers._record_outcome_consequence(
            r, "Void Study", "partner answered with a new question",
            char_id="char_001",
        )
        per_char = r.lists.get("npc_outcomes:char_001", [])
        assert len(per_char) == 1  # resolved in place, not appended
        assert "awaiting" not in per_char[0]
        assert "partner answered" in per_char[0]

    def test_consequence_without_placeholder_appends(self):
        # If no placeholder exists, a consequence is appended as a fresh record.
        r = FakeRedis()
        helpers._record_outcome_consequence(
            r, "New Work", "produced durable work", char_id="char_001",
        )
        per_char = r.lists.get("npc_outcomes:char_001", [])
        assert len(per_char) == 1
        assert "produced durable work" in per_char[0]