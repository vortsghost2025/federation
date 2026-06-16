#!/usr/bin/env python3
import json
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


# --- Threshold bands for world vitals ---
# Lower numbers are worse for "stability", "morale", "resources";
# higher numbers are worse for "tension", "threat", "anomaly".
_VITAL_BANDS_LOW = {"stability", "morale", "resource_abundance"}
_VITAL_BANDS_HIGH = {"tension_level", "threat_level", "anomaly_activity"}


def _vital_band(value, key):
    if value is None:
        return "unknown"
    if key in _VITAL_BANDS_LOW:
        if value < 30:
            return "critical"
        if value < 50:
            return "warning"
        if value < 70:
            return "watch"
        return "good"
    if key in _VITAL_BANDS_HIGH:
        if value > 70:
            return "critical"
        if value > 55:
            return "warning"
        if value > 40:
            return "watch"
        return "good"
    return "watch"


def _vital_label(key):
    return {
        "tension_level": "Tension",
        "resource_abundance": "Resources",
        "threat_level": "Threat",
        "stability": "Stability",
        "morale": "Morale",
        "anomaly_activity": "Anomalies",
    }.get(key, key.replace("_", " ").title())


@router.get("/spectator/world-vitals")
def spectator_world_vitals():
    """Aggregate world state, faction cohesion, and operator warnings
    into a single at-a-glance snapshot. Frontend renders this as 4-6
    colored tiles at the top of the spectator."""
    import time as _time
    out = {"status": "ok", "tiles": [], "factions": [], "operator": {}, "ts": int(_time.time())}

    # The single source of truth used by /world/state and /simulation/state.
    # Imports the same helper the world routes use so the spectator reads
    # exactly what /world and /simulation already return.
    try:
        from npc_autonomy import get_world_state as _gws
        world_state = _gws() or {}
        if not isinstance(world_state, dict):
            world_state = world_state.data if hasattr(world_state, "data") else {}
    except Exception:
        world_state = {}

    keys = ["stability", "tension_level", "resource_abundance", "morale", "threat_level", "anomaly_activity"]
    for k in keys:
        val = world_state.get(k)
        out["tiles"].append({
            "key": k,
            "label": _vital_label(k),
            "value": val,
            "band": _vital_band(val, k),
        })

    # Faction cohesion — pulled from the live game state object.
    try:
        from state import game_state as _gs
        factions = (getattr(getattr(_gs, "game_state_v2", None), "factions", {}) or {})
    except Exception:
        factions = {}

    for fid, fdata in list(factions.items())[:8]:
        cohesion = (fdata or {}).get("cohesion")
        out["factions"].append({
            "id": fid,
            "name": (fdata or {}).get("display_name") or fid.replace("_", " ").title(),
            "cohesion": cohesion,
            "band": _vital_band(cohesion, "stability"),
            "members": (fdata or {}).get("member_count"),
        })

    # Operator warnings — captive signal of who is in a runaway loop or
    # whose validation failed.
    try:
        from simulation_operator import get_operator_status
        op = get_operator_status() or {}
        last_result = op.get("last_result") or {}
        last_validation = op.get("last_validation") or {}
        war = last_result.get("warnings") or []
        val_war = last_validation.get("warnings") or []
        loop_chars = sorted({w.get("char_id") for w in (war + val_war) if w.get("check") == "runaway_loop"} and {None})
        out["operator"] = {
            "status": op.get("status"),
            "last_tick_id": op.get("last_tick_id"),
            "stability_delta": (last_result.get("world_state_changes") or {}).get("stability"),
            "npc_count": last_result.get("npc_count"),
            "turn_count": last_result.get("turn_count"),
            "warnings": [
                {"char_id": w.get("char_id"), "message": w.get("message"), "severity": w.get("severity")}
                for w in (war + val_war)[:3]
            ],
        }
    except Exception as e:
        out["operator"] = {"error": str(e), "status": "unknown"}

    out["updated_at"] = datetime.utcnow().isoformat() + "Z"
    return out


