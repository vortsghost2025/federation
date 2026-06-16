#!/usr/bin/env python3
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from typing import Optional
from datetime import datetime
from collections import Counter, defaultdict
from federation_game_db import db_manager, NpcActionLog

router = APIRouter(prefix="", tags=["npc-logs"])

def _avg(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 1) if values else 0

def _analyze_turns(turns):
    now = int(datetime.utcnow().timestamp())
    grouped = defaultdict(list)
    for turn in turns:
        grouped[turn.get("npc_id") or "unknown"].append(turn)

    fleet = []
    alerts = []
    for npc_id, rows in grouped.items():
        rows.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
        latest = rows[0]
        providers = Counter(r.get("model_provider") or "unknown" for r in rows)
        models = Counter(r.get("model_name") or "unknown" for r in rows)
        task_classes = Counter(r.get("task_class") or "unknown" for r in rows)
        errors = [r for r in rows if r.get("error_code")]
        fallbacks = [r for r in rows if r.get("fallback_used")]
        memory_used = [r for r in rows if r.get("memory_context_ids")]
        tool_used = [r for r in rows if r.get("tool_calls") or r.get("tool_events")]
        latencies = [r.get("latency_ms") for r in rows if r.get("latency_ms") is not None]
        avg_latency = _avg(latencies)
        max_latency = max(latencies) if latencies else 0
        output_previews = Counter((r.get("output_text") or "")[:80] for r in rows if r.get("output_text"))
        repeated_outputs = [text for text, count in output_previews.items() if text and count >= 2]

        anomaly_flags = []
        error_rate = round(len(errors) / len(rows), 3) if rows else 0
        fallback_rate = round(len(fallbacks) / len(rows), 3) if rows else 0
        if error_rate >= 0.2:
            anomaly_flags.append("repeated_failures")
        if fallback_rate >= 0.2:
            anomaly_flags.append("provider_fallbacks")
        if len(providers) > 1:
            anomaly_flags.append("provider_drift")
        if avg_latency and max_latency > max(5000, avg_latency * 2):
            anomaly_flags.append("latency_spike")
        if not memory_used:
            anomaly_flags.append("missing_memory")
        if repeated_outputs:
            anomaly_flags.append("repeated_loop")
        if any(r.get("error_code") == "parse_unparseable" for r in rows):
            anomaly_flags.append("unparseable_output")

        summary = {
            "npc_id": npc_id,
            "turn_count": len(rows),
            "online": now - int(latest.get("timestamp") or 0) < 600,
            "last_turn_ts": latest.get("timestamp"),
            "usual_behavior": f"Usually runs {task_classes.most_common(1)[0][0]} via {providers.most_common(1)[0][0]}" if rows else "No turn history",
            "recent_change": ", ".join(anomaly_flags) if anomaly_flags else "No anomaly in recent window",
            "common_failure_modes": [code for code, _ in Counter(r.get("error_code") for r in errors).most_common(3)],
            "providers": dict(providers),
            "models": dict(models),
            "task_classes": dict(task_classes),
            "avg_latency_ms": avg_latency,
            "max_latency_ms": max_latency,
            "error_rate": error_rate,
            "fallback_rate": fallback_rate,
            "memory_usage_rate": round(len(memory_used) / len(rows), 3) if rows else 0,
            "tool_dependence_rate": round(len(tool_used) / len(rows), 3) if rows else 0,
            "anomalies": anomaly_flags,
        }
        fleet.append(summary)

        for flag in anomaly_flags:
            alerts.append({"npc_id": npc_id, "type": flag, "last_turn_ts": latest.get("timestamp")})

    fleet.sort(key=lambda row: (len(row["anomalies"]), row.get("last_turn_ts") or 0), reverse=True)
    return {"fleet": fleet, "alerts": alerts}

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

@router.get("/npc-turns")
def get_npc_turns(npc_id: Optional[str] = None, char_id: Optional[str] = None, limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0), include_events: bool = False):
    target_id = npc_id or char_id
    results = db_manager.get_npc_turns(npc_id=target_id, limit=limit, offset=offset, include_events=include_events)
    return {"npc_id": target_id, "limit": limit, "offset": offset, "count": len(results), "results": results}

@router.get("/npc-turns/analyze")
def analyze_npc_turns(npc_id: Optional[str] = None, char_id: Optional[str] = None, limit: int = Query(500, ge=10, le=5000)):
    target_id = npc_id or char_id
    turns = db_manager.get_npc_turns(npc_id=target_id, limit=limit, offset=0, include_events=False)
    analysis = _analyze_turns(turns)
    return {
        "status": "ok",
        "npc_id": target_id,
        "turns_analyzed": len(turns),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        **analysis,
    }



