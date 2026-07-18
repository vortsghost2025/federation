"""Focused tests for the operator-only OpenRouter route (single-switch config).

These tests prove:

Config switch (on npc_llm_client._operator_route_config):
  1.  Route disabled by default (no env) -> (False, None).
  2.  Each accepted FALSE spelling -> (False, None).
  3.  Each accepted TRUE spelling -> config path taken (dict or incomplete/None).
  4.  Invalid boolean spelling -> (None, "invalid_bool").
  5.  Enabled + missing base URL -> FAIL CLOSED ("incomplete").
  6.  Enabled + missing API key   -> FAIL CLOSED ("incomplete").
  7.  Enabled + missing model     -> FAIL CLOSED ("incomplete").
  8.  Invalid timeout value        -> (None, "invalid_timeout").
  9.  Invalid token limit          -> (None, "invalid_tokens").

Routing (on npc_decisions._decide_operator_response, monkeypatched clients):
 10.  NVIDIA ordinary call unchanged (decide_action never calls operator route).
 11.  Operator initial call uses OpenRouter route (decide_operator).
 12.  Operator repair call uses the same OpenRouter route.
 13.  Requested model stays openrouter/free; actual model is captured distinctly.
 14.  Two sequential mocked operator calls cannot exchange attribution.
 15.  No API key, prompt, or response body appears in logs.
 16.  OpenRouter 429 / timeout enters the repair / truthful-failure path.

Compose (rendered docker-compose config):
 17.  Compose defaults leave Oracle operator routing disabled.
 18.  Compose switch enables the operator route only for Oracle (npc-agent-306),
      never for Archimedes (npc-agent-001).

No network or live key is touched. The operator client is exercised through a
fake httpx.Client. Decision routing is exercised by monkeypatching
npc_decisions.call_llm_operator and call_llm.
"""

import io
import json
import logging
import os

import pytest

import npc_llm_client as llc
import npc_decisions as nd

# Operator env vars the route reads (set in tests that need an enabled route).
_OP_VARS = (
    "OPERATOR_ROUTE_ENABLED",
    "OPERATOR_LLM_BASE_URL",
    "OPERATOR_DECISION_MODEL",
    "OPERATOR_LLM_API_KEY",
    "OPERATOR_REQUEST_TIMEOUT",
    "OPERATOR_MAX_OUTPUT_TOKENS",
)


def _clear_op_env(monkeypatch):
    for v in _OP_VARS:
        monkeypatch.delenv(v, raising=False)


def _enable_op_env(monkeypatch, base_url="https://openrouter.ai/api/v1",
                   model="openrouter/free", key="sk-or-test-xxxx",
                   timeout="90", tokens="4096"):
    _clear_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_ROUTE_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_LLM_BASE_URL", base_url)
    monkeypatch.setenv("OPERATOR_DECISION_MODEL", model)
    monkeypatch.setenv("OPERATOR_LLM_API_KEY", key)
    monkeypatch.setenv("OPERATOR_REQUEST_TIMEOUT", timeout)
    monkeypatch.setenv("OPERATOR_MAX_OUTPUT_TOKENS", tokens)


# ---------------------------------------------------------------------------
# 1. Route disabled by default.
# ---------------------------------------------------------------------------
def test_route_disabled_by_default(monkeypatch):
    _clear_op_env(monkeypatch)
    cfg, err = llc._operator_route_config()
    assert cfg is False
    assert err is None


# ---------------------------------------------------------------------------
# 2. Each accepted FALSE spelling -> route disabled.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val", ["false", "0", "no", "off", ""])
def test_route_disabled_false_spellings(monkeypatch, val):
    _clear_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_ROUTE_ENABLED", val)
    cfg, err = llc._operator_route_config()
    assert cfg is False
    assert err is None


# ---------------------------------------------------------------------------
# 3. Each accepted TRUE spelling -> config path taken (complete here).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val", ["true", "1", "yes", "on"])
def test_route_enabled_true_spellings(monkeypatch, val):
    _enable_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_ROUTE_ENABLED", val)
    cfg, err = llc._operator_route_config()
    assert err is None
    assert isinstance(cfg, dict)
    assert cfg["base"] == "https://openrouter.ai/api/v1"
    assert cfg["model"] == "openrouter/free"
    assert cfg["key"] == "sk-or-test-xxxx"
    assert cfg["timeout"] == 90
    assert cfg["tokens"] == 4096


# ---------------------------------------------------------------------------
# 4. Invalid boolean spelling -> route disabled with safe config error.
# ---------------------------------------------------------------------------
def test_route_invalid_bool(monkeypatch):
    _clear_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_ROUTE_ENABLED", "maybe")
    cfg, err = llc._operator_route_config()
    assert cfg is None
    assert err == "invalid_bool"


# ---------------------------------------------------------------------------
# 5/6/7. Enabled + a required value missing -> FAIL CLOSED (never NVIDIA mix).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("missing,var", [
    ("base", "OPERATOR_LLM_BASE_URL"),
    ("key", "OPERATOR_LLM_API_KEY"),
    ("model", "OPERATOR_DECISION_MODEL"),
])
def test_route_enabled_missing_value_fails_closed(monkeypatch, missing, var):
    _enable_op_env(monkeypatch)
    monkeypatch.delenv(var, raising=False)
    cfg, err = llc._operator_route_config()
    assert cfg == "incomplete"
    assert var in err


# ---------------------------------------------------------------------------
# 8. Invalid timeout -> safe config error (must be positive int within max).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["abc", "0", "-5", "999999", "1.5"])
def test_route_invalid_timeout(monkeypatch, bad):
    _enable_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_REQUEST_TIMEOUT", bad)
    cfg, err = llc._operator_route_config()
    assert cfg == "invalid_timeout"
    assert err is None


# ---------------------------------------------------------------------------
# 9. Invalid token limit -> safe config error.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["abc", "0", "-1", "1000000", "2.0"])
def test_route_invalid_tokens(monkeypatch, bad):
    _enable_op_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_MAX_OUTPUT_TOKENS", bad)
    cfg, err = llc._operator_route_config()
    assert cfg == "invalid_tokens"
    assert err is None


# ---------------------------------------------------------------------------
# Fake httpx plumbing for exercising the real call_llm_operator.
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler
        self.last_post = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.last_post = (url, headers, json)
        return self._handler(url, headers, json)


def _operator_directive():
    return {
        "id": "msg_testop123",
        "msg_id": "msg_testop123",
        "subject": "Final report",
        "body": (
            "Produce the report with these sections:\n"
            "1. Prioritized Criteria\n"
            "2. Quantitative Metrics and Suggested Thresholds\n"
            "3. Sector Comparison Method\n"
            "4. Risk and Ethical Safeguards\n"
            "5. Final Recommendation"
        ),
    }


def _good_body():
    return (
        "1. Prioritized Criteria: depth over volume. "
        "2. Quantitative Metrics and Suggested Thresholds: score>0.7. "
        "3. Sector Comparison Method: normalized delta rank. "
        "4. Risk and Ethical Safeguards: anonymize sources. "
        "5. Final Recommendation: adopt deep-signal rubric."
    )


# ---------------------------------------------------------------------------
# 10. Ordinary decide_action never calls the operator route.
# ---------------------------------------------------------------------------
def test_ordinary_decide_uses_nvidia_not_operator(monkeypatch):
    used_operator = []
    used_nvidia = []

    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        used_operator.append(call_label)
        return {"content": "{}", "error": "forced",
                "attribution": {"requested_model": "", "actual_model": "",
                                "provider": "operator_openrouter",
                                "error_category": "forced", "is_repair": is_repair}}

    def fake_nvidia(system_prompt, user_prompt, model="", r=None, call_label=""):
        used_nvidia.append(call_label)
        return {"content": json.dumps({"category": "investigate", "target": "char_001",
                                       "description": "o", "reasoning": "o"}), "error": None}

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", fake_nvidia)
    monkeypatch.setattr(nd, "CHAR_ID", "char_001")

    nd.decide_action("ordinary context", r=None)
    assert used_operator == [], "ordinary decide must never call operator route"
    assert any(c == "decide" for c in used_nvidia), "ordinary decide must call NVIDIA route"


# ---------------------------------------------------------------------------
# 11. Operator initial call uses the OpenRouter route.
# ---------------------------------------------------------------------------
def test_decide_operator_uses_operator_route(monkeypatch):
    seen = []

    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        seen.append((call_label, is_repair))
        return {
            "content": json.dumps({"category": "send_message", "target": "moderator",
                                   "body": _good_body(), "description": "r", "reasoning": "r"}),
            "error": None,
            "attribution": {"requested_model": "openrouter/free",
                            "actual_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                            "provider": "operator_openrouter", "error_category": "",
                            "is_repair": is_repair},
        }

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("NVIDIA must not be used for operator")))
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")

    decision = nd._decide_operator_response(_operator_directive(), "ctx", r=None)
    assert ("decide_operator", False) in seen
    assert decision["operator_response_status"] == "complete"
    assert decision["operator_directive_id"] == "msg_testop123"
    assert decision["operator_attribution"]["requested_model"] == "openrouter/free"
    assert decision["operator_attribution"]["actual_model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"


# ---------------------------------------------------------------------------
# 12. Operator repair call uses the same OpenRouter route.
# ---------------------------------------------------------------------------
def test_decide_operator_repair_uses_same_operator_route(monkeypatch):
    seen = []

    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        seen.append((call_label, is_repair))
        if is_repair:
            return {"content": json.dumps({"category": "send_message", "target": "moderator",
                                           "body": _good_body(), "description": "r", "reasoning": "r"}),
                    "error": None,
                    "attribution": {"requested_model": "openrouter/free",
                                    "actual_model": "meta-llama/llama-3.3-70b-instruct:free",
                                    "provider": "operator_openrouter", "error_category": "",
                                    "is_repair": is_repair}}
        # initial attempt weak (missing labels) -> forces repair
        return {"content": json.dumps({"category": "send_message", "target": "moderator",
                                       "body": "report complete", "description": "r", "reasoning": "r"}),
                "error": None,
                "attribution": {"requested_model": "openrouter/free",
                                "actual_model": "nvidia/nemotron-3-nano-30b-a3b:free",
                                "provider": "operator_openrouter", "error_category": "",
                                "is_repair": is_repair}}

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("NVIDIA must not be used for operator")))
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")

    decision = nd._decide_operator_response(_operator_directive(), "ctx", r=None)
    assert ("decide_operator", False) in seen
    assert ("decide_operator_repair", True) in seen
    assert decision["operator_response_status"] == "complete"
    # repair's actual model is the one bound to this decision
    assert decision["operator_attribution"]["actual_model"] == "meta-llama/llama-3.3-70b-instruct:free"


