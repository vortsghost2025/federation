"""Prometheus metrics shim for the LLM router.

Surfaces the data the router ALREADY records in Redis so it can be graphed in
Grafana without touching router behavior:

- ``llm_audit`` zset           -> total calls + final-route decisions
- ``llm_errors:<provider>``    -> per-provider error counts
- ``llm_circuit_breaker:<p>``  -> per-provider circuit-open state (1/0)

The router already writes all of the above; this module only scrapes them into
the shared metrics registry. If Redis is unavailable the metrics simply stay at
their last value (no exception escapes ``collect``).

Wire into ``routes/metrics.py`` by importing ``collect_llm_metrics`` and calling
it from ``collect_all``.
"""

import logging

import redis as _redis

logger = logging.getLogger(__name__)

# Lazily reuse the same registry instance as routes/metrics.py so /metrics
# exports once. Importing prometheus_client and building the metrics is deferred
# to _ensure() so a missing package or a different import order never crashes
# module load (mirrors the lazy style in routes/metrics.py).
_registry = None
_llm_calls_total = None
_llm_errors_total = None
_llm_circuit_open = None
_initialized = False

# Provider names match the router's CIRCUIT_BREAKER_KEY_PREFIX consumers.
_PROVIDERS = ("nim", "cloudflare", "together", "openrouter", "gemini", "grok", "ollama")
_CIRCUIT_BREAKER_KEY_PREFIX = "llm_circuit_breaker:"
_REDIS_URL = "redis://redis:6379/0"

_pool = None


def _r():
    global _pool
    if _pool is None:
        _pool = _redis.ConnectionPool.from_url(_REDIS_URL, decode_responses=True, max_connections=2)
    return _redis.Redis(connection_pool=_pool)


def _ensure():
    """Build the LLM metrics on the shared registry. Safe if prometheus missing."""
    global _registry, _llm_calls_total, _llm_errors_total, _llm_circuit_open, _initialized
    if _initialized:
        return True
    try:
        from prometheus_client import Counter, Gauge, CollectorRegistry
        try:
            from routes.metrics import _registry as shared
        except Exception:
            shared = CollectorRegistry()
        _registry = shared
        _llm_calls_total = Counter(
            "federation_llm_calls_total",
            "Total LLM router calls recorded in llm_audit",
            registry=_registry,
        )
        _llm_errors_total = Counter(
            "federation_llm_errors_total",
            "Total LLM provider errors recorded in llm_errors:<provider>",
            ["provider"],
            registry=_registry,
        )
        _llm_circuit_open = Gauge(
            "federation_llm_circuit_open",
            "1 if a provider's circuit breaker is currently open, else 0",
            ["provider"],
            registry=_registry,
        )
        _initialized = True
        return True
    except ImportError:
        logger.warning("prometheus_client not available — LLM metrics disabled")
        return False
    except Exception as exc:
        logger.warning("LLM metrics init failed: %s", exc)
        return False


def _circuit_open(r, provider: str) -> int:
    try:
        key = f"{_CIRCUIT_BREAKER_KEY_PREFIX}{provider}"
        val = r.get(key)
        ttl = r.ttl(key)
        return 1 if val == "open" and ttl and ttl > 0 else 0
    except Exception:
        return 0


def collect_llm_metrics():
    """Scrape router Redis zsets into the shared registry. Safe if Redis is down."""
    if not _ensure():
        return
    try:
        r = _r()
    except Exception as exc:
        logger.warning("LLM metrics: redis unavailable: %s", exc)
        return

    # Total calls from the audit zset cardinality (cheap, no payload read).
    try:
        total = r.zcard("llm_audit")
        if isinstance(total, int):
            _llm_calls_total.inc(max(total - int(_llm_calls_total._value.get()), 0))
    except Exception as exc:
        logger.warning("LLM metrics: audit scrape failed: %s", exc)

    # Per-provider errors + circuit state.
    for provider in _PROVIDERS:
        try:
            errs = r.zcard(f"llm_errors:{provider}")
            if isinstance(errs, int):
                _llm_errors_total.labels(provider=provider).inc(
                    max(errs - int(_llm_errors_total.labels(provider=provider)._value.get()), 0)
                )
        except Exception:
            pass
        try:
            _llm_circuit_open.labels(provider=provider).set(_circuit_open(r, provider))
        except Exception:
            pass
