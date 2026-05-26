#!/usr/bin/env python3
"""
Redis helper for host-based monitoring scripts.
Replaces the Python `redis` module with subprocess calls to
`docker exec federation-game-redis-1 redis-cli`, because Redis
is not exposed on a host port — only accessible via Docker exec.

Matches the existing Tier 1 monitor.py access pattern.
"""

import subprocess
import time

_REDIS_CLI = ["docker", "exec", "federation-game-redis-1", "redis-cli"]
_TIMEOUT = 15


def _run(*args):
    """Run a redis-cli command, return (stdout_str, returncode)."""
    try:
        result = subprocess.run(
            _REDIS_CLI + [str(a) for a in args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", 1
    except FileNotFoundError:
        # docker not found — try alternate name
        alt = ["docker", "exec", "federation-game-redis-1", "redis-cli"]
        try:
            result = subprocess.run(
                alt + [str(a) for a in args],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            return result.stdout.strip(), result.returncode
        except Exception:
            return "", 1
    except Exception:
        return "", 1


# ── Key-Value ──


def redis_get(key):
    """GET key — returns value string or None."""
    out, rc = _run("GET", key)
    if rc == 0 and out and out != "(nil)":
        return out
    return None


def redis_set(key, value):
    """SET key value."""
    _run("SET", key, str(value))


# ── Hash ──


def redis_hgetall(key):
    """HGETALL key — returns dict. Output is alternating field/value lines."""
    out, rc = _run("HGETALL", key)
    if rc != 0 or not out or out == "(empty list or set)":
        return {}
    parts = out.split("\n")
    result = {}
    i = 0
    while i < len(parts) - 1:
        f = parts[i].strip()
        v = parts[i + 1].strip()
        if f:
            result[f] = v
        i += 2
    return result


def redis_hset(key, field, value):
    """HSET key field value (single field)."""
    _run("HSET", key, str(field), str(value))


def redis_hset_map(key, mapping):
    """HSET key multiple fields from a dict."""
    if not mapping:
        return
    args = ["HSET", key]
    for k, v in mapping.items():
        args.append(str(k))
        args.append(str(v))
    _run(*args)


def redis_hget(key, field):
    """HGET key field — returns value string or None."""
    out, rc = _run("HGET", key, str(field))
    if rc == 0 and out and out != "(nil)":
        return out
    return None


# ── Scan ──


def redis_scan_iter(pattern):
    """SCAN for keys matching pattern — returns list of key names."""
    cursor = "0"
    keys = []
    while True:
        out, rc = _run("SCAN", cursor, "MATCH", pattern, "COUNT", "200")
        if rc != 0 or not out:
            break
        lines = out.split("\n")
        cursor = lines[0].strip() if lines else "0"
        if len(lines) > 1:
            for k in lines[1:]:
                k = k.strip()
                if k:
                    keys.append(k)
        if cursor == "0":
            break
    return keys


# ── TTL ──


def redis_ttl(key):
    """TTL key — returns integer seconds, -1 if no expiry, -2 if missing."""
    out, rc = _run("TTL", key)
    if rc == 0 and out:
        try:
            return int(out)
        except ValueError:
            pass
    return -2


# ── Delete ──


def redis_del(key):
    """DEL key."""
    _run("DEL", key)


# ── Exists ──


def redis_exists(key):
    """EXISTS key — returns True if key exists."""
    out, rc = _run("EXISTS", key)
    if rc == 0 and out:
        try:
            return int(out) > 0
        except ValueError:
            pass
    return False
