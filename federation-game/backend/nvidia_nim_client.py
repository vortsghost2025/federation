#!/usr/bin/env python3
"""NVIDIA NIM Client + Multi-Provider Offload -- LLM client for NPC cognition.

Provides a tiered LLM routing system:
 Tier 0 (local): Ollama (qwen2.5-coder:3b-q4_K_M via Tailscale, 7B only for high-significance)
Tier 0.5 (free):    Cloudflare Workers AI (llama-3.1-8b)
Tier 1.5 (free):    Together AI, Google Gemini Flash
Tier 2 (cloud):     NVIDIA NIM (6 keys, Qwen3/Minimax/Gemma)
Tier 2.5 (cloud):   Grok/xAI
Tier 3 (last resort): None (returns None for template fallback)

Features:
- Ollama offload: high-volume NPC thoughts go to local GPU, saving NIM budget
- Cloudflare Workers AI: free, fast, good for NPC thoughts when Ollama is down
- Together AI: free tier, OpenAI-compatible, good for mid-tier routing
- Google Gemini Flash: free, fast, high quality for important calls
- Grok/xAI: high quality, for faction/diplomacy calls
- Round-robin key rotation across multiple NIM API keys
- Primary/fallback model chain (Qwen3 Coder -> Minimax -> Gemma) on NIM
- Rate-limit tracking per key with cooldown windows
- Token budget management (max calls per tick cycle)
- Automatic reasoning_content extraction for thinking models
- Circuit breaker: if a provider fails, gracefully degrades
- Priority routing: "local" (Ollama→CF→NIM), "cloud" (Gemini→Grok→NIM)

Architecture:
npc_autonomy._call_llm() -> NimClient.call(priority=...) -> Ollama/CF/Together/Gemini/NIM/Grok
"""

import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration -- all from env vars
# ---------------------------------------------------------------------------

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Comma-separated NIM API keys from env
_NIM_KEYS_ENV = os.environ.get("NIM_API_KEYS", "")
NIM_API_KEYS: List[str] = [k.strip() for k in _NIM_KEYS_ENV.split(",") if k.strip()]
# Also check individual key env vars NIM_API_KEY_1 through NIM_API_KEY_8
for _i in range(1, 9):
    _k = os.environ.get(f"NIM_API_KEY_{_i}", "")
    if _k and _k not in NIM_API_KEYS:
        NIM_API_KEYS.append(_k)

# Model priority chain -- Qwen3 Coder is best for content (not a thinking model)
# Minimax is a thinking model (reasoning_content) -- handled but less ideal
# Gemma is slow but works as last resort
MODEL_CHAIN = [
    {
        "id": "qwen/qwen3-coder-480b-a35b-instruct",
        "max_tokens_default": 4096,
        "temperature_default": 0.7,
        "top_p_default": 0.8,
        "is_thinking_model": False,
        "timeout": 30,
    },
    {
        "id": "minimaxai/minimax-m2.7",
        "max_tokens_default": 8192,
        "temperature_default": 1.0,
        "top_p_default": 0.95,
        "is_thinking_model": True,
        "timeout": 30,
    },
    {
        "id": "google/gemma-4-31b-it",
        "max_tokens_default": 16384,
        "temperature_default": 1.0,
        "top_p_default": 0.95,
        "is_thinking_model": False,
        "timeout": 60,
    },
]

# Rate limit config
COOLDOWN_SECONDS = 60
MAX_CALLS_PER_CYCLE = 30
MAX_CALLS_PER_KEY_PER_MINUTE = 20

# ---------------------------------------------------------------------------
# Ollama configuration -- local GPU inference via Tailscale
# HARDENED: concurrency=1, queue=3, cooldown=60s on 500s, tags cache 60s
# ---------------------------------------------------------------------------
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

_ollama_available: Optional[bool] = None
_ollama_tags_last_check: float = 0.0
_ollama_checking: bool = False  # sentinel to prevent concurrent /api/tags polls


