# Steward S2 — Read-Only Live Adapters

**Scope:** Read-only observation adapters only. S2 performs **NO Federation-world
writes, NO infrastructure mutations, NO NPC cognition/inbox writes, and NO
Docker/Redis/Postgres/Dagu state changes.** It normalizes live observations
into the same shape the S1 pure engine already consumes.

## Hard boundary (spec Section 5/6, S2 authorization)

- S2 adapters NEVER infer "healthy" from a failed/unavailable read. A failed,
  timed-out, refused, or missing source yields `availability = "unknown"`.
- The S1 pure engine (`steward/schema.py`, `steward/checks/*`, `steward/cli.py`)
  is **untouched** and remains I/O-free.
- Live I/O lives ONLY in `steward/collectors.py` and is reach-able only through
  the S2 CLI (`steward.s2cli`). Adapters take injected runners so tests need no
  network/process.

## Layout

- `steward/adapters/base.py` — `ObservationSnapshot` + adapter contract.
- `steward/adapters/redis_ro.py` — read-only Redis (allowlisted commands only).
- `steward/adapters/http_ro.py` — GET/HEAD only, bounded timeout/size.
- `steward/adapters/docker_ro.py` — info-only Docker (ps/inspect/stats/logs/network/volume).
- `steward/adapters/npc.py` — NPC heartbeat normalization (no cognition).
- `steward/adapters/semantic_loop.py` — pair-workspace normalization.
- `steward/adapters/host.py` — host disk/RAM/DB observation normalization.
- `steward/redact.py` — centralized secret redaction (always on by default).
- `steward/collectors.py` — live I/O runners wired to adapters.
- `steward/s2cli.py` — S2 CLI (`snapshot`, `check-live`).

## Allowlists

- **Redis read commands:** PING, INFO, DBSIZE, SCAN, TYPE, GET, MGET, HGET,
  HMGET, HGETALL, HEXISTS, HLEN, TTL, PTTL, ZCARD, ZRANGE, ZSCORE, SCARD,
  SMEMBERS, LLEN, LRANGE. All writes, EVAL, scripts, pub/sub, MONITOR, and
  unbounded KEYS are refused.
- **HTTP:** GET and HEAD only. Bounded by 5s timeout and 64 KiB response cap.
- **Docker:** `ps`, `inspect`, `stats --no-stream`, `logs --tail`,
  `network inspect`, `volume inspect`. No start/stop/restart/kill/rm/run/exec
  in app containers, no compose mutations.

## CLI

```text
python -m steward.s2cli snapshot <source|all> [--from-file PATH] [--save PATH]
python -m steward.s2cli check-live <id|all> --from-file PATH [--save PATH]
```

- `snapshot` collects a live or frozen read-only observation and prints it as
  redacted JSON (redaction on by default; `--no-redact` for trusted local use).
- `check-live` loads a frozen snapshot and interprets it with the **existing S1
  pure engine** — no new I/O is added to S1.

## Redaction

All snapshot and finding output passes through `steward.redact.redact_value`
before leaving the process. Sensitive keys (password, token, secret, auth,
cookie, private key, connection string, etc.) and credential-shaped strings
(JWT, `redis://user:pass@`, `Bearer …`, private-key PEM, etc.) are masked as
`***REDACTED***`. Tests in `test_s2_adapters.py` assert no secret appears on any
output surface.

## Tests

```text
python -m unittest discover -s tests/unit -p "test_*.py"
```

Covers adapter allowlists, unknown-on-failure, normalization, redaction,
determinism, and the S1-engine purity boundary.

## What S2 is NOT

- Not S3 (no `steward:` Federation-world writes).
- Not S4–S6 (no autonomous action, no scheduling, no escalation).
- Not a Dagu workflow (Dagu stays at 0 workflows).
- Not a push/deploy (local commits only, when authorized).
