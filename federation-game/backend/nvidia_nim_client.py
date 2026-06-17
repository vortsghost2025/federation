#!/usr/bin/env python3
"""NVIDIA NIM Client + Multi-Provider Offload -- LLM client for NPC cognition.

Routing order (ALL priority modes):
  Tier 1 (primary):    NVIDIA NIM (6 keys, Nemotron/GPT-OSS/Llama)
  Tier 2 (fallback):   Ollama local (qwen2.5-coder:3b via Tailscale)
  Tier 3 (last resort): OpenRouter free models

Features:
- NIM first: primary provider for all call types (user has 8B credits/month)
- OpenRouter: free-tier fallback with key rotation
- Ollama: local GPU fallback, concurrency-gated
- Round-robin key rotation across multiple NIM API keys
- Rate-limit tracking per key with cooldown windows
- Token budget management (max calls per tick cycle)
- Automatic reasoning_content extraction for thinking models
- Circuit breaker: if a provider fails, gracefully degrades

Architecture:
npc_autonomy._call_llm() -> NimClient.call(priority=...) -> NIM -> Ollama -> OpenRouter
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
# Also check standard NVIDIA_API_KEY env var (common in NVIDIA tooling)
_NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "")
if _NVIDIA_KEY and _NVIDIA_KEY not in NIM_API_KEYS:
    NIM_API_KEYS.append(_NVIDIA_KEY)

# Model priority chain -- Proven fast models only
# Nemotron Super 49B as primary (fast, reliable)
# GPT-OSS 120B as second (user preference, slightly slower)
# Llama 3.1 8B as last-resort NIM (smallest, fastest)
MODEL_CHAIN = [
    {
        "id": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "max_tokens_default": 4096,
        "temperature_default": 0.7,
        "top_p_default": 0.8,
        "is_thinking_model": False,
        "timeout": 12,
    },
    {
        "id": "openai/gpt-oss-120b",
        "max_tokens_default": 4096,
        "temperature_default": 0.7,
        "top_p_default": 0.8,
        "is_thinking_model": False,
        "timeout": 15,
    },
    {
        "id": "meta/llama-3.1-8b-instruct",
        "max_tokens_default": 2048,
        "temperature_default": 0.7,
        "top_p_default": 0.8,
        "is_thinking_model": False,
        "timeout": 10,
    },
]

# Rate limit config
COOLDOWN_SECONDS = 60
MAX_CALLS_PER_CYCLE = 30
MAX_CALLS_PER_KEY_PER_MINUTE = 20

# NIM per-attempt timeout — reduced to 10s for faster fail-over with faster models.
# GPT-OSS-120B, GLM-5.1, Nemotron-3-Ultra typically respond in 3-8s.
NIM_PER_ATTEMPT_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Ollama configuration -- local GPU inference via Tailscale
# HARDENED: concurrency=2, queue=5, cooldown=60s on 500s, tags cache 60s
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://100.95.92.117:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b-instruct-q4_K_M")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "30"))
OLLAMA_TAGS_CACHE_TTL = int(os.environ.get("OLLAMA_TAGS_CACHE_TTL", "60"))

# Heavy model (7B) — DISABLED by default. Set OLLAMA_HEAVY_ENABLED=1 to allow.
OLLAMA_HEAVY_MODEL = os.environ.get("OLLAMA_HEAVY_MODEL", "qwen2.5-coder:7b")
OLLAMA_HEAVY_KEEP_ALIVE = os.environ.get("OLLAMA_HEAVY_KEEP_ALIVE", "3m")
OLLAMA_HEAVY_ENABLED = os.environ.get("OLLAMA_HEAVY_ENABLED", "") == "1"

# Backpressure: max 2 active calls (Ollama can handle 2 concurrent on most GPUs),
# max 5 queued, cooldown 60s on 500/client-abort. Increased from 1→2 active
# to allow parallel NPC thought generation while respecting GPU limits.
OLLAMA_MAX_ACTIVE = int(os.environ.get("OLLAMA_MAX_ACTIVE", "2"))
OLLAMA_MAX_QUEUE = int(os.environ.get("OLLAMA_MAX_QUEUE", "5"))
OLLAMA_COOLDOWN_SECONDS = int(os.environ.get("OLLAMA_COOLDOWN_SECONDS", "60"))

_ollama_available: Optional[bool] = None
_ollama_tags_last_check: float = 0.0
_ollama_checking: bool = False  # sentinel to prevent concurrent /api/tags polls


class OllamaLane:
    """Thread-safe Ollama call scheduler with backpressure.

    Enforces: max 2 active calls, max 5 queued, cooldown 60s on 500/client-abort.
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
# OpenRouter configuration -- free-tier fallback with key rotation
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_KEY_1 = os.environ.get("OPENROUTER_API_KEY_1", "")
OPENROUTER_KEYS = [k for k in [OPENROUTER_API_KEY, OPENROUTER_API_KEY_1] if k]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT = int(os.environ.get("OPENROUTER_TIMEOUT", "25"))
_openrouter_key_index: int = 0

