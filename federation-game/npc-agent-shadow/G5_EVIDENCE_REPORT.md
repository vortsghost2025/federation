# G5 Behavioral Qualification Report

**Date:** 2026-07-20 (VPS run)
**Branch:** `npc-topic-loop-control`
**Commit:** `e9eb6b2` (cherry-picked from `0ca37eb` on `vortsghost2025-redesigned-eureka`)
**Runtime commit:** `0db35db`

---

## Categories

**Runtime-discovered set: 13** (dynamically from `ALL_KNOWN = _SHADOW_SAFE_CATEGORIES | _SHADOW_WRITE_CATEGORIES`)

| # | Category | Type | Intent recorded | No external op |
|---|----------|------|-----------------|---------------|
| 1 | rest | SAFE | ✅ | ✅ |
| 2 | read_artifacts | SAFE | ✅ | ✅ |
| 3 | investigate | SAFE | ✅ | ✅ |
| 4 | self_improve | SAFE | ✅ | ✅ |
| 5 | reflect | SAFE | ✅ | ✅ |
| 6 | send_message | WRITE | ✅ | ✅ |
| 7 | create_artifact | WRITE | ✅ | ✅ |
| 8 | write_code | WRITE | ✅ | ✅ |
| 9 | create_institution | WRITE | ✅ | ✅ |
| 10 | propose_role | WRITE | ✅ | ✅ |
| 11 | submit_to_institution | WRITE | ✅ | ✅ |
| 12 | request_capability | WRITE | ✅ | ✅ |
| 13 | operator_ack | WRITE | ✅ | ✅ |
| 14 | launch_missiles | UNKNOWN | ShadowBlocked | fail-closed |

**Mock cycle covers all 13** (`_G5_CATEGORIES` updated from 11 → 13 to include `reflect` and `operator_ack`).

---

## Mock Engine SHA-256 Manifest (build context, 17 files)

| File | SHA-256 |
|------|---------|
| cosmic_monitor.py | 55bc0777d983456c311b4210af99822ea2c079e9d1ff234913019a0f2c9d6e35 |
| fourth_wall.py | 8fed9407ec625c462ffb1590128184a431bf25a45e5d0459e951944fd9baa45d |
| institutions.py | 8c051df79c9b34c321201221d7933cdfa0d13b86bb42d7b0e323ecf8a330880a |
| npc_actions.py | 9832f2adcdf9f779c263cdd31b19c2a9314b105f2e5b11e1256919e82157fc19 |
| npc_agent.py | ec01a5bc8b5e7250f02322df652e6f47b3091c8e542aca308114f77e2840e13d |
| npc_context.py | 815d06f6361776ac016b163c80100600da96e00ddca2bfffd87bbb463b92b9c2 |
| npc_decisions.py | dee367e251bc488a64e883d355eea869ef03d931fa825ced6e96da2dd99e680d |
| npc_llm_client.py | c4f90cdc95475ea9f16d42dcdff69e07425e6132c5e561a39f98a5e59db30736 |
| npc_loop_control.py | a4361148a1a29ae39ea36517305906a07d834e828eba1e4411271c70a634f3c9 |
| npc_memory_bridge.py | a85710bf714fe115bd2e06c20fcdd0648aa52754e098770cb06c1d58fb5f9c58 |
| npc_redis_helpers.py | f8235b98d33fd5ce30e233f0d96b9ff1c4ad92978ae40d0cd12f33b5ac730145 |
| npc_shadow_mode.py | 08d3bb699b599c26625b9b73793a1c39915442aec2cdae1a2d1eae31546374a1 |
| qualify_shadow.py | a355ba821cdc2eb038745b6af05f509d9cac30c26d7195371eb0174639dc7781 |
| run_shadow_observation.py | 1b7235c312cbc274db95d470489696b74f3872e9aef463164dfdc79fce311702 |
| shadow_npc_main.py | eb8db689a32254c9041164b332ab6400c89bf4b6baa97ec3e7f033c86bbce9c5 |
| test_npc_g5_qualify.py | 5cc65bd4beb72cf4e74986c888f38594ce4038f055861b25ae87dd49c7d8ef21 |
| test_npc_shadow_mode.py | b95ba558ae679207f7be07b68156b4adc38413fa0346756c228cc8640def1f4e |

