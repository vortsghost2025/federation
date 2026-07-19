"""
NPC Shadow Mode — bounded, reversible, fail-closed isolation gate.

This module is the single source of truth for SHADOW_MODE behavior. It is
imported by npc_actions.py (dispatcher-level protection) and by
npc_redis_helpers.py (sink-level defense in depth). It MUST NOT perform any
external operation itself.

Design guarantees (verified by test_npc_shadow_mode.py):
  * SHADOW_MODE requires a non-empty, sanitized SHADOW_INSTANCE_ID. Invalid
    configuration raises ShadowConfigError (fail closed).
  * Every writable key is namespaced under shadow:<instance_id>.
  * record_intent() stores ONLY sanitized category, normalized topic, tick,
    NPC ID, and instance ID. No bodies, prompts, credentials, artifact text,
    or private messages are ever persisted.
  * The intent log is capped at SHADOW_MAX_LOG_BYTES.
  * Unknown / newly added action categories default to BLOCKED.
  * Production Redis URL or any production service endpoint is rejected.
  * Provider calls use a deterministic mock (zero credentials, zero network).

Nothing here deploys, connects to production, or triggers cognition.
"""

import hashlib
import json
import logging
import os
import re
import time

logger = logging.getLogger("npc_shadow_mode")

# Well-known production endpoint fragments. Shadow mode must never touch these.
_BLOCKED_URL_FRAGMENTS = (
    "postgres",
    "postgresql",
    "mysql",
    "mongodb",
    "amqp",
    "rabbitmq",
    "kafka",
    "redis://redis:",        # production redis service name
    "redis://redis.",        # production redis host
    ":5432",                 # common postgres port
    "supabase",
    "nvidianim",
    "api.openai",
    "openrouter",
)

_BLOCKED_ENV_KEYS = (
    "NVIDIA_API_KEY",
    "FALLBACK_KEY_1",
    "FALLBACK_KEY_2",
    "OPENROUTER_API_KEY",
    "OPERATOR_LLM_API_KEY",
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
)


class ShadowConfigError(Exception):
    """Raised when SHADOW_MODE is misconfigured. Fail closed."""


class ShadowBlocked(Exception):
    """Raised when a protected sink is invoked under SHADOW_MODE."""


class ShadowLogLimit(Exception):
    """Raised when the append-only intent log would exceed SHADOW_MAX_LOG_BYTES."""


def _parse_bool(value):
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ── Configuration (resolved at import and on configure()) ──
SHADOW = False
SHADOW_NS = "shadow:unknown"
SHADOW_MAX_TICKS = 200
SHADOW_MAX_RUNTIME_S = 3600
SHADOW_MAX_MODEL_CALLS = 50
SHADOW_MAX_LOG_BYTES = 10 * 1024 * 1024
SHADOW_LOG_PATH = ""
_SANITIZED = ""
_RAW_SHADOW = ""
_RAW_INSTANCE_ID = ""

# Counters (enforced by the gate caller)
_tick_count = 0
_model_call_count = 0
_start_ts = time.time()
_intent_count = 0
_log_bytes = 0
_intents = []  # in-memory intent store when no log path is configured


def configure():
    """Re-read all configuration from the environment. Safe to call after
    monkeypatch.setenv in tests; no import/reload needed."""
    global SHADOW, SHADOW_NS, SHADOW_MAX_TICKS, SHADOW_MAX_RUNTIME_S
    global SHADOW_MAX_MODEL_CALLS, SHADOW_MAX_LOG_BYTES, SHADOW_LOG_PATH
    global _SANITIZED, _RAW_SHADOW, _RAW_INSTANCE_ID
    _RAW_SHADOW = os.environ.get("SHADOW_MODE", "")
    SHADOW = _parse_bool(_RAW_SHADOW)
    _RAW_INSTANCE_ID = (os.environ.get("SHADOW_INSTANCE_ID", "") or "").strip()
    _SANITIZED = re.sub(r"[^a-z0-9_-]", "", _RAW_INSTANCE_ID.lower())
    SHADOW_NS = f"shadow:{_SANITIZED}" if _SANITIZED else "shadow:unknown"
    SHADOW_MAX_TICKS = int(os.environ.get("SHADOW_MAX_TICKS", "200"))
    SHADOW_MAX_RUNTIME_S = int(os.environ.get("SHADOW_MAX_RUNTIME_S", "3600"))
    SHADOW_MAX_MODEL_CALLS = int(os.environ.get("SHADOW_MAX_MODEL_CALLS", "50"))
    SHADOW_MAX_LOG_BYTES = int(os.environ.get("SHADOW_MAX_LOG_BYTES", str(10 * 1024 * 1024)))
    SHADOW_LOG_PATH = os.environ.get("SHADOW_LOG_PATH", "")


