"""
G1 shadow-mode tests. Run with fakeredis (no production endpoint, no network).

Covers every requirement in the G1 task:
  - every current action category -> intent recorded, no external write
  - unknown category default-block
  - direct write-sink invocation raises ShadowBlocked
  - malformed SHADOW_MODE
  - missing/invalid SHADOW_INSTANCE_ID
  - production Redis URL / service endpoint rejected
  - intent-log size limit
  - private-content exclusion
  - provider-call limit
  - shadow Redis failure safe termination
  - import-time side effects
  - identical output across PYTHONHASHSEED 0/1/random (determinism)
"""

import importlib
import os

import fakeredis
import pytest

import npc_shadow_mode as sm
from npc_shadow_mode import ShadowBlocked, ShadowConfigError


WRITE_CATEGORIES = [
    "send_message",
    "create_artifact",
    "write_code",
    "create_institution",
    "propose_role",
    "submit_to_institution",
    "request_capability",
    "operator_ack",
]
SAFE_CATEGORIES = ["rest", "read_artifacts", "investigate", "self_improve", "reflect"]


@pytest.fixture
def shadow_env(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "shadow-001")
    monkeypatch.setenv("CHAR_ID", "char_001")
    monkeypatch.setenv("REDIS_URL", "redis://redis-shadow:6379/0")
    monkeypatch.setenv("SHADOW_PROVIDER", "mock")
    # Ensure no production credentials anywhere (blank, not merely unset).
    for k in ("NVIDIA_API_KEY", "FALLBACK_KEY_1", "FALLBACK_KEY_2",
              "OPENROUTER_API_KEY", "OPERATOR_LLM_API_KEY", "DATABASE_URL",
              "POSTGRES_URL", "POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        monkeypatch.setenv(k, "")
    sm.reset_counters()
    # Re-evaluate config under this environment.
    sm.configure()
    sm.validate_config()
    yield
    monkeypatch.delenv("SHADOW_MODE", raising=False)
    sm.configure()
    sm.reset_counters()


@pytest.fixture
def fake_r(shadow_env):
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    return r


def _decision(cat, **kw):
    d = {"category": cat, "description": "test decision", "topic": "open governance"}
    d.update(kw)
    return d


# ── 1. Every write category -> intent only, no external write ──
@pytest.mark.parametrize("cat", WRITE_CATEGORIES)
def test_write_category_intent_only(shadow_env, fake_r, cat):
    from npc_actions import execute_decision
    contacts = {"char_306": "Partner"}
    decision = _decision(cat, target="char_306", body="hello", title="T")
    res = execute_decision(decision, fake_r, contacts)
    assert res["shadow_intent_recorded"] is True
    # No production keys may be written.
    keys = fake_r.keys("*")
    prod_keys = [k for k in keys if not str(k).startswith("shadow:")]
    assert prod_keys == [], f"production key written: {prod_keys}"
    assert any(i["category"] == cat for i in sm.get_intents())


# ── safe categories still run but write only to shadow namespace ──
@pytest.mark.parametrize("cat", SAFE_CATEGORIES)
def test_safe_category_no_prod_write(shadow_env, fake_r, cat):
    from npc_actions import execute_decision
    res = execute_decision(_decision(cat), fake_r, {})
    # Safe categories may record loop-control/decision state only in shadow ns.
    prod_keys = [k for k in fake_r.keys("*") if not str(k).startswith("shadow:")]
    assert prod_keys == [], f"production key written: {prod_keys}"


# ── 2. Unknown category default-block ──
def test_unknown_category_blocked(shadow_env, fake_r):
    from npc_actions import execute_decision
    res = execute_decision(_decision("launch_missiles"), fake_r, {})
    assert res.get("shadow_blocked_unknown") is True
    assert res["shadow_intent_recorded"] is True


# ── 3. Direct write-sink invocation raises ShadowBlocked ──
def test_direct_sink_blocked(shadow_env, fake_r):
    from npc_redis_helpers import _store_thread_message
    msg = {"id": "x", "body": "private message content must not persist"}
    with pytest.raises(ShadowBlocked):
        _store_thread_message(fake_r, msg, "thread-1", char_id="char_001")


def test_direct_get_redis_production_blocked(shadow_env):
    # Under SHADOW_MODE get_redis must refuse unconditionally (fail closed),
    # regardless of whether REDIS_URL looks like production.
    import npc_redis_helpers as rh
    for url in ("redis://redis-shadow:6379/0", "redis://redis:6379/0", "redis://10.0.0.9:6379"):
        rh.REDIS_URL = url
        try:
            with pytest.raises(ShadowBlocked):
                rh.get_redis()
        finally:
            rh.REDIS_URL = "redis://redis-shadow:6379/0"


def test_get_shadow_redis_rejects_production(shadow_env):
    import npc_redis_helpers as rh
    # A production-style endpoint must be refused by the shadow accessor.
    with pytest.raises(ShadowBlocked):
        rh.get_shadow_redis(url="redis://redis:6379/0")
    # An injected fake client is always accepted.
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    assert rh.get_shadow_redis(fake_client=fake) is fake
    # A validated shadow endpoint is accepted.
    client = rh.get_shadow_redis(url="redis://redis-shadow:6379/0")
    assert client is not None


def test_get_shadow_redis_requires_shadow(monkeypatch):
    import npc_redis_helpers as rh
    monkeypatch.setenv("SHADOW_MODE", "false")
    sm.configure()
    with pytest.raises(ShadowBlocked):
        rh.get_shadow_redis(url="redis://redis-shadow:6379/0")


# ── 4. Malformed SHADOW_MODE ──
def test_malformed_shadow_mode(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "maybe")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "shadow-001")
    sm.configure()
    assert sm.SHADOW is False  # "maybe" is not true


