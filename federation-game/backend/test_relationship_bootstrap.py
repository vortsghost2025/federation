"""Focused tests for relationship-edge bootstrap in evolve_npc_relationships.

The fix guards first-edge creation against a floating-point boundary defect:
a combined intended +/-0.05 signal such as 0.15 - 0.10 can be represented as
0.04999999999999999 and must NOT be dropped as sub-threshold.

Uses an in-memory fake Redis. No live Redis / production infra required.
"""

import json

import simulation_engine as se


class FakePipeline:
    def __init__(self, parent):
        self.parent = parent
        self.cmds = []

    def hset(self, name, key=None, value=None, mapping=None):
        self.parent.hset_calls.append((name, key, value, mapping))
        return True

    def expire(self, name, ttl):
        self.parent.expire_calls.append((name, ttl))
        return True

    def persist(self, name):
        self.parent.persist_calls.append(name)
        return True

    def execute(self):
        return [True] * len(self.cmds)


class FakeRedis:
    """In-memory fake. Tracks a TTL map so HSET/HINCRBY can be tested for
    TTL-preserving semantics: field writes never create or remove a TTL."""

    def __init__(self, treaties=None, existing=None, quests=None, votes=None,
                 conflicts=None):
        self.treaties = treaties or {}
        self.existing = existing or {}
        self.quests = quests or {}
        self.votes = votes or []
        self.conflicts = conflicts or []
        self.hset_calls = []
        self.expire_calls = []
        self.persist_calls = []
        # key -> ttl (None means no TTL / permanent)
        self.ttls = {}

    def _rels(self, key):
        cid = key.split(":", 1)[1]
        return self.existing.get(cid, {})

    def hgetall(self, key):
        if key == "faction_treaties_active":
            return self.treaties
        if key.startswith("npc_relationships:"):
            return self._rels(key)
        return {}

    def hset(self, name, key=None, value=None, mapping=None):
        # HSET preserves any existing TTL state.
        self.hset_calls.append((name, key, value, mapping))
        return True

    def hincrby(self, name, key, amount):
        # HINCRBY preserves any existing TTL state.
        self.hset_calls.append((name, key, amount, None))
        return True

    def persist(self, name):
        # Only used here for direct TTL inspection in tests.
        self.persist_calls.append(name)
        self.ttls.pop(name, None)
        return True

    def expire(self, name, ttl):
        self.expire_calls.append((name, ttl))
        self.ttls[name] = ttl
        return True

    def ttl(self, name):
        return self.ttls.get(name)

    def lrange(self, key, a, b):
        if key.startswith("npc_quests:completed:"):
            cid = key.split(":", 2)[-1]
            return self.quests.get(cid, [])
        return []

    def zrevrange(self, key, a, b):
        if key == "choice_resolutions":
            return [json.dumps(v) for v in self.votes]
        if key == "faction_conflicts":
            return [json.dumps(v) for v in self.conflicts]
        return []

    def pipeline(self, transaction=False):
        return FakePipeline(self)


def _npcs():
    return [
        {"char_id": "char_A", "affiliation": "facA"},
        {"char_id": "char_B", "affiliation": "facB"},
    ]


def _npcs3():
    return [
        {"char_id": "char_A", "affiliation": "facA"},
        {"char_id": "char_B", "affiliation": "facB"},
        {"char_id": "char_C", "affiliation": "facC"},
    ]


def _run(npcs=None, treaties=None, quests=None, votes=None, existing=None):
    r = FakeRedis(
        treaties=treaties or {},
        quests=quests or {},
        votes=votes or [],
        existing=existing or {},
    )
    cnt = se.evolve_npc_relationships(npcs or _npcs(), r)
    edges = {
        key: value
        for (k, key, value, mapping) in r.hset_calls
        if k == "npc_relationships:char_A"
    }
    return cnt, edges, r.expire_calls, r.persist_calls


def _has_edge(edges):
    return "char_B" in edges


def test_direct_treaty_plus_0_05_creates_edge():
    cnt, edges, _, _ = _run(treaties={"facA:facB": "x"})
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 50.05) < 1e-9


def test_direct_vote_diff_minus_0_05_creates_edge():
    cnt, edges, _, _ = _run(votes=[{"faction_votes": {
        "facA": {"choice_id": "X"}, "facB": {"choice_id": "Y"}}}])
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 49.95) < 1e-9


