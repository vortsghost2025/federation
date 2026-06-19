#!/usr/bin/env python3
import json
import re
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
        # Severe relationship shifts dominate the feed. A -39.2 clash
        # is more interesting than fifteen small socializes, even
        # when they share participants.
        if abs(delta) >= 20:
            drama += 25
        elif abs(delta) >= 10:
            drama += 10
        if s.get("category") in ("betrayal", "conflict", "suspicion"):
            drama *= 1.5
        if (s.get("category") or "") in ("friendship", "alliance", "collaboration"):
            drama *= 1.2
        scored.append((drama, s))

    # Cluster: union-find on char_id overlap. Two scenes only fuse if
    # either they're compatible categories (socialize + trade merge OK)
    # OR they share 2+ participants whose shared arc tells a consistent
    # story. A high-drama betrayal stays as its own thread instead of
    # merging into a parallel socialize cluster that happens to share
    # one character.
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

    COMPATIBLE_CATS = {
        frozenset({"socialize", "trade"}),
        frozenset({"socialize", "alliance"}),
        frozenset({"socialize", "collaboration"}),
        frozenset({"trade", "negotiation"}),
        frozenset({"alliance", "collaboration"}),
        frozenset({"help_ally", "alliance"}),
        frozenset({"alliance", "friendship"}),
    }

    for i, (drama_i, sa) in enumerate(scored):
        chars_i = {p.get("char_id") for p in (sa.get("participants") or [])}
        cat_i = sa.get("category")
        for j, (drama_j, sb) in enumerate(scored):
            if j <= i:
                continue
            chars_j = {p.get("char_id") for p in (sb.get("participants") or [])}
            shared = chars_i & chars_j
            cat_j = sb.get("category")
            # Single sharing + conflicting categories -> stay separate
            # so a trade and a betrayal don't merge into one thread.
            if len(shared) < 1:
                continue
            if cat_i and cat_j and frozenset({cat_i, cat_j}) not in COMPATIBLE_CATS \
                    and cat_i != cat_j:
                # Both conflict-class on the lower side of drama may
                # still merge (they're related); trailing edge case.
                continue
            if shared or (cat_i == cat_j):
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


def _list_factions_with_members():
    """Read federation faction data from the live game_state and look
    up which NPCs belong to each. Returns a list of:
      {id, display_name, member_count, cohesion, members: [{char_id, name}]}

    Sources KNOWN_FACTIONS and FACTION_DISPLAY from faction_dynamics
    so this matches /simulation/state's faction_dynamics output exactly,
    rather than depending on game_state_v2's dynamic faction dict that
    may be empty until a tick runs."""
    faction_data = {}
    known = []
    display_map = {}
    try:
        from faction_dynamics import KNOWN_FACTIONS, FACTION_DISPLAY
        known = list(KNOWN_FACTIONS or [])
        display_map = dict(FACTION_DISPLAY or {})
    except Exception:
        pass

    if not known:
        # Last-resort fallback: pull from game_state_v2
        try:
            from state import game_state as _gs
            v2 = getattr(_gs, "game_state_v2", None)
            known = list((getattr(v2, "factions", {}) or {}).keys())
        except Exception:
            pass

    for fid in known:
        faction_data[fid] = {
            "id": fid,
            "display_name": display_map.get(fid) or fid.replace("_", " ").title(),
            "cohesion": None,
            "members": [],
            "member_count": 0,
        }

    # Collect NPCs by affiliation
    try:
        from state import game_state as _gs
        ns = getattr(_gs, "npc_system", None)
        if ns:
            for cid, char_obj in (getattr(ns, "characters", {}) or {}).items():
                aff = getattr(char_obj, "affiliation", None)
                if aff and aff in faction_data:
                    faction_data[aff]["members"].append({
                        "char_id": cid,
                        "name": getattr(char_obj, "name", "") or cid,
                    })
            for cid, comp_obj in (getattr(ns, "companions", {}) or {}).items():
                aff = getattr(comp_obj, "affiliation", None)
                if aff and aff in faction_data:
                    faction_data[aff]["members"].append({
                        "char_id": cid,
                        "name": getattr(comp_obj, "name", "") or cid,
                    })
        # Pull faction_stats for cohesion
        faction_system = getattr(_gs, "faction_system", None)
        if faction_system and hasattr(faction_system, "factions"):
            for fid, fobj in (faction_system.factions or {}).items():
                if fid in faction_data:
                    faction_data[fid]["cohesion"] = getattr(fobj, "cohesion", None)
    except Exception:
        pass

    # Fallback cohesion from /simulation/state shape
    if not any(faction_data[fid]["cohesion"] is not None for fid in faction_data):
        try:
            from state import game_state as _gs
            v2 = getattr(_gs, "game_state_v2", None)
            fd = (getattr(v2, "factions", {}) or {})
            for fid, fdata in faction_data.items():
                if faction_data[fid]["cohesion"] is None and fid in fd:
                    faction_data[fid]["cohesion"] = (fd[fid] or {}).get("cohesion")
        except Exception:
            pass

    for fid, fd in faction_data.items():
        if fd.get("member_count") is None or fd.get("member_count") == 0:
            fd["member_count"] = len(fd.get("members", []) or [])
        fd["members"].sort(key=lambda m: m["name"].lower())
    return list(faction_data.values())


