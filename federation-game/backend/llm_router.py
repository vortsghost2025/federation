#!/usr/bin/env python3
"""
FEDERATION GAME — LLM Router

Multi-provider routing layer for tiered NPC cognition.
Supports Ollama, Cloudflare Workers AI, Together AI, NVIDIA NIM,
Google Gemini, Grok/xAI, and OpenRouter — with automatic fallback.

Design principles:
- Multi-provider: Ollama(3B/7B) → Cloudflare → Together → NIM → OpenRouter → Gemini → Grok
- Key rotation for NIM (up to 8 keys, round-robin with least-recently-used)
- Per-provider rate limit awareness (Redis-backed call tracking)
- Per-provider circuit breaker (3 consecutive failures → 5 min cooldown)
- Task-class routing: leader/specialist/worker/narrator → different models
- Ollama resource safety: 3B default, 7B only with OLLAMA_HEAVY_ENABLED=1
- Ollama backpressure: max 1 active call, queue=3, cooldown 60s on 500s
- Audit logging to Redis

Fallback chain (route_call):
  Ollama(3B) → Cloudflare → Together → NIM primary → NIM fallback
  → OpenRouter → Gemini → Grok → template fallback

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
import copy
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from collections import OrderedDict

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
            _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
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
# Also check standard NVIDIA_API_KEY env var (common in NVIDIA tooling)
_NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "")
if _NVIDIA_KEY and _NVIDIA_KEY not in NIM_KEYS:
    NIM_KEYS.append(_NVIDIA_KEY)
NIM_DISABLED = os.environ.get("NIM_DISABLED", "").strip() == "1"
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_RATE_LIMIT_PER_KEY = 40  # requests per minute per key
NIM_RATE_LIMIT_WINDOW = 60  # seconds

# OpenRouter — multi-key rotation
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
_OR_KEY_1 = os.environ.get("OPENROUTER_API_KEY_1", "")
_OR_KEY_2 = os.environ.get("OPENROUTER_API_KEY_2", "")
OPENROUTER_KEYS = [k for k in [OPENROUTER_API_KEY, _OR_KEY_1, _OR_KEY_2] if k]
_or_key_index = 0

def _get_openrouter_key() -> str:
    global _or_key_index
    if not OPENROUTER_KEYS:
        return ""
    key = OPENROUTER_KEYS[_or_key_index % len(OPENROUTER_KEYS)]
    _or_key_index += 1
    return key

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

# Backpressure: max 2 active calls, max 5 queued, cooldown 60s on 500/client-abort
# (2 active matches nvidia_nim_client.py so both backend clients throttle the
# same local Ollama consistently; 1 was too restrictive for 37 NPCs per tick).
OLLAMA_MAX_ACTIVE = int(os.environ.get("OLLAMA_MAX_ACTIVE", "2"))
OLLAMA_MAX_QUEUE = int(os.environ.get("OLLAMA_MAX_QUEUE", "5"))
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
_GEMINI_ALLOWED_RAW = os.environ.get("GEMINI_ALLOWED_TASKS", "assistant,worker,specialist,narrator,npc_memory,leader")
GEMINI_ALLOWED_TASKS = frozenset(
    t.strip()
    for t in _GEMINI_ALLOWED_RAW.split(",")
    if t.strip()
)
GEMINI_MAX_CALLS_PER_DAY = int(os.environ.get("GEMINI_MAX_CALLS_PER_DAY", "500") or "500")
GEMINI_MAX_CALLS_PER_MONTH = int(
    os.environ.get("GEMINI_MAX_CALLS_PER_MONTH", "10000") or "10000"
)
GEMINI_MONTHLY_USD_CAP = float(os.environ.get("GEMINI_MONTHLY_USD_CAP", "10.0") or "10.0")
GEMINI_NOTIFY_THRESHOLDS = tuple(
    sorted(
        {
            float(x.strip())
            for x in os.environ.get("GEMINI_NOTIFY_THRESHOLDS", "0.5,0.8,1.0").split(",")
            if x.strip()
        }
    )
)
GEMINI_NOTIFY_INTERVAL_SECONDS = int(
    os.environ.get("GEMINI_NOTIFY_INTERVAL_SECONDS", "3600") or "3600"
)
GEMINI_PRICE_PER_MTOKEN = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
}
_gemini_available: Optional[bool] = None
_gemini_last_check: float = 0.0
GEMINI_CHECK_INTERVAL = 300.0
GEMINI_DEPLETED_COOLDOWN = 3600.0
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
    task_class: str = "",
    char_id: str = "",
    source: str = "",
    system_path: str = "",
) -> Tuple[bool, str, float]:
    """Call Ollama via OpenAI-compatible API with backpressure. Returns (success, content, latency_ms).

    Enforces: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort.
    Heavy calls (7B) are blocked unless OLLAMA_HEAVY_ENABLED=1.

    Args:
        heavy: If True, use the heavy model (7B) with short keep_alive.
        Only for high-significance events. Requires OLLAMA_HEAVY_ENABLED=1.
    """
    global _ollama_calls, _ollama_failures, _ollama_available
    model = OLLAMA_HEAVY_MODEL if heavy else OLLAMA_MODEL

    def _early_failure(message: str) -> Tuple[bool, str, float]:
        _record_call(
            "ollama",
            None,
            model,
            task_class,
            False,
            0,
            message,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
        return False, message, 0

    if not _check_ollama_available():
        return _early_failure("Ollama not available")

    # Block heavy calls unless explicitly enabled
    if heavy and not OLLAMA_HEAVY_ENABLED:
        logger.debug(
            "Ollama: heavy call requested but OLLAMA_HEAVY_ENABLED=0, skipping"
        )
        return _early_failure("Ollama heavy model disabled")

    # Check lane availability (backpressure)
    if not _ollama_lane.is_available():
        logger.debug("Ollama: lane cooling down, skipping")
        return _early_failure("Ollama lane cooling down")

    if not _ollama_lane.try_acquire():
        logger.debug(
            "Ollama: lane full (active=%d, queue=%d), skipping",
            OLLAMA_MAX_ACTIVE,
            OLLAMA_MAX_QUEUE,
        )
        return _early_failure("Ollama lane full")

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
            _record_call(
                "ollama",
                None,
                model,
                task_class,
                True,
                latency_ms,
                char_id=char_id,
                source=source,
                system_path=system_path,
                is_final=False,
            )
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
        _record_call(
            "ollama",
            None,
            model,
            task_class,
            False,
            latency_ms,
            err_msg,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
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
        _record_call(
            "ollama",
            None,
            model,
            task_class,
            False,
            latency_ms,
            err_msg,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
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


# ── Google Gemini ──────────────────────────────────────────────────


def _mark_gemini_depleted():
    global _gemini_available, _gemini_last_check
    _gemini_available = False
    _gemini_last_check = time.time()
    try:
        r = _get_redis()
        r.set("llm:gemini_depleted_until", str(_gemini_last_check + GEMINI_DEPLETED_COOLDOWN), ex=int(GEMINI_DEPLETED_COOLDOWN) + 60)
    except Exception:
        pass


def _check_gemini_available() -> bool:
    global _gemini_available, _gemini_last_check
    now = time.time()
    if (
        _gemini_available is not None
        and not _gemini_available
        and (now - _gemini_last_check) < GEMINI_DEPLETED_COOLDOWN
    ):
        return False
    try:
        r = _get_redis()
        depleted_until = r.get("llm:gemini_depleted_until")
        if depleted_until:
            if now < float(depleted_until):
                _gemini_available = False
                _gemini_last_check = now
                return False
            else:
                r.delete("llm:gemini_depleted_until")
    except Exception:
        pass
    if (
        _gemini_available is not None
        and _gemini_available
        and (now - _gemini_last_check) < GEMINI_CHECK_INTERVAL
    ):
        return True
    if not GEMINI_API_KEY:
        _gemini_available = False
        _gemini_last_check = now
        return False
    _gemini_available = True
    _gemini_last_check = now
    return True


def _build_gemini_payload(
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    """Translate OpenAI-style messages into Gemini generateContent payload."""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []

    for message in messages:
        text = message.get("content", "")
        if text is None:
            continue
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            continue

        role = str(message.get("role", "user") or "user").lower()
        if role == "system":
            system_parts.append(text)
            continue

        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            }
        )

    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]

    payload: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if system_parts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]
        }
    return payload


def _extract_gemini_text(body: Dict[str, Any]) -> str:
    """Extract text from Gemini generateContent responses."""
    candidates = body.get("candidates") or []
    if candidates:
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        texts: List[str] = []
        for part in parts:
            text = part.get("text")
            if text is None:
                continue
            texts.append(text if isinstance(text, str) else str(text))
        if texts:
            return "".join(texts).strip()

    prompt_feedback = body.get("promptFeedback") or {}
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        return f"blocked: {block_reason}"
    return ""


def _normalize_gemini_model_name(model: str) -> str:
    model = str(model or "")
    return model[7:] if model.startswith("models/") else model


def _extract_gemini_usage(body: Dict[str, Any]) -> Dict[str, int]:
    usage = body.get("usageMetadata") or {}
    input_tokens = int(usage.get("promptTokenCount") or 0)
    output_tokens = int(usage.get("candidatesTokenCount") or 0)
    total_tokens = int(usage.get("totalTokenCount") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _estimate_gemini_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = GEMINI_PRICE_PER_MTOKEN.get(_normalize_gemini_model_name(model))
    if not pricing:
        return 0.0
    return round(
        (input_tokens / 1_000_000.0) * pricing["input"]
        + (output_tokens / 1_000_000.0) * pricing["output"],
        6,
    )


def _gemini_budget_keys(now: Optional[float] = None) -> Dict[str, str]:
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    month = time.strftime("%Y-%m", time.gmtime(now))
    return {
        "day": day,
        "month": month,
        "daily_calls": f"llm_budget:gemini:daily:{day}:calls",
        "monthly_calls": f"llm_budget:gemini:monthly:{month}:calls",
        "monthly_input_tokens": f"llm_budget:gemini:monthly:{month}:input_tokens",
        "monthly_output_tokens": f"llm_budget:gemini:monthly:{month}:output_tokens",
        "monthly_total_tokens": f"llm_budget:gemini:monthly:{month}:total_tokens",
        "monthly_usd": f"llm_budget:gemini:monthly:{month}:usd",
    }


def _send_budget_notification(title: str, body: str, dedupe_key: str = "") -> None:
    notify_urls = os.environ.get("NOTIFICATION_URLS", "")
    if not notify_urls:
        return
    try:
        r = _get_redis()
        if dedupe_key:
            key = f"llm_budget:notify:{dedupe_key}"
            if r.get(key):
                return
            r.set(key, "1", ex=GEMINI_NOTIFY_INTERVAL_SECONDS)
    except Exception:
        pass

    try:
        import apprise

        apobj = apprise.Apprise()
        for url in [u.strip() for u in notify_urls.split(",") if u.strip()]:
            try:
                apobj.add(url)
            except Exception:
                continue
        apobj.notify(title=title, body=body)
    except Exception as e:
        logger.warning("Failed to send Gemini budget notification: %s", e)


def _check_gemini_budget(task_class: str, model: str) -> Tuple[bool, str]:
    if GEMINI_ALLOWED_TASKS and task_class not in GEMINI_ALLOWED_TASKS:
        return False, f"Gemini disabled for task_class={task_class}"

    try:
        r = _get_redis()
        keys = _gemini_budget_keys()
        daily_calls = int(r.get(keys["daily_calls"]) or 0)
        monthly_calls = int(r.get(keys["monthly_calls"]) or 0)
        monthly_usd = float(r.get(keys["monthly_usd"]) or 0.0)
    except Exception:
        return True, ""

    if GEMINI_MAX_CALLS_PER_DAY > 0 and daily_calls >= GEMINI_MAX_CALLS_PER_DAY:
        _send_budget_notification(
            "⚠️ Gemini daily call cap reached",
            (
                f"Task class: {task_class}\nModel: {_normalize_gemini_model_name(model)}\n"
                f"Daily calls: {daily_calls}/{GEMINI_MAX_CALLS_PER_DAY}\n"
                "Gemini fallback is blocked until the next UTC day."
            ),
            dedupe_key=f"gemini-daily-cap:{keys['day']}",
        )
        return False, f"Gemini daily call cap reached ({daily_calls}/{GEMINI_MAX_CALLS_PER_DAY})"

    if GEMINI_MAX_CALLS_PER_MONTH > 0 and monthly_calls >= GEMINI_MAX_CALLS_PER_MONTH:
        _send_budget_notification(
            "⚠️ Gemini monthly call cap reached",
            (
                f"Task class: {task_class}\nModel: {_normalize_gemini_model_name(model)}\n"
                f"Monthly calls: {monthly_calls}/{GEMINI_MAX_CALLS_PER_MONTH}\n"
                "Gemini fallback is blocked until the next UTC month."
            ),
            dedupe_key=f"gemini-monthly-cap:{keys['month']}",
        )
        return False, f"Gemini monthly call cap reached ({monthly_calls}/{GEMINI_MAX_CALLS_PER_MONTH})"

    if GEMINI_MONTHLY_USD_CAP > 0 and monthly_usd >= GEMINI_MONTHLY_USD_CAP:
        _send_budget_notification(
            "⚠️ Gemini monthly USD cap reached",
            (
                f"Task class: {task_class}\nModel: {_normalize_gemini_model_name(model)}\n"
                f"Estimated spend: ${monthly_usd:.4f}/${GEMINI_MONTHLY_USD_CAP:.2f}\n"
                "Gemini fallback is blocked until the next UTC month."
            ),
            dedupe_key=f"gemini-usd-cap:{keys['month']}",
        )
        return False, f"Gemini monthly USD cap reached (${monthly_usd:.4f}/${GEMINI_MONTHLY_USD_CAP:.2f})"

    return True, ""


def _record_gemini_usage(model: str, task_class: str, body: Dict[str, Any]) -> None:
    usage = _extract_gemini_usage(body)
    usd = _estimate_gemini_usd(model, usage["input_tokens"], usage["output_tokens"])

    try:
        r = _get_redis()
        keys = _gemini_budget_keys()
        pipe = r.pipeline()
        pipe.incr(keys["daily_calls"])
        pipe.expire(keys["daily_calls"], 86400 * 3)
        pipe.incr(keys["monthly_calls"])
        pipe.expire(keys["monthly_calls"], 86400 * 40)
        pipe.incrby(keys["monthly_input_tokens"], usage["input_tokens"])
        pipe.expire(keys["monthly_input_tokens"], 86400 * 40)
        pipe.incrby(keys["monthly_output_tokens"], usage["output_tokens"])
        pipe.expire(keys["monthly_output_tokens"], 86400 * 40)
        pipe.incrby(keys["monthly_total_tokens"], usage["total_tokens"])
        pipe.expire(keys["monthly_total_tokens"], 86400 * 40)
        pipe.incrbyfloat(keys["monthly_usd"], usd)
        pipe.expire(keys["monthly_usd"], 86400 * 40)
        pipe.execute()

        if GEMINI_MONTHLY_USD_CAP > 0:
            monthly_usd = float(r.get(keys["monthly_usd"]) or 0.0)
            for threshold in GEMINI_NOTIFY_THRESHOLDS:
                if threshold <= 0:
                    continue
                threshold_value = GEMINI_MONTHLY_USD_CAP * threshold
                if monthly_usd >= threshold_value:
                    pct = int(round(threshold * 100))
                    _send_budget_notification(
                        f"⚠️ Gemini spend at {pct}% of cap",
                        (
                            f"Task class: {task_class or 'unknown'}\n"
                            f"Model: {_normalize_gemini_model_name(model)}\n"
                            f"Estimated monthly spend: ${monthly_usd:.4f}/${GEMINI_MONTHLY_USD_CAP:.2f}\n"
                            f"This call used input={usage['input_tokens']} output={usage['output_tokens']} total={usage['total_tokens']} tokens."
                        ),
                        dedupe_key=f"gemini-threshold:{keys['month']}:{pct}",
                    )
    except Exception as e:
        logger.debug("Failed to record Gemini usage: %s", e)


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


# ── OpenRouter Free Model Pool ─────────────────────────────────────

# Instead of a single model per task class, we maintain a pool of free `:free` models.
# The router tries each model in the pool until one succeeds.
# Circuit breaker is per-model (key: llm_circuit_breaker:or_free:{model_id})
# to avoid one bad model blocking the entire free tier.

# Tier 1: High-context, high-quality (leader, narrator, npc_memory)
OR_FREE_POOL_LARGE = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-31b-it:free",
]

# Tier 2: Mid-context, balanced (specialist, assistant)
OR_FREE_POOL_MID = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-120b:free",
    "cohere/north-mini-code:free",
]

# Tier 3: Low-context, fast/cheap (worker)
OR_FREE_POOL_SMALL = [
    "meta-llama/llama-3.2-3b-instruct:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
]

_or_free_pool_index = 0

def _get_or_free_model(pool: list) -> str:
    """Round-robin select next model from pool, skipping circuit-open models."""
    global _or_free_pool_index
    if not pool:
        return ""
    tried = 0
    while tried < len(pool):
        model = pool[_or_free_pool_index % len(pool)]
        _or_free_pool_index += 1
        # Check per-model circuit breaker
        cb_key = f"or_free_model:{model}"
        if not _is_circuit_open(cb_key):
            return model
        tried += 1
    # All models circuit-open — return first anyway (will fail, then template)
    return pool[0]


# ── Task-class config ──────────────────────────────────────────────

TASK_MODELS = {
    "leader": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.3-70b-instruct",
            "max_tokens": 400,
            "temperature": 0.85,
            "timeout": 30,
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
            "models": OR_FREE_POOL_LARGE,
            "max_tokens": 300,
            "temperature": 0.85,
            "timeout": 30,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct",
            "max_tokens": 300,
            "temperature": 0.85,
            "timeout": 30,
        },
    },
    "specialist": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.3-70b-instruct",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 30,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "meta/llama-3.1-8b-instruct",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 30,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "models": OR_FREE_POOL_MID,
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 30,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.2-3b-instruct",
            "max_tokens": 200,
            "temperature": 0.8,
            "timeout": 30,
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
            "models": OR_FREE_POOL_SMALL,
            "max_tokens": 100,
            "temperature": 0.7,
            "timeout": 15,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.2-3b-instruct",
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
            "models": OR_FREE_POOL_LARGE,
            "max_tokens": 500,
            "temperature": 0.9,
            "timeout": 30,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct",
            "max_tokens": 500,
            "temperature": 0.9,
            "timeout": 30,
        },
    },
    "assistant": {
        "primary": {
            "provider": "nim",
            "model": "meta/llama-3.1-8b-instruct",
            "max_tokens": 300,
            "temperature": 0.6,
            "timeout": 10,
        },
        "fallback_nim": {
            "provider": "nim",
            "model": "nvidia/llama-3.1-nemotron-nano-8b-v1",
            "max_tokens": 300,
            "temperature": 0.6,
            "timeout": 10,
        },
        "fallback_openrouter": {
            "provider": "openrouter",
            "models": OR_FREE_POOL_MID,
            "max_tokens": 300,
            "temperature": 0.6,
            "timeout": 12,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.2-3b-instruct",
            "max_tokens": 300,
            "temperature": 0.6,
            "timeout": 12,
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
            "models": OR_FREE_POOL_LARGE,
            "max_tokens": 400,
            "temperature": 0.8,
            "timeout": 30,
        },
        "fallback_openrouter_paid": {
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct",
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


_VALID_AUDIT_SOURCES = {"cognition", "thought", "narrator", "assistant", "unknown", "dialogue"}


def _normalize_audit_source(source: str) -> str:
    return source if source in _VALID_AUDIT_SOURCES else "unknown"


def _record_call(
    provider: str,
    key: Optional[str] = None,
    model: str = "",
    task_class: str = "",
    success: bool = True,
    latency_ms: float = 0,
    error: str = "",
    char_id: str = "",
    source: str = "",
    system_path: str = "",
    is_final: bool = True,
):
    """Record an LLM call in Redis for rate limiting and auditing.

    Attribution fields (Phase 1):
      char_id:  which NPC triggered this call (empty if unknown)
      source:   cognition | thought | narrator | assistant | unknown
      is_final: True = final route_call result, False = provider sub-call
    """
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
            "char_id": char_id,
            "source": _normalize_audit_source(source),
            "is_final": is_final,
        }
        if system_path:
            audit_entry["system_path"] = system_path
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


def _record_final_route_call(
    provider: str,
    model: str,
    task_class: str,
    success: bool,
    latency_ms: float,
    content: str = "",
    error: str = "",
    char_id: str = "",
    source: str = "",
    system_path: str = "",
) -> None:
    """Record the final route_call outcome without touching rate counters."""
    try:
        r = _get_redis()
        now = time.time()
        audit_entry = {
            "ts": now,
            "provider": provider,
            "model": model,
            "task_class": task_class,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "char_id": char_id,
            "source": _normalize_audit_source(source),
            "is_final": True,
        }
        if system_path:
            audit_entry["system_path"] = system_path
        if content:
            audit_entry["content_preview"] = content[:100]
        if error:
            audit_entry["error"] = error[:200]

        r.zadd("llm_audit", {json.dumps(audit_entry): now})
        r.expire("llm_audit", 86400 * 7)
        r.zremrangebyrank("llm_audit", 0, -501)
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
    timeout: int = 20,
    task_class: str = "",
    char_id: str = "",
    source: str = "",
    system_path: str = "",
) -> Tuple[bool, str, float]:
    """Make a single API call to a provider. Returns (success, content, latency_ms).

    Args:
        provider: "nim", "gemini", or "openrouter"
        model: Model ID string
        messages: List of {"role": ..., "content": ...} dicts
        max_tokens: Max response tokens
        temperature: Sampling temperature
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success: bool, content: str, latency_ms: float)
    """
    global _gemini_calls, _gemini_failures

    def _early_failure(message: str, key_for_rate: Optional[str] = None) -> Tuple[bool, str, float]:
        _record_call(
            provider,
            key_for_rate,
            model,
            task_class,
            False,
            0,
            message,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
        return False, message, 0

    payload_dict: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if provider == "nim":
        if NIM_DISABLED:
            logger.info("NIM disabled by env; skipping hosted NIM tier")
            return _early_failure("NIM disabled by env (NIM_DISABLED=1)")
        key = _get_nim_key()
        if not key:
            return _early_failure("No NIM API keys configured")
        if not _check_rate_limit("nim", key):
            return _early_failure("NIM rate limit exceeded", key)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        url = NIM_BASE_URL

    elif provider == "gemini":
        if not GEMINI_API_KEY:
            return _early_failure("No Gemini API key configured")
        if not _check_rate_limit("gemini"):
            return _early_failure("Gemini rate limit exceeded")
        headers = {"Content-Type": "application/json"}
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = (
            f"{GEMINI_BASE_URL.rstrip('/')}/{urllib.parse.quote(model_path, safe='/')}:generateContent"
            f"?key={urllib.parse.quote(GEMINI_API_KEY, safe='')}"
        )
        payload_dict = _build_gemini_payload(messages, max_tokens, temperature)

    elif provider == "openrouter":
        or_key = _get_openrouter_key()
        if not or_key:
            return _early_failure("No OpenRouter API key configured")
        if not _check_rate_limit("openrouter"):
            return _early_failure("OpenRouter rate limit exceeded")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {or_key}",
            "HTTP-Referer": "https://federation-game.deliberatefederation.cloud",
            "X-Title": "Federation Game LLM Router",
        }
        url = OPENROUTER_BASE_URL

    else:
        return _early_failure(f"Unknown provider: {provider}")

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if provider == "gemini":
                raw_content = _extract_gemini_text(body)
                _gemini_calls += 1
                _record_gemini_usage(model, task_class, body)
            else:
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
                task_class,
                True,
                latency_ms,
                char_id=char_id,
                source=source,
                system_path=system_path,
                is_final=False,
            )
            return True, content, latency_ms
    except urllib.error.HTTPError as e:
        if provider == "gemini":
            _gemini_calls += 1
            _gemini_failures += 1
            if e.code == 429:
                _mark_gemini_depleted()
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
            task_class,
            False,
            latency_ms,
            error_msg,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
        return False, error_msg, latency_ms
    except urllib.error.URLError as e:
        if provider == "gemini":
            _gemini_calls += 1
            _gemini_failures += 1
        latency_ms = (time.time() - start) * 1000
        error_msg = f"URL Error: {str(e.reason)[:200]}"
        _record_call(
            provider,
            key if provider == "nim" else None,
            model,
            task_class,
            False,
            latency_ms,
            error_msg,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
        return False, error_msg, latency_ms
    except Exception as e:
        if provider == "gemini":
            _gemini_calls += 1
            _gemini_failures += 1
        latency_ms = (time.time() - start) * 1000
        error_msg = f"Exception: {str(e)[:200]}"
        _record_call(
            provider,
            key if provider == "nim" else None,
            model,
            task_class,
            False,
            latency_ms,
            error_msg,
            char_id=char_id,
            source=source,
            system_path=system_path,
            is_final=False,
        )
        return False, error_msg, latency_ms


# ── Public API: Route Call ──────────────────────────────────────────


# ── Prompt cache (in-memory, LRU) ───────────────────────────────────
# Caches only successful route_call results. Keyed on everything that can
# change the output: task_class, char_id, source, prompts, sampling params,
# fallback toggles, and a route-config version salt. api_key / system_path are
# intentionally excluded (legacy-compat / attribution-only; they do not change
# generated content). char_id in the key guarantees councilor outputs are never
# reused across characters (e.g. Archimedes char_001 vs Oracle char_306).
ROUTE_CACHE_VERSION = "2026-07-15"
_PROMPT_CACHE_TTL = 600          # seconds (soft; enforced via LRU cap below)
_PROMPT_CACHE_MAX = 2000         # max entries; LRU eviction
_PROMPT_CACHE_LOCK = threading.Lock()
_PROMPT_CACHE = OrderedDict()    # key -> deep-copied result dict


def _prompt_cache_key(
    task_class, system_prompt, user_prompt, max_tokens, temperature,
    allow_ollama, allow_gemini, char_id, source,
):
    payload = "|".join(
        repr(x) for x in (
            task_class, char_id, source, system_prompt, user_prompt,
            max_tokens, temperature, allow_ollama, allow_gemini,
            ROUTE_CACHE_VERSION,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_cache_get(key):
    with _PROMPT_CACHE_LOCK:
        if key not in _PROMPT_CACHE:
            return None
        _PROMPT_CACHE.move_to_end(key)          # LRU touch
        return copy.deepcopy(_PROMPT_CACHE[key])


def _prompt_cache_put(key, result):
    with _PROMPT_CACHE_LOCK:
        _PROMPT_CACHE[key] = copy.deepcopy(result)
        _PROMPT_CACHE.move_to_end(key)
        while len(_PROMPT_CACHE) > _PROMPT_CACHE_MAX:
            _PROMPT_CACHE.popitem(last=False)   # evict oldest


def route_call(
    task_class: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    allow_ollama: bool = True,
    allow_gemini: bool = True,
    char_id: str = "",
    source: str = "",
    system_path: str = "",
    api_key: Optional[str] = None,
) -> Dict:
    """Route an LLM call through the multi-provider tiered system.

    Fallback chain (ALL priority modes):
      NIM primary → NIM fallback → Ollama(3B) → OpenRouter free → Gemini → template fallback

    Args:
        task_class: One of "leader", "specialist", "worker", "narrator"
        system_prompt: System message
        user_prompt: User message
        max_tokens: Override default max_tokens for this task class
        temperature: Override default temperature
        allow_ollama: Whether local Ollama may be used in the fallback chain
        allow_gemini: Whether Gemini may be used as the last-resort fallback
        char_id: Optional NPC id for llm_audit attribution
        source: Optional source for llm_audit attribution
        system_path: Optional call-site path for llm_audit attribution
        api_key: Legacy compatibility parameter; routing uses configured keys

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
    if not source and task_class in ("assistant", "narrator"):
        source = task_class
    # ── Prompt cache lookup ───────────────────────────────────────
    # On a hit we return a deep copy and skip the provider chain entirely.
    # A cache hit intentionally skips llm_audit (no real call was made).
    _cache_key = _prompt_cache_key(
        task_class, system_prompt, user_prompt, max_tokens, temperature,
        allow_ollama, allow_gemini, char_id, source,
    )
    _cached = _prompt_cache_get(_cache_key)
    if _cached is not None:
        return _cached


    config = TASK_MODELS.get(task_class)
    if not config:
        error = f"Unknown task class: {task_class}"
        result["errors"].append(error)
        _record_final_route_call(
            "",
            "",
            task_class,
            False,
            0,
            error=error,
            char_id=char_id,
            source=source,
            system_path=system_path,
        )
        if result.get("success"): _prompt_cache_put(_cache_key, result)
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
    # 5. Gemini fallback (global or task override; budget-guarded)
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
            provider,
            model,
            messages,
            tier_mt,
            tier_temp,
            tier_timeout,
            task_class=task_class,
            char_id=char_id,
            source=source,
            system_path=system_path,
        )

        _record_provider_result(provider, ok)

        if ok and content:
            result["success"] = True
            result["content"] = content
            result["provider"] = provider
            result["model"] = model
            result["latency_ms"] = latency
            _record_final_route_call(
                provider,
                model,
                task_class,
                True,
                latency,
                content,
                char_id=char_id,
                source=source,
                system_path=system_path,
            )
            if result.get("success"): _prompt_cache_put(_cache_key, result)
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
    if allow_ollama and _check_ollama_available() and not _is_circuit_open("ollama"):
        result["attempts"] += 1
        ok, content, latency = _call_ollama(
            messages,
            mt,
            temp,
            task_class=task_class,
            char_id=char_id,
            source=source,
            system_path=system_path,
        )
        if ok and content:
            result["success"] = True
            result["content"] = content
            result["provider"] = "ollama"
            result["model"] = OLLAMA_MODEL
            result["latency_ms"] = latency
            _record_final_route_call(
                "ollama",
                OLLAMA_MODEL,
                task_class,
                True,
                latency,
                content,
                char_id=char_id,
                source=source,
                system_path=system_path,
            )
            if result.get("success"): _prompt_cache_put(_cache_key, result)
            return result
        else:
            result["errors"].append(f"ollama/{OLLAMA_MODEL}: {content[:150]}")
            result["latency_ms"] += latency

    # ── OpenRouter free fallback (pool rotation) ─────────────────────
    or_config = config.get("fallback_openrouter")
    if or_config:
        provider = or_config["provider"]
        tier_mt = max_tokens if max_tokens is not None else or_config["max_tokens"]
        tier_temp = (
            temperature if temperature is not None else or_config["temperature"]
        )
        tier_timeout = or_config.get("timeout", 25)
        pool = or_config.get("models", [])
        # Legacy: if config still has single "model" key, use a 1-element pool
        if not pool and or_config.get("model"):
            pool = [or_config["model"]]

        # Try up to 3 models from the pool (skip circuit-open ones)
        max_or_tries = min(3, len(pool))
        or_tries = 0
        while or_tries < max_or_tries and pool:
            model = _get_or_free_model(pool)
            or_tries += 1
            cb_key = f"or_free_model:{model}"

            if _is_circuit_open(cb_key):
                continue

            # Also check overall openrouter circuit (rate limit, key issues)
            if _is_circuit_open(provider):
                break

            result["attempts"] += 1
            ok, content, latency = _call_provider(
                provider,
                model,
                messages,
                tier_mt,
                tier_temp,
                tier_timeout,
                task_class=task_class,
                char_id=char_id,
                source=source,
                system_path=system_path,
            )
            # Record per-model circuit breaker
            _record_provider_result(cb_key, ok)
            # Also record at provider level for rate-limit tracking
            _record_provider_result(provider, ok)
            if ok and content:
                result["success"] = True
                result["content"] = content
                result["provider"] = provider
                result["model"] = model
                result["latency_ms"] = latency
                _record_final_route_call(
                    provider,
                    model,
                    task_class,
                    True,
                    latency,
                    content,
                    char_id=char_id,
                    source=source,
                    system_path=system_path,
                )
                if result.get("success"): _prompt_cache_put(_cache_key, result)
                return result
            else:
                result["errors"].append(f"{provider}/{model}: {content[:150]}")
                result["latency_ms"] += latency

    # ── OpenRouter paid fallback (requires credits) ──────────────────
    or_paid_config = config.get("fallback_openrouter_paid")
    if or_paid_config:
        pp = or_paid_config["provider"]
        pmodel = or_paid_config["model"]
        pmt = max_tokens if max_tokens is not None else or_paid_config["max_tokens"]
        ptemp = (
            temperature if temperature is not None else or_paid_config["temperature"]
        )
        ptimeout = or_paid_config.get("timeout", 25)

        if not _is_circuit_open("openrouter_paid"):
            result["attempts"] += 1
            ok, content, latency = _call_provider(
                pp,
                pmodel,
                messages,
                pmt,
                ptemp,
                ptimeout,
                task_class=task_class,
                char_id=char_id,
                source=source,
                system_path=system_path,
            )
            _record_provider_result("openrouter_paid", ok)
            if ok and content:
                result["success"] = True
                result["content"] = content
                result["provider"] = pp
                result["model"] = pmodel
                result["latency_ms"] = latency
                _record_final_route_call(
                    pp,
                    pmodel,
                    task_class,
                    True,
                    latency,
                    content,
                    char_id=char_id,
                    source=source,
                    system_path=system_path,
                )
                if result.get("success"): _prompt_cache_put(_cache_key, result)
                return result
            else:
                result["errors"].append(f"{pp}/{pmodel}: {content[:150]}")
                result["latency_ms"] += latency

    # ── Gemini fallback (budget-guarded last resort) ──────────────────
    gemini_config = config.get("fallback_gemini") or {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "max_tokens": mt,
        "temperature": temp,
        "timeout": GEMINI_TIMEOUT,
    }
    if allow_gemini and gemini_config and _check_gemini_available():
        provider = gemini_config["provider"]
        model = gemini_config["model"]
        tier_mt = max_tokens if max_tokens is not None else gemini_config["max_tokens"]
        tier_temp = (
            temperature if temperature is not None else gemini_config["temperature"]
        )
        tier_timeout = gemini_config.get("timeout", GEMINI_TIMEOUT)

        allowed, reason = _check_gemini_budget(task_class, model)
        if not allowed:
            result["errors"].append(reason)
        elif not _is_circuit_open(provider):
            result["attempts"] += 1
            ok, content, latency = _call_provider(
                provider,
                model,
                messages,
                tier_mt,
                tier_temp,
                tier_timeout,
                task_class=task_class,
                char_id=char_id,
                source=source,
                system_path=system_path,
            )
            _record_provider_result(provider, ok)
            if ok and content:
                result["success"] = True
                result["content"] = content
                result["provider"] = provider
                result["model"] = model
                result["latency_ms"] = latency
                _record_final_route_call(
                    provider,
                    model,
                    task_class,
                    True,
                    latency,
                    content,
                    char_id=char_id,
                    source=source,
                    system_path=system_path,
                )
                if result.get("success"): _prompt_cache_put(_cache_key, result)
                return result
            else:
                result["errors"].append(f"{provider}/{model}: {content[:150]}")
                result["latency_ms"] += latency

    logger.error(
        "All LLM providers failed for task_class=%s: %s",
        task_class,
        "; ".join(result["errors"][:3]),
    )
    _record_final_route_call(
        result.get("provider", ""),
        result.get("model", ""),
        task_class,
        False,
        result.get("latency_ms", 0),
        error="; ".join(result["errors"][:3]),
        char_id=char_id,
        source=source,
        system_path=system_path,
    )
    if result.get("success"): _prompt_cache_put(_cache_key, result)
    return result


