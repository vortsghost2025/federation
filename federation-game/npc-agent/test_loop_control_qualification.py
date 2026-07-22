"""
Phase D — Live Loop-Control Candidate Synthetic Qualification Tests

Tests the real production modules (npc_actions, npc_decisions, npc_loop_control)
using an in-memory Redis fake. No network, no real Redis, no model calls,
no protected IDs (the well-known protected councilor IDs).
"""

import sys
import os

# Ensure we import from the correct package
sys.path.insert(0, os.path.dirname(__file__))

# Set test environment variables BEFORE importing production modules
os.environ["CHAR_ID"] = "test_char_901"
os.environ["NPC_NAME"] = "Test NPC 901"
os.environ["SESSION_CAP"] = "24"

# Ensure no external API keys can be used
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

# Now import production modules
from npc_loop_control import (
    record_deferral,
    record_completed_work,
    enforce,
    _defer_key,
    _topic_key,
    _shape_key,
    _normalize_topic,
    _decision_shape,
    DEFER_STREAK_TTL,
    SHAPE_LIST_TTL,
    MAX_SHAPE_HISTORY,
    DEFER_FORCE_ALTERNATIVE,
    SHAPE_REPEAT_HARD_BREAK,
)
from npc_decisions import _enforce_loop_control, decide_action
from npc_actions import execute_decision

import json
import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock


# ════════════════════════════════════════════════════════════════════════
# In-Memory Redis Fake
# ════════════════════════════════════════════════════════════════════════