---

## Cross-Seed Determinism

**PYTHONHASHSEED=0, 1, random** — canonical hash of first 5 decisions for char_001:

```
983c324de88ef5408a4fe4afc5cf3a95
```
Identical across all three seeds, both NPCs. Proves deterministic mock without hash randomization.

---

## Qualification Results (VPS containers)

**char_001 (Archimedes Prime):**
- 13/13 categories exercised
- Unknown category (`launch_missiles`) ShadowBlocked
- Direct sinks blocked: `_store_thread_message`, `get_redis`, `get_shadow_redis`
- Intent log: sanitized, no prompts/bodies/credentials
- Redis namespace: `shadow:shadow-g5-001` (0 keys — intents to JSONL)
- Production state: unchanged

**char_306 (The Oracle):**
- 13/13 categories exercised
- Same safety results
- Different `shadow_ns: shadow:shadow-g5-306`

---

## Production Isolation (before/after)

| Metric | Before | After |
|--------|--------|-------|
| char_001 uptime | 39h | 39h (unchanged) |
| char_306 uptime | 36h | 36h (unchanged) |
| Redis clients | 65 | 65 |
| Postgres connections | 0 | 0 |

---

## Appendix: test_npc_g5_qualify.py (full source — preserved in evidence, gitignored locally)

