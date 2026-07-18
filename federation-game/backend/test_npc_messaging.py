"""Tests for npc_messaging: bool-safe send and inbox reconciliation.

Run from the backend dir:
    python -m pytest test_npc_messaging.py -q

Uses an in-memory fake Redis only. No live Redis access.
"""
import pytest


class _FakeRedis:
    """Minimal in-memory redis stub covering only the ops npc_messaging uses."""

    def __init__(self):
        self.hashes = {}
        self.zsets = {}
        self.ttls = {}
        # When set, the next hgetall/zrange/zrem call raises this. Allows
        # simulating a Redis error mid-reconciliation.
        self.next_error = None

    def _maybe_fail(self):
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err

    # --- hash ops ---
    def hset(self, key, field=None, value=None, mapping=None, **kwargs):
        # Support both hset(key, mapping=...) and hset(key, field, value).
        payload = {}
        if mapping:
            payload.update(mapping)
        if field is not None:
            payload[field] = value
        payload.update(kwargs)
        # redis-py rejects bool values; emulate that strictly.
        for v in payload.values():
            if isinstance(v, bool):
                raise Exception(
                    "DataError Invalid input of type: 'bool'. "
                    "Convert to a bytes, string, int or float first."
                )
        self.hashes.setdefault(key, {}).update(payload)

    def hgetall(self, key):
        self._maybe_fail()
        return dict(self.hashes.get(key, {}))

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    # --- sorted set ops ---
    def zadd(self, key, mapping=None, **kwargs):
        z = self.zsets.setdefault(key, {})
        items = dict(mapping or {})
        items.update(kwargs)
        for member, score in items.items():
            z[member] = score
        return len(items)

    def zremrangebyrank(self, key, start, stop):
        z = self.zsets.get(key, {})
        ranks = sorted(z.items(), key=lambda kv: kv[1])
        if stop < 0:
            stop = len(ranks) + stop
        to_drop = [m for i, (m, _) in enumerate(ranks) if start <= i <= stop]
        for m in to_drop:
            z.pop(m, None)
        return len(to_drop)

    def zrevrange(self, key, start, stop):
        self._maybe_fail()
        z = self.zsets.get(key, {})
        ranks = sorted(z.items(), key=lambda kv: kv[1], reverse=True)
        if stop < 0:
            stop = len(ranks) + stop
        return [m for m, _ in ranks[start:stop + 1]]

    def zrange(self, key, start, stop):
        self._maybe_fail()
        z = self.zsets.get(key, {})
        ranks = sorted(z.items(), key=lambda kv: kv[1])
        if stop < 0:
            stop = len(ranks) + stop
        return [m for m, _ in ranks[start:stop + 1]]

    def zrem(self, key, *members):
        self._maybe_fail()
        z = self.zsets.get(key, {})
        removed = 0
        for m in members:
            if z.pop(m, None) is not None:
                removed += 1
        return removed

    def exists(self, key):
        return 1 if (key in self.hashes or key in self.zsets) else 0

    # test helper: drop a payload to simulate TTL expiry
    def _expire_payload(self, msg_id):
        self.hashes.pop(f"msg:{msg_id}", None)


@pytest.fixture
def fake_redis(monkeypatch):
    fr = _FakeRedis()
    import npc_messaging as nm

    nm._redis_client = fr
    monkeypatch.setattr(nm, "_get_redis", lambda: fr)
    return fr


# 1. send_message writes "read": "false" as a string (no bool DataError).
def test_send_message_read_is_string(fake_redis):
    import npc_messaging as nm

    msg = nm.send_message(
        from_char_id="char_001", from_char_name="Archimedes",
        to_char_id="char_306", subject="hello", body="world",
    )
    stored = fake_redis.hashes[f"msg:{msg['id']}"]
    assert stored["read"] == "false"
    assert isinstance(stored["read"], str)


# 2. send_message creates canonical payload hash + inbox ZSET member.
def test_send_message_creates_payload_and_inbox_member(fake_redis):
    import npc_messaging as nm

    msg = nm.send_message(
        from_char_id="char_001", from_char_name="Archimedes",
        to_char_id="char_306", subject="hello", body="world",
    )
    assert fake_redis.hashes.get(f"msg:{msg['id']}") is not None
    assert msg["id"] in fake_redis.zsets.get("msg:inbox:char_306", {})


