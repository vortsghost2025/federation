#!/usr/bin/env python3
"""
FEDERATION GAME — LLM Router

Multi-provider routing layer for tiered NPC cognition.
Supports NVIDIA NIM, OpenRouter, and future local/OpenAI-compatible endpoints.

Design principles:
- Provider-agnostic: NIM, OpenRouter, Ollama, any OpenAI-compatible API
- Key rotation for NIM (40 keys, round-robin with least-recently-used)
- Per-provider rate limit awareness (Redis-backed call tracking)
- Task-class routing: leader/specialist/worker/narrator → different models
- Fallback chain: primary → secondary → tertiary
- Structured output validation before world state effects
- Timeout and retry logic with exponential backoff
- Audit logging to Redis

Redis keys:
    llm_call_log:{provider}  — ZSET (score=timestamp) of recent calls
    llm_key_last_used:{key_hash} — STRING timestamp
    llm_errors:{provider} — ZSET of recent errors
    llm_audit — ZSET of all LLM calls (TTL 7d)
"""

import hashlib
import json
import logging
import os
import random
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
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_RATE_LIMIT_PER_KEY = 40  # requests per minute per key
NIM_RATE_LIMIT_WINDOW = 60  # seconds

# OpenRouter — single key
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Circuit breaker — if a provider fails N times in a window, skip it
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures to trip
CIRCUIT_BREAKER_WINDOW = 300  # seconds (5 min)
CIRCUIT_BREAKER_KEY_PREFIX = "llm_circuit_breaker:"

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
    """Route an LLM call through the tiered system with fallbacks.

    Tries: primary → fallback_nim → fallback_openrouter

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

    # Try each tier: primary → fallback_nim → fallback_openrouter
    for tier_name in ("primary", "fallback_nim", "fallback_openrouter"):
        tier_config = config.get(tier_name)
        if not tier_config:
            continue

        provider = tier_config["provider"]
        model = tier_config["model"]
        mt = max_tokens if max_tokens is not None else tier_config["max_tokens"]
        temp = temperature if temperature is not None else tier_config["temperature"]
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
            provider, model, messages, mt, temp, tier_timeout
        )

        _record_provider_result(provider, ok)

        if ok and content:
            result["success"] = True
            result["content"] = content
            result["provider"] = provider
            result["model"] = model
            result["latency_ms"] = latency
            # Record task class in audit
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
        "task_classes": list(TASK_MODELS.keys()),
        "recent_calls": {},
        "recent_errors": {},
    }

    # Count recent calls per provider (last 60s)
    for provider in ("nim", "openrouter"):
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
                counter_key = "llm_call_log:openrouter"
                r.zremrangebyscore(counter_key, 0, now - 60)
                stats["recent_calls"]["openrouter"] = r.zcard(counter_key)
        except Exception:
            stats["recent_calls"][provider] = -1

    # Recent errors
    for provider in ("nim", "openrouter"):
        try:
            errors = r.zrevrange(f"llm_errors:{provider}", 0, 4)
            stats["recent_errors"][provider] = len(errors)
        except Exception:
            stats["recent_errors"][provider] = -1

    return stats
