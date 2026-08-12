"""Councilor needs queue — read and mutation endpoints for NPC capability requests."""

import json
import os
import redis as _redis
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from operator_auth import require_operator
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


@router.get("/councilor/areas")
def get_councilor_areas(request: Request, _: None = Depends(require_operator)):
    """Return areas founded by the persistent councilor pair (world expansion)."""
    try:
        from federation_work_loop.core import get_areas
    except Exception:
        return {"ok": False, "error": "work_loop_unavailable", "areas": []}
    pair_slug = "char_001__char_306"
    areas = get_areas(pair_slug)
    return {"ok": True, "pair_slug": pair_slug, "count": len(areas), "areas": areas}


@router.get("/councilor/needs")
def get_needs(npc_id: Optional[str] = None, _: None = Depends(require_operator)):
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
def create_need(filing: NeedFiling, request: Request, _: None = Depends(require_operator)):
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
def close_need(need_id: str, payload: CloseNeedPayload = CloseNeedPayload(), _: None = Depends(require_operator)):
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
def get_notifications(npc_id: str, _: None = Depends(require_operator)):
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
def clear_notifications(npc_id: str, _: None = Depends(require_operator)):
    r = _r(None)
    key = f"npc:system_notifications:{npc_id}"
    count = r.llen(key)
    r.delete(key)
    return {"cleared": True, "npc_id": npc_id, "count": count}


# ── Capability Requests (Work Loop MVP) ─────────────────────────────

try:
    from federation_work_loop.core import (
        set_messaging_adapter,
        get_all_capability_requests,
        get_capability_request,
        update_capability_request_status,
        create_capability_request as create_work_loop_capability_request,
        record_acceptance_test as record_acceptance_test_domain,
    )
    WORK_LOOP_AVAILABLE = True
except ImportError:
    WORK_LOOP_AVAILABLE = False

if WORK_LOOP_AVAILABLE:
    try:
        import npc_messaging
        set_messaging_adapter(npc_messaging)
    except Exception:
        pass


@router.get("/councilor/capability-requests")
def get_capability_requests(_: None = Depends(require_operator)):
    """Get all capability requests for moderator visibility."""
    if not WORK_LOOP_AVAILABLE:
        return {"requests": [], "count": 0, "error": "work_loop_not_available"}
    
    requests = get_all_capability_requests()
    return {"requests": requests, "count": len(requests)}


@router.get("/councilor/capability-requests/{request_id}")
def get_capability_request_by_id(request_id: str, _: None = Depends(require_operator)):
    """Get a specific capability request by ID."""
    if not WORK_LOOP_AVAILABLE:
        raise HTTPException(status_code=503, detail="work_loop_not_available")
    
    request = get_capability_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="request_not_found")
    return request


class CapabilityRequestStatusUpdate(BaseModel):
    status: str
    actor_id: str = ""
    reason: str = ""
    delivery_reference: str = ""
    acceptance_test_result: str = ""
    acceptance_test_evidence: str = ""


@router.post("/councilor/capability-requests/{request_id}/status")
def update_capability_request(
    request_id: str,
    payload: CapabilityRequestStatusUpdate,
    _: None = Depends(require_operator),
):
    """Update capability request status with lifecycle enforcement.

    Temporarily operator-mediated: only trusted network clients
    (Tailscale/loopback) may call this mutation endpoint. This is not the
    final NPC/councilor identity design.
    """
    if not WORK_LOOP_AVAILABLE:
        raise HTTPException(status_code=503, detail="work_loop_not_available")
    
    success = update_capability_request_status(
        request_id=request_id,
        status=payload.status,
        actor_id=payload.actor_id,
        reason=payload.reason,
        delivery_reference=payload.delivery_reference,
        acceptance_test_result=payload.acceptance_test_result,
        acceptance_test_evidence=payload.acceptance_test_evidence,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="invalid_transition_or_unauthorized")
    
    return {"updated": True, "request_id": request_id, "status": payload.status}


class AcceptanceRecord(BaseModel):
    councilor_id: str
    result: str
    evidence: str
    expected_lifecycle_version: str = ""


@router.post("/councilor/capability-requests/{request_id}/acceptance")
def record_acceptance(
    request_id: str,
    payload: AcceptanceRecord,
    _: None = Depends(require_operator),
):
    """Record an acceptance test result for a capability request.

    Only char_001 and char_306 may record. Each councilor gets a separate
    persisted acceptance record. Repeated identical recording is idempotent.
    Conflicting result replacement is rejected with 409.
    When both councilors pass while status is delivered, the domain layer
    atomically transitions to verification_pending.

    Temporarily operator-mediated: only trusted network clients
    (Tailscale/loopback) may call this mutation endpoint. This is not the
    final NPC/councilor identity design.
    """
    if not WORK_LOOP_AVAILABLE:
        raise HTTPException(status_code=503, detail="work_loop_not_available")

    result = record_acceptance_test_domain(
        request_id=request_id,
        councilor_id=payload.councilor_id,
        result=payload.result,
        evidence=payload.evidence,
        expected_version=payload.expected_lifecycle_version,
    )

    if not result.get("ok"):
        error = result.get("error", "acceptance_failed")
        if error == "request_not_found":
            raise HTTPException(status_code=404, detail=error)
        if error == "invalid_status_for_acceptance":
            raise HTTPException(status_code=409, detail=error)
        if error == "version_mismatch":
            raise HTTPException(status_code=409, detail=error)
        if error == "only_councilors_may_record":
            raise HTTPException(status_code=403, detail=error)
        if error == "councilor_not_in_pair":
            raise HTTPException(status_code=403, detail=error)
        if error == "invalid_result":
            raise HTTPException(status_code=400, detail=error)
        if error == "conflicting_acceptance":
            raise HTTPException(status_code=409, detail=error)
        if error == "lua_failed":
            raise HTTPException(status_code=500, detail=error)
        if error == "missing_pair_slug":
            raise HTTPException(status_code=500, detail=error)
        if error == "missing_pair_fields":
            raise HTTPException(status_code=500, detail=error)
        raise HTTPException(status_code=500, detail=error)

    return {
        "accepted": True,
        "request_id": request_id,
        "councilor_id": payload.councilor_id,
        "result": payload.result,
        "passed_count": result.get("passed_count", 0),
        "idempotent": result.get("idempotent", False),
        "transitioned": result.get("transitioned", False),
    }
