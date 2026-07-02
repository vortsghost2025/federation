# FEDERATION DELTA LOG — Write-Ahead Log

## Institution Dedup Guard
```
NEW npc_actions.py:_is_repetitive_institution() -> Jaccard word-overlap vs existing names, threshold 0.50
NEW npc_actions.py:MAX_INSTITUTIONS = 30 -> capacity cap, blocks after 30
NEW npc_actions.py:_INST_STOP_WORDS -> domain stop words (bureau, council, committee, commission, etc.)
UPDATE npc_actions.py:create_institution handler -> guards: existing slug match -> repetitive name -> at capacity (30 max) -> create
UPDATE npc_context.py:think_about_world() -> always shows institution count + first 6 names, even before NPC joins one
UPDATE backend/routes/admin.py:/api/admin/status -> returns institution_count + role_count
DEPLOYED: live, all 3 md5s match (host + 001 + 306), backend restarted
INSTITUTION COUNT AT DEPLOY: 210 (all proposed, 0 filled) — capacity cap will block new ones
```

## Institution Redis Cleanup
```
RUN inst_cleanup.py -> purged 198 stale institutions + 36 orphaned roles from Redis
KEPT: 12 (Consciousness Collective Council + Research Division Council with members, 10 narrative-referenced)
REMAINING: 12 institutions, 91 roles
VERIFIED: admin endpoint returns 12, both agents ticking normally post-cleanup
```

**Format:** Each entry = one atomic code change. Append only, never edit.
**Purpose:** Post-compaction replay — read this instead of grepping git log.

---

## P0 — need_reflection propagation fix
```
UPDATE npc_autonomy.py:evaluate_decision_options() -> added need_reflection param, passed to _score_decision_option
UPDATE npc_autonomy.py:_score_decision_option() -> added need_reflection param, skip rest/wander when fulfilled
KEY npc:needs -> need_reflection now flows from fulfilled notifications to scoring
DEPLOYED: live, md5 f3f66340420e60e36a03082eb57642e6
```

## Councilor Decrees v0
```
NEW routes/decrees.py -> 3 endpoints (issue, history, status)
NEW npc_autonomy.py:evaluate_decrees() -> rule-based decree evaluation
NEW npc_autonomy.py:_write_decree_directive(r, char_id, metric) -> writes DIRECTIVE_KEY
KEY councilor:directive:active -> JSON directive, TTL 600s
KEY councilor:decrees:history -> append-only decree log
KEY councilor:decrees:cooldown:{char_id} -> cooldown marker
CONSTANT DECREES_ALLOWED_NPCS = ["char_001", "char_306"]
DEPLOYED: live, commit 0110d27 + 86a4430 + e79abe8
```

## P0 Bridge bug fix — fulfilled needs suppress repeat
```
UPDATE npc_autonomy.py:_score_decision_option() -> added fulfilled_need_types param
UPDATE npc_autonomy.py:_reflect_on_missing_context() -> added fulfilled_need_types param, skip low_value if need fulfilled
UPDATE npc_autonomy.py:evaluate_decision_options() -> builds fulfilled_need_types from npc:notifications:{char_id}
PATTERN: 3-layer suppression (fulfilled_need_types built from notifications, passed through scoring + reflection skip)
DEPLOYED: live, commit e79abe8
```

## P2 Directive system
```
UPDATE npc_autonomy.py:_score_decision_option() -> added affiliation param, reads DIRECTIVE_KEY, applies DECREE_DIRECTIVE_BIAS multipliers
UPDATE npc_autonomy.py:evaluate_decision_options() -> passes affiliation from char_data
NEW CONSTANT DECREE_DIRECTIVE_BIAS -> maps metric -> faction_tier -> category -> multiplier
NEW CONSTANT COUNCILOR_AFFILIATIONS = {"char_001": "research_division", "char_306": None}
NEW CONSTANT FACTION_ALLIANCES = {"research_division": "consciousness_collective", ...}
NEW _is_allied_faction() -> bidirectional alliance check
DEPLOYED: live, 22/22 directive tests pass
```

## P4 Traefik security
```
UPDATE docker-compose.yml -> removed --api.insecure=true, removed port 8080 mapping
UPDATE docker-compose.yml -> added GRAFANA_ADMIN_PASSWORD env var with fallback
UPDATE docker-compose.yml -> restored postgres:15-alpine service with healthcheck
DEPLOYED: live, commit 005fc9f
```

