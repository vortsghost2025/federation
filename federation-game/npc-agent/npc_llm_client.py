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
