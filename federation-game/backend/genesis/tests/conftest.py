"""
Shared test fixtures for the genesis package.

L1 (constitution) and L4 (drift) touch Redis. We inject an in-memory fake so the
suite runs with NO live Redis (CI-friendly, matches Federation's no-Docker-test rule).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Ensure the backend package is importable when running pytest from anywhere.
BACKEND = Path(__file__).resolve().parent.parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from genesis import genesis_constitution as constitution  # noqa: E402


class FakeRedis:
    """Minimal in-memory Redis mimicking the calls constitution/drift use."""

    def __init__(self):
        self._store: dict = {}

    def set(self, key, value, ex=None):
        self._store[key] = (value, ex)

    def get(self, key):
        v = self._store.get(key)
        return v[0] if v else None

    def rename(self, src, dst):
        if src in self._store:
            self._store[dst] = self._store.pop(src)

    def expire(self, key, ttl):
        if key in self._store:
            self._store[key] = (self._store[key][0], ttl)

    def ttl(self, key):
        v = self._store.get(key)
        if not v:
            return -2  # absent
        return v[1] if v[1] is not None else -1

    def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(constitution, "_redis", lambda: fr)
    # genesis_drift does `from . import genesis_constitution as constitution` and calls
    # constitution.recover_snapshot at runtime, so patching the module object is enough.
    return fr


@pytest.fixture
def sample_state():
    return {
        "char_id": "npc_test",
        "mood": "contemplative",
        "relationships": {"ally_a": 0.8},
        "goals": [{"id": "g1", "text": "build a garden"}],
    }


@pytest.fixture
def sample_options():
    return [
        {"category": "advance_goal", "score": 0.9, "est_cost": 1.0, "target": "other"},
        {"category": "confront_rival", "score": 0.8, "est_cost": 5.0, "target": "self"},
        {"category": "socialize", "score": 0.6, "est_cost": 0.5, "target": "other"},
        {"category": "rest", "score": 0.3, "est_cost": 0.0, "target": "self"},
    ]