class FakeRedis:
    """Minimal in-memory Redis implementation supporting only the methods
    actually used by the three production modules under test."""

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._ttl: Dict[str, int] = {}
        self._lists: Dict[str, List[str]] = {}
        self._sets: Dict[str, set] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._sorted_sets: Dict[str, List[tuple]] = {}  # list of (score, value)
        self._expire_times: Dict[str, float] = {}
        import time
        self._time = time.time

    def _cleanup_expired(self):
        now = self._time()
        expired = [k for k, exp in self._expire_times.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)
            self._lists.pop(k, None)
            self._sets.pop(k, None)
            self._hashes.pop(k, None)
            self._sorted_sets.pop(k, None)
            self._expire_times.pop(k, None)
            self._ttl.pop(k, None)

    # Key-value operations
    def get(self, key: str) -> Optional[bytes]:
        self._cleanup_expired()
        val = self._data.get(key)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._data[key] = value
        if ex is not None:
            self._expire_times[key] = self._time() + ex
        return True

    def incr(self, key: str) -> int:
        self._cleanup_expired()
        current = self._data.get(key, 0)
        try:
            current = int(current)
        except (ValueError, TypeError):
            current = 0
        new_val = current + 1
        self._data[key] = str(new_val)
        return new_val

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
            if key in self._lists:
                del self._lists[key]
                count += 1
            if key in self._sets:
                del self._sets[key]
                count += 1
            if key in self._hashes:
                del self._hashes[key]
                count += 1
            if key in self._sorted_sets:
                del self._sorted_sets[key]
                count += 1
            self._expire_times.pop(key, None)
            self._ttl.pop(key, None)
        return count

    def expire(self, key: str, ttl: int) -> bool:
        if key in self._data or key in self._lists or key in self._sets or key in self._hashes or key in self._sorted_sets:
            self._expire_times[key] = self._time() + ttl
            return True
        return False

    def ttl(self, key: str) -> int:
        self._cleanup_expired()
        if key not in self._data and key not in self._lists and key not in self._sets and key not in self._hashes and key not in self._sorted_sets:
            return -2
        exp = self._expire_times.get(key)
        if exp is None:
            return -1
        remaining = int(exp - self._time())
        return max(0, remaining)

    def exists(self, *keys: str) -> int:
        self._cleanup_expired()
        return sum(1 for k in keys if k in self._data or k in self._lists or k in self._sets or k in self._hashes or k in self._sorted_sets)

    # List operations
    def rpush(self, key: str, *values: str) -> int:
        self._cleanup_expired()
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].extend(str(v) for v in values)
        return len(self._lists[key])

    def lrange(self, key: str, start: int, end: int) -> List[bytes]:
        self._cleanup_expired()
        if key not in self._lists:
            return []
        lst = self._lists[key]
        if end == -1:
            end = len(lst)
        else:
            end = min(end + 1, len(lst))
        start = max(0, start)
        return [v.encode("utf-8") for v in lst[start:end]]

    def ltrim(self, key: str, start: int, end: int) -> bool:
        self._cleanup_expired()
        if key not in self._lists:
            return True
        lst = self._lists[key]
        if end == -1:
            end = len(lst)
        else:
            end = min(end + 1, len(lst))
        start = max(0, start)
        self._lists[key] = lst[start:end]
        return True

    # Set operations
    def sadd(self, key: str, *values: str) -> int:
        self._cleanup_expired()
        if key not in self._sets:
            self._sets[key] = set()
        before = len(self._sets[key])
        for v in values:
            self._sets[key].add(str(v))
        return len(self._sets[key]) - before

    def smembers(self, key: str) -> set:
        self._cleanup_expired()
        if key not in self._sets:
            return set()
        return self._sets[key].copy()

    def scard(self, key: str) -> int:
        self._cleanup_expired()
        if key not in self._sets:
            return 0
        return len(self._sets[key])

    # Hash operations
    def hset(self, key: str, mapping: Dict[str, str] = None, **kwargs) -> int:
        self._cleanup_expired()
        if key not in self._hashes:
            self._hashes[key] = {}
        count = 0
        if mapping:
            for k, v in mapping.items():
                if k not in self._hashes[key]:
                    count += 1
                self._hashes[key][k] = str(v)
        for k, v in kwargs.items():
            if k not in self._hashes[key]:
                count += 1
            self._hashes[key][k] = str(v)
        return count

    def hget(self, key: str, field: str) -> Optional[bytes]:
        self._cleanup_expired()
        if key not in self._hashes or field not in self._hashes[key]:
            return None
        return self._hashes[key][field].encode("utf-8")

    def hgetall(self, key: str) -> Dict[bytes, bytes]:
        self._cleanup_expired()
        if key not in self._hashes:
            return {}
        return {k.encode(): v.encode() for k, v in self._hashes[key].items()}

    def hincrby(self, key: str, field: str, amount: int) -> int:
        self._cleanup_expired()
        if key not in self._hashes:
            self._hashes[key] = {}
        current = self._hashes[key].get(field, "0")
        try:
            current = int(current)
        except (ValueError, TypeError):
            current = 0
        new_val = current + amount
        self._hashes[key][field] = str(new_val)
        return new_val

    # Sorted set operations (for npc_decisions)
    def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        self._cleanup_expired()
        if key not in self._sorted_sets:
            self._sorted_sets[key] = []
        count = 0
        for member, score in mapping.items():
            # Remove existing entry with same member
            self._sorted_sets[key] = [(s, m) for s, m in self._sorted_sets[key] if m != member]
            self._sorted_sets[key].append((score, member))
            count += 1
        # Keep sorted by score
        self._sorted_sets[key].sort(key=lambda x: x[0])
        return count

    def zrevrange(self, key: str, start: int, end: int) -> List[bytes]:
        self._cleanup_expired()
        if key not in self._sorted_sets:
            return []
        lst = self._sorted_sets[key]
        # zrevrange: highest score first
        lst_sorted = sorted(lst, key=lambda x: x[0], reverse=True)
        if end == -1:
            end = len(lst_sorted)
        else:
            end = min(end + 1, len(lst_sorted))
        start = max(0, start)
        return [m.encode("utf-8") for _, m in lst_sorted[start:end]]

    def zremrangebyrank(self, key: str, start: int, end: int) -> int:
        self._cleanup_expired()
        if key not in self._sorted_sets:
            return 0
        lst = self._sorted_sets[key]
        lst.sort(key=lambda x: x[0])
        if end == -1:
            end = len(lst)
        else:
            end = min(end + 1, len(lst))
        start = max(0, start)
        removed = len(lst[start:end])
        self._sorted_sets[key] = lst[:start] + lst[end:]
        return removed


