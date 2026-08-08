# Genesis Replay Harness

Offline, **read-only** proof that the 4 WE4FREE layers (L1 Symmetry, L2 Constraint,
L3 Phenotype, L4 Drift) help an NPC *before* any flag is flipped in production.

## Guarantees
- Never touches the live 60s tick, `game_state`, or write path.
- For the whole replay, `L1._redis` is monkeypatched to an in-memory store, so even
  accidental live calls are impossible from this host.
- `--capture-from-redis` does a **read-only** `HGETALL npc:{id}` then disconnects.
  Nothing is written to Redis.

## Run
```powershell
cd S:\federation\federation-game\backend

# Replay a captured/sample NPC (no live Redis needed)
python -m genesis.replay_harness --capture-file genesis/samples/npc_east_adam.json --dump-report

# Prove L4 recovery triggers on a divergent NPC
python -m genesis.replay_harness --capture-file genesis/samples/npc_east_adam.json --diverged

# Capture a REAL npc live (read-only), then replay the dump
python -m genesis.replay_harness --capture-from-redis east_adam --dump-to ./captures/east_adam.json
python -m genesis.replay_harness --capture-file ./captures/east_adam.json

# Replay a FULL captured VPS tick (all 39 NPCs) from a read-only JSON — no live connection
python -m genesis.replay_harness --capture-real-tick ./captures/vps_real_tick.json --dump-report
```

## Note on the REAL production schema (learned 2026-07-18)
The live VPS does NOT store per-NPC `affiliation`/`mood`/`decree_alignment` in Redis.
Real keys are `npc_state:{id}` (corruption/rumor/status) and `npc_actions:{id}`
(zset of `{action_type, mood, ...}`). The harness DERIVES `affiliation` from the dominant
recent `action_type` and `decree_alignment` from `1 - rumor_level`. NPCs with no captured
actions read drift 0.0 (unknown). A NPC that only ever `rest`s reads high drift and triggers
L4 recovery — that is the layers correctly flagging a stalled NPC.

## Reading the report
- `L1 symmetry` — snapshot freezes and round-trips; aliveness is a real Redis probe, not mtime.
- `L2 lattice` — how many of the 11 options survive the constraint lattice. Violations listed.
- `L3 phenotype` — is the chosen action coherent with this NPC's attractor?
- `L4 drift` — TVD of recent behavior vs attractor. Under `tolerance` = stable; over = recovered.
- `BASELINE vs GENESIS` — what `random.choices` would pick vs the constraint-governed choice.
- `CONSTITUTIONAL: True` means the layers behaved (no uncontrolled divergence).

## Next step (awaiting Sean's go)
Wire `run_replay`-style logic into `npc_autonomy._process_single_npc` behind
`GENESIS_LAYERS_ENABLED`, once replays against REAL captured ticks look good.
