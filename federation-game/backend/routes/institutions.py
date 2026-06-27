"""Institution route handlers — read and mutation endpoints for institution/workflow state."""

import json
import os
import redis as _redis
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from institutions import (
    VALID_WORKFLOW_TYPES,
    TERMINAL_STATES,
    WORKFLOW_TRANSITIONS,
    seed_institutions,
    ensure_workflow,
    override_workflow_status,
    set_institution_status,
    _rebuild_inst_counters,
)

router = APIRouter(prefix="", tags=["institutions"])

_redis_pool = None


def _get_redis(request: Optional[Request] = None):
    global _redis_pool
    try:
        if request is not None and getattr(request.app.state, "redis", None) is not None:
            return request.app.state.redis
    except Exception:
        pass
    if _redis_pool is None:
        _redis_pool = _redis.ConnectionPool.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            max_connections=10,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis.Redis(connection_pool=_redis_pool)


def _workflow_summary(wf_id, rec):
    return {
        "id": wf_id,
        "kind": rec.get("type", "proposal_review"),
        "title": rec.get("title", "")[:80],
        "status": rec.get("status", ""),
        "source_councilor_id": rec.get("source_councilor_id", ""),
        "artifact_kind": rec.get("artifact_kind", ""),
        "created_at": rec.get("created_at", ""),
        "updated_at": rec.get("updated_at", ""),
    }


@router.get("/institutions/health")
async def health_check(request: Request):
    r = _get_redis(request)
    try:
        ping = r.ping()
        inst_count = len(r.smembers("institution:index"))
        role_count = len(r.smembers("role:index"))
        active_wf = len(r.smembers("workflow:active"))
        completed_wf = len(r.smembers("workflow:completed"))
        return {
            "status": "ok" if ping else "degraded",
            "redis": ping,
            "institutions": inst_count,
            "roles": role_count,
            "active_workflows": active_wf,
            "completed_workflows": completed_wf,
        }
    except Exception as exc:
        return {"status": "error", "redis": False, "detail": str(exc)}


@router.get("/institutions")
async def list_institutions(request: Request):
    r = _get_redis(request)
    result = []
    for inst_id in sorted(r.smembers("institution:index")):
        rec = r.hgetall(inst_id)
        if not rec:
            continue
        role_ids = sorted(r.smembers(f"{inst_id}:roles"))
        member_ids = sorted(r.smembers(f"{inst_id}:members"))
        roles = []
        for rid in role_ids:
            rd = r.hgetall(rid)
            if rd:
                roles.append({
                    "role_id": rid,
                    "title": rd.get("title", ""),
                    "holder": rd.get("holder_char_id", ""),
                    "authority": rd.get("authority", ""),
                })
        active_count = int(r.get(f"{inst_id}:active_workflows") or 0)
        completed_count = int(r.get(f"{inst_id}:completed_workflows") or 0)
        result.append({
            "id": inst_id,
            "name": rec.get("name", ""),
            "kind": rec.get("kind", ""),
            "mandate": rec.get("mandate", ""),
            "status": rec.get("status", ""),
            "created_at": rec.get("created_at", ""),
            "members": member_ids,
            "roles": roles,
            "active_workflows": active_count,
            "completed_workflows": completed_count,
        })
    return {"institutions": result}


@router.get("/institutions/workflows/active")
async def list_active_workflows(request: Request):
    r = _get_redis(request)
    workflows = []
    for wf_id in sorted(r.smembers("workflow:active")):
        rec = r.hgetall(wf_id)
        if rec:
            workflows.append(_workflow_summary(wf_id, rec))
    return {"active": workflows, "count": len(workflows)}


@router.get("/institutions/workflows/completed")
async def list_completed_workflows(request: Request, offset: int = 0, limit: int = 20):
    r = _get_redis(request)
    all_ids = sorted(r.smembers("workflow:completed"))
    page = all_ids[offset : offset + limit]
    workflows = []
    for wf_id in page:
        rec = r.hgetall(wf_id)
        if rec:
            workflows.append(_workflow_summary(wf_id, rec))
    return {
        "completed": workflows,
        "count": len(workflows),
        "total": len(all_ids),
        "offset": offset,
        "limit": limit,
    }


