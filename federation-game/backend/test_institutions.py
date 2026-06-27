"""Tests for institution seeding, workflow behavior, counters, and overrides."""

import fnmatch
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import institutions


class FakeRedis:
    def __init__(self):
        self.strings = {}
        self.hashes = {}
        self.lists = {}
        self.sets = {}

    def exists(self, key):
        return int(
            key in self.strings
            or key in self.hashes
            or key in self.lists
            or key in self.sets
        )

    def keys(self, pattern):
        all_keys = (
            set(self.strings)
            | set(self.hashes)
            | set(self.lists)
            | set(self.sets)
        )
        return [key for key in all_keys if fnmatch.fnmatch(key, pattern)]

    def set(self, key, value, ex=None):
        self.strings[key] = value
        return True

    def get(self, key):
        return self.strings.get(key)

    def sadd(self, key, *values):
        if not values:
            raise TypeError("sadd requires at least one value")
        bucket = self.sets.setdefault(key, set())
        added = 0
        for value in values:
            if value not in bucket:
                bucket.add(value)
                added += 1
        return added

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def srem(self, key, *values):
        bucket = self.sets.get(key, set())
        removed = 0
        for value in values:
            if value in bucket:
                bucket.remove(value)
                removed += 1
        return removed

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(key, {})
        if mapping is not None:
            bucket.update(mapping)
        elif field is not None:
            bucket[field] = value
        return True

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def lpush(self, key, *values):
        bucket = self.lists.setdefault(key, [])
        for value in values:
            bucket.insert(0, value)
        return len(bucket)

    def rpush(self, key, *values):
        bucket = self.lists.setdefault(key, [])
        for value in values:
            bucket.append(value)
        return len(bucket)

    def lrange(self, key, start, end):
        items = list(self.lists.get(key, []))
        if not items:
            return []
        n = len(items)
        if start < 0:
            start = max(n + start, 0)
        if end < 0:
            end = n + end
        end = min(end, n - 1)
        if start > end or start >= n:
            return []
        return items[start : end + 1]

    def llen(self, key):
        return len(self.lists.get(key, []))


def test_seed_institutions_creates_indexes_and_role_bindings():
    fake = FakeRedis()

    result = institutions.seed_institutions(fake, now="2026-06-27T19:30:00Z")

    assert result["institutions_seeded"] == 2
    assert result["roles_seeded"] == 2
    assert "institution:research_division_council" in fake.smembers("institution:index")
    assert "institution:consciousness_collective_council" in fake.smembers("institution:index")
    assert "role:research_chief_mathematician" in fake.smembers("role:index")
    assert "role:collective_oracle" in fake.smembers("role:index")

    char_001_ctx = institutions.get_councilor_role_context(fake, "char_001")
    char_306_ctx = institutions.get_councilor_role_context(fake, "char_306")

    assert char_001_ctx["institution_id"] == "institution:research_division_council"
    assert char_001_ctx["role_id"] == "role:research_chief_mathematician"
    assert char_306_ctx["institution_id"] == "institution:consciousness_collective_council"
    assert char_306_ctx["role_id"] == "role:collective_oracle"


def test_annotate_artifact_creates_single_proposal_review_workflow():
    fake = FakeRedis()

    artifact = {
        "artifact_id": "artifact-001",
        "title": "Proposal: Sol Prime Research Accord",
        "body": "Approve a new research charter for Sol Prime.",
    }

    first = institutions.annotate_artifact(fake, "char_001", dict(artifact), now="2026-06-27T19:31:00Z")
    second = institutions.annotate_artifact(fake, "char_001", dict(artifact), now="2026-06-27T19:31:30Z")

    assert first["institution_id"] == "institution:research_division_council"
    assert first["role_id"] == "role:research_chief_mathematician"
    assert first["artifact_kind"] == "proposal"
    assert first["workflow_id"].startswith("workflow:proposal_review:")
    assert second["workflow_id"] == first["workflow_id"]
    assert len(fake.smembers("workflow:index")) == 1

    workflow = fake.hgetall(first["workflow_id"])
    assert workflow["type"] == "proposal_review"
    assert workflow["status"] == "submitted"
    assert workflow["source_artifact_id"] == "artifact-001"


def test_run_institution_tick_advances_workflow_without_duplication():
    fake = FakeRedis()

    artifact = {
        "artifact_id": "artifact-002",
        "title": "Proposal: Harbor Transit Compact",
        "body": "Create a transit compact for Harbor sector.",
    }

    annotated = institutions.annotate_artifact(fake, "char_306", artifact, now="2026-06-27T19:32:00Z")
    workflow_id = annotated["workflow_id"]

    tick_one = institutions.run_institution_tick(fake, now="2026-06-27T19:33:00Z")
    tick_two = institutions.run_institution_tick(fake, now="2026-06-27T19:34:00Z")
    tick_three = institutions.run_institution_tick(fake, now="2026-06-27T19:35:00Z")

    workflow = fake.hgetall(workflow_id)
    events = [json.loads(item) for item in fake.lrange(f"{workflow_id}:events", 0, -1)]

    assert workflow["status"] == "ratified"
    assert len(fake.smembers("workflow:index")) == 1
    assert [event["status"] for event in events] == [
        "submitted",
        "under_review",
        "deliberating",
        "ratified",
    ]
    assert tick_one["workflows_advanced"] == 1
    assert tick_two["workflows_advanced"] == 1
    assert tick_three["workflows_advanced"] == 1


