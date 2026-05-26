# Federation Simulation API Reference

Generated from full source-code analysis of `main.py` (5796 lines), `simulation_engine.py` (2448 lines), `npc_autonomy.py` (2376 lines), `faction_dynamics.py` (409 lines), `worker.py` (631 lines), `npcs.py` (1417+ lines), and `federation_game_events.py` (1549 lines).

---

## Endpoint Map

| Method | Path | Lines in main.py | Purpose |
|--------|------|-------------------|---------|
| POST | `/simulation/tick` | 4372–4393 | Trigger NPC autonomy tick (async) |
| GET | `/simulation/tick/status` | 4395–4402 | Poll tick completion |
| POST | `/simulation/autonomous/tick` | 4403–4426 | Trigger full autonomous tick (async) |
| GET | `/simulation/autonomous/status` | 4427–4434 | Poll autonomous tick completion |
| GET | `/simulation/status` | 4436–4513 | World state + faction dynamics + cascade + events + NPC summary |
| GET | `/simulation/factions` | 4516–4571 | Detailed per-faction data |
| GET | `/simulation/npcs/activity` | 4574–4665 | NPC activity feed |
| GET | `/simulation/events` | 4668–4702 | World + cascade + broadcast events |
| GET | `/simulation/npc-quests` | 4703–4729 | NPC quest log |
| GET | `/simulation/npc-quests/{char_id}` | 4730–4754 | Per-NPC quest summary |
| GET | `/simulation/faction-tech` | 4755–4779 | All faction tech research |
| GET | `/simulation/faction-tech/{faction_id}` | 4780–4807 | Per-faction tech detail |
| GET | `/simulation/faction-tech-log` | 4808–4828 | Recent faction tech events |
| GET | `/simulation/choice-resolutions` | 4829–4852 | Faction choice resolution stats |
| GET | `/simulation/choice-resolutions/detail` | 4853–4877 | Detailed resolution history |
| GET | `/simulation/choice-resolutions/{faction_id}` | 4878–4910 | Per-faction choice voting |
| GET | `/simulation/cognition/stats` | 4911–4935 | LLM cognition layer stats |
| GET | `/simulation/faction-brains` | 4936–4968 | Faction brain states |
| GET | `/simulation/cascade-chains` | 4969–4993 | Cascade chain propagation |
| GET | `/simulation/faction-treaties` | 4994–5024 | Active faction treaties |
| GET | `/simulation/diplomacy-summary` | 5025–5062 | Diplomacy summary |
| GET | `/simulation/nim-stats` | 5063–5086 | NVIDIA NIM LLM client stats |

---

## 1. GET `/simulation/status`

**Source:** main.py lines 4436–4513  
**Redis round-trips:** 3 pipelined batches (not 10+ sequential)

### Response Structure

