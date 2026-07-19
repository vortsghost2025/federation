# G4B ISOLATED VPS SHADOW QUALIFICATION — EVIDENCE REPORT

**Date:** 2026-07-19 (UTC)
**Worktree:** vortsghost2025-npc-loop-control
**Branch:** npc-topic-loop-control
**Git HEAD:** a998ac2 (a998ac270c28ece9f65d7569aceb19caba2f7bf0)
**VPS:** root@187.77.3.56 (srv1345984), Docker v29.4.2

## G4B VERDICT: PASS

All isolation, qualification, and teardown requirements satisfied.
Production containers, files, Redis, and Postgres were NOT modified.

## Build-context isolation
- Shadow image built exclusively from /docker/federation-game/npc-agent-shadow/.
- Production /docker/federation-game/npc-agent/ was NEVER read, written, or sourced.
- Compose: `context: /docker/federation-game/npc-agent-shadow`, `dockerfile: Dockerfile`.
- Unique image tag: `federation-npc-shadow:a998ac2` (HEAD-derived; never reused prod tags).
- SHA-256 of all 15 staged runtime files == committed npc-agent/ source at HEAD (byte-identical).

## SHA manifest (staged shadow context vs Git HEAD)
All 15 files verified byte-identical via `git hash-object` comparison. See G4A/G2 manifests.
Runtime closure: npc_agent, npc_actions, npc_decisions, npc_loop_control, npc_shadow_mode,
npc_redis_helpers, npc_context, npc_llm_client, npc_memory_bridge, fourth_wall, cosmic_monitor,
institutions, qualify_shadow, test_npc_shadow_mode + requirements.txt + Dockerfile + .dockerignore.

## Compose validation (18/18 PASS)
build context only npc-agent-shadow | unique shadow image tag | restart "no" |
internal shadow-net | NO fed-net | dedicated redis-shadow | mock provider |
NO prod redis url | NVIDIA key empty | no postgres password | read_only true |
cap_drop ALL | no-new-privileges | bounded mem_limit | bounded cpus | bounded pids_limit |
NO docker socket | NO host prod mount | non-root USER shadow (agents) / user 999:1000 (redis)

## Image isolation
- Image: federation-npc-shadow:a998ac2 (f8cc3bb3aa44, 219MB), built from isolated context only.
- Deleted after teardown (no lingering temp image).

## Container isolation
- redis-shadow-1 (redis:7-alpine, user 999:1000, non-root, cap_drop ALL, ro, no-new-priv)
- npc-agent-shadow-001-1 (user shadow, cap_drop ALL, ro, no-new-priv, mem 256m, cpu 1.0, pids 128)
- npc-agent-shadow-306-1 (same)
- All three on internal shadow-net only.

## Network and egress isolation
- shadow-net: internal=true (no gateway, no egress).
- Agent cannot resolve/route to production (separate network namespace).
- DNS/egress to internet blocked (getent google.com => no address; /dev/tcp blocked).
- redis-cli absent from agent image (no prod redis attempt possible).

## Credential isolation
- NVIDIA_API_KEY, OPENROUTER_API_KEY, FALLBACK_KEY_1/2, OPERATOR_LLM_API_KEY,
  DATABASE_URL, POSTGRES_URL, POSTGRES_PASSWORD, REDIS_PASSWORD all "".
- No .env, no real credentials, zero internet.

## Action-block results (qualification driver, agent-001 + agent-306)
- 13/13 known categories => intent_recorded:true, no_external_op:true
  (send_message, create_artifact, write_code, create_institution, propose_role,
   submit_to_institution, request_capability, operator_ack, rest, read_artifacts,
   investigate, self_improve, reflect)
- unknown_category_blocked: true (fail-closed for "launch_missiles")
- g2_get_redis_fails_closed: true
- g2_get_shadow_redis_rejects_production: true

## Direct-sink results
- _store_thread_message => blocked: true (ShadowBlocked raised)

## Private-content exclusion
- Intent logs scanned for content|prompt|body|private_message|password|api_key|secret|token|credential => ZERO matches.
- Sample record: {instance, char_id, category, normalized_topic, tick, ts} only.
- No bodies, prompts, credentials, or private messages recorded.

## Redis namespace
- shadow_key() => "shadow:shadow-001:intent"; SHADOW_NS="shadow:shadow-001" in every key.
- Qualification used in-process fakeredis (never production Redis).

## Failure behavior
- Unreachable shadow Redis => ConnectionError raised, NO fallback to another endpoint.
- Hard log-size cap => ShadowLogLimit raised; final size stayed within cap (131 <= 200 in boundary test).

## Limits enforced
- Compose: mem=268435456 (256m), cpu=1000000000 (1.0), pids=128, ro=true, caps=ALL, np=no-new-privileges.
- Config: MAX_TICKS=200, MAX_RUNTIME_S=3600, MAX_MODEL_CALLS=50, MAX_LOG_BYTES=10485760.
- Hard log cap proven to refuse writes beyond boundary.
- Mock-provider call cap = 50 (deterministic, zero credentials).

## Cross-seed exact hashes
- agent-001 canonical report sha256 (PYTHONHASHSEED 0 / 1 / random):
  09a02080ee39a8c50cbf4e5f4df033a7952ae43d3e35f48ace00e2affd172b0e  (IDENTICAL)
- agent-306 canonical report sha256 (seed 0):
  5e08683fd599e9d549e11db4cf6374cf9c58df5a300fc93fbcd136fba200cac3

## Resource evidence (observed live; no sustained-load peak telemetry collected)
- agent-001: 2.656MiB / 256MiB, PIDs 1
- agent-306: 1.059MiB / 256MiB, PIDs 1
- redis-shadow: 7.664MiB / 128MiB, PIDs 6
- Zero OOM kills, zero restarts during the entire run.

## Production before/after comparison
- npc-agent-001-1: ID 62e174132a9b, restart 0 -> 0, image 72e8df3b... unchanged
- npc-agent-306-1: ID 2cef1bbe8d31, restart 0 -> 0, image 32687929... unchanged
- redis-1: ID 30ef21b70009, restart 0 -> 0, image 6ab0b6e7... unchanged
- postgres-1: ID f5c7bdff265f, restart 0 -> 0, image df7bca00... unchanged
- prod npc_redis_helpers.py hash e34a3fae... UNCHANGED (old pre-G2 version, confirms prod untouched)
- prod Redis dbsize 36243 (no shadow keys leaked); prod Postgres federation tables = 0 (no writes)

## Teardown
- docker compose -p federation-shadow-g4b down --volumes --remove-orphans: all 3 containers removed.
- Shadow volumes (shadow-log, redis-shadow-data) removed.
- Shadow-net removed.
- Temp image federation-npc-shadow:a998ac2 deleted.
- PROOF: no G4B containers / networks / volumes remain.

## Evidence commit
- e62da06b5bd4e42502f894f8139026814889f28f

## Pushed HEAD
- e62da06b5bd4e42502f894f8139026814889f28f

## Local HEAD equals remote HEAD
- MATCH

## Google Drive continuity
- Updated: C:\Users\seand\Google Drive\AI_AGENT_CONTINUITY\PROJECTS\Federation

## Eligible for persistent VPS shadow observation
- YES (subject to separate authorization)

## Persistent shadow authorization: NOT AUTHORIZED
## Production promotion authorization: NOT AUTHORIZED