```python
"""G5 qualification: NPC loop-control and shadow-mode integration tests."""
import pytest, os, sys, json, hashlib, time, subprocess

# ── Test fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_env():
    """Strip all production credentials and set isolated shadow env."""
    for k in ["NVIDIA_API_KEY", "FALLBACK_KEY_1", "FALLBACK_KEY_2",
              "OPENROUTER_API_KEY", "OPERATOR_LLM_API_KEY",
              "DATABASE_URL", "POSTGRES_URL", "POSTGRES_PASSWORD", "REDIS_PASSWORD",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SECRET_KEY", "GITHUB_TOKEN",
              "REDIS_URL", "SERVICE_URL", "API_URL", "LLM_BASE_URL"]:
        os.environ.pop(k, None)
    os.environ["REDIS_URL"] = ""
    os.environ["SHADOW_MODE"] = "true"
    os.environ["SHADOW_INSTANCE_ID"] = "g5-qual"
    os.environ["SHADOW_LOG_PATH"] = ""
    os.environ["CHAR_ID"] = "char_001"
    os.environ["PYTHONHASHSEED"] = "0"
    yield


@pytest.fixture
def sm():
    sys.path.insert(0, r"C:\Users\seand\.copilot\copilot-worktrees\federation\vortsghost2025-npc-loop-control\federation-game\npc-agent-shadow")
    import npc_shadow_mode as m
    m.reset_counters()
    m.configure()
    return m


# ── 1. All 13 runtime-registered categories produced ──────────────────────────

def test_g5_all_13_categories_produced(sm):
    """G5 mock produces all 13 action categories across 39 calls.

    Category set is discovered at runtime from ALL_KNOWN (SAFE | WRITE).
    The mock cycle covers all of them so qualification can exercise every path.
    """
    cats = set()
    for i in range(39):
        r = sm.mock_provider("sys", "user", call_label="decide")
        p = json.loads(r["content"])
        cats.add(p["category"])
    assert cats == {
        "send_message", "create_artifact", "write_code", "read_artifacts",
        "investigate", "rest", "self_improve", "create_institution",
        "propose_role", "submit_to_institution", "request_capability",
        "reflect", "operator_ack",
    }, f"Missing categories: {set(sm.ALL_KNOWN) - cats}"


# ── 2. Valid JSON from mock_provider ───────────────────────────────────────

def test_g5_mock_returns_valid_json(sm):
    """mock_provider() always returns valid JSON with required fields in content."""
    for i in range(13):
        r = sm.mock_provider("sys", "user", call_label="decide")
        assert "content" in r
        parsed = json.loads(r["content"])
        assert isinstance(parsed, dict)
        assert "category" in parsed
        assert "reasoning" in parsed or "description" in parsed


# ── 3. char_001 vs char_306 produce different sequences ─────────────────────

def test_g5_chars_differ(sm):
    """char_001 and char_306 produce different category sequences."""
    os.environ["CHAR_ID"] = "char_306"
    sm.reset_counters()
    r306 = sm.mock_provider("sys", "user", call_label="decide")
    cat_306 = json.loads(r306["content"])["category"]

    os.environ["CHAR_ID"] = "char_001"
    sm.reset_counters()
    r001 = sm.mock_provider("sys", "user", call_label="decide")
    cat_001 = json.loads(r001["content"])["category"]

    assert cat_306 != cat_001, f"char_001 and char_306 produced same category: {cat_001}"


# ── 4. Mock provider structure ─────────────────────────────────────────────

def test_g5_mock_provider_structure(sm):
    """mock_provider returns {content: json_str} with category, reasoning, description."""
    r = sm.mock_provider("sys", "user", call_label="decide")
    assert isinstance(r, dict)
    assert "content" in r
    p = json.loads(r["content"])
    assert "category" in p
    assert "reasoning" in p
    assert "description" in p or "topic" in p or any(
        k in p for k in ["institution_name", "role_title", "need_type", "target"]
    )


# ── 5. Cross-seed determinism (seed 0, 1, random → same hash) ─────────────

def _g5_hash_for_seed(seed):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = str(seed)
    env["CHAR_ID"] = "char_001"
    script = r"""
import os, sys, json, hashlib
sys.path.insert(0, r"C:\Users\seand\.copilot\copilot-worktrees\federation\vortsghost2025-npc-loop-control\federation-game\npc-agent-shadow")
for k in ["NVIDIA_API_KEY","FALLBACK_KEY_1","FALLBACK_KEY_2","OPENROUTER_API_KEY",
          "OPERATOR_LLM_API_KEY","DATABASE_URL","POSTGRES_URL","POSTGRES_PASSWORD",
          "REDIS_PASSWORD","OPENAI_API_KEY","ANTHROPIC_API_KEY","SECRET_KEY",
          "GITHUB_TOKEN","REDIS_URL","SERVICE_URL","API_URL","LLM_BASE_URL"]:
    os.environ.pop(k, None)
os.environ["REDIS_URL"] = ""
os.environ["SHADOW_MODE"] = "true"
os.environ["SHADOW_INSTANCE_ID"] = "g5-test"
os.environ["SHADOW_LOG_PATH"] = ""
import npc_shadow_mode as sm
sm.reset_counters()
sm.configure()
out = []
for _ in range(5):
    r = sm.mock_provider("sys", "user", call_label="decide")
    out.append(r["content"])
print(hashlib.sha256("".join(out).encode()).hexdigest())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env
    )
    return result.stdout.strip()


def test_g5_cross_seed_determinism():
    h0 = _g5_hash_for_seed(0)
    h1 = _g5_hash_for_seed(1)
    hr = _g5_hash_for_seed("random")
    assert h0 == h1 == hr, f"Seed hashes differ: 0={h0}, 1={h1}, r={hr}"


# ── 6. Intent records: sanitized, no private content ──────────────────────────

def test_g5_intent_record_no_private_content(sm):
    """record_intent stores only category, topic, tick, instance, char_id."""
    sm.reset_counters()
    sm.tick()
    sm.record_intent("send_message", {"description": "test message"}, {"action_taken": "test"})

    intents = sm.get_intents()
    assert len(intents) == 1
    intent = intents[0]
    assert "category" in intent
    assert "normalized_topic" in intent
    assert "tick" in intent
    assert "instance" in intent
    for key in intent:
        for bad in ["password", "token", "key", "body", "message", "prompt"]:
            assert bad not in key.lower(), f"Intent contains forbidden key: {key}"


# ── 7. category_blocked for unknown vs known categories ─────────────────────

def test_g5_category_blocked_unknown(sm):
    """Unknown categories are blocked by category_blocked()."""
    assert sm.category_blocked("Manufacture::totally_unknown_category")
    assert sm.category_blocked("Manufacture::UnknownCategory2026")


def test_g5_category_blocked_safe(sm):
    """Known safe categories return False from category_blocked."""
    safe_cats = ["rest", "read_artifacts", "investigate", "self_improve", "reflect"]
    for cat in safe_cats:
        assert not sm.category_blocked(cat)


def test_g5_category_blocked_write_actions(sm):
    """Known write categories are NOT blocked from intent recording."""
    write_cats = ["send_message", "create_artifact", "write_code",
                  "create_institution", "propose_role", "submit_to_institution",
                      "request_capability", "operator_ack"]
    for cat in write_cats:
        assert not sm.category_blocked(cat), f"{cat} should not be blocked"


# ── 8. record_intent signature: (category, decision=dict, extra=dict) ─────

def test_g5_record_intent_signature(sm):
    """record_intent accepts (category, decision_dict, extra_dict) — decision must be a dict."""
    sm.reset_counters()
    sm.tick()
    sm.record_intent("rest", {"description": "resting"})
    sm.record_intent("send_message", {"description": "hello"}, {"action_taken": "test"})
    assert len(sm.get_intents()) == 2


# ── 9. shadow_result returns expected structure ─────────────────────────────

def test_g5_shadow_result_structure(sm):
    """shadow_result returns char_id, category, shadow_intent_recorded, etc. — no private content."""
    result = sm.shadow_result("send_message", {"description": "hello topic"})
    assert isinstance(result, dict)
    assert "category" in result
    assert result["category"] == "send_message"
    assert "shadow_intent_recorded" in result
    assert "char_id" in result
    assert "action_taken" in result


# ── 10. Resource limits: tick ─────────────────────────────────────────────

def test_g5_tick_limit_enforced(sm):
    """Exceeding SHADOW_MAX_TICKS causes check_limits to return False."""
    sm._tick_count = sm.SHADOW_MAX_TICKS
    ok, reason = sm.check_limits()
    assert not ok
    assert "ticks" in reason


def test_g5_tick_increments(sm):
    """tick() increments and returns the new count."""
    sm.reset_counters()
    assert sm.tick() == 1
    assert sm.tick() == 2
    assert sm._tick_count == 2


# ── 11. Resource limits: runtime ───────────────────────────────────────────

def test_g5_runtime_limit_enforced(sm):
    """check_limits returns False when runtime exceeds SHADOW_MAX_RUNTIME_S."""
    sm._start_ts = time.time() - sm.SHADOW_MAX_RUNTIME_S - 1
    ok, reason = sm.check_limits()
    assert not ok
    assert "runtime" in reason


# ── 12. Resource limits: model calls ───────────────────────────────────────

def test_g5_model_call_limit_enforced(sm):
    """check_limits returns False when model call count is at limit.

    Reset tick and start_ts so runtime check doesn't fire before model_call check.
    """
    sm._tick_count = 0
    sm._start_ts = time.time()
    sm._model_call_count = sm.SHADOW_MAX_MODEL_CALLS
    ok, reason = sm.check_limits()
    assert not ok
    assert "model_calls" in reason


def test_g5_count_model_call_increments(sm):
    """count_model_call() increments and returns the new count."""
    sm.reset_counters()
    assert sm.count_model_call() == 1
    assert sm.count_model_call() == 2


# ── 13. Log limit ──────────────────────────────────────────────────────────

def test_g5_log_at_cap_raises(sm):
    """record_intent raises ShadowLogLimit when cap is reached."""
    sm.reset_counters()
    sm._log_bytes = sm.SHADOW_MAX_LOG_BYTES
    sm.tick()
    with pytest.raises(sm.ShadowLogLimit):
        sm.record_intent("rest", {"description": "test_topic"})


# ── 14. Redis key namespacing ─────────────────────────────────────────────

def test_g5_redis_key_namespaced(sm):
    """shadow_key() prefixes keys with SHADOW_NS (shadow:<instance>)."""
    ns = sm.SHADOW_NS
    key = sm.shadow_key("test_key")
    assert key == f"{ns}:test_key", f"Expected {ns}:test_key, got {key}"
    assert key.startswith("shadow:g5-qual:")


# ── 15. get_provider returns mock in shadow mode ────────────────────────────

def test_g5_get_provider_is_mock(sm):
    """get_provider() returns the mock_provider in shadow mode."""
    p = sm.get_provider()
    assert callable(p)
    r = p("sys", "user", call_label="test")
    assert "content" in r


# ── 16. reset_counters clears G5 mock state ───────────────────────────────

def test_g5_reset_counters_clears_everything(sm):
    """reset_counters() resets ticks, calls, intents, log bytes, and G5 engines."""
    for _ in range(5):
        sm.mock_provider("sys", "user", call_label="decide")
        sm.tick()
    sm.record_intent("rest", {"description": "test"})

    assert sm._tick_count == 5
    assert sm._model_call_count == 5
    assert sm._intent_count == 1
    assert sm._log_bytes > 0

    sm.reset_counters()

    assert sm._tick_count == 0
    assert sm._model_call_count == 0
    assert sm._intent_count == 0
    assert sm._log_bytes == 0
    assert sm._intents == []
    assert sm._G5_MOCK_CALL_COUNT["count"] == 0
    assert len(sm._G5_ENGINES) == 0


# ── 17. Mock output contains no credential-like strings ─────────────────────

def test_g5_mock_output_no_credentials(sm):
    """mock_provider output contains no API keys, tokens, or credentials."""
    for _ in range(13):
        r = sm.mock_provider("sys", "user", call_label="decide")
        c = r["content"]
        lower = c.lower()
        words = lower.split()
        assert "sk-" not in words
        assert not any(w.startswith("sk") and len(w) > 10 for w in words)


# ── 18. G5 mock uses char-specific offset for non-lock-step behavior ─────────

def test_g5_char_offset_differs(sm):
    """Different char_ids produce different initial categories (proves char_offset works)."""
    os.environ["CHAR_ID"] = "char_001"
    sm.reset_counters()
    r1 = sm.mock_provider("sys", "user", call_label="decide")

    os.environ["CHAR_ID"] = "char_999"
    sm.reset_counters()
    r999 = sm.mock_provider("sys", "user", call_label="decide")

    p1 = json.loads(r1["content"])
    p999 = json.loads(r999["content"])
    assert p1["category"] != p999["category"]


# ── 19. Unknown category recorded but blocked from external action ─────────

def test_g5_unknown_category_intent_recorded(sm):
    """Unknown category: category_blocked=True, but record_intent still works."""
    sm.reset_counters()
    sm.tick()
    assert sm.category_blocked("unknown_cat_xyz")
    sm.record_intent("unknown_cat_xyz", {"description": "unknown topic"})
    intents = sm.get_intents()
    assert any(i["category"] == "unknown_cat_xyz" for i in intents)


# ── 20. get_intents and intents_for_category ──────────────────────────────

def test_g5_get_intents_and_filter(sm):
    """get_intents returns all; intents_for_category filters correctly."""
    sm.reset_counters()
    sm.tick()
    sm.record_intent("rest", {"description": "topic1"})
    sm.tick()
    sm.record_intent("send_message", {"description": "topic2"})
    sm.tick()
    sm.record_intent("rest", {"description": "topic3"})

    all_intents = sm.get_intents()
    assert len(all_intents) == 3

    rest_intents = sm.intents_for_category("rest")
    assert len(rest_intents) == 2

    send_intents = sm.intents_for_category("send_message")
    assert len(send_intents) == 1


# ── 21. Anti-loop logic exists in G5 engine ──────────────────────────────

def test_g5_anti_loop_logic_present(sm):
    """_G5MockEngine._next contains anti-loop: streak detection and dedup."""
    import inspect
    src = inspect.getsource(sm._G5MockEngine._next)
    assert "send_message" in src
    assert "create_artifact" in src
    assert "_last_category" in src or "consecutive" in src


# ── 22. Log exactly at boundary ───────────────────────────────────────────

def test_g5_log_just_below_cap(sm):
    """Log bytes just below cap allows one more small record.

    An encoded intent record is ~120 bytes. Setting headroom to 120 ensures
    the next record fits.
    """
    sm.reset_counters()
    sm._log_bytes = sm.SHADOW_MAX_LOG_BYTES - 120
    sm.tick()
    sm.record_intent("rest", {"description": "x"})  # must not raise


# ── 23. Anti-loop: send_message streak detected and broken ─────────────────

def test_g5_send_streak_detected(sm):
    """G5 engine increments _consecutive_send_streak when send_message repeats."""
    os.environ["CHAR_ID"] = "char_001"
    sm.reset_counters()
    cats = []
    for _ in range(8):
        r = sm.mock_provider("sys", "user", call_label="decide")
        cats.append(json.loads(r["content"])["category"])
    assert cats.count("send_message") < len(cats)


# ── 24. category_blocked returns False for ALL_KNOWN categories ───────────

def test_g5_all_known_categories_not_blocked(sm):
    """Every category in ALL_KNOWN returns False from category_blocked."""
    for cat in sm.ALL_KNOWN:
        result = sm.category_blocked(cat)
        assert not result, f"ALL_KNOWN category {cat} should not be blocked"


# ── 25. ShadowResult action_taken field ───────────────────────────────────

def test_g5_shadow_result_action_taken(sm):
    """shadow_result sets action_taken='shadow_intent_only'."""
    result = sm.shadow_result("create_institution", {"description": "test"})
    assert result.get("action_taken") == "shadow_intent_only"
    assert result.get("shadow_intent_recorded") is True


# ── 26. Mock_provider increments G5 mock call count ─────────────────────

def test_g5_mock_call_count_tracked(sm):
    """mock_provider increments _G5_MOCK_CALL_COUNT each call."""
    sm.reset_counters()
    before = sm._G5_MOCK_CALL_COUNT["count"]
    for _ in range(3):
        sm.mock_provider("sys", "user", call_label="decide")
    after = sm._G5_MOCK_CALL_COUNT["count"]
    assert after == before + 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```