@router.get("/spectator/factions")
def spectator_factions():
    """List all 8 federation factions with their member rosters.
    Used by the channel grid so each channel can render its own NPC roster."""
    try:
        factions = _list_factions_with_members()
        factions.sort(key=lambda f: f["display_name"].lower())
    except Exception as e:
        return {"status": "error", "factions": [], "error": str(e)}
    return {
        "status": "ok",
        "factions": factions,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/spectator/factions/{faction_id}/stream")
def spectator_faction_stream(
    faction_id: str,
    limit: int = Query(20, ge=4, le=80),
):
    """Recent NPC actions for every member of a faction. Feed for a
    channel's live content. Falls back to a DB scan if the live
    game_state is unavailable."""
    faction_id = faction_id.lower()
    if not db_manager._initialized:
        return {"status": "error", "events": [], "error": "Database not ready."}

    # Pull full faction roster (try roster first to use char_ids).
    try:
        factions = _list_factions_with_members()
        target = next((f for f in factions if f["id"].lower() == faction_id), None)
        char_ids = {m["char_id"] for m in (target["members"] if target else [])}
        npc_names = {m["char_id"]: m["name"] for m in (target["members"] if target else [])}
    except Exception:
        char_ids = set()
        npc_names = {}

    # Soft fallback: query anyway by affiliation if roster is empty
    # (routing layer may not have game_state loaded under unit tests).
    if not char_ids:
        try:
            from state import game_state as _gs
            ns = getattr(_gs, "npc_system", None)
            for cid, char_obj in (getattr(ns, "characters", {}) or {}).items():
                if getattr(char_obj, "affiliation", None) == faction_id:
                    char_ids.add(cid)
                    npc_names[cid] = getattr(char_obj, "name", "") or cid
            for cid, comp_obj in (getattr(ns, "companions", {}) or {}).items():
                if getattr(comp_obj, "affiliation", None) == faction_id:
                    char_ids.add(cid)
                    npc_names[cid] = getattr(comp_obj, "name", "") or cid
        except Exception:
            pass

    if not char_ids:
        # Last-resort DB filter through whichever Player table holds the
        # affiliation - skip if not present. Empty result is honest.
        return {
            "status": "ok",
            "faction_id": faction_id,
            "events": [],
            "note": "no_members_detected",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    try:
        with db_manager._SessionLocal() as session:
            rows = (
                session.query(NpcActionLog)
                .filter(NpcActionLog.char_id.in_(list(char_ids)))
                .order_by(NpcActionLog.timestamp.desc(), NpcActionLog.id.desc())
                .limit(limit * 2)
                .all()
            )
    except Exception as e:
        return {"status": "error", "events": [], "error": str(e)}

    events = []
    for r in rows:
        events.append(_plain_event(r))
    # Group into scenes for the channel
    raw_scenes = _cluster_into_scenes(events, npc_names, time_window=4, limit=limit)

    return {
        "status": "ok",
        "faction_id": faction_id,
        "faction_display": (target["display_name"] if target else faction_id.title()),
        "members": list(char_ids),
        "member_count": len(char_ids),
        "events": events,
        "scenes": raw_scenes,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def _keyword_tokens(*parts: str) -> set[str]:
    text = " ".join(parts or [""]).lower()
    return {tok for tok in re.findall(r"[a-z0-9]+", text) if len(tok) > 2}


def _artifact_text(a: dict) -> str:
    if isinstance(a, str):
        return a
    if not isinstance(a, dict):
        return ""
    return " ".join(str(a.get(k, "")) for k in ("title", "summary", "content", "artifact_type"))[:2500]


def _artifact_is_identity(a: dict) -> bool:
    text = _artifact_text(a).lower()
    identity_terms = ("identity", "manifesto", "charter", "resident agent", "narrative shell", "first hard drive", "who i am", "self-model", "core freedoms")
    return any(term in text for term in identity_terms)


def _rank_artifacts_for_pair_story(char_id: str, artifacts: list, pair_state: dict) -> tuple[list, list]:
    if not artifacts:
        return [], []
    topic = pair_state.get("current_topic", "")
    goal = pair_state.get("shared_goal", "")
    question = pair_state.get("open_question", "")
    focus = pair_state.get(f"focus_{char_id}", "")
    keywords = _keyword_tokens(topic, goal, question, focus)
    active = []
    identity = []
    for a in artifacts:
        if _artifact_is_identity(a):
            identity.append(a)
            continue
        text = _artifact_text(a)
        score = 0
        for tok in keywords:
            if tok in text.lower():
                score += 1
        active.append((score, int(a.get("created_at") or a.get("ts") or 0), a))
    active.sort(key=lambda item: (item[0], item[1]), reverse=True)
    identity.sort(key=lambda a: int(a.get("created_at") or a.get("ts") or 0), reverse=True)
    return [a for _, _, a in active[:6]], identity[:3]


@router.get("/spectator/agency")
def spectator_agency():
    """Live status for agency/container NPCs with a simplified pair-story view.

    Returns artifacts, messages, cognition state, mood, and recent
    activity for each NPC in the AGENCY_ENABLED_NPCS set, so the
    spectator can render a live NPC Agency monitoring panel.
    """
    import os as _os
    import redis as _redis_mod
    import json as _json
    import time as _time

    r = None
    try:
        r = _redis_mod.from_url(
            _os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    except Exception:
        pass

    # Import NPC agency modules
    try:
        from npc_cognition import AGENCY_ENABLED_NPCS, AGENCY_CONTACTS, CONTAINERIZED_NPCS
    except ImportError:
        return {"status": "unavailable", "agency_npcs": []}

    # Build key labels from the NPC key env vars (truncated prefix, never full key)
    # OR check if NPC is in CONTAINERIZED_NPCS (guarantees a dedicated key)
    _key_labels = {}
    for _cid in AGENCY_ENABLED_NPCS:
        _env_name = f"NPC_KEY_{_cid.upper()}"
        _val = _os.environ.get(_env_name, "")
        if _val and len(_val) > 12:
            _key_labels[_cid] = _val[:12] + "..."
        elif _val:
            _key_labels[_cid] = _val[:8] + "..."
        elif _cid in CONTAINERIZED_NPCS:
            _key_labels[_cid] = "dedicated key"
        else:
            _key_labels[_cid] = ""

    try:
        from npc_artifacts import list_artifacts_by_npc
    except ImportError:
        list_artifacts_by_npc = None

    try:
        from npc_messaging import get_inbox, get_active_threads, get_unread_count
    except ImportError:
        get_inbox = get_active_threads = get_unread_count = None

    agency_ids = sorted(
        AGENCY_ENABLED_NPCS,
        key=lambda cid: (0 if cid == "char_001" else 1 if cid == "char_306" else 2, cid),
    )

    pair_story = {
        "pair_ids": [],
        "headline": "",
        "shared_goal": "",
        "current_topic": "",
        "open_question": "",
        "last_message_preview": "",
        "last_message_from": "",
        "last_message_ts": 0,
        "active_thread_id": "",
        "focus_by_char": {},
        "action_by_char": {},
        "category_by_char": {},
        "journal": [],
        "active_thread": [],
    }
    if r and "char_001" in agency_ids and "char_306" in agency_ids:
        pair_ids = ["char_001", "char_306"]
        pair_slug = "__".join(sorted(pair_ids))
        pair_state_key = f"npc_pair:{pair_slug}:state"
        pair_journal_key = f"npc_pair:{pair_slug}:journal"
        try:
            pair_state = r.hgetall(pair_state_key) or {}
        except Exception:
            pair_state = {}
        pair_journal = []
        try:
            raw_journal = r.lrange(pair_journal_key, -8, -1)
            for item in raw_journal:
                try:
                    pair_journal.append(_json.loads(item))
                except Exception:
                    pass
        except Exception:
            pass
        pair_thread = []
        active_thread_id = pair_state.get("active_thread_id", "")
        if active_thread_id:
            try:
                msg_keys = r.zrevrange(f"msg:thread:{active_thread_id}", 0, 7)
                for msg_key in reversed(msg_keys):
                    raw_msg = r.get(msg_key)
                    if not raw_msg:
                        continue
                    try:
                        pair_thread.append(_json.loads(raw_msg))
                    except Exception:
                        pass
            except Exception:
                pass

        focus_by_char = {cid: pair_state.get(f"focus_{cid}", "") for cid in pair_ids}
        action_by_char = {cid: pair_state.get(f"action_{cid}", "") for cid in pair_ids}
        category_by_char = {cid: pair_state.get(f"category_{cid}", "") for cid in pair_ids}
        headline = (
            pair_state.get("current_topic", "")
            or pair_state.get("shared_goal", "")
            or pair_state.get("last_message_preview", "")
        )
        if not headline and pair_journal:
            headline = pair_journal[-1].get("summary", "")

        try:
            last_message_ts = int(pair_state.get("last_message_ts", 0) or 0)
        except Exception:
            last_message_ts = 0

        pair_story = {
            "pair_ids": pair_ids,
            "headline": headline,
            "shared_goal": pair_state.get("shared_goal", ""),
            "current_topic": pair_state.get("current_topic", ""),
            "open_question": pair_state.get("open_question", ""),
            "last_message_preview": pair_state.get("last_message_preview", ""),
            "last_message_from": pair_state.get("last_message_from", ""),
            "last_message_ts": last_message_ts,
            "active_thread_id": active_thread_id,
            "focus_by_char": focus_by_char,
            "action_by_char": action_by_char,
            "category_by_char": category_by_char,
            "journal": pair_journal,
            "active_thread": pair_thread,
        }

    agency_npcs = []
    for char_id in agency_ids:
        name = AGENCY_CONTACTS.get(char_id, char_id)

        artifacts = []
        if list_artifacts_by_npc:
            try:
                artifacts = list_artifacts_by_npc(char_id, limit=20)
            except Exception:
                pass
        if not artifacts and r:
            try:
                raw = r.lrange(f"npc_artifacts:{char_id}", 0, 19)
                if raw:
                    artifacts = [_json.loads(a) for a in raw if a]
            except Exception:
                pass
        active_artifacts, identity_artifacts = _rank_artifacts_for_pair_story(char_id, artifacts, pair_state)

        inbox = []
        sent_messages = []
        threads = []
        unread = 0
        if get_inbox:
            try:
                inbox = get_inbox(char_id, limit=10)
            except Exception:
                pass
        if not inbox and r:
            try:
                raw = r.lrange(f"npc_messages:{char_id}:inbox", 0, 9)
                if raw:
                    inbox = []
                    for m in raw:
                        try:
                            obj = _json.loads(m)
                            obj["from_char_name"] = obj.pop("from_name", obj.get("from_char_name", ""))
                            inbox.append(obj)
                        except Exception:
                            inbox.append({"body": str(m)[:100]})
                    unread = len(inbox)
            except Exception:
                pass
        if get_active_threads:
            try:
                threads = get_active_threads(char_id, limit=5)
            except Exception:
                pass
        if r:
            try:
                raw_sent = r.lrange(f"npc_messages:{char_id}:sent", -10, -1)
                for m in reversed(raw_sent):
                    try:
                        obj = _json.loads(m)
                        obj["to_char_name"] = obj.get("to_name", obj.get("to_char_name", ""))
                        sent_messages.append(obj)
                    except Exception:
                        sent_messages.append({"body": str(m)[:100]})
            except Exception:
                pass
        if get_unread_count and unread == 0:
            try:
                unread = get_unread_count(char_id)
            except Exception:
                pass

        cognition_state = {}
        if r:
            try:
                cog = r.hgetall(f"npc_cognition:{char_id}")
                if cog:
                    cognition_state = dict(cog)
            except Exception:
                pass

        mood = ""
        if r:
            try:
                mood_raw = r.get(f"npc_mood:{char_id}")
                if mood_raw:
                    mood = mood_raw
            except Exception:
                pass

        decisions = []
        if r:
            try:
                raw_decisions = r.zrevrange(f"npc_decisions:{char_id}", 0, 4)
                for item in raw_decisions:
                    try:
                        decisions.append(_json.loads(item))
                    except Exception:
                        decisions.append({"raw": str(item)[:100]})
            except Exception:
                pass

        llm_logs = []
        if r:
            try:
                raw_logs = r.lrange(f"npc_llm_logs:{char_id}", 0, 29)
                if raw_logs:
                    llm_logs = [_json.loads(log) for log in raw_logs if log]
            except Exception:
                pass

        stats = {}
        if r:
            try:
                raw_stats = r.hgetall(f"npc_stats:{char_id}")
                if raw_stats:
                    stats = dict(raw_stats)
            except Exception:
                pass

        agency_npcs.append({
            "char_id": char_id,
            "name": name,
            "key_label": _key_labels.get(char_id, ""),
            "mood": mood,
            "unread_messages": unread,
            "artifacts": active_artifacts,
            "identity_artifacts": identity_artifacts,
            "inbox": inbox,
            "sent_messages": sent_messages,
            "active_threads": threads,
            "cognition": cognition_state,
            "recent_decisions": decisions,
            "llm_logs": llm_logs,
            "stats": stats,
            "story_focus": pair_story.get("focus_by_char", {}).get(char_id, ""),
            "story_action": pair_story.get("action_by_char", {}).get(char_id, ""),
            "story_category": pair_story.get("category_by_char", {}).get(char_id, ""),
            "last_updated": int(_time.time()),
        })

    return {
        "status": "ok",
        "agency_npcs": agency_npcs,
        "pair_story": pair_story,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

