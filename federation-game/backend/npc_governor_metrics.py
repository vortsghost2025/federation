"""Metrics-only NPC governor snapshots.

This module collects read-only signals and writes an optional observer snapshot.
It does not change NPC selection, LLM routing, memory scoring, or tick behavior.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import redis
from sqlalchemy import create_engine, text


REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://federation:federation_pwd@postgres:5432/federation_game",
)

LLM_AUDIT_KEY = "llm_audit"
NPC_TOOL_EVENTS_KEY = "npc_tool_events"
SIM_OPERATOR_HISTORY_KEY = "simulation_operator_history"
GOVERNOR_METRICS_PREFIX = "npc_governor_metrics:"
GOVERNOR_METRICS_LATEST_KEY = "npc_governor_metrics:latest"

SPECIAL_EXTERNAL_NPCS = {"char_001", "char_306"}
BLANK_LLM_CHAR_ID = "__blank__"
SNAPSHOT_TTL_SECONDS = 7 * 86400

REAL_DECISION_SKIP_FIELDS = (
    "skipped_no_char_id",
    "skipped_no_npc_match",
    "skipped_no_description",
    "skipped_below_threshold",
)

DIAGNOSTIC_COUNTER_FIELDS = (
    "harvested",
    "harvested_memory_count",
    "real_decisions_count",
    "fallback_decisions_count",
    "skipped_fallback_rest",
    *REAL_DECISION_SKIP_FIELDS,
)

SOURCE_WINDOW_NOTES = {
    "llm_audit": "Redis llm_audit is capped at 500 retained rows; this is latest retained rows within 24h, not guaranteed exhaustive 24h.",
    "visible_activity": "Postgres npc_action_logs entries with timestamp >= generated_at - 24h.",
    "memory": "Redis npc_memory:* current retained memory state and npc_memory_summary:* existence.",
    "diagnostics": "Redis npc_tool_events operator_progress entries for step9_5_memory_harvest_complete.",
    "operator_history": "Redis simulation_operator_history latest retained completed operator ticks.",
    "blank_llm": "llm_audit rows with blank char_id are reported as __blank__ and excluded from NPC tier annotations.",
    "special_external": "char_001 and char_306 are special/external observe-only NPCs and are never suppression candidates.",
}


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _get_db_engine():
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def _counter_to_dict(counter: Counter) -> Dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _empty_llm_metrics() -> Dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "fail": 0,
        "source_breakdown": Counter(),
        "provider_model_breakdown": Counter(),
        "task_class_breakdown": Counter(),
        "final_total": 0,
        "final_success": 0,
        "final_fail": 0,
    }


def _load_llm_audit(cutoff_ts: float) -> Dict[str, Any]:
    r = _get_redis()
    by_char = defaultdict(_empty_llm_metrics)
    sources = Counter()
    provider_models = Counter()
    task_classes = Counter()
    retained_rows = 0
    final_rows = 0

    for raw, _score in r.zrangebyscore(LLM_AUDIT_KEY, cutoff_ts, "+inf", withscores=True):
        try:
            row = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        retained_rows += 1
        char_id = row.get("char_id") or BLANK_LLM_CHAR_ID
        provider = row.get("provider") or "unknown"
        model = row.get("model") or "unknown"
        source = row.get("source") or "unknown"
        task_class = row.get("task_class") or "unknown"
        provider_model = f"{provider}/{model}"
        success = bool(row.get("success"))
        is_final = bool(row.get("is_final"))

        metrics = by_char[char_id]
        metrics["total"] += 1
        metrics["success" if success else "fail"] += 1
        metrics["source_breakdown"][source] += 1
        metrics["provider_model_breakdown"][provider_model] += 1
        metrics["task_class_breakdown"][task_class] += 1
        sources[source] += 1
        provider_models[provider_model] += 1
        task_classes[task_class] += 1
        if is_final:
            final_rows += 1
            metrics["final_total"] += 1
            metrics["final_success" if success else "final_fail"] += 1

    normalized = {}
    for char_id, metrics in by_char.items():
        normalized[char_id] = {
            "total": metrics["total"],
            "success": metrics["success"],
            "fail": metrics["fail"],
            "source_breakdown": _counter_to_dict(metrics["source_breakdown"]),
            "provider_model_breakdown": _counter_to_dict(metrics["provider_model_breakdown"]),
            "task_class_breakdown": _counter_to_dict(metrics["task_class_breakdown"]),
            "final_total": metrics["final_total"],
            "final_success": metrics["final_success"],
            "final_fail": metrics["final_fail"],
        }

    return {
        "retained_rows_24h": retained_rows,
        "retained_final_rows_24h": final_rows,
        "source_breakdown": _counter_to_dict(sources),
        "provider_model_breakdown": _counter_to_dict(provider_models),
        "task_class_breakdown": _counter_to_dict(task_classes),
        "by_char": normalized,
    }


def _load_visible_activity(cutoff_ts: float) -> Dict[str, Any]:
    engine = _get_db_engine()
    by_char = defaultdict(lambda: {"total": 0, "entry_type_breakdown": Counter()})
    entry_types = Counter()

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT char_id, entry_type, COUNT(*) AS count
                FROM npc_action_logs
                WHERE timestamp >= :cutoff
                GROUP BY char_id, entry_type
                """
            ),
            {"cutoff": int(cutoff_ts)},
        ).mappings()
        for row in rows:
            char_id = row["char_id"]
            count = int(row["count"])
            by_char[char_id]["total"] += count
            by_char[char_id]["entry_type_breakdown"][row["entry_type"]] += count
            entry_types[row["entry_type"]] += count

    normalized = {
        char_id: {
            "total": metrics["total"],
            "entry_type_breakdown": _counter_to_dict(metrics["entry_type_breakdown"]),
        }
        for char_id, metrics in by_char.items()
    }
    return {
        "total_24h": sum(item["total"] for item in normalized.values()),
        "npc_count": sum(1 for item in normalized.values() if item["total"] > 0),
        "entry_type_breakdown": _counter_to_dict(entry_types),
        "by_char": normalized,
    }


