
"""
Tests for the Federation Builder event collector and state.
"""

import json
import time
from pathlib import Path

import sys, os
import pytest
# Ensure the repository root is on the import path for absolute imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from builder.event_collector import collect_once, EventCollector
from builder.state import BuilderState


class FakeRedis:
    def __init__(self, data):
        # data: dict of char_id -> list of (score, raw_json)
        self.data = data

    def zrevrange(self, key, start, stop):
        # key format: npc_decisions:<char_id>
        parts = key.split(":")
        if len(parts) != 2:
            return []
        char_id = parts[1]
        items = self.data.get(char_id, [])
        # sort by score descending (newest first)
        items = sorted(items, key=lambda x: x[0], reverse=True)
        # slice according to start/stop (both inclusive semantics for redis)
        sliced = items[start : stop + 1]
        return [raw for _score, raw in sliced]

    # Redis clients used by builder state call .ping() – we can stub it.
    def ping(self):
        return True

    # For get, set, hset, etc., builder state does not use redis.
    # So we leave them unimplemented.


def test_collect_once_filters_by_timestamp():
    now = time.time()
    # Create two decisions, one older than cursor, one newer
    older = json.dumps({"ts": now - 10, "action": "old"})
    newer = json.dumps({"ts": now + 5, "action": "new"})
    fake = FakeRedis({"char_001": [(now - 10, older), (now + 5, newer)]})
    # cursor at now, should only return the newer decision
    out = collect_once(fake, ["char_001"], since_ts=now)
    assert len(out) == 1
    assert out[0]["action"] == "new"
    # If cursor before both, returns both sorted by ts asc
    out2 = collect_once(fake, ["char_001"], since_ts=now - 20)
    assert len(out2) == 2
    assert out2[0]["action"] == "old"
    assert out2[1]["action"] == "new"


def test_event_collector_writes_jsonl(tmp_path: Path):
    now = time.time()
    decision = json.dumps({"ts": now, "action": "test"})
    fake = FakeRedis({"char_001": [(now, decision)]})
    collector = EventCollector(
        redis_client=fake,
        npc_ids=["char_001"],
        events_dir=str(tmp_path / "events"),
        poll_interval_s=1,
    )
    written = collector.run_once()
    assert written == 1
    # Verify a JSONL file exists and contains the JSON line
    files = list((tmp_path / "events").glob("events-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text().strip()
    assert json.loads(content)["action"] == "test"


def test_builder_state_initial(tmp_path: Path):
    state_path = tmp_path / "state.json"
    bs = BuilderState(str(state_path))
    snapshot = bs.snapshot()
    assert snapshot["version"] == 1
    assert snapshot["pending_requests"] == []
    # Add a pending request and verify persistence
    req = {"id": "req-1", "kind": "capability_request", "payload": {"foo": "bar"}}
    bs.add_pending(req)
    # Reload from disk
    bs2 = BuilderState(str(state_path))
    pending = bs2.pending()
    assert len(pending) == 1
    assert pending[0]["id"] == "req-1"
    assert pending[0]["status"] == "pending"
