#!/usr/bin/env python3
"""
NPC Activity Logs API Routes
Provides JSON and CSV access to NPC activity logs from PostgreSQL.
"""
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from typing import Optional, List
from datetime import datetime
from collections import Counter

from federation_game_db import db_manager, NpcActionLog


router = APIRouter(prefix="", tags=["npc-logs"])


def _plain_event(row: NpcActionLog) -> dict:
    data = row.data_json or {}
    entry_type = row.entry_type or "unknown"
    category = data.get("category") or entry_type
    description = data.get("description") or data.get("action_desc") or "Something changed."
    target = data.get("target_name") or data.get("target_char_id")
    relationship_delta = data.get("relationship_delta")

    summary = description
    if target and target not in summary:
        summary = f"{summary} with {target}"
    if relationship_delta is not None:
        sign = "+" if float(relationship_delta) >= 0 else ""
        summary = f"{summary}. Relationship {sign}{relationship_delta}."

    return {
        "id": row.id,
        "char_id": row.char_id,
        "entry_type": entry_type,
        "category": category,
        "timestamp": row.timestamp,
        "summary": summary,
        "source_text": description,
        "target_name": target,
        "relationship_delta": relationship_delta,
    }


def _world_mood(distribution: Counter) -> str:
    conflict = distribution.get("conflict", 0) + distribution.get("rivalry", 0) + distribution.get("betrayal", 0)
    trade = distribution.get("trade", 0) + distribution.get("negotiation", 0)
    social = distribution.get("friendship", 0) + distribution.get("alliance", 0) + distribution.get("collaboration", 0)
    if conflict > trade and conflict > social:
        return "Tense"
    if trade >= conflict and trade >= social:
        return "Negotiating"
    if social >= conflict:
        return "Bonding"
    return "Watching"


@router.get("/spectator/summary")
def spectator_summary(limit: int = Query(80, ge=10, le=250)):
    """Readable observer feed for the simple spectator page."""
    if not db_manager._initialized:
        return {
            "status": "error",
            "headline": "The world is waking up.",
            "summary": "The database is not ready yet, so the spectator feed is waiting for the next pulse.",
            "events": [],
            "distribution": {},
        }

    try:
        with db_manager._SessionLocal() as session:
            rows = (
                session.query(NpcActionLog)
                .order_by(NpcActionLog.timestamp.desc(), NpcActionLog.id.desc())
                .limit(limit)
                .all()
            )
    except Exception as exc:
        return {
            "status": "error",
            "headline": "The world is quiet for a moment.",
            "summary": f"The spectator feed could not read the activity log: {exc}",
            "events": [],
            "distribution": {},
        }

    events = [_plain_event(row) for row in rows]
    distribution = Counter(event["category"] for event in events)
    entry_counts = Counter(event["entry_type"] for event in events)
    relationship_events = [event for event in events if event.get("target_name")]
    highlighted = relationship_events[:5] or events[:5]
    mood = _world_mood(distribution)

    if highlighted:
        lead = highlighted[0]["summary"]
    else:
        lead = "The Federation is between visible moments."

    headline = f"{mood}: {lead}"
    summary_parts = []
    if entry_counts:
        summary_parts.append(
            f"The last {len(events)} signals include {entry_counts.get('interaction', 0)} interactions, "
            f"{entry_counts.get('decision', 0)} decisions, and {entry_counts.get('cognition', 0)} deep thoughts."
        )
    if distribution:
        top = ", ".join(f"{name.replace('_', ' ')} ({count})" for name, count in distribution.most_common(4))
        summary_parts.append(f"The strongest themes right now are {top}.")
    if relationship_events:
        summary_parts.append(f"{len(relationship_events)} recent moments directly changed relationships between named NPCs.")

    return {
        "status": "ok",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "headline": headline,
        "summary": " ".join(summary_parts) or "The world is alive, but no activity has been logged yet.",
        "mood": mood,
        "events": highlighted,
        "distribution": dict(distribution),
        "entry_counts": dict(entry_counts),
        "ask_suggestions": [
            "What just happened in simple terms?",
            "Who is becoming important right now?",
            "Are relationships improving or getting worse?",
            "What should I watch next?",
        ],
    }


@router.get("/npc-logs")
def get_npc_logs(
    char_id: str = Query(..., description="NPC character ID"),
    entry_type: Optional[str] = Query(None, description="Filter by entry type (cognition, interaction, decision, chat)"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum entries to return"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    format: str = Query("json", description="Response format: 'json' or 'csv'"),
):
    """
    Get NPC activity logs.

    Query parameters:
    - char_id (required): NPC character ID
    - entry_type: Filter by entry type (cognition, interaction, decision, chat)
    - limit: Max entries (1-1000, default 50)
    - offset: Pagination offset (default 0)
    - format: 'json' or 'csv' (default 'json')

    Returns JSON array of log entries or CSV text.
    """
    entry_types = [entry_type] if entry_type else None

    if format.lower() == "csv":
        csv_data = db_manager.export_npc_action_log_csv(
            char_id=char_id,
            entry_types=entry_types,
            limit=limit,
        )
        if not csv_data:
            return PlainTextResponse("id,char_id,entry_type,timestamp,data_json,created_at\n", media_type="text/csv")
        return PlainTextResponse(csv_data, media_type="text/csv")

    # JSON response
    results = db_manager.get_npc_action_log(
        char_id=char_id,
        entry_types=entry_types,
        limit=limit,
        offset=offset,
    )
    return {
        "char_id": char_id,
        "entry_type": entry_type,
        "limit": limit,
        "offset": offset,
        "count": len(results),
        "results": results,
    }


@router.get("/npc-logs/export")
def export_npc_logs_csv(
    char_id: str = Query(..., description="NPC character ID"),
    entry_type: Optional[str] = Query(None, description="Filter by entry type"),
    limit: int = Query(10000, ge=1, le=50000, description="Maximum entries to export"),
):
    """
    Export NPC activity logs as CSV (dedicated endpoint).

    Query parameters:
    - char_id (required): NPC character ID
    - entry_type: Optional filter by entry type
    - limit: Max entries (1-50000, default 10000)
    """
    entry_types = [entry_type] if entry_type else None

    csv_data = db_manager.export_npc_action_log_csv(
        char_id=char_id,
        entry_types=entry_types,
        limit=limit,
    )
    if not csv_data:
        csv_data = "id,char_id,entry_type,timestamp,data_json,created_at\n"

    filename = f"npc_logs_{char_id}.csv"
    return PlainTextResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
