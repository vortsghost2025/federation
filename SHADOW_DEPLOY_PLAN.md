# NPC Topic-Loop Control — Bounded Reversible SHADOW Deployment Plan (HARDENED)

STATUS: PREPARED, NOT EXECUTED. No VPS/container/Redis/provider action taken.
This revision closes the external/action-isolation gap from the prior skeleton.
A separate Redis logical DB is NO LONGER the isolation mechanism; a dedicated
shadow Redis container on an isolated Docker network is.

## 0. Layered authorization gates (all must be PASS to proceed one layer deeper)

  GATE 0  Plan hardening (this file) ............. PREPARED
  GATE 1  SHADOW_MODE code gate implemented ...... REQUIRED BEFORE BUILD
  GATE 2  Local container qualification .......... REQUIRED BEFORE VPS TOUCH
  GATE 3  Read-only VPS pre-check (Phase A) ...... ELIGIBLE (no changes)
  GATE 4  Shadow launch on VPS ................... SEPARATE AUTHORIZATION
  GATE 5  Promotion to production ................ SEPARATE AUTHORIZATION (future)

Live deployment of production containers: NOT AUTHORIZED. Push: NOT AUTHORIZED.

## 1. SHADOW_MODE runtime gate (REQUIRED CODE ARTIFACT — not yet written)

A new module npc_shadow_mode.py exports:
    SHADOW = os.environ.get("SHADOW_MODE", "").lower() in ("1","true")
    SHADOW_INSTANCE_ID = os.environ.get("SHADOW_INSTANCE_ID", "shadow")
    SHADOW_NS = f"shadow:{SHADOW_INSTANCE_ID}"
and helpers:
    shadow_key(k)        -> f"{SHADOW_NS}:{k}"   (all storage/log keys namespaced)
    record_intent(action, payload) -> append-only JSONL to SHADOW_INTENT_LOG
                                       (local file or shadow Redis list only)
    assert_shadow_blocked(path_name) -> if SHADOW and path_name in BLOCKED,
                                       record intent + return True (caller skips)

npc_actions.py imports SHADOW; at the TOP of every write-capable branch it calls
assert_shadow_blocked("<surface>"). If blocked, it records the intended action to
the shadow intent log and returns a benign result WITHOUT performing the write.

## 2. Blocked action surfaces in SHADOW_MODE (proven from deployed npc_actions.py)

Write-capable paths enumerated in the deployed file (line refs from byte-identical
capture 04555945...). Each is gated:

  send_message            (81-148)  rpush npc_messages:*:inbox, _store_thread_message,
                                    rpush npc_session:*, hincrby npc_stats
                                    -> BLOCK: no message, no thread, no stats write.
  create_artifact         (159-223) call_llm(provider), rpush npc_artifacts:*,
                                    hincrby artifacts_created, partner notify
                                    -> BLOCK publish; loop-control state only;
                                       artifact CONTENT may be generated but NOT stored
                                       or published (intent recorded).
  write_code              (225-244) call_llm, rpush npc_artifacts:*, hincrby
                                    -> BLOCK publish; intent recorded.
  read_artifacts          (250-269) read-only (lrange) -> ALLOWED (no write).
  investigate             (271-293) hincrby investigations -> BLOCK stat write;
                                    intent recorded.
  self_improve            (295-304) hincrby -> BLOCK.
  reflect                 (306-315) hincrby -> BLOCK.
  create_institution      (325-426) sadd institution:index, hset, hincrby,
                                    rpush npc_session:* -> BLOCK entirely.
  propose_role            (428-512) sadd role:index, hset, hincrby -> BLOCK entirely.
  submit_for_review       (524-600) ensure_workflow (Postgres/backend import at 526-527),
                                    hincrby artifacts_submitted_for_review -> BLOCK;
                                    do NOT import backend/institutions; intent recorded.
  capability_request/file_npc_need (610-649) file_npc_need (npc_autonomy import 618-620)
                                    -> BLOCK; intent recorded.
  operator_ack            (687-699) _acknowledge_operator_directive -> BLOCK moderator/
                                    operator message; intent recorded. NO attribution write.
  record_decision         (708-715) zadd npc_decisions:*, set npc_activity:*,
                                    hset npc_cognition:* -> BLOCK prod Redis; write to
                                    shadow namespace only (shadow Redis container).
  _sync_pair_workspace    (723)     -> BLOCK.
  record_councilor_memory (726-727) -> BLOCK.
  mood                   (739)      r.set npc_mood:* -> BLOCK.

ALLOWED in SHADOW_MODE: decision generation (npc_decisions), loop-control state
(npc_loopctrl:* in shadow Redis), read-only reads, intent-log appends.

## 3. Isolation architecture (replaces DB /2 design)

  - Dedicated shadow Redis container `redis-shadow` on a SEPARATE Docker network
    `shadow-net` (no route to fed-net, no route to production redis).
  - Shadow containers join ONLY shadow-net; they cannot reach production redis,
    postgres, or backend.
  - Provider: DEFAULT = mock/deterministic fixture (no production API key).
    Real-provider shadow test = SEPARATE authorization + strict call cap.
  - SHADOW_INSTANCE_ID prevents external identity collision; all keys shadow-namespaced.
  - Production credentials NEVER mounted into shadow containers.