configure()


def validate_config():
    """Fail closed: raise ShadowConfigError on any unsafe configuration."""
    if not SHADOW:
        return
    if not _SANITIZED:
        raise ShadowConfigError(
            "SHADOW_MODE=true requires a non-empty SHADOW_INSTANCE_ID "
            "(sanitized to [a-z0-9_-])."
        )
    if _SANITIZED != _RAW_INSTANCE_ID.lower():
        raise ShadowConfigError(
            "SHADOW_INSTANCE_ID contains invalid characters; "
            "use only [a-z0-9_-]."
        )
    # Reject any production credential being present in the environment.
    for key in _BLOCKED_ENV_KEYS:
        if os.environ.get(key):
            raise ShadowConfigError(
                f"Production credential {key} must not be present in SHADOW_MODE."
            )
    # Reject a production Redis URL.
    redis_url = os.environ.get("REDIS_URL", "")
    if _looks_like_production_url(redis_url):
        raise ShadowConfigError(
            f"REDIS_URL '{redis_url}' points at production; "
            "shadow must use a dedicated shadow Redis."
        )
    # Reject known production service endpoint variables (do not scan the whole
    # environment, which would flag unrelated dev-shell values).
    for ep_key in ("DATABASE_URL", "POSTGRES_URL", "REDIS_URL",
                   "SERVICE_URL", "API_URL", "LLM_BASE_URL"):
        val = os.environ.get(ep_key, "")
        if val and _looks_like_production_url(val):
            raise ShadowConfigError(
                f"Production service endpoint {ep_key}='{val}' detected."
            )


def _looks_like_production_url(url):
    if not url:
        return False
    low = url.lower()
    return any(frag in low for frag in _BLOCKED_URL_FRAGMENTS)


# ── Namespacing ──
def shadow_key(key):
    """Namespace every writable key under the shadow instance."""
    return f"{SHADOW_NS}:{key}"


def _normalize_topic(decision):
    topic = decision.get("topic") or decision.get("description") or ""
    # Keep only alnum/space, lowercase, truncate — never store bodies.
    norm = re.sub(r"[^a-z0-9 ]", " ", (topic or "").lower())
    norm = " ".join(norm.split())[:80]
    return norm


# ── Intent recording (no private content) ──
def record_intent(category, decision=None, extra=None):
    """Append-only intent record. Stores ONLY non-private metadata."""
    global _intent_count, _log_bytes
    if not SHADOW:
        return None
    entry = {
        "instance": _SANITIZED,
        "char_id": os.environ.get("CHAR_ID", ""),
        "category": category,
        "normalized_topic": _normalize_topic(decision) if decision else "",
        "tick": _tick_count,
        "ts": int(time.time()),
    }
    if extra:
        # extra is restricted to scalar, non-private fields by callers.
        for k, v in extra.items():
            if k in ("target", "title", "action_taken", "shadow_intent_recorded"):
                entry[k] = v
    payload = json.dumps(entry, default=str)
    encoded = payload.encode("utf-8")
    # Hard boundary: never exceed SHADOW_MAX_LOG_BYTES. Check before appending.
    if _log_bytes + len(encoded) > SHADOW_MAX_LOG_BYTES:
        # Emit at most one small sanitized marker when space permits.
        marker = json.dumps({
            "instance": _SANITIZED,
            "category": "log_limit_reached",
            "tick": _tick_count,
            "ts": int(time.time()),
        }, default=str)
        if _log_bytes + len(marker.encode("utf-8")) <= SHADOW_MAX_LOG_BYTES:
            try:
                with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as fh:
                    fh.write(marker + "\n")
            except OSError:
                pass
            _log_bytes += len(marker.encode("utf-8"))
        raise ShadowLogLimit("Shadow intent log cap reached; write refused.")
    _intent_count += 1
    _log_bytes += len(encoded)
    _intents.append(entry)
    if SHADOW_LOG_PATH:
        try:
            with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(payload + "\n")
        except OSError as e:
            logger.warning("Shadow intent log write failed: %s", e)
    return entry


