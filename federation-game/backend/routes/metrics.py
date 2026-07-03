"""Prometheus metrics endpoint for Federation simulation.

Exposes gauges for:
- NPC needs queue (open needs by npc_name, need_type, priority)
- World state (stability, morale, resource_abundance, tension, threat, anomaly_activity)
- Institution health (workflow counts, role counts)
- NPC notification backlog (pending system_notifications per NPC)

All prometheus_client imports are lazy — if the package is missing,
metrics_response() returns None instead of crashing.
"""

import json
import os
import logging

import redis as _redis

logger = logging.getLogger(__name__)

_registry = None
_needs_gauge = None
_world_gauge = None
_institution_workflow_gauge = None
_institution_role_gauge = None
_notification_backlog_gauge = None
_needs_total_gauge = None
_needs_open_gauge = None
_initialized = False

_redis_pool = None


def _r():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = _redis.ConnectionPool.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            max_connections=2,
        )
    return _redis.Redis(connection_pool=_redis_pool)


def _ensure_registry():
    global _registry, _needs_gauge, _world_gauge, _institution_workflow_gauge
    global _institution_role_gauge, _notification_backlog_gauge
    global _needs_total_gauge, _needs_open_gauge, _initialized
    if _initialized:
        return True
    try:
        from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST
        _registry = CollectorRegistry()
        _needs_gauge = Gauge(
            "federation_npc_open_needs",
            "Count of open NPC needs in the councilor queue",
            ["npc_name", "need_type", "priority"],
            registry=_registry,
        )
        _world_gauge = Gauge(
            "federation_world_state",
            "Current world state metric value",
            ["metric"],
            registry=_registry,
        )
        _institution_workflow_gauge = Gauge(
            "federation_institution_workflows",
            "Number of workflows in an institution",
            ["institution_id", "status"],
            registry=_registry,
        )
        _institution_role_gauge = Gauge(
            "federation_institution_roles",
            "Number of assigned roles in an institution",
            ["institution_id"],
            registry=_registry,
        )
        _notification_backlog_gauge = Gauge(
            "federation_npc_notification_backlog",
            "Number of pending system notifications for an NPC",
            ["npc_id"],
            registry=_registry,
        )
        _needs_total_gauge = Gauge(
            "federation_npc_needs_total",
            "Total needs in queue (all statuses)",
            registry=_registry,
        )
        _needs_open_gauge = Gauge(
            "federation_npc_needs_open",
            "Total open needs in queue",
            registry=_registry,
        )
        _initialized = True
        return True
    except ImportError:
        logger.warning("prometheus_client not available — metrics disabled")
        return False
    except Exception as exc:
        logger.warning("Metrics registry init failed: %s", exc)
        return False


def _collect_needs(r):
    if not _needs_gauge or not _needs_total_gauge or not _needs_open_gauge:
        return
    _needs_gauge.clear()
    _needs_total_gauge.set(0)
    _needs_open_gauge.set(0)
    raw_list = r.lrange("npc:needs", 0, -1)
    open_counts = {}
    total = len(raw_list)
    open_total = 0
    for raw in raw_list:
        try:
            rec = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if rec.get("status") == "open":
            open_total += 1
            key = (rec.get("npc_name", "unknown"), rec.get("need_type", "unknown"), rec.get("priority", "unknown"))
            open_counts[key] = open_counts.get(key, 0) + 1
    _needs_total_gauge.set(total)
    _needs_open_gauge.set(open_total)
    for (npc_name, need_type, priority), count in open_counts.items():
        _needs_gauge.labels(npc_name=npc_name, need_type=need_type, priority=priority).set(count)


def _collect_world_state(r):
    if not _world_gauge:
        return
    _world_gauge.clear()
    ws = r.hgetall("world_state")
    int_fields = ("stability", "morale", "resource_abundance", "tension", "threat", "anomaly_activity")
    for field in int_fields:
        val = ws.get(field)
        if val is not None:
            try:
                _world_gauge.labels(metric=field).set(int(val))
            except (ValueError, TypeError):
                pass


def _collect_institutions(r):
    if not _institution_workflow_gauge or not _institution_role_gauge:
        return
    _institution_workflow_gauge.clear()
    _institution_role_gauge.clear()
    inst_ids = list(r.smembers("institution:index"))
    for inst_key in inst_ids:
        try:
            raw = r.hgetall(inst_key)
            short_id = inst_key.split(":", 1)[1] if ":" in inst_key else inst_key
            role_count = r.scard(f"{inst_key}:roles")
            _institution_role_gauge.labels(institution_id=short_id).set(role_count)
            for counter_key in ("active_workflows", "completed_workflows"):
                count = int(raw.get(counter_key, 0))
                _institution_workflow_gauge.labels(institution_id=short_id, status=counter_key).set(count)
        except Exception:
            continue


def _collect_notifications(r):
    if not _notification_backlog_gauge:
        return
    _notification_backlog_gauge.clear()
    npc_ids = []
    for key in r.scan_iter("npc:system_notifications:*"):
        npc_id = key.split(":")[-1]
        if npc_id:
            npc_ids.append(npc_id)
    for npc_id in npc_ids:
        count = r.llen(f"npc:system_notifications:{npc_id}")
        if count > 0:
            _notification_backlog_gauge.labels(npc_id=npc_id).set(count)


def collect_all():
    try:
        r = _r()
        _collect_needs(r)
        _collect_world_state(r)
        _collect_institutions(r)
        _collect_notifications(r)
    except Exception as exc:
        logger.warning("Metrics collection failed: %s", exc)


def metrics_response():
    if not _ensure_registry():
        return None
    collect_all()
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return generate_latest(_registry)
