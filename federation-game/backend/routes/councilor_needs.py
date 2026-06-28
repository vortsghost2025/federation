"""Councilor needs queue — read and mutation endpoints for NPC capability requests."""

import json
import os
import redis as _redis
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from npc_autonomy import (
    file_npc_need,
    get_open_needs,
    consume_system_notifications,
    ALLOWED_NEED_TYPES,
    FORBIDDEN_NEED_TYPES,
)

router = APIRouter(prefix="", tags=["councilor-needs"])

_redis_pool = None


def _r(request: Request):
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = _redis.ConnectionPool.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            max_connections=4,
        )
    return _redis.Redis(connection_pool=_redis_pool)


@router.get("/councilor/needs")
def get_needs(npc_id: Optional[str] = None):
    r = _r(None)
    needs = get_open_needs(r, npc_id=npc_id)
    return {"needs": needs, "count": len(needs)}


class NeedFiling(BaseModel):
    npc_id: str
    npc_name: str
    need_type: str
    priority: str = Field("medium", pattern="^(high|medium|low)$")
    description: str
    why_needed: str
    suggested_capability: str
    related_institution_id: str = ""
    context_snapshot: dict = Field(default_factory=dict, description="World state + recent decisions at time of filing")


@router.post("/councilor/needs")
def create_need(filing: NeedFiling):
    r = _r(None)
    result = file_npc_need(
        r,
        filing.npc_id,
        filing.npc_name,
        filing.need_type,
        filing.priority,
        filing.description,
        filing.why_needed,
        filing.suggested_capability,
        filing.related_institution_id,
        context_snapshot=filing.context_snapshot,
    )
    if not result.get("ok"):
        return {"filed": False, "error": result.get("error"), "detail": result}
    return {"filed": True, "need_id": result["need_id"]}


@router.get("/councilor/needs/types")
def list_need_types():
    return {
        "allowed": sorted(ALLOWED_NEED_TYPES),
        "forbidden": sorted(FORBIDDEN_NEED_TYPES),
    }


class CloseNeedPayload(BaseModel):
    resolution: str = Field("closed_rejected", pattern="^(closed_fulfilled|closed_rejected|closed_duplicate)")
    resolution_message: str = Field("", description="System notice injected into NPC's next tick")


@router.post("/councilor/needs/{need_id}/close")
def close_need(need_id: str, payload: CloseNeedPayload = CloseNeedPayload()):
    r = _r(None)
    closed = 0
    npc_id = None
    need_type = None
    suggested_capability = None
    for raw in r.lrange("npc:needs", 0, -1):
        try:
            record = json.loads(raw)
            if record.get("need_id") == need_id and record.get("status") == "open":
                record["status"] = payload.resolution
                npc_id = record.get("npc_id", "")
                need_type = record.get("need_type", "")
                suggested_capability = record.get("suggested_capability", "")
                closed += 1
                r.lrem("npc:needs", 1, raw)
                r.rpush("npc:needs", json.dumps(record))
                break
        except (json.JSONDecodeError, TypeError):
            continue
    if closed and npc_id and payload.resolution_message:
        notification = {
            "need_id": need_id,
            "need_type": need_type,
            "resolution": payload.resolution,
            "message": payload.resolution_message,
            "suggested_capability": suggested_capability,
        }
        r.rpush(f"npc:system_notifications:{npc_id}", json.dumps(notification))
    if closed:
        return {"closed": True, "need_id": need_id, "resolution": payload.resolution}
    return {"closed": False, "error": "not_found_or_already_closed"}


@router.get("/councilor/needs/{npc_id}/notifications")
def get_notifications(npc_id: str):
    r = _r(None)
    key = f"npc:system_notifications:{npc_id}"
    count = r.llen(key)
    notifications = []
    for raw in r.lrange(key, 0, -1):
        try:
            notifications.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return {"npc_id": npc_id, "notifications": notifications, "count": count}


@router.delete("/councilor/needs/{npc_id}/notifications")
def clear_notifications(npc_id: str):
    r = _r(None)
    key = f"npc:system_notifications:{npc_id}"
    count = r.llen(key)
    r.delete(key)
    return {"cleared": True, "npc_id": npc_id, "count": count}
