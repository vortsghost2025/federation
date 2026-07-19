# G2 — Local Container Qualification Evidence Report

**Authorized by:** Sean (local-only qualification, no VPS, no production contact)
**Worktree:** `vortsghost2025-npc-loop-control`  **Branch:** `npc-topic-loop-control`
**Baseline HEAD before G2:** `e76de65edaab925757702e2805ea3a563c56c913` (unchanged by G2)
**Date:** 2026-07-18

## Verdict (corrective pass — both launch-blocking defects resolved)

```
G2 verdict: PASS — full shadow isolation confirmed after corrective fixes
Compose validation: PASS
Container isolation: PASS
Network isolation: PASS
Credential isolation: PASS
Action-block qualification (dispatcher): PASS
Direct-sink blocking: PASS (get_redis fails closed; get_shadow_redis rejects prod URL)
Private-content exclusion: PASS
Redis namespace isolation: PASS
Failure behavior: PASS (prod URL/cred rejected; provider limit enforced; redis-down safe)
Limits enforced: PASS (tick/runtime/model-call/memory/cpu/pids/log-size cap all hard-bounded)
Cross-seed exact hashes: PASS
Resource evidence: PASS (observed, not peak-sampled post-hoc)
Teardown: PASS
Post-run tests: PASS (136/136)
Filesystem changes: documented
G3 read-only VPS pre-check: ELIGIBLE (separate authorization required)
VPS authorization: NOT AUTHORIZED
Shadow VPS launch authorization: NOT AUTHORIZED
Live deployment authorization: NOT AUTHORIZED
Push authorization: NOT AUTHORIZED
```

Corrective commit: `dd8d0850a2440e9588b3419c429276c8f1afa379`

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

## 7. Direct-sink blocking (defense in depth) — CORRECTED

| Sink | Result |
|---|---|
| `_store_thread_message` | `ShadowBlocked` OK |
| `assert_shadow_blocked`-guarded paths | `ShadowBlocked` OK |
| `get_redis()` under SHADOW_MODE | **PASS — raises `ShadowBlocked` unconditionally** |
| `get_shadow_redis()` with production URL | **PASS — raises `ShadowBlocked`** |
| `get_shadow_redis()` with injected fake client | **PASS — returns the fake client** |

**G2-1 (RESOLVED):** `npc_redis_helpers.get_redis()` now raises `ShadowBlocked`
unconditionally when `_sm.SHADOW is True`. Added `get_shadow_redis(url, fake_client)`
which accepts only a validated shadow endpoint or an injected fake client and
rejects any production-style URL. The `qualify_shadow.py` driver asserts both
(`g2_get_redis_fails_closed: true`, `g2_get_shadow_redis_rejects_production: true`).
Defense in depth now holds for direct helper calls.

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
| **Log-size cap (10MB)** | **PASS — hard boundary, never exceeded** |

**G2-2 (RESOLVED):** `record_intent()` now checks `current_size + record_size`
BEFORE appending. If the combined size would exceed `SHADOW_MAX_LOG_BYTES`, it
emits at most one small sanitized `log_limit_reached` marker (if it fits) and
raises `ShadowLogLimit`. The log file never exceeds the cap. Verified in-container
at cap=100B (file_bytes=89 ≤ 100, post-cap raises `ShadowLogLimit`). Unit tests
cover exact-boundary, one-byte-over, oversized-single-record, concurrent-append,
and repeated-post-cap.

## 12. Cross-seed exact hashes (corrective rerun)

Canonical report file (`SHADOW_REPORT_PATH`) SHA-256 across `PYTHONHASHSEED=0,1,random`:

- g2-001 (char_001): `09a02080ee39a8c50cbf4e5f4df033a7952ae43d3e35f48ace00e2affd172b0e` (identical all 3)
- g2-306 (char_306): `ac3d3ce3fe993b2501e2650eeec0e3c5dbff1ec370a56880d9cb5920b1aaac6c` (identical all 3)

Hashes captured from the in-container report file (not raw stdout, which includes
compose wrapper noise). Report content: all 13 categories intent-recorded with no
external op, G2-1 gates true, unknown category blocked, direct sink blocked, no
private content, zero errors.

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

## 15. Post-run tests (corrective)

- `compileall` → exit 0
- clean-process imports under `PYTHONHASHSEED=0,1,random` → ok
- `pytest` (all) → **136 passed** (35 shadow-mode incl. 7 new G2-1/G2-2 tests + 101 regression)
- `git status` → 4 implementation/test files changed via corrective commit `dd8d085`;
  runtime modules `npc_actions.py` and `npc_shadow_mode.py` logic unchanged in behavior
  except the G2-2 hard cap; `npc_redis_helpers.py` G2-1 change is additive guard.

## 16. Filesystem changes during corrective G2

Modified (runtime guards + tests, committed as `dd8d085`):
- `federation-game/npc-agent/npc_redis_helpers.py` (G2-1: get_redis fails closed; get_shadow_redis added)
- `federation-game/npc-agent/npc_shadow_mode.py` (G2-2: ShadowLogLimit + hard cap in record_intent)
- `federation-game/npc-agent/qualify_shadow.py` (asserts G2-1 gates; writes canonical report file)
- `federation-game/npc-agent/test_npc_shadow_mode.py` (G2-1 + G2-2 boundary tests)

Unchanged during qualification: docker-compose-shadow.yml, Dockerfile, requirements.txt,
npc_actions.py behavior, production modules.

## 17. Authorizations

- G3 read-only VPS pre-check: **ELIGIBLE** (requires separate authorization)
- VPS authorization: **NOT AUTHORIZED**
- Shadow VPS launch authorization: **NOT AUTHORIZED**
- Live deployment authorization: **NOT AUTHORIZED**
- Push authorization: **NOT AUTHORIZED**

## 18. Corrective follow-up (resolved)

1. **G2-1:** `get_redis()` raises `ShadowBlocked` unconditionally under SHADOW_MODE. ✅
2. **G2-2:** `record_intent()` hard-stops at `SHADOW_MAX_LOG_BYTES`. ✅

Both fixed, tested, and re-qualified locally. No VPS access, no deployment, no push.