@router.get("/spectator/scenes")
def spectator_scenes(limit: int = Query(60, ge=10, le=200), page: int = Query(0, ge=0)):
    """Grouped, deduplicated event scenes with NPC name resolution."""
    if not db_manager._initialized:
        return {"status": "error", "scenes": [], "total": 0, "page": 0}
    try:
        with db_manager._SessionLocal() as session:
            rows = session.query(NpcActionLog).order_by(
                NpcActionLog.timestamp.desc(), NpcActionLog.id.desc()
            ).limit(limit * 3).all()
    except Exception as e:
        return {"status": "error", "scenes": [], "total": 0, "error": str(e)}

    # Build NPC name lookup — GameState.npc_system.characters dict
    npc_names = {}
    try:
        from state import game_state
        chars = getattr(getattr(game_state, "npc_system", None), "characters", {})
        for cid, char_obj in chars.items():
            nm = getattr(char_obj, "name", "") or cid
            npc_names[cid] = nm
        comps = getattr(getattr(game_state, "npc_system", None), "companions", {})
        for cid, comp_obj in comps.items():
            nm = getattr(comp_obj, "name", "") or cid
            npc_names[cid] = nm
    except Exception:
        pass

    # Fallback: scan Redis for NPC names if game_state didn't work
    if not npc_names:
        try:
            import redis as _redis, os
            r = _redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
            for key in r.scan_iter("npc:*"):
                if ":name" in key:
                    char_id = key.split(":")[1] if ":" in key else ""
                    npc_names[char_id] = r.get(key)
        except Exception:
            pass

    def resolve_name(char_id):
        if not char_id:
            return "Someone"
        return npc_names.get(char_id, char_id)

    # Group events into scenes
    # Same timestamp (within 2 sec) + same category = one scene
    events = []
    for row in rows:
        ev = _plain_event(row)
        ev["source_name"] = resolve_name(ev["char_id"])
        events.append(ev)

    # Group by timestamp proximity and category
    scenes = []
    used = set()
    for i, ev in enumerate(events):
        if i in used:
            continue
        scene = {
            "timestamp": ev["timestamp"],
            "category": ev["category"],
            "entry_type": ev["entry_type"],
            "participants": [{"char_id": ev["char_id"], "name": ev["source_name"]}],
            "dialogue": [],
            "summary": ev["summary"],
            "relationship_delta": ev.get("relationship_delta"),
            "mood_delta": 0,
        }

        # Extract dialogue from summary
        summary = ev.get("summary", "")
        if '"' in summary:
            # Find quoted dialogue
            import re
            dialogues = re.findall(r'"([^"]+)"', summary)
            if dialogues:
                scene["dialogue"] = [{"speaker": ev["source_name"], "text": d} for d in dialogues]

        # Find matching events (same time, same interaction)
        for j, other in enumerate(events):
            if j <= i or j in used:
                continue
            time_diff = abs((other["timestamp"] or 0) - (ev["timestamp"] or 0))
            same_category = other["category"] == ev["category"]
            same_summary = other.get("source_text", "")[:40] == ev.get("source_text", "")[:40]

            if time_diff <= 3 and (same_category or same_summary):
                used.add(j)
                # Add as participant
                other_name = other["source_name"]
                if not any(p["char_id"] == other["char_id"] for p in scene["participants"]):
                    scene["participants"].append({"char_id": other["char_id"], "name": other_name})

                # Merge relationship deltas
                if other.get("relationship_delta") is not None:
                    if scene["relationship_delta"] is None:
                        scene["relationship_delta"] = other["relationship_delta"]
                    else:
                        scene["relationship_delta"] = round(
                            float(scene["relationship_delta"]) + float(other["relationship_delta"]), 1
                        )

                # Extract additional dialogue
                other_summary = other.get("summary", "")
                if '"' in other_summary:
                    import re
                    other_dialogues = re.findall(r'"([^"]+)"', other_summary)
                    for d in other_dialogues:
                        if not any(dg["text"] == d for dg in scene["dialogue"]):
                            scene["dialogue"].append({"speaker": other_name, "text": d})

        # Compute mood delta
        rd = scene.get("relationship_delta")
        if rd is not None:
            scene["mood_delta"] = round(float(rd), 1)

        used.add(i)
        scenes.append(scene)

    # Paginate
    total = len(scenes)
    page_size = 8
    start = page * page_size
    end = start + page_size
    page_scenes = scenes[start:end]

    # World mood
    dist = Counter(s["category"] for s in scenes)
    mood = _world_mood(dist)

    return {
        "status": "ok",
        "mood": mood,
        "scenes": page_scenes,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": end < total,
    }