@router.get("/institutions/workflows/{workflow_id:path}")
async def get_workflow_detail(request: Request, workflow_id: str):
    r = _get_redis(request)
    rec = r.hgetall(workflow_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Workflow not found")
    events_raw = r.lrange(f"{workflow_id}:events", 0, -1)
    events = [json.loads(e) for e in events_raw]
    return {
        "id": workflow_id,
        "type": rec.get("type", ""),
        "institution_id": rec.get("institution_id", ""),
        "role_id": rec.get("role_id", ""),
        "source_councilor_id": rec.get("source_councilor_id", ""),
        "artifact_kind": rec.get("artifact_kind", ""),
        "title": rec.get("title", ""),
        "status": rec.get("status", ""),
        "created_at": rec.get("created_at", ""),
        "updated_at": rec.get("updated_at", ""),
        "events": events,
    }


@router.get("/institutions/{institution_id:path}/workflows")
async def institution_workflows(request: Request, institution_id: str, offset: int = 0, limit: int = 20):
    r = _get_redis(request)
    active_ids = r.smembers("workflow:active")
    completed_ids = r.smembers("workflow:completed")
    all_ids = active_ids | completed_ids
    active = []
    completed = []
    for wf_id in sorted(all_ids):
        rec = r.hgetall(wf_id)
        if rec and rec.get("institution_id") == institution_id:
            summary = _workflow_summary(wf_id, rec)
            if wf_id in active_ids:
                active.append(summary)
            else:
                completed.append(summary)
    return {
        "institution_id": institution_id,
        "active": active,
        "completed": completed[offset : offset + limit],
        "active_count": len(active),
        "completed_count": len(completed),
    }


class TriggerWorkflowRequest(BaseModel):
    councilor_id: str
    artifact_id: str
    title: str = ""
    artifact_kind: str = Field(default="proposal", pattern="^(proposal|analysis)$")
    body: str = ""


@router.post("/institutions/workflows/trigger")
async def trigger_workflow(request: Request, body: TriggerWorkflowRequest):
    from institutions import get_councilor_role_context

    r = _get_redis(request)
    seed_institutions(r)
    role_ctx = get_councilor_role_context(r, body.councilor_id)
    if not role_ctx:
        return {"outcome": "FAILED", "detail": "Councilor has no institutional role binding"}
    wf_type = "proposal_review" if body.artifact_kind == "proposal" else "analysis_review"
    artifact = {
        "artifact_id": body.artifact_id,
        "title": body.title or f"Untitled {body.artifact_kind}",
        "body": body.body,
    }
    try:
        wf_id = ensure_workflow(r, body.councilor_id, artifact, role_ctx, wf_type)
    except ValueError as exc:
        return {"outcome": "FAILED", "detail": str(exc)}
    return {"outcome": "CREATED", "workflow_id": wf_id}


class OverrideStatusRequest(BaseModel):
    new_status: str


@router.patch("/institutions/workflows/{workflow_id:path}/status")
async def override_workflow(request: Request, workflow_id: str, body: OverrideStatusRequest):
    r = _get_redis(request)
    rec = r.hgetall(workflow_id)
    if not rec:
        return {"outcome": "FAILED", "detail": "Workflow not found"}
    result = override_workflow_status(r, workflow_id, body.new_status)
    if result:
        return {"outcome": "OVERRIDDEN", "workflow_id": workflow_id, "new_status": body.new_status}
    return {"outcome": "FAILED", "detail": "Override failed"}


class InstitutionStatusRequest(BaseModel):
    new_status: str


@router.patch("/institutions/{institution_id:path}/status")
async def change_institution_status(request: Request, institution_id: str, body: InstitutionStatusRequest):
    r = _get_redis(request)
    result = set_institution_status(r, institution_id, body.new_status)
    if result:
        return {"outcome": "UPDATED", "institution_id": institution_id, "new_status": body.new_status}
    return {"outcome": "FAILED", "detail": "Institution not found"}


@router.post("/institutions/rebuild-counters")
async def rebuild_counters(request: Request):
    r = _get_redis(request)
    _rebuild_inst_counters(r)
    return {"outcome": "REBUILT"}
