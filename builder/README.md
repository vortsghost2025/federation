# Federation Builder Agent

A long-running observer / operator process that lives next to the
Federation Game simulation on the VPS and gives us (Sean and Kilo) a
continuous second pair of eyes on every NPC turn.

## Goals

- Watch all 39 NPCs (the 2 persistent + 37 dynamic) without having to
  stare at the spectator page.
- Convert observations into *approval-gated* draft capability requests
  so we can intervene (e.g. propose a new area when the pair is stuck,
  spawn an investigation when no one has moved in N minutes).
- Surface a simple CLI for the human operator to approve or reject
  drafts, and a small HTTP RPC for remote control.
- Be idempotent, restart-safe, and replayable from disk.

## Non-Goals

- Auto-deploy without approval. *Every* non-read-only action goes
  through the approval queue.
- Replace the existing capability-request flow. We add capability
  requests via the same `create_capability_request` Python helper the
  work loop uses, with `requester_id="builder"`.
- Mutate Redis DB0 schema. We only read.

## Layout

```
builder/
  __init__.py
  event_collector.py    # Stage 1: poll Redis decisions -> JSONL events
  state.py              # Stage 1: on-disk state (pending queue + stats)
  redis_discovery.py    # Stage 1: locate the federation-game redis
  builder_agent.py      # Stage 2: rule engine, produces approval-gated drafts
  cli.py                # Stage 2: list-pending / approve / reject / status
  rpc_server.py         # Stage 3: FastAPI server for remote control
  docs/                 # Design notes for each stage
  events/               # JSONL event streams (rotated by size)
  pending/              # Mirror of state.pending_requests as JSON files
  tests/                # pytest suite, runs against an in-memory fake redis
```

## Stage 1: Observation only

`event_collector.py` runs as a background process:

```
EventCollector.run_forever()
   |
   +--> every poll_interval_s:
            redis.zrevrange("npc_decisions:<char_id>", 0, 49)
            for each decision newer than our cursor:
                write JSONL line to events/events-<ts>.jsonl
                advance cursor
            rotate file when it crosses high_water_bytes
```

It never touches anything but the local `events/` directory and Redis
read-only commands.

`state.py` provides a tiny atomic-write JSON store with a versioned
schema (`version: 1`) and migration hooks for future bumps.

`redis_discovery.py` finds the live Redis container without taking a
hard dependency on the federation_game shared library.

## Stage 2: Approval-gated drafts (next)

The rule engine reads from `events/`, applies a small set of heuristics
(e.g. "no area founded in the last 30 minutes", "both councilors idle"),
and emits a *draft* capability request into `state.pending_requests`.
Nothing is sent to the simulation until the operator approves.

## Stage 3: RPC + CLI (next)

A FastAPI server exposing:

- `GET  /status`           — current stats + pending count
- `GET  /pending`          — list pending drafts
- `POST /pending/<id>/approve` `{ "by": "sean" }`
- `POST /pending/<id>/reject` `{ "by": "sean", "reason": "..." }`
- `POST /ask`              — free-form question to the agent

And a `builder_cli.sh` wrapper that calls the RPC and prints the
response.

## Safety & Observability

- All capability requests flow through the existing
  `create_capability_request` helper; the builder is just another
  requester.
- Each draft carries `evidence` (the events that triggered it) and a
  `rationale` (the rule that fired).
- The heartbeat script logs pending count + last draft time so we know
  if the agent is alive.
- All long-running processes are owned by `background_process` and
  restart on VPS reboot.

## Testing

- All components have unit tests in `tests/` using a fake redis client
  so they run in seconds without needing the live container.
- `pytest builder/tests/` should pass before any merge.
- Integration smoke tests live in `tests/integration/` and hit the
  Docker-hosted Redis with `REDIS_TEST_DB=1` (so we never pollute DB0).
