"""
NPC Agent — runs as an isolated Docker container for a single NPC.

Each container gets its own NVIDIA_API_KEY. The agent:
  - Reads CHAR_ID, NVIDIA_API_KEY, NPC_NAME from env
  - Connects to shared Redis for state/messaging
  - Runs a cognition loop: think -> decide -> act -> report
  - Uses its own key for LLM calls (bypasses the shared pool)

Designed for the first pair: Archimedes Prime (char_001) & The Oracle (char_306).
"""
import logging
import os
import time

import redis

from fourth_wall import _startup_scrub_redis
from npc_decisions import decide_action
from npc_actions import execute_decision, update_mood
from npc_context import think_about_world
from npc_redis_helpers import get_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("npc_agent")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TICK_INTERVAL = int(os.environ.get("TICK_INTERVAL", "30"))

CONTACTS: dict = {}
OPERATOR_ID = "moderator"
OPERATOR_NAME = "Sean / Federation Moderator"


def load_contacts(r):
    global CONTACTS
    CONTACTS = {
        "char_001": "Archimedes Prime (Research Division)",
        "char_306": "The Oracle (Seer of Futures)",
        OPERATOR_ID: OPERATOR_NAME,
    }
    try:
        raw = r.hgetall("npc_agent:contacts")
        if raw:
            CONTACTS.update(dict(raw))
            return
    except Exception:
        pass


def main():
    logger.info("NPC Agent starting — ID: %s, Name: %s", CHAR_ID, NPC_NAME)

    if not CHAR_ID:
        logger.error("CHAR_ID env var is required")
        return

    if not NVIDIA_API_KEY:
        logger.error("NVIDIA_API_KEY env var is not set — agent cannot make LLM calls")
        return

    r = get_redis()
    load_contacts(r)

    _startup_scrub_redis(r, NPC_NAME)

    r.hset("npc_agent:registry", CHAR_ID, f"{NPC_NAME}|started:{int(time.time())}")

    r.set(f"npc_mood:{CHAR_ID}", "awakening")

    logger.info("Starting cognition loop every %ds for %s (%s)", TICK_INTERVAL, NPC_NAME, CHAR_ID)

    tick = 0
    while True:
        try:
            tick += 1
            logger.debug("[%s] Tick %d", CHAR_ID, tick)

            context = think_about_world(r)
            decision = decide_action(context, r)
            execute_decision(decision, r, CONTACTS)

            if tick % 3 == 0:
                update_mood(r)

            try:
                inbox_count = r.llen(f"npc_messages:{CHAR_ID}:inbox")
                r.hset(f"npc_stats:{CHAR_ID}", "unread", str(inbox_count))
            except Exception:
                pass

        except Exception as e:
            logger.error("Tick %d failed: %s", tick, e, exc_info=True)

        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    main()
