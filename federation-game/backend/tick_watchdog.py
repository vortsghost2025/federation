"""Redis-backed watchdog for autonomous simulation ticks."""
import logging
import os
import time
import redis

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_SEC = 1800
LEASE_TTL_SEC = 1800
TICK_TIMEOUT_SEC = 1800

_ACTIVE_TICK_KEY = "fed:watchdog:active_tick"
_ACTIVE_TICK_OWNER_KEY = "fed:watchdog:active_tick_owner"
_LAST_HEARTBEAT_KEY = "fed:watchdog:last_heartbeat"
_STARTED_AT_KEY = "fed:watchdog:started_at"
_TICK_COUNT_KEY = "fed:watchdog:tick_count"

_OWNER = os.environ.get("WATCHDOG_OWNER", "unknown")


def _redis():
    return redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _now():
    return time.time()


def _read_int(key, default=0):
    try:
        value = _redis().get(key)
        return int(value) if value is not None else default
    except Exception:
        return default


def try_start_tick(tick_id):
    """Acquire the watchdog lease for one autonomous tick."""
    r = _redis()
    now = _now()
    try:
        current = r.get(_ACTIVE_TICK_KEY)
        last_heartbeat = r.get(_LAST_HEARTBEAT_KEY)
        started_at = r.get(_STARTED_AT_KEY)

        if current and not current.isdigit():
            current = None
        def _parse_ts(v):
            if not v:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        parsed_hb = _parse_ts(last_heartbeat)
        parsed_sa = _parse_ts(started_at)
        last_heartbeat = str(parsed_hb) if parsed_hb is not None else None
        started_at = str(parsed_sa) if parsed_sa is not None else None

        stale = (
            not last_heartbeat
            or now - float(last_heartbeat) > HEARTBEAT_STALE_SEC
            or now - float(started_at or now) > TICK_TIMEOUT_SEC
        )

        if stale:
            # Clear a stale lease before trying to acquire a new one.
            # Without this, a crashed worker can leave _ACTIVE_TICK_KEY present
            # until TTL expiry, and SET NX will fail even though the lease is stale.
            r.delete(
                _ACTIVE_TICK_KEY,
                _ACTIVE_TICK_OWNER_KEY,
                _LAST_HEARTBEAT_KEY,
                _STARTED_AT_KEY,
                _TICK_COUNT_KEY,
            )
            acquired = bool(r.set(_ACTIVE_TICK_KEY, tick_id, ex=LEASE_TTL_SEC, nx=True))
        else:
            acquired = False
        if acquired:
            r.set(_ACTIVE_TICK_OWNER_KEY, _OWNER, ex=LEASE_TTL_SEC)
            r.set(_LAST_HEARTBEAT_KEY, str(now), ex=LEASE_TTL_SEC)
            r.set(_STARTED_AT_KEY, str(now), ex=LEASE_TTL_SEC)
            r.set(_TICK_COUNT_KEY, str(_read_int(_TICK_COUNT_KEY) + 1), ex=LEASE_TTL_SEC)
            logger.info("Watchdog lease acquired for tick %s", tick_id)
        return acquired
    except Exception as exc:
        logger.warning("Watchdog start failed for tick %s: %s", tick_id, exc)
        return False


def tick_heartbeat():
    """Extend the watchdog lease while a tick is still active."""
    try:
        now = _now()
        r = _redis()
        r.expire(_ACTIVE_TICK_KEY, LEASE_TTL_SEC)
        r.expire(_ACTIVE_TICK_OWNER_KEY, LEASE_TTL_SEC)
        r.set(_LAST_HEARTBEAT_KEY, str(now), ex=LEASE_TTL_SEC)
        r.set(_STARTED_AT_KEY, r.get(_STARTED_AT_KEY) or str(now), ex=LEASE_TTL_SEC)
    except Exception as exc:
        logger.warning("Watchdog heartbeat failed: %s", exc)


def complete_tick(tick_id):
    """Release the watchdog lease when a tick finishes."""
    try:
        r = _redis()
        current = r.get(_ACTIVE_TICK_KEY)
        if current is None or str(current) == str(tick_id):
            r.delete(_ACTIVE_TICK_KEY)
            r.delete(_ACTIVE_TICK_OWNER_KEY)
            r.delete(_LAST_HEARTBEAT_KEY)
            r.delete(_STARTED_AT_KEY)
            r.delete(_TICK_COUNT_KEY)
            logger.info("Watchdog lease released for tick %s", tick_id)
    except Exception as exc:
        logger.warning("Watchdog completion failed for tick %s: %s", tick_id, exc)


def watchdog_status():
    now = _now()
    try:
        r = _redis()
        active_tick = r.get(_ACTIVE_TICK_KEY)
        last_heartbeat = r.get(_LAST_HEARTBEAT_KEY)
        started_at = r.get(_STARTED_AT_KEY)
        def _parse_ts(v):
            if not v:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        parsed_hb = _parse_ts(last_heartbeat)
        parsed_sa = _parse_ts(started_at)
        last_heartbeat = str(parsed_hb) if parsed_hb is not None else None
        started_at = str(parsed_sa) if parsed_sa is not None else None
        last_heartbeat = float(last_heartbeat) if last_heartbeat else None
        started_at = float(started_at) if started_at else None
        return {
            "active": bool(active_tick),
            "active_tick": int(active_tick) if active_tick and active_tick.isdigit() else None,
            "owner": r.get(_ACTIVE_TICK_OWNER_KEY),
            "last_heartbeat": last_heartbeat,
            "heartbeat_age_sec": round(now - last_heartbeat, 2) if last_heartbeat else None,
            "started_at": started_at,
            "age_sec": round(now - started_at, 2) if started_at else None,
            "stale": bool(
                active_tick
                and (
                    last_heartbeat is None
                    or now - last_heartbeat > HEARTBEAT_STALE_SEC
                    or now - started_at > TICK_TIMEOUT_SEC
                )
            ),
            "tick_count": _read_int(_TICK_COUNT_KEY),
            "heartbeat_stale_sec": HEARTBEAT_STALE_SEC,
            "lease_ttl_sec": LEASE_TTL_SEC,
            "tick_timeout_sec": TICK_TIMEOUT_SEC,
        }
    except Exception as exc:
        return {
            "active": False,
            "active_tick": None,
            "owner": None,
            "last_heartbeat": None,
            "heartbeat_age_sec": None,
            "started_at": None,
            "age_sec": None,
            "stale": False,
            "tick_count": 0,
            "heartbeat_stale_sec": HEARTBEAT_STALE_SEC,
            "lease_ttl_sec": LEASE_TTL_SEC,
            "tick_timeout_sec": TICK_TIMEOUT_SEC,
            "error": str(exc),
        }