def test_combined_plus_0_05_float_not_lost():
    # voting SAME (+0.15 A->B) minus a confront_rival quest vs a DIFFERENT
    # faction (-0.1 A->B) nets +0.05; the arithmetic 0.15 - 0.10 is
    # float-represented as 0.04999999999999999 and must still form the edge.
    quests = {"char_A": [json.dumps(
        {"quest_type": "confront_rival", "faction_id": "facC"})]}
    cnt, edges, _, _ = _run(
        npcs=_npcs3(),
        votes=[{"faction_votes": {
            "facA": {"choice_id": "X"}, "facB": {"choice_id": "X"}}}],
        quests=quests,
    )
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 50.05) < 1e-9


def test_combined_minus_0_05_float_not_lost():
    # treaty +0.05 (facA:facB) minus a confront_rival quest vs a DIFFERENT
    # faction (-0.1 A->B) nets -0.05 and must still form the edge (a net-0
    # signal with no real magnitude is what gets suppressed).
    quests = {"char_A": [json.dumps(
        {"quest_type": "confront_rival", "faction_id": "facC"})]}
    cnt, edges, _, _ = _run(npcs=_npcs3(), treaties={"facA:facB": "x"},
                            quests=quests)
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 49.95) < 1e-9


def test_sub_threshold_signal_suppressed():
    # treaty +0.05 plus voting DIFFERENT -0.05 nets 0 -> no real signal ->
    # brand-new edge must be suppressed.
    cnt, edges, _, _ = _run(
        treaties={"facA:facB": "x"},
        votes=[{"faction_votes": {
            "facA": {"choice_id": "X"}, "facB": {"choice_id": "Y"}}}],
    )
    assert not _has_edge(edges), edges


def test_existing_edge_updates_and_decays():
    # An existing edge above neutral decays toward 50 by 0.02.
    existing = {"char_A": {"char_B": "60.0"}}
    cnt, edges, _, persists = _run(existing=existing)
    assert edges.get("char_B") == "59.98", edges
    assert "npc_relationships:char_A" in persists, persists

    # An existing edge below neutral rises toward 50 by 0.02.
    existing = {"char_A": {"char_B": "49.0"}}
    cnt, edges, _, persists = _run(existing=existing)
    assert edges.get("char_B") == "49.02", edges
    assert "npc_relationships:char_A" in persists, persists

    # An existing edge with a real new signal updates by that signal.
    existing = {"char_A": {"char_B": "50.0"}}
    cnt, edges, _, persists = _run(treaties={"facA:facB": "x"}, existing=existing)
    assert abs(float(edges["char_B"]) - 50.05) < 1e-9
    assert "npc_relationships:char_A" in persists, persists


def test_relationship_key_is_permanent_not_expired():
    """Evolution must persist (not expire) changed relationship keys."""
    _, _, expires, persists = _run(treaties={"facA:facB": "x"})
    rel_expires = [t for t in expires if t[0].startswith("npc_relationships:")]
    rel_persists = [p for p in persists if p.startswith("npc_relationships:")]
    # No relationship key receives a TTL.
    assert len(rel_expires) == 0, expires
    # Changed relationship keys are made permanent.
    assert len(rel_persists) == 2, persists


def test_new_edge_is_persisted():
    """A brand-new edge (first contact) must also be persisted."""
    _, edges, expires, persists = _run(treaties={"facA:facB": "x"})
    assert _has_edge(edges), edges
    assert "npc_relationships:char_A" in persists, persists
    assert "npc_relationships:char_B" in persists, persists
    assert all(not t[0].startswith("npc_relationships:") for t in expires), expires


def test_no_change_issues_no_unnecessary_writes():
    """With no signal and a neutral/empty state, no writes occur."""
    r = FakeRedis()
    cnt = se.evolve_npc_relationships(_npcs(), r)
    rel_writes = [c for c in r.hset_calls if c[0].startswith("npc_relationships:")]
    assert cnt == 0
    assert rel_writes == []
    assert r.persist_calls == []
    assert r.expire_calls == []


def test_hset_preserves_existing_ttl():
    """HSET on a relationship key must NOT create or remove an existing TTL."""
    r = FakeRedis(existing={"char_A": {"char_B": "50.0"}})
    # Simulate an upstream writer (e.g. socialize handler) that sets a field.
    r.ttls["npc_relationships:char_A"] = 604800
    r.hset("npc_relationships:char_A", "char_B", "55.0")
    # TTL unchanged: not created, not removed.
    assert r.ttl("npc_relationships:char_A") == 604800


def test_hincrby_preserves_existing_ttl():
    """HINCRBY on a relationship key must NOT create or remove an existing TTL."""
    r = FakeRedis(existing={"char_A": {"char_B": "50.0"}})
    r.ttls["npc_relationships:char_A"] = 604800
    r.hincrby("npc_relationships:char_A", "char_B", 5)
    assert r.ttl("npc_relationships:char_A") == 604800