```json
{
  "world_state": {
    "tension_level": 50,
    "resource_abundance": 60,
    "threat_level": 30,
    "stability": 65,
    "morale": 55,
    "anomaly_activity": 20,
    "_meta": {
      "condition_labels": {
        "tension_level": "Elevated Tension",
        "resource_abundance": "Moderate Resources",
        "threat_level": "Low Threat",
        "stability": "Stable",
        "morale": "Moderate Morale",
        "anomaly_activity": "Minimal Anomaly"
      },
      "last_updated": 1748030400.0
    }
  },
  "faction_dynamics": {
    "diplomatic_corps": {
      "faction": "diplomatic_corps",
      "display_name": "Diplomatic Corps",
      "member_count": 6,
      "cohesion": 0.65,
      "influence": 0.45,
      "standing": 0.70,
      "vigilance": 0.30,
      "avg_mood": "cautious",
      "activity_rate": 0.55,
      "decisions_this_tick": 4,
      "events_this_tick": 2,
      "ts": 1748030400.0
    },
    "research_division": { "...": "same shape" },
    "security_council": { "...": "same shape" },
    "cultural_unity": { "...": "same shape" },
    "shadow_syndicate": { "...": "same shape" }
  },
  "cascade_summary": {
    "temperature": 0.35,
    "active_chains": 1,
    "total_propagations": 7,
    "recent_reactions": [
      {
        "source": "diplomatic_corps",
        "target": "research_division",
        "type": "diplomatic_pressure",
        "magnitude": 0.15,
        "ts": 1748030395.0
      }
    ]
  },
  "recent_events": [
    {
      "type": "diplomatic_crisis",
      "severity": 2,
      "description": "Tensions rise between factions over resource allocation.",
      "faction": "security_council",
      "ts": 1748030350.0
    }
  ],
  "npc_activity_summary": {
    "total_npcs": 35,
    "mood_distribution": {
      "curious": 8,
      "cautious": 6,
      "determined": 5,
      "anxious": 4,
      "hopeful": 4,
      "suspicious": 3,
      "indifferent": 3,
      "resolute": 2
    },
    "total_decisions": 23
  },
  "pending_items": {
    "laws": 2,
    "treaties": 1,
    "research": 3,
    "faction_laws": 1,
    "active_treaties": 4
  },
  "last_tick_timestamp": "2025-05-23T22:00:00Z",
  "last_tick_result": {
    "npc_decisions": 23,
    "events_generated": 3,
    "world_state_changes": { "morale": -2, "stability": +1 },
    "faction_updates": ["diplomatic_corps", "research_division"]
  },
  "faction_ai_last_tick": {
    "diplomatic_corps": {
      "tick": 1748030400,
      "decisions": 2,
      "priority": "economic"
    }
  },
  "cascade_temperature": 0.35
}
```

### Field Source Breakdown

| Field | Computed By | Redis Key | Notes |
|-------|-------------|-----------|-------|
| `world_state` | `simulation_engine.py` step 6 (game events), step 3 (world→game bridge) | `federation:world_state` HASH | 6 conditions, each 0–100 |
| `world_state._meta.condition_labels` | `npc_autonomy.py` `get_condition_label()` | Computed from value ranges | Returns label string based on value bracket |
| `faction_dynamics` | `faction_dynamics.py` `compute_faction_dynamics()` | `faction_dynamics:{fid}` HASH | Computed from NPC decisions + broadcast events per tick |
| `cascade_summary` | `simulation_engine.py` cascade system | `cascade_reactions` ZSET | Tracks faction-to-faction propagation chains |
| `recent_events` | `npc_autonomy.py` `get_world_events()` | `npc_world_events` ZSET | Last 20, JSON-parsed |
| `npc_activity_summary` | Aggregation from Redis pipelines | `npc_mood:{cid}`, `npc_decisions:{cid}` | Batched: moods + decisions per tick |
| `pending_items` | Count of unconsumed political items | `pending_laws`, `pending_treaties`, `pending_research` LISTs | Consumed by step 4b of `autonomous_tick()` |
| `last_tick_result` | Stored at end of `autonomous_tick()` | `sim_tick_log` ZSET | JSON-serialized result of last tick |
| `faction_ai_last_tick` | Faction AI system | `faction_ai:last_tick` HASH | Per-faction tick metadata |
| `cascade_temperature` | Cascade system | `cascade_temperature` STRING | 0.0–1.0, increases with propagations |

---

## 2. GET `/simulation/factions`

**Source:** main.py lines 4516–4571  
**Redis round-trips:** 2 pipelined batches (batch actions + batch power for all factions)

### Response Structure

```json
{
  "diplomatic_corps": {
    "id": "diplomatic_corps",
    "name": "Diplomatic Corps",
    "dynamics": {
      "faction": "diplomatic_corps",
      "display_name": "Diplomatic Corps",
      "member_count": 6,
      "cohesion": 0.65,
      "influence": 0.45,
      "standing": 0.70,
      "vigilance": 0.30,
      "avg_mood": "cautious",
      "activity_rate": 0.55,
      "decisions_this_tick": 4,
      "events_this_tick": 2,
      "ts": 1748030400.0
    },
    "stances": {
      "research_division": {
        "value": 0.60,
        "label": "cordial",
        "trend": 0.05
      },
      "security_council": {
        "value": 0.35,
        "label": "tense",
        "trend": -0.10
      },
      "cultural_unity": {
        "value": 0.70,
        "label": "allied",
        "trend": 0.02
      },
      "shadow_syndicate": {
        "value": 0.15,
        "label": "hostile",
        "trend": -0.08
      }
    },
    "recent_actions": [
      {
        "type": "propose_treaty",
        "target": "cultural_unity",
        "details": "Proposed mutual defense pact",
        "ts": 1748030350.0
      }
    ],
    "power": 0.55
  },
  "research_division": { "...": "same shape" },
  "security_council": { "...": "same shape" },
  "cultural_unity": { "...": "same shape" },
  "shadow_syndicate": { "...": "same shape" }
}
```