# 3. get_inbox removes a dangling member.
def test_get_inbox_prunes_dangling_member(fake_redis):
    import npc_messaging as nm

    fake_redis.zadd("msg:inbox:char_306", {"msg_ghost": 100.0})
    fake_redis.hset("msg:msg_real", mapping={"id": "msg_real", "subject": "s", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_real": 200.0})

    msgs = nm.get_inbox("char_306", limit=20)
    assert len(msgs) == 1
    assert msgs[0]["id"] == "msg_real"
    assert "msg_ghost" not in fake_redis.zsets["msg:inbox:char_306"]
    assert "msg_real" in fake_redis.zsets["msg:inbox:char_306"]


# 4. get_inbox preserves valid members and ordering (newest first).
def test_get_inbox_preserves_ordering(fake_redis):
    import npc_messaging as nm

    fake_redis.hset("msg:msg_old", mapping={"id": "msg_old", "subject": "o", "body": "b", "read": "false"})
    fake_redis.hset("msg:msg_new", mapping={"id": "msg_new", "subject": "n", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_old": 100.0, "msg_new": 200.0})

    msgs = nm.get_inbox("char_306", limit=20)
    assert [m["id"] for m in msgs] == ["msg_new", "msg_old"]


# 5. get_inbox marks returned messages read (string "true").
def test_get_inbox_marks_read(fake_redis):
    import npc_messaging as nm

    fake_redis.hset("msg:msg_real", mapping={"id": "msg_real", "subject": "s", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_real": 200.0})

    msgs = nm.get_inbox("char_306", limit=20)
    # returned dict marks read as Python True
    assert msgs[0]["read"] is True
    # persisted Redis value is the string "true"
    assert fake_redis.hashes["msg:msg_real"]["read"] == "true"


# 6. get_unread_count ignores and removes dangling members.
def test_get_unread_count_ignores_dangling(fake_redis):
    import npc_messaging as nm

    fake_redis.zadd("msg:inbox:char_306", {"msg_ghost": 100.0})
    fake_redis.hset("msg:msg_real", mapping={"id": "msg_real", "subject": "s", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_real": 200.0})

    assert nm.get_unread_count("char_306") == 1
    # dangling member pruned by the count path
    assert "msg_ghost" not in fake_redis.zsets["msg:inbox:char_306"]


# 7. get_unread_count counts valid members correctly (read vs unread).
def test_get_unread_count_counts_valid(fake_redis):
    import npc_messaging as nm

    fake_redis.hset("msg:msg_a", mapping={"id": "msg_a", "subject": "a", "body": "b", "read": "false"})
    fake_redis.hset("msg:msg_b", mapping={"id": "msg_b", "subject": "b", "body": "b", "read": "true"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_a": 100.0, "msg_b": 200.0})

    assert nm.get_unread_count("char_306") == 1


# 8. reconcile_inbox returns exact removal count.
def test_reconcile_inbox_returns_removed_count(fake_redis):
    import npc_messaging as nm

    fake_redis.zadd("msg:inbox:char_001", {"msg_dangling_a": 1.0})
    fake_redis.zadd("msg:inbox:char_001", {"msg_dangling_b": 2.0})
    removed = nm.reconcile_inbox(fake_redis, "char_001")
    assert removed == 2
    assert fake_redis.zsets.get("msg:inbox:char_001", {}) == {}


# 9. reconcile_inbox is idempotent.
def test_reconcile_inbox_idempotent(fake_redis):
    import npc_messaging as nm

    fake_redis.zadd("msg:inbox:char_001", {"msg_dangling_a": 1.0})
    fake_redis.zadd("msg:inbox:char_001", {"msg_dangling_b": 2.0})
    assert nm.reconcile_inbox(fake_redis, "char_001") == 2
    # second pass: nothing left to remove
    assert nm.reconcile_inbox(fake_redis, "char_001") == 0
    assert fake_redis.zsets.get("msg:inbox:char_001", {}) == {}


# 10. empty inbox returns zero removals.
def test_reconcile_inbox_empty_inbox(fake_redis):
    import npc_messaging as nm

    assert nm.reconcile_inbox(fake_redis, "char_999") == 0


# 11. No payload hash is deleted by reconciliation.
def test_reconcile_does_not_delete_payloads(fake_redis):
    import npc_messaging as nm

    fake_redis.hset("msg:msg_keep", mapping={"id": "msg_keep", "subject": "s", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_keep": 100.0, "msg_ghost": 50.0})

    nm.reconcile_inbox(fake_redis, "char_306")
    # keeper payload still present
    assert "msg:msg_keep" in fake_redis.hashes
    assert fake_redis.hashes["msg:msg_keep"]["id"] == "msg_keep"
    # only the ghost zset member removed
    assert "msg_ghost" not in fake_redis.zsets["msg:inbox:char_306"]
    assert "msg_keep" in fake_redis.zsets["msg:inbox:char_306"]


# 12. Redis error during reconciliation is reported as failure, not silent success.
def test_reconcile_reports_redis_error(fake_redis):
    import npc_messaging as nm

    fake_redis.zadd("msg:inbox:char_001", {"msg_dangling_a": 1.0})
    # Force zrange (used inside reconcile) to raise once.
    fake_redis.next_error = RuntimeError("redis down")

    removed = nm.reconcile_inbox(fake_redis, "char_001")
    # error path returns 0 (not a successful cleanup) and leaves member intact
    assert removed == 0
    assert "msg_dangling_a" in fake_redis.zsets["msg:inbox:char_001"]


# Extra: payload expiring between reconcile and retrieval is tolerated by get_inbox.
def test_get_inbox_tolerates_payload_expiry_mid_read(fake_redis):
    import npc_messaging as nm

    fake_redis.hset("msg:msg_real", mapping={"id": "msg_real", "subject": "s", "body": "b", "read": "false"})
    fake_redis.zadd("msg:inbox:char_306", {"msg_real": 200.0})

    msgs = nm.get_inbox("char_306", limit=20)
    assert len(msgs) == 1  # present on first read

    # simulate the payload expiring before a later read
    fake_redis._expire_payload("msg_real")
    msgs2 = nm.get_inbox("char_306", limit=20)
    assert msgs2 == []  # now pruned, no crash
    assert "msg_real" not in fake_redis.zsets["msg:inbox:char_306"]
