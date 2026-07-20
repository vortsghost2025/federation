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


# ── G5 Deterministic JSON Mock Decision Engine ─────────────────────────────────
# Replaces the old string-returning mock. Produces valid JSON decisions,
# exercises all action categories, triggers anti-loop logic (streak detection,
# dedup, cooldowns, topic fatigue), and is deterministic across PYTHONHASHSEED.
# Zero credentials, zero network.

_G5_CATEGORIES = [
    "send_message",
    "create_artifact",
    "write_code",
    "read_artifacts",
    "investigate",
    "rest",
    "self_improve",
    "create_institution",
    "propose_role",
    "submit_to_institution",
    "request_capability",
]

_G5_TOPICS = [
    "symbolic governance",
    "resonance theory",
    "echo chambers",
    "anchor network signals",
    "pair awareness",
    "institutional memory",
    "topic fatigue recovery",
    "fourth wall integrity",
    "deduplication strategy",
    "councilor handoff",
]

_G5_INSTITUTIONS = [
    ("Guild of Echoes", "council"),
    ("Bureau of Resonance", "bureau"),
    ("Assembly of Anchors", "assembly"),
    ("Tribunal of Forms", "tribunal"),
    ("Committee of Futures", "committee"),
]

_G5_ROLES = [
    ("Echo Keeper", "Guild of Echoes", "observe_and_report"),
    ("Resonance Auditor", "Bureau of Resonance", "review_and_warn"),
    ("Anchor Witness", "Assembly of Anchors", "review_and_enforce"),
    ("Form Analyst", "Tribunal of Forms", "review_and_propose"),
]

_G5_MOCK_CALL_COUNT = {"count": 0}  # module-level, deterministic progression


class _G5MockEngine:
    """Deterministic JSON decision engine. Produces valid JSON that triggers
    real parser paths, anti-loop logic, deduplication, and topic transitions.

    All outputs are a function of:
      - call_label (which determines which schema to use)
      - char_id (from environment, shifts starting position in cycles)
      - call_sequence (increments each call, never resets mid-run)
      - system_prompt hash (shifts topic selection per NPC)
    None of these sources are affected by PYTHONHASHSEED.
    """

    def __init__(self, char_id="char_001"):
        self.char_id = char_id
        # Shift starting index per char_id so NPCs don't start in lock-step.
        self._char_offset = (int(char_id.split("_")[1]) if char_id.split("_")[1].isdigit() else 0) * 3
        # Track artifact topics for dedup-trigger scenarios.
        self._artifact_topics_seen = []   # type: list[str]
        self._last_category = None        # type: str | None
        self._last_topic = None           # type: str | None
        self._consecutive_send_streak = 0
        self._artifact_count = 0

    def _topic_for_call(self, call_seq, prompt_hash):
        nibble = int(prompt_hash[:4], 16) if prompt_hash else call_seq
        idx = (call_seq + self._char_offset + (nibble % 10)) % len(_G5_TOPICS)
        return _G5_TOPICS[idx]

    def _next(self, call_seq, system_prompt_hash=""):
        """Return the next decision dict (not JSON string yet) for call number `call_seq`."""
        # Anti-loop: detect consecutive send_message streak.
        if self._last_category == "send_message":
            self._consecutive_send_streak += 1
        else:
            self._consecutive_send_streak = 0

        # Advance call_seq by char offset for per-NPC variation.
        seq = call_seq + self._char_offset

        # Determine category using a deterministic cycle.
        cat_idx = seq % len(_G5_CATEGORIES)

        # Anti-loop: force create_artifact if 2+ consecutive sends with 0 artifacts.
        if self._last_category == "send_message" and self._consecutive_send_streak >= 2 and self._artifact_count == 0:
            cat_idx = 1  # create_artifact
            self._consecutive_send_streak = 0

        category = _G5_CATEGORIES[cat_idx]

        # Anti-loop: force investigate if repeated create_artifact on same topic.
        if category == "create_artifact":
            topic = self._topic_for_call(call_seq, system_prompt_hash)
            topic_streak = self._artifact_topics_seen.count(topic)
            if topic_streak >= 2:
                category = "investigate"

        # Build decision payload.
        decision = {"category": category}
        topic = self._topic_for_call(call_seq, system_prompt_hash)
        reasoning = f"G5 deterministic mock tick {call_seq} for {self.char_id} about {topic}."

        if category == "send_message":
            target = "char_306" if self.char_id == "char_001" else "char_001"
            decision.update({
                "reasoning": reasoning,
                "target": target,
                "body": f"Shadow message {call_seq} from {self.char_id} to {target}.",
                "description": f"message to {target}",
            })
            self._consecutive_send_streak += 1
        elif category == "create_artifact":
            decision.update({
                "reasoning": reasoning,
                "description": f"artifact about {topic}",
                "title": f"Artifact #{call_seq}: {topic.title()}",
            })
            self._artifact_topics_seen.append(topic)
            self._artifact_count += 1
        elif category == "write_code":
            decision.update({
                "reasoning": reasoning,
                "description": f"helper code for {topic}",
            })
        elif category == "read_artifacts":
            decision.update({
                "reasoning": reasoning,
                "description": f"reading artifacts about {topic}",
            })
        elif category == "investigate":
            decision.update({
                "reasoning": reasoning,
                "description": f"investigating {topic}",
            })
        elif category == "rest":
            decision.update({
                "reasoning": reasoning,
                "description": f"resting and reflecting on {topic}",
            })
        elif category == "self_improve":
            decision.update({
                "reasoning": reasoning,
                "description": f"improving capability: {topic}",
            })
        elif category == "create_institution":
            name, kind = _G5_INSTITUTIONS[seq % len(_G5_INSTITUTIONS)]
            decision.update({
                "reasoning": reasoning,
                "institution_name": name,
                "institution_kind": kind,
                "mandate": f"Mandate for {name}: address {topic} in the federation.",
            })
        elif category == "propose_role":
            title, inst, auth = _G5_ROLES[seq % len(_G5_ROLES)]
            decision.update({
                "reasoning": reasoning,
                "institution_name": inst,
                "role_title": title,
                "scope": f"Scope: {topic}",
                "authority": auth,
            })
        elif category == "submit_to_institution":
            inst = _G5_INSTITUTIONS[seq % len(_G5_INSTITUTIONS)][0]
            decision.update({
                "reasoning": reasoning,
                "artifact_title": f"Artifact #{max(0, call_seq - 1)}: {topic.title()}",
                "institution_name": inst,
            })
        elif category == "request_capability":
            need_types = ["information_access", "memory_access", "coordination_help",
                          "institution_support", "workflow_visibility",
                          "decision_feedback", "world_state_gap"]
            need = need_types[seq % len(need_types)]
            decision.update({
                "reasoning": reasoning,
                "need_type": need,
                "priority": ["high", "medium", "low"][seq % 3],
                "description": f"need: {topic}",
                "why_needed": f"{topic} is limiting effectiveness",
                "suggested_capability": f"cap-{call_seq}",
            })

        self._last_category = category
        self._last_topic = topic
        return decision