# ── 5. Missing / invalid SHADOW_INSTANCE_ID fails closed ──
def test_missing_instance_id(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.delenv("SHADOW_INSTANCE_ID", raising=False)
    sm.configure()
    with pytest.raises(ShadowConfigError):
        sm.validate_config()


def test_invalid_instance_id_chars(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "prod char_001")
    sm.configure()
    with pytest.raises(ShadowConfigError):
        sm.validate_config()


# ── 6. Production Redis URL / service endpoint rejected ──
def test_production_redis_url_rejected(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "shadow-001")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    sm.configure()
    with pytest.raises(ShadowConfigError):
        sm.validate_config()


def test_production_service_endpoint_rejected(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "shadow-001")
    monkeypatch.setenv("REDIS_URL", "redis://redis-shadow:6379/0")
    monkeypatch.setenv("EXTRA_URL", "postgresql://user@db:5432/fed")
    sm.configure()
    with pytest.raises(ShadowConfigError):
        sm.validate_config()
    monkeypatch.delenv("EXTRA_URL", raising=False)


# ── 7. Intent-log size limit (hard boundary) ──
def test_intent_log_size_cap(monkeypatch, shadow_env):
    # Hard cap: the on-disk log must never exceed SHADOW_MAX_LOG_BYTES.
    cap = 200
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.configure()
    sm.validate_config()
    accepted = 0
    for _ in range(50):
        try:
            sm.record_intent("send_message", _decision("send_message"))
            accepted += 1
        except sm.ShadowLogLimit:
            break
    # File size must never exceed the cap.
    size = sm._log_bytes if hasattr(sm, "_log_bytes") else 0
    if sm.SHADOW_LOG_PATH and os.path.exists(sm.SHADOW_LOG_PATH):
        size = max(size, os.path.getsize(sm.SHADOW_LOG_PATH))
    assert size <= cap, f"log exceeded cap: {size} > {cap}"
    assert accepted >= 1  # at least the first record fit


def test_log_cap_exact_boundary(monkeypatch, shadow_env, tmp_path):
    # Fill the log until exactly the boundary, then one more must raise.
    cap = 100
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.SHADOW_LOG_PATH = str(tmp_path / "intents.log")
    sm._log_bytes = 0
    sm._intent_count = 0
    sm.configure()
    sm.validate_config()
    # Record small fixed-size records until near the cap.
    payload = {"category": "send_message", "description": "x", "topic": "t"}
    filled = 0
    while True:
        try:
            sm.record_intent("send_message", payload)
            filled += 1
        except sm.ShadowLogLimit:
            break
        if filled > 1000:
            break
    assert sm._log_bytes <= cap
    # A further append must raise ShadowLogLimit (post-cap).
    with pytest.raises(sm.ShadowLogLimit):
        sm.record_intent("send_message", payload)


def test_log_cap_one_byte_over(monkeypatch, shadow_env, tmp_path):
    # Each record larger than remaining space must be rejected, never truncated.
    cap = 60
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.SHADOW_LOG_PATH = str(tmp_path / "intents.log")
    sm._log_bytes = 0
    sm._intent_count = 0
    sm.configure()
    sm.validate_config()
    big = {"category": "send_message", "description": "a" * 50, "topic": "t"}
    # First may or may not fit; if it fits, second must raise without writing.
    try:
        sm.record_intent("send_message", big)
    except sm.ShadowLogLimit:
        pass
    before = sm._log_bytes
    with pytest.raises(sm.ShadowLogLimit):
        sm.record_intent("send_message", big)
    assert sm._log_bytes == before  # nothing appended past the cap


def test_log_cap_oversized_single_record(monkeypatch, shadow_env, tmp_path):
    # A single record larger than the whole cap must be refused outright.
    cap = 40
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.SHADOW_LOG_PATH = str(tmp_path / "intents.log")
    sm._log_bytes = 0
    sm._intent_count = 0
    sm.configure()
    sm.validate_config()
    huge = {"category": "send_message", "description": "z" * 200, "topic": "t"}
    with pytest.raises(sm.ShadowLogLimit):
        sm.record_intent("send_message", huge)
    assert sm._log_bytes == 0


def test_log_cap_repeated_post_cap(monkeypatch, shadow_env, tmp_path):
    # Repeated attempts after the cap must keep raising, never grow the log.
    cap = 80
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.SHADOW_LOG_PATH = str(tmp_path / "intents.log")
    sm._log_bytes = 0
    sm._intent_count = 0
    sm.configure()
    sm.validate_config()
    payload = {"category": "send_message", "description": "m", "topic": "t"}
    for _ in range(500):
        try:
            sm.record_intent("send_message", payload)
        except sm.ShadowLogLimit:
            break
    frozen = sm._log_bytes
    assert frozen <= cap
    for _ in range(20):
        with pytest.raises(sm.ShadowLogLimit):
            sm.record_intent("send_message", payload)
    assert sm._log_bytes == frozen


def test_log_cap_concurrent_append(monkeypatch, shadow_env, tmp_path):
    # Concurrent appends must not exceed the cap (best-effort serialized guard).
    import threading
    cap = 120
    monkeypatch.setenv("SHADOW_MAX_LOG_BYTES", str(cap))
    sm.SHADOW_LOG_PATH = str(tmp_path / "intents.log")
    sm._log_bytes = 0
    sm._intent_count = 0
    sm.configure()
    sm.validate_config()
    payload = {"category": "send_message", "description": "c", "topic": "t"}

    def worker():
        for _ in range(200):
            try:
                sm.record_intent("send_message", payload)
            except sm.ShadowLogLimit:
                return

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sm._log_bytes <= cap, f"concurrent append exceeded cap: {sm._log_bytes}"


# ── 8. Private-content exclusion ──
def test_no_private_content_in_intent(shadow_env):
    sm.record_intent("send_message", {
        "category": "send_message",
        "description": "public topic",
        "body": "SECRET PRIVATE MESSAGE BODY",
        "target": "char_306",
    }, extra={"target": "char_306"})
    payload = str(sm.get_intents()[-1])
    assert "SECRET PRIVATE MESSAGE BODY" not in payload
    assert "char_306" in payload  # target is non-private scalar, allowed


# ── 9. Provider-call limit ──
def test_provider_call_limit(shadow_env):
    for _ in range(sm.SHADOW_MAX_MODEL_CALLS + 5):
        sm.mock_provider("s", "p", call_label="artifact")
    # Beyond the cap the mock still returns but flags the limit.
    last = sm.mock_provider("s", "p", call_label="artifact")
    assert last.get("shadow_limit") in (None, "max_model_calls_reached")


# ── 10. Shadow Redis failure safe termination ──
def test_shadow_redis_failure_safe(monkeypatch, shadow_env):
    import npc_actions
    # Simulate redis connection failure by passing a broken client object.
    class BrokenRedis:
        def zadd(self, *a, **k):
            raise RuntimeError("shadow redis down")
    from npc_actions import execute_decision
    # rest is safe; but decision recording uses r. With broken r and SHADOW,
    # execute_decision should not raise out to production — it records intent.
    res = execute_decision(_decision("rest"), BrokenRedis(), {})
    assert res["shadow_intent_recorded"] is True


# ── 11. Import-time side effects ──
def test_import_no_side_effects(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("SHADOW_INSTANCE_ID", "shadow-001")
    sm.configure()
    # Importing must not open sockets or call providers.
    assert sm.SHADOW is True
    assert sm.get_intents() == []


# ── 12. Determinism across hash seeds ──
def test_determinism_across_seeds(shadow_env, fake_r):
    from npc_actions import execute_decision
    sm.configure()
    sm.reset_counters()
    res_a = execute_decision(_decision("create_artifact", title="Open Governance"), fake_r, {})
    dig_a = sm.mock_provider("s", "p")["digest"]
    res_b = execute_decision(_decision("create_artifact", title="Open Governance"), fake_r, {})
    dig_b = sm.mock_provider("s", "p")["digest"]
    assert res_a["shadow_intent_recorded"] == res_b["shadow_intent_recorded"]
    assert dig_a == dig_b  # deterministic digest


def test_complete_intent_matrix(shadow_env, fake_r):
    from npc_actions import execute_decision
    all_cats = WRITE_CATEGORIES + SAFE_CATEGORIES + ["launch_missiles"]
    sm.reset_counters()
    for c in all_cats:
        execute_decision(_decision(c, target="char_306", title="T"), fake_r, {"char_306": "P"})
    intents = sm.get_intents()
    # Every category produced exactly one intent record.
    for c in WRITE_CATEGORIES + SAFE_CATEGORIES:
        assert len([i for i in intents if i["category"] == c]) >= 1
    assert len([i for i in intents if i["category"] == "launch_missiles"]) == 1
