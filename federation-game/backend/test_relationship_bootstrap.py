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

    def execute(self):
        return [True] * len(self.cmds)


class FakeRedis:
    def __init__(self, treaties=None, existing=None, quests=None, votes=None,
                 conflicts=None):
        self.treaties = treaties or {}
        self.existing = existing or {}
        self.quests = quests or {}
        self.votes = votes or []
        self.conflicts = conflicts or []
        self.hset_calls = []
        self.expire_calls = []

    def hgetall(self, key):
        if key == "faction_treaties_active":
            return self.treaties
        if key.startswith("npc_relationships:"):
            return self.existing.get(key.split(":", 1)[1], {})
        return {}

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
    return cnt, edges, r.expire_calls


def _has_edge(edges):
    return "char_B" in edges


def test_direct_treaty_plus_0_05_creates_edge():
    cnt, edges, _ = _run(treaties={"facA:facB": "x"})
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 50.05) < 1e-9


def test_direct_vote_diff_minus_0_05_creates_edge():
    cnt, edges, _ = _run(votes=[{"faction_votes": {
        "facA": {"choice_id": "X"}, "facB": {"choice_id": "Y"}}}])
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 49.95) < 1e-9


def test_combined_plus_0_05_float_not_lost():
    # voting SAME (+0.15 A->B) minus a confront_rival quest vs a DIFFERENT
    # faction (-0.1 A->B) nets +0.05; the arithmetic 0.15 - 0.10 is
    # float-represented as 0.04999999999999999 and must still form the edge.
    quests = {"char_A": [json.dumps(
        {"quest_type": "confront_rival", "faction_id": "facC"})]}
    cnt, edges, _ = _run(
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
    cnt, edges, _ = _run(npcs=_npcs3(), treaties={"facA:facB": "x"},
                         quests=quests)
    assert _has_edge(edges), edges
    assert abs(float(edges["char_B"]) - 49.95) < 1e-9


def test_sub_threshold_signal_suppressed():
    # treaty +0.05 plus voting DIFFERENT -0.05 nets 0 -> no real signal ->
    # brand-new edge must be suppressed.
    cnt, edges, _ = _run(
        treaties={"facA:facB": "x"},
        votes=[{"faction_votes": {
            "facA": {"choice_id": "X"}, "facB": {"choice_id": "Y"}}}],
    )
    assert not _has_edge(edges), edges


def test_existing_edge_updates_and_decays():
    # An existing edge above neutral decays toward 50 by 0.02.
    existing = {"char_A": {"char_B": "60.0"}}
    cnt, edges, _ = _run(existing=existing)
    assert edges.get("char_B") == "59.98", edges

    # An existing edge below neutral rises toward 50 by 0.02.
    existing = {"char_A": {"char_B": "49.0"}}
    cnt, edges, _ = _run(existing=existing)
    assert edges.get("char_B") == "49.02", edges

    # An existing edge with a real new signal updates by that signal.
    existing = {"char_A": {"char_B": "50.0"}}
    cnt, edges, _ = _run(treaties={"facA:facB": "x"}, existing=existing)
    assert abs(float(edges["char_B"]) - 50.05) < 1e-9


def test_seven_day_expiry_retained():
    _, _, expires = _run(treaties={"facA:facB": "x"})
    rel_expires = [t for t in expires if t[0].startswith("npc_relationships:")]
    assert len(rel_expires) == 2, expires
    for _, ttl in rel_expires:
        assert ttl == 604800, expires
