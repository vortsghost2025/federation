#!/usr/bin/env python3
"""
FEDERATION GAME — LLM Router

Multi-provider routing layer for tiered NPC cognition.
Supports Ollama, Cloudflare Workers AI, Together AI, NVIDIA NIM,
Google Gemini, Grok/xAI, and OpenRouter — with automatic fallback.

Design principles:
- Multi-provider: Ollama(3B/7B) → Cloudflare → Together → NIM → Gemini → Grok → OpenRouter
- Key rotation for NIM (up to 8 keys, round-robin with least-recently-used)
- Per-provider rate limit awareness (Redis-backed call tracking)
- Per-provider circuit breaker (3 consecutive failures → 5 min cooldown)
- Task-class routing: leader/specialist/worker/narrator → different models
- Ollama resource safety: 3B default, 7B only with OLLAMA_HEAVY_ENABLED=1
- Ollama backpressure: max 1 active call, queue=3, cooldown 60s on 500s
- Audit logging to Redis

Fallback chain (route_call):
  Ollama(3B) → Cloudflare → Together → NIM primary → NIM fallback
  → Gemini → Grok → OpenRouter → template fallback

Redis keys:
llm_call_log:{provider} — ZSET (score=timestamp) of recent calls
llm_key_last_used:{key_hash} — STRING timestamp
llm_errors:{provider} — ZSET of recent errors
llm_audit — ZSET of all LLM calls (TTL 7d)
llm_circuit_breaker:{provider} — STRING circuit breaker state
"""

import hashlib
import json
import logging
import os
import random
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ── Provider Configuration ──────────────────────────────────────────

# NIM keys — comma-separated in env var, rotated round-robin
_NIM_KEYS_RAW = os.environ.get("NIM_API_KEYS", "")
NIM_KEYS = [k.strip() for k in _NIM_KEYS_RAW.split(",") if k.strip()]

# Also check individual key env vars (NIM_API_KEY_1 through NIM_API_KEY_8)
for _i in range(1, 9):
    _k = os.environ.get(f"NIM_API_KEY_{_i}", "")
    if _k and _k not in NIM_KEYS:
        NIM_KEYS.append(_k)
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_RATE_LIMIT_PER_KEY = 40  # requests per minute per key
NIM_RATE_LIMIT_WINDOW = 60  # seconds

# OpenRouter — single key
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Ollama (Local GPU via Tailscale) ──────────────────────────────────
# HARDENED: concurrency=1, queue=3, cooldown=60s on 500s, tags cache 60s
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://100.95.92.117:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b-instruct-q4_K_M")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "45"))
OLLAMA_TAGS_CACHE_TTL = int(os.environ.get("OLLAMA_TAGS_CACHE_TTL", "60"))

# Heavy model (7B) — DISABLED by default. Set OLLAMA_HEAVY_ENABLED=1 to allow.
OLLAMA_HEAVY_MODEL = os.environ.get("OLLAMA_HEAVY_MODEL", "qwen2.5-coder:7b")
OLLAMA_HEAVY_KEEP_ALIVE = os.environ.get("OLLAMA_HEAVY_KEEP_ALIVE", "3m")
OLLAMA_HEAVY_ENABLED = os.environ.get("OLLAMA_HEAVY_ENABLED", "") == "1"

# Backpressure: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort
OLLAMA_MAX_ACTIVE = int(os.environ.get("OLLAMA_MAX_ACTIVE", "1"))
OLLAMA_MAX_QUEUE = int(os.environ.get("OLLAMA_MAX_QUEUE", "3"))
OLLAMA_COOLDOWN_SECONDS = int(os.environ.get("OLLAMA_COOLDOWN_SECONDS", "60"))

_ollama_available: Optional[bool] = None  # None = not checked yet
_ollama_last_check: float = 0.0
_ollama_checking: bool = False  # sentinel to prevent concurrent /api/tags polls
_ollama_calls = 0
_ollama_failures = 0


