"""Narrow static/isolated tests for NPC agent placeholder-rejection and
duplicate-prevention logic.

These tests do NOT touch Redis or any runtime service. They exercise the
pure-Python helper functions in npc_actions.py with a FakeRedis stub.
"""
import importlib.util
import os
import sys
import time
import types

# Stub out redis so import of npc_actions does not require a live Redis server.
class _DummyRedis:
    @staticmethod
    def from_url(*a, **k):
        return None
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=_DummyRedis))
sys.modules.setdefault("httpx", types.SimpleNamespace(
    Client=object, TimeoutException=Exception,
    RequestError=Exception, HTTPStatusError=Exception))

MODULE_PATH = os.path.join(os.path.dirname(__file__), "npc_actions.py")
spec = importlib.util.spec_from_file_location("npc_actions_under_test", MODULE_PATH)
npc_actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npc_actions)


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}
        self.strings = {}
        self.expiries = {}
        self.counters = {}

    def _now(self):
        return time.time()

    def _purge(self, key):
        exp = self.expiries.get(key)
        if exp is not None and exp <= self._now():
            self.expiries.pop(key, None)
            self.strings.pop(key, None)
            self.counters.pop(key, None)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def lrange(self, key, start, end):
        items = list(self.lists.get(key, []))
        return items

    def rpush(self, key, *values):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].extend(values)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(len(items) + start, 0)
        if end < 0:
            end = max(len(items) + end + 1, 0)
        self.lists[key] = items[start:end] if start < len(items) else []

    def expire(self, key, seconds):
        self.expiries[key] = self._now() + seconds
        return True

    def rpop(self, key):
        items = self.lists.get(key, [])
        if items:
            return items.pop()
        return None

    def hincrby(self, key, field, amount):
        if key not in self.hashes:
            self.hashes[key] = {}
        self.hashes[key][field] = str(int(self.hashes[key].get(field, 0)) + amount)
        return self.hashes[key][field]


class TestPlaceholderRejection:
    """Validate that _is_placeholder_reply correctly detects template text."""

    def test_angle_bracket_template_is_placeholder(self):
        assert npc_actions._is_placeholder_reply("<your full reply to the moderator>")

    def test_angle_bracket_full_reply(self):
        assert npc_actions._is_placeholder_reply("<full reply>")

    def test_report_content(self):
        assert npc_actions._is_placeholder_reply("Report content...")

    def test_empty_string(self):
        assert npc_actions._is_placeholder_reply("")

    def test_whitespace_only(self):
        assert npc_actions._is_placeholder_reply("   ")

    def test_short_generic_claim(self):
        assert npc_actions._is_placeholder_reply("Done.")

    def test_substantive_reply_is_not_placeholder(self):
        assert not npc_actions._is_placeholder_reply(
            "The signal patterns suggest a lattice-based resonance in the outer rim."
        )

    def test_long_substantive_not_flagged(self):
        long_body = " ".join(["word"] * 20)
        assert not npc_actions._is_placeholder_reply(long_body)


