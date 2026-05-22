#!/usr/bin/env python3
"""NVIDIA NIM Client + Ollama Offload -- LLM client for NPC cognition.

Provides a tiered LLM routing system:
  Tier 1 (cheap/high-volume): Local Ollama (qwen2.5-coder:7b via Tailscale)
  Tier 2 (cloud): NVIDIA NIM (5 keys, Qwen3/Minimax/Gemma)
  Tier 3 (last resort): None (returns None for template fallback)

Features:
- Ollama offload: high-volume NPC thoughts go to local GPU, saving NIM budget
- Round-robin key rotation across multiple NIM API keys
- Primary/fallback model chain (Qwen3 Coder -> Minimax -> Gemma) on NIM
- Rate-limit tracking per key with cooldown windows
- Token budget management (max calls per tick cycle)
- Automatic reasoning_content extraction for thinking models
- Circuit breaker: if all keys fail, gracefully degrades to templates
- Priority routing: "local" (Ollama first), "cloud" (NIM only for high-value)

Architecture:
npc_autonomy._call_llm() -> NimClient.call(priority=...) -> Ollama/NIM
"""

import asyncio
import logging
import os
import time
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

# Fallback: also check individual key env vars
for _i in range(1, 5):
    _k = os.environ.get(f"NIM_API_KEY_{_i}", "")
    if _k and _k not in NIM_API_KEYS:
        NIM_API_KEYS.append(_k)

# Extra keys from the NVIDIA developer account (hardcoded as fallback)
# These are free-tier NIM keys valid for 100 years
_FALLBACK_KEYS = [
    "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",
    "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",
    "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",
    "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",
]
for _fk in _FALLBACK_KEYS:
    if _fk not in NIM_API_KEYS:
        NIM_API_KEYS.append(_fk)

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
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://100.95.92.117:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "15"))
_ollama_available: Optional[bool] = None  # lazy-checked on first call


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
    """Multi-key, multi-model LLM client for NVIDIA NIM.

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
        self._ollama_calls: int = 0
        self._ollama_failures: int = 0

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
    # Ollama tier -- local GPU via Tailscale
    # ------------------------------------------------------------------

    @staticmethod
    def _check_ollama() -> bool:
        """Lazy-check if Ollama is reachable (cached after first check)."""
        global _ollama_available
        if _ollama_available is not None:
            return _ollama_available
        try:
            import urllib.request

            base = OLLAMA_BASE_URL.replace("/v1", "")
            r = urllib.request.urlopen(f"{base}/api/tags", timeout=3)
            _ollama_available = r.status == 200
            if _ollama_available:
                logger.info("Ollama available at %s (model: %s)", base, OLLAMA_MODEL)
            return bool(_ollama_available)
        except Exception:
            _ollama_available = False
            logger.info("Ollama not reachable at %s -- NIM-only mode", OLLAMA_BASE_URL)
            return False

    async def _call_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """Try local Ollama inference. Returns content string or None."""
        if not self._check_ollama():
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            from openai import AsyncOpenAI

            ollama_client = AsyncOpenAI(
                base_url=OLLAMA_BASE_URL,
                api_key="ollama",  # Ollama doesn't need a real key
                timeout=httpx.Timeout(float(OLLAMA_TIMEOUT), connect=5.0),
                max_retries=1,
            )
            resp = await asyncio.wait_for(
                ollama_client.chat.completions.create(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    max_tokens=min(max_tokens, 512),
                    temperature=temperature,
                    stream=False,
                ),
                timeout=float(OLLAMA_TIMEOUT) + 5.0,
            )
            content = resp.choices[0].message.content
            if content:
                content = content.strip().strip('"').strip("'")
                if len(content) > 500:
                    content = content[:500]
                self._ollama_calls += 1
                logger.debug("Ollama: %s -> %d chars", OLLAMA_MODEL, len(content))
                return content
        except asyncio.TimeoutError:
            self._ollama_failures += 1
            logger.warning("Ollama: %s timed out (%ds)", OLLAMA_MODEL, OLLAMA_TIMEOUT)
        except Exception as exc:
            self._ollama_failures += 1
            exc_str = str(exc).lower()
            if "connect" in exc_str or "refused" in exc_str:
                global _ollama_available
                _ollama_available = False
                logger.info("Ollama connection lost -- falling back to NIM")
            else:
                logger.warning("Ollama: error: %s", exc)
        return None

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
        priority: str = "local",
    ) -> Optional[str]:
        """Call LLM with tiered routing.

        priority="local" (default): Try Ollama first, then NIM. Good for
            high-volume NPC thoughts where quality can be "good enough".
        priority="cloud": Skip Ollama, use NIM only. For high-value content
            like faction justifications, narration, diplomacy.
        """
        # Tier 1: Local Ollama (cheap, fast, unlimited) for "local" priority
        if priority == "local":
            ollama_result = await self._call_ollama(
                system_prompt, user_prompt, max_tokens, temperature
            )
            if ollama_result is not None:
                return ollama_result

        # Tier 2: NIM cloud (quality, rate-limited)
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

    def get_stats(self) -> Dict:
        """Return usage statistics."""
        return {
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "cycle_calls": self._cycle_calls,
            "cycle_budget": MAX_CALLS_PER_CYCLE,
            "keys_available": sum(1 for k in self.keys if k.is_available()),
            "keys_total": len(self.keys),
            "ollama_calls": self._ollama_calls,
            "ollama_failures": self._ollama_failures,
            "ollama_available": self._check_ollama(),
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