## 4. Exact compose design (docker-compose-shadow.yml)

  networks:
    shadow-net:
      driver: bridge
      internal: true            # no external egress
  services:
    redis-shadow:
      image: redis:7-alpine
      networks: [shadow-net]
      restart: "no"
    npc-agent-shadow-001:
      build: /docker/federation-game/npc-agent-shadow
      restart: "no"
      environment:
        - CHAR_ID=char_001
        - NPC_NAME=Archimedes Prime
        - SHADOW_MODE=true
        - SHADOW_INSTANCE_ID=shadow-001
        - REDIS_URL=redis://redis-shadow:6379/0
        - NVIDIA_API_KEY=        # empty; mock provider used
        - SHADOW_PROVIDER=mock
        - SHADOW_MAX_TICKS=200
        - SHADOW_MAX_RUNTIME_S=3600
        - SHADOW_MAX_MODEL_CALLS=50
        - SHADOW_MAX_LOG_BYTES=10485760
        - SHADOW_MAX_MEM=256M
      networks: [shadow-net]
      depends_on: [redis-shadow]
    npc-agent-shadow-306: (same, CHAR_ID=char_306, SHADOW_INSTANCE_ID=shadow-306)

  Note: `internal: true` blocks all outbound network — so even if a key were
  leaked it cannot call external providers. Mock provider required.

## 5. Action-block matrix (intent vs write)

  action category      | external write | prod redis | message | publish | in SHADOW
  ---------------------+---------------+-----------+---------+---------+----------
  send_message         | no            | no        | no      | n/a     | intent only
  create_artifact      | no            | no        | no      | no      | intent only
  write_code           | no            | no        | no      | no      | intent only
  read_artifacts       | read-only     | read      | n/a     | n/a     | ALLOWED
  investigate          | no            | no        | no      | n/a     | intent only
  self_improve/reflect | no            | no        | n/a     | n/a     | intent only
  create_institution   | no            | no        | no      | n/a     | BLOCKED
  propose_role         | no            | no        | no      | n/a     | BLOCKED
  submit_for_review    | no (no PG)    | no        | no      | no      | BLOCKED
  capability_request   | no            | no        | no      | n/a     | BLOCKED
  operator_ack         | no            | no        | no      | n/a     | BLOCKED
  record_decision      | n/a           | shadow ns | n/a     | n/a     | shadow only
  mood/memory sync     | no            | no        | n/a     | n/a     | BLOCKED

## 6. Tests required (req 8) — design, not yet written

  test_npc_shadow_mode.py (fake Redis + mock provider):
    1. send_message -> intent logged, 0 inbox writes, 0 thread writes
    2. create_artifact -> intent logged, 0 npc_artifacts writes, no publish
    3. write_code -> intent logged, no artifact stored
    4. create_institution -> intent logged, institution:index unchanged
    5. propose_role -> intent logged, role:index unchanged
    6. submit_for_review -> no ensure_workflow call, no PG import
    7. capability_request -> intent logged, no file_npc_need side effect
    8. operator_ack -> intent logged, no operator directive write
    9. record_decision -> written only to shadow:{id}:decisions, not npc_decisions:*
    10. read_artifacts -> reads succeed, no write
    11. loop-control deferral still records to shadow ns
    12. every category yields exactly one intent record, zero external writes
  These run in GATE 2 (local qualification) before any VPS touch.

## 7. Automatic termination limits (req 9)

  SHADOW_MAX_TICKS=200, SHADOW_MAX_RUNTIME_S=3600, SHADOW_MAX_MODEL_CALLS=50,
  SHADOW_MAX_LOG_BYTES=10MiB, memory limit 256M, restart: "no".
  The SHADOW gate enforces tick/call/runtime counters; on exceed it records a
  termination intent and exits 0.

## 8. Abort conditions + teardown (req 10)

  Abort if: any external write detected, prod redis key written, outbound network
  attempt beyond mock, credential present, OOM. Teardown:
    docker compose -f docker-compose-shadow.yml down
    docker rm -f redis-shadow npc-agent-shadow-001 npc-agent-shadow-306
    docker network rm shadow-net
    rm -rf /docker/federation-game/npc-agent-shadow
  Production npc-agent-001 / -306 UNTOUCHED throughout.

## 9. Local container qualification (GATE 2, req 11) — before VPS

  - isolated network (shadow-net, internal:true)
  - fake Redis (no production endpoint)
  - mock provider (zero credentials, zero external calls)
  - complete filesystem diff of shadow dir vs prod (only 4 modules + siblings)
  - zero side-effect proof via test_npc_shadow_mode.py (12 tests)
  - SHADOW_MODE gate compiled + imported clean

## 10. What is NOT done now

  No SHADOW_MODE code written, no tests written, no compose file on VPS, no scp,
  no container start, no Redis/Postgres write, no provider call, no push.
  This file is preparation only.