class _OllamaLaneSync:
    """Thread-safe sync Ollama call scheduler with backpressure.

    Enforces: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort.
    Logs per call: provider, model, timeout, queued_ms, success/fallback.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._queue_depth = 0
        self._cooldown_until: float = 0.0

    def is_available(self) -> bool:
        """Check if Ollama lane is not in cooldown."""
        return time.time() >= self._cooldown_until

    def try_acquire(self) -> bool:
        """Try to enter the Ollama lane. Returns False if at capacity or cooling down."""
        with self._lock:
            if time.time() < self._cooldown_until:
                return False
            if self._active >= OLLAMA_MAX_ACTIVE:
                if self._queue_depth >= OLLAMA_MAX_QUEUE:
                    return False
                self._queue_depth += 1
                return True  # queued — caller must wait
            self._active += 1
            return True

    def release(self, was_error: bool = False, is_500: bool = False):
        """Release an Ollama lane slot. If 500/client-abort, start cooldown."""
        with self._lock:
            if self._active > 0:
                self._active -= 1
            if is_500:
                self._cooldown_until = time.time() + OLLAMA_COOLDOWN_SECONDS
            cooling = time.time() < self._cooldown_until
        if is_500:
            logger.warning(
                "Ollama: 500/client-abort detected — cooldown %ds",
                OLLAMA_COOLDOWN_SECONDS,
            )

    def stats(self) -> Dict:
        with self._lock:
            return {
                "active": self._active,
                "queue_depth": self._queue_depth,
                "cooling_down": time.time() < self._cooldown_until,
                "cooldown_remaining": max(0, self._cooldown_until - time.time()),
            }


_ollama_lane = _OllamaLaneSync()

# ── Cloudflare Workers AI ──────────────────────────────────────────
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_MODEL = os.environ.get("CF_MODEL", "@cf/meta/llama-3.1-8b-instruct")
CF_BASE_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
    if CF_ACCOUNT_ID
    else ""
)
CF_TIMEOUT = int(os.environ.get("CF_TIMEOUT", "15"))
_cf_available: Optional[bool] = None
_cf_last_check: float = 0.0
CF_CHECK_INTERVAL = 120.0
_cf_calls = 0
_cf_failures = 0

# ── Together AI ────────────────────────────────────────────────────
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "")
TOGETHER_BASE_URL = os.environ.get(
    "TOGETHER_BASE_URL", "https://api.together.xyz/v1/chat/completions"
)
TOGETHER_MODEL = os.environ.get("TOGETHER_MODEL", "meta-llama/Llama-3-8b-chat-hf")
TOGETHER_TIMEOUT = int(os.environ.get("TOGETHER_TIMEOUT", "20"))
_together_available: Optional[bool] = None
_together_last_check: float = 0.0
TOGETHER_CHECK_INTERVAL = 300.0
_together_calls = 0
_together_failures = 0

# ── Google Gemini ──────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "20"))
_gemini_available: Optional[bool] = None
_gemini_last_check: float = 0.0
GEMINI_CHECK_INTERVAL = 300.0
_gemini_calls = 0
_gemini_failures = 0

# ── Grok/xAI ───────────────────────────────────────────────────────
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1/chat/completions")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
GROK_TIMEOUT = int(os.environ.get("GROK_TIMEOUT", "25"))
_grok_available: Optional[bool] = None
_grok_last_check: float = 0.0
GROK_CHECK_INTERVAL = 300.0
_grok_calls = 0
_grok_failures = 0


def _check_ollama_available() -> bool:
    """Check if Ollama is reachable. Polls /api/tags ONCE on first call.

    Once the model is confirmed present, returns True indefinitely without
    re-polling /api/tags. Only re-checks tags after a generation error
    explicitly sets _ollama_available = False (which triggers a re-check
    after OLLAMA_TAGS_CACHE_TTL cooldown).

    Uses _ollama_checking sentinel to prevent concurrent /api/tags polls
    on startup (avoids N simultaneous calls all polling tags at once).
    """
    global _ollama_available, _ollama_last_check, _ollama_checking
    # Already confirmed available — never poll again
    if _ollama_available is True:
        return True
    # Another caller is already checking — spin-wait briefly
    if _ollama_checking:
        for _ in range(30):  # wait up to ~3s
            time.sleep(0.1)
            if _ollama_available is not None:
                return _ollama_available is True
        return False  # timeout waiting for check
    now = time.time()
    # Previously failed — wait OLLAMA_TAGS_CACHE_TTL before retrying
    if (
        _ollama_available is False
        and (now - _ollama_last_check) < OLLAMA_TAGS_CACHE_TTL
    ):
        return False
    _ollama_checking = True
    try:
        base = OLLAMA_BASE_URL.replace("/v1", "")
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            if any(OLLAMA_MODEL in m for m in models):
                _ollama_available = True
            else:
                logger.warning(
                    "Ollama reachable but model %s not found (available: %s)",
                    OLLAMA_MODEL,
                    models[:5],
                )
                _ollama_available = False
    except Exception as e:
        logger.debug("Ollama not reachable at %s: %s", OLLAMA_BASE_URL, e)
        _ollama_available = False
    finally:
        _ollama_last_check = now
        _ollama_checking = False
    return _ollama_available


def _call_ollama(
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
    heavy: bool = False,
) -> Tuple[bool, str, float]:
    """Call Ollama via OpenAI-compatible API with backpressure. Returns (success, content, latency_ms).

    Enforces: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort.
    Heavy calls (7B) are blocked unless OLLAMA_HEAVY_ENABLED=1.

    Args:
        heavy: If True, use the heavy model (7B) with short keep_alive.
        Only for high-significance events. Requires OLLAMA_HEAVY_ENABLED=1.
    """
    global _ollama_calls, _ollama_failures, _ollama_available

    if not _check_ollama_available():
        return False, "Ollama not available", 0

    # Block heavy calls unless explicitly enabled
    if heavy and not OLLAMA_HEAVY_ENABLED:
        logger.debug(
            "Ollama: heavy call requested but OLLAMA_HEAVY_ENABLED=0, skipping"
        )
        return False, "Ollama heavy model disabled", 0

    # Check lane availability (backpressure)
    if not _ollama_lane.is_available():
        logger.debug("Ollama: lane cooling down, skipping")
        return False, "Ollama lane cooling down", 0

    if not _ollama_lane.try_acquire():
        logger.debug(
            "Ollama: lane full (active=%d, queue=%d), skipping",
            OLLAMA_MAX_ACTIVE,
            OLLAMA_MAX_QUEUE,
        )
        return False, "Ollama lane full", 0

    model = OLLAMA_HEAVY_MODEL if heavy else OLLAMA_MODEL
    queue_start = time.time()

    payload_dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    # Add keep_alive for heavy model to limit VRAM residency
    if heavy and OLLAMA_HEAVY_KEEP_ALIVE:
        payload_dict["keep_alive"] = OLLAMA_HEAVY_KEEP_ALIVE

    payload = json.dumps(payload_dict).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    start = time.time()
    is_500 = False
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            _ollama_calls += 1
            latency_ms = (time.time() - start) * 1000
            queued_ms = (start - queue_start) * 1000
            choices = body.get("choices") or [{}]
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            _record_call("ollama", None, model, "", True, latency_ms)
            _record_provider_result("ollama", True)
            logger.info(
                "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d success=True -> %d chars (%dms)",
                model,
                OLLAMA_TIMEOUT,
                int(queued_ms),
                len(content.strip()),
                int(latency_ms),
            )
            _ollama_lane.release(was_error=False, is_500=False)
            return True, content.strip(), latency_ms
    except urllib.error.HTTPError as e:
        _ollama_calls += 1
        _ollama_failures += 1
        latency_ms = (time.time() - start) * 1000
        queued_ms = (start - queue_start) * 1000
        is_500 = e.code >= 500
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        err_msg = f"Ollama HTTP {e.code}: {err_body}"
        logger.debug(err_msg)
        _record_call("ollama", None, model, "", False, latency_ms, err_msg)
        _record_provider_result("ollama", False)
        logger.warning(
            "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d success=Fallback is_500=%s (%dms)",
            model,
            OLLAMA_TIMEOUT,
            int(queued_ms),
            is_500,
            int(latency_ms),
        )
        _ollama_lane.release(was_error=True, is_500=is_500)
        if is_500:
            _ollama_available = False
        return False, err_msg, latency_ms
    except Exception as e:
        _ollama_calls += 1
        _ollama_failures += 1
        latency_ms = (time.time() - start) * 1000
        queued_ms = (start - queue_start) * 1000
        err_str = str(e)
        # Detect client-abort / connection-reset patterns
        is_client_abort = any(
            kw in err_str.lower()
            for kw in ("reset", "aborted", "refused", "broken", "connection")
        )
        err_msg = f"Ollama error: {err_str[:200]}"
        logger.debug(err_msg)
        _record_call("ollama", None, model, "", False, latency_ms, err_msg)
        _record_provider_result("ollama", False)
        logger.warning(
            "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d success=Fallback is_500=%s (%dms)",
            model,
            OLLAMA_TIMEOUT,
            int(queued_ms),
            is_client_abort,
            int(latency_ms),
        )
        _ollama_lane.release(was_error=True, is_500=is_client_abort)
        # Mark unavailable so we don't retry immediately
        _ollama_available = False
        return False, err_msg, latency_ms


# Circuit breaker — if a provider fails N times in a window, skip it
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures to trip
CIRCUIT_BREAKER_WINDOW = 300  # seconds (5 min)
CIRCUIT_BREAKER_KEY_PREFIX = "llm_circuit_breaker:"


# ── Cloudflare Workers AI ──────────────────────────────────────────


def _check_cloudflare_available() -> bool:
    global _cf_available, _cf_last_check
    now = time.time()
    if _cf_available is not None and (now - _cf_last_check) < CF_CHECK_INTERVAL:
        return _cf_available
    if not CF_API_TOKEN or not CF_ACCOUNT_ID:
        _cf_available = False
        _cf_last_check = now
        return False
    _cf_available = True
    _cf_last_check = now
    return True


def _call_cloudflare(
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
) -> Tuple[bool, str, float]:
    global _cf_calls, _cf_failures
    if not _check_cloudflare_available():
        return False, "Cloudflare not available", 0

    payload = json.dumps(
        {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CF_API_TOKEN}",
    }
    req = urllib.request.Request(
        CF_BASE_URL, data=payload, headers=headers, method="POST"
    )
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=CF_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000
            content = None
            if "result" in body and isinstance(body["result"], dict):
                content = body["result"].get("response") or ""
            elif "choices" in body:
                choices = body.get("choices") or [{}]
                message = choices[0].get("message") or {}
                content = message.get("content") or ""
            if content and isinstance(content, str):
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                _cf_calls += 1
                _record_call("cloudflare", None, CF_MODEL, "", True, latency_ms)
                _record_provider_result("cloudflare", True)
                return True, content, latency_ms
            _cf_failures += 1
            _record_call(
                "cloudflare", None, CF_MODEL, "", False, latency_ms, "empty response"
            )
            _record_provider_result("cloudflare", False)
            return False, "Cloudflare: empty response", latency_ms
    except urllib.error.HTTPError as e:
        _cf_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        err_msg = f"Cloudflare HTTP {e.code}: {err_body}"
        _record_call("cloudflare", None, CF_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("cloudflare", False)
        if e.code == 429:
            _cf_available = False
            _cf_last_check = time.time()
        return False, err_msg, latency_ms
    except Exception as e:
        _cf_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_msg = f"Cloudflare error: {str(e)[:200]}"
        logger.debug(err_msg)
        _record_call("cloudflare", None, CF_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("cloudflare", False)
        return False, err_msg, latency_ms


# ── Together AI ────────────────────────────────────────────────────


def _check_together_available() -> bool:
    global _together_available, _together_last_check
    now = time.time()
    if (
        _together_available is not None
        and (now - _together_last_check) < TOGETHER_CHECK_INTERVAL
    ):
        return _together_available
    if not TOGETHER_API_KEY:
        _together_available = False
        _together_last_check = now
        return False
    _together_available = True
    _together_last_check = now
    return True


def _call_together(
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
) -> Tuple[bool, str, float]:
    global _together_calls, _together_failures
    if not _check_together_available():
        return False, "Together not available", 0

    payload = json.dumps(
        {
            "model": TOGETHER_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
    }
    req = urllib.request.Request(
        TOGETHER_BASE_URL, data=payload, headers=headers, method="POST"
    )
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=TOGETHER_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000
            choices = body.get("choices") or [{}]
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            content = content.strip().strip('"').strip("'")
            if len(content) > 500:
                content = content[:500]
            if content:
                _together_calls += 1
                _record_call("together", None, TOGETHER_MODEL, "", True, latency_ms)
                _record_provider_result("together", True)
                return True, content, latency_ms
            _together_failures += 1
            _record_call(
                "together",
                None,
                TOGETHER_MODEL,
                "",
                False,
                latency_ms,
                "empty response",
            )
            _record_provider_result("together", False)
            return False, "Together: empty response", latency_ms
    except urllib.error.HTTPError as e:
        _together_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        err_msg = f"Together HTTP {e.code}: {err_body}"
        _record_call("together", None, TOGETHER_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("together", False)
        if e.code in (401, 403, 429):
            _together_available = False
            _together_last_check = time.time()
        return False, err_msg, latency_ms
    except Exception as e:
        _together_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_msg = f"Together error: {str(e)[:200]}"
        logger.debug(err_msg)
        _record_call("together", None, TOGETHER_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("together", False)
        return False, err_msg, latency_ms


# ── Google Gemini ──────────────────────────────────────────────────


def _check_gemini_available() -> bool:
    global _gemini_available, _gemini_last_check
    now = time.time()
    if (
        _gemini_available is not None
        and (now - _gemini_last_check) < GEMINI_CHECK_INTERVAL
    ):
        return _gemini_available
    if not GEMINI_API_KEY:
        _gemini_available = False
        _gemini_last_check = now
        return False
    _gemini_available = True
    _gemini_last_check = now
    return True


def _call_gemini(
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
) -> Tuple[bool, str, float]:
    global _gemini_calls, _gemini_failures
    if not _check_gemini_available():
        return False, "Gemini not available", 0

    system_text = ""
    user_text = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_text = msg.get("content", "")
        elif msg.get("role") == "user":
            user_text = msg.get("content", "")

    url = (
        f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    gemini_payload = {
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if system_text:
        gemini_payload["system_instruction"] = {"parts": [{"text": system_text}]}

    payload_bytes = json.dumps(gemini_payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=payload_bytes, headers=headers, method="POST"
    )
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000
            candidates = body.get("candidates") or [{}]
            parts = (candidates[0].get("content") or {}).get("parts") or [{}]
            content = parts[0].get("text") or ""
            if content and isinstance(content, str):
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                _gemini_calls += 1
                _record_call("gemini", None, GEMINI_MODEL, "", True, latency_ms)
                _record_provider_result("gemini", True)
                return True, content, latency_ms
            _gemini_failures += 1
            _record_call(
                "gemini", None, GEMINI_MODEL, "", False, latency_ms, "empty response"
            )
            _record_provider_result("gemini", False)
            return False, "Gemini: empty response", latency_ms
    except urllib.error.HTTPError as e:
        _gemini_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        err_msg = f"Gemini HTTP {e.code}: {err_body}"
        _record_call("gemini", None, GEMINI_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("gemini", False)
        if e.code in (403, 429):
            _gemini_available = False
            _gemini_last_check = time.time()
        return False, err_msg, latency_ms
    except Exception as e:
        _gemini_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_msg = f"Gemini error: {str(e)[:200]}"
        logger.debug(err_msg)
        _record_call("gemini", None, GEMINI_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("gemini", False)
        return False, err_msg, latency_ms


# ── Grok/xAI ───────────────────────────────────────────────────────


def _check_grok_available() -> bool:
    global _grok_available, _grok_last_check
    now = time.time()
    if _grok_available is not None and (now - _grok_last_check) < GROK_CHECK_INTERVAL:
        return _grok_available
    if not GROK_API_KEY:
        _grok_available = False
        _grok_last_check = now
        return False
    _grok_available = True
    _grok_last_check = now
    return True


def _call_grok(
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
) -> Tuple[bool, str, float]:
    global _grok_calls, _grok_failures
    if not _check_grok_available():
        return False, "Grok not available", 0

    payload = json.dumps(
        {
            "model": GROK_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROK_API_KEY}",
    }
    req = urllib.request.Request(
        GROK_BASE_URL, data=payload, headers=headers, method="POST"
    )
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=GROK_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000
            choices = body.get("choices") or [{}]
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            content = content.strip().strip('"').strip("'")
            if len(content) > 500:
                content = content[:500]
            if content:
                _grok_calls += 1
                _record_call("grok", None, GROK_MODEL, "", True, latency_ms)
                _record_provider_result("grok", True)
                return True, content, latency_ms
            _grok_failures += 1
            _record_call(
                "grok", None, GROK_MODEL, "", False, latency_ms, "empty response"
            )
            _record_provider_result("grok", False)
            return False, "Grok: empty response", latency_ms
    except urllib.error.HTTPError as e:
        _grok_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        err_msg = f"Grok HTTP {e.code}: {err_body}"
        _record_call("grok", None, GROK_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("grok", False)
        if e.code in (401, 403, 429):
            _grok_available = False
            _grok_last_check = time.time()
        return False, err_msg, latency_ms
    except Exception as e:
        _grok_failures += 1
        latency_ms = (time.time() - start) * 1000
        err_msg = f"Grok error: {str(e)[:200]}"
        logger.debug(err_msg)
        _record_call("grok", None, GROK_MODEL, "", False, latency_ms, err_msg)
        _record_provider_result("grok", False)
        return False, err_msg, latency_ms


# ── Model Selection per Task Class ──────────────────────────────────
# Each task class has a primary model on NIM, a fallback on NIM,
# and a secondary fallback on OpenRouter.

TASK_MODELS = {
    "leader": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.3-70b-instruct",
            "max_tokens": 300,
            "temperature": 0.85,
            "timeout": 20,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "max_tokens": 300,
            "temperature": 0.85,
            "timeout": 30,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "max_tokens": 300,
            "temperature": 0.85,
            "timeout": 25,
        },
    },
    "specialist": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.3-70b-instruct",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 18,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "meta/llama-3.1-8b-instruct",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 15,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 20,
        },
    },
    "worker": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.1-8b-instruct",
            "max_tokens": 100,
            "temperature": 0.7,
            "timeout": 12,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "nvidia/llama-3.1-nemotron-nano-8b-v1",
            "max_tokens": 100,
            "temperature": 0.7,
            "timeout": 12,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.2-3b-instruct:free",
            "max_tokens": 100,
            "temperature": 0.7,
            "timeout": 15,
        },
    },
    "narrator": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.3-70b-instruct",
            "max_tokens": 500,
            "temperature": 0.9,
            "timeout": 25,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "max_tokens": 500,
            "temperature": 0.9,
            "timeout": 35,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "max_tokens": 500,
            "temperature": 0.9,
            "timeout": 30,
        },
    },
    "npc_memory": {
        "primary": {
            "provider": "nim",
            "model": "nvidia/llama-3.1-nemotron-super-49b-v1",
            "max_tokens": 400,
            "temperature": 0.8,
            "timeout": 25,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "nvidia/llama-3.1-nemotron-ultra-251b",
            "max_tokens": 400,
            "temperature": 0.8,
            "timeout": 35,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "max_tokens": 400,
            "temperature": 0.8,
            "timeout": 30,
        },
    },
}

# ── Key Rotation ────────────────────────────────────────────────────

_nim_key_index = 0


def _get_nim_key() -> Optional[str]:
    """Get the next NIM API key using round-robin with LRU awareness.

    Picks the key that was used longest ago (LRU), falling back to
    simple round-robin if Redis tracking is unavailable.
    """
    global _nim_key_index
    if not NIM_KEYS:
        return None

    r = _get_redis()
    oldest_time = float("inf")
    best_key = None
    best_idx = 0

    for idx, key in enumerate(NIM_KEYS):
        key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
        try:
            last_used = r.get(f"llm_key_last_used:{key_hash}")
            ts = float(last_used) if last_used else 0.0
        except Exception:
            ts = 0.0

        if ts < oldest_time:
            oldest_time = ts
            best_key = key
            best_idx = idx

    # Mark this key as used now
    if best_key:
        key_hash = hashlib.md5(best_key.encode()).hexdigest()[:12]
        try:
            r.set(f"llm_key_last_used:{key_hash}", str(time.time()), ex=300)
        except Exception:
            pass

    _nim_key_index = best_idx + 1
    return best_key


def _check_rate_limit(provider: str, key: Optional[str] = None) -> bool:
    """Check if the provider/key is within rate limits.

    Returns True if OK to proceed, False if rate-limited.
    Uses Redis to count calls in the last 60s window.
    """
    r = _get_redis()
    now = time.time()
    window_start = now - NIM_RATE_LIMIT_WINDOW

    if provider == "nim" and key:
        key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
        counter_key = f"llm_call_log:nim:{key_hash}"
    else:
        counter_key = f"llm_call_log:{provider}"

    try:
        # Remove entries older than window
        r.zremrangebyscore(counter_key, 0, window_start)
        count = r.zcard(counter_key)

        limit = NIM_RATE_LIMIT_PER_KEY if provider == "nim" else 60
        return count < limit
    except Exception:
        # If Redis fails, allow the call (fail open)
        return True


def _record_call(
    provider: str,
    key: Optional[str] = None,
    model: str = "",
    task_class: str = "",
    success: bool = True,
    latency_ms: float = 0,
    error: str = "",
):
    """Record an LLM call in Redis for rate limiting and auditing."""
    r = _get_redis()
    now = time.time()

    # Rate limit tracking
    if provider == "nim" and key:
        key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
        counter_key = f"llm_call_log:nim:{key_hash}"
    else:
        counter_key = f"llm_call_log:{provider}"

    try:
        r.zadd(counter_key, {str(now): now})
        r.expire(counter_key, NIM_RATE_LIMIT_WINDOW + 10)
    except Exception:
        pass

    # Audit log
    try:
        audit_entry = {
            "ts": now,
            "provider": provider,
            "model": model,
            "task_class": task_class,
            "success": success,
            "latency_ms": round(latency_ms, 1),
        }
        if error:
            audit_entry["error"] = error[:200]

        r.zadd("llm_audit", {json.dumps(audit_entry): now})
        r.expire("llm_audit", 86400 * 7)
        # Keep last 500 entries
        r.zremrangebyrank("llm_audit", 0, -501)
    except Exception:
        pass

    # Error tracking
    if not success and error:
        try:
            err_entry = {
                "ts": now,
                "provider": provider,
                "model": model,
                "error": error[:200],
            }
            r.zadd(f"llm_errors:{provider}", {json.dumps(err_entry): now})
            r.expire(f"llm_errors:{provider}", 3600)
            r.zremrangebyrank(f"llm_errors:{provider}", 0, -101)
        except Exception:
            pass


def _is_circuit_open(provider: str) -> bool:
    """Check if a provider's circuit breaker is open (should be skipped).

    Reads llm_circuit_breaker:{provider} from Redis. If the value is "open"
    and TTL > 0, the circuit is open and the provider should be skipped.
    Returns False (allow calls) if Redis is unavailable.
    """
    try:
        r = _get_redis()
        key = f"{CIRCUIT_BREAKER_KEY_PREFIX}{provider}"
        val = r.get(key)
        ttl = r.ttl(key)
        if val == "open" and ttl and ttl > 0:
            return True
        return False
    except Exception:
        return False


def _trip_circuit(provider: str):
    """Trip a provider's circuit breaker, skipping it for CIRCUIT_BREAKER_WINDOW seconds."""
    try:
        r = _get_redis()
        r.set(
            f"{CIRCUIT_BREAKER_KEY_PREFIX}{provider}",
            "open",
            ex=CIRCUIT_BREAKER_WINDOW,
        )
        logger.warning(
            "Circuit breaker TRIPPED for provider %s — skipping for %ds",
            provider,
            CIRCUIT_BREAKER_WINDOW,
        )
    except Exception:
        pass