def _load_memory_state() -> Dict[str, Any]:
    r = _get_redis()
    by_char: Dict[str, Dict[str, Any]] = {}
    category_counts = Counter()
    score_distribution = Counter()

    for key in r.scan_iter("npc_memory:*", count=500):
        char_id = key.split(":", 1)[1]
        categories = Counter()
        scores = Counter()
        for raw, _score in r.zrange(key, 0, -1, withscores=True):
            try:
                event = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            category = event.get("category") or event.get("type") or "unknown"
            memory_score = str(event.get("memory_score", "unknown"))
            categories[category] += 1
            scores[memory_score] += 1
            category_counts[category] += 1
            score_distribution[memory_score] += 1

        by_char[char_id] = {
            "memory_event_count": int(r.zcard(key)),
            "summary_exists": bool(r.exists(f"npc_memory_summary:{char_id}")),
            "category_counts": _counter_to_dict(categories),
            "score_distribution": _counter_to_dict(scores),
        }

    return {
        "total_events": sum(item["memory_event_count"] for item in by_char.values()),
        "npc_count": sum(1 for item in by_char.values() if item["memory_event_count"] > 0),
        "summaries": sum(1 for item in by_char.values() if item["summary_exists"]),
        "category_counts": _counter_to_dict(category_counts),
        "score_distribution": _counter_to_dict(score_distribution),
        "by_char": by_char,
    }


def _load_latest_harvest_diagnostics(limit: int = 10) -> Dict[str, Any]:
    r = _get_redis()
    latest_event: Optional[Dict[str, Any]] = None
    counter_ticks: List[Dict[str, Any]] = []

    for raw, score in r.zrevrange(NPC_TOOL_EVENTS_KEY, 0, 5000, withscores=True):
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if event.get("event_type") != "operator_progress":
            continue
        if event.get("phase") != "step9_5_memory_harvest_complete":
            continue

        payload = event.get("payload") or {}
        normalized = {
            "tick_id": event.get("tick_id"),
            "timestamp": score,
            "phase": event.get("phase"),
            "payload": payload,
        }
        if latest_event is None:
            latest_event = normalized
        if all(field in payload for field in DIAGNOSTIC_COUNTER_FIELDS):
            counter_ticks.append({"tick_id": event.get("tick_id"), "timestamp": score, **payload})
            if len(counter_ticks) >= limit:
                break

    real_total = sum(int(t.get("real_decisions_count", 0) or 0) for t in counter_ticks)
    harvested_total = sum(int(t.get("harvested", 0) or 0) for t in counter_ticks)
    fallback_total = sum(int(t.get("fallback_decisions_count", 0) or 0) for t in counter_ticks)
    tick_count = len(counter_ticks)
    skip_totals = {
        field: sum(int(t.get(field, 0) or 0) for t in counter_ticks)
        for field in (*REAL_DECISION_SKIP_FIELDS, "skipped_fallback_rest")
    }

    return {
        "latest_event": latest_event,
        "counter_bearing_ticks": counter_ticks,
        "health": {
            "counter_bearing_ticks": tick_count,
            "avg_real_decisions_count": round(real_total / tick_count, 2) if tick_count else 0,
            "avg_fallback_decisions_count": round(fallback_total / tick_count, 2) if tick_count else 0,
            "real_decisions_total": real_total,
            "harvested_total": harvested_total,
            "fallback_decisions_total": fallback_total,
            "harvest_yield": round(harvested_total / real_total, 4) if real_total else None,
            "skipped_no_char_id_total": skip_totals["skipped_no_char_id"],
            "skipped_no_npc_match_total": skip_totals["skipped_no_npc_match"],
            "skipped_no_description_total": skip_totals["skipped_no_description"],
            "skipped_below_threshold_total": skip_totals["skipped_below_threshold"],
            "skipped_fallback_rest_total": skip_totals["skipped_fallback_rest"],
        },
    }


