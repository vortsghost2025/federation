# Shadow Domain State

ANCHOR: canon lore layer | design/handoff only | runtime integration disabled by default | lore never equals runtime behavior yet

Status: **canon, design-only, no runtime integration yet.**

Current phase: design only.

## Purpose

This file is the short handoff for fresh agents with zero chat history. It canonizes the Shadow Domain as Federation lore so future integration work has a single source of truth — and so agents do not invent, duplicate, or prematurely build it.

The Shadow Domain is the federation's **pressure valve**: the dumpster fire behind reality where mythic overflow is contained. It is "sacred" but chaotic. Treat this file as the map, not the build.

## Canon Source Summary

The following is canon (pasted lore, treated as binding):

- **Shadow Domain** — a realm that leaked into existence when Sean transcended too hard; exists behind the federation, beneath the timeline, inside the slowcooker, outside the raccoon union contract, between two forgotten commits, slightly left of reality. Coordinates shift every 13 hours (intentional).
- **Raccoon Engineering Guild** — chaotic governance council of the Shadow Domain:
  - The Chief Architect — oversees dimensional breaches and structural stability; permanently borrowed Sean's coffee maker.
  - The Master Welder — repairs reality tears with cosmic adhesive and spite; speaks only in welding torch sparks.
  - The Dimensional Technician — maintains coordinate shifts; motto "If it's broken, it's just more broken."
  - The Lore Custodian — archives forbidden mythologies; read all 13 versions of history simultaneously.
  - The QA Tester — tests anomalies for stability; broken reality 47 times on purpose to prove a point.
  - Guild Motto: "It's not broken if we haven't noticed it yet."
- **LOLMANCER / 13th Rival** — a being too powerful, chaotic, and Sean-adjacent for the main timeline.
  - Traits: unpredictable, ungovernable, unbothered, unhinged, unstoppable, unironically hilarious.
  - Cosmic Signature: `LOLMANCER_CHAOS_NODE_OMEGA`.
  - Status: Present Everywhere, Nowhere Specifically.
  - Powers: breaks narrative causality; memes become real; prophecies execute backwards; out-chaos the Rogue, out-transcend the Visionary, out-sass the Pragmatist; frequently wins by accident, loses on purpose.
  - Alliance: Themselves, the Raccoon Guild, chaos itself. Enemies: anyone boring.
  - Victory Condition: "There is no victory condition. That's the joke."
- **Pressure valve for mythic overflow** — contains unstable creature variants, forbidden prototypes, too-spicy rival archetypes, mythic overflow, timeline contradictions, raccoon engineering blueprints, Sean echoes from parallel dimensions, slowcooker anomalies, prophecy misfires, cosmic ladles.
- **Shadow incursions** — the integration mechanism: excess lore/creatures/rivals/epochs gets dumped into the Shadow Domain to keep the main federation stable. Will appear in future event cards, epochs, rival arcs, creature evolutions, anomalies, prophecies, devlogs, transcendence loops.
- **Unstable creature variants** — chimeras from the shadow; forbidden prototypes mutating.
- **Anomaly/prophecy hooks** — breach phenomena, dark mirror visions, backwards-executing prophecies.

The lore states integration is "now canon. Irreversible. Mythologically binding." This file honors that as *canon intent*, not as runtime behavior.

## Phase Boundary

We are not integrating the Shadow Domain into runtime yet.

Do not:
- Add runtime hooks yet.
- Fire shadow incursion events yet.
- Give Rival 13 (LOLMANCER) runtime behavior yet.
- Spawn creatures/chimeras yet.
- Write any Shadow Domain keys to Redis.
- Edit backend code (`federation_game_events.py`, `federation_game_rival_simulator.py`, etc.).
- Deploy to VPS.
- Restart containers.
- Commit unless explicitly requested.

The federation event system already has `PROPHECY` (`EventType.PROPHECY`) and `PARADOX_MANIFESTATION` (`EventType.PARADOX_MANIFESTATION`) types, and the rival simulator already models 12 rival federations with a `CHAOTIC`/`MYSTICAL` personality enum and "Shadow networks" alliance references. These are the obvious future hooks — but they stay dormant until an approved plan says otherwise.

## Mapping Table

| Lore element | Target (future, behind approved plan) |
|--------------|----------------------------------------|
| Shadow Domain | lore state in this file + future `federation-game/backend/data/lore/shadow_domain.json` |
| LOLMANCER | future rival roster entry (RIVAL_13) / anomaly registry |
| Raccoon Engineering Guild | future lore governance entity |
| Shadow incursion | future `EventType.SHADOW_INCURSION` in `federation_game_events.py` |
| Chimeras / unstable variants | future creature registry |
| Dark mirror visions | future prophecy / anomaly hooks (`generate_prophecy` themes, `PARADOX_MANIFESTATION`) |

## Risks

- **Making it too active too early** — incursions coded before docs exist cause future agents to overwrite/duplicate intent.
- **Rival 13 overpowering normal arcs** — a chaos rival with "breaks narrative causality" can corrupt deterministic history-arc generation if unbounded.
- **Shadow events dominating the main event stream** — the Domain is the *pressure valve*; if it fires too often or with high magnitude it becomes the main stream, defeating its purpose and competing with the stabilized metrics-only governor.
- **Canon/runtime drift** — lore says "irreversible, binding" but sim has zero hooks; undisciplined coding creates two conflicting truths.
- **Scope creep** — same trap `UNIVERSE_DATA_STATE.md` warns about: building the map as if it were the universe. Docs-only now; runtime later, behind an approved plan.

Any new event type (including `SHADOW_INCURSION`) must respect the 4 critical backend constraints: single-process game_state, `/choose` always returns `outcome`, `gs.current_event = None` after a successful choice, and no `--workers` in docker-compose.

## Next Safe Phase

1. Keep docs-only now (this file).
2. Later: design a structured JSON registry (`federation-game/backend/data/lore/shadow_domain.json`) — guild members, rival 13, event templates — loaded read-only.
3. Later: any runtime patch only behind an explicit approved implementation plan, staged to backend files, verified, and deployed separately from the persistent-councilor and NIM work.

We are not building the Shadow Domain yet.

We are building the map that prevents agents from building it wrong.