# ── Dispatcher gate ──
# Categories that are read-only / loop-control state and are SAFE in shadow.
_SHADOW_SAFE_CATEGORIES = {
    "rest",
    "read_artifacts",
    "investigate",   # stat writes blocked, but intent recorded; no external write
    "self_improve",  # stat writes blocked
    "reflect",       # stat writes blocked
}

# Categories that are explicitly WRITE-capable and become intent-only in shadow.
_SHADOW_WRITE_CATEGORIES = {
    "send_message",
    "create_artifact",
    "write_code",
    "create_institution",
    "propose_role",
    "submit_to_institution",
    "request_capability",
    "operator_ack",
}

ALL_KNOWN = _SHADOW_SAFE_CATEGORIES | _SHADOW_WRITE_CATEGORIES


def assert_shadow_blocked(surface):
    """Sink-level guard. Raises ShadowBlocked if used under SHADOW_MODE.

    Call at the entry of any write sink so that a direct helper call outside
    npc_actions.py cannot bypass the dispatcher gate.
    """
    if SHADOW:
        raise ShadowBlocked(
            f"Sink '{surface}' is blocked under SHADOW_MODE; "
            "intent recorded, no external write performed."
        )


def category_blocked(cat):
    """Fail closed: unknown / new categories are blocked by default."""
    if cat in _SHADOW_SAFE_CATEGORIES:
        return False
    # Known write categories are redirected to intent-only; not "blocked" from
    # recording, but no external action. Truly unknown categories are blocked.
    return cat not in ALL_KNOWN


def shadow_result(category, decision):
    """Truthful result returned when an action is shadowed."""
    result = {
        "char_id": os.environ.get("CHAR_ID", ""),
        "category": category,
        "shadow_intent_recorded": True,
        "shadow_instance": _SANITIZED,
        "action_taken": "shadow_intent_only",
    }
    return result


# ── Limit enforcement ──
def tick():
    global _tick_count
    _tick_count += 1
    return _tick_count


def check_limits():
    """Return (ok, reason). Caller must terminate safely when ok is False."""
    if _tick_count >= SHADOW_MAX_TICKS:
        return False, "max_ticks_reached"
    if time.time() - _start_ts >= SHADOW_MAX_RUNTIME_S:
        return False, "max_runtime_reached"
    if _model_call_count >= SHADOW_MAX_MODEL_CALLS:
        return False, "max_model_calls_reached"
    return True, ""


def count_model_call():
    global _model_call_count
    _model_call_count += 1
    return _model_call_count


# ── Mock provider (deterministic, no credentials, no network) ──
_MOCK_RESPONSES = {
    "artifact": "Shadow artifact text (deterministic mock).",
    "code": "print('shadow mock code')",
    "decision": "rest",
}


def mock_provider(system_prompt, user_prompt, model="", r=None, call_label=""):
    """Deterministic recorded-response provider. No network, no credentials."""
    count_model_call()
    ok, reason = check_limits()
    if not ok:
        return {"content": "", "model": "shadow-mock", "shadow_limit": reason}
    label = call_label or "decision"
    content = _MOCK_RESPONSES.get(label, f"shadow-mock:{label}")
    # Deterministic digest of (system, prompt) so output is reproducible.
    digest = hashlib.sha256(
        f"{system_prompt}|{user_prompt}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "content": content,
        "model": "shadow-mock",
        "digest": digest,
        "shadow": True,
    }


def get_provider():
    """Return the provider callable to use. Mock by default in shadow."""
    if SHADOW:
        return mock_provider
    return None  # production uses its own call_llm


def reset_counters():
    """Test helper."""
    global _tick_count, _model_call_count, _intent_count, _log_bytes, _intents
    _tick_count = 0
    _model_call_count = 0
    _intent_count = 0
    _log_bytes = 0
    _intents = []


def get_intents():
    return list(_intents)


def intents_for_category(cat):
    return [i for i in _intents if i.get("category") == cat]
