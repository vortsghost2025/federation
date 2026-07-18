"""Tests for the relationship-lifetime migration helper.

Uses an in-memory fake Redis with cursor-based scan pagination. No live
Redis connection is made.
"""

import copy

import relationship_migration as rm


class FakeScanRedis:
    """Minimal Redis fake supporting cursor-based scan_iter and persist.

    Keys are stored so ``scan_iter`` can return them across multiple pages,
    modelling real Redis MATCH + COUNT pagination. ``persist`` returns a
    configurable result code (1 = TTL removed, 0 = already permanent/absent)
    and can be made to raise.
    """

    def __init__(self, keys=None, page_size=2, persist_result=1,
                 persist_raises=None, scan_raises=None, values=None):
        # Preserve supplied key types (bytes and/or str) so mixed-type
        # coverage is genuine. redis-py yields bytes by default, but a caller
        # may also yield str; the helper must normalize both.
        self._keys = list(keys or [])
        self._page_size = page_size
        # Actual relationship-value mapping owned by the fake. The helper must
        # never read or write it.
        self.values = values or {}
        self._persist_result = persist_result
        self._persist_raises = persist_raises
        self._scan_raises = scan_raises
        self.persisted = []

    def scan_iter(self, match=None):
        if self._scan_raises is not None:
            raise self._scan_raises
        import fnmatch
        matched = []
        for k in self._keys:
            name = k.decode() if isinstance(k, bytes) else k
            if fnmatch.fnmatchcase(name, match or "*"):
                matched.append(k)
        for i in range(0, len(matched), self._page_size):
            yield from matched[i:i + self._page_size]

    def persist(self, name):
        if self._persist_raises is not None:
            raise self._persist_raises
        self.persisted.append(name)
        return self._persist_result


def test_empty_database():
    r = FakeScanRedis([])
    assert rm.persist_relationship_keys(r) == 0
    assert r.persisted == []


def test_only_relationship_keys_touched():
    r = FakeScanRedis([
        "npc_relationships:char_A",
        "npc_relationships:char_B",
        "npc_traits:char_A",
        "world_state",
    ])
    count = rm.persist_relationship_keys(r)
    assert count == 2
    assert set(r.persisted) == {"npc_relationships:char_A", "npc_relationships:char_B"}


def test_multiple_scan_pages():
    keys = [f"npc_relationships:npc_{i}" for i in range(7)]
    r = FakeScanRedis(keys, page_size=2)
    count = rm.persist_relationship_keys(r)
    assert count == 7
    assert len(r.persisted) == 7


def test_keys_with_and_without_ttl():
    # Helper does not inspect TTL; it persists every matched key.
    r = FakeScanRedis([
        "npc_relationships:char_A",
        "npc_relationships:char_B",
    ])
    count = rm.persist_relationship_keys(r)
    assert count == 2
    assert r.persisted == ["npc_relationships:char_A", "npc_relationships:char_B"]


def test_deterministic_count():
    keys = ["npc_relationships:x", "npc_relationships:y", "npc_relationships:z"]
    a = rm.persist_relationship_keys(FakeScanRedis(keys))
    b = rm.persist_relationship_keys(FakeScanRedis(keys))
    assert a == b == 3


def test_duplicate_byte_keys_persisted_once():
    r = FakeScanRedis([
        b"npc_relationships:dup",
        b"npc_relationships:dup",
    ])
    count = rm.persist_relationship_keys(r)
    assert count == 1
    assert r.persisted == ["npc_relationships:dup"]


def test_bytes_and_str_same_logical_key_persisted_once():
    # Genuine mixed types: one bytes key, one str key, same logical key.
    r = FakeScanRedis([
        b"npc_relationships:mixed",
        "npc_relationships:mixed",
    ])
    # Prove the fake actually yields distinct Python types.
    yielded = list(r.scan_iter(match="npc_relationships:*"))
    types = [type(k).__name__ for k in yielded]
    assert "bytes" in types and "str" in types, types
    assert len(yielded) == 2
    count = rm.persist_relationship_keys(r)
    assert count == 1
    assert r.persisted == ["npc_relationships:mixed"]


def test_two_different_keys_both_persisted():
    r = FakeScanRedis([
        "npc_relationships:A",
        "npc_relationships:B",
    ])
    count = rm.persist_relationship_keys(r)
    assert count == 2
    assert set(r.persisted) == {"npc_relationships:A", "npc_relationships:B"}


def test_already_permanent_not_counted():
    r = FakeScanRedis(["npc_relationships:A", "npc_relationships:B"],
                      persist_result=0)
    count = rm.persist_relationship_keys(r)
    assert count == 0
    assert len(r.persisted) == 2


def test_vanished_key_returns_zero_not_counted():
    r = FakeScanRedis(["npc_relationships:ghost"], persist_result=0)
    count = rm.persist_relationship_keys(r)
    assert count == 0
    assert r.persisted == ["npc_relationships:ghost"]


def test_mixed_persist_results_exact_count():
    class MixedRedis(FakeScanRedis):
        def persist(self, name):
            self.persisted.append(name)
            return 1 if name == "npc_relationships:A" else 0

    r = MixedRedis(["npc_relationships:A", "npc_relationships:B"])
    count = rm.persist_relationship_keys(r)
    assert count == 1
    assert set(r.persisted) == {"npc_relationships:A", "npc_relationships:B"}


def test_persist_exception_propagates():
    r = FakeScanRedis(["npc_relationships:A"],
                      persist_raises=RuntimeError("redis down"))
    try:
        rm.persist_relationship_keys(r)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_scan_exception_propagates():
    r = FakeScanRedis(["npc_relationships:A"],
                      scan_raises=RuntimeError("scan failed"))
    try:
        rm.persist_relationship_keys(r)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_unsupported_key_type_raises_typeerror():
    class BadKeyRedis(FakeScanRedis):
        def scan_iter(self, match=None):
            yield 12345

    r = BadKeyRedis(["npc_relationships:A"])
    try:
        rm.persist_relationship_keys(r)
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_unrelated_keys_excluded_and_values_unchanged():
    sentinel = {
        "npc_relationships:A": {
            "trust": "82",
            "respect": "55",
            "history": [{"event": "shared_mission", "delta": 3}],
        },
    }
    r = FakeScanRedis(
        keys=[
            "npc_relationships:A",
            "npc_traits:A",
            "world_state",
        ],
        values=sentinel,
    )
    before = copy.deepcopy(r.values)
    count = rm.persist_relationship_keys(r)
    assert count == 1
    assert r.persisted == ["npc_relationships:A"]
    # The helper only calls scan_iter() and persist(); it never reads or
    # writes relationship values. Prove the owned mapping is unchanged.
    assert r.values == before