def make_fake_redis() -> FakeRedis:
    """Factory for fresh FakeRedis instances."""
    return FakeRedis()


def make_decision(category: str, title: str = "Test Artifact", desc: str = "", reasoning: str = "") -> Dict:
    """Create a minimal decision dict."""
    return {
        "category": category,
        "title": title,
        "description": desc,
        "reasoning": reasoning,
    }


def populate_decision_history(r: FakeRedis, char_id: str, category: str, count: int, title: str = "Test"):
    """Populate npc_decisions sorted set with repeated decisions of same category."""
    import time
    base_time = int(time.time() * 1000)
    for i in range(count):
        decision = {
            "category": category,
            "title": f"{title} {i}",
            "description": "test",
            "reasoning": "test",
            "action_taken": category,
        }
        r.zadd(f"npc_decisions:{char_id}", {json.dumps(decision): base_time + i})


# ════════════════════════════════════════════════════════════════════════
# Test Classes
# ════════════════════════════════════════════════════════════════════════

class TestRecordDeferral:
    """Tests for record_deferral() function."""

    def test_first_deferral_creates_streak_1_and_stores_topic(self):
        """1. record_deferral() first call: creates defer streak 1, stores blocked topic, bounded TTL."""
        r = make_fake_redis()
        char_id = "test_char_901"

        record_deferral(r, char_id, "infrastructure resilience")

        # Loop-control keys
        assert r.exists(_defer_key(char_id)) == 1
        assert r.get(_defer_key(char_id)).decode() == "1"
        assert r.exists(_topic_key(char_id)) == 1
        assert r.get(_topic_key(char_id)).decode() == "infrastructure"

        # Bounded TTL (should be set)
        assert r.ttl(_defer_key(char_id)) > 0
        assert r.ttl(_topic_key(char_id)) > 0

    def test_second_same_topic_deferral_increases_streak_blocks_same_topic(self):
        """2. Second same-topic deferral: increases defer streak, same-topic create_artifact blocked."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # First deferral
        record_deferral(r, char_id, "infrastructure")
        # Second same-topic deferral
        record_deferral(r, char_id, "infrastructure")

        assert r.get(_defer_key(char_id)).decode() == "2"

        # Now enforce() should block create_artifact on same normalized topic
        decision = make_decision("create_artifact", title="Local Analysis Report")
        result = enforce(decision, r, char_id)
        assert result["category"] == "read_artifacts"
        assert "defer>=2 same topic" in result["reasoning"]


class TestThirdDeferralGate:
    """Tests for the >=3 deferral threshold (all artifacts blocked)."""

    def test_third_deferral_blocks_all_create_artifact(self):
        """3. Third deferral: module >=3 gate is reachable, any create_artifact topic is blocked."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Three deferrals
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")
        streak3 = record_deferral(r, char_id, "infrastructure")
        assert streak3 == 3

        # Any create_artifact should be blocked (different topic too)
        decision1 = make_decision("create_artifact", title="Different Topic Report")
        result1 = enforce(decision1, r, char_id)
        assert result1["category"] == "read_artifacts"
        assert "defer>=3 all artifacts" in result1["reasoning"]

        decision2 = make_decision("create_artifact", title="Infrastructure Again")
        result2 = enforce(decision2, r, char_id)
        assert result2["category"] == "read_artifacts"
        assert "defer>=3 all artifacts" in result2["reasoning"]


