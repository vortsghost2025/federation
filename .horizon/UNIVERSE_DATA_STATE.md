# Universe Data State

ANCHOR: cache-first universe layer | runtime local only | ingestion disabled by default | generated never equals observed

Current phase: design only.

## Purpose

This file is the short handoff for fresh agents with zero chat history. It protects Federation from agents turning the universe-data idea into a fragile live API spider or giant catalog import.

## Runtime-Local-Only Rule

Federation runtime must read only local cache files or local database tables.

Do not call NASA, NOAA, JPL, Gaia, MAST, Hubble, JWST, or other external APIs from runtime routes, NPC cognition, worker ticks, frontend rendering, or mission generation.

Runtime must be boring and local. Ingestion can be fancy later.

## Current Design Files

Allowed design/handoff files:

- `docs/superpowers/specs/2026-07-04-universe-data-simulation-design.md`
- `.horizon/UNIVERSE_DATA_STATE.md`

Future Phase 1 files may be added only after an approved implementation plan:

- `federation-game/backend/data/universe/universe_manifest.json`
- `federation-game/backend/data/universe/solar_system_sample.json`
- `federation-game/backend/data/universe/nearby_stars_sample.json`
- `federation-game/backend/data/universe/exoplanets_sample.json`
- `federation-game/backend/data/universe/deep_sky_references_sample.json`
- `federation-game/backend/data/universe/space_weather_sample.json`
- `federation-game/backend/data/universe/procedural_unknown_sample.json`

## Next Safe Step

Write a Phase 1 implementation plan for local cached datasets only.

The plan should cover:

- Small sample JSON datasets.
- Provenance-first schema validation.
- Local runtime loader.
- Read-only local query endpoint.
- NPC science evidence packet builder.
- Frontend provenance visualization proof of concept.

## Forbidden Actions

Do not:

- Build the universe yet.
- Deploy to VPS.
- Restart containers.
- Commit unless explicitly requested.
- Spawn subagents unless explicitly requested.
- Call live APIs at runtime.
- Add live API calls to route handlers, worker ticks, NPC cognition, frontend rendering, or mission generation.
- Import giant catalogs.
- Download whole Gaia, Hubble, JWST, MAST, NOAA, or JPL datasets.
- Store generated data as observed data.
- Mix observed and generated truth levels.
- Use Redis as the permanent astronomy catalog.

## Truth Boundary

Every universe object must use one of these truth levels:

- `observed`: real catalog/archive/measurement-backed evidence.
- `estimated`: real but uncertain or incomplete evidence.
- `generated`: Federation/procedural hypothesis only.

Generated never equals observed.

NPCs may reason about generated objects as hypotheses, but must never describe them as confirmed discoveries.

## Phase Boundary

Phase 1: local cached datasets only.

Phase 2: optional ingestion worker, disabled by default with `UNIVERSE_INGESTION_ENABLED=false`.

Phase 2 may pull NASA/JPL/Gaia/MAST/NOAA data and write local cache/database records, but it must never be required for runtime boot.

## Agent Reminder

We are not building the universe yet.

We are building the map that prevents agents from building it wrong.
