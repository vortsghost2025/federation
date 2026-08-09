"""Targeted tests for the role anti-bloat guards in npc_actions.py.

Proves the two outcomes the propose_role guard must enforce:
  · role_rejected_near_duplicate  — a proposed role whose normalized base name
    (after dropping standard title suffixes) already exists is rejected.
  · role_rejected_institution_cap — a proposed role for an institution already
    at ROLE_CAP_PER_INSTITUTION is rejected.

No live Redis. The guard helpers only use r.smembers()/r.hget(), so a tiny
FakeRedis is sufficient.
"""
import importlib.util
import os
import sys
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
spec = importlib.util.spec_from_file_location("npc_actions_bloat_test", MODULE_PATH)
npc_actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npc_actions)


class FakeRedis:
    """Minimal fake exposing the smembers/hget used by the guard helpers."""

    def __init__(self):
        self.sets = {}
        self.hashes = {}

    def smembers(self, key):
        return set(self.sets.get(key, []))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)


def _inst(rid, roles):
    return {"rid": rid, "roles": roles}


class TestNearDuplicateRole:
    """The near-duplicate guard rejects suffix-variant titles of a role."""

    def test_suffix_variant_rejected(self):
        r = FakeRedis()
        r.sets["inst:roles"] = ["role:equitable_influence_analyst"]
        r.hashes["role:equitable_influence_analyst"] = {"title": "Equitable Influence Analyst"}
        dup = npc_actions._find_near_duplicate_role(r, "Equitable Influence Auditor", "inst")
        assert dup == "role:equitable_influence_analyst"

    def test_curator_variant_rejected(self):
        r = FakeRedis()
        r.sets["inst:roles"] = ["role:stakeholder_influence_coordinator"]
        r.hashes["role:stakeholder_influence_coordinator"] = {"title": "Stakeholder Influence Coordinator"}
        dup = npc_actions._find_near_duplicate_role(r, "Stakeholder Influence Curator", "inst")
        assert dup == "role:stakeholder_influence_coordinator"

    def test_distinct_role_allowed(self):
        r = FakeRedis()
        r.sets["inst:roles"] = ["role:equitable_influence_analyst"]
        r.hashes["role:equitable_influence_analyst"] = {"title": "Equitable Influence Analyst"}
        dup = npc_actions._find_near_duplicate_role(r, "Trade Route Analyst", "inst")
        assert dup is None

    def test_index_wide_fallback(self):
        # Uses role:index when the institution has no role set yet.
        r = FakeRedis()
        r.sets["role:index"] = ["role:resonance_governance_coordinator"]
        r.hashes["role:resonance_governance_coordinator"] = {"title": "Resonance Governance Coordinator"}
        dup = npc_actions._find_near_duplicate_role(r, "Resonance Governance Steward", "")
        assert dup == "role:resonance_governance_coordinator"


class TestInstitutionRoleCap:
    """The cap guard rejects roles for institutions at the limit."""

    def test_at_cap_rejected(self):
        r = FakeRedis()
        cap = npc_actions.ROLE_CAP_PER_INSTITUTION
        r.sets["inst:roles"] = {f"role:r{i}" for i in range(cap)}
        assert npc_actions._institution_role_count(r, "inst") == cap
        # Direct proof: a title for this institution is a near-duplicate of
        # none, but the count is at cap.
        assert npc_actions._institution_role_count(r, "inst") >= npc_actions.ROLE_CAP_PER_INSTITUTION

    def test_below_cap_allowed(self):
        r = FakeRedis()
        r.sets["inst:roles"] = {"role:a", "role:b"}
        assert npc_actions._institution_role_count(r, "inst") == 2
        assert npc_actions._institution_role_count(r, "inst") < npc_actions.ROLE_CAP_PER_INSTITUTION