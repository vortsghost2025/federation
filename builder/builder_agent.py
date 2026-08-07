"""
Federation Builder Agent — Stage 2 core.



Runs periodically (e.g. via a background process) and:

1. Loads any new events from `builder/events/` that have a timestamp newer
   than the stored `stats.last_event_ts`.
2. Updates the `stats.events_processed` counter.
3. Applies simple heuristics to decide whether to draft a new capability
   request. Currently only one rule is implemented:

   *If no `area_found` event occurred in the last 30 minutes, draft a
   request to create a new exploratory area.*

The draft is stored in `BuilderState` as a pending request with a
human‑readable rationale and a list of recent events (as evidence).

The agent does **not** auto‑approve or auto‑execute any request – the
operator must approve via the CLI (`builder_cli.sh`) or the HTTP RPC.
"""

from __future__ import annotations

import sys, os
sys.path.append('/docker/federation-architect')

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from builder.state import BuilderState
from builder.redis_discovery import get_redis

logger = logging.getLogger("federation.builder.agent")

# Configuration constants (could be env‑overridden later)
EVENTS_DIR = os.getenv("BUILDER_EVENTS_DIR", "/docker/federation-architect/builder/events")
STATE_PATH = os.getenv("BUILDER_STATE_PATH", "/docker/federation-architect/builder/state.json")
NPC_IDS = os.getenv("BUILDER_NPC_IDS", "char_001,char_306").split(",")
POLL_INTERVAL = int(os.getenv("BUILDER_POLL_INTERVAL", "5"))  # seconds

# Simple rule parameters
AREA_IDLE_SECONDS = int(os.getenv("BUILDER_AREA_IDLE_SECONDS", "1800"))  # 30 min


def _now_ts() -> float:
    return time.time()


def _load_new_events(state: BuilderState) -> List[Dict[str, Any]]:
    """Read JSONL files from EVENTS_DIR newer than last_event_ts.

    Returns a list of event dicts sorted by `ts` ascending.
    """
    last_ts = state.stats().get("last_event_ts", 0.0)
    events: List[Dict[str, Any]] = []
    events_path = Path(EVENTS_DIR)
    if not events_path.is_dir():
        logger.warning("events dir %s missing", EVENTS_DIR)
        return []
    for file in sorted(events_path.glob("events-*.jsonl")):
        try:
            with file.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ev_ts = float(ev.get("ts", 0.0))
                    if ev_ts > last_ts:
                        events.append(ev)
        except OSError as exc:
            logger.error("failed reading %s: %s", file, exc)
    events.sort(key=lambda e: e.get("ts", 0.0))
    # Update state stats for processed events
    if events:
        state._data["stats"]["last_event_ts"] = events[-1]["ts"]
        state._data["stats"]["events_processed"] = (
            state._data["stats"].get("events_processed", 0) + len(events)
        )
        state.save_if_dirty()
    return events


def _has_recent_area_found(events: List[Dict[str, Any]]) -> bool:
    """Return True if any `area_found` event within AREA_IDLE_SECONDS.
    """
    cutoff = _now_ts() - AREA_IDLE_SECONDS
    for ev in reversed(events):  # newest first
        if ev.get("action") == "area_found" and ev.get("ts", 0) > cutoff:
            return True
        if ev.get("ts", 0) < cutoff:
            break
    return False


def _draft_create_area(state: BuilderState, evidence: List[Dict[str, Any]]) -> None:
    """Create a pending capability request draft for a new area.

    The draft uses `requester_id="builder"` and a placeholder title.
    The actual `capability_key` is "create_area" – the work‑loop will
    handle it like any NPC request.
    """
    draft_id = f"draft_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    draft = {
        "id": draft_id,
        "kind": "capability_request",
        "created_at": now_iso,
        "rationale": "No area founded in the last 30 minutes – suggest expanding the map.",
        "evidence": evidence[-5:],  # last few events for context
        "proposed_action": {
            "capability_key": "create_area",
            "title": "Explore a new frontier",
            "objective": "Add a novel area to enrich the world",
            "requested_change": "Create a fresh area with unique identifier",
        },
        "status": "pending",
    }
    state.add_pending(draft)
    logger.info("drafted new area creation request %s", draft_id)


# Degradation / runway thresholds
DEGRADATION_THRESHOLDS = {
    "stability": {"min": 60, "label": "Stability"},
    "resource_abundance": {"min": 50, "label": "Resource Abundance"},
    "morale": {"min": 55, "label": "Morale"},
    "tension_level": {"max": 60, "label": "Tension Level"},
    "threat_level": {"max": 40, "label": "Threat Level"},
    "anomaly_activity": {"max": 30, "label": "Anomaly Activity"},
}


def _load_world_state(redis_client) -> Dict[str, Any]:
    try:
        data = redis_client.hgetall("world_state")
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val_str = v.decode("utf-8") if isinstance(v, bytes) else v
                try:
                    result[key] = int(float(val_str))
                except (ValueError, TypeError):
                    result[key] = val_str
            return result
    except Exception as exc:
        logger.warning("world_state read failed: %s", exc)
    return {}


def _check_degradation(state: BuilderState, world_state: Dict[str, Any], redis_client) -> None:
    degraded: List[str] = []
    for key, cfg in DEGRADATION_THRESHOLDS.items():
        val = world_state.get(key)
        if val is None:
            continue
        if "min" in cfg and val < cfg["min"]:
            degraded.append(f"{cfg['label']}={val}")
        elif "max" in cfg and val > cfg["max"]:
            degraded.append(f"{cfg['label']}={val}")
    if degraded:
        draft_id = f"draft_degrad_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        evidence = [
            {"source": "world_state", "metrics": world_state},
            {"degraded_metrics": degraded},
        ]
        draft = {
            "id": draft_id,
            "kind": "capability_request",
            "created_at": now_iso,
            "rationale": f"Degradation/runway metrics elevated ({', '.join(degraded)}). Suggest stabilization.",
            "evidence": evidence,
            "proposed_action": {
                "capability_key": "stabilize_infrastructure",
                "title": "Stabilize critical infrastructure",
                "objective": "Address elevated degradation and runway drift before cascade failure",
                "requested_change": "Initiate infrastructure repair and resource rebalancing",
            },
            "status": "pending",
        }
        state.add_pending(draft)
        logger.info("drafted degradation/stabilization request %s (metrics: %s)", draft_id, ", ".join(degraded))


def run_once() -> None:
    redis_client = get_redis()
    if redis_client is None:
        logger.error("Redis client could not be discovered – abort")
        return
    # Load persisted state
    state = BuilderState(STATE_PATH)
    # Degradation / runway rule (autonomous) – always evaluate
    world_state = _load_world_state(redis_client)
    if world_state:
        _check_degradation(state, world_state, redis_client)
    # Pull new events from files (decisions only – builder does not read redis directly)
    events = _load_new_events(state)
    if not events:
        logger.debug("no new events")
    else:
        # Area rule
        if not _has_recent_area_found(events):
            _draft_create_area(state, events)
        else:
            logger.debug("recent area_found present – no draft needed")


def main() -> None:
    logger.info("Builder agent started (poll=%ss, idle=%ss)", POLL_INTERVAL, AREA_IDLE_SECONDS)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("builder iteration failed")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