def _load_operator_history(limit: int = 10) -> Dict[str, Any]:
    r = _get_redis()
    latest: List[Dict[str, Any]] = []
    by_tick: Dict[str, Dict[str, Any]] = {}
    warning_types = Counter()
    failure_count = 0
    error_count = 0

    for raw, score in r.zrevrange(SIM_OPERATOR_HISTORY_KEY, 0, max(limit * 3, 30), withscores=True):
        try:
            result = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        tick_id = result.get("tick_id")
        if not tick_id:
            continue
        warnings = result.get("warnings") or []
        failures = result.get("failures") or []
        errors = result.get("errors") or []
        item = {
            "tick_id": tick_id,
            "timestamp": score,
            "decision_count": result.get("decision_count"),
            "warnings": warnings,
            "failures": failures,
            "errors": errors,
        }
        by_tick[tick_id] = item
        if len(latest) < limit:
            latest.append(item)
            failure_count += len(failures)
            error_count += len(errors)
            for warning in warnings:
                warning_types[warning.get("check", "unknown")] += 1

    return {
        "latest": latest,
        "by_tick": by_tick,
        "summary": {
            "warning_types": _counter_to_dict(warning_types),
            "failure_count": failure_count,
            "error_count": error_count,
        },
    }


def _build_char_metrics(
    llm_audit: Dict[str, Any],
    visible_activity: Dict[str, Any],
    memory_state: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    llm_by_char = llm_audit.get("by_char", {})
    visible_by_char = visible_activity.get("by_char", {})
    memory_by_char = memory_state.get("by_char", {})
    char_ids = set(visible_by_char) | set(memory_by_char) | set(llm_by_char) | SPECIAL_EXTERNAL_NPCS
    char_ids.discard(BLANK_LLM_CHAR_ID)

    metrics: Dict[str, Dict[str, Any]] = {}
    for char_id in sorted(char_ids):
        llm = llm_by_char.get(char_id, {})
        visible = visible_by_char.get(char_id, {})
        memory = memory_by_char.get(char_id, {})
        metrics[char_id] = {
            "char_id": char_id,
            "visible_24h": int(visible.get("total", 0) or 0),
            "entry_type_breakdown": visible.get("entry_type_breakdown", {}),
            "llm_total_24h": int(llm.get("total", 0) or 0),
            "llm_success_24h": int(llm.get("success", 0) or 0),
            "llm_fail_24h": int(llm.get("fail", 0) or 0),
            "llm_source_breakdown": llm.get("source_breakdown", {}),
            "llm_provider_model_breakdown": llm.get("provider_model_breakdown", {}),
            "memory_event_count": int(memory.get("memory_event_count", 0) or 0),
            "summary_exists": bool(memory.get("summary_exists", False)),
            "memory_category_counts": memory.get("category_counts", {}),
            "memory_score_distribution": memory.get("score_distribution", {}),
            "special_external": char_id in SPECIAL_EXTERNAL_NPCS,
        }
    return metrics


def _annotation(char_metrics: Dict[str, Any], tier: str, reasons: List[str]) -> Dict[str, Any]:
    return {
        "char_id": char_metrics["char_id"],
        "tier": tier,
        "visible_24h": char_metrics["visible_24h"],
        "llm_total_24h": char_metrics["llm_total_24h"],
        "llm_fail_24h": char_metrics["llm_fail_24h"],
        "memory_event_count": char_metrics["memory_event_count"],
        "summary_exists": char_metrics["summary_exists"],
        "reasons": reasons,
        "observe_only": True,
    }


def _classify_governor_annotations(char_metrics: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    high_tier: List[Dict[str, Any]] = []
    medium_tier: List[Dict[str, Any]] = []
    low_tier: List[Dict[str, Any]] = []
    special_external: List[Dict[str, Any]] = []
    active_deterministic: List[Dict[str, Any]] = []
    expensive_low_payoff: List[Dict[str, Any]] = []
    memory_rich: List[Dict[str, Any]] = []

    for metrics in char_metrics.values():
        visible = metrics["visible_24h"]
        llm_total = metrics["llm_total_24h"]
        llm_success = metrics["llm_success_24h"]
        llm_fail = metrics["llm_fail_24h"]
        memory_count = metrics["memory_event_count"]
        summary_exists = metrics["summary_exists"]

        if metrics["special_external"]:
            special_external.append(
                _annotation(metrics, "special_external", ["external_agent", "never_suppress"])
            )
            continue

        if visible >= 100 and llm_total <= 2 and memory_count <= 1:
            active_deterministic.append(
                _annotation(metrics, "active_deterministic", ["high_visible", "low_llm", "low_memory"])
            )
        if llm_total >= 15 and visible < 20 and memory_count <= 1:
            expensive_low_payoff.append(
                _annotation(metrics, "expensive_low_payoff", ["high_llm", "low_visible", "low_memory"])
            )
        if memory_count >= 8 and summary_exists:
            memory_rich.append(
                _annotation(metrics, "memory_rich", ["high_memory", "summary_exists"])
            )

        if visible >= 100 and (memory_count >= 3 or llm_total > 0):
            reasons = ["high_visible"]
            if memory_count >= 3:
                reasons.append("has_memory")
            if llm_success > 0:
                reasons.append("useful_llm")
            high_tier.append(_annotation(metrics, "high", reasons))
        elif visible >= 50 or memory_count >= 3:
            reasons = []
            if visible >= 50:
                reasons.append("visible_activity")
            if memory_count >= 3:
                reasons.append("has_memory")
            medium_tier.append(_annotation(metrics, "medium", reasons))
        elif visible < 20 and memory_count <= 1 and llm_fail >= 15:
            low_tier.append(
                _annotation(metrics, "low", ["low_visible", "low_memory", "high_failed_llm"])
            )

    def sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                item["visible_24h"],
                item["memory_event_count"],
                item["llm_total_24h"],
            ),
            reverse=True,
        )

    return {
        "high_tier": sort_items(high_tier),
        "medium_tier": sort_items(medium_tier),
        "low_tier": sort_items(low_tier),
        "special_external": sort_items(special_external),
        "active_deterministic": sort_items(active_deterministic),
        "expensive_low_payoff": sort_items(expensive_low_payoff),
        "memory_rich": sort_items(memory_rich),
    }