## P3 Workflow Outcome Memory
```
NEW institutions.py:_record_outcome(r, workflow_id, record, new_status) -> terminal-state guard, hincrby + lpush + ltrim
NEW institutions.py:get_npc_outcome_history(r, npc_id) -> returns {approved: N, rejected: N, recent: [...]}
NEW institutions.py:NPC_OUTCOME_HISTORY_KEY = "npc:{npc_id}:workflow_outcomes"
NEW institutions.py:NPC_RECENT_OUTCOMES_KEY = "npc:{npc_id}:recent_outcomes"
NEW institutions.py:MAX_RECENT_OUTCOMES = 20
UPDATE institutions.py:TERMINAL_STATES -> added "approved"
UPDATE institutions.py:advance_workflow() -> calls _record_outcome on terminal state
UPDATE institutions.py:override_workflow_status() -> calls _record_outcome on terminal state
NEW npc_autonomy.py:_get_npc_outcome_ctx(npc_id) -> reads outcome counts + recent list
UPDATE npc_autonomy.py:_score_decision_option() -> added outcome_ctx param, consecutive rejection suppresses advance_goal 42%, approval boosts 15%
UPDATE npc_autonomy.py:_reflect_on_missing_context() -> added outcome_ctx param, pivot_strategy reflection on rejection streak
UPDATE npc_autonomy.py:evaluate_decision_options() -> fetches _get_npc_outcome_ctx, passes to scoring + reflection
NEW ALLOWED_NEED_TYPES entry: "pivot_strategy"
KEY npc:{npc_id}:workflow_outcomes -> hash {approved: N, rejected: N}
KEY npc:{npc_id}:recent_outcomes -> list, last 20 JSON entries, lpush/ltrim
REASON LABELS: rejection_cautious(N), pivoting_to_collaborate, approval_confidence
MD5 institutions.py: a10900844ef5ec59ab492e21de8c4855
MD5 npc_autonomy.py: ae3475acda9596ef9de311ec9cf72ae7
DEPLOYED: live, all 4 containers verified, 35/35 tests pass
```

## Context Engineering (this session)
```
NEW .horizon/ARCHITECTURE_STATE.md -> compressed backend state (signatures, Redis keys, wiring, deploy rules)
UPDATE AGENTS.md -> Ramsingh loop pointer, ARCHITECTURE_STATE reference in project files + session-startup
UPDATE .horizon/HORIZON_STATUS.md -> current HEAD, P0-P4+P3 logged, dirty tree updated
NEW .horizon/DELTA_LOG.md -> this file, structured write-ahead log
```
UPDATE routes/metrics.py -> lazy prometheus_client imports, graceful fallback when missing (returns None instead of crashing) | UPDATE main.py:metrics(L341) -> returns fallback text when metrics_response() is None | DEPLOY routes/metrics.py + main.py -> VPS, pip install prometheus_client in container, /metrics returns 200 with world_state data

## Nginx Proxy Routes — 4 missing routes deployed
```
UPDATE frontend/nginx-default.conf -> added location blocks for /error-reports, /councilor, /institutions, /decrees (were 404ing from frontend)
DEPLOY nginx-default.conf -> VPS host + container, nginx -s reload
VERIFY: error-reporter.js can now POST through nginx to backend (was auto-disabling on 404)
VERIFY: all 3 md5s match (local, VPS host, container)
```

## Spectator "Councilor autonomy" label fix
```
UPDATE frontend/spectator.html:L1176 -> "Councilor autonomy" relabeled to "Councilor proposals" (was misleading — showed active workflow proposal count, not autonomy)
DEPLOY spectator.html -> VPS host mount /docker/federation-game/public_html/
VERIFY: all 3 md5s match (local, VPS host, container)
```

## Institution key pattern fix in metrics.py
```
UPDATE routes/metrics.py:_collect_institutions() -> changed from r.keys("institution:*:info") (wrong pattern, returned nothing) to r.smembers("institution:index") (canonical index). Also reads role_count from SCARD and workflow counters from hash fields active_workflows/completed_workflows instead of nonexistent JSON workflow_counts field.
DEPLOY routes/metrics.py -> VPS host, docker restart backend
VERIFY: /metrics returns 30 institutions with real role counts (CC Council: 48, Research Council: 16, etc.)
VERIFY: all 3 md5s match (local, VPS host, container)
```
