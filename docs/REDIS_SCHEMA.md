# REDIS SCHEMA — hot keys for agents (updated 2026-11-21)

Type-safe rule: never assume a key's type. `get`/`lrange`/`hgetall` on the wrong type
raises `WRONGTYPE`. Use `r.type(key)` first, or the helpers in `scripts/mod.py` (`.\scripts\mod.ps1`).

## Moderator / messaging
| Key | Type | Purpose |
|-----|------|---------|
| `npc_messages:moderator:inbox` | list of JSON strings | Agent→moderator messages. Fields: `id`, `from_char_id`, `from_name`, `subject`, `body`, `read`, `ts`, `created_at`, `thread_id` |
| `npc_messages:moderator:sent` | list of JSON strings | Moderator→agent copies |
| `npc_messages:{cid}:inbox` | list of JSON strings | Per-agent inbox (`comp_001`/`comp_010`/`char_001`/`char_306`), read by `npc_context.py` and `npc_decisions.py` |
| `msg:inbox:{cid}` | **zset** (score=epoch) | Production inbox index of `msg_id`; `get_inbox()` marks read, `peek_inbox()` does not. `scripts/mod.py` mirrors moderator replies to BOTH list + zset |
| `msg:{id}` | hash (or JSON string for thread msgs) | Message payload for `msg:inbox:{cid}` / `msg:thread:{tid}` |

## Agent decisions / activity
| Key | Type | Purpose |
|-----|------|---------|
| `npc_decisions:{cid}` | **zset** (score=epoch) | Last ~20 decisions per agent. Fields: `category`, `description`, `reasoning`, `action_taken`, `summary`, `ts` |
| `npc_session:{cid}` | list | Session/worklog entries (`kind`, `actor`, `body`, `title`) |
| `npc_actions:{cid}` | **zset** | Executed action records |
| `npc_artifacts:{cid}` | list | Agent's artifacts (`char_001`/`char_306` trimmed to 2000 on 2026-11-18) |
| `npc_artifacts:global` | list | All published artifacts incl. moderator ones |
| `npc_artifacts:moderator` | list | Moderator-only artifacts |
| `npc_artifact_titles:{cid}` | **set** | Durable normalized-title dedup (added 2026-11-18) |
| `npc_investigation_evidence:{cid}` | string | Last investigation evidence hash (added 2026-11-20) |
| `npc_dedup_streak:{cid}` | string (int, TTL 600s) | Dedup/penalty streak counter |
| `npc_dedup_topic:{cid}` | string (TTL 600s) | Topic word to discourage |

## Sandbox (comp pair pilot)
| Key | Type | Purpose |
|-----|------|---------|
| `npc_capability:grants:{cid}` | **set** | Real grants, e.g. `sandbox_exec` (only `comp_001`/`comp_010`) |
| `npc_sandbox_exec_log:{cid}` | **zset** | Exec audit: `path` remote/local, `blocked`, `ok`, `code_sha256_16`, `lines`, `output_preview`, `ts` |
| `npc_sandbox_exec_quota:{cid}` | string (int, TTL 180s) | Rolling 3-per-180s exec quota |

## Capability requests
| Key | Type | Purpose |
|-----|------|---------|
| `npc_capability_requests:index` | **zset** | `request_id` -> `created_ts` (mostly old rejected; ~837) |
| `npc_capability_request:{id}` | hash | `blocker`, `status`, `requester_id`, `need_type`, `created_ts`, `resolution` |

## Pair / world / spatial state
| Key | Type | Purpose |
|-----|------|---------|
| `npc_pair:{slug}:state` | **hash** | `open_question`, `current_topic`, `shared_goal`, `focus_{cid}`, `last_message_ts`, `last_message_from` |
| `npc_pair:{slug}:areas` | hash | Founded areas per pair |
| `world_facts:nonexistent` | **set** | Pinned negative facts (`id`, `text`, `patterns`, `alternative`) — permanent |
| `world_state` | hash | World vitals (`tension_level`, `stability`, `threat_level`, `morale`, `anomaly_activity`, `resource_abundance`) |
| `faction_dynamics` | hash | Field `<faction_id>` -> JSON string (`member_count`, `influence`, `cohesion`, `standing`, `vigilance`, `avg_mood`) |
| `territory:{faction_id}:{sector_id}` | **string (JSON)** | **NOT a hash!** Read with `r.get()` + `json.loads()`. Holds `control_level`, `influence_level`, `claim_type` |
| `sector:all` / `sector:{id}` | set / string (JSON) | 22 canonical sectors incl. `lumen_confluence` |
| `cascade_temperature` | string (float) | Live event cascade temperature (`Step 8.8`, `event_cascade.py`) |
| `faction_treaties_active` / `pending_treaties` | list / hash | Active & pending inter-faction treaties (human-readable `description`) |
| `institution:index` | set | Institution IDs; `institution:{id}` hash holds `name`, `status`, `kind` |
| `workflow:source_artifact:{artifact_id}` | string | Workflow ID for review dedup |

## System health & LLM routing
| Key | Type | Purpose |
|-----|------|---------|
| `fed:auto_tick_status` | hash | `running`, `tick_id`, `last_start`, `last_end`, `last_error`, `last_result` (JSON) |
| `monitor:llm_health` | hash | `status`, `health_score`, `alerts`, `tripped_count` |
| `llm_circuit_breaker:{provider}` | string (`open`, TTL) | Provider-wide circuit breaker |
| `llm_nim_dead_key:{hash}` | string (`1`, TTL 6h) | Per-key 403 auth blacklist |
| `llm_nim_cooldown_key:{hash}` | string (`1`, TTL 90s / Retry-After) | Per-key 429 rate-limit cooldown (added 2026-11-21) |
| `fed:watchdog:*` | (deleted between restarts) | Tick watchdog leases |

## File parity & container mount rules
- Local canonical `federation-game/npc-agent/npc_*.py` (`npc_decisions.py`, `npc_actions.py`, `npc_redis_helpers.py`, `npc_context.py`) use the **same filenames** as VPS `/docker/federation-game/npc-agent/npc_*.py`.
- Always verify MD5/SHA-256 parity (`local == VPS host == container`) before editing any backend or npc-agent file.
- `/app` is bind-mounted **read-only** inside backend/worker/npc-agent containers: use `python3 -B -c "import ast; ..."` for in-container syntax checks, and clear `__pycache__` on the VPS host before restarting containers.
