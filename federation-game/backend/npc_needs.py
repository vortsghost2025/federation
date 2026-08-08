"""
FEDERATION GAME - NPC Needs Queue
Extracted from npc_autonomy.py [2.1]

Councilor capability-request system:
- file_npc_need: NPC files a structured need request
- get_open_needs: Retrieve open needs (optionally filtered by NPC)
- consume_system_notifications: Drain system notifications for an NPC

Redis keys:
  npc:needs              - LIST of structured need records
  npc:needs:{npc_id}:last - STRING timestamp of last need filed (dedup throttle)
  npc:system_notifications:{npc_id} - LIST of system notifications
"""

import os
import json
import time
import hashlib
from datetime import datetime, timezone

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

ALLOWED_NEED_TYPES = frozenset({
    "information_access",
    "memory_access",
    "coordination_help",
    "institution_support",
    "workflow_visibility",
    "decision_feedback",
    "world_state_gap",
    "pivot_strategy",
})

FORBIDDEN_NEED_TYPES = frozenset({
    "shell_access",
    "server_access",
    "delete_access",
    "billing_access",
    "provider_key_access",
    "admin_access",
    "unrestricted_tool_access",
})

NPC_NEEDS_KEY = "npc:needs"
NPC_NEEDS_MAX = 100
NPC_NEEDS_THROTTLE_SECONDS = 600


def file_npc_need(r, npc_id, npc_name, need_type, priority, description,
                  why_needed, suggested_capability, related_institution_id="",
                  context_snapshot=None):
    if need_type in FORBIDDEN_NEED_TYPES:
        return {"ok": False, "error": "forbidden_need_type", "need_type": need_type}
    if need_type not in ALLOWED_NEED_TYPES:
        return {"ok": False, "error": "unknown_need_type", "need_type": need_type}
    now = time.time()
    last_ts = r.get(f"npc:needs:{npc_id}:last")
    if last_ts:
        try:
            if now - float(last_ts) < NPC_NEEDS_THROTTLE_SECONDS:
                return {"ok": False, "error": "throttled", "seconds_remaining": int(NPC_NEEDS_THROTTLE_SECONDS - (now - float(last_ts)))}
        except (ValueError, TypeError):
            pass
    queue_len = r.llen(NPC_NEEDS_KEY)
    if queue_len >= NPC_NEEDS_MAX:
        r.lpop(NPC_NEEDS_KEY)
    need_id = hashlib.md5(f"{npc_id}:{need_type}:{description[:80]}:{now}".encode()).hexdigest()[:12]
    record = {
        "need_id": need_id,
        "npc_id": npc_id,
        "npc_name": npc_name,
        "need_type": need_type,
        "priority": priority,
        "description": description,
        "why_needed": why_needed,
        "suggested_capability": suggested_capability,
        "related_institution_id": related_institution_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
    }
    if context_snapshot:
        record["context_snapshot"] = context_snapshot
    for existing_raw in r.lrange(NPC_NEEDS_KEY, 0, -1):
        try:
            existing = json.loads(existing_raw)
            if (existing.get("npc_id") == npc_id and
                existing.get("need_type") == need_type and
                existing.get("status") == "open"):
                return {"ok": False, "error": "duplicate_open", "existing_need_id": existing.get("need_id")}
        except (json.JSONDecodeError, TypeError):
            continue
    r.rpush(NPC_NEEDS_KEY, json.dumps(record))
    r.set(f"npc:needs:{npc_id}:last", str(now))
    return {"ok": True, "need_id": need_id}


def get_open_needs(r, npc_id=None):
    needs = []
    for raw in r.lrange(NPC_NEEDS_KEY, 0, -1):
        try:
            record = json.loads(raw)
            if record.get("status") == "open":
                if npc_id is None or record.get("npc_id") == npc_id:
                    needs.append(record)
        except (json.JSONDecodeError, TypeError):
            continue
    return needs


def consume_system_notifications(r, npc_id):
    notifications = []
    key = f"npc:system_notifications:{npc_id}"
    for raw in r.lrange(key, 0, -1):
        try:
            notifications.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    r.delete(key)
    return notifications