# OpenRouter free models per priority class
OPENROUTER_MODELS = {
    "local": "meta-llama/llama-3.3-70b-instruct:free",
    "cloud": "meta-llama/llama-3.3-70b-instruct:free",
    "heavy": "meta-llama/llama-3.3-70b-instruct:free",
}


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
        # OpenRouter stats
        self._openrouter_calls: int = 0
        self._openrouter_failures: int = 0

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
    # Tier 3: OpenRouter free models -- last resort fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _get_openrouter_key() -> Optional[str]:
        """Get next OpenRouter API key (round-robin rotation)."""
        global _openrouter_key_index
        if not OPENROUTER_KEYS:
            return None
        key = OPENROUTER_KEYS[_openrouter_key_index % len(OPENROUTER_KEYS)]
        _openrouter_key_index += 1
        return key

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
        priority: str = "local",
    ) -> Optional[str]:
        """Call OpenRouter free models. Returns content string or None."""
        key = self._get_openrouter_key()
        if not key:
            return None

        model = OPENROUTER_MODELS.get(priority, "meta-llama/llama-3.3-70b-instruct:free")

        try:
            from openai import AsyncOpenAI

            or_client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=key,
                timeout=httpx.Timeout(float(OPENROUTER_TIMEOUT), connect=5.0),
                max_retries=1,
            )
            resp = await asyncio.wait_for(
                or_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=min(max_tokens, 512),
                    temperature=temperature,
                    stream=False,
                    extra_headers={
                        "HTTP-Referer": "https://federation-game.deliberatefederation.cloud",
                        "X-Title": "Federation Game LLM Router",
                    },
                ),
                timeout=float(OPENROUTER_TIMEOUT) + 5.0,
            )
            content = resp.choices[0].message.content
            if content:
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._openrouter_calls += 1
                logger.info(
                    "OpenRouter: model=%s chars=%d success=True",
                    model,
                    len(content),
                )
                return content
            self._openrouter_failures += 1
            return None
        except asyncio.TimeoutError:
            self._openrouter_failures += 1
            logger.warning("OpenRouter: timed out (%ds)", OPENROUTER_TIMEOUT)
        except Exception as exc:
            self._openrouter_failures += 1
            logger.warning("OpenRouter: error: %s", str(exc)[:100])
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
                        timeout=float(NIM_PER_ATTEMPT_TIMEOUT),
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
                        if content.startswith(("The user", "So we", "Let me", "We need")):
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
                    logger.warning(
                        "NimClient: %s call timed out (%ds limit)",
                        model_id,
                        NIM_PER_ATTEMPT_TIMEOUT,
                    )
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
        """Call LLM with NIM-first tiered routing.

        ALL priority modes use the same chain:
          Tier 1: NVIDIA NIM (primary, user has 8B credits/month)
          Tier 2: Ollama local (3B model via Tailscale)
          Tier 3: OpenRouter free (last resort)
        """
        result = None

        # Tier 1: NIM cloud -- primary for ALL call types
        result = await self._call_nim(
            system_prompt, user_prompt, max_tokens, temperature
        )
        if result is not None:
            return result

        # Tier 2: Ollama local -- fallback to local GPU
        heavy = (priority == "heavy")
        result = await self._call_ollama(
            system_prompt, user_prompt, max_tokens, temperature, heavy=heavy
        )
        if result is not None:
            return result

        # Tier 3: OpenRouter free -- last resort
        result = await self._call_openrouter(
            system_prompt, user_prompt, max_tokens, temperature, priority=priority
        )
        return result

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
            "openrouter_calls": self._openrouter_calls,
            "openrouter_failures": self._openrouter_failures,
            "openrouter_keys": len(OPENROUTER_KEYS),
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
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        try:
            return executor.submit(asyncio.run, coro).result()
        finally:
            executor.shutdown(wait=False)
    else:
        return asyncio.run(coro)
