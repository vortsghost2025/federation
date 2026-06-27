# Institutions Recovery Design

## Goal

Move Federation from "persistent individual councilors" to "persistent institutions with durable roles, memory, and workflows" without breaking the live councilor substrate that is now running on the VPS.

## Current Baseline

The following pieces are now live and should be treated as the starting point, not as future work:

- `npc-agent` containers for `char_001` and `char_306`
- `routes/agents.py` for moderator and councilor messaging
- `npc_world_snapshot.py` writing `npc_world_snapshot:global`
- `councilor_bridge.py` syncing councilor artifacts into the main simulation
- `council-chat.html` as the direct moderator surface

The system currently supports persistent councilor cognition, artifact production, and message routing. What it does not yet support is durable collective organization. Redis still has no `institution:*` or `role:*` state.

## Problem Statement

Right now Federation has memory-bearing NPCs that can think, write, and message. They still act as individuals. There is no durable structure for:

- assigning responsibilities across ticks
- preserving institution-level intent
- tracking open work
- routing proposals through a decision process
- remembering which role is accountable for which domain

That keeps the simulation at the "interesting characters" layer instead of the "self-organizing civilization" layer.

## Design Principles

1. Build on the live councilor substrate instead of replacing it.
2. Make institution state explicit in Redis with stable key patterns.
3. Keep workflows idempotent so repeated worker ticks do not duplicate actions.
4. Separate role memory from character memory.
5. Start with a small number of institution types and repeatable workflow templates.

## Proposed Architecture

### 1. Institution Registry

Add a first-class institution registry keyed by stable institution ids.

Suggested Redis shape:

- `institution:index` -> set of institution ids
- `institution:{id}` -> hash with `name`, `kind`, `mandate`, `status`, `created_at`
- `institution:{id}:members` -> set of `char_id`
- `institution:{id}:roles` -> set of role ids
- `institution:{id}:memory` -> list of institution-level records

Initial institution kinds:

- council
- ministry
- research body
- military command
- trade body
- preservation body

### 2. Role System

Roles are the unit of responsibility. NPCs can hold a role inside an institution, and the role survives reassignment.

Suggested Redis shape:

- `role:index` -> set of role ids
- `role:{id}` -> hash with `institution_id`, `title`, `scope`, `authority`, `holder_char_id`, `status`
- `role:{id}:queue` -> list of assigned work items
- `role:{id}:memory` -> list of role-specific notes, decisions, and pending constraints

This is the critical separation: Archimedes may be the current holder of a role, but the role itself carries the institution's continuity.

### 3. Workflow Layer

Institutions need repeatable pipelines instead of one-off message passing.

Suggested initial workflow types:

- proposal review
- crisis response
- alliance request
- sector claim review
- law or proclamation drafting

Suggested Redis shape:

- `workflow:index` -> set of workflow ids
- `workflow:{id}` -> hash with `type`, `institution_id`, `status`, `created_at`, `updated_at`
- `workflow:{id}:steps` -> ordered list of step objects
- `workflow:{id}:events` -> append-only event log

Each workflow should define:

- the triggering event
- required roles
- transition conditions
- timeout or stale-state handling
- output artifact type

### 4. Institution Memory

Artifacts already exist, but they are still mostly authored as individuals. Institutions need a parallel memory stream.

Suggested memory categories:

- mandate
- standing policy
- open matters
- recent decisions
- unresolved disputes
- external relationships

Suggested Redis shape:

- `institution:{id}:ledger` -> append-only institution decisions
- `institution:{id}:brief` -> latest summarized operational brief
- `institution:{id}:relationships` -> hash keyed by faction or institution id

This gives each institution a durable state surface that can be summarized into prompts.

### 5. Worker Integration

The worker already runs spatial and councilor sync logic. Extend it with an institution pass after the councilor bridge.

Recommended future order inside `run_tick()`:

1. spatial tick
2. councilor world snapshot
3. councilor bridge sync
4. institution workflow pass
5. autosave

The institution workflow pass should:

- create workflow instances from eligible events
- assign work to roles
- advance active workflows one step at a time
- emit institution artifacts back into the existing bridge and narrator surfaces

## Integration Points

### Councilor Agents

Councilors remain the first persistent actors, but they stop being only "special NPCs" and become role holders, advisors, or institution members.

### Existing Artifacts

Keep `federation_councilor_artifacts`, but add institution metadata when relevant:

- `institution_id`
- `role_id`
- `workflow_id`
- `artifact_kind`

### Existing Messages

Messages can stay in Redis lists for now, but institution workflows should consume them as triggers rather than treating them as the final coordination layer.

## Safety and Idempotency Rules

1. No workflow step should create duplicate artifacts on repeated ticks.
2. Role assignment changes must be explicit state transitions, not implicit prompt side effects.
3. Institution summaries must be regenerated from durable state, not treated as the source of truth.
4. Any new worker hook must preserve the single-process backend constraint.

## Non-Goals

- full institution simulation for every NPC at once
- replacing the current councilor bridge
- introducing multi-worker backend execution
- migrating everything away from Redis before the workflow model is proven

## Recommended Rollout

### Phase 1

Introduce the Redis schema for institutions and roles. Seed a minimal set of institutions and bind the two live councilors into explicit roles.

### Phase 2

Add one workflow template, preferably proposal review, end to end.

### Phase 3

Expose institution state in spectator and moderator surfaces.

### Phase 4

Expand to additional institutions, workflows, and non-councilor role holders.

## Immediate Next Build Target

The first implementation slice should be:

- seed `institution:*` and `role:*`
- bind `char_001` and `char_306` into roles
- add one worker-driven workflow type
- emit institution-tagged artifacts into the existing bridge

That is the smallest change that proves Federation can move from persistent people to persistent organizations.