### Field Source Breakdown

| Field | Computed By | Redis Key | Notes |
|-------|-------------|-----------|-------|
| `id` | Constant | `KNOWN_FACTIONS` in main.py | 5 known factions |
| `name` | Constant | `FACTION_DISPLAY` in main.py | Display names |
| `dynamics` | `faction_dynamics.py` `get_faction_detail()` | `faction_dynamics:{fid}` HASH | Computed per tick |
| `dynamics.member_count` | Count of NPCs with matching affiliation | `npc_state:{cid}` | Scanned during `compute_faction_dynamics()` |
| `dynamics.cohesion` | `faction_dynamics.py` | Cumulative from NPC decisions | 0.0–1.0, increases with aligned decisions |
| `dynamics.influence` | `faction_dynamics.py` | Based on decision volume | 0.0–1.0 |
| `dynamics.standing` | `faction_dynamics.py` | Aggregated from NPC standing scores | 0.0–1.0 |
| `dynamics.vigilance` | `faction_dynamics.py` | Based on threat-related decisions | 0.0–1.0 |
| `dynamics.avg_mood` | `faction_dynamics.py` | Mode of member NPC moods | String label |
| `dynamics.activity_rate` | `faction_dynamics.py` | decisions_this_tick / member_count | 0.0–1.0 |
| `stances` | `faction_dynamics.py` `get_faction_stances()` | `faction_stances:{fid}` HASH | Bilateral, value 0–1 with label |
| `stances.*.label` | Computed from value | Thresholds: <0.2 hostile, <0.4 tense, <0.6 neutral, <0.8 cordial, >=0.8 allied | |
| `stances.*.trend` | Delta from previous tick | `faction_stances_prev:{fid}` | Positive = improving, negative = degrading |
| `recent_actions` | Last 5 from faction action log | `faction_actions:{fid}` ZSET | JSON-parsed, pipelined |
| `power` | Cumulative from `execute_npc_decisions()` | `faction_power:{fid}` STRING | 0.0–1.0, updated per tick |

### Known Factions

| ID | Display Name |
|----|-------------|
| `diplomatic_corps` | Diplomatic Corps |
| `research_division` | Research Division |
| `security_council` | Security Council |
| `cultural_unity` | Cultural Unity |
| `shadow_syndicate` | Shadow Syndicate |

---

## 3. GET `/simulation/events`

**Source:** main.py lines 4668–4702

### Response Structure

```json
{
  "world_events": [
    {
      "type": "diplomatic_crisis",
      "severity": 2,
      "description": "Ambassador Voss walks out of treaty negotiations...",
      "faction": "diplomatic_corps",
      "ts": 1748030350.0
    },
    {
      "type": "resource_event",
      "severity": 1,
      "description": "New mineral deposits discovered in Sector 7.",
      "faction": "research_division",
      "ts": 1748030280.0
    }
  ],
  "cascade_events": [
    {
      "source": "diplomatic_corps",
      "target": "security_council",
      "type": "diplomatic_pressure",
      "magnitude": 0.20,
      "ts": 1748030340.0
    }
  ],
  "broadcast_events": [
    {
      "char_id": "char_001",
      "name": "Archimedes Prime",
      "event": "publishes research findings on anomaly patterns",
      "faction": "research_division",
      "ts": 1748030320.0
    }
  ]
}
```

### Field Source Breakdown

