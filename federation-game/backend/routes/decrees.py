"""Councilor Decrees — bounded world-state write access for authorized councilors."""

import os
import redis as _redis
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from operator_auth import require_operator
from npc_autonomy import (
    issue_decree,
    get_decree_history,
    DECREES_ALLOWED_NPCS,
    DECREES_ALLOWED_METRICS,
    DECREE_MAX_DELTA,
    DECREE_COOLDOWN_SECONDS,
)

router = APIRouter(prefix="", tags=["councilor-decrees"])

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


class DecreeRequest(BaseModel):
    char_id: str = Field(..., pattern=r"^char_\d{3}$")
    char_name: str = Field(..., min_length=1, max_length=80)
    metric: str
    delta: int = Field(..., ge=-DECREE_MAX_DELTA, le=DECREE_MAX_DELTA)
    reasoning: str = Field("", max_length=500)


@router.post("/councilor/decree", dependencies=[Depends(require_operator)])
def post_decree(req: DecreeRequest, request: Request):
    result = issue_decree(req.char_id, req.char_name, req.metric, req.delta, req.reasoning)
    return result


@router.get("/councilor/decrees")
def list_decrees(char_id: Optional[str] = None, limit: int = 20):
    limit = max(1, min(limit, 100))
    decrees = get_decree_history(char_id=char_id, limit=limit)
    return {"decrees": decrees, "count": len(decrees)}


@router.get("/councilor/decrees/capabilities")
def decree_capabilities():
    return {
        "allowed_npcs": DECREES_ALLOWED_NPCS,
        "allowed_metrics": DECREES_ALLOWED_METRICS,
        "max_delta": DECREE_MAX_DELTA,
        "cooldown_seconds": DECREE_COOLDOWN_SECONDS,
    }
