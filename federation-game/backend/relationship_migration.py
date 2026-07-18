"""One-off helper to make existing NPC relationship keys permanent.

Relationship hashes are permanent (no TTL). A legacy 7-day TTL may still be
attached to keys that predate the permanent-lifetime contract. This helper
removes those TTLs by calling ``PERSIST`` on every ``npc_relationships:*`` key.

Design notes:
* Pure and dependency-injected: the caller passes a Redis-compatible client.
* No Redis connection is opened here; no code runs at import time.
* Uses cursor-based ``scan_iter`` so it is safe for large key spaces.
* Only keys matching ``npc_relationships:*`` are touched; field values are
  never read, modified, or deleted.
"""

REL_KEY_PREFIX = "npc_relationships:"


def _normalize_key(key):
    """Normalize a yielded scan key into a logical str.

    Raises TypeError for unsupported key types rather than silently coercing.
    """
    if isinstance(key, bytes):
        return key.decode("utf-8")
    if isinstance(key, str):
        return key
    raise TypeError(
        f"Unsupported relationship key type {type(key).__name__!r}; "
        "expected str or bytes"
    )


def persist_relationship_keys(client) -> int:
    """Remove TTLs from all existing ``npc_relationships:*`` keys.

    Args:
        client: A Redis-compatible client exposing ``scan_iter(match=...)``
            and ``persist(name)``.

    Returns:
        Number of keys whose TTL was actually removed (count of ``persist``
        calls that returned a truthy/``1`` result). Keys that were already
        permanent (``persist`` returns 0/``False``) are not counted.
    """
    migrated = 0
    seen = set()
    for raw_key in client.scan_iter(match=f"{REL_KEY_PREFIX}*"):
        name = _normalize_key(raw_key)
        if name in seen:
            continue
        seen.add(name)
        # Allow scan/persist exceptions to propagate; do not misreport.
        if client.persist(name):
            migrated += 1
    return migrated
