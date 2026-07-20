#!/usr/bin/env python3
"""
Shadow NPC cognition loop — runs the NPC agent in SHADOW_MODE.
Replaces npc_agent.main() with shadow-aware redis access and mock LLM.

All cognition is intent-only: no messages, artifacts, institutions, or
production writes. All state is namespaced under shadow:<SHADOW_INSTANCE_ID>.
"""
import logging
import os
import sys
import time
import signal
import threading
from datetime import datetime, timezone

# Shadow context on path
sys.path.insert(0, "/app")

# MUST configure shadow mode BEFORE patching call_llm, because SHADOW global
# is set by configure() and the patch checks it.
from npc_shadow_mode import configure, get_provider, shadow_key, _model_call_count
from npc_redis_helpers import get_shadow_redis
from npc_llm_client import call_llm as _original_call_llm
import npc_llm_client


# Monkey-patch call_llm so SHADOW_MODE redirects to the deterministic mock.
# npc_decisions imports call_llm at module load; this patch must happen before
# the cognition loop starts so decide_action uses the mock transparently.
_shadow_provider = None


def _patched_call_llm(system_prompt, user_prompt, model="", r=None, call_label=""):
    global _shadow_provider
    if _shadow_provider is None:
        _shadow_provider = get_provider()
    if _shadow_provider:
        return _shadow_provider(system_prompt, user_prompt, model, r, call_label)
    return _original_call_llm(system_prompt, user_prompt, model, r, call_label)


npc_llm_client.call_llm = _patched_call_llm

# Now safe to import the rest of the cognition stack
from npc_context import think_about_world
from npc_decisions import decide_action
from npc_actions import execute_decision


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("shadow_npc")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
SHADOW_INSTANCE_ID = os.environ.get("SHADOW_INSTANCE_ID", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis-shadow:6379/0")
TICK_INTERVAL = int(os.environ.get("TICK_INTERVAL", "30"))
MAX_RUNTIME_S = int(os.environ.get("SHADOW_MAX_RUNTIME_S", "86400"))
MAX_TICKS = int(os.environ.get("SHADOW_MAX_TICKS", "10000"))
MAX_MODEL_CALLS = int(os.environ.get("SHADOW_MAX_MODEL_CALLS", "5000"))

CONTACTS = {
    "char_001": "Archimedes Prime (Research Division)",
    "char_306": "The Oracle (Seer of Futures)",
    "moderator": "Sean / Federation Moderator",
}

SHUTDOWN = threading.Event()
START_TIME = time.time()
TICK_COUNT = 0
CALL_COUNT = 0
LAST_LOG_TIME = [0]


def log_progress(msg):
    now = time.time()
    if now - LAST_LOG_TIME[0] >= 60:
        elapsed = now - START_TIME
        logger.info(
            "%s | ticks=%d calls=%d elapsed=%ds runtime_limit=%ds",
            msg, TICK_COUNT, CALL_COUNT, int(elapsed), MAX_RUNTIME_S,
        )
        LAST_LOG_TIME[0] = now


def signal_handler(sig, frame):
    logger.info("Received signal %d — initiating graceful shutdown...", sig)
    SHUTDOWN.set()


def main():
    global TICK_COUNT, CALL_COUNT

    logger.info("Shadow NPC starting — ID: %s, Name: %s, Instance: %s",
                CHAR_ID, NPC_NAME, SHADOW_INSTANCE_ID)

    if not CHAR_ID:
        logger.error("CHAR_ID env var is required")
        return

    if os.environ.get("SHADOW_MODE", "").lower() != "true":
        logger.error("SHADOW_MODE is not enabled — refusing to run")
        return

    # Configure shadow mode (reads env vars SHADOW_MODE, SHADOW_INSTANCE_ID, etc.)
    configure()

    # Connect to shadow Redis
    r = get_shadow_redis(REDIS_URL, None)
    logger.info("Connected to shadow Redis: %s", REDIS_URL)

    # Record observation metadata
    r.set(shadow_key("observation_start"), datetime.now(timezone.utc).isoformat())
    r.set(shadow_key("observation_char_id"), CHAR_ID)
    r.set(shadow_key("observation_npc_name"), NPC_NAME)
    r.set(shadow_key("observation_status"), "running")

    # Bounded signal handling
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(
        "Starting shadow cognition loop — max_runtime=%ds max_ticks=%d max_calls=%d tick_interval=%ds",
        MAX_RUNTIME_S, MAX_TICKS, MAX_MODEL_CALLS, TICK_INTERVAL,
    )

    while not SHUTDOWN.is_set():
        # Check time/bound limits
        elapsed = time.time() - START_TIME
        if elapsed >= MAX_RUNTIME_S:
            logger.info("Runtime limit reached (%ds >= %ds) — stopping", elapsed, MAX_RUNTIME_S)
            break
        if TICK_COUNT >= MAX_TICKS:
            logger.info("Tick limit reached (%d >= %d) — stopping", TICK_COUNT, MAX_TICKS)
            break
        if CALL_COUNT >= MAX_MODEL_CALLS:
            logger.info("Model call limit reached (%d >= %d) — stopping", CALL_COUNT, MAX_MODEL_CALLS)
            break

        try:
            TICK_COUNT += 1

            # Cognition: think -> decide -> execute (shadow-safe)
            context = think_about_world(r)
            decision = decide_action(context, r)
            outcome = execute_decision(decision, r, CONTACTS)

            # Track model calls (from the mock provider via npc_shadow_mode)
            import npc_shadow_mode as sm
            CALL_COUNT = sm._model_call_count

            logger.debug(
                "[%s] tick=%d decision=%s outcome=%s calls=%d",
                CHAR_ID, TICK_COUNT,
                decision.get("action", "none"),
                outcome.get("outcome", "none") if isinstance(outcome, dict) else str(outcome)[:40],
                CALL_COUNT,
            )

            log_progress(f"[{CHAR_ID}] tick {TICK_COUNT}")

        except Exception as e:
            logger.error("Tick %d failed: %s", TICK_COUNT, e, exc_info=True)

        time.sleep(TICK_INTERVAL)

    # Final status record
    elapsed = time.time() - START_TIME
    final_status = "completed" if not SHUTDOWN.is_set() else "interrupted"

    logger.info(
        "Shadow observation ended — status=%s ticks=%d calls=%d elapsed=%.1fs",
        final_status, TICK_COUNT, CALL_COUNT, elapsed,
    )
    r.set(shadow_key("observation_end"), datetime.now(timezone.utc).isoformat())
    r.set(shadow_key("observation_status"), final_status)
    r.set(shadow_key("observation_ticks"), str(TICK_COUNT))
    r.set(shadow_key("observation_calls"), str(CALL_COUNT))
    r.set(shadow_key("observation_elapsed_s"), str(int(elapsed)))

    logger.info("Observation metadata written to shadow Redis — goodbye")
    return 0


if __name__ == "__main__":
    main()