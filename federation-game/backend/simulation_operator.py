"""Simulation operator for autonomous Federation ticks.

This module wraps the existing NPC autonomy and simulation engine with a
supervisor layer that:
- validates input and output
- logs structured per-tick events to Redis
- injects safe fallback decisions for idle NPCs
- retries once if the downstream simulation engine fails
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis
import yaml

from npc_autonomy import simulation_tick
from simulation_engine import autonomous_tick

# Try to import apprise for notifications (same as worker.py)
try:
    import apprise
    APPRISE_AVAILABLE = True
except ImportError:
    apprise = None
    APPRISE_AVAILABLE = False

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

NPC_TURNS_KEY = "npc_turns"
NPC_MEMORY_EVENTS_KEY = "npc_memory_events"
NPC_TOOL_EVENTS_KEY = "npc_tool_events"
SIM_OPERATOR_STATUS_KEY = "simulation_operator_status"
SIM_OPERATOR_ALERTS_KEY = "simulation_operator_alerts"
SIM_OPERATOR_RECOVERY_KEY = "simulation_operator_recovery"
SIM_OPERATOR_HISTORY_KEY = "simulation_operator_history"


def _load_config() -> Dict[str, Any]:
    """Load configuration from YAML with environment variable overrides."""
    config_path = Path(__file__).parent / "simulation_operator.yaml"
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")
    # Environment variable overrides (flat keys with SIM_OPERATOR_ prefix)
    for key, value in os.environ.items():
        if key.startswith("SIM_OPERATOR_"):
            # Convert SIM_OPERATOR_REDIS_TTL_SECONDS -> redis.ttl_seconds
            parts = key[len("SIM_OPERATOR_"):].lower().split("_")
            if len(parts) >= 2:
                section = parts[0]
                key_name = "_".join(parts[1:])
                if section not in config:
                    config[section] = {}
                # Try to convert value
                try:
                    config[section][key_name] = yaml.safe_load(value)
                except Exception:
                    config[section][key_name] = value
    return config


CONFIG = _load_config()

# Configuration with defaults
REDIS_CONFIG = CONFIG.get("redis", {})
VALIDATION_CONFIG = CONFIG.get("validation", {})
RECOVERY_CONFIG = CONFIG.get("recovery", {})
ALERTS_CONFIG = CONFIG.get("alerts", {})
OPERATOR_CONFIG = CONFIG.get("operator", {})

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

NPC_TURNS_KEY = "npc_turns"
NPC_MEMORY_EVENTS_KEY = "npc_memory_events"
NPC_TOOL_EVENTS_KEY = "npc_tool_events"
SIM_OPERATOR_STATUS_KEY = "simulation_operator_status"
SIM_OPERATOR_ALERTS_KEY = "simulation_operator_alerts"
SIM_OPERATOR_RECOVERY_KEY = "simulation_operator_recovery"
SIM_OPERATOR_HISTORY_KEY = "simulation_operator_history"

_RUNAWAY_HISTORY_TTL = REDIS_CONFIG.get("runaway_history_ttl", 86400)
_RECENT_LOG_TTL = REDIS_CONFIG.get("ttl_seconds", 7 * 86400)
_STALLED_SIM_SECONDS = REDIS_CONFIG.get("stalled_sim_seconds", 300)

RUNWAY_THRESHOLD = VALIDATION_CONFIG.get("runaway_threshold", 6)
IDLE_NPC_FALLBACK = VALIDATION_CONFIG.get("idle_npc_fallback", "rest")
MAX_LLM_CALLS_PER_TICK = VALIDATION_CONFIG.get("max_llm_calls_per_tick", 1)
AMBIENT_TRIGGER_RATE = VALIDATION_CONFIG.get("ambient_trigger_rate", 0.0)

MAX_RETRIES = RECOVERY_CONFIG.get("max_retries", 1)
FALLBACK_LLM_CALLS = RECOVERY_CONFIG.get("fallback_llm_calls", 0)
FALLBACK_AMBIENT_RATE = RECOVERY_CONFIG.get("fallback_ambient_rate", 0.0)

TELEGRAM_ENABLED = ALERTS_CONFIG.get("telegram_enabled", True)
ALERT_LOG_LEVEL = ALERTS_CONFIG.get("log_level", "warning")

MAX_HISTORY_ENTRIES = OPERATOR_CONFIG.get("max_history_entries", 100)
_STALLED_THRESHOLD_SECONDS = OPERATOR_CONFIG.get("stalled_threshold_seconds", 300)


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _json_default(value: Any) -> str:
    return str(value)


def _zadd_json(key: str, payload: Dict[str, Any], score: Optional[float] = None) -> None:
    r = _get_redis()
    ts = score if score is not None else time.time()
    r.zadd(key, {json.dumps(payload, default=_json_default): ts})
    r.expire(key, _RECENT_LOG_TTL)


def _set_status(payload: Dict[str, Any]) -> None:
    r = _get_redis()
    mapping = {
        key: (json.dumps(value, default=_json_default) if isinstance(value, (dict, list)) else str(value))
        for key, value in payload.items()
        if value is not None
    }
    if mapping:
        r.hset(SIM_OPERATOR_STATUS_KEY, mapping=mapping)
        r.expire(SIM_OPERATOR_STATUS_KEY, _RECENT_LOG_TTL)


def _build_npc_list(game_state: Any, faction_ideology: Optional[Dict[str, str]]) -> List[Dict[str, Any]]:
    npc_list: List[Dict[str, Any]] = []
    for char_id, character in game_state.npc_system.characters.items():
        affiliation = character.affiliation
        npc_list.append(
            {
                "id": char_id,
                "char_id": char_id,
                "name": character.name,
                "archetype": character.personality_type.value,
                "affiliation": affiliation,
                "ideology": faction_ideology.get(affiliation, "diplomatic")
                if faction_ideology and affiliation
                else None,
                "title": character.title,
                "description": getattr(character, "description", ""),
            }
        )
    return npc_list


def _decision_char_id(decision: Dict[str, Any]) -> str:
    return decision.get("char_id") or decision.get("id") or "unknown"


def _action_hash(char_id: str, action_type: str, payload: Dict[str, Any]) -> str:
    raw = f"{char_id}:{action_type}:{json.dumps(payload, sort_keys=True, default=_json_default)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _extract_turns(npc_results: Dict[str, Any], tick_id: str, tick_ts: float) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []

    for entry in npc_results.get("moods", []):
        turns.append(
            {
                "tick_id": tick_id,
                "timestamp": tick_ts,
                "char_id": entry.get("char_id", "unknown"),
                "turn_type": "mood",
                "payload": entry,
            }
        )

    for bucket_name in ("thoughts", "actions", "opinions", "decisions", "interactions"):
        for entry in npc_results.get(bucket_name, []):
            char_id = entry.get("char_id") or entry.get("source_char_id") or "unknown"
            turns.append(
                {
                    "tick_id": tick_id,
                    "timestamp": tick_ts,
                    "char_id": char_id,
                    "turn_type": bucket_name[:-1] if bucket_name.endswith("s") else bucket_name,
                    "payload": entry,
                }
            )

    return turns


def _validate(
    game_state: Any,
    npc_list: List[Dict[str, Any]],
    npc_results: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    fallback_decisions: List[Dict[str, Any]] = []

    if game_state is None:
        failures.append(
            {
                "check": "missing_game_state",
                "severity": "critical",
                "message": "game_state is None",
            }
        )
        return failures, warnings, fallback_decisions

    if not getattr(game_state, "npc_system", None):
        failures.append(
            {
                "check": "missing_npc_system",
                "severity": "critical",
                "message": "game_state.npc_system is missing",
            }
        )
        return failures, warnings, fallback_decisions

    turn_entries = _extract_turns(npc_results, "validation", time.time())
    if not turn_entries:
        failures.append(
            {
                "check": "empty_turns",
                "severity": "high",
                "message": "simulation_tick produced no turn entries",
            }
        )

    seen_hashes = set()
    active_npcs = set()
    for decision in npc_results.get("decisions", []):
        char_id = _decision_char_id(decision)
        active_npcs.add(char_id)
        digest = _action_hash(char_id, "decision", decision)
        if digest in seen_hashes:
            failures.append(
                {
                    "check": "duplicate_actions",
                    "severity": "high",
                    "char_id": char_id,
                    "message": "duplicate NPC decision payload in same tick",
                }
            )
        seen_hashes.add(digest)

        r = _get_redis()
        runaway_key = f"simulation_operator:runaway:{char_id}"
        category = decision.get("category", "unknown")
        r.rpush(runaway_key, category)
        r.ltrim(runaway_key, -6, -1)
        r.expire(runaway_key, _RUNAWAY_HISTORY_TTL)
        recent = r.lrange(runaway_key, 0, -1)
        if len(recent) >= 6 and len(set(recent)) == 1:
            warnings.append(
                {
                    "check": "runaway_loop",
                    "severity": "medium",
                    "char_id": char_id,
                    "message": f"NPC repeated decision category '{category}' for 6 turns",
                }
            )

    action_ids = {
        entry.get("char_id") or entry.get("source_char_id") or "unknown"
        for entry in npc_results.get("actions", [])
    }
    thought_ids = {
        entry.get("char_id") or entry.get("source_char_id") or "unknown"
        for entry in npc_results.get("thoughts", [])
    }
    active_npcs.update(action_ids)
    active_npcs.update(thought_ids)

    for npc in npc_list:
        char_id = npc["char_id"]
        if char_id not in active_npcs:
            fallback_decisions.append(
                {
                    "char_id": char_id,
                    "char_name": npc.get("name", "Unknown"),
                    "category": "rest",
                    "affiliation": npc.get("affiliation", "independent"),
                    "summary": "Safe fallback rest action",
                    "reason": "operator_injected_fallback",
                }
            )

    if fallback_decisions:
        warnings.append(
            {
                "check": "idle_npcs",
                "severity": "low",
                "count": len(fallback_decisions),
                "message": "fallback rest decisions injected for idle NPCs",
            }
        )

    return failures, warnings, fallback_decisions


def _log_turns(turns: List[Dict[str, Any]]) -> None:
    for turn in turns:
        _zadd_json(NPC_TURNS_KEY, turn, score=turn.get("timestamp"))


def _log_memory_events(tick_id: str, auto_result: Dict[str, Any], tick_ts: float) -> None:
    memory_step = auto_result.get("step9_5_memory_harvest", {})
    payload = {
        "tick_id": tick_id,
        "timestamp": tick_ts,
        "harvest": memory_step,
    }
    _zadd_json(NPC_MEMORY_EVENTS_KEY, payload, score=tick_ts)


def _log_tool_event(event_type: str, payload: Dict[str, Any], tick_ts: float) -> None:
    entry = {"event_type": event_type, "timestamp": tick_ts, **payload}
    _zadd_json(NPC_TOOL_EVENTS_KEY, entry, score=tick_ts)


def _progress_status(tick_id: str, phase: str, payload: Dict[str, Any]) -> None:
    now = time.time()
    _set_status(
        {
            "status": "running",
            "last_tick_id": tick_id,
            "last_progress_phase": phase,
            "last_progress_at": now,
            "last_progress_payload": payload,
        }
    )
    _log_tool_event("operator_progress", {"tick_id": tick_id, "phase": phase, "payload": payload}, now)


def _alert_for_review(tick_id: str, reason: str, details: Dict[str, Any], tick_ts: float) -> None:
    _zadd_json(
        SIM_OPERATOR_ALERTS_KEY,
        {
            "tick_id": tick_id,
            "timestamp": tick_ts,
            "reason": reason,
            "details": details,
            "requires_human_review": True,
        },
        score=tick_ts,
    )
    # Send Telegram alert if enabled and apprise is available
    if TELEGRAM_ENABLED and APPRISE_AVAILABLE:
        _send_telegram_alert(reason, details, tick_id, tick_ts)


def _send_telegram_alert(reason: str, details: Dict[str, Any], tick_id: str, tick_ts: float) -> None:
    """Send alert via Apprise (Telegram) using same infrastructure as worker."""
    try:
        import apprise
        notify_urls = os.environ.get("NOTIFICATION_URLS", "")
        if not notify_urls:
            logger.debug("No NOTIFICATION_URLS configured, skipping Telegram alert")
            return
        
        apobj = apprise.Apprise()
        for url in notify_urls.split(","):
            url = url.strip()
            if url:
                apobj.add(url)
        
        title = f"🚨 Simulation Operator Alert: {reason}"
        body = f"Tick: {tick_id}\nTime: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tick_ts))}\nReason: {reason}\nDetails: {json.dumps(details, default=str)[:1000]}"
        
        apobj.notify(title=title, body=body)
        logger.info(f"Telegram alert sent for tick {tick_id}: {reason}")
    except Exception as e:
        logger.warning(f"Failed to send Telegram alert: {e}")


def get_operator_status() -> Dict[str, Any]:
    r = _get_redis()
    raw = r.hgetall(SIM_OPERATOR_STATUS_KEY)
    if not raw:
        return {"status": "idle"}

    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in {"last_start", "last_end"}:
            try:
                result[key] = float(value)
            except (TypeError, ValueError):
                result[key] = value
        elif key in {"last_result", "last_validation", "last_recovery"}:
            try:
                result[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                result[key] = value
        else:
            result[key] = value

    last_start = result.get("last_start")
    auto_raw = r.hgetall("fed:auto_tick_status")
    auto_running = auto_raw.get("running") == "True"
    # Capture transitions BEFORE mutating Redis - reading back after the
    # _set_status call below would always see the newly-written value.
    prev_status = result.get("status")
    if (
        prev_status == "running"
        and last_start
        and not auto_running
        and (time.time() - float(last_start)) > 30
    ):
        result["status"] = "stale"
        stale_msg = "operator_status_cleared_after_restart"
        result["last_error"] = stale_msg
        _set_status(
            {
                "status": "stale",
                "last_tick_id": result.get("last_tick_id"),
                "last_start": last_start,
                "last_end": time.time(),
                "last_error": stale_msg,
            }
        )
        # Alert on running -> stale transition (captured before mutation).
        try:
            tick_id = result.get("last_tick_id") or "unknown"
            _alert_for_review(
                tick_id=tick_id,
                reason="operator_stale_status",
                details={
                    "message": stale_msg,
                    "prev_status": prev_status,
                    "last_start": float(last_start),
                    "now": time.time(),
                    "elapsed_sec": time.time() - float(last_start),
                },
                tick_ts=time.time(),
            )
        except Exception as e:
            logger.warning(f"Failed to emit stale alert: {e}")

    sim_last_tick = r.get("sim_last_tick")
    if sim_last_tick:
        try:
            result["sim_last_tick"] = int(sim_last_tick)
            result["stalled"] = (time.time() - int(sim_last_tick)) > _STALLED_SIM_SECONDS
        except (TypeError, ValueError):
            result["sim_last_tick"] = sim_last_tick
    return result


def run_simulation_operator_tick(
    game_state: Any,
    faction_ideology: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run one supervised simulation tick using the existing pipeline."""
    tick_ts = time.time()
    tick_id = f"operator_{int(tick_ts * 1000)}"

    _set_status(
        {
            "status": "running",
            "last_tick_id": tick_id,
            "last_start": tick_ts,
            "last_error": "",
        }
    )
    _log_tool_event("tick_supervisor_started", {"tick_id": tick_id}, tick_ts)

    npc_list = _build_npc_list(game_state, faction_ideology)
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    recovery_steps: List[Dict[str, Any]] = []
    npc_results: Dict[str, Any] = {}

    try:
        _progress_status(tick_id, "npc_autonomy_start", {"npc_count": len(npc_list)})
        npc_results = simulation_tick(npc_list)
        turns = _extract_turns(npc_results, tick_id, tick_ts)
        _log_turns(turns)

        _progress_status(
            tick_id,
            "npc_autonomy_complete",
            {
                "turn_count": len(turns),
                "decision_count": len(npc_results.get("decisions", [])),
            },
        )

        failures, warnings, fallback_decisions = _validate(game_state, npc_list, npc_results)

        if failures:
            _log_tool_event(
                "validator_failures",
                {"tick_id": tick_id, "failures": failures},
                tick_ts,
            )
        if warnings:
            _log_tool_event(
                "validator_warnings",
                {"tick_id": tick_id, "warnings": warnings},
                tick_ts,
            )

        decisions = list(npc_results.get("decisions", []))
        if fallback_decisions:
            decisions.extend(fallback_decisions)
            recovery = {
                "type": "fallback_rest_decisions",
                "count": len(fallback_decisions),
            }
            recovery_steps.append(recovery)
            _zadd_json(SIM_OPERATOR_RECOVERY_KEY, {"tick_id": tick_id, **recovery}, score=tick_ts)

        try:
            auto_result = autonomous_tick(
                npc_list,
                decisions,
                progress_callback=lambda phase, payload: _progress_status(tick_id, phase, payload),
                cognition_overrides={
                    "max_llm_calls_per_tick": 1,
                    "ambient_trigger_rate": 0.0,
                },
                narration_llm_enabled=False,
            )
        except Exception as exc:
            recovery = {
                "type": "retry_failed_tick",
                "error": str(exc),
            }
            recovery_steps.append(recovery)
            _zadd_json(SIM_OPERATOR_RECOVERY_KEY, {"tick_id": tick_id, **recovery}, score=tick_ts)
            _log_tool_event("tick_retry", {"tick_id": tick_id, "error": str(exc)}, tick_ts)
            auto_result = autonomous_tick(
                npc_list,
                fallback_decisions or decisions,
                progress_callback=lambda phase, payload: _progress_status(tick_id, phase, payload),
                cognition_overrides={
                    "max_llm_calls_per_tick": 0,
                    "ambient_trigger_rate": 0.0,
                },
                narration_llm_enabled=False,
            )

        _log_memory_events(tick_id, auto_result, tick_ts)

        summary = {
            "tick_id": tick_id,
            "tick_ts": tick_ts,
            "npc_count": len(npc_list),
            "turn_count": len(turns),
            "decision_count": len(decisions),
            "failures": failures,
            "warnings": warnings,
            "recovery_steps": recovery_steps,
            "world_state_changes": auto_result.get("step2_decision_effects", {}).get("world_state_changes", {}),
            "faction_updates": auto_result.get("step2_decision_effects", {}).get("faction_updates", {}),
            "errors": auto_result.get("errors", []),
            "duration_ms": auto_result.get("duration_ms", 0),
        }

        _zadd_json(SIM_OPERATOR_HISTORY_KEY, summary, score=tick_ts)

        if failures or len(auto_result.get("errors", [])) >= 3:
            _alert_for_review(
                tick_id,
                "validation_or_runtime_failures",
                {
                    "failures": failures,
                    "warnings": warnings,
                    "errors": auto_result.get("errors", [])[:5],
                },
                tick_ts,
            )

        _set_status(
            {
                "status": "completed",
                "last_tick_id": tick_id,
                "last_end": time.time(),
                "last_result": summary,
                "last_validation": {"failures": failures, "warnings": warnings},
                "last_recovery": recovery_steps,
                "last_error": json.dumps(auto_result.get("errors", [])[:3]),
            }
        )
        return {
            "status": "completed",
            "tick_id": tick_id,
            "npc_results": npc_results,
            "simulation_result": auto_result,
            "validation": {"failures": failures, "warnings": warnings},
            "recovery_steps": recovery_steps,
        }
    except Exception as exc:
        logger.exception("Simulation operator tick failed")
        failure_payload = {
            "status": "failed",
            "tick_id": tick_id,
            "error": str(exc),
        }
        _log_tool_event("tick_failure", failure_payload, tick_ts)
        _alert_for_review(tick_id, "operator_exception", failure_payload, tick_ts)
        _set_status(
            {
                "status": "failed",
                "last_tick_id": tick_id,
                "last_end": time.time(),
                "last_error": str(exc),
            }
        )
        raise