| Field | Redis Key | Notes |
|-------|-----------|-------|
| `world_events` | `npc_world_events` ZSET | Populated by `simulation_tick()` and `autonomous_tick()` step 6. Limited by `?limit=N` (default 50). |
| `cascade_events` | `cascade_reactions` ZSET | Populated by cascade system during tick. Max 50. |
| `broadcast_events` | `npc_broadcast_events` ZSET | Populated by NPC broadcasting in `npc_autonomy.py`. Max 20. |

### Why Events Might Return 0

1. **Worker hasn't ticked yet** — `npc_world_events` ZSET is only populated when `simulation_tick()` or `autonomous_tick()` runs. If no tick has completed, the ZSET is empty.
2. **Redis was flushed** — Events are ephemeral (no persistence to disk between restarts unless Redis AOF/RDB is configured).
3. **Events are NOT pre-seeded** — They are generated incrementally by NPC decisions + the `EventGenerator` during each tick. On first boot, there are zero events until the first tick completes.
4. **TTL expiry** — Events have no explicit TTL but are stored in ZSETs with timestamps; old events persist until Redis memory pressure evicts them or the ZSET is trimmed.

### Event Generation Pipeline

```
worker.py TICK_INTERVAL (60s)
  -> POST /simulation/tick (npc_autonomy.py: simulation_tick())
     -> generate_npc_events()  ->  writes to npc_world_events ZSET
  -> POST /simulation/autonomous/tick (simulation_engine.py: autonomous_tick())
     -> Step 6: generate_game_events()  ->  EventGenerator creates 1-3 random events
     -> Step 4: bridge_npc_events_to_political()  ->  proposes laws/treaties/research
     -> Step 8: faction tech, diplomacy, cascade
  -> NPC broadcasting  ->  writes to npc_broadcast_events ZSET
  -> Cascade system  ->  writes to cascade_reactions ZSET
```

### Event Types (from `federation_game_events.py`)

| Type | Severity Range | Description |
|------|---------------|-------------|
| `diplomatic_crisis` | 1–4 | Faction conflict or negotiation breakdown |
| `dream_destabilization` | 1–3 | Anomaly-related consciousness disruption |
| `rival_move` | 1–3 | Competitive faction action |
| `prophecy` | 2–4 | Significant narrative foreshadowing |
| `resource_event` | 1–2 | Resource discovery or shortage |
| `cultural_shift` | 1–3 | Cultural values change |
| `paradox_manifestation` | 2–4 | Reality distortion event |
| `first_contact` | 3–4 | New entity encounter |
| `natural_disaster` | 2–3 | Environmental catastrophe |
| `technological_breakthrough` | 1–3 | Tech advancement |
| `alliance_formation` | 1–2 | Faction alliance |
| `espionage_uncovered` | 2–3 | Spy operation revealed |

---

## 4. GET `/simulation/npcs/activity`

**Source:** main.py lines 4574–4665  
**Redis round-trips:** 5 pipelined batches (moods, thoughts, decisions, actions, state) instead of 234+ sequential calls

### Response Structure

```json
{
  "npcs": [
    {
      "char_id": "char_001",
      "name": "Archimedes Prime",
      "affiliation": "research_division",
      "archetype": "scholar",
      "mood": "curious",
      "recent_thoughts": [
        {
          "content": "The anomaly patterns suggest a deeper structure...",
          "mood": "curious",
          "ts": 1748030350.0
        }
      ],
      "recent_decisions": [
        {
          "action": "investigate_anomaly",
          "target": "Sector 7 readings",
          "rationale": "Pattern correlation with historical data",
          "ts": 1748030340.0
        }
      ],
      "recent_actions": [
        {
          "type": "research",
          "description": "Began deep analysis of anomaly waveforms",
          "effects": { "research_progress": 0.05 },
          "ts": 1748030330.0
        }
      ],
      "corruption_level": 0.0,
      "rumor_level": 0.0,
      "status": "active"
    }
  ],
  "count": 35
}
```

### Field Source Breakdown