def _record_provider_result(provider: str, success: bool):
    """Record the result of a provider call for circuit breaker tracking.

    On success: reset the failure counter and any open circuit.
    On failure: increment the counter. If it reaches the threshold,
    trip the circuit and clean up the counter.
    """
    try:
        r = _get_redis()
        if success:
            r.delete(f"{CIRCUIT_BREAKER_KEY_PREFIX}{provider}")
            r.delete(f"llm_circuit_failures:{provider}")
            return

        counter_key = f"llm_circuit_failures:{provider}"
        count = r.incr(counter_key)
        r.expire(counter_key, CIRCUIT_BREAKER_WINDOW)
        if count >= CIRCUIT_BREAKER_THRESHOLD:
            _trip_circuit(provider)
            r.delete(counter_key)
    except Exception:
        pass


# ── Low-Level API Call ──────────────────────────────────────────────


def _call_provider(
    provider: str,
    model: str,
    messages: List[Dict],
    max_tokens: int = 200,
    temperature: float = 0.8,
    timeout: int = 12,
) -> Tuple[bool, str, float]:
    """Make a single API call to a provider. Returns (success, content, latency_ms).

    Args:
        provider: "nim" or "openrouter"
        model: Model ID string
        messages: List of {"role": ..., "content": ...} dicts
        max_tokens: Max response tokens
        temperature: Sampling temperature
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success: bool, content: str, latency_ms: float)
    """
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    if provider == "nim":
        key = _get_nim_key()
        if not key:
            return False, "No NIM API keys configured", 0
        if not _check_rate_limit("nim", key):
            return False, "NIM rate limit exceeded", 0
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        url = NIM_BASE_URL

    elif provider == "openrouter":
        if not OPENROUTER_API_KEY:
            return False, "No OpenRouter API key configured", 0
        if not _check_rate_limit("openrouter"):
            return False, "OpenRouter rate limit exceeded", 0
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://federation-game.deliberatefederation.cloud",
            "X-Title": "Federation Game LLM Router",
        }
        url = OPENROUTER_BASE_URL

    else:
        return False, f"Unknown provider: {provider}", 0

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            # Defensive content extraction — NIM reasoning models may return
            # null "content" with actual text in "reasoning_content"
            raw_content = None
            try:
                choices = body.get("choices") or [{}]
                message = choices[0].get("message") or {}
                raw_content = message.get("content")
                # If content is null/empty, try reasoning_content (NIM reasoning models)
                if not raw_content:
                    reasoning = message.get("reasoning_content")
                    if reasoning and isinstance(reasoning, str):
                        raw_content = reasoning
            except (IndexError, KeyError, TypeError, AttributeError):
                raw_content = None
            # Final safety: ensure content is always a string
            if raw_content is None:
                raw_content = ""
            if not isinstance(raw_content, str):
                raw_content = str(raw_content)
            content = raw_content.strip()
            latency_ms = (time.time() - start) * 1000
            _record_call(
                provider,
                key if provider == "nim" else None,
                model,
                "",
                True,
                latency_ms,
            )
            return True, content, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.time() - start) * 1000
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        error_msg = f"HTTP {e.code}: {err_body}"
        _record_call(
            provider,
            key if provider == "nim" else None,
            model,
            "",
            False,
            latency_ms,
            error_msg,
        )
        return False, error_msg, latency_ms
    except urllib.error.URLError as e:
        latency_ms = (time.time() - start) * 1000
        error_msg = f"URL Error: {str(e.reason)[:200]}"
        _record_call(
            provider,
            key if provider == "nim" else None,
            model,
            "",
            False,
            latency_ms,
            error_msg,
        )
        return False, error_msg, latency_ms
    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        error_msg = f"Exception: {str(e)[:200]}"
        _record_call(
            provider,
            key if provider == "nim" else None,
            model,
            "",
            False,
            latency_ms,
            error_msg,
        )
        return False, error_msg, latency_ms


