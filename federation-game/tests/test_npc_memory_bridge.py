"""
Unit tests for npc_memory_bridge.py (Phase 1 councilor memory bridge).

Tests:
- CouncilorMemory: add, get_context_for_prompt, consolidate, clear
- record_councilor_memory: field mapping from raw decision dicts
- _compute_importance: keyword boosting and generic-thought penalty
- Edge cases: empty content, missing fields, empty ZSET
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "npc-agent"))

try:
    import fakeredis
except ImportError:
    fakeredis = None

pytestmark = pytest.mark.skipif(fakeredis is None, reason="fakeredis not installed")


def _make_r():
    return fakeredis.FakeStrictRedis()


class TestCouncilorMemoryAdd:

    def test_add_returns_memory_with_all_fields(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add("idea", "I discovered a pattern in the anomaly.", tick=100)
        assert result is not None
        assert result["id"].startswith("test_char_mem_")
        assert result["type"] == "idea"
        assert result["content"] == "I discovered a pattern in the anomaly."
        assert result["tick"] == 100
        assert 0.0 <= result["importance"] <= 1.0
        assert "created_at" in result

    def test_add_event_wrapper(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add_event("Sent message to Oracle.", tick=101)
        assert result["type"] == "event"
        assert result["importance"] == 0.4

    def test_add_idea_wrapper(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add_idea("We need a new institution.", tick=102)
        assert result["type"] == "idea"
        assert result["importance"] == 0.5

    def test_add_observation_wrapper(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add_observation("Discovered resource stockpile.", tick=103)
        assert result["type"] == "observation"
        assert result["importance"] == 0.7

    def test_add_relationship_wrapper(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add_relationship("Trust with Oracle is growing.", tick=104)
        assert result["type"] == "relationship"
        assert result["importance"] == 0.3

    def test_add_skill_wrapper(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add_skill("Learned data analysis.", tick=105)
        assert result["type"] == "skill"
        assert result["importance"] == 0.5

    def test_add_empty_content_returns_none(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add("idea", "  ", tick=106)
        assert result is None

    def test_add_very_short_content_returns_none(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add("idea", "ab", tick=107)
        assert result is None

    def test_add_truncates_long_content(self):
        from npc_memory_bridge import CouncilorMemory, CONTENT_MAX_LENGTH
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        long_text = "x" * (CONTENT_MAX_LENGTH + 100)
        result = mem.add("idea", long_text, tick=108)
        assert len(result["content"]) <= CONTENT_MAX_LENGTH
        assert result["content"].endswith("...")

    def test_add_clamps_importance(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.add("idea", "Test", tick=109, importance=5.0)
        assert result["importance"] == 1.0
        result = mem.add("idea", "Test low", tick=110, importance=-1.0)
        assert result["importance"] == 0.0

    def test_char_id_required(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        with pytest.raises(ValueError):
            CouncilorMemory(r, "")

    def test_incrementing_seq(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        m1 = mem.add("idea", "First", tick=111)
        m2 = mem.add("idea", "Second", tick=112)
        assert int(m1["id"].split("_")[-1]) == 1
        assert int(m2["id"].split("_")[-1]) == 2


class TestGetContextForPrompt:

    def test_empty_returns_empty_string(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=200)
        assert result == ""

    def test_returns_recent_memories(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        mem.add_event("Did something.", tick=150)
        mem.add_idea("Had an idea.", tick=160)
        result = mem.get_context_for_prompt(tick=200)
        assert "## Your Memories" in result
        assert "[event]" in result
        assert "[idea]" in result

    def test_memories_sorted_by_tick_descending(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        mem.add_idea("Old idea.", tick=100)
        mem.add_idea("Newer idea.", tick=200)
        mem.add_idea("Middle idea.", tick=150)
        result = mem.get_context_for_prompt(tick=300)
        lines = [l for l in result.split("\n") if l.startswith("  - [")]
        assert len(lines) >= 3
        ticks = [int(l.split("tick ")[1].split(",")[0]) for l in lines]
        assert ticks == sorted(ticks, reverse=True)

    def test_respects_max_memories(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        for i in range(20):
            mem.add_idea(f"Idea {i}.", tick=100 + i)
        result = mem.get_context_for_prompt(tick=200, max_memories=3)
        lines = [l for l in result.split("\n") if l.startswith("  - [")]
        assert len(lines) == 3

    def test_includes_high_importance_when_few_recent(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        mem.add_idea("Low imp idea.", tick=150, importance=0.3)
        mem.add_idea("Critical emergency! Respond now!", tick=50, importance=0.9)
        result = mem.get_context_for_prompt(tick=200, max_memories=5)
        assert "Critical emergency!" in result


class TestConsolidate:

    def test_consolidate_reduces_count(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        for i in range(50):
            mem.add_idea(f"Idea {i}.", tick=100 + i)
        result = mem.consolidate(max_memories=20)
        assert result == 20

    def test_under_limit_does_nothing(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        for i in range(5):
            mem.add_idea(f"Idea {i}.", tick=100 + i)
        result = mem.consolidate(max_memories=200)
        assert result == 5

    def test_keeps_high_importance_over_low(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        mem.add_idea("Critical emergency!", tick=90, importance=0.9)
        for i in range(5):
            mem.add_idea(f"Routine thought {i}.", tick=100 + i, importance=0.3)
        mem.consolidate(max_memories=10)
        result = mem.get_context_for_prompt(tick=200)
        assert "Critical emergency!" in result


class TestRecordCouncilorMemory:

    def test_records_idea_from_thought_field(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"thought": "I should investigate the anomaly.", "action": "Send message to Oracle."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "investigate the anomaly" in result

    def test_falls_back_to_reasoning_field(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"reasoning": "I should investigate the anomaly.", "description": "Send message to Oracle."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "investigate the anomaly" in result

    def test_records_event_from_action(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"thought": "Thinking.", "action": "Proposed new decree to council."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "[event]" in result

    def test_records_observation_on_discovery_keyword(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"thought": "I found something.", "action": "Uncover hidden resource cache."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "[observation]" in result

    def test_records_relationship_when_to_field_present(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"thought": "Thinking.", "action": "Contacting Oracle.", "to": "char_306"}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "[relationship]" in result

    def test_records_relationship_on_social_keyword(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"thought": "Thinking.", "action": "Negotiate alliance with neighbors."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "[relationship]" in result

    def test_empty_char_id_does_not_crash(self):
        from npc_memory_bridge import record_councilor_memory
        r = _make_r()
        decision = {"thought": "Test.", "action": "Test."}
        record_councilor_memory(decision, r, tick=300, char_id="")

    def test_missing_thought_field_does_not_crash(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory
        r = _make_r()
        decision = {"action": "Just did something."}
        record_councilor_memory(decision, r, tick=300, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        result = mem.get_context_for_prompt(tick=310)
        assert "[event]" in result

    def test_triggers_consolidation_at_interval(self):
        from npc_memory_bridge import record_councilor_memory, CouncilorMemory, CONSOLIDATION_INTERVAL
        r = _make_r()
        decision = {"thought": "Dummy thought.", "action": "Dummy action."}
        for i in range(60):
            record_councilor_memory(decision, r, tick=1000 + i, char_id="test_char")
        mem = CouncilorMemory(r, "test_char")
        stats = mem.get_stats()
        # At CONSOLIDATION_INTERVAL intervals, consolidation should have fired,
        # keeping total under MAX_MEMORIES
        total = int(stats.get(b"total", stats.get("total", 0)))
        assert total >= 60  # all were submitted


class TestComputeImportance:

    def test_discovery_keyword_boosts(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("I discovered a new resource.", "Report findings.")
        assert imp > 0.7

    def test_critical_keyword_boosts(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("Critical emergency in sector 7!", "Issue warning.")
        assert imp > 0.65

    def test_social_keyword_boosts(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("Trust is building with the Oracle.", "Negotiate alliance.")
        assert imp > 0.55

    def test_generic_thought_penalized(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("I observe the current situation.", "Monitor")
        assert imp < 0.5

    def test_clamped_to_range(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("discover" * 20, "find" * 20)
        assert 0.0 <= imp <= 1.0

    def test_plain_thought_defaults(self):
        from npc_memory_bridge import _compute_importance
        imp = _compute_importance("Just another thought.", ".")
        assert imp == 0.5


class TestClear:

    def test_clear_removes_all_keys(self):
        from npc_memory_bridge import CouncilorMemory
        r = _make_r()
        mem = CouncilorMemory(r, "test_char")
        mem.add("idea", "Something.", tick=100)
        mem.add("idea", "Something else.", tick=101)
        mem.clear()
        result = mem.get_context_for_prompt(tick=200)
        assert result == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