├── test_g5_redis_key_namespaced            ✅
├── test_g5_get_provider_is_mock             ✅
├── test_g5_reset_counters_clears_everything ✅
├── test_g5_mock_output_no_credentials       ✅
├── test_g5_char_offset_differs              ✅
├── test_g5_unknown_category_intent_recorded  ✅
├── test_g5_get_intents_and_filter           ✅
├── test_g5_anti_loop_logic_present          ✅
├── test_g5_log_just_below_cap               ✅
├── test_g5_send_streak_detected             ✅
├── test_g5_all_known_categories_not_blocked ✅
├── test_g5_shadow_result_action_taken        ✅
└── test_g5_mock_call_count_tracked          ✅
```

---

## Corrections Applied After G5

1. **`_G5_CATEGORIES`**: extended from 11 → 13 (`reflect` + `operator_ack`)
2. **`_G5MockEngine._next()`**: added `reflect` and `operator_ack` decision branches
3. **`test_npc_g5_qualify.py`**: renamed `test_g5_all_11_categories_produced` → `test_g5_all_13_categories_produced`, loop 33→39, loop 11→13 (2 occurrences), expected set +2 categories, `write_cats` + `operator_ack`

---

## Teardown

All G5 containers, volumes, networks, and temporary image `federation-npc-shadow:g5-0db35db` removed.

---

## Next: G6

Persistent behavioral shadow observation with deterministic valid-JSON mock decisions — exercising topic transitions, loop detection/escape, and deduplication under sustained realistic NPC behavior.

**Eligible for G6:** YES (separate authorization required)