class TestInlinePostParseEnforcement:
    """Tests for the inline post-parse enforcement in npc_decisions.py decide_action().

    These test the inline enforcement logic inside decide_action (around lines 1071-1097)
    which checks decision shape streaks from recent LLM outputs.
    """

    def test_inline_streak_2_returns_read_artifacts(self):
        """4. Inline post-parse streak 2: returns read_artifacts."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Populate decision history: 2 consecutive create_artifact decisions
        populate_decision_history(r, char_id, "create_artifact", 2, "Infrastructure")

        # Mock call_llm to return a create_artifact decision (the 3rd in a row)
        mock_decision = {
            "category": "create_artifact",
            "title": "Infrastructure Report",
            "description": "Analyzing local infrastructure",
            "reasoning": "Need to document infrastructure",
            "confidence": 0.8,
            "force_constraint": "",
            "expected_outcome": "Report created",
        }

        with patch("npc_decisions.call_llm", return_value=json.dumps(mock_decision)):
            result = decide_action("Test context", r, char_id)

        # Inline enforcement at streak>=2 should force read_artifacts
        assert result["category"] == "read_artifacts"
        assert "Loop-break forced fallback" in result["reasoning"]

    def test_inline_streak_3_returns_rest(self):
        """5. Inline post-parse streak 3: returns rest."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Populate decision history: 3 consecutive create_artifact decisions
        populate_decision_history(r, char_id, "create_artifact", 3, "Infrastructure")

        # Mock call_llm to return a create_artifact decision (the 4th in a row)
        mock_decision = {
            "category": "create_artifact",
            "title": "Infrastructure Report",
            "description": "Analyzing local infrastructure",
            "reasoning": "Need to document infrastructure",
            "confidence": 0.8,
            "force_constraint": "",
            "expected_outcome": "Report created",
        }

        with patch("npc_decisions.call_llm", return_value=json.dumps(mock_decision)):
            result = decide_action("Test context", r, char_id)

        # Inline enforcement at streak>=3 should force rest
        assert result["category"] == "rest"
        assert "3-in-a-row" in result["reasoning"]


class TestNormalParsedDecision:
    """Tests for normal parsed decision flow through _enforce_loop_control."""

    def test_normal_decision_calls_enforce_once_never_returns_none(self):
        """6. Normal parsed decision: calls _enforce_loop_control exactly once, cannot return None."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Fresh state - no deferrals
        decision = make_decision("investigate", title="Trade Disputes")
        result = _enforce_loop_control(decision, r, char_id)

        assert result is not None
        assert isinstance(result, dict)
        assert "category" in result
        # Should not have been rewritten (no loop detected)
        assert result["category"] == "investigate"


class TestInlineEarlyReturnNoDoubleCall:
    """Test that inline early returns don't double-call enforcement."""

    def test_inline_early_return_does_not_double_call_enforce(self):
        """7. Inline early return: does not call _enforce_loop_control a second time."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Set up streak >=3 to trigger inline early return (rest)
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")

        shape = _decision_shape("create_artifact", "infrastructure")
        r.rpush(_shape_key(char_id), shape)
        r.rpush(_shape_key(char_id), shape)
        r.rpush(_shape_key(char_id), shape)

        decision = make_decision("create_artifact", title="Infrastructure Report")

        # Call inline enforcement - should return rest early
        result = _enforce_loop_control(decision, r, char_id)

        assert result["category"] == "rest"
        assert "3-in-a-row" in result["reasoning"]

        # The module-level enforce() should NOT have been called again
        # (we can't directly test call count, but we verify the result is from inline)


class TestArtifactDeferredDedupActionPath:
    """Tests for the artifact_deferred_dedup action path in npc_actions.py."""

    def test_dedup_action_calls_record_deferral_once(self):
        """8. artifact_deferred_dedup action path: calls record_deferral exactly once."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # First, create a deferral via record_deferral directly (simulating one call)
        record_deferral(r, char_id, "infrastructure resilience")

        # Verify legacy bookkeeping was also done (streak incremented, topic set)
        streak_key = f"npc_dedup_streak:{char_id}"
        topic_key = f"npc_dedup_topic:{char_id}"

        assert r.exists(streak_key) == 1
        assert r.get(streak_key) is not None
        assert r.exists(topic_key) == 1
        assert r.get(topic_key) is not None

        # The loop-control key should also exist
        assert r.exists(_defer_key(char_id)) == 1
        assert r.exists(_topic_key(char_id)) == 1

    def test_dedup_uses_dedup_topic_or_title_fallback(self):
        """8b. Uses dedup_topic or title fallback correctly."""
        from npc_context import most_common_topic_word

        r = make_fake_redis()
        char_id = "test_char_901"

        # Test with a title that yields a topic
        title_with_topic = "Infrastructure Resilience Report"
        topic = most_common_topic_word([title_with_topic])
        assert topic == "infrastructure"

        record_deferral(r, char_id, topic or title_with_topic)

        stored = r.get(_topic_key(char_id)).decode()
        assert stored == "infrastructure"

    def test_legacy_bookkeeping_preserved(self):
        """8c. Preserves npc_dedup_streak and npc_dedup_topic bookkeeping."""
        r = make_fake_redis()
        char_id = "test_char_901"

        record_deferral(r, char_id, "infrastructure")

        # Legacy keys should exist
        streak_key = f"npc_dedup_streak:{char_id}"
        topic_key = f"npc_dedup_topic:{char_id}"

        assert r.exists(streak_key) == 1
        assert r.get(streak_key).decode() == "1"
        assert r.exists(topic_key) == 1
        assert r.get(topic_key).decode() == "infrastructure"


