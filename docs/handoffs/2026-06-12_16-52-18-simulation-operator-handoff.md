# Simulation Operator Handoff

Date: `2026-06-12 16:52:18`
Author: `OpenCode / gpt-5.4`
Scope: supervised autonomous simulation tick hardening for Federation VPS

## Goal

Stabilize autonomous simulation ticks so the system behaves like a simulation operator instead of a passive endpoint:

- supervise tick lifecycle
- detect stale or blocked runs
- validate NPC output
- recover safely with fallback actions
- expose operator status and manual trigger endpoints
- reduce end-to-end tick runtime so the supervisor can complete reliably

## Files Changed

Primary operator integration:

- `federation-game/backend/simulation_operator.py`
- `federation-game/backend/tick_engine.py`
- `federation-game/backend/routes/simulation.py`
- `federation-game/backend/tick_watchdog.py`

Runtime reduction and progress reporting:

- `federation-game/backend/npc_cognition.py`
- `federation-game/backend/llm_router.py`
- `federation-game/backend/simulation_engine.py`
- `federation-game/backend/narrator.py`

## Commit Boundary Note

The live VPS received one additional runtime-only hotfix in `federation-game/backend/llm_router.py` to shorten leader and specialist provider timeouts.

That file has overlapping local edits in the working tree, so the clean handoff commit intentionally does not absorb that wider file diff.

If another agent needs the live behavior exactly, they should use this document plus the commit and reapply the timeout reductions described here:

- leader timeouts: `20/30/25` to `8/10/12`
- specialist timeouts: `18/15/20` to `6/8/10`

## What Was Added

### 1. Simulation operator layer

Added `simulation_operator.py` as the supervisor around the existing pipeline.

It now:

- builds the NPC list from live `game_state`
- runs `npc_autonomy.simulation_tick(...)`
- validates output for missing state, empty turns, duplicate actions, runaway loops, and idle NPCs
- injects safe fallback `rest` decisions for idle NPCs
- runs the richer downstream engine with `simulation_engine.autonomous_tick(...)`
- records structured operator status and event logs in Redis

Redis keys written by operator:

- `npc_turns`
- `npc_memory_events`
- `npc_tool_events`
- `simulation_operator_status`
- `simulation_operator_alerts`
- `simulation_operator_recovery`
- `simulation_operator_history`

### 2. Tick engine integration

Replaced the autonomous tick’s direct `simulation_tick(...)` call with `run_simulation_operator_tick(...)` inside `tick_engine.py`.

This keeps the existing entrypoint and worker behavior while upgrading the execution path.

### 3. New endpoints

Added:

- `GET /simulation/operator/status`
- `POST /simulation/operator/tick`

Also fixed the route-level locking bug in `/simulation/autonomous/tick` and the new operator trigger path.

### 4. Stale watchdog lease recovery

Fixed `tick_watchdog.try_start_tick()` so it clears stale active lease keys before attempting `SET NX`.

Without this fix, a crash or restart could leave the watchdog blocking all new ticks until lease expiry.

### 5. Faster supervised tick profile

For supervised ticks only:

- cognition is capped to `1` LLM call per tick
- ambient cognition is disabled
- leader and specialist timeouts were cut down substantially
- narration LLM is disabled and replaced with deterministic fallback narration
- progress is emitted throughout the simulation engine phases

## Root Causes Found

### Root cause 1: route lock collision

The route was pre-acquiring `_tick_lock` before starting the background thread. The background thread then immediately failed on the same lock with `Legacy lock failed`.

### Root cause 2: stale watchdog lease

The watchdog detected stale state but still attempted `SET NX` against an uncleared active key. That prevented a new lease from being acquired after a crash/restart.

### Root cause 3: slow cognition chain

Worst-case cognition per leader call was effectively:

- NIM primary timeout
- NIM fallback timeout
- Ollama fallback attempt
- OpenRouter fallback timeout

That was enough to push supervised ticks well past a minute.

### Root cause 4: narration LLM inside every supervised tick

Narration was doing its own full LLM route during Step 9, and in the observed run it alone consumed about a minute.

## Tests And Verification Performed

### Local compile checks

Ran `python -m py_compile` successfully on:

- `federation-game/backend/simulation_operator.py`
- `federation-game/backend/tick_engine.py`
- `federation-game/backend/routes/simulation.py`
- `federation-game/backend/tick_watchdog.py`
- `federation-game/backend/npc_cognition.py`
- `federation-game/backend/llm_router.py`
- `federation-game/backend/simulation_engine.py`
- `federation-game/backend/narrator.py`

### Local import check

Ran:

```bash
python -c "import simulation_operator; print('simulation_operator import ok')"
```

Result: import succeeded.

### VPS deployment steps used

- copied touched files to `/docker/federation-game/backend/`
- cleared backend `__pycache__`
- restarted `federation-game-backend-1`

### VPS endpoint verification

Verified with Python HTTP probes inside the backend container:

- `GET /simulation/operator/status`
- `POST /simulation/operator/tick`
- `GET /simulation/autonomous/status`

### Observed runtime before fast-path changes

Completed supervised tick:

- autonomous status duration: about `103.65s`
- operator summary duration: about `98178.6ms`

Observed expensive phases:

- cognition: about `32756.8ms`
- narration: about `60486.9ms`

### Observed runtime after fast-path changes

Completed supervised tick:

- autonomous status duration: about `19.24s`
- operator summary duration: about `11804.2ms`

Observed changes:

- cognition dropped to `14.6ms` in the last verified completed tick because no trigger fired
- narration stayed deterministic fallback with about `1.4ms`
- operator reached `status: completed`
- `stalled: false`

## Start vs Finish

### Start state

- no dedicated simulation operator endpoint
- autonomous route could falsely deadlock itself
- watchdog could block new ticks after stale lease scenarios
- supervised/manual tick path could sit in `running` for roughly 100 seconds
- operator-style progress and recovery visibility did not exist

### Finish state

- supervised operator layer exists and is wired into the autonomous path
- manual trigger endpoint exists
- operator status endpoint exists
- route-level lock collision is fixed
- stale watchdog lease recovery is fixed
- operator emits progress through major simulation phases
- supervised ticks run with a faster cognition/narration profile
- verified live completion on VPS at roughly 19 seconds instead of roughly 104 seconds

## Live Production Notes

VPS target used during this work:

- `root@187.77.3.56`

Backend container:

- `federation-game-backend-1`

One validator warning remained non-fatal in the final verified tick:

- `char_403` repeated `react_to_events` for 6 turns

This is surfaced as a warning, not a failure.

## Recommended Next Steps

1. Add a dedicated anti-loop mitigation for repeated `react_to_events` NPCs such as `char_403`.
2. Consider applying the faster cognition profile selectively to worker-driven autonomous ticks if throughput matters more than richer LLM reasoning.
3. If richer narration is still desired, move LLM narration to a non-blocking post-tick job instead of the critical path.

## Commit Reference

This document was created so another agent can continue from either:

- this handoff document
- the matching git commit created with the same timestamped handoff work

If credits run out, point the next agent to:

- `docs/handoffs/2026-06-12_16-52-18-simulation-operator-handoff.md`