def test_analysis_review_workflow_completes_in_two_ticks():
    fake = FakeRedis()

    artifact = {
        "artifact_id": "artifact-analysis-001",
        "title": "Analysis: Sector 7 Resonance Diagnostic",
        "body": "Diagnostic brief on sector 7 anomaly patterns.",
    }

    annotated = institutions.annotate_artifact(fake, "char_306", artifact, now="2026-06-27T20:00:00Z")
    workflow_id = annotated["workflow_id"]

    assert annotated["artifact_kind"] == "analysis"
    assert workflow_id.startswith("workflow:analysis_review:")

    workflow = fake.hgetall(workflow_id)
    assert workflow["type"] == "analysis_review"
    assert workflow["status"] == "submitted"

    tick_one = institutions.run_institution_tick(fake, now="2026-06-27T20:01:00Z")
    tick_two = institutions.run_institution_tick(fake, now="2026-06-27T20:02:00Z")
    tick_three = institutions.run_institution_tick(fake, now="2026-06-27T20:03:00Z")

    workflow = fake.hgetall(workflow_id)
    events = [json.loads(item) for item in fake.lrange(f"{workflow_id}:events", 0, -1)]

    assert workflow["status"] == "endorsed"
    assert [event["status"] for event in events] == [
        "submitted",
        "peer_review",
        "endorsed",
    ]
    assert tick_one["workflows_advanced"] == 1
    assert tick_two["workflows_advanced"] == 1
    assert tick_three["workflows_advanced"] == 0

    assert workflow_id not in fake.smembers("workflow:active")
    assert workflow_id in fake.smembers("workflow:completed")


def test_ensure_workflow_rejects_unknown_type():
    fake = FakeRedis()
    institutions.seed_institutions(fake, now="2026-06-27T20:10:00Z")
    role_ctx = institutions.get_councilor_role_context(fake, "char_001")

    artifact = {"artifact_id": "artifact-bad-001", "title": "Test"}
    try:
        institutions.ensure_workflow(fake, "char_001", artifact, role_ctx, "nonexistent_type")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "nonexistent_type" in str(exc)


def test_override_workflow_status():
    fake = FakeRedis()

    artifact = {
        "artifact_id": "artifact-override-001",
        "title": "Proposal: Override Test",
        "body": "Test override.",
    }
    annotated = institutions.annotate_artifact(fake, "char_001", artifact, now="2026-06-27T20:20:00Z")
    workflow_id = annotated["workflow_id"]

    assert workflow_id in fake.smembers("workflow:active")

    result = institutions.override_workflow_status(fake, workflow_id, "ratified", now="2026-06-27T20:21:00Z")
    assert result is True

    workflow = fake.hgetall(workflow_id)
    assert workflow["status"] == "ratified"
    assert workflow_id not in fake.smembers("workflow:active")
    assert workflow_id in fake.smembers("workflow:completed")


def test_counters_are_incremented_on_workflow_creation_and_completion():
    fake = FakeRedis()
    inst_id = "institution:research_division_council"

    artifact = {
        "artifact_id": "artifact-counter-001",
        "title": "Proposal: Counter Test",
        "body": "Test counters.",
    }

    institutions.annotate_artifact(fake, "char_001", artifact, now="2026-06-27T20:30:00Z")
    active_count = int(fake.get(f"{inst_id}:active_workflows") or 0)
    assert active_count == 1

    institutions.run_institution_tick(fake, now="2026-06-27T20:31:00Z")
    institutions.run_institution_tick(fake, now="2026-06-27T20:32:00Z")
    institutions.run_institution_tick(fake, now="2026-06-27T20:33:00Z")

    active_count = int(fake.get(f"{inst_id}:active_workflows") or 0)
    completed_count = int(fake.get(f"{inst_id}:completed_workflows") or 0)
    assert active_count == 0
    assert completed_count == 1


def test_rebuild_inst_counters():
    fake = FakeRedis()
    inst_id = "institution:research_division_council"

    artifact = {
        "artifact_id": "artifact-rebuild-001",
        "title": "Proposal: Rebuild Counter Test",
        "body": "Test rebuild.",
    }

    institutions.annotate_artifact(fake, "char_001", artifact, now="2026-06-27T20:40:00Z")

    fake.strings[f"{inst_id}:active_workflows"] = "99"
    fake.strings[f"{inst_id}:completed_workflows"] = "99"

    institutions._rebuild_inst_counters(fake)

    active_count = int(fake.get(f"{inst_id}:active_workflows") or 0)
    completed_count = int(fake.get(f"{inst_id}:completed_workflows") or 0)
    assert active_count == 1
    assert completed_count == 0


def test_set_institution_status():
    fake = FakeRedis()
    institutions.seed_institutions(fake, now="2026-06-27T20:50:00Z")
    inst_id = "institution:research_division_council"

    result = institutions.set_institution_status(fake, inst_id, "suspended")
    assert result is True

    rec = fake.hgetall(inst_id)
    assert rec["status"] == "suspended"

    result = institutions.set_institution_status(fake, "institution:nonexistent", "active")
    assert result is False