| Field | Redis Key | Notes |
|-------|-----------|-------|
| `char_id` | Constant from `npcs.py` | Pre-built character ID |
| `name` | Constant from `npcs.py` | Character name |
| `affiliation` | Constant from `npcs.py` | Faction ID |
| `archetype` | `npc_mood:{cid}` or fallback from `npcs.py` `personality_type` | String label |
| `mood` | `npc_mood:{cid}` STRING | Current mood, pipelined batch |
| `recent_thoughts` | `npc_thoughts:{cid}` ZSET | Last 3, JSON-parsed, pipelined |
| `recent_decisions` | `npc_decisions:{cid}` ZSET | Last 3, JSON-parsed, pipelined |
| `recent_actions` | `npc_actions:{cid}` ZSET | Last 3, JSON-parsed, pipelined |
| `corruption_level` | `npc_state:{cid}` HASH field `corruption_level` | 0.0–1.0, pipelined |
| `rumor_level` | `npc_state:{cid}` HASH field `rumor_level` | 0.0–1.0, pipelined |
| `status` | `npc_state:{cid}` HASH field `status` | String, pipelined |
| `count` | Length of `npcs` array | Total NPCs returned |

### NPC Character Types (from `npcs.py`)

**35+ pre-built characters across 6 categories:**

| Category | Count | Examples |
|----------|-------|---------|
| Historical Figures | 5 | Archimedes Prime, Cleo the Wanderer, Marcus Vex, Lyra Dreamweaver, Theron Ashwalk |
| Faction Leaders | 8 | One per faction + deputies |
| Companions | 10 | Recurable allies with special abilities |
| Antagonists | 4 | Opposing forces |
| Mysterious Figures | 6 | Enigmatic characters |
| Unique NPCs | 6 | Special role characters |

### Character Dataclass Fields

```
char_id, name, title, description, loyalty, ambition, wisdom, charisma, cunning,
affiliation, relationship_to_player, status, personality_type (archetype),
skills, inventory, corruption_level, rumor_level
```

### Companion Extended Fields

```
companion_bonus, bonus_value, special_ability, personality_quirks, betrayal_risk
```

### Mood Labels

`curious, cautious, determined, anxious, hopeful, suspicious, indifferent, resolute`

---

## 5. Other Simulation Endpoints

### GET `/simulation/npc-quests`

Returns quest log for all NPCs. Source: main.py lines 4703–4729.

```json
{
  "quests": [
    {
      "char_id": "char_001",
      "name": "Archimedes Prime",
      "quests": [
        {
          "quest_id": "q_001",
          "title": "Anomaly Source Investigation",
          "status": "active",
          "progress": 0.45,
          "faction": "research_division"
        }
      ]
    }
  ],
  "total_quests": 12
}
```

### GET `/simulation/npc-quests/{char_id}`

Per-NPC quest summary. Source: main.py lines 4730–4754.

```json
{
  "char_id": "char_001",
  "name": "Archimedes Prime",
  "quests": [ "..." ],
  "active_count": 2,
  "completed_count": 1
}
```

### GET `/simulation/faction-tech`

All faction tech research. Source: main.py lines 4755–4779.

```json
{
  "factions": {
    "research_division": {
      "active_research": [
        {
          "tech_id": "quantum_sensing",
          "name": "Quantum Sensing Array",
          "progress": 0.65,
          "eta_ticks": 12,
          "priority": "high"
        }
      ],
      "completed_tech": ["basic_scanners", "advanced_comms"],
      "research_capacity": 3
    }
  }
}
```

### GET `/simulation/faction-tech/{faction_id}`

Per-faction tech detail. Source: main.py lines 4780–4807.

### GET `/simulation/faction-tech-log`

Recent tech events. Source: main.py lines 4808–4828.

```json
{
  "events": [
    {
      "faction": "research_division",
      "tech": "quantum_sensing",
      "event": "progress",
      "progress_delta": 0.10,
      "ts": 1748030400.0
    }
  ],
  "count": 5
}
```

### GET `/simulation/choice-resolutions`

Faction choice resolution stats. Source: main.py lines 4829–4852.

```json
{
  "total_resolutions": 15,
  "by_faction": {
    "diplomatic_corps": 5,
    "research_division": 4
  },
  "by_outcome": {
    "consensus": 8,
    "majority": 5,
    "vetoed": 2
  }
}
```