def _cluster_scenes_into_threads(scenes, max_threads=6):
    """Group scenes that share participants into one thread.
    Two scenes become part of the same thread if they share at least
    one char_id. Threads are then ranked by combined drama score:
      abs(relationship_delta) summed + active-participant weight +
      recency. We cap to max_threads and return the densest arcs."""
    if not scenes:
        return []

    # First, give each scene a drama score.
    scored = []
    for s in scenes:
        delta = s.get("relationship_delta") or 0
        mood_delta = s.get("mood_delta") or 0
        participants = s.get("participants") or []
        dialogue = s.get("dialogue") or []
        drama = abs(delta) + abs(mood_delta) * 0.5 + len(participants) * 0.5 + len(dialogue) * 0.5
        if s.get("category") in ("betrayal", "conflict", "suspicion"):
            drama *= 1.5
        if (s.get("category") or "") in ("friendship", "alliance", "collaboration"):
            drama *= 1.2
        scored.append((drama, s))

    # Cluster: union-find on char_id overlap.
    parent = list(range(len(scored)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, (_, sa) in enumerate(scored):
        chars_i = {p.get("char_id") for p in (sa.get("participants") or [])}
        for j, (_, sb) in enumerate(scored):
            if j <= i:
                continue
            chars_j = {p.get("char_id") for p in (sb.get("participants") or [])}
            if chars_i & chars_j:
                union(i, j)

    buckets = {}
    for i, (drama, s) in enumerate(scored):
        buckets.setdefault(find(i), []).append((drama, s))

    threads = []
    for cluster in buckets.values():
        cluster.sort(key=lambda t: t[1].get("timestamp") or 0, reverse=True)
        head = cluster[0][1]
        all_chars = {}
        drama_total = 0
        for drama, s in cluster:
            for p in s.get("participants") or []:
                cid = p.get("char_id")
                if cid and cid not in all_chars:
                    all_chars[cid] = p.get("name") or cid
            drama_total += drama
        # If a thread only has one scene and that scene only has one
        # participant, skip — the scene list already covers that.
        if len(cluster) == 1 and len(all_chars) <= 1:
            continue
        threads.append({
            "head": head,
            "scene_count": len(cluster),
            "characters": [{"char_id": cid, "name": name} for cid, name in all_chars.items()],
            "drama": round(drama_total, 2),
            "categories": Counter(s.get("category") for _, s in cluster).most_common(3),
            "latest_ts": cluster[0][1].get("timestamp"),
            "earliest_ts": cluster[-1][1].get("timestamp"),
            "scenes": [s for _, s in cluster[-3:]],
        })

    threads.sort(key=lambda t: t["drama"], reverse=True)
    return threads[:max_threads]


@router.get("/spectator/threads")
def spectator_threads(limit: int = Query(60, ge=10, le=240), max_threads: int = Query(6, ge=1, le=12)):
    """Cluster recent scenes into active cross-participant threads.
    Each thread is a single named storyline that touches multiple
    characters; the spectator renders the highest-drama threads at
    the top so you can see 'The Overthrow' and 'The Theta Protocol'
    instead of 60 flat scenes."""
    if not db_manager._initialized:
        return {"status": "error", "threads": [], "error": "Database not ready."}
    try:
        with db_manager._SessionLocal() as session:
            rows = session.query(NpcActionLog).order_by(
                NpcActionLog.timestamp.desc(), NpcActionLog.id.desc()
            ).limit(limit).all()
    except Exception as e:
        return {"status": "error", "threads": [], "error": str(e)}

    npc_names = _collect_npc_name_map(rows)
    events = [_plain_event(r) for r in rows]
    raw_scenes = _cluster_into_scenes(events, npc_names, time_window=4, limit=limit)

    threads = _cluster_scenes_into_threads(raw_scenes, max_threads=max_threads)

    # Snake-case label heuristic — short, evocative, mentions top 2 actors.
    for thread in threads:
        char_names = [c["name"] for c in thread["characters"][:3]]
        cats = [c[0] for c in thread["categories"]]
        if "betrayal" in cats or "conflict" in cats:
            label = f"{char_names[0]} vs {char_names[1] if len(char_names) > 1 else 'others'}"
        elif "alliance" in cats or "collaboration" in cats:
            label = f"{char_names[0]} & {char_names[1] if len(char_names) > 1 else 'allies'}"
        elif "suspicion" in cats:
            label = f"{char_names[0]}'s hunt for {char_names[1] if len(char_names) > 1 else 'an answer'}"
        elif "trade" in cats:
            label = f"{char_names[0]}'s trade with {char_names[1] if len(char_names) > 1 else 'others'}"
        else:
            label = f"{char_names[0]}'s {cats[0] if cats else 'scene'}"
        thread["label"] = label
        thread["tone"] = (
            "negative" if any(c in cats for c in ("betrayal", "conflict", "suspicion"))
            else "positive" if any(c in cats for c in ("friendship", "alliance", "collaboration"))
            else "neutral"
        )

    return {
        "status": "ok",
        "thread_count": len(threads),
        "threads": threads,
        "scene_pool_size": len(raw_scenes),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def _collect_npc_name_map(rows):
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
    if not npc_names:
        try:
            import redis as _redis, os as _os
            r = _redis.from_url(_os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
            for key in r.scan_iter("npc:*"):
                if ":name" in key:
                    char_id = key.split(":")[1] if ":" in key else ""
                    if char_id:
                        npc_names[char_id] = r.get(key)
        except Exception:
            pass
    return npc_names


def _cluster_into_scenes(events, npc_names, time_window=3, limit=60):
    """Build scenes from a raw event list, matching the spectator/scenes
    logic, but without all the dialogue extraction. Used by /spectator/threads
    so it can cluster by participant overlap cheaply."""
    scenes = []
    used = set()
    for i, ev in enumerate(events):
        if i in used:
            continue
        scene = {
            "timestamp": ev["timestamp"],
            "category": ev["category"],
            "entry_type": ev["entry_type"],
            "summary": ev["summary"],
            "relationship_delta": ev.get("relationship_delta"),
            "mood_delta": 0,
            "participants": [{"char_id": ev["char_id"], "name": npc_names.get(ev["char_id"], ev["char_id"])}],
            "dialogue": [],
        }
        for j, other in enumerate(events):
            if j <= i or j in used:
                continue
            same_cat = other["category"] == ev["category"]
            time_diff = abs((other.get("timestamp") or 0) - (ev.get("timestamp") or 0))
            if time_diff <= time_window and (same_cat or ev["char_id"] == other["char_id"]):
                used.add(j)
                pname = npc_names.get(other["char_id"], other["char_id"])
                if not any(p["char_id"] == other["char_id"] for p in scene["participants"]):
                    scene["participants"].append({"char_id": other["char_id"], "name": pname})
        used.add(i)
        scenes.append(scene)
        if len(scenes) >= limit:
            break
    scenes.sort(key=lambda s: s["timestamp"] or 0, reverse=True)
    return scenes

