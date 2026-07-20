#!/usr/bin/env python3
"""
Persistent 24-hour shadow observation runner.
Runs the NPC cognition loop with SHADOW_MODE=true, exercising real decision
making via the deterministic mock provider. All output is intent-only;
no external operations, no production writes.
"""
import os
import sys
import time
import json
import signal
import threading
from datetime import datetime, timezone

# Ensure shadow context is on path
sys.path.insert(0, "/app")

from npc_shadow_mode import get_shadow_redis, shadow_key, record_intent
from npc_agent import run_npc_agent, init_shadow_mode


SHUTDOWN = threading.Event()
START_TIME = time.time()
START_TICK = 0
TICK_COUNT = 0
CALL_COUNT = 0
LAST_REPORT = [0]

def signal_handler(sig, frame):
    print(f"[shadow-obs] Received signal {sig}, initiating graceful shutdown...", flush=True)
    SHUTDOWN.set()

def tick_loop(char_id: str, npc_name: str):
    """Run the NPC cognition loop until shutdown or tick limit reached."""
    global TICK_COUNT, CALL_COUNT, START_TICK, LAST_REPORT

    config = {
        "char_id": char_id,
        "npc_name": npc_name,
        "tick": TICK_COUNT,
        "provider": os.getenv("SHADOW_PROVIDER", "mock"),
    }

    try:
        result = run_npc_agent(config)
    except Exception as e:
        result = {"error": str(e), "type": "exception"}

    TICK_COUNT += 1
    if result.get("model_calls"):
        CALL_COUNT += result.get("model_calls", 0)

    # Log progress every 60 seconds
    elapsed = time.time() - START_TIME
    if elapsed - LAST_REPORT[0] >= 60:
        print(
            f"[shadow-obs] tick={TICK_COUNT} calls={CALL_COUNT} "
            f"elapsed={elapsed:.0f}s runtime_limit={os.getenv('SHADOW_MAX_RUNTIME_S','?')}s",
            flush=True,
        )
        LAST_REPORT[0] = elapsed

    return result


def main():
    char_id = os.getenv("CHAR_ID", "char_001")
    npc_name = os.getenv("NPC_NAME", "Shadow NPC")
    max_runtime = int(os.getenv("SHADOW_MAX_RUNTIME_S", "86400"))  # 24h default
    max_ticks = int(os.getenv("SHADOW_MAX_TICKS", "10000"))
    max_calls = int(os.getenv("SHADOW_MAX_MODEL_CALLS", "5000"))

    print(f"[shadow-obs] Starting 24h shadow observation", flush=True)
    print(f"[shadow-obs] char_id={char_id} npc_name={npc_name}", flush=True)
    print(f"[shadow-obs] max_runtime={max_runtime}s max_ticks={max_ticks} max_calls={max_calls}", flush=True)

    init_shadow_mode()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Prime the shadow Redis with observation metadata
    try:
        r = get_shadow_redis(
            os.getenv("REDIS_URL", "redis://redis-shadow:6379/0"),
            None
        )
        r.set(shadow_key("observation_start"), datetime.now(timezone.utc).isoformat())
        r.set(shadow_key("observation_char_id"), char_id)
        r.set(shadow_key("observation_status"), "running")
        print(f"[shadow-obs] Shadow Redis connected, observation metadata written", flush=True)
    except Exception as e:
        print(f"[shadow-obs] Shadow Redis connection failed: {e}", flush=True)
        # Continue — shadow mode still works without Redis persistence

    # Main cognition loop
    while not SHUTDOWN.is_set():
        elapsed = time.time() - START_TIME
        runtime_exceeded = elapsed >= max_runtime
        tick_exceeded = TICK_COUNT >= max_ticks
        call_exceeded = CALL_COUNT >= max_calls

        if runtime_exceeded:
            print(f"[shadow-obs] Runtime limit reached ({elapsed:.0f}s >= {max_runtime}s)", flush=True)
            break
        if tick_exceeded:
            print(f"[shadow-obs] Tick limit reached ({TICK_COUNT} >= {max_ticks})", flush=True)
            break
        if call_exceeded:
            print(f"[shadow-obs] Call limit reached ({CALL_COUNT} >= {max_calls})", flush=True)
            break

        tick_loop(char_id, npc_name)
        time.sleep(0.5)  # Brief pause between ticks

    # Final status
    elapsed = time.time() - START_TIME
    final_status = "completed" if not SHUTDOWN.is_set() else "interrupted"
    print(
        f"[shadow-obs] Observation ended: status={final_status} "
        f"ticks={TICK_COUNT} calls={CALL_COUNT} elapsed={elapsed:.1f}s",
        flush=True,
    )

    try:
        r = get_shadow_redis(os.getenv("REDIS_URL", "redis://redis-shadow:6379/0"), None)
        r.set(shadow_key("observation_end"), datetime.now(timezone.utc).isoformat())
        r.set(shadow_key("observation_status"), final_status)
        r.set(shadow_key("observation_ticks"), str(TICK_COUNT))
        r.set(shadow_key("observation_calls"), str(CALL_COUNT))
        r.set(shadow_key("observation_elapsed_s"), str(round(elapsed, 1)))
    except Exception:
        pass

    print("[shadow-obs] Shadow observation complete. Exiting.", flush=True)


if __name__ == "__main__":
    main()