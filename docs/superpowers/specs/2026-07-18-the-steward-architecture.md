# The Steward — Federation Operations Agent Architecture

**Date:** 2026-07-18
**Status:** Draft (docs-only, for review — not committed, not deployed)
**Author:** Copilot (mechanic) + Sean (direction)
**Base commit:** `730d87e762dfd2b507236ac27fbe17edb5a00651` (origin/feature/phase2-councilor-exchange)
**Scope:** Specification only. No code, no installation, no VPS access, no commit/push.

---

## 1. Purpose

The Federation runs as a consciousness simulation across ~16 containers on a VPS (backend, two NPC agents, frontend/Councilor Watch, Redis, Postgres, worker, Prometheus, Grafana, cAdvisor, node-exporter, exporters, Dozzle-class log viewer, Traefik, npc-sandbox). Today there is no persistent, governed operator that continuously watches the real stack, correlates it with Federation-world state, and surfaces findings as an in-world actor.

**The Steward** is a persistent, tool-using operations agent with an NPC face. It:

- Wakes on schedules and important events.
- Reads the live stack (containers, logs, Redis state, API health, metrics, NPC activity, disk/RAM/DB).
- Runs **deterministic** checks and produces **structured findings**.
- Records Federation-world artifacts (incidents, work orders, snapshots) in a dedicated, isolated namespace.
- Appears in Councilor Watch as a **system actor / operator NPC** — not as a normal simulated character.
- Requests human approval before any risky action.

The Steward is deliberately **not** a normal Federation NPC subject to the autonomous cognition loop, and **not** an LLM that administers the server. The model, when used at all, only interprets already-produced deterministic findings.

## 2. Load-Bearing Separation

This separation is the central, non-negotiable design rule.

### 2A. Hard Operator Engine (deterministic Python)
- Pure, testable Python. No model invocation in the decision path.
- Reads only; writes only to the dedicated `steward:` Redis namespace (Federation-world scoped).
- Each check takes inputs, applies explicit thresholds, returns a `Finding` (Section 8).
- Scheduling, run history, retries, and the dashboard are provided by an external shell (Section 4), not by the engine itself.
- The engine never decides server administration. It only observes, records, and flags.

### 2B. Soft NPC Identity (render of engine output)
- The Steward's "presence" in Councilor Watch is a **presentation adapter** over engine findings.
- It translates a `Finding` into Federation-world language ("The Steward inspected the pair workspace and detected a resolved-topic loop").
- It has **no cognition ticks, no pair matching, no convergence, no relationships, no open-question orbit, no inbox**, and does not inject messages (Section 11).
- If a model is used (Section 5 / 13), it summarizes or translates the finding; it cannot alter severity, evidence, or execute tools.

**Why this matters:** an LLM randomly deciding how to administer the server is the exact danger we avoid. The hard layer controls what may be touched; the soft layer only narrates.

## 3. Component Model

```
[Scheduler shell: Dagu candidate]            (external; runs the engine on cron/event)
        │  invokes:  steward check <id>
        ▼
[Steward Python Engine]                       (deterministic, testable)
   ├─ check modules: container-health, npc-heartbeats,
   │                semantic-loops, redis-ttl, api-health, disk-ram-db
   ├─ data-source adapters (read-only): prometheus, grafana-read,
   │                backend health API, redis-read, postgres-read, logs, npc API
   ├─ finding builder + dedupe
   └─ world-writer (steward: namespace ONLY)
        │
        ▼
[Structured Finding -> finding.json / steward:incident:* / steward:work_order:*]
        │
        ▼
[Councilor Watch system-actor renderer]      (read-only presentation)
        │
        ▼
[Sean]  <- notifications (Apprise/Gotify candidate); approval gateway for risky acts
```

The engine is a library + CLI. The scheduler is configuration around it. The renderer is a thin read-only view.

## 4. Scheduler Decision

The scheduler's job: run checks on a cadence, keep history, allow manual reruns. It is **not** the capability authority.

**Leading candidate: Dagu.** DAG scheduling, cron-like web UI, run history, manual reruns, simple command invocation. Dagu would invoke `steward check <id>`, never run logic itself.

**Decision matrix:**

| Option | Fit | Risk | Verdict |
|--------|-----|------|---------|
| Dagu | Purpose-built scheduler shell; minimal surface | Low | **Leading candidate** |
| Cronicle (project `cronicle-gyag`) | Already may exist on VPS per prior claim | Unknown — **UNVERIFIED** | Use **only if** VPS inventory proves it is healthy and reachable |
| Systemd timers / cron | Ubiquitous, zero new deps | No dashboard/history UI | Acceptable fallback |
| Agent Zero / Hermes / Dify / Flowise / n8n / Activepieces | Broad agent/workflow platforms | LLM-or-platform becomes real administrator | **Prohibited as controller** |

**Binding rule:** Dagu (or Cronicle, if VPS-verified) is a **candidate scheduler, not a dependency**, until the VPS inventory is actually inspected. The engine must remain schedulable by plain cron/systemd so no scheduler is mandatory. Installation of any scheduler requires a **separate** authorization; it is out of scope for this spec.

## 5. Security Boundary

The Steward engine is bound by a strict prohibition list. **None** of the following may ever be performed by the engine, the scheduler, or any model integration:

- Mounting `docker.sock` or calling the raw Docker API for control.
- Unrestricted Redis access (engine uses a **read-only adapter**; world writes limited to `steward:` keys).
- Arbitrary shell execution.
- Model-issued infrastructure commands.
- Infrastructure mutation: container restart/stop/start/recreate/scale.
- Redis infrastructure mutation (SET/DEL/HSET on non-`steward:` keys, FLUSH, EVAL, EXPIRE on others).
- Deployment, rebuild, code modification, or Git operations.
- NPC inbox message injection (see Section 11).
- Triggering cognition cycles or model calls as part of observation.
- Any action on Sean's behalf without explicit approval.

Read-only inspection (TYPE/GET/MGET/HGET/HGETALL/EXISTS/TTL/PTTL/ZRANGE/LRANGE/SCAN/XRANGE/XLEN, HTTP GET to known endpoints, `docker ps`/`inspect`/container logs, file hashing, metric scraping) is authorized for the engine. **Dedupe keys and incident/work-order writes stay inside `steward:`.**

## 6. Data Sources

The engine reads from these sources. Each adapter must **tolerate unknown** (missing exporter, unreachable endpoint) and **report `unknown`** rather than failing the whole run.

- **Prometheus** (scraped metrics: container restarts, CPU/mem, up-states) — read queries only.
- **cAdvisor / node-exporter / redis-exporter / postgres-exporter** — via Prometheus or direct read.
- **Grafana** — read-only dashboard/data-source queries for context (not authoritative).
- **Backend health APIs** — HTTP GET known endpoints (e.g., `/healthz`, status routes).
- **Redis read adapter** — non-mutating commands scoped to observation; `steward:` writes only.
- **Postgres read** — read-only connection / read replica where available.
- **Structured container logs** — `docker logs` capture / Dozzle-class viewer (read).
- **NPC heartbeat + pair APIs** — read endpoints for `char_001`, `char_306`, and other actors.
- **Disk / RAM / DB health** — node-exporter or host metrics.

If a source is unreachable, the check returns `status: unknown` with the evidence describing the gap. The engine never infers "healthy" from "could not read."

## 7. Initial Check Catalog

Each check returns one or more `Finding`s (Section 8). Reference example uses the **resolved-topic semantic loop** (diagnosed live as PASS in a prior session) to illustrate, but the engine does **not** depend on commit `909ea76`.

### 7.1 `container-health`
- **Inputs:** `docker ps` / compose ps, restart counts, health statuses, Prometheus `up`.
- **Evidence:** container name, restart count, exit/health, last log tail hash.
- **Threshold:** restart_count > N within window, or container not `healthy`/`running`.
- **Severity:** warning/error by impact.
- **dedupe_key:** `container-health:{container}`.
- **On failure:** emit finding; no restart.
- **Permitted output:** finding only. **Prohibited:** any container control.

### 7.2 `npc-heartbeats`
- **Inputs:** NPC heartbeat age from API/Redis.
- **Evidence:** char_id, last heartbeat ts, age seconds.
- **Threshold:** age > expected tick interval × factor.
- **Severity:** warning/error.
- **dedupe_key:** `npc-heartbeat:{char_id}`.
- **Permitted:** finding. **Prohibited:** triggering cognition.

### 7.3 `semantic-loops`
- **Inputs:** pair workspace state for PAIR_IDS (`char_001`, `char_306`): `convergence_state`, `shared_goal`, `resolved_shared_goal`, recent action log.
- **Reference mechanism (read-only description):** a resolved pair whose active `shared_goal` still equals `resolved_shared_goal`, combined with a sync path that insists on a nonblank question and re-applies the same universal fallback ("What happens next in the Federation?"), produces a permanent semantic loop. The check detects: `convergence_state.resolved == true` AND `shared_goal == resolved_shared_goal` AND repeated identical fallback question in recent actions.
- **Evidence:** pair key, both goal values, last N actions, counts of repeated question.
- **Threshold:** resolved + matched + ≥2 repeats.
- **Severity:** warning.
- **dedupe_key:** `semantic-loop:{pair_key}`.
- **Permitted:** finding + (later, Federation-world) work order to investigate. **Prohibited:** editing pair state, inbox injection.

### 7.4 `redis-ttl`
- **Inputs:** sampled keys, TTL/PTTL, key-type census.
- **Evidence:** key, type, TTL (or -1/-2), anomaly flag.
- **Threshold:** unexpected `-1` (no expiry) on keys expected to be ephemeral, or mass near-expiry.
- **Severity:** info/warning.
- **dedupe_key:** `redis-ttl:{pattern}`.

### 7.5 `api-health`
- **Inputs:** HTTP GET known endpoints, latency, status codes.
- **Evidence:** endpoint, status, ms, body snippet hash.
- **Threshold:** non-2xx, or latency > budget.
- **Severity:** warning/error.
- **dedupe_key:** `api-health:{endpoint}`.

### 7.6 `disk-ram-db`
- **Inputs:** node-exporter host metrics, Postgres health/read.
- **Evidence:** usage %, free, DB connection health.
- **Threshold:** usage > threshold; DB unreachable (read).
- **Severity:** warning/error.
- **dedupe_key:** `host-health:{resource}`.

All checks share the contract: **observe, record, flag — never mutate.**

## 8. Structured Finding Schema

```json
{
  "finding_id": "fdg_<uuid>",
  "check_id": "semantic-loops",
  "observed_at": "2026-07-18T23:00:00Z",
  "severity": "warning",
  "status": "open",
  "summary": "Resolved pair char_001/char_306 re-anchored to generic fallback question.",
  "evidence": {
    "pair_key": "npc_pair:char_001__char_306:state",
    "convergence_resolved": true,
    "shared_goal": "deep-signal",
    "resolved_shared_goal": "deep-signal",
    "repeated_question_count": 4
  },
  "affected_entities": ["char_001", "char_306"],
  "dedupe_key": "semantic-loop:npc_pair:char_001__char_306:state",
  "first_seen": "2026-07-18T20:00:00Z",
  "last_seen": "2026-07-18T23:00:00Z",
  "occurrence_count": 12,
  "recommended_action": "Assign investigation work order; consider post-resolution topic transition.",
  "required_capability": "steward:work_order:create",
  "approval_required": true,
  "source_versions": {
    "engine": "steward@0.1.0",
    "backend_observed": "npc_redis_helpers.py@<sha256-when-known>"
  }
}
```

Findings are the single source of truth. Rendering (model or UI) is always derived from a finding, never the reverse.

## 9. Capability Matrix

### Automatically allowed (Federation-world scoped only)
- `steward:incident:create` — record an incident in `steward:` namespace.
- `steward:work_order:create` — create an assigned work-order record (NOT an inbox message).
- `steward:snapshot:create` — capture a read-only state snapshot for evidence.
- `steward:dedupe:touch` — update first/last seen and occurrence count.
- `steward:notify` — emit a notification via the approved channel (no content mutation of external systems).

### Approval-gated (require Sean)
- Any container restart/stop/start/recreate/scale.
- Any Redis mutation outside `steward:`.
- Any deployment, rebuild, or code change.
- Any NPC inbox message injection or cognition trigger.
- Any model-issued command execution.
- Any Git operation.

"Automatic" Steward actions are **world writes**, not infrastructure writes. Infrastructure actions never auto-execute.

## 10. Federation-World Storage Boundary

The engine writes **only** to dedicated keys:

- `steward:incident:*`
- `steward:work_order:*`
- `steward:snapshot:*`
- `steward:dedupe:*`

It must **never** write to:
- `npc:*` / pair / relationship / operator-acknowledgement keys,
- any convergence, shared-goal, or open-question key,
- any inbox or message key.