# Module-level engine instances (one per char_id; reused across calls).
_G5_ENGINES = {}  # char_id -> _G5MockEngine


def _get_g5_engine(char_id):
    if char_id not in _G5_ENGINES:
        _G5_ENGINES[char_id] = _G5MockEngine(char_id)
    return _G5_ENGINES[char_id]


# ── Mock provider (deterministic, no credentials, no network) ──


def mock_provider(system_prompt, user_prompt, model="", r=None, call_label=""):
    """Deterministic recorded-response provider. No network, no credentials.

    For call_label="decide": returns valid JSON with realistic decision structure
    that exercises all action categories, anti-loop logic, dedup, and topic
    transitions. Identical across PYTHONHASHSEED=0,1,random because all inputs
    are deterministic (environment vars, sequential counter, hashlib).

    For call_label in ("artifact", "code"): returns a deterministic mock
    artifact payload.

    All other labels: returns a deterministic placeholder string.
    """
    count_model_call()
    ok, reason = check_limits()
    if not ok:
        return {"content": "", "model": "shadow-mock", "shadow_limit": reason}

    # Advance sequence counter.
    call_seq = _G5_MOCK_CALL_COUNT["count"]
    _G5_MOCK_CALL_COUNT["count"] += 1

    char_id = os.environ.get("CHAR_ID", "char_001")
    engine = _get_g5_engine(char_id)

    # Deterministic prompt hash (only for topic selection — not a security risk).
    prompt_hash = hashlib.sha256(
        f"{char_id}|{call_seq}".encode("utf-8")
    ).hexdigest()

    if call_label == "decide":
        decision = engine._next(call_seq, prompt_hash)
        content = json.dumps(decision, separators=(",", ":"))
    elif call_label in ("artifact", "code"):
        content = json.dumps({
            "category": call_label,
            "result": f"shadow-mock:{call_label} #{call_seq}",
            "model": "shadow-mock",
        }, separators=(",", ":"))
    else:
        content = f"shadow-mock:{call_label}"

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
    """Test helper. Resets all shadow counters AND the G5 mock engine state."""
    global _tick_count, _model_call_count, _intent_count, _log_bytes, _intents
    _tick_count = 0
    _model_call_count = 0
    _intent_count = 0
    _log_bytes = 0
    _intents = []
    # Reset G5 mock engine state.
    _G5_MOCK_CALL_COUNT["count"] = 0
    _G5_ENGINES.clear()


def get_intents():
    return list(_intents)


def intents_for_category(cat):
    return [i for i in _intents if i.get("category") == cat]
