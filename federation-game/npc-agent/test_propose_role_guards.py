"""End-to-end tests for the propose_role anti-bloat guards in npc_actions.py.

These tests invoke the REAL execute_decision() path with a propose_role
decision, proving the two guard outcomes surface on action_taken AND that no
new role is actually written to Redis:

  · role_rejected_near_duplicate  — suffix variant of an existing role rejected.
  · role_rejected_institution_cap — institution at ROLE_CAP_PER_INSTITUTION.

The "no role written" assertion is the important part: it proves the guard
isn't merely returning the right label after accidentally creating the role.
"""
import importlib.util
import json
import os
import sys
import types

# Stub redis/httpx so importing npc_actions needs no live services.
class _DummyRedis:
    @staticmethod
    def from_url(*a, **k):
        return None
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=_DummyRedis))
sys.modules.setdefault("httpx", types.SimpleNamespace(
    Client=object, TimeoutException=Exception,
    RequestError=Exception, HTTPStatusError=Exception))

# Order matters: npc_actions imports from npc_redis_helpers, npc_context,
# npc_decisions, npc_llm_client, fourth_wall. Importing npc_actions pulls those
# in; stub redis/httpx first (above) so they import cleanly.
MODULE_PATH = os.path.join(os.path.dirname(__file__), "npc_actions.py")
spec = importlib.util.spec_from_file_location("npc_actions_e2e", MODULE_PATH)
npc_actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npc_actions)

# Pin identity so _partner_id / session keys are deterministic.
os.environ.setdefault("CHAR_ID", "char_001")
os.environ.setdefault("NPC_NAME", "char_001")


class FakeRedis:
    """In-memory redis-method stub covering the propose_role path.

    Supports: smembers, sadd, hgetall, hget, hset, get, hincrby, rpush, ltrim.
    """

    def __init__(self):
        self.sets = {}
        self.hashes = {}
        self.strings = {}
        self.lists = {}

    def smembers(self, key):
        return set(self.sets.get(key, []))

    def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, mapping=None, **kwargs):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update(mapping)
        if kwargs:
            h.update(kwargs)

    def hincrby(self, key, field, amount):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + amount)
        return h[field]

    def get(self, key):
        return self.strings.get(key)

    def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(len(items) + start, 0)
        if end < 0:
            end = max(len(items) + end + 1, 0)
        self.lists[key] = items[start:end] if start < len(items) else []


def _setup_inst(r, inst_id, inst_name, roles):
    """Seed an institution with a name + a set of existing role ids."""
    r.sadd("institution:index", inst_id)
    r.hset(inst_id, mapping={"name": inst_name, "kind": "council", "status": "active"})
    r.sadd(f"{inst_id}:roles", *roles)
    for rid in roles:
        r.hset(rid, mapping={"title": rid.split(":", 1)[-1].replace("_", " ").title()})


def _propose(r, role_title, inst_name):
    return npc_actions.execute_decision(
        {
            "category": "propose_role",
            "institution_name": inst_name,
            "role_title": role_title,
            "scope": "some scope",
            "authority": "observe_and_report",
            "description": f"propose role {role_title}",
        },
        r,
        contacts={},
    )


class TestProposeRoleNearDuplicate:
    def test_suffix_variant_rejected_and_not_written(self):
        r = FakeRedis()
        _setup_inst(r, "inst:gov", "Governance Bureau", ["role:equitable_influence_analyst"])
        result = _propose(r, "Equitable Influence Auditor", "Governance Bureau")
        assert result["action_taken"] == "role_rejected_near_duplicate"
        # The new role must NOT have been added to role:index nor written.
        assert "role:equitable_influence_auditor" not in r.smembers("role:index")
        assert "role:equitable_influence_auditor" not in r.hashes

    def test_curator_variant_rejected_and_not_written(self):
        r = FakeRedis()
        _setup_inst(r, "inst:gov", "Governance Bureau", ["role:stakeholder_influence_coordinator"])
        result = _propose(r, "Stakeholder Influence Curator", "Governance Bureau")
        assert result["action_taken"] == "role_rejected_near_duplicate"
        assert "role:stakeholder_influence_curator" not in r.smembers("role:index")
        assert "role:stakeholder_influence_curator" not in r.hashes


class TestProposeRoleInstitutionCap:
    def test_at_cap_rejected_and_not_written(self):
        r = FakeRedis()
        cap = npc_actions.ROLE_CAP_PER_INSTITUTION
        roles = {f"role:r{i}" for i in range(cap)}
        _setup_inst(r, "inst:gov", "Governance Bureau", roles)
        result = _propose(r, "Brand New Distinct Role", "Governance Bureau")
        assert result["action_taken"] == "role_rejected_institution_cap"
        # No new role written despite the distinct title.
        assert "role:brand_new_distinct_role" not in r.smembers("role:index")
        assert "role:brand_new_distinct_role" not in r.hashes

    def test_below_cap_allowed(self):
        # Sanity: a distinct role for a below-cap institution is created.
        r = FakeRedis()
        _setup_inst(r, "inst:gov", "Governance Bureau", ["role:existing"])
        result = _propose(r, "Totally Unique New Role", "Governance Bureau")
        assert result["action_taken"] == "role_proposed"
        assert "role:totally_unique_new_role" in r.smembers("role:index")