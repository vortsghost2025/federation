# Loop-control patch proposal — char_001 + char_306

Scope: 1 + 3 from your priority list. No model routing changes. No tick interval changes.

## What exists already (do not duplicate)

`_consecutive_send_streak()` and `_recent_artifact_dedup_count()` are present and
the dedup gate already forces `read_artifacts` / `investigate` / `rest` /
`self_improve` once `dedup_count >= 2`.

The artifact-title similarity test (`_is_repetitive_artifact`) catches the
Oracle's recurring title pattern at write-time. It is what is causing the
3rd "Void Oracle analysis" attempt to be logged as `artifact_deferred_dedup`.

## What is missing

The current gates block **send_message** repeats and **artifact write-time**
similarity. They do NOT detect:
- "investigate" 2 ticks in a row on the same topic
- "create_artifact" 2 ticks in a row, where the new titles are **different
  enough to pass similarity** but the agent is doing write-write-write with
  no read/rest/investigate/respond between them
- The agent never sees its **own recent decision shape** in the system
  prompt — the prompt only sees the session transcript of body-level activity

Fix: surface a compact recent-decision-shape list into the system prompt and
add a "last N decisions are all same action shape" check that hard-forks the
decision.

## Patches (concise, no new files)

### Patch 1 — helper `_recent_decision_shapes(r, n=5)`

New function near `_consecutive_send_streak` (~line 1226).

Returns `["create_artifact","create_artifact","investigate"]` — a list of
the last `n` decisions' category, newest first. Backs onto `_recent_decisions`
already in the file.

### Patch 2 — inject into decide_action() system prompt

In `decide_action(context, r=None)` right after the existing
`force_constraint` lines (~line 1520), add:

```
recent_shapes = _recent_decision_shapes(r, 5)  # newest first
if recent_shapes:
    parts.append(
        "── Your recent decisions (newest first) ──\n  "
        + "\n  ".join(f"{i+1}. {s}" for i, s in enumerate(recent_shapes))
        + "\nDo not repeat the same action shape unless new evidence appeared."
    )
```

This goes **into the prompt** as a soft hint — the agent sees it.

### Patch 3 — runtime cap on consecutive same-shape actions

In `decide_action()`, after the existing `force_constraint` block, add:

```python
if r is not None:
    shapes = _recent_decision_shapes(r, 3)  # last 3 decisions
    if len(shapes) >= 2 and all(s == shapes[0] for s in shapes):
        # Same action shape 2–3 times in a row → hard ban a 4th
        banned = shapes[0]
        allowed = [a for a in (
            "create_artifact","write_code","send_message",
            "read_artifacts","investigate","rest","self_improve",
        ) if a != banned]
        force_constraint += (
            f"\n\nLOOP-BREAK (runtime): You have picked "
            f"'{banned}' on each of the last {len(shapes)} ticks. "
            f"You MUST NOT pick '{banned}' this turn. "
            f"Pick one of: {', '.join(allowed)}."
        )
```

Logging: at the start of the function, if the cap fires, log:
```
logger.warning("[%s] loop_break action=%s streak=%d", CHAR_ID, banned, len(shapes))
```

### Patch 4 — log tag on execute side (visibility only)

In `execute_decision` (around line 1639), the existing
`logger.info("[%s] Decision: %s — %s"...)` is already there. No edit needed — 3 already gives us the trace.

## What the patch does NOT touch

- Nothing in `_partner_id`, `_session_*`, `_is_repetitive_artifact`,
  `_acknowledge_inbox`. Those work as intended.
- No changes to the LLM call chain (`call_llm`, fallback, timeouts).
- No changes to `TICK_INTERVAL`, `PRIMARY_MODEL`, `FALLBACK_MODEL_*`, or any
  Docker env. No compose changes. No service restart loop. Just edit the
  Python file.

## Deploy mechanism

This file is live-mounted (`/docker/federation-game/npc-agent:/app:ro`).
So:

1. Edit `S:/federation/federation-game/npc-agent/npc_agent.py`
2. `scp` to `/docker/federation-game/npc-agent/npc_agent.py`
3. **No container restart needed** — the file gets reimported on next NPC
   loop iteration? NO: the agent is already running with `npc_agent.py`
   loaded. We **DOCKER RESTART** both NPC containers.
4. Verify with `md5sum` on host + each container:

```
ssh root@187.77.3.56 'md5sum /docker/federation-game/npc-agent/npc_agent.py'
ssh root@187.77.3.56 'docker exec federation-game-npc-agent-001-1 md5sum /app/npc_agent.py'
ssh root@187.77.3.56 'docker exec federation-game-npc-agent-306-1 md5sum /app/npc_agent.py'
```

5. Watch 10 ticks per agent (~10 minutes). Pass criteria you specified:

   - no more than 2 `create_artifact` rows in a row for either
   - char_306 does not attempt the same "Void Oracle analytical report" 3 ticks running
   - char_001 alternates between write/read/investigate/respond/rest over 10 ticks
   - partner messages still work
   - artifact creation still works when genuinely new

## Failure modes I expect

- The cap may over-fire if decision-shape list is wrong: e.g. one of the
  histories shows the agent just produced a successful artifact and now
  generating a follow-up. To soften: only ban the next occurrence, not all
  of banned. My patch already does that (ban this turn only).
- LLM might still pick banned action despite constraint. If so, fall back —
  re-call with explicit JSON parse override in a follow-up patch. **Not in
  this scope.**

## Files I will edit

```
S:/federation/federation-game/npc-agent/npc_agent.py
```

Only this one file. ~25 lines added across 3 spots.
