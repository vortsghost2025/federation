#!/usr/bin/env python3
"""
Federation Game Worker — Autonomous tick engine with Apprise notifications.
Runs game ticks every 60s, captures significant events, and broadcasts
notifications via Apprise API.
"""

import os
import sys
import time
import json
import logging
import signal

import redis
import requests

# ── Configuration ──────────────────────────────────────────
TICK_INTERVAL = int(os.getenv("TICK_INTERVAL", "60"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6432/0")
APPRISE_URL = os.getenv("APPRISE_URL", "http://apprise:8000")

# ── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("worker")

# ── Redis ──────────────────────────────────────────────────
r = redis.from_url(REDIS_URL, decode_responses=True)

# ── State ──────────────────────────────────────────────────
tick_count = 0
last_tick_time = 0
running = True


def handle_signal(signum, frame):
    global running
    log.info(f"Received signal {signum}, shutting down...")
    running = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


# ── Apprise Notification ───────────────────────────────────


def send_notification(title, body):
    """Send a notification via Apprise API."""
    try:
        resp = requests.post(
            f"{APPRISE_URL}/notify/game-events",
            json={"title": title, "body": body},
            timeout=5,
        )
        if resp.status_code in (200, 204):
            log.info(f"Notification sent: {title}")
        else:
            log.warning(f"Notification failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        log.warning(f"Apprise unreachable: {e}")


def check_significant_events(history_data, political_data):
    """Check tick responses for Tier-1 significant events.
    Returns list of (emoji, title, detail) tuples."""
    events = []

    # ── Era transition ─────────────────────────────────
    details = history_data.get("details") or {}
    if details.get("era_changed"):
        era = details.get("era", "unknown")
        events.append(
            (
                "\U0001f3db\ufe0f",
                "Era Transition",
                f"The federation has entered the {era}",
            )
        )

    # ── Coherence collapse ─────────────────────────────
    coherence = details.get("coherence")
    if coherence is not None and coherence < 0.3:
        events.append(
            (
                "\u26a0\ufe0f",
                "Coherence Collapse",
                f"Reality coherence at {coherence:.2f} — stability failing",
            )
        )

    # ── Rival hostile actions ──────────────────────────
    rival_actions = details.get("rival_actions") or {}
    hostile_keywords = (
        "incursion",
        "espionage",
        "embargo",
        "attack",
        "raid",
        "sabotage",
        "hostile",
        "invasion",
    )
    for rival, action_data in rival_actions.items():
        action_text = (
            json.dumps(action_data).lower()
            if isinstance(action_data, dict)
            else str(action_data).lower()
        )
        if any(kw in action_text for kw in hostile_keywords):
            events.append(
                (
                    "\u2694\ufe0f",
                    "Rival Hostile Action",
                    f"{rival}: {json.dumps(action_data)[:120]}",
                )
            )
            break

    # ── History branch point ───────────────────────────
    event_obj = details.get("event") or {}
    if event_obj.get("branch_point"):
        event_name = event_obj.get("name", "Unknown Event")
        events.append(
            (
                "\U0001f500",
                "Timeline Branch Point",
                f"{event_name} — the timeline has diverged",
            )
        )

    # ── Chaosbringer activity ──────────────────────────
    chaosbringer = details.get("chaosbringer_report") or {}
    if isinstance(chaosbringer, dict) and chaosbringer.get("active"):
        agent = chaosbringer.get("agent_name", "Unknown Agent")
        action = chaosbringer.get("action", "unknown activity")
        events.append(
            (
                "\U0001f525",
                "Chaosbringer Activity",
                f"{agent}: {action}",
            )
        )

    # ── Laws passed ────────────────────────────────────
    if political_data and isinstance(political_data, list):
        for law in political_data[:3]:
            law_name = law.get("law_name", law.get("name", "Unknown Law"))
            events.append(("\u2696\ufe0f", "Law Passed", f"{law_name}"))

    return events


def check_npc_broadcasts():
    """Check Redis npc_broadcast_events for high-significance
    events since last tick."""
    events = []
    try:
        now = time.time()
        window = TICK_INTERVAL + 5
        recent = r.zrangebyscore("npc_broadcast_events", now - window, now)
        for raw in recent:
            try:
                evt = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if evt.get("significance", 0) >= 0.8 and evt.get("visibility") == "public":
                char_name = evt.get("source_char_name", "Unknown")
                desc = evt.get("description", "")
                events.append(
                    ("\U0001f514", "Critical NPC Decision", f"{char_name}: {desc}")
                )
    except Exception as e:
        log.warning(f"Failed to query npc_broadcast_events: {e}")
    return events


def build_notification(game_events, npc_events):
    """Combine events into a single notification. Max 1 per tick."""
    all_events = game_events + npc_events
    if not all_events:
        return None

    all_events = all_events[:5]

    title = (
        f"\U0001f30c Federation Update "
        f"({len(all_events)} event{'s' if len(all_events) > 1 else ''})"
    )

    lines = []
    for emoji, evt_title, detail in all_events:
        lines.append(f"{emoji} **{evt_title}**: {detail}")

    body = "\n".join(lines)
    return title, body


# ── Tick Engine ────────────────────────────────────────────


def run_tick():
    """Execute one game tick: advance NPC, political, and
    history-arc systems."""
    global tick_count
    tick_count += 1
    log.info(f"Tick #{tick_count} starting...")

    history_data = {}
    political_data = []

    endpoints = [
        ("/npcs/advance-turn", "NPC system"),
        ("/political/process-turn", "Political engine"),
        ("/history-arc/advance", "History arc"),
    ]

    for path, name in endpoints:
        try:
            resp = requests.post(
                f"{BACKEND_URL}{path}",
                json={},
                timeout=30,
            )
            status = resp.status_code
            log.info(f"  {name}: {status}")

            if status == 200:
                try:
                    data = resp.json()
                    if path == "/history-arc/advance":
                        history_data = data
                    elif path == "/political/process-turn":
                        political_data = data.get("details") or []
                except Exception:
                    pass
            elif status >= 400:
                log.warning(f"  {name} error {status}: {resp.text[:100]}")

        except requests.exceptions.ConnectionError:
            log.error(f"  {name}: backend unreachable")
        except requests.exceptions.Timeout:
            log.error(f"  {name}: timeout (30s)")
        except Exception as e:
            log.error(f"  {name}: {e}")

    # ── Auto-save ──────────────────────────────────────
    try:
        resp = requests.post(
            f"{BACKEND_URL}/state/save",
            json={"snapshot_type": "auto"},
            timeout=10,
        )
        log.info(f"  Auto-save: {resp.status_code}")
    except Exception as e:
        log.warning(f"  Auto-save failed: {e}")

    # ── Publish tick to Redis ──────────────────────────
    try:
        r.publish(
            "federation:updates",
            json.dumps(
                {
                    "event": "game:tick",
                    "tick": tick_count,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ),
        )
        r.hset(
            "worker:status",
            mapping={
                "last_tick": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tick_count": str(tick_count),
                "backend_url": BACKEND_URL,
                "enabled": "1",
            },
        )
    except Exception as e:
        log.warning(f"Redis publish failed: {e}")

    # ── Check for significant events and notify ────────
    try:
        game_events = check_significant_events(history_data, political_data)
        npc_events = check_npc_broadcasts()
        notification = build_notification(game_events, npc_events)
        if notification:
            title, body = notification
            send_notification(title, body)
            log.info(f"  Events detected: {len(game_events + npc_events)}")
        else:
            log.info("  No significant events this tick")
    except Exception as e:
        log.warning(f"Event detection failed: {e}")


# ── Health check ───────────────────────────────────────────


def health_check():
    """Report worker health for Docker HEALTHCHECK."""
    try:
        backend_ok = (
            requests.get(f"{BACKEND_URL}/healthz", timeout=3).status_code == 200
        )
        redis_ok = r.ping()
        return backend_ok and redis_ok
    except Exception:
        return False


# ── Main Loop ──────────────────────────────────────────────


def main():
    log.info("═══ Federation Worker Starting ═══")
    log.info(f"  Backend: {BACKEND_URL}")
    log.info(f"  Redis: {REDIS_URL}")
    log.info(f"  Apprise: {APPRISE_URL}")
    log.info(f"  Tick interval: {TICK_INTERVAL}s")

    for attempt in range(30):
        try:
            resp = requests.get(f"{BACKEND_URL}/healthz", timeout=3)
            if resp.status_code == 200:
                log.info("Backend is ready")
                break
        except Exception:
            pass
        log.info(f"Waiting for backend... (attempt {attempt + 1}/30)")
        time.sleep(2)

    while running:
        try:
            run_tick()
        except Exception as e:
            log.error(f"Tick failed: {e}")

        for _ in range(TICK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    log.info(f"Worker stopped after {tick_count} ticks")


if __name__ == "__main__":
    main()