### GET `/simulation/choice-resolutions/detail`

Detailed resolution history. Source: main.py lines 4853–4877.

### GET `/simulation/choice-resolutions/{faction_id}`

Per-faction voting history. Source: main.py lines 4878–4910.

### GET `/simulation/cognition/stats`

LLM cognition layer stats. Source: main.py lines 4911–4935.

```json
{
  "total_calls": 142,
  "total_tokens": 285000,
  "by_model": {
    "gpt-4o-mini": { "calls": 100, "tokens": 200000 },
    "claude-3-haiku": { "calls": 42, "tokens": 85000 }
  },
  "avg_latency_ms": 1200,
  "last_call_ts": 1748030400.0
}
```

### GET `/simulation/faction-brains`

Faction brain states (priorities, weights). Source: main.py lines 4936–4968.

```json
{
  "diplomatic_corps": {
    "current_priority": "economic",
    "weights": {
      "military": 0.15,
      "economic": 0.45,
      "diplomatic": 0.30,
      "research": 0.10
    },
    "recent_decisions": 3,
    "last_updated": 1748030400.0
  }
}
```

### GET `/simulation/cascade-chains`

Cascade chain propagation records. Source: main.py lines 4969–4993.

```json
{
  "chains": [
    {
      "id": "chain_001",
      "origin": "security_council",
      "propagations": [
        { "target": "diplomatic_corps", "type": "military_pressure", "magnitude": 0.20 },
        { "target": "shadow_syndicate", "type": "security_crackdown", "magnitude": 0.15 }
      ],
      "total_magnitude": 0.35,
      "active": true,
      "ts": 1748030400.0
    }
  ],
  "total_chains": 3
}
```

### GET `/simulation/faction-treaties`

Active faction treaties. Source: main.py lines 4994–5024.

```json
{
  "treaties": [
    {
      "id": "treaty_001",
      "parties": ["diplomatic_corps", "cultural_unity"],
      "type": "mutual_defense",
      "terms": "Mutual defense against external threats",
      "signed_tick": 1748020000,
      "expires_tick": 1748100000,
      "status": "active"
    }
  ],
  "total": 4
}
```

### GET `/simulation/diplomacy-summary`

Faction diplomacy summary. Source: main.py lines 5025–5062.

```json
{
  "factions": {
    "diplomatic_corps": {
      "allies": ["cultural_unity"],
      "enemies": ["shadow_syndicate"],
      "neutral": ["research_division", "security_council"],
      "treaties": 2,
      "open_disputes": 1
    }
  },
  "bilateral": {
    "diplomatic_corps:research_division": {
      "stance": 0.60,
      "label": "cordial",
      "trend": 0.05
    }
  }
}
```

### GET `/simulation/nim-stats`

NVIDIA NIM LLM client usage stats. Source: main.py lines 5063–5086.

```json
{
  "total_requests": 87,
  "total_tokens": 174000,
  "models_used": {
    "meta/llama-3.1-8b-instruct": { "requests": 50, "tokens": 100000 }
  },
  "avg_latency_ms": 800,
  "errors": 2,
  "last_request_ts": 1748030400.0
}
```

---

## 6. Computed vs. Missing Fields Summary

### Fully Computed Each Tick

- `world_state` (6 conditions) — by game events + world→game bridge
- `faction_dynamics.{fid}` (all 11 fields) — by `compute_faction_dynamics()`
- `faction_stances.{fid}` (bilateral values + labels + trends) — by `compute_faction_stances()`
- `faction_power` — cumulative from NPC decision execution
- `cascade_summary` — from cascade system
- `npc_activity_summary` — aggregation from Redis
- `pending_items` — count of unconsumed political items

### Pre-Seeded (from `npcs.py` constants)

- NPC `char_id`, `name`, `title`, `description`, `loyalty`, `ambition`, `wisdom`, `charisma`, `cunning`, `affiliation`, `personality_type`
- Companion extended fields
- Creature definitions
- `KNOWN_FACTIONS`, `FACTION_DISPLAY`

### Persisted to Redis per Tick (with TTLs)