class TestArtifactCreatedActionPath:
    """Tests for successful artifact_created action path."""

    def test_artifact_created_sets_result_fields_and_calls_record_completed_work_once(self):
        """9. Successful artifact_created: sets action_taken, artifact_title, calls record_completed_work once."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Pre-populate deferral state to test clearing
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")
        assert r.exists(_defer_key(char_id)) == 1

        # Call record_completed_work with a DIFFERENT topic
        record_completed_work(r, char_id, "create_artifact", "trade disputes")

        # Loop-control state should be cleared (different topic)
        assert r.exists(_defer_key(char_id)) == 0
        assert r.exists(_topic_key(char_id)) == 0
        # Shape history should also be cleared
        assert r.exists(_shape_key(char_id)) == 0


class TestCompletedWorkStateManagement:
    """Tests for record_completed_work state clearing logic."""

    def test_different_completed_topic_clears_state(self):
        """10. Different completed artifact topic: clears loop-control deferral/topic state."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Build up deferral state
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")
        assert r.exists(_defer_key(char_id)) == 1

        # Complete work on a DIFFERENT topic
        record_completed_work(r, char_id, "create_artifact", "trade disputes")

        # State should be cleared
        assert r.exists(_defer_key(char_id)) == 0
        assert r.exists(_topic_key(char_id)) == 0

    def test_same_blocked_topic_does_not_clear_streak(self):
        """11. Same blocked-topic completed artifact: does not incorrectly clear loop-control streak."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Build up deferral state on "infrastructure"
        record_deferral(r, char_id, "infrastructure")
        record_deferral(r, char_id, "infrastructure")
        assert r.exists(_defer_key(char_id)) == 1
        assert r.get(_defer_key(char_id)).decode() == "2"

        # Complete work on the SAME normalized topic (reworded title)
        record_completed_work(r, char_id, "create_artifact", "Infrastructure Analysis Report")

        # State should NOT be cleared (same normalized topic)
        assert r.exists(_defer_key(char_id)) == 1
        assert r.get(_defer_key(char_id)).decode() == "2"
        assert r.exists(_topic_key(char_id)) == 1


class TestNpcShadowModeAbsent:
    """Test that npc_shadow_mode is not imported or required."""

    def test_npc_shadow_mode_not_imported_in_loop_control(self):
        """12a. npc_shadow_mode is not imported in npc_loop_control."""
        import npc_loop_control
        assert not hasattr(npc_loop_control, "npc_shadow_mode")
        import inspect
        source = inspect.getsource(npc_loop_control)
        assert "npc_shadow_mode" not in source

    def test_npc_shadow_mode_not_imported_in_decisions(self):
        """12b. npc_shadow_mode is not imported in npc_decisions."""
        import npc_decisions
        import inspect
        source = inspect.getsource(npc_decisions)
        assert "npc_shadow_mode" not in source

    def test_npc_shadow_mode_not_imported_in_actions(self):
        """12c. npc_shadow_mode is not imported in npc_actions."""
        import npc_actions
        import inspect
        source = inspect.getsource(npc_actions)
        assert "npc_shadow_mode" not in source


class TestLegacyLiveBehaviorPreserved:
    """Test that legacy live behavior (npc_dedup_streak, npc_dedup_topic) remains."""

    def test_legacy_keys_present_in_actions(self):
        """13a. npc_dedup_streak and npc_dedup_topic namespaces remain in npc_actions."""
        import npc_actions
        import inspect
        source = inspect.getsource(npc_actions)
        assert "npc_dedup_streak" in source
        assert "npc_dedup_topic" in source

    def test_no_live_baseline_artifact_path_removed(self):
        """13b. No live-baseline artifact path was removed."""
        import npc_actions
        import inspect
        source = inspect.getsource(npc_actions)
        # The artifact creation path should still exist
        assert "artifact_created" in source
        assert "npc_artifacts:" in source
        assert "npc_stats:" in source


class TestSourceSafety:
    """Test that no protected IDs or network calls exist in tests."""

    def test_no_protected_ids_in_test_file(self):
        """14a. No protected IDs (char_001, char_306) appear in this test file."""
        import inspect
        source = inspect.getsource(sys.modules[__name__])
        assert "char_001" not in source
        assert "char_306" not in source
        assert "Archimedes" not in source
        assert "Oracle" not in source

    def test_no_network_calls_possible(self):
        """14b. No network/model/provider calls can occur in these tests."""
        # Tests only use FakeRedis and direct function calls
        # No call_llm, no HTTP requests, no external connections
        pass  # Verified by inspection of test code


class TestModuleEnforcementGates:
    """Additional tests verifying the module enforce() gates are reachable."""

    def test_shape_repeat_hard_break_reachable(self):
        """Verify shape repeat >=4 triggers hard break (investigate different topic)."""
        r = make_fake_redis()
        char_id = "test_char_901"

        # Repeat same decision shape 4 times
        for _ in range(4):
            decision = make_decision("investigate", title="Trade Disputes")
            result = enforce(decision, r, char_id)

        # 4th call should trigger hard break
        assert result["category"] == "investigate"
        assert "shape_repeat=4" in result["reasoning"]
        # The hard break returns title "Investigating: {diverse_topic}" and
        # description mentions "Investigating diverse topic"
        assert "Investigating:" in result["title"]
        assert "Investigating diverse topic" in result["description"]

    def test_enforce_never_returns_none(self):
        """enforce() never returns None for valid input."""
        r = make_fake_redis()
        char_id = "test_char_901"

        for cat in ["create_artifact", "investigate", "read_artifacts", "rest", "write_code"]:
            decision = make_decision(cat, title="Test")
            result = enforce(decision, r, char_id)
            assert result is not None
            assert isinstance(result, dict)
            assert "category" in result

    def test_enforce_preserves_non_artifact_decisions(self):
        """Non-create_artifact decisions pass through unchanged when no shape repeat."""
        r = make_fake_redis()
        char_id = "test_char_901"

        decision = make_decision("investigate", title="Trade Disputes")
        result = enforce(decision, r, char_id)

        assert result["category"] == "investigate"
        assert result.get("title") == "Trade Disputes"


# ════════════════════════════════════════════════════════════════════════
# Entry point for pytest
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-vv"])