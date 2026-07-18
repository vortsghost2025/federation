import json
import logging
import os
import random
import time

import httpx

logger = logging.getLogger("npc_llm_client")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
FALLBACK_KEY_1 = os.environ.get("FALLBACK_KEY_1", "") or None
FALLBACK_KEY_2 = os.environ.get("FALLBACK_KEY_2", "") or None
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "meta/llama-3.3-70b-instruct")
FALLBACK_MODEL_1 = os.environ.get("FALLBACK_MODEL_1", "") or None
FALLBACK_MODEL_2 = os.environ.get("FALLBACK_MODEL_2", "") or None
DECISION_MODEL = os.environ.get("DECISION_MODEL", FALLBACK_MODEL_1)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_FREE_POOL = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
]
_or_pool_idx = 0
MODEL_EXTRA_BODY = os.environ.get("MODEL_EXTRA_BODY", "")
MODEL_ENABLE_THINKING = os.environ.get("MODEL_ENABLE_THINKING", "").lower() in ("1", "true", "yes")
MODEL_REASONING_BUDGET = int(os.environ.get("MODEL_REASONING_BUDGET", "0") or "0")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "45"))
ARTIFACT_TIMEOUT = float(os.environ.get("ARTIFACT_TIMEOUT", "90"))
MAX_TOTAL_BUDGET_MS = int(os.environ.get("MAX_TOTAL_BUDGET_MS", "90000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
OR_BASE = "https://openrouter.ai/api/v1/chat/completions"

# ── Operator-only OpenRouter route (Patch A2 escalation tier) ────────────────
#
# Ordinary NPC cognition stays on the NVIDIA route. Only the two operator call
# labels (decide_operator / decide_operator_repair) may use this route, and
# ONLY when OPERATOR_ROUTE_ENABLED is an explicit truthy value AND the required
# operator configuration is complete. The route is OFF unless deliberately
# switched on, and any partial/invalid configuration fails CLOSED into the
# existing Patch A2 repair / truthful-failure path — it never falls back to a
# mixed NVIDIA+OpenRouter setup. All values are read at call time so runtime
# environment changes and monkeypatched tests take effect without a reload.

# Accepted spellings for the enable switch.
_OPERATOR_ENABLED_TRUE = {"true", "1", "yes", "on"}
_OPERATOR_ENABLED_FALSE = {"false", "0", "no", "off", ""}

# Safe bounds for operator route numeric configuration.
_OPERATOR_TIMEOUT_MIN = 1
_OPERATOR_TIMEOUT_MAX = 600
_OPERATOR_TOKENS_MIN = 1
_OPERATOR_TOKENS_MAX = 8192

# Required operator settings when the route is enabled.
OPERATOR_REQUIRED_KEYS = (
    "OPERATOR_LLM_BASE_URL",
    "OPERATOR_LLM_API_KEY",
    "OPERATOR_DECISION_MODEL",
    "OPERATOR_REQUEST_TIMEOUT",
    "OPERATOR_MAX_OUTPUT_TOKENS",
)


def _operator_route_config():
    """Resolve the operator route configuration.

    Returns a 2-tuple ``(config, error)``:
      * (False, None)            — route disabled (use NVIDIA fallback).
      * (None, "invalid_bool")   — OPERATOR_ROUTE_ENABLED present but unparseable;
                                    route disabled, caller should treat as safe error.
      * ("incomplete", <list>)   — enabled but required values missing; FAIL CLOSED
                                    (repair / truthful-failure, never NVIDIA mix).
      * (<dict>, None)           — enabled and valid; dict has base/key/model/
                                    timeout/tokens validated as positive ints.

    Read at call time so environment overrides apply immediately.
    """
    raw = (os.environ.get("OPERATOR_ROUTE_ENABLED") or "false").strip().lower()
    if raw not in _OPERATOR_ENABLED_TRUE and raw not in _OPERATOR_ENABLED_FALSE:
        return None, "invalid_bool"
    if raw not in _OPERATOR_ENABLED_TRUE:
        return False, None  # disabled (false / absent / 0 / no / off)

    base = (os.environ.get("OPERATOR_LLM_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("OPERATOR_LLM_API_KEY") or "").strip()
    model = (os.environ.get("OPERATOR_DECISION_MODEL") or "").strip()
    timeout_raw = (os.environ.get("OPERATOR_REQUEST_TIMEOUT") or "90").strip()
    tokens_raw = (os.environ.get("OPERATOR_MAX_OUTPUT_TOKENS") or "4096").strip()

    missing = [
        name for name, val in (
            ("OPERATOR_LLM_BASE_URL", base),
            ("OPERATOR_LLM_API_KEY", key),
            ("OPERATOR_DECISION_MODEL", model),
        ) if not val
    ]
    if missing:
        return "incomplete", missing  # fail closed

    try:
        timeout = int(timeout_raw)
    except ValueError:
        return "invalid_timeout", None
    if timeout < _OPERATOR_TIMEOUT_MIN or timeout > _OPERATOR_TIMEOUT_MAX:
        return "invalid_timeout", None

    try:
        tokens = int(tokens_raw)
    except ValueError:
        return "invalid_tokens", None
    if tokens < _OPERATOR_TOKENS_MIN or tokens > _OPERATOR_TOKENS_MAX:
        return "invalid_tokens", None

    return {"base": base, "key": key, "model": model, "timeout": timeout, "tokens": tokens}, None


def _api_key_for_model(model_name: str) -> str:
    primary = model_name == PRIMARY_MODEL or (not model_name)
    if primary:
        return NVIDIA_API_KEY
    if model_name == FALLBACK_MODEL_1 and FALLBACK_KEY_1:
        return FALLBACK_KEY_1
    if model_name == FALLBACK_MODEL_2 and FALLBACK_KEY_2:
        return FALLBACK_KEY_2
    return NVIDIA_API_KEY


def _call_openrouter_free(system_prompt: str, user_prompt: str, r=None, call_label: str = "") -> dict:
    global _or_pool_idx
    if not OPENROUTER_API_KEY or not OR_FREE_POOL:
        return {"content": "", "error": "No OPENROUTER_API_KEY or pool empty"}
    start = time.monotonic()
    tried = 0
    while tried < len(OR_FREE_POOL):
        model = OR_FREE_POOL[_or_pool_idx % len(OR_FREE_POOL)]
        _or_pool_idx += 1
        tried += 1
        try:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(
                    OR_BASE,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://federation.game",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("[%s] OR free OK — model: %s (%dms)", CHAR_ID, model, elapsed_ms)
                if r:
                    from npc_redis_helpers import _log_llm_call
                    _log_llm_call(r, call_label, model, system_prompt, user_prompt, content, True, "", elapsed_ms)
                return {"content": content, "model": model, "provider": "openrouter_free"}
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = getattr(e, "response", None)
            status_code = getattr(status, "status_code", 0) if status else 0
            err_msg = str(e)[:200]
            logger.warning("[%s] OR free %s failed (HTTP %s, %dms): %s", CHAR_ID, model, status_code, elapsed_ms, err_msg)
            if status_code in (400, 401, 403, 404):
                continue
            if status_code == 429:
                time.sleep(random.uniform(1.0, 3.0))
            if r:
                from npc_redis_helpers import _log_llm_call
                _log_llm_call(r, call_label, model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
    logger.error("[%s] All %d OR free models failed", CHAR_ID, len(OR_FREE_POOL))
    return {"content": "", "error": "All OR free models failed"}



def call_llm_operator(system_prompt: str, user_prompt: str, r=None, call_label: str = "", is_repair: bool = False) -> dict:
    """Operator-only OpenRouter route used by decide_operator / decide_operator_repair.

    Ordinary cognition must NOT call this. The route is OFF unless
    OPERATOR_ROUTE_ENABLED is an explicit truthy value AND the required
    operator configuration is complete.

    Returned dict ALWAYS carries a per-call ``attribution`` object so the exact
    provider/model used is attached to the specific decision and cannot be
    overwritten by a later call:

        {"content": "...", "attribution": {
            "requested_model": "openrouter/free",
            "actual_model": "...",
            "provider": "operator_openrouter",
            "error_category": "",
            "is_repair": False,
        }}

    No prompt, key, or moderator body is ever placed in logs.

    Resolution (see _operator_route_config):
      * disabled            -> {"content": "", "error": "operator route disabled", ...}
                               so the caller falls back to the NVIDIA route.
      * invalid bool        -> {"content": "", "error": "operator route misconfigured:
                               invalid_bool", ...} (route disabled, safe error).
      * enabled + incomplete -> FAILS CLOSED: returns empty content with
                               error_category "config_incomplete" so the Patch A2
                               repair / truthful-failure path engages. It never
                               mixes an OpenRouter key with the NVIDIA URL.
      * enabled + valid     -> performs the OpenRouter chat completion and returns
                               the content with attribution populated.
    """
    cfg, err = _operator_route_config()

    if cfg is False:
        # Route disabled -> caller falls back to NVIDIA unchanged.
        logger.info("[%s] operator route disabled; caller uses NVIDIA", CHAR_ID)
        return {
            "content": "",
            "error": "operator route disabled",
            "attribution": {
                "requested_model": (os.environ.get("OPERATOR_DECISION_MODEL") or "").strip(),
                "actual_model": "",
                "provider": "operator_openrouter",
                "error_category": "disabled",
                "is_repair": is_repair,
            },
        }

    if cfg is None:
        # Invalid boolean spelling -> route disabled with a safe config error.
        logger.warning("[%s] operator route misconfigured: %s", CHAR_ID, err)
        return {
            "content": "",
            "error": f"operator route misconfigured: {err}",
            "attribution": {
                "requested_model": (os.environ.get("OPERATOR_DECISION_MODEL") or "").strip(),
                "actual_model": "",
                "provider": "operator_openrouter",
                "error_category": "config_error",
                "is_repair": is_repair,
            },
        }

    if cfg == "incomplete":
        # Enabled but missing required values -> FAIL CLOSED, never NVIDIA mix.
        missing = err or []
        logger.error("[%s] operator route enabled but incomplete, missing: %s", CHAR_ID, ", ".join(missing))
        return {
            "content": "",
            "error": f"operator route incomplete: {', '.join(missing)}",
            "attribution": {
                "requested_model": os.environ.get("OPERATOR_DECISION_MODEL", "").strip(),
                "actual_model": "",
                "provider": "operator_openrouter",
                "error_category": "config_incomplete",
                "is_repair": is_repair,
            },
        }

    # cfg is a validated dict: base/key/model/timeout/tokens.
    requested_model = cfg["model"]
    start = time.monotonic()
    try:
        body = {
            "model": requested_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": cfg["tokens"],
        }
        with httpx.Client(timeout=cfg["timeout"]) as client:
            resp = client.post(
                f"{cfg['base']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg['key']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://federation.game",
                },
                json=body,
            )
            status_code = getattr(resp, "status_code", None)
            if status_code == 429:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.warning("[%s] operator route 429 (call=%s, %dms)", CHAR_ID, call_label, elapsed_ms)
                return {"content": "", "error": "429 rate limit", "attribution": {
                    "requested_model": requested_model, "actual_model": "",
                    "provider": "operator_openrouter", "error_category": "rate_limit", "is_repair": is_repair}}
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            content = content.strip()
            actual_model = data.get("model", requested_model)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if not content:
                logger.warning("[%s] operator route empty content (call=%s, %dms)", CHAR_ID, call_label, elapsed_ms)
                return {"content": "", "error": "empty content", "attribution": {
                    "requested_model": requested_model, "actual_model": actual_model,
                    "provider": "operator_openrouter", "error_category": "empty_content", "is_repair": is_repair}}
            logger.info("[%s] operator route OK (call=%s, requested=%s, actual=%s, %dms)", CHAR_ID, call_label, requested_model, actual_model, elapsed_ms)
            if r:
                from npc_redis_helpers import _log_llm_call
                _log_llm_call(r, call_label, actual_model, system_prompt, user_prompt, content, True, "", elapsed_ms)
            return {"content": content, "model": actual_model, "attribution": {
                "requested_model": requested_model, "actual_model": actual_model,
                "provider": "operator_openrouter", "error_category": "", "is_repair": is_repair}}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        status = getattr(e, "response", None)
        status_code = getattr(status, "status_code", 0) if status else 0
        err_msg = str(e)[:200]
        # classify error category
        if status_code == 429:
            category = "rate_limit"
        elif status_code in (404, 400, 422):
            category = "unavailable_model"
        elif "timeout" in err_msg.lower() or isinstance(e, httpx.TimeoutException):
            category = "timeout"
        elif "json" in err_msg.lower() or "expecting value" in err_msg.lower():
            category = "malformed_response"
        else:
            category = "provider_error"
        logger.warning("[%s] operator route failed (call=%s, category=%s, HTTP %s, %dms): %s", CHAR_ID, call_label, category, status_code, elapsed_ms, err_msg)
        if r:
            from npc_redis_helpers import _log_llm_call
            _log_llm_call(r, call_label, requested_model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
        return {"content": "", "error": err_msg, "attribution": {
            "requested_model": requested_model, "actual_model": "",
            "provider": "operator_openrouter", "error_category": category, "is_repair": is_repair}}
def call_llm(system_prompt: str, user_prompt: str, model: str = "", r=None, call_label: str = "") -> dict:
    from npc_redis_helpers import _log_llm_call

    models_to_try = []
    if NVIDIA_API_KEY:
        if model:
            models_to_try.append(model)
        if PRIMARY_MODEL:
            models_to_try.append(PRIMARY_MODEL)
        if FALLBACK_MODEL_1:
            models_to_try.append(FALLBACK_MODEL_1)
        if FALLBACK_MODEL_2:
            models_to_try.append(FALLBACK_MODEL_2)
    elif not OPENROUTER_API_KEY:
        return {"content": "", "error": "No NVIDIA_API_KEY or OPENROUTER_API_KEY set"}
    if not models_to_try and OPENROUTER_API_KEY:
        logger.info("[%s] No NIM models configured, going straight to OR free pool", CHAR_ID)
        return _call_openrouter_free(system_prompt, user_prompt, r, call_label)
    if not models_to_try:
        return {"content": "", "error": "No models configured"}

    timeout = ARTIFACT_TIMEOUT if call_label in ("artifact", "code") else REQUEST_TIMEOUT

    last_error = ""
    total_start = time.monotonic()
    for attempt_model in models_to_try:
        if (time.monotonic() - total_start) * 1000 > MAX_TOTAL_BUDGET_MS:
            logger.warning("[%s] Total budget %dms exceeded, aborting fallback chain", CHAR_ID, MAX_TOTAL_BUDGET_MS)
            last_error = f"Total budget {MAX_TOTAL_BUDGET_MS}ms exceeded"
            break

        attempt_key = _api_key_for_model(attempt_model)
        key_tag = "primary" if attempt_key == NVIDIA_API_KEY else "fallback"
        start = time.monotonic()
        try:
            body = {
                "model": attempt_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            if MODEL_EXTRA_BODY:
                try:
                    extra = json.loads(MODEL_EXTRA_BODY)
                    body.update(extra)
                except json.JSONDecodeError:
                    pass
            if MODEL_ENABLE_THINKING and MODEL_REASONING_BUDGET > 0:
                body.setdefault("extra_body", {})
                body["extra_body"]["chat_template_kwargs"] = {"enable_thinking": True}
                body["extra_body"]["reasoning_budget"] = min(MODEL_REASONING_BUDGET, MAX_OUTPUT_TOKENS // 2)

            attempt_key = _api_key_for_model(attempt_model)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{NVIDIA_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {attempt_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("[%s] LLM OK — model: %s (%dms)", CHAR_ID, attempt_model, elapsed_ms)
                if r:
                    _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, content, True, "", elapsed_ms)
                return {"content": content, "model": attempt_model}
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = getattr(e, "response", None)
            status_code = getattr(status, "status_code", 0) if status else 0
            err_msg = str(e)[:200]
            if attempt_model == PRIMARY_MODEL:
                logger.warning(
                    "[%s] PRIMARY_MODEL %s failed (HTTP %s, %dms): %s — falling back",
                    CHAR_ID, attempt_model, status_code, elapsed_ms, err_msg,
                )
            else:
                logger.warning(
                    "[%s] FALLBACK_MODEL %s failed (HTTP %s, %dms): %s — trying next",
                    CHAR_ID, attempt_model, status_code, elapsed_ms, err_msg,
                )
            if status_code in (400, 401, 403, 404):
                logger.warning("[%s] Skipping permanent failure %s for %s", CHAR_ID, status_code, attempt_model)
                if r:
                    _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, f"HTTP {status_code}", elapsed_ms)
                last_error = f"HTTP {status_code}"
                continue
            if status_code == 429:
                jitter = random.uniform(1.0, 5.0)
                logger.info("[%s] 429 rate limit on %s — backing off %.1fs before fallback", CHAR_ID, attempt_model, jitter)
                time.sleep(jitter)
            if r:
                _log_llm_call(r, call_label, attempt_model, system_prompt, user_prompt, "", False, err_msg, elapsed_ms)
            last_error = err_msg
            continue

    logger.warning("[%s] All %d NIM models failed, trying OpenRouter free pool. Last error: %s", CHAR_ID, len(models_to_try), last_error)
    or_result = _call_openrouter_free(system_prompt, user_prompt, r, call_label)
    if or_result.get("content"):
        return or_result
    logger.error("[%s] All NIM + OR free models failed. Last NIM: %s | OR: %s", CHAR_ID, last_error, or_result.get("error", ""))
    return {"content": "", "error": f"All models failed. NIM: {last_error}; OR: {or_result.get('error', '')}"}