# ── Public API: Route Call ──────────────────────────────────────────


def route_call(
    task_class: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Dict:
    """Route an LLM call through the multi-provider tiered system.

    Fallback chain (ALL priority modes):
      NIM primary → NIM fallback → Ollama(3B) → OpenRouter free → template fallback

    Args:
        task_class: One of "leader", "specialist", "worker", "narrator"
        system_prompt: System message
        user_prompt: User message
        max_tokens: Override default max_tokens for this task class
        temperature: Override default temperature

    Returns:
    Dict with keys:
        success: bool
        content: str (empty on failure)
        provider: str (which provider answered)
        model: str (which model answered)
        task_class: str
        latency_ms: float
        attempts: int (how many providers were tried)
        errors: List[str] (errors from failed attempts)
    """
    result = {
        "success": False,
        "content": "",
        "provider": "",
        "model": "",
        "task_class": task_class,
        "latency_ms": 0,
        "attempts": 0,
        "errors": [],
    }

    config = TASK_MODELS.get(task_class)
    if not config:
        result["errors"].append(f"Unknown task class: {task_class}")
        return result

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Resolve max_tokens / temperature — use primary tier defaults as baseline
    primary_config = config.get("primary", {})
    mt = max_tokens if max_tokens is not None else primary_config.get("max_tokens", 200)
    temp = (
        temperature
        if temperature is not None
        else primary_config.get("temperature", 0.8)
    )

    # ── NIM-first fallback chain ──────────────────────────────────────
    # 1. NIM primary model (from TASK_MODELS)
    # 2. NIM fallback model (from TASK_MODELS)
    # 3. Ollama local (3B via Tailscale)
    # 4. OpenRouter free (from TASK_MODELS)
    nim_tiers = [
        ("primary", config.get("primary")),
        ("fallback_nim", config.get("fallback_nim")),
    ]

    for tier_name, tier_config in nim_tiers:
        if not tier_config:
            continue

        provider = tier_config["provider"]
        model = tier_config["model"]
        tier_mt = max_tokens if max_tokens is not None else tier_config["max_tokens"]
        tier_temp = (
            temperature if temperature is not None else tier_config["temperature"]
        )
        tier_timeout = tier_config.get("timeout", 12)

        if _is_circuit_open(provider):
            logger.warning(
                "Circuit breaker OPEN for provider %s — skipping %s tier",
                provider,
                tier_name,
            )
            result["errors"].append(f"{provider}: circuit breaker open, skipped")
            continue

        result["attempts"] += 1

        ok, content, latency = _call_provider(
            provider, model, messages, tier_mt, tier_temp, tier_timeout
        )

        _record_provider_result(provider, ok)

        if ok and content:
            result["success"] = True
            result["content"] = content
            result["provider"] = provider
            result["model"] = model
            result["latency_ms"] = latency
            try:
                r = _get_redis()
                audit_entry = {
                    "ts": time.time(),
                    "provider": provider,
                    "model": model,
                    "task_class": task_class,
                    "success": True,
                    "latency_ms": round(latency, 1),
                    "content_preview": content[:100],
                }
                r.zadd("llm_audit", {json.dumps(audit_entry): time.time()})
            except Exception:
                pass
            return result
        else:
            result["errors"].append(f"{provider}/{model}: {content[:150]}")
            result["latency_ms"] += latency
            logger.warning(
                "LLM call failed for %s tier %s: %s",
                task_class,
                tier_name,
                content[:100],
            )

    # ── Ollama local fallback ─────────────────────────────────────────
    if _check_ollama_available() and not _is_circuit_open("ollama"):
        result["attempts"] += 1
        ok, content, latency = _call_ollama(messages, mt, temp)
        if ok and content:
            result["success"] = True
            result["content"] = content
            result["provider"] = "ollama"
            result["model"] = OLLAMA_MODEL
            result["latency_ms"] = latency
            try:
                r = _get_redis()
                audit_entry = {
                    "ts": time.time(),
                    "provider": "ollama",
                    "model": OLLAMA_MODEL,
                    "task_class": task_class,
                    "success": True,
                    "latency_ms": round(latency, 1),
                    "content_preview": content[:100],
                }
                r.zadd("llm_audit", {json.dumps(audit_entry): time.time()})
            except Exception:
                pass
            return result
        else:
            result["errors"].append(f"ollama/{OLLAMA_MODEL}: {content[:150]}")
            result["latency_ms"] += latency

    # ── OpenRouter free fallback (last resort) ────────────────────────
    or_config = config.get("fallback_openrouter")
    if or_config:
        provider = or_config["provider"]
        model = or_config["model"]
        tier_mt = max_tokens if max_tokens is not None else or_config["max_tokens"]
        tier_temp = (
            temperature if temperature is not None else or_config["temperature"]
        )
        tier_timeout = or_config.get("timeout", 25)

        if not _is_circuit_open(provider):
            result["attempts"] += 1
            ok, content, latency = _call_provider(
                provider, model, messages, tier_mt, tier_temp, tier_timeout
            )
            _record_provider_result(provider, ok)
            if ok and content:
                result["success"] = True
                result["content"] = content
                result["provider"] = provider
                result["model"] = model
                result["latency_ms"] = latency
                try:
                    r = _get_redis()
                    audit_entry = {
                        "ts": time.time(),
                        "provider": provider,
                        "model": model,
                        "task_class": task_class,
                        "success": True,
                        "latency_ms": round(latency, 1),
                        "content_preview": content[:100],
                    }
                    r.zadd("llm_audit", {json.dumps(audit_entry): time.time()})
                except Exception:
                    pass
                return result
            else:
                result["errors"].append(f"{provider}/{model}: {content[:150]}")
                result["latency_ms"] += latency

    logger.error(
        "All LLM providers failed for task_class=%s: %s",
        task_class,
        "; ".join(result["errors"][:3]),
    )
    return result


def route_call_batch(
    calls: List[Dict],
) -> List[Dict]:
    """Process multiple LLM calls sequentially (respecting rate limits).

    Args:
        calls: List of dicts, each with keys: task_class, system_prompt, user_prompt,
               optional max_tokens, optional temperature

    Returns:
        List of result dicts (same format as route_call)
    """
    results = []
    for call in calls:
        result = route_call(
            task_class=call["task_class"],
            system_prompt=call["system_prompt"],
            user_prompt=call["user_prompt"],
            max_tokens=call.get("max_tokens"),
            temperature=call.get("temperature"),
        )
        results.append(result)
        # Small delay between calls to respect rate limits
        time.sleep(0.3)
    return results


# ── Health / Stats ──────────────────────────────────────────────────


def get_router_stats() -> Dict:
    """Get current router statistics for monitoring."""
    r = _get_redis()
    now = time.time()
    stats = {
        "nim_keys_available": len(NIM_KEYS),
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "ollama_available": _check_ollama_available(),
        "ollama_model": OLLAMA_MODEL,
        "ollama_heavy_model": OLLAMA_HEAVY_MODEL,
        "ollama_heavy_enabled": OLLAMA_HEAVY_ENABLED,
        "ollama_lane_active": _ollama_lane.stats()["active"],
        "ollama_lane_queue": _ollama_lane.stats()["queue_depth"],
        "ollama_lane_cooling_down": _ollama_lane.stats()["cooling_down"],
        "ollama_lane_cooldown_remaining": round(
            _ollama_lane.stats()["cooldown_remaining"], 1
        ),
        "ollama_calls": _ollama_calls,
        "ollama_failures": _ollama_failures,
        "cloudflare_available": _check_cloudflare_available(),
        "cloudflare_calls": _cf_calls,
        "cloudflare_failures": _cf_failures,
        "together_available": _check_together_available(),
        "together_calls": _together_calls,
        "together_failures": _together_failures,
        "gemini_available": _check_gemini_available(),
        "gemini_calls": _gemini_calls,
        "gemini_failures": _gemini_failures,
        "grok_available": _check_grok_available(),
        "grok_calls": _grok_calls,
        "grok_failures": _grok_failures,
        "task_classes": list(TASK_MODELS.keys()),
        "recent_calls": {},
        "recent_errors": {},
    }

    # Count recent calls per provider (last 60s)
    all_providers = (
        "nim",
        "openrouter",
        "ollama",
        "cloudflare",
        "together",
        "gemini",
        "grok",
    )
    for provider in all_providers:
        try:
            if provider == "nim":
                total = 0
                for key in NIM_KEYS:
                    key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
                    counter_key = f"llm_call_log:nim:{key_hash}"
                    r.zremrangebyscore(counter_key, 0, now - 60)
                    total += r.zcard(counter_key)
                stats["recent_calls"]["nim"] = total
            else:
                counter_key = f"llm_call_log:{provider}"
                r.zremrangebyscore(counter_key, 0, now - 60)
                stats["recent_calls"][provider] = r.zcard(counter_key)
        except Exception:
            stats["recent_calls"][provider] = -1

    # Recent errors
    for provider in all_providers:
        try:
            errors = r.zrevrange(f"llm_errors:{provider}", 0, 4)
            stats["recent_errors"][provider] = len(errors)
        except Exception:
            stats["recent_errors"][provider] = -1

    return stats
