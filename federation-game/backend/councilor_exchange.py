"""
Phase 2 councilor-exchange read-only helper (Gate B).

Reads exchange-ledger entries from Redis for the three supported views
(shared / inbox / outbox) and returns them newest-first. This module is
strictly a data accessor:

- No authentication (that is the operator dependency's job, Gate A).
- No HTTP handling (the route belongs to Gate C).
- No Redis connection at module import.
- A Redis client is either injected (for tests/DI) or lazily constructed
  inside the helper via a small accessor.
- LRANGE is the only permitted Redis operation. No writes, expiry, trimming,
  scans, or key enumeration happen here.
- A fixed newest window is returned. Malformed entries in that window are
  counted, never backfilled from older entries.

Key shapes follow COUNCILOR_EXCHANGE_LEDGER_SPEC.md:
- shared:  councilor_exchange:shared
- inbox:   councilor_exchange:{char_id}:inbox
- outbox:  councilor_exchange:{char_id}:outbox

Redis lists are stored oldest -> newest.
"""

import json
import os

# Supported views and councilors (per spec / contract).
SUPPORTED_VIEWS = ("shared", "inbox", "outbox")
SUPPORTED_COUNCILORS = ("char_001", "char_306")
VALID_LIMIT_MIN = 1
VALID_LIMIT_MAX = 200

REDIS_URL_ENV = "REDIS_URL"
REDIS_HOST_ENV = "FEDERATION_REDIS_HOST"
REDIS_PORT_ENV = "FEDERATION_REDIS_PORT"
REDIS_DB_ENV = "FEDERATION_REDIS_DB"


class CouncilorExchangeValidationError(Exception):
    """Raised when helper inputs (view, char_id, limit) are invalid."""


class StoreUnavailableError(Exception):
    """Raised when Redis cannot be reached or returns a store-level error.

    The message is sanitized: it never contains the raw Redis exception text,
    Redis URLs, or credentials. The original exception is preserved via
    exception chaining (``raise StoreUnavailableError(...) from exc``) for
    debugging, but is not rendered to the caller.
    """


def _resolve_key(view: str, char_id: str | None) -> str:
    """Build the Redis key for the given view, validating inputs."""
    if view not in SUPPORTED_VIEWS:
        raise CouncilorExchangeValidationError(
            f"Unsupported view: {view!r}. "
            f"Supported views: {', '.join(SUPPORTED_VIEWS)}"
        )
    if view in ("inbox", "outbox"):
        if not char_id:
            raise CouncilorExchangeValidationError(
                f"char_id is required for view {view!r}"
            )
        if char_id not in SUPPORTED_COUNCILORS:
            raise CouncilorExchangeValidationError(
                f"Unknown councilor: {char_id!r}. "
                f"Supported councilors: {', '.join(SUPPORTED_COUNCILORS)}"
            )
        return f"councilor_exchange:{char_id}:{view}"
    return "councilor_exchange:shared"


def _decode_entry(raw) -> dict:
    """Decode a raw Redis value (bytes or str) into a JSON object.

    Raises CouncilorExchangeValidationError if the entry is malformed
    (invalid UTF-8, not valid JSON, or not a dict). Such entries are counted
    as malformed within the selected window by the caller, never returned.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CouncilorExchangeValidationError("Malformed entry") from exc
    else:
        text = str(raw)
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CouncilorExchangeValidationError("Malformed entry") from exc
    if not isinstance(obj, dict):
        raise CouncilorExchangeValidationError("Malformed entry")
    return obj


def _get_redis_client(injected=None):
    """Return an injected client or lazily build one.

    No connection is attempted at module import. The lazy path reads Redis
    connection settings from the environment only when invoked and no client
    is injected. This avoids touching Redis during import or in isolated
    tests that inject a fake.
    """
    if injected is not None:
        return injected
    try:
        import redis  # local import: no Redis at module load

        # Honor REDIS_URL (the repo-wide convention) when present; this is what
        # the deployment environment sets. Fall back to host/port only if it is
        # missing, so local/test setups without REDIS_URL still work.
        url = os.environ.get(REDIS_URL_ENV)
        if url:
            return redis.Redis.from_url(url, decode_responses=True)
        host = os.environ.get(REDIS_HOST_ENV, "localhost")
        port = int(os.environ.get(REDIS_PORT_ENV, "6379"))
        db = int(os.environ.get(REDIS_DB_ENV, "0"))
        return redis.Redis(host=host, port=port, db=db, decode_responses=True)
    except Exception as exc:  # pragma: no cover - defensive
        raise StoreUnavailableError("Exchange ledger store is unavailable") from exc


def get_entries(
    view: str,
    char_id: str | None = None,
    limit: int = 50,
    redis_client=None,
) -> dict:
    """Read the newest ``limit`` entries for a view, newest-first.

    Returns a dict with keys:
      - entries: list of valid entry dicts, newest first
      - count: number of valid entries returned
      - invalid_count: number of malformed entries within the selected window
      - partial: bool, True when invalid_count > 0

    ``limit`` is clamped/validated to 1..200. The helper reads only the
    newest ``limit`` stored entries (LRANGE with a negative start) and never
    fetches older entries to replace malformed ones.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise CouncilorExchangeValidationError(
            f"limit must be an integer in {VALID_LIMIT_MIN}..{VALID_LIMIT_MAX}"
        )
    if limit < VALID_LIMIT_MIN or limit > VALID_LIMIT_MAX:
        raise CouncilorExchangeValidationError(
            f"limit must be in {VALID_LIMIT_MIN}..{VALID_LIMIT_MAX}"
        )

    key = _resolve_key(view, char_id)

    client = _get_redis_client(redis_client)

    try:
        # LRANGE is the only permitted Redis command. Negative start reads
        # the newest `limit` entries; Redis returns them oldest -> newest.
        raw_entries = client.lrange(key, -limit, -1)
    except Exception as exc:
        raise StoreUnavailableError("Exchange ledger store is unavailable") from exc

    valid_entries = []
    invalid_count = 0
    for raw in raw_entries:
        try:
            valid_entries.append(_decode_entry(raw))
        except CouncilorExchangeValidationError:
            invalid_count += 1

    # raw_entries is oldest -> newest; reverse for newest-first.
    valid_entries.reverse()

    return {
        "entries": valid_entries,
        "count": len(valid_entries),
        "invalid_count": invalid_count,
        "partial": invalid_count > 0,
    }