class TestDuplicatePrevention:
    """Validate that _is_duplicate_reply rejects recent identical bodies,
    namespaced by sender and target."""

    def test_no_recent_messages_is_not_duplicate(self):
        r = FakeRedis()
        old = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            assert not npc_actions._is_duplicate_reply(r, "moderator", "Hello there")
        finally:
            npc_actions.CHAR_ID = old

    def test_identical_recent_body_is_duplicate(self):
        r = FakeRedis()
        old = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            r.rpush("npc_messages:char_001:moderator:sent_recently",
                   '{"body": "Hello there", "ts": %d}' % int(time.time()))
            assert npc_actions._is_duplicate_reply(r, "moderator", "Hello there")
        finally:
            npc_actions.CHAR_ID = old

    def test_different_body_is_not_duplicate(self):
        r = FakeRedis()
        old = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            r.rpush("npc_messages:char_001:moderator:sent_recently",
                   '{"body": "Hello there", "ts": %d}' % int(time.time()))
            assert not npc_actions._is_duplicate_reply(r, "moderator", "Goodbye now")
        finally:
            npc_actions.CHAR_ID = old

    def test_expired_timestamp_is_not_duplicate(self):
        r = FakeRedis()
        old = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            old_ts = int(time.time()) - 9999
            r.rpush("npc_messages:char_001:moderator:sent_recently",
                   '{"body": "Hello there", "ts": %d}' % old_ts)
            assert not npc_actions._is_duplicate_reply(r, "moderator", "Hello there")
        finally:
            npc_actions.CHAR_ID = old

    def test_sender_isolation(self):
        """Identical body from a different sender is not a duplicate."""
        r = FakeRedis()
        old = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            r.rpush("npc_messages:char_001:moderator:sent_recently",
                   '{"body": "Same message", "ts": %d}' % int(time.time()))
            npc_actions.CHAR_ID = "char_306"
            assert not npc_actions._is_duplicate_reply(r, "moderator", "Same message")
        finally:
            npc_actions.CHAR_ID = old


class TestExecuteDecisionRejection:
    """Validate that execute_decision rejects placeholder and duplicate replies
    before they enter the moderator inbox."""

    def test_placeholder_reply_rejected(self):
        r = FakeRedis()
        old_char_id = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            npc_actions.PAIR_IDS = {"char_001", "char_306"}
            decision = {"category": "send_message", "target": "moderator",
                        "body": "<your full reply to the moderator>"}
            result = npc_actions.execute_decision(decision, r, {"moderator": "moderator"})
            assert result["action_taken"] == "message_skipped_placeholder"
            assert not r.lrange("npc_messages:moderator:inbox", 0, -1)
        finally:
            npc_actions.CHAR_ID = old_char_id

    def test_duplicate_reply_rejected(self):
        r = FakeRedis()
        old_char_id = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            npc_actions.PAIR_IDS = {"char_001", "char_306"}
            body = "Unique substantive reply about sensor anomalies."
            npc_actions._record_sent_reply(r, "moderator", body, int(time.time()))
            decision = {"category": "send_message", "target": "moderator", "body": body}
            result = npc_actions.execute_decision(decision, r, {"moderator": "moderator"})
            assert result["action_taken"] == "message_skipped_duplicate"
            assert not r.lrange("npc_messages:moderator:inbox", 0, -1)
        finally:
            npc_actions.CHAR_ID = old_char_id

    def test_valid_reply_persisted(self):
        r = FakeRedis()
        old_char_id = npc_actions.CHAR_ID
        try:
            npc_actions.CHAR_ID = "char_001"
            npc_actions.PAIR_IDS = {"char_001", "char_306"}
            decision = {"category": "send_message", "target": "moderator",
                        "body": "Substantive reply with real content about the case."}
            result = npc_actions.execute_decision(decision, r, {"moderator": "moderator"})
            assert result["action_taken"] == "message_sent"
            inbox = r.lrange("npc_messages:moderator:inbox", 0, -1)
            assert len(inbox) == 1
        finally:
            npc_actions.CHAR_ID = old_char_id


if __name__ == "__main__":
    t = TestPlaceholderRejection()
    t.test_angle_bracket_template_is_placeholder()
    t.test_angle_bracket_full_reply()
    t.test_report_content()
    t.test_empty_string()
    t.test_whitespace_only()
    t.test_short_generic_claim()
    t.test_substantive_reply_is_not_placeholder()
    t.test_long_substantive_not_flagged()
    d = TestDuplicatePrevention()
    d.test_no_recent_messages_is_not_duplicate()
    d.test_identical_recent_body_is_duplicate()
    d.test_different_body_is_not_duplicate()
    d.test_expired_timestamp_is_not_duplicate()
    e = TestExecuteDecisionRejection()
    e.test_placeholder_reply_rejected()
    e.test_duplicate_reply_rejected()
    e.test_valid_reply_persisted()
    print("All placeholder/duplicate tests passed.")
