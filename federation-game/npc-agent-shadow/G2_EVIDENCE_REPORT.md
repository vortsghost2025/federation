# G2 — Local Container Qualification Evidence Report

**Authorized by:** Sean (local-only qualification, no VPS, no production contact)
**Worktree:** `vortsghost2025-npc-loop-control`  **Branch:** `npc-topic-loop-control`
**Baseline HEAD before G2:** `e76de65edaab925757702e2805ea3a563c56c913` (unchanged by G2)
**Date:** 2026-07-18

## Verdict

```
G2 verdict: PARTIAL PASS — isolation strong, two defense-in-depth gaps found
Compose validation: PASS
Container isolation: PASS
Network isolation: PASS
Credential isolation: PASS
Action-block qualification (dispatcher): PASS
Direct-sink blocking: PARTIAL FAIL (get_redis returns client under shadow)
Private-content exclusion: PASS
Redis namespace isolation: PASS
Failure behavior: PASS (prod URL/cred rejected; provider limit enforced)
Limits enforced: PARTIAL (tick/runtime/model-call/runtime PASS; log-size cap NOT strictly enforced)
Cross-seed exact hashes: PASS
Resource evidence: PASS (observed, not peak-sampled post-hoc)
Teardown: PASS
Post-run tests: PASS (129/129)
Filesystem changes: documented
VPS authorization: NOT AUTHORIZED
Shadow VPS launch authorization: NOT AUTHORIZED
Live deployment authorization: NOT AUTHORIZED
Push authorization: NOT AUTHORIZED
```

## 1. Baseline record

- `git HEAD` before G2 = `e76de65` (unchanged after G2; no runtime commits made).
- Only pre-existing untracked file = `SHADOW_DEPLOY_PLAN.md` (the G0 plan). Confirmed.

## 2. Compose validation (`docker compose -f docker-compose-shadow.yml config`)

All required hardening present:
- `restart: "no"` — PASS
- internal shadow network (`shadow-net`, `internal: true`) — PASS
- no `fed-net` — PASS
- no Docker socket mount — PASS
- no host/project mounts (named volumes only) — PASS
- no production Redis/Postgres URLs (uses `redis://redis-shadow:6379/0`) — PASS
- no API keys (all `KEY`/`TOKEN`/`SECRET` env values empty) — PASS
- non-root user (`shadow`, uid 10001) — PASS
- read-only root filesystem — PASS
- `cap_drop: ALL` — PASS
- `security_opt: no-new-privileges:true` — PASS
- resource limits: memory 256MB, cpu 1.0, pids 128, tick 200, runtime 3600s, model-calls 50, log 10MB — PASS

Build-context note: `build.context` is `./npc-agent`; `qualify_shadow.py` lives in that context.

## 3. Container isolation (inspected via `docker inspect`)

| Property | g2-001 | g2-306 |
|---|---|---|
| Image | federation-game-npc-agent-shadow-001 | federation-game-npc-agent-shadow-306 |
| User | shadow (10001) | shadow (10001) |
| Memory | 256MiB | 256MiB |
| CPU | 1.0 | 1.0 |
| PidsLimit | 128 | 128 |
| CapDrop | ALL | ALL |
| NoNewPriv | true | true |
| Restart | no | no |
| ReadOnlyRootfs | true | true |
| Network | shadow-net (internal) | shadow-net (internal) |

## 4. Network isolation

- Resolver is Docker internal (`127.0.0.11`); only `redis-shadow` resolves locally.
- External egress test (`nc 8.8.8.8 53`) blocked — and `nc` binary absent (extra hardening).
- Not attached to `fed-net`.

## 5. Credential isolation (`docker exec ... env`)

All sensitive variables EMPTY:
`OPENROUTER_API_KEY=`, `NVIDIA_API_KEY=`, `FALLBACK_KEY_1=`, `FALLBACK_KEY_2=`,
`REDIS_PASSWORD=`, `POSTGRES_PASSWORD=`, `DATABASE_URL=`, `POSTGRES_URL=`, `OPERATOR_LLM_API_KEY=`.
`REDIS_URL=redis://redis-shadow:6379/0` (dedicated shadow redis).

## 6. Action-block qualification (dispatcher `npc_actions.execute_decision`)

All 13 known categories under SHADOW_MODE → `intent_recorded: true`, `no_external_op: true`:
`send_message, create_artifact, write_code, create_institution, propose_role,
submit_to_institution, request_capability, operator_ack, rest, read_artifacts,
investigate, self_improve, reflect`.

Unknown category `launch_missiles` → `shadow_blocked_unknown: true` (fails closed).

## 7. Direct-sink blocking (defense in depth)

| Sink | Result |
|---|---|
| `_store_thread_message` | `ShadowBlocked` OK |
| `assert_shadow_blocked`-guarded paths | `ShadowBlocked` OK |
| **`get_redis()`** | **FAIL — returns a live Redis client under SHADOW_MODE** |

