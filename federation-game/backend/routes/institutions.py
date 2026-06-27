"""Institution route handlers — read-only observability for institution/workflow state."""

import json
import os
import redis as _redis
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="", tags=["institutions"])


def _get_redis(request: Optional[Request] = None):
    try:
        if request is not None and getattr(request.app.state, "redis", None) is not None:
            return request.app.state.redis
    except Exception:
        pass
    return _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


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
                roles.append({"role_id": rid, "title": rd.get("title", ""), "holder": rd.get("holder_char_id", ""), "authority": rd.get("authority", "")})
        active_count = 0
        completed_count = 0
        for wf_id in r.smembers("workflow:active"):
            w = r.hgetall(wf_id)
            if w.get("institution_id") == inst_id:
                active_count += 1
        for wf_id in r.smembers("workflow:completed"):
            w = r.hgetall(wf_id)
            if w.get("institution_id") == inst_id:
                completed_count += 1
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
async def list_completed_workflows(request: Request, limit: int = 20):
    r = _get_redis(request)
    all_ids = sorted(r.smembers("workflow:completed"))
    workflows = []
    for wf_id in all_ids[-limit:]:
        rec = r.hgetall(wf_id)
        if rec:
            workflows.append(_workflow_summary(wf_id, rec))
    return {"completed": workflows, "count": len(workflows), "total": len(all_ids)}


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
async def institution_workflows(request: Request, institution_id: str, limit: int = 20):
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
        "completed": completed[-limit:],
        "active_count": len(active),
        "completed_count": len(completed),
    }


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