def route_assistant_call(
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    source: str = "",
    system_path: str = "",
) -> Dict:
    """Route the human-facing assistant through bounded cloud providers only.

    The live chat UI has its own timeout and should not burn time on the local
    Ollama fallback path. Use the assistant task's fast NIM/OpenRouter chain and
    avoid long last-resort providers that outlive the browser request.
    """
    attribution = {}
    if source:
        attribution["source"] = source
    if system_path:
        attribution["system_path"] = system_path
    return route_call(
        task_class="assistant",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        allow_ollama=False,
        allow_gemini=False,
        **attribution,
    )


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
            char_id=call.get("char_id", ""),
            source=call.get("source", ""),
            system_path=call.get("system_path", ""),
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
        "openrouter_configured": bool(OPENROUTER_KEYS),
        "openrouter_keys_available": len(OPENROUTER_KEYS),
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
        "gemini_allowed_tasks": sorted(GEMINI_ALLOWED_TASKS),
        "gemini_daily_call_cap": GEMINI_MAX_CALLS_PER_DAY,
        "gemini_monthly_call_cap": GEMINI_MAX_CALLS_PER_MONTH,
        "gemini_monthly_usd_cap": GEMINI_MONTHLY_USD_CAP,
        "grok_available": _check_grok_available(),
        "grok_calls": _grok_calls,
        "grok_failures": _grok_failures,
        "task_classes": list(TASK_MODELS.keys()),
        "or_free_pools": {
            "large": OR_FREE_POOL_LARGE,
            "mid": OR_FREE_POOL_MID,
            "small": OR_FREE_POOL_SMALL,
        },
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

    try:
        keys = _gemini_budget_keys()
        stats["gemini_budget"] = {
            "daily_calls": int(r.get(keys["daily_calls"]) or 0),
            "monthly_calls": int(r.get(keys["monthly_calls"]) or 0),
            "monthly_input_tokens": int(r.get(keys["monthly_input_tokens"]) or 0),
            "monthly_output_tokens": int(r.get(keys["monthly_output_tokens"]) or 0),
            "monthly_total_tokens": int(r.get(keys["monthly_total_tokens"]) or 0),
            "monthly_usd_estimate": round(float(r.get(keys["monthly_usd"]) or 0.0), 6),
        }
    except Exception:
        stats["gemini_budget"] = {
            "daily_calls": -1,
            "monthly_calls": -1,
            "monthly_input_tokens": -1,
            "monthly_output_tokens": -1,
            "monthly_total_tokens": -1,
            "monthly_usd_estimate": -1.0,
        }

    return stats