| Data | Redis Key Pattern | TTL |
|------|-------------------|-----|
| World state | `federation:world_state` HASH | None (permanent) |
| Faction dynamics | `faction_dynamics:{fid}` HASH | None |
| Faction stances | `faction_stances:{fid}` HASH | None |
| NPC moods | `npc_mood:{cid}` STRING | 1 hour |
| NPC thoughts | `npc_thoughts:{cid}` ZSET | 24 hours |
| NPC decisions | `npc_decisions:{cid}` ZSET | 24 hours |
| NPC actions | `npc_actions:{cid}` ZSET | 24 hours |
| NPC state | `npc_state:{cid}` HASH | 7 days |
| NPC broadcast events | `npc_broadcast_events` ZSET | None (trimmed to 100) |
| World events | `npc_world_events` ZSET | None (trimmed to 200) |
| Cascade reactions | `cascade_reactions` ZSET | None (trimmed to 100) |
| Faction actions | `faction_actions:{fid}` ZSET | None (trimmed to 50) |
| Sim tick log | `sim_tick_log` ZSET | None (trimmed to 100) |
| Faction AI last tick | `faction_ai:last_tick` HASH | None |

### Fields That May Be Missing/Zero on Fresh Boot

- `world_events` — empty ZSET until first tick generates events
- `cascade_events` — empty until cascade chain triggers
- `broadcast_events` — empty until NPCs broadcast
- `faction_dynamics.*.decisions_this_tick` — 0 until tick runs
- `faction_dynamics.*.events_this_tick` — 0 until tick runs
- `last_tick_result` — null/empty until first tick completes
- `faction_ai_last_tick` — empty HASH until faction AI runs
- `recent_actions` — empty arrays for factions with no actions yet

---

## 7. Worker Tick Pipeline (full sequence)

From `worker.py`, the main loop runs every `TICK_INTERVAL` seconds (default 60):

```
1. POST /npcs/advance-turn          (sync, 120s timeout)
   └─ NPCSystem.advance_turn() — updates NPC states, corruption, rumors

2. POST /simulation/tick            (async, 15s submit)
   └─ npc_autonomy.py: simulation_tick()
      ├─ generate NPC thoughts, moods, opinions
      ├─ generate NPC decisions
      ├─ compute faction dynamics + stances
      ├─ store dynamics to Redis
      └─ write world events to ZSET
   └─ Poll GET /simulation/tick/status until complete

3. POST /political/process-turn     (sync, 60s timeout)
   └─ Political engine — process pending laws, treaties, research

4. POST /history-arc/advance        (sync, 60s timeout)
   └─ History arc progression

5. POST /simulation/autonomous/tick (async, 15s submit)
   └─ simulation_engine.py: autonomous_tick()
      ├─ Step 1:  Wire faction context into NPC decisions (5-min TTL)
      ├─ Step 1.5: LLM Cognition (optional)
      ├─ Step 2:  Execute NPC decisions with world_state effects
      ├─ Step 3:  Bridge world state → game_state (morale, stability, tech, military, treasury)
      ├─ Step 4:  Bridge NPC events → political engine (proposes laws, treaties, research)
      ├─ Step 4b: Consume pending political items (apply effects)
      ├─ Step 5:  Check era advancement
      ├─ Step 6:  Generate game events (1-3 random events via EventGenerator)
      ├─ Step 7:  NPC autonomous quest progression
      ├─ Step 7.5: Evolve NPC relationships
      ├─ Step 8:  Faction autonomous tech research
      ├─ Step 8.5: Faction diplomacy cycle
      ├─ Step 8.6: Cross-layer diplomacy→NPC relationship bridge
      ├─ Step 9:  Narration (LLM-generated summary)
      └─ Step 9.5: NPC memory harvest
   └─ Poll GET /simulation/autonomous/status until complete

6. POST /cognition/tick             (sync, 120s timeout)
   └─ LLM cognition processing

7. POST /narrator/generate          (sync, 90s timeout)
   └─ Narrative generation

8. Auto-save game state
9. Publish to Redis federation:updates channel
10. Check for significant events → Apprise notifications
```
