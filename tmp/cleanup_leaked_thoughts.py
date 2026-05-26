#!/usr/bin/env python3
"""One-time cleanup: purge NPC thoughts that contain leaked prompt instructions.

Scans all npc_thoughts:* keys in Redis and removes entries where the
'thought' field contains prompt-generation instruction phrases (the bug
where small models echoed the system prompt instead of generating a thought).

Run once on the VPS after deploying the fixed npc_autonomy.py.
"""

import json
import sys

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. pip install redis")
    sys.exit(1)

LEAK_MARKERS = [
    "we need to generate",
    "generate a single internal thought",
    "no quotes or attribution",
    "just the thought itself",
    "be specific and in-character",
    "this character would have right now",
    "reflect their personality",
    "do not use quotes or attribution",
    "what is on your mind right now",
    "produce a single internal thought",
    "roleplay as",
    "as a language model",
    "as an ai",
    "1-2 sentences",
]


def is_leaked(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(marker in lower for marker in LEAK_MARKERS)


def main():
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    if not r.ping():
        print("ERROR: Cannot connect to Redis")
        sys.exit(1)

    # Find all npc_thoughts:* keys
    keys = list(r.scan_iter(match="npc_thoughts:*"))
    print(f"Found {len(keys)} npc_thoughts:* keys")

    total_scanned = 0
    total_purged = 0

    for key in keys:
        # Get all entries (scored set)
        entries = r.zrange(key, 0, -1, withscores=True)
        for entry_json, score in entries:
            total_scanned += 1
            try:
                entry = json.loads(entry_json)
                thought_text = entry.get("thought", "")
                if is_leaked(thought_text):
                    # Remove this specific entry from the sorted set
                    r.zrem(key, entry_json)
                    total_purged += 1
                    char_name = entry.get("char_name", "unknown")
                    print(f"  PURGED: {key} | {char_name} | {thought_text[:80]}...")
            except (json.JSONDecodeError, AttributeError):
                continue

    print(f"\nDone. Scanned: {total_scanned} | Purged: {total_purged}")


if __name__ == "__main__":
    main()
