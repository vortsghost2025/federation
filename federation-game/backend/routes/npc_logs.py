#!/usr/bin/env python3
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from typing import Optional
from datetime import datetime
from collections import Counter
from federation_game_db import db_manager, NpcActionLog

router = APIRouter(prefix="", tags=["npc-logs"])

def _plain_event(row):
    data = row.data_json or {}
    entry_type = row.entry_type or "unknown"
    category = data.get("category") or entry_type
    desc = data.get("description") or data.get("action_desc") or "Something happened."
    action = data.get("action") or ""
    action_desc = data.get("action_desc") or ""
    reasoning = data.get("reasoning") or ""
    target = data.get("target_name") or data.get("target_char_id")
    relationship_delta = data.get("relationship_delta")
    summary = desc
    if action and action_desc:
        summary = f"{desc} - {action_desc}"
    elif action_desc:
        summary = action_desc
    if target and target not in summary:
        summary = f"{summary} with {target}"
    if reasoning:
        summary = f"{summary} ({reasoning})"
    if relationship_delta is not None:
        sign = "+" if float(relationship_delta) >= 0 else ""
        summary = f"{summary}. Relationship {sign}{relationship_delta}."
    return {"id": row.id, "char_id": row.char_id, "entry_type": entry_type, "category": category, "timestamp": row.timestamp, "summary": summary, "source_text": desc, "target_name": target, "relationship_delta": relationship_delta, "reasoning": reasoning, "action": action}

def _world_mood(d):
    conflict = d.get("conflict", 0) + d.get("rivalry", 0) + d.get("betrayal", 0)
    trade = d.get("trade", 0) + d.get("negotiation", 0)
    social = d.get("friendship", 0) + d.get("alliance", 0) + d.get("collaboration", 0)
    if conflict > trade and conflict > social: return "Tense"
    if trade >= conflict and trade >= social: return "Negotiating"
    if social >= conflict: return "Bonding"
    return "Watching"

@router.get("/spectator/summary")
def spectator_summary(limit: int = Query(80, ge=10, le=250)):
    if not db_manager._initialized:
        return {"status": "error", "headline": "The world is waking up.", "summary": "Database not ready.", "events": [], "distribution": {}}
    try:
        with db_manager._SessionLocal() as session:
            rows = session.query(NpcActionLog).order_by(NpcActionLog.timestamp.desc(), NpcActionLog.id.desc()).limit(limit).all()
    except Exception as e:
        return {"status": "error", "headline": "Error", "summary": str(e), "events": [], "distribution": {}}
    events = [_plain_event(r) for r in rows]
    dist = Counter(e["category"] for e in events)
    counts = Counter(e["entry_type"] for e in events)
    rel = [e for e in events if e.get("target_name")]
    highlighted = rel[:5] or events[:5]
    mood = _world_mood(dist)
    lead = highlighted[0]["summary"] if highlighted else "The Federation is between visible moments."
    parts = []
    interaction_count = counts.get("interaction", 0)
    decision_count = counts.get("decision", 0)
    if counts: parts.append(f"{len(events)} signals: {interaction_count} interactions, {decision_count} decisions.")
    if dist:
        themes = ", ".join(f"{n.replace('_', ' ')} ({c})" for n, c in dist.most_common(3))
        parts.append(f"Themes: {themes}.")
    if rel: parts.append(f"{len(rel)} relationship changes.")
    return {"status": "ok", "updated_at": datetime.utcnow().isoformat() + "Z", "headline": f"{mood}: {lead}", "summary": " ".join(parts), "mood": mood, "events": highlighted, "distribution": dict(dist), "entry_counts": dict(counts), "ask_suggestions": ["What happened?", "Who matters?", "Relationship status?"]}

@router.get("/npc-logs")
def get_npc_logs(char_id: str = Query(...), entry_type: Optional[str] = None, limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0), format: str = Query("json")):
    entry_types = [entry_type] if entry_type else None
    if format.lower() == "csv":
        csv = db_manager.export_npc_action_log_csv(char_id=char_id, entry_types=entry_types, limit=limit) or ""
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=npc_logs_{char_id}.csv"})
    results = db_manager.get_npc_action_log(char_id=char_id, entry_types=entry_types, limit=limit, offset=offset)
    return {"char_id": char_id, "entry_type": entry_type, "limit": limit, "offset": offset, "count": len(results), "results": results}

@router.get("/npc-logs/export")
def export_npc_logs_csv(char_id: str = Query(...), entry_type: Optional[str] = None, limit: int = Query(10000, ge=1, le=50000)):
    entry_types = [entry_type] if entry_type else None
    csv = db_manager.export_npc_action_log_csv(char_id=char_id, entry_types=entry_types, limit=limit) or ""
    return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=npc_logs_{char_id}.csv"})