# ---------------------------------------------------------------------------
# 13. Requested stays openrouter/free; actual captured; distinct values.
# ---------------------------------------------------------------------------
def test_operator_captures_actual_model_and_requested(monkeypatch):
    captured = {}

    def handler(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return _FakeResp({"model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                          "choices": [{"message": {"content": "hello operator"}}]})

    _enable_op_env(monkeypatch)
    monkeypatch.setattr(llc.httpx, "Client", lambda *a, **k: _FakeClient(handler))

    res = llc.call_llm_operator("sys", "usr", r=None, call_label="decide_operator")
    assert res["attribution"]["requested_model"] == "openrouter/free"
    assert res["attribution"]["actual_model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert res["content"] == "hello operator"
    assert captured["url"].endswith("/chat/completions")
    # key transmitted but never logged; value is the configured key
    assert captured["headers"]["Authorization"] == "Bearer sk-or-test-xxxx"
    assert captured["body"]["model"] == "openrouter/free"
    assert captured["body"]["max_tokens"] == 4096
    assert captured["body"]["temperature"] == 0.7


# ---------------------------------------------------------------------------
# 14. Two sequential mocked operator calls cannot exchange attribution.
# ---------------------------------------------------------------------------
def test_sequential_calls_cannot_exchange_attribution(monkeypatch):
    def handler(url, headers, body):
        # The fake returns the SAME requested model each time; we tag the
        # actual model with a per-call marker derived from call order via the
        # prompt, proving the returned attribution belongs to its own call.
        marker = body["messages"][1]["content"]
        return _FakeResp({"model": f"actual-for-{marker}",
                          "choices": [{"message": {"content": f"reply-{marker}"}}]})

    _enable_op_env(monkeypatch)
    monkeypatch.setattr(llc.httpx, "Client", lambda *a, **k: _FakeClient(handler))

    r1 = llc.call_llm_operator("s1", "CALL_A", r=None, call_label="decide_operator")
    r2 = llc.call_llm_operator("s2", "CALL_B", r=None, call_label="decide_operator_repair")

    # Each result's content/actual_model must match its own returned payload.
    assert r1["content"] == "reply-CALL_A"
    assert r1["attribution"]["actual_model"] == "actual-for-CALL_A"
    assert r2["content"] == "reply-CALL_B"
    assert r2["attribution"]["actual_model"] == "actual-for-CALL_B"
    # Crucially: r1 attribution was NOT overwritten by r2.
    assert r1["attribution"]["actual_model"] != r2["attribution"]["actual_model"]
    assert r1["attribution"] is not r2["attribution"]
    assert r1["attribution"]["requested_model"] == r2["attribution"]["requested_model"] == "openrouter/free"


# ---------------------------------------------------------------------------
# 15. No API key, prompt, or response body appears in logs.
# ---------------------------------------------------------------------------
def test_no_secret_or_body_in_logs(monkeypatch):
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    logger = logging.getLogger("npc_llm_client")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    def handler_fn(url, headers, body):
        return _FakeResp({"model": "x", "choices": [{"message": {"content": "SECRET_BODY_MARKER"}}]})

    _enable_op_env(monkeypatch, key="sk-or-SENSITIVEKEY123")
    monkeypatch.setattr(llc.httpx, "Client", lambda *a, **k: _FakeClient(handler_fn))

    llc.call_llm_operator("SYSTEM_PROMPT_MARKER", "USER_PROMPT_MARKER", r=None, call_label="decide_operator")

    logger.removeHandler(handler)
    logger.setLevel(old_level)

    logs = log_capture.getvalue()
    assert "SENSITIVEKEY123" not in logs, "API key must not appear in logs"
    assert "SYSTEM_PROMPT_MARKER" not in logs, "system prompt must not appear in logs"
    assert "USER_PROMPT_MARKER" not in logs, "user prompt must not appear in logs"
    assert "SECRET_BODY_MARKER" not in logs, "response body must not appear in logs"


# ---------------------------------------------------------------------------
# 16. OpenRouter 429 / timeout enters the repair / truthful-failure path.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("error_category", ["rate_limit", "timeout"])
def test_operator_failure_enters_truthful_failure(monkeypatch, error_category):
    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        return {"content": "", "error": error_category,
                "attribution": {"requested_model": "openrouter/free", "actual_model": "",
                                "provider": "operator_openrouter", "error_category": error_category,
                                "is_repair": is_repair}}

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("NVIDIA must not be used")))
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")

    decision = nd._decide_operator_response(_operator_directive(), "ctx", r=None)
    assert decision["operator_response_status"] == "failed"
    # truthful message, not rest/artifact/partner
    assert decision["category"] == "send_message"
    assert decision["target"] == "moderator"
    assert "could not produce" in decision["body"]


# ---------------------------------------------------------------------------
# 16b. Enabled + missing config FAILS CLOSED (no NVIDIA fallback).
# ---------------------------------------------------------------------------
def test_enabled_missing_config_fails_closed_not_nvidia(monkeypatch):
    used_nvidia = []

    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        # emulate call_llm_operator with incomplete config
        return {"content": "", "error": "operator route incomplete: OPERATOR_LLM_API_KEY",
                "attribution": {"requested_model": "openrouter/free", "actual_model": "",
                                "provider": "operator_openrouter", "error_category": "config_incomplete",
                                "is_repair": is_repair}}

    def fake_nvidia(system_prompt, user_prompt, model="", r=None, call_label=""):
        used_nvidia.append(call_label)
        return {"content": json.dumps({"category": "send_message", "target": "moderator",
                                       "body": _good_body(), "description": "r", "reasoning": "r"}), "error": None}

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", fake_nvidia)
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")

    decision = nd._decide_operator_response(_operator_directive(), "ctx", r=None)
    assert used_nvidia == [], "fail-closed config must NOT fall back to NVIDIA"
    assert decision["operator_response_status"] == "failed"


# ---------------------------------------------------------------------------
# 16c. Route disabled (default) falls back to NVIDIA behavior cleanly.
# ---------------------------------------------------------------------------
def test_disabled_route_falls_back_to_nvidia(monkeypatch):
    used_nvidia = []
    seen_op = []

    def fake_operator(system_prompt, user_prompt, r=None, call_label="", is_repair=False):
        seen_op.append(call_label)
        return {"content": "", "error": "operator route disabled",
                "attribution": {"requested_model": "", "actual_model": "",
                                "provider": "operator_openrouter", "error_category": "disabled",
                                "is_repair": is_repair}}

    def fake_nvidia(system_prompt, user_prompt, model="", r=None, call_label=""):
        used_nvidia.append(call_label)
        return {"content": json.dumps({"category": "send_message", "target": "moderator",
                                       "body": _good_body(), "description": "r", "reasoning": "r"}), "error": None}

    monkeypatch.setattr(nd, "call_llm_operator", fake_operator)
    monkeypatch.setattr(nd, "call_llm", fake_nvidia)
    monkeypatch.setattr(nd, "CHAR_ID", "char_306")

    decision = nd._decide_operator_response(_operator_directive(), "ctx", r=None)
    assert seen_op == ["decide_operator"], "operator route attempted once then fallback"
    assert "decide_operator" in used_nvidia, "fallback must use NVIDIA route"
    assert decision["operator_response_status"] == "complete"


# ---------------------------------------------------------------------------
# 17/18. Compose rendering: Oracle disabled by default; switch enables only 306.
# ---------------------------------------------------------------------------
def _render_compose_enable(enabled: bool) -> str:
    import subprocess
    import tempfile

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    compose_dir = os.path.join(repo_root, "federation-game")
    # Docker Compose always auto-loads federation-game/.env (project dir). A
    # detached bare-HEAD worktree has no .env, which makes `config` fatal. We
    # therefore write a TEMPORARY fake .env (no real secret) alongside the
    # temp --env-file so the render is clean-worktree independent. Both are
    # removed afterwards. The rendered output must contain only ${...}
    # references, never a real key value.
    env_lines = [
        "OPENROUTER_API_KEY_1=fake-openrouter-key-1",
        "ORACLE_OPERATOR_LLM_BASE_URL=https://openrouter.ai/api/v1",
        "ORACLE_OPERATOR_DECISION_MODEL=openrouter/free",
        "ORACLE_OPERATOR_REQUEST_TIMEOUT=90",
        "ORACLE_OPERATOR_MAX_OUTPUT_TOKENS=4096",
        "ORACLE_OPERATOR_ROUTE_ENABLED=" + ("true" if enabled else "false"),
    ]
    env_text = "\n".join(env_lines) + "\n"
    tmp_env = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", dir=compose_dir, delete=False, encoding="utf-8",
    )
    tmp_env.write(env_text)
    tmp_env.close()
    project_env = os.path.join(compose_dir, ".env")
    wrote_project_env = False
    if not os.path.exists(project_env):
        with open(project_env, "w", encoding="utf-8") as fh:
            fh.write(env_text)
        wrote_project_env = True
    try:
        # Strip any real secret/operator vars from the inherited environment so
        # they can never leak into the rendered output.
        env_for_subprocess = {k: v for k, v in os.environ.items()
                              if not k.startswith("ORACLE_OPERATOR")
                              and k != "OPENROUTER_API_KEY"
                              and not k.startswith("OPERATOR_")}
        env_for_subprocess["OPENROUTER_API_KEY_1"] = "fake-openrouter-key-1"
        out = subprocess.run(
            ["docker", "compose", "-f", "federation-game/docker-compose.yml",
             "--env-file", tmp_env.name, "config"],
            cwd=repo_root, capture_output=True, text=True, env=env_for_subprocess,
        )
        return out.stdout
    finally:
        os.unlink(tmp_env.name)
        if wrote_project_env:
            os.unlink(project_env)


def _service_block(text: str, svc: str, stop: str) -> str:
    start = text.index(svc + ":")
    end = text.index(stop + ":", start)
    return text[start:end]


def test_compose_defaults_oracle_disabled(monkeypatch):
    text = _render_compose_enable(False)
    assert "sk-" not in text, "no OpenRouter secret value may appear in rendered compose"
    assert "OPENROUTER_API_KEY" in text, "key must remain a ${...} reference"
    block = _service_block(text, "npc-agent-306", "npc-sandbox")
    assert 'OPERATOR_ROUTE_ENABLED: "false"' in block
    # Archimedes must NOT carry operator vars
    block1 = _service_block(text, "npc-agent-001", "npc-agent-306")
    assert "OPERATOR_ROUTE_ENABLED" not in block1
    assert "OPERATOR_LLM_BASE_URL" not in block1


def test_compose_switch_enables_only_oracle(monkeypatch):
    text = _render_compose_enable(True)
    assert "sk-" not in text, "no OpenRouter secret value may appear in rendered compose"
    block = _service_block(text, "npc-agent-306", "npc-sandbox")
    assert 'OPERATOR_ROUTE_ENABLED: "true"' in block
    assert "OPERATOR_DECISION_MODEL: openrouter/free" in block
    # Archimedes still has no operator route
    block1 = _service_block(text, "npc-agent-001", "npc-agent-306")
    assert "OPERATOR_ROUTE_ENABLED" not in block1
