#!/usr/bin/env python3
"""NVIDIA NIM Client -- LLM client for NPC cognition.

Provides a multi-key, multi-model client for NVIDIA NIM free endpoints.
Uses the OpenAI-compatible API at integrate.api.nvidia.com/v1.

Features:
- Round-robin key rotation across multiple NIM API keys
- Primary/fallback model chain (Qwen3 Coder -> Minimax -> Gemma)
- Rate-limit tracking per key with cooldown windows
- Token budget management (max calls per tick cycle)
- Automatic reasoning_content extraction for thinking models
- Circuit breaker: if all keys fail, gracefully degrades to templates

Architecture:
  npc_autonomy._call_llm() -> NimClient.call() -> OpenAI SDK -> NVIDIA NIM
"""

import logging
import os
import time
from typing import Dict, List, Optional

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
MAX_CALLS_PER_CYCLE = 20
MAX_CALLS_PER_KEY_PER_MINUTE = 15


# ---------------------------------------------------------------------------
# Key state tracking
# ---------------------------------------------------------------------------


class _KeyState:
    """Track rate-limit state for a single API key."""

    __slots__ = ("key", "last_used", "call_count", "cooldown_until", "errors")

    def __init__(self, key: str):
        self.key = key
        self.last_used: float = 0.0
        self.call_count: int = 0
        self.cooldown_until: float = 0.0
        self.errors: int = 0

    def is_available(self) -> bool:
        now = time.time()
        if now < self.cooldown_until:
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

        if not self.keys:
            logger.warning("NimClient: No NIM API keys configured")

    def _get_openai_client(self, api_key: str):
        """Lazy-create an OpenAI client for a given key."""
        if api_key not in self._openai_clients:
            try:
                from openai import OpenAI

                self._openai_clients[api_key] = OpenAI(
                    base_url=NIM_BASE_URL,
                    api_key=api_key,
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

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 80,
        temperature: float = 0.8,
    ) -> str:
        """Call the LLM with automatic key rotation and model fallback.

        Returns the generated text string, or "" if all attempts fail.
        """
        if not self.keys:
            return ""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for model_cfg in MODEL_CHAIN:
            model_id = model_cfg["id"]
            timeout = model_cfg["timeout"]
            mt = min(max_tokens, model_cfg["max_tokens_default"])
            tp = model_cfg.get("top_p_default", 0.9)

            # Try up to 2 keys per model
            for _attempt in range(2):
                ks = self._next_available_key()
                if ks is None:
                    break

                client = self._get_openai_client(ks.key)
                if client is None:
                    continue

                try:
                    resp = client.chat.completions.create(
                        model=model_id,
                        messages=messages,
                        max_tokens=mt,
                        temperature=temperature,
                        top_p=tp,
                        stream=False,
                        timeout=timeout,
                    )

                    ks.mark_used()
                    self._cycle_calls += 1
                    self._total_calls += 1

                    msg = resp.choices[0].message
                    content = msg.content

                    # Thinking model fallback: extract from reasoning_content
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
        return ""

    def get_stats(self) -> Dict:
        """Return usage statistics."""
        return {
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "cycle_calls": self._cycle_calls,
            "cycle_budget": MAX_CALLS_PER_CYCLE,
            "keys_available": sum(1 for k in self.keys if k.is_available()),
            "keys_total": len(self.keys),
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