def _validate_diagnostics(
    harvest_diagnostics: Dict[str, Any],
    operator_history: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    invalid_reasons: List[str] = []
    latest_event = harvest_diagnostics.get("latest_event")
    if not latest_event:
        invalid_reasons.append("latest_memory_harvest_payload_missing")
        return False, invalid_reasons

    payload = latest_event.get("payload") or {}
    if not payload:
        invalid_reasons.append("latest_memory_harvest_payload_missing")
    missing_fields = [field for field in DIAGNOSTIC_COUNTER_FIELDS if field not in payload]
    if missing_fields:
        invalid_reasons.append("diagnostic_counters_missing:" + ",".join(missing_fields))

    health = harvest_diagnostics.get("health", {})
    skip_totals = {
        "skipped_no_char_id_total": health.get("skipped_no_char_id_total", 0),
        "skipped_no_npc_match_total": health.get("skipped_no_npc_match_total", 0),
        "skipped_no_description_total": health.get("skipped_no_description_total", 0),
        "skipped_below_threshold_total": health.get("skipped_below_threshold_total", 0),
    }
    for field, value in skip_totals.items():
        if int(value or 0) > 0:
            invalid_reasons.append(f"real_decision_skip_counter_nonzero:{field}")

    tick_id = latest_event.get("tick_id")
    matched_history = operator_history.get("by_tick", {}).get(tick_id)
    if not matched_history:
        invalid_reasons.append("latest_harvest_tick_missing_operator_history")
    else:
        if matched_history.get("failures"):
            invalid_reasons.append("matched_operator_history_failures_nonempty")
        if matched_history.get("errors"):
            invalid_reasons.append("matched_operator_history_errors_nonempty")

    return not invalid_reasons, invalid_reasons


def build_governor_metrics_snapshot(
    tick_id: Optional[str] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    generated_at = time.time()
    cutoff_ts = generated_at - 86400
    llm_audit = _load_llm_audit(cutoff_ts)
    visible_activity = _load_visible_activity(cutoff_ts)
    memory_state = _load_memory_state()
    harvest_diagnostics = _load_latest_harvest_diagnostics(limit=10)
    operator_history = _load_operator_history(limit=10)
    char_metrics = _build_char_metrics(llm_audit, visible_activity, memory_state)
    annotations = _classify_governor_annotations(char_metrics)
    diagnostic_valid, invalid_reasons = _validate_diagnostics(harvest_diagnostics, operator_history)

    latest_event = harvest_diagnostics.get("latest_event") or {}
    snapshot_tick_id = tick_id or latest_event.get("tick_id") or f"governor_{int(generated_at * 1000)}"
    snapshot = {
        "tick_id": snapshot_tick_id,
        "generated_at": generated_at,
        "diagnostic_valid": diagnostic_valid,
        "invalid_reasons": invalid_reasons,
        "high_tier": annotations["high_tier"],
        "medium_tier": annotations["medium_tier"],
        "low_tier": annotations["low_tier"],
        "special_external": annotations["special_external"],
        "active_deterministic": annotations["active_deterministic"],
        "expensive_low_payoff": annotations["expensive_low_payoff"],
        "memory_rich": annotations["memory_rich"],
        "source_window_notes": SOURCE_WINDOW_NOTES,
        "source_counts": {
            "llm_audit_retained_rows_24h": llm_audit["retained_rows_24h"],
            "llm_audit_retained_final_rows_24h": llm_audit["retained_final_rows_24h"],
            "visible_activity_total_24h": visible_activity["total_24h"],
            "visible_activity_npc_count": visible_activity["npc_count"],
            "memory_total_events": memory_state["total_events"],
            "memory_npc_count": memory_state["npc_count"],
            "memory_summaries": memory_state["summaries"],
            "blank_llm_rows": llm_audit.get("by_char", {}).get(BLANK_LLM_CHAR_ID, {}).get("total", 0),
        },
        "breakdowns": {
            "llm_source_breakdown": llm_audit["source_breakdown"],
            "llm_provider_model_breakdown": llm_audit["provider_model_breakdown"],
            "llm_task_class_breakdown": llm_audit["task_class_breakdown"],
            "visible_entry_type_breakdown": visible_activity["entry_type_breakdown"],
            "memory_category_counts": memory_state["category_counts"],
            "memory_score_distribution": memory_state["score_distribution"],
        },
        "diagnostic_health": harvest_diagnostics["health"],
        "operator_history_summary": operator_history["summary"],
        "char_metrics": char_metrics,
    }

    if persist:
        r = _get_redis()
        key = f"{GOVERNOR_METRICS_PREFIX}{snapshot_tick_id}"
        r.set(key, json.dumps(snapshot), ex=SNAPSHOT_TTL_SECONDS)
        r.set(
            GOVERNOR_METRICS_LATEST_KEY,
            json.dumps({"tick_id": snapshot_tick_id, "key": key, "generated_at": generated_at}),
            ex=SNAPSHOT_TTL_SECONDS,
        )

    return snapshot


def get_latest_governor_metrics() -> Optional[Dict[str, Any]]:
    r = _get_redis()
    pointer_raw = r.get(GOVERNOR_METRICS_LATEST_KEY)
    if not pointer_raw:
        return None
    try:
        pointer = json.loads(pointer_raw)
    except (TypeError, json.JSONDecodeError):
        return None
    key = pointer.get("key")
    if not key:
        return None
    snapshot_raw = r.get(key)
    if not snapshot_raw:
        return None
    try:
        return json.loads(snapshot_raw)
    except (TypeError, json.JSONDecodeError):
        return None