Storage design note: where a value should be "empty," prefer deletion (consistent with the existing `_pair_hset` convention where `""` → `hdel`) and always re-apply the intended TTL via `expire`. Steward keys use their own TTL policy, independent of pair-state TTL.

## 11. NPC Identity Without Cognition

The Steward has a `char_id` for presentation but is **excluded from the autonomous simulation**:

- No cognition ticks.
- No pair matching / convergence participation.
- No relationships, no open-question orbit, no artifact orbit.
- No inbox; no received/sent message participation.
- Not eligible for operator-directive acknowledgement flows.

It is rendered as `operator_npc` / `system_actor`. For Councilor Watch, which expects pair-shaped data, a **synthetic, read-only presentation adapter** maps engine findings into a pair-like view (e.g., a "steward" pseudo-pair) without creating a real pair workspace or writing pair state. "Assign investigation" = create a `steward:work_order:*` record assigned to the relevant councilor — **not** injecting a message into that councilor's inbox.

## 12. Optional Model Interpretation

The model is an optional, late-stage layer:

- Receives only a **sanitized finding** (no credentials, no raw infra write access).
- May: summarize, explain, translate into Federation-world narrative, suggest.
- May **not**: change `severity`, alter `evidence`, execute tools, approve actions, or produce commands.
- The deterministic `Finding` is stored **beside** the rendering; the rendering is never the source of truth.

This keeps the LLM in the "soft NPC identity" role (Section 2B) and out of the "hard operator engine" role.

## 13. Auxiliary Catalog Tools (all later, none authoritative)

- **Dozzle** — quick live Docker log inspection (read). Useful, not required.
- **Healthchecks** — dead-man's-switch; alert if a scheduled Steward run fails to report.
- **Apprise API / Gotify** — deliver notifications to Sean. Apprise = many services; Gotify = simple self-hosted push.
- **Alerta** — later consolidation/deduplication across many checks.
- **Atlas CMMS** — possible future human-facing work-order cabinet; too heavy for v1.

None of these override the capability policy in Section 5/9. They are outputs or conveniences.

## 14. Deployment Phases

- **S0 — Spec.** This document. (Current.)
- **S1 — Pure engine, frozen fixtures.** Deterministic checks with recorded fixtures; no live I/O.
- **S2 — Read-only adapters.** Prometheus/API/Redis-read/log adapters against the live stack (read-only).
- **S3 — Incident / work-order world writes.** `steward:` namespace only.
- **S4 — Councilor Watch system-actor rendering.** Synthetic read-only presentation adapter.
- **S5 — Optional model interpretation.** Sanitized findings only.
- **S6 — Separately approved operational actions.** Any auto-infra action. **Out of scope**; requires a new security review and explicit authorization.

Each phase is independently reviewable. S6 is deliberately gated away from this spec.

## 15. Acceptance Criteria

- Engine runs each check and emits valid `Finding`s with zero infrastructure mutation.
- Every check tolerates unknown sources (`status: unknown`) without crashing.
- Dedupe prevents alert storms (occurrence count increments; new finding only on key change).
- World writes touch **only** `steward:*` keys (verified by an adapter test that fails on any other key prefix).
- Steward is absent from cognition, pair, relationship, inbox, and operator-ack paths (verified by exclusion tests).
- Scheduler (Dagu/cron) can invoke `steward check <id>` and capture `finding.json`.
- Model layer (if present) cannot alter severity/evidence or execute tools (verified by contract test).
- No read-only check ever performs a write outside `steward:`.

## 16. Future Authorization Gates

1. Scheduler installation (Dagu or verified Cronicle) — separate approval.
2. VPS inventory verification (prove Cronicle exists/healthy, or confirm Dagu target).
3. Live read-only adapter enablement against the 16-container stack.
4. `steward:` world-write enablement (incidents/work orders).
5. Councilor Watch system-actor renderer merge.
6. Optional model interpretation enablement (sanitized-finding contract).
7. First automatic world-write action (e.g., work-order creation) go-live.
8. Any infrastructure auto-action (S6) — new security review.
9. Push/deploy of any Steward code — separate from this docs-only spec.

---

*This document is a specification. It authorizes no code, install, VPS access, commit, push, or deployment. The base commit `730d87e` is unchanged and unmodified by this file.*