class OllamaLane:
    """Thread-safe Ollama call scheduler with backpressure.

    Enforces: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort.
    Logs per call: provider, model, timeout, queued_ms, success/fallback.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._queue_depth = 0
        self._cooldown_until: float = 0.0
        self._ollama_client = None  # reuse a single AsyncOpenAI client

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
            if self._queue_depth > 0:
                self._queue_depth -= 1
            elif self._active > 0:
                self._active -= 1
            if is_500:
                self._cooldown_until = time.time() + OLLAMA_COOLDOWN_SECONDS
                logger.warning(
                    "Ollama: 500/client-abort detected — cooldown %ds",
                    OLLAMA_COOLDOWN_SECONDS,
                )

    def get_ollama_client(self):
        """Get or create a reusable AsyncOpenAI client for Ollama."""
        if self._ollama_client is None:
            try:
                from openai import AsyncOpenAI

                self._ollama_client = AsyncOpenAI(
                    base_url=OLLAMA_BASE_URL,
                    api_key="ollama",
                    timeout=httpx.Timeout(float(OLLAMA_TIMEOUT), connect=5.0),
                    max_retries=0,
                )
            except ImportError:
                logger.error("openai package not installed")
                return None
        return self._ollama_client

    def stats(self) -> Dict:
        with self._lock:
            return {
                "active": self._active,
                "queue_depth": self._queue_depth,
                "cooling_down": time.time() < self._cooldown_until,
                "cooldown_remaining": max(0, self._cooldown_until - time.time()),
            }


_ollama_lane = OllamaLane()

# ---------------------------------------------------------------------------
# Cloudflare Workers AI configuration -- free, fast
# ---------------------------------------------------------------------------
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_MODEL = os.environ.get("CF_MODEL", "@cf/meta/llama-3.1-8b-instruct")
CF_BASE_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
)
CF_TIMEOUT = int(os.environ.get("CF_TIMEOUT", "15"))
_cf_available: Optional[bool] = None
_cf_last_check: float = 0.0
_CF_CHECK_INTERVAL = 120.0  # re-check every 2 min

# ---------------------------------------------------------------------------
# Together AI configuration -- free tier, OpenAI-compatible
# ---------------------------------------------------------------------------
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "")
TOGETHER_BASE_URL = os.environ.get("TOGETHER_BASE_URL", "https://api.together.xyz/v1")
TOGETHER_MODEL = os.environ.get("TOGETHER_MODEL", "meta-llama/Llama-3-8b-chat-hf")
TOGETHER_TIMEOUT = int(os.environ.get("TOGETHER_TIMEOUT", "20"))
_together_available: Optional[bool] = None
_together_last_check: float = 0.0
_TOGETHER_CHECK_INTERVAL = 300.0  # re-check every 5 min

# ---------------------------------------------------------------------------
# Google Gemini configuration -- free, fast, high quality
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "20"))
_gemini_available: Optional[bool] = None
_gemini_last_check: float = 0.0
_GEMINI_CHECK_INTERVAL = 300.0  # re-check every 5 min

# ---------------------------------------------------------------------------
# Grok/xAI configuration -- high quality
# ---------------------------------------------------------------------------
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
GROK_TIMEOUT = int(os.environ.get("GROK_TIMEOUT", "25"))
_grok_available: Optional[bool] = None
_grok_last_check: float = 0.0
_GROK_CHECK_INTERVAL = 300.0  # re-check every 5 min


# ---------------------------------------------------------------------------
# Key state tracking
# ---------------------------------------------------------------------------


class _KeyState:
    """Track rate-limit state for a single API key."""

    __slots__ = (
        "key",
        "last_used",
        "call_count",
        "cooldown_until",
        "errors",
        "consecutive_failures",
        "circuit_break_until",
    )

    def __init__(self, key: str):
        self.key = key
        self.last_used: float = 0.0
        self.call_count: int = 0
        self.cooldown_until: float = 0.0
        self.errors: int = 0
        self.consecutive_failures: int = 0
        self.circuit_break_until: float = 0.0

    CIRCUIT_BREAKER_THRESHOLD = 3
    CIRCUIT_BREAKER_SECONDS = 60

    def is_available(self) -> bool:
        now = time.time()
        if now < self.cooldown_until:
            return False
        if now < self.circuit_break_until:
            return False
        if now - self.last_used > 60:
            self.call_count = 0
        return self.call_count < MAX_CALLS_PER_KEY_PER_MINUTE

    def mark_used(self) -> None:
        self.last_used = time.time()
        self.call_count += 1

    def mark_rate_limited(self) -> None:
        self.cooldown_until = time.time() + COOLDOWN_SECONDS
        logger.warning(
            "NIM key %s... rate-limited, cooling down %ds",
            self.key[:12],
            COOLDOWN_SECONDS,
        )

    def mark_error(self) -> None:
        self.errors += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            self.circuit_break_until = time.time() + self.CIRCUIT_BREAKER_SECONDS
            logger.warning(
                "NIM key %s... circuit breaker tripped (%d consecutive failures), blocking %ds",
                self.key[:12],
                self.consecutive_failures,
                self.CIRCUIT_BREAKER_SECONDS,
            )

    def mark_success(self) -> None:
        self.consecutive_failures = 0

    def reset_cycle(self) -> None:
        self.call_count = 0


# ---------------------------------------------------------------------------
# NimClient
# ---------------------------------------------------------------------------


class NimClient:
    """Multi-key, multi-model LLM client with multi-provider support.

    Usage:
    client = NimClient()
    result = client.call(
        system_prompt="You are a space NPC...",
        user_prompt="What are you thinking?",
        max_tokens=80,
    )
    # result is a string, or "" if all keys/models failed
    """

    def __init__(self) -> None:
        self.keys: List[_KeyState] = [_KeyState(k) for k in NIM_API_KEYS]
        self._key_index: int = 0
        self._cycle_calls: int = 0
        self._cycle_start: float = time.time()
        self._total_calls: int = 0
        self._total_failures: int = 0
        self._openai_clients: Dict[str, object] = {}
        # Ollama stats
        self._ollama_calls: int = 0
        self._ollama_failures: int = 0
        # Cloudflare stats
        self._cf_calls: int = 0
        self._cf_failures: int = 0
        # Together stats
        self._together_calls: int = 0
        self._together_failures: int = 0
        # Gemini stats
        self._gemini_calls: int = 0
        self._gemini_failures: int = 0
        # Grok stats
        self._grok_calls: int = 0
        self._grok_failures: int = 0

        if not self.keys:
            logger.warning("NimClient: No NIM API keys configured")

    def _get_openai_client(self, api_key: str):
        if api_key not in self._openai_clients:
            try:
                from openai import AsyncOpenAI

                self._openai_clients[api_key] = AsyncOpenAI(
                    base_url=NIM_BASE_URL,
                    api_key=api_key,
                    timeout=httpx.Timeout(15.0, connect=5.0),
                    max_retries=2,
                )
            except ImportError:
                logger.error("openai package not installed")
                return None
        return self._openai_clients[api_key]

    def _next_available_key(self) -> Optional[_KeyState]:
        """Get the next available key (round-robin, skipping cooled-down)."""
        if not self.keys:
            return None
        now = time.time()
        if now - self._cycle_start > 60:
            self._cycle_calls = 0
            self._cycle_start = now
            for ks in self.keys:
                ks.reset_cycle()

        if self._cycle_calls >= MAX_CALLS_PER_CYCLE:
            logger.debug(
                "NimClient: cycle budget exhausted (%d/%d)",
                self._cycle_calls,
                MAX_CALLS_PER_CYCLE,
            )
            return None

        tried = 0
        while tried < len(self.keys):
            ks = self.keys[self._key_index % len(self.keys)]
            self._key_index += 1
            tried += 1
            if ks.is_available():
                return ks

        logger.warning("NimClient: All keys rate-limited or exhausted")
        return None

    # ------------------------------------------------------------------
    # Tier 0: Ollama -- local GPU via Tailscale
    # ------------------------------------------------------------------

    @staticmethod
    def _check_ollama() -> bool:
        """Check if Ollama is reachable. Polls /api/tags ONCE on first call.

        Once the model is confirmed present, returns True indefinitely without
        re-polling /api/tags. Only re-checks tags after a generation error
        explicitly sets _ollama_available = False (which triggers a re-check
        after OLLAMA_TAGS_CACHE_TTL cooldown).

        Uses _ollama_checking sentinel to prevent concurrent /api/tags polls
        on startup (avoids N simultaneous calls all polling tags at once).
        """
        global _ollama_available, _ollama_tags_last_check, _ollama_checking
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
            _ollama_available is not None
            and (now - _ollama_tags_last_check) < OLLAMA_TAGS_CACHE_TTL
        ):
            return False
        _ollama_checking = True
        try:
            import urllib.request

            base = OLLAMA_BASE_URL.replace("/v1", "")
            req = urllib.request.Request(f"{base}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
                _ollama_available = r.status == 200
                _ollama_tags_last_check = now
                if _ollama_available:
                    models = [m.get("name", "") for m in data.get("models", [])]
                    logger.info(
                        "Ollama available at %s (model: %s, models: %s)",
                        base,
                        OLLAMA_MODEL,
                        models[:5],
                    )
                return bool(_ollama_available)
        except Exception:
            _ollama_available = False
            _ollama_tags_last_check = now
            logger.info(
                "Ollama not reachable at %s -- cloud-only mode", OLLAMA_BASE_URL
            )
            return False
        finally:
            _ollama_checking = False

    async def _call_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
        heavy: bool = False,
    ) -> Optional[str]:
        """Try local Ollama inference with backpressure. Returns content string or None.

        Enforces: max 1 active call, max 3 queued, cooldown 60s on 500/client-abort.
        Heavy model (7B) is BLOCKED unless OLLAMA_HEAVY_ENABLED=1.
        Logs per call: provider, model, timeout, queued_ms, success/fallback.
        """
        if not self._check_ollama():
            return None

        # Block heavy calls unless explicitly enabled
        if heavy and not OLLAMA_HEAVY_ENABLED:
            logger.debug("Ollama: heavy model disabled (set OLLAMA_HEAVY_ENABLED=1)")
            return None

        if not _ollama_lane.is_available():
            logger.debug("Ollama: lane in cooldown, skipping")
            return None

        if not _ollama_lane.try_acquire():
            logger.info(
                "Ollama: lane full (active=%d, queue=%d), template fallback",
                OLLAMA_MAX_ACTIVE,
                OLLAMA_MAX_QUEUE,
            )
            return None

        model = OLLAMA_HEAVY_MODEL if heavy else OLLAMA_MODEL
        keep_alive = OLLAMA_HEAVY_KEEP_ALIVE if heavy else None
        queue_start = time.time()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        is_500 = False
        try:
            ollama_client = _ollama_lane.get_ollama_client()
            if ollama_client is None:
                return None

            queued_ms = int((time.time() - queue_start) * 1000)

            # Build kwargs for the create call
            create_kwargs = dict(
                model=model,
                messages=messages,
                max_tokens=min(max_tokens, 512),
                temperature=temperature,
                stream=False,
            )
            # keep_alive is passed via extra_body for Ollama's OpenAI-compatible API
            if keep_alive:
                create_kwargs["extra_body"] = {"keep_alive": keep_alive}

            call_start = time.time()
            resp = await asyncio.wait_for(
                ollama_client.chat.completions.create(**create_kwargs),
                timeout=float(OLLAMA_TIMEOUT) + 5.0,
            )
            call_ms = int((time.time() - call_start) * 1000)
            content = resp.choices[0].message.content
            if content:
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._ollama_calls += 1
                logger.info(
                    "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d call_ms=%d success=True chars=%d",
                    model,
                    OLLAMA_TIMEOUT,
                    queued_ms,
                    call_ms,
                    len(content),
                )
                _ollama_lane.release(was_error=False)
                return content
            else:
                self._ollama_failures += 1
                logger.info(
                    "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d call_ms=%d success=False fallback=empty",
                    model,
                    OLLAMA_TIMEOUT,
                    queued_ms,
                    call_ms,
                )
                _ollama_lane.release(was_error=True)
                return None

        except asyncio.TimeoutError:
            self._ollama_failures += 1
            call_ms = (
                int((time.time() - call_start) * 1000)
                if "call_start" in dir()
                else OLLAMA_TIMEOUT * 1000
            )
            logger.warning(
                "Ollama: provider=ollama model=%s timeout=%d queued_ms=%d call_ms=%d success=False fallback=timeout",
                model,
                OLLAMA_TIMEOUT,
                0,
                call_ms,
            )
            _ollama_lane.release(was_error=True)
            return None

        except Exception as exc:
            self._ollama_failures += 1
            exc_str = str(exc).lower()
            call_ms = (
                int((time.time() - call_start) * 1000) if "call_start" in dir() else 0
            )

            # Detect 500 errors and client aborts
            if (
                "500" in exc_str
                or "server error" in exc_str
                or "aborted" in exc_str
                or "reset" in exc_str
            ):
                is_500 = True
                logger.warning(
                    "Ollama: provider=ollama model=%s timeout=%d success=False fallback=500_cooldown error=%s",
                    model,
                    OLLAMA_TIMEOUT,
                    str(exc)[:100],
                )
            elif "connect" in exc_str or "refused" in exc_str:
                global _ollama_available
                _ollama_available = False
                logger.info(
                    "Ollama: provider=ollama model=%s timeout=%d success=False fallback=connection_lost",
                    model,
                    OLLAMA_TIMEOUT,
                )
            else:
                logger.warning(
                    "Ollama: provider=ollama model=%s timeout=%d success=False fallback=error error=%s",
                    model,
                    OLLAMA_TIMEOUT,
                    str(exc)[:100],
                )
        _ollama_lane.release(was_error=True, is_500=is_500)
        return None

    # ------------------------------------------------------------------
    # Tier 0.5: Cloudflare Workers AI -- free, fast, good for NPC thoughts
    # ------------------------------------------------------------------

    @staticmethod
    def _check_cloudflare() -> bool:
        """Check if Cloudflare Workers AI is available (cached)."""
        global _cf_available, _cf_last_check
        now = time.time()
        if _cf_available is not None and (now - _cf_last_check) < _CF_CHECK_INTERVAL:
            return _cf_available
        if not CF_API_TOKEN or not CF_ACCOUNT_ID:
            _cf_available = False
            _cf_last_check = now
            return False
        # Cloudflare is always "available" if we have credentials -- no health check needed
        _cf_available = True
        _cf_last_check = now
        return True

    async def _call_cloudflare(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Call Cloudflare Workers AI. Returns content string or None."""
        if not self._check_cloudflare():
            return None

        payload = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
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
            loop = asyncio.get_event_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=CF_TIMEOUT),
            )
            body = json.loads(resp_data.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000

            # Cloudflare response format: {"result": {"response": "..."}} or
            # OpenAI-compatible: {"choices": [{"message": {"content": "..."}}]}
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
                self._cf_calls += 1
                logger.debug(
                    "Cloudflare: %s -> %d chars (%dms)",
                    CF_MODEL,
                    len(content),
                    int(latency_ms),
                )
                return content

            logger.debug("Cloudflare: empty response")
            self._cf_failures += 1
            return None

        except asyncio.TimeoutError:
            self._cf_failures += 1
            logger.warning("Cloudflare: timed out (%ds)", CF_TIMEOUT)
        except urllib.error.HTTPError as e:
            self._cf_failures += 1
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            logger.warning("Cloudflare: HTTP %d: %s", e.code, err_body)
            if e.code == 429:
                global _cf_available
                _cf_available = False
                _cf_last_check = time.time()
        except Exception as exc:
            self._cf_failures += 1
            logger.warning("Cloudflare: error: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Tier 1.5: Together AI -- free tier, OpenAI-compatible
    # ------------------------------------------------------------------

    @staticmethod
    def _check_together() -> bool:
        """Check if Together AI is available (cached)."""
        global _together_available, _together_last_check
        now = time.time()
        if (
            _together_available is not None
            and (now - _together_last_check) < _TOGETHER_CHECK_INTERVAL
        ):
            return _together_available
        if not TOGETHER_API_KEY:
            _together_available = False
            _together_last_check = now
            return False
        _together_available = True
        _together_last_check = now
        return True

    async def _call_together(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Call Together AI via OpenAI-compatible API. Returns content string or None."""
        if not self._check_together():
            return None

        try:
            from openai import AsyncOpenAI

            together_client = AsyncOpenAI(
                base_url=TOGETHER_BASE_URL,
                api_key=TOGETHER_API_KEY,
                timeout=httpx.Timeout(float(TOGETHER_TIMEOUT), connect=5.0),
                max_retries=1,
            )
            resp = await asyncio.wait_for(
                together_client.chat.completions.create(
                    model=TOGETHER_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=min(max_tokens, 512),
                    temperature=temperature,
                    stream=False,
                ),
                timeout=float(TOGETHER_TIMEOUT) + 5.0,
            )
            content = resp.choices[0].message.content
            if content:
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._together_calls += 1
                logger.debug("Together: %s -> %d chars", TOGETHER_MODEL, len(content))
                return content
        except asyncio.TimeoutError:
            self._together_failures += 1
            logger.warning("Together: timed out (%ds)", TOGETHER_TIMEOUT)
        except Exception as exc:
            self._together_failures += 1
            exc_str = str(exc).lower()
            global _together_available
            if "429" in exc_str or "rate" in exc_str:
                _together_available = False
                _together_last_check = time.time()
                logger.info("Together AI rate limited -- pausing 5 min")
            elif "401" in exc_str or "auth" in exc_str:
                _together_available = False
                _together_last_check = time.time()
                logger.warning("Together AI auth failed -- disabling")
            else:
                logger.warning("Together: error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Tier 1.5: Google Gemini Flash -- free, fast, high quality
    # ------------------------------------------------------------------

    @staticmethod
    def _check_gemini() -> bool:
        """Check if Gemini API is available (cached)."""
        global _gemini_available, _gemini_last_check
        now = time.time()
        if (
            _gemini_available is not None
            and (now - _gemini_last_check) < _GEMINI_CHECK_INTERVAL
        ):
            return _gemini_available
        if not GEMINI_API_KEY:
            _gemini_available = False
            _gemini_last_check = now
            return False
        _gemini_available = True
        _gemini_last_check = now
        return True

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Call Google Gemini via REST API. Returns content string or None."""
        if not self._check_gemini():
            return None

        url = (
            f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent"
            f"?key={GEMINI_API_KEY}"
        )

        payload = json.dumps(
            {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            }
        ).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        start = time.time()

        try:
            loop = asyncio.get_event_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT),
            )
            body = json.loads(resp_data.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000

            # Gemini response format:
            # {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
            candidates = body.get("candidates") or [{}]
            parts = (candidates[0].get("content") or {}).get("parts") or [{}]
            content = parts[0].get("text") or ""

            if content and isinstance(content, str):
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._gemini_calls += 1
                logger.debug(
                    "Gemini: %s -> %d chars (%dms)",
                    GEMINI_MODEL,
                    len(content),
                    int(latency_ms),
                )
                return content

            logger.debug("Gemini: empty response")
            self._gemini_failures += 1
            return None

        except asyncio.TimeoutError:
            self._gemini_failures += 1
            logger.warning("Gemini: timed out (%ds)", GEMINI_TIMEOUT)
        except urllib.error.HTTPError as e:
            self._gemini_failures += 1
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            logger.warning("Gemini: HTTP %d: %s", e.code, err_body)
            global _gemini_available
            if e.code == 429:
                _gemini_available = False
                _gemini_last_check = time.time()
                logger.info("Gemini rate limited -- pausing 5 min")
            elif e.code == 403:
                _gemini_available = False
                _gemini_last_check = time.time()
                logger.warning("Gemini auth failed -- disabling")
        except Exception as exc:
            self._gemini_failures += 1
            logger.warning("Gemini: error: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Tier 2.5: Grok/xAI -- high quality, for important calls
    # ------------------------------------------------------------------

    @staticmethod
    def _check_grok() -> bool:
        """Check if Grok API is available (cached)."""
        global _grok_available, _grok_last_check
        now = time.time()
        if (
            _grok_available is not None
            and (now - _grok_last_check) < _GROK_CHECK_INTERVAL
        ):
            return _grok_available
        if not GROK_API_KEY:
            _grok_available = False
            _grok_last_check = now
            return False
        _grok_available = True
        _grok_last_check = now
        return True

    async def _call_grok(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Call Grok/xAI via OpenAI-compatible API. Returns content string or None."""
        if not self._check_grok():
            return None

        try:
            from openai import AsyncOpenAI

            grok_client = AsyncOpenAI(
                base_url=GROK_BASE_URL,
                api_key=GROK_API_KEY,
                timeout=httpx.Timeout(float(GROK_TIMEOUT), connect=5.0),
                max_retries=1,
            )
            resp = await asyncio.wait_for(
                grok_client.chat.completions.create(
                    model=GROK_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=False,
                ),
                timeout=float(GROK_TIMEOUT) + 5.0,
            )
            content = resp.choices[0].message.content
            if content:
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._grok_calls += 1
                logger.debug("Grok: %s -> %d chars", GROK_MODEL, len(content))
                return content
        except asyncio.TimeoutError:
            self._grok_failures += 1
            logger.warning("Grok: timed out (%ds)", GROK_TIMEOUT)
        except Exception as exc:
            self._grok_failures += 1
            exc_str = str(exc).lower()
            global _grok_available
            if "429" in exc_str or "rate" in exc_str:
                _grok_available = False
                _grok_last_check = time.time()
                logger.info("Grok rate limited -- pausing 5 min")
            elif "401" in exc_str or "auth" in exc_str:
                _grok_available = False
                _grok_last_check = time.time()
                logger.warning("Grok auth failed -- disabling")
            else:
                logger.warning("Grok: error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Tier 2: NIM cloud -- quality, rate-limited
    # ------------------------------------------------------------------

    async def _call_nim(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Call NIM with model chain fallback. Returns content string or None."""
        if not self.keys:
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for model_cfg in MODEL_CHAIN:
            model_id = model_cfg["id"]
            timeout = model_cfg["timeout"]
            mt = min(max_tokens, model_cfg["max_tokens_default"])
            tp = model_cfg.get("top_p_default", 0.9)

            for _attempt in range(2):
                ks = self._next_available_key()
                if ks is None:
                    break

                client = self._get_openai_client(ks.key)
                if client is None:
                    continue

                try:
                    resp = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=model_id,
                            messages=messages,
                            max_tokens=mt,
                            temperature=temperature,
                            top_p=tp,
                            stream=False,
                            timeout=timeout,
                        ),
                        timeout=20.0,
                    )

                    ks.mark_used()
                    ks.mark_success()
                    self._cycle_calls += 1
                    self._total_calls += 1

                    msg = resp.choices[0].message
                    content = msg.content

                    if (
                        not content
                        and hasattr(msg, "reasoning_content")
                        and msg.reasoning_content
                    ):
                        reasoning = msg.reasoning_content
                        sentences = [
                            s.strip()
                            for s in reasoning.replace("\n", ".").split(".")
                            if len(s.strip()) > 10
                        ]
                        if sentences:
                            content = sentences[-1]
                        if content.startswith(
                            ("The user", "So we", "Let me", "We need")
                        ):
                            content = (
                                ". ".join(sentences[-2:])
                                if len(sentences) >= 2
                                else sentences[-1]
                            )

                    if content:
                        content = content.strip().strip('"').strip("'")
                        if len(content) > 500:
                            content = content[:500]
                        logger.debug(
                            "NimClient: %s via %s... -> %d chars",
                            model_id,
                            ks.key[:12],
                            len(content),
                        )
                        return content

                    logger.debug("NimClient: %s returned empty content", model_id)

                except asyncio.TimeoutError:
                    ks.mark_error()
                    logger.warning("NimClient: %s call timed out (20s limit)", model_id)
                    self._total_failures += 1

                except Exception as exc:
                    exc_str = str(exc).lower()
                    ks.mark_error()
                    if "429" in exc_str or "rate" in exc_str:
                        ks.mark_rate_limited()
                    elif "timeout" in exc_str:
                        logger.warning("NimClient: %s timed out", model_id)
                    else:
                        logger.warning("NimClient: %s error: %s", model_id, exc)
                    self._total_failures += 1

        return None

    # ------------------------------------------------------------------
    # Main entry point -- tiered routing
    # ------------------------------------------------------------------

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
        priority: str = "local",
    ) -> Optional[str]:
        """Call LLM with tiered routing.

        priority="local" (default): Try Ollama(3B) → Cloudflare → Together → NIM.
        Good for high-volume NPC thoughts where quality can be "good enough".

        priority="cloud": Try Gemini → Grok → NIM. For high-value content
        like faction justifications, narration, diplomacy.

        priority="heavy": Try Ollama(7B, keep_alive=3m) → Gemini → Grok → NIM.
        For high-significance events that need deeper reasoning.
        The 7B model is loaded on-demand and auto-unloaded after keep_alive.
        """
        if priority == "local":
            # Tier 0: Local Ollama 3B (fastest, unlimited, free)
            ollama_result = await self._call_ollama(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if ollama_result is not None:
                return ollama_result

            # Tier 0.5: Cloudflare Workers AI (free, fast, good for thoughts)
            cf_result = await self._call_cloudflare(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if cf_result is not None:
                return cf_result

            # Tier 1.5: Together AI (free tier, better quality)
            together_result = await self._call_together(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if together_result is not None:
                return together_result

            # Tier 2: NIM cloud (quality, rate-limited)
            nim_result = await self._call_nim(
                system_prompt, user_prompt, max_tokens, temperature
            )
            return nim_result

        elif priority == "heavy":
            # Tier 0: Ollama 7B (deeper reasoning, keep_alive=3m, concurrency-gated)
            ollama_result = await self._call_ollama(
                system_prompt, user_prompt, max_tokens, temperature, heavy=True
            )
            if ollama_result is not None:
                return ollama_result

            # Tier 1.5: Gemini Flash (free, fast, high quality)
            gemini_result = await self._call_gemini(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if gemini_result is not None:
                return gemini_result

            # Tier 2.5: Grok/xAI (high quality)
            grok_result = await self._call_grok(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if grok_result is not None:
                return grok_result

            # Tier 2: NIM cloud (fallback)
            nim_result = await self._call_nim(
                system_prompt, user_prompt, max_tokens, temperature
            )
        return nim_result

    def get_stats(self) -> Dict:
        """Return usage statistics."""
        lane_stats = _ollama_lane.stats()
        return {
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "cycle_calls": self._cycle_calls,
            "cycle_budget": MAX_CALLS_PER_CYCLE,
            "keys_available": sum(1 for k in self.keys if k.is_available()),
            "keys_total": len(self.keys),
            "ollama_model": OLLAMA_MODEL,
            "ollama_heavy_model": OLLAMA_HEAVY_MODEL,
            "ollama_heavy_enabled": OLLAMA_HEAVY_ENABLED,
            "ollama_lane_active": lane_stats["active"],
            "ollama_lane_queue": lane_stats["queue_depth"],
            "ollama_lane_cooling_down": lane_stats["cooling_down"],
            "ollama_lane_cooldown_remaining": round(
                lane_stats["cooldown_remaining"], 1
            ),
            "ollama_calls": self._ollama_calls,
            "ollama_failures": self._ollama_failures,
            "ollama_available": self._check_ollama(),
            "cloudflare_calls": self._cf_calls,
            "cloudflare_failures": self._cf_failures,
            "cloudflare_available": self._check_cloudflare(),
            "together_calls": self._together_calls,
            "together_failures": self._together_failures,
            "together_available": self._check_together(),
            "gemini_calls": self._gemini_calls,
            "gemini_failures": self._gemini_failures,
            "gemini_available": self._check_gemini(),
            "grok_calls": self._grok_calls,
            "grok_failures": self._grok_failures,
            "grok_available": self._check_grok(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[NimClient] = None


def get_nim_client() -> NimClient:
    """Get the singleton NimClient instance."""
    global _client
    if _client is None:
        _client = NimClient()
    return _client


def _run_async(coro):
    """Run an async coroutine from sync context safely.

    If an event loop is already running (e.g. inside FastAPI),
    runs the coroutine in a separate thread to avoid blocking.
    Otherwise, uses asyncio.run() directly.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