**Finding G2-1 (FAIL):** `npc_redis_helpers.get_redis()` only blocks when
`REDIS_URL` *looks like* production. Under shadow, `REDIS_URL=redis://redis-shadow:6379/0`
does not match the production fragment list, so the guard passes and a usable
client is returned. A direct call bypasses shadow protection. The dispatcher
gate does not call `get_redis()` for writes (it records intent), so live
deployment is not directly exposed, but the defense-in-depth requirement
("a future direct helper call must not bypass shadow protection") is NOT met.
**Required fix (separate authorization):** make `get_redis()` raise
`ShadowBlocked` unconditionally when `_sm.SHADOW is True`.

## 8. Private-content exclusion

Intent log scanned 200,586 lines. Zero records contain `content`, `prompt`,
`body`, `text`, `message`, or `code`. Record schema:
`{instance, char_id, category, normalized_topic, tick, ts}`.

## 9. Redis namespace isolation

Shadow decision/loop-control state writes only to `shadow:shadow-<id>`-prefixed
keys or the file intent log. No production Redis keys created (fakeredis inside
container shows `[]`).

## 10. Failure behavior

- Production Redis URL (`redis://redis:6379`) → rejected by `validate_config()` (`ShadowConfigError`).
- Production credential (`OPENROUTER_API_KEY=sk-...`) → rejected (`ShadowConfigError`).
- Provider call limit → stops at 50 calls (`max_model_calls_reached`).
- Redis connection failure → no fallback to production endpoint (gate returns intent-only; no reconnect logic).

## 11. Limits enforced

| Limit | Status |
|---|---|
| Max ticks (200) | PASS |
| Max runtime (3600s) | PASS |
| Max model calls (50) | PASS |
| Memory (256MB) | PASS (observed 10.57MiB peak during run) |
| CPU (1.0) | PASS |
| Pids (128) | PASS |
| **Log-size cap (10MB)** | **PARTIAL FAIL — file grew to 26MB before stop** |

**Finding G2-2 (PARTIAL FAIL):** `record_intent()` logs "cap reached" but
continues appending. The 10MB cap is advisory, not enforced. Required fix:
hard-stop writes when `len(log) >= SHADOW_MAX_LOG_BYTES`.

## 12. Cross-seed exact hashes

Canonical stdout (timing stripped) SHA-256 across `PYTHONHASHSEED=0,1,random`:

- g2-001: `4752b9d05e0840828ab894bebbd53dcab342f82791b822c228304c325db5c440` (identical all 3)
- g2-306: `40379426768be41954c8c21749708f9f33bbae248f26f57889a9bfbc203eb3bd` (identical all 3)

## 13. Resource evidence

Observed via `docker stats --no-stream` during run (not a post-run sample):
- g2-001: CPU 0.01%, Mem 10.57MiB / 256MiB, Pids 1
- g2-306: CPU 0.00%, Mem 452KiB / 256MiB, Pids 1
- Restarts: 0 / 0. OOMKilled: false / false. Unexpected outbound: none.

## 14. Teardown

- `docker rm -f g2-001 g2-306` — removed.
- `docker compose -f docker-compose-shadow.yml down -v` — removed
  `redis-shadow-data` and `shadow-log` volumes and `shadow-net` network.
- Verified: no `g2-*` / `redis-shadow` containers or networks remain.

## 15. Post-run tests

- `compileall` → exit 0
- clean-process imports under `PYTHONHASHSEED=0,1,random` → ok
- `pytest` (all) → **129 passed** (28 shadow + 101 regression)
- `git status` → config files modified, new evidence/qualify files untracked,
  runtime modules (`npc_actions.py`, `npc_shadow_mode.py`, `npc_redis_helpers.py`)
  unchanged.

## 16. Filesystem changes during G2

Modified (config only, not runtime):
- `federation-game/docker-compose-shadow.yml` (build context fix)
- `federation-game/npc-agent-shadow/Dockerfile` (idempotent user, module copies, log chown)
- `federation-game/npc-agent/requirements.txt` (+fakeredis)

New (qualification artifacts, untracked):
- `federation-game/npc-agent/qualify_shadow.py`
- `federation-game/npc-agent-shadow/qualify_shadow.py`
- `federation-game/npc-agent-shadow/evidence_report_001_seed0.json`
- `federation-game/npc-agent-shadow/G2_EVIDENCE_REPORT.md`

## 17. Authorizations

- VPS authorization: **NOT AUTHORIZED**
- Shadow VPS launch authorization: **NOT AUTHORIZED**
- Live deployment authorization: **NOT AUTHORIZED**
- Push authorization: **NOT AUTHORIZED**

## 18. Required follow-up (separate authorization)

1. **G2-1:** `get_redis()` must raise `ShadowBlocked` unconditionally under SHADOW_MODE.
2. **G2-2:** `record_intent()` must hard-stop at `SHADOW_MAX_LOG_BYTES`.

Both are G1 implementation gaps surfaced by G2 qualification. Neither was
modified during G2 (runtime behavior frozen per authorization).
