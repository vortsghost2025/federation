"""
Error report route handlers — browser-side error capture for agent analysis.

Collects JS errors, unhandled rejections, Reporting API events,
and fetch failures from the frontend into a Redis store that
agents can query.
"""

import json
import logging
import time

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["errors"])


def _get_redis(request: Request):
    """Get Redis client from app state."""
    try:
        return request.app.state.redis
    except AttributeError:
        import redis as _redis, os as _os
        return _redis.from_url(_os.environ.get("REDIS_URL", "redis://redis:6379/0"))


def _redis_hash_value(value):
    """Convert nested report values into Redis hash-safe scalar strings."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


@router.post("/error-reports")
async def report_error(request: Request):
    """Receive error reports from frontend and store in Redis."""
    try:
        payload = await request.json()
    except Exception as e:
        return {"ok": False, "error": f"invalid json: {e}"}

    now = time.time()
    if isinstance(payload, dict) and isinstance(payload.get("reports"), list):
        reports = payload.get("reports") or []
        page_url = payload.get("url", "")
        client_ts = payload.get("timestamp", "")
        user_agent = payload.get("userAgent", "")
    else:
        reports = [payload]
        page_url = payload.get("url", "") if isinstance(payload, dict) else ""
        client_ts = payload.get("timestamp", "") if isinstance(payload, dict) else ""
        user_agent = payload.get("userAgent", "") if isinstance(payload, dict) else ""

    if not reports:
        return {"ok": True, "count": 0, "ids": []}

    r = _get_redis(request)
    if r:
        stored_ids = []
        try:
            for raw_report in reports:
                if isinstance(raw_report, dict):
                    report = dict(raw_report)
                else:
                    report = {"type": "unknown", "message": str(raw_report)}

                report.setdefault("url", page_url)
                report.setdefault("timestamp", client_ts)
                report.setdefault("userAgent", user_agent)
                report["_received"] = now

                ts = int(now)
                key = f"error_report:{ts}:{hash(json.dumps(report, sort_keys=True, default=str)) & 0xFFFF}"
                report["_id"] = key

                r.hset(key, mapping={k: _redis_hash_value(v) for k, v in report.items()})
                r.expire(key, 86400 * 7)  # keep 7 days
                # Also push to a sorted set for agent queries (score = timestamp)
                r.zadd("error_reports", {json.dumps(report, default=str): now})
                # Maintain category counts
                cat = report.get("type", "unknown")
                r.hincrby("error_report_counts", cat, 1)
                r.hincrby("error_report_counts", "_total", 1)
                stored_ids.append(key)
        except Exception as e:
            logger.warning("Failed to store error report: %s", e)
            return {"ok": False, "error": str(e)}
    else:
        return {"ok": False, "error": "redis unavailable"}

    return {"ok": True, "id": stored_ids[0], "ids": stored_ids, "count": len(stored_ids)}


@router.get("/error-reports")
async def get_errors(
    request: Request,
    since: float = 0,
    limit: int = 100,
    type_filter: str = "",
):
    """Get error reports for agent analysis.

    Args:
        since: Unix timestamp — only return reports after this time
        limit: Max reports to return
        type_filter: Optional filter (js-error, unhandled-rejection, fetch-failure, etc.)
    """
    r = _get_redis(request)
    if not r:
        return {"reports": [], "error": "redis unavailable"}

    try:
        raw = r.zrangebyscore("error_reports", since, "+inf", start=0, num=limit)
    except Exception as e:
        return {"reports": [], "error": str(e)}

    reports = []
    for item in raw:
        try:
            report = json.loads(item)
            if type_filter and report.get("type") != type_filter:
                continue
            reports.append(report)
        except json.JSONDecodeError:
            continue

    return {"reports": reports, "count": len(reports)}


@router.get("/error-reports/summary")
async def get_error_summary(request: Request):
    """Get error category counts for agents to prioritize."""
    r = _get_redis(request)
    if not r:
        return {"error": "redis unavailable"}

    try:
        counts = r.hgetall("error_report_counts")
        return {
            "counts": {k.decode() if isinstance(k, bytes) else k:
                       int(v) for k, v in counts.items()},
        }
    except Exception as e:
        return {"counts": {}, "error": str(e)}


@router.delete("/error-reports")
async def clear_errors(request: Request, older_than: float = 0):
    """Clear old error reports. If older_than=0, clears all."""
    r = _get_redis(request)
    if not r:
        return {"ok": False, "error": "redis unavailable"}

    try:
        if older_than > 0:
            r.zremrangebyscore("error_reports", 0, older_than)
        else:
            # Remove all keys matching error_report:*
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor, match="error_report:*", count=100)
                if keys:
                    r.delete(*keys)
                if cursor == 0:
                    break
            r.delete("error_reports")
            r.delete("error_report_counts")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
