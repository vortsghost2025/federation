# Universe Data Simulation Design

ANCHOR: cache-first universe layer | runtime local only | ingestion disabled by default | generated never equals observed

Date: 2026-07-04
Status: Design only
Scope: Federation universe-data simulation architecture

## Purpose

Federation needs a universe-data layer that can represent real astronomical data, uncertain scientific estimates, and generated frontier space without confusing one for another. The purpose of this design is to define the map before implementation so future agents can build the system safely, incrementally, and without turning Federation runtime into a fragile live API spider.

The system must let Federation use real data from sources such as NASA, NOAA, JPL Horizons, Gaia, MAST, Hubble, JWST, and the NASA Exoplanet Archive while protecting the simulation from network failures, rate limits, huge catalog imports, and context loss between agents.

Core rule: runtime must be boring and local. Ingestion can be fancy later.

## Non-Goals

This design does not build the universe-data system yet.

Do not implement these in the first phase:

- Live API calls during normal Federation runtime.
- Whole Gaia imports.
- Giant Hubble or JWST FITS downloads.
- Automated runtime crawlers or API spiders.
- Automatic ingestion on boot.
- Frontend rendering of millions of objects.
- Redis as the permanent astronomy catalog.
- Generated objects stored or displayed as observed facts.
- Unlabeled mixing of real, estimated, and generated data.
- Production deploy, VPS restart, or container changes as part of the design step.

## Data Layers

Federation should treat the universe as stacked evidence layers. Each layer has a Phase 1 cached form and a later Phase 2 ingestion source.

| Layer | Source | Phase 1 Runtime Form | Phase 2 Optional Source |
|---|---|---|---|
| Solar System | NASA/JPL Horizons | Small local sample of Sun, planets, key moons, and a few asteroid/comet examples | JPL Horizons API or exported ephemerides |
| Exoplanets | NASA Exoplanet Archive | Small confirmed exoplanet sample with host stars and discovery metadata | Exoplanet Archive TAP/API exports |
| Stars | ESA Gaia | Nearby star sample, limited to a small curated set | Gaia archive exports or curated query results |
| Deep Sky Images | MAST, Hubble, JWST, SkyView | Metadata references, image URLs, observation ids, and small thumbnails if needed | MAST API, astroquery, SkyView cutouts, archive exports |
| Earth, Weather, Space Weather | NASA and NOAA | Cached solar weather, geomagnetic, atmosphere, and sample weather records | NOAA/NASA APIs and exports |
| Procedural Unknown | Federation model | Small generated frontier sample clearly marked generated | Local procedural generator only |

## Provenance-First Schema

Every universe object must carry provenance and uncertainty before gameplay fields. The schema must make it impossible for fresh agents, NPCs, or frontend code to treat generated data as observed data.

Required fields:

| Field | Purpose |
|---|---|
| `id` | Federation internal id, stable across imports |
| `name` | Human-readable name |
| `object_type` | `star`, `planet`, `moon`, `asteroid`, `comet`, `exoplanet`, `galaxy`, `nebula`, `image_reference`, `space_weather_event`, `anomaly`, `generated_system`, or similar |
| `truth_level` | `observed`, `estimated`, or `generated` |
| `confidence` | Numeric confidence from `0.0` to `1.0` |
| `source` | Source name, such as `JPL Horizons`, `NASA Exoplanet Archive`, `Gaia DR3`, `MAST`, `NOAA`, or `procedural_model_v1` |
| `source_id` | External id, archive id, catalog id, or local sample id |
| `source_url` | Optional source reference or archive URL |
| `last_updated` | Date or timestamp of the cache/import update |
| `position` | Coordinate frame, epoch, values, and unit |
| `distance` | Distance value, unit, and uncertainty when available |
| `uncertainty` | Error bars, missing-value notes, method limitations, and confidence notes |
| `generated` | Boolean mirror of whether the object is generated |
| `federation_tags` | Simulation tags such as `mission_target`, `science_priority`, `anomaly`, or `frontier` |

Example shape:

```json
{
  "id": "fed_star_sol",
  "name": "Sol",
  "object_type": "star",
  "truth_level": "observed",
  "confidence": 1.0,
  "source": "JPL Horizons / curated_seed",
  "source_id": "solar_system_sample_v1",
  "source_url": null,
  "last_updated": "2026-07-04",
  "position": {
    "frame": "heliocentric",
    "epoch": "J2000",
    "x": 0,
    "y": 0,
    "z": 0,
    "unit": "AU"
  },
  "distance": {
    "value": 0,
    "unit": "AU",
    "uncertainty": null
  },
  "uncertainty": {
    "position_error": null,
    "distance_error": null,
    "notes": "Curated seed object"
  },
  "generated": false,
  "federation_tags": ["solar_system", "observed", "mission_safe"]
}
```

## Truth Levels

Truth level is the central safety boundary.

| Truth Level | Meaning | Runtime Behavior |
|---|---|---|
| `observed` | Real catalog, archive, or measurement-backed object | NPCs may treat it as known evidence, subject to source limitations |
| `estimated` | Real object or phenomenon with incomplete, uncertain, or derived values | NPCs may debate uncertainty, request follow-up missions, or compare confidence |
| `generated` | Federation/procedural object created by simulation | NPCs must treat it as hypothesis/frontier only, never confirmed fact |

Rules:

- `generated` must always be `true` when `truth_level` is `generated`.
- Generated records must never overwrite observed or estimated records.
- Frontend and NPC prompts must expose truth level clearly.
- Mission generation can target generated objects, but mission text must call them hypotheses or frontier projections.

## Phase 1 Cached Dataset Plan

Phase 1 is local cached datasets only. It must not depend on external APIs during normal runtime.

Suggested local layout:

```text
federation-game/backend/data/universe/
  universe_manifest.json
  solar_system_sample.json
  nearby_stars_sample.json
  exoplanets_sample.json
  deep_sky_references_sample.json
  space_weather_sample.json
  procedural_unknown_sample.json
```

Dataset goals:

| Dataset | Suggested Size | Purpose |
|---|---:|---|
| `solar_system_sample.json` | 20 to 100 objects | Sun, planets, major moons, and a few asteroids/comets |
| `nearby_stars_sample.json` | 50 to 500 objects | Local stellar neighborhood for early starmap work |
| `exoplanets_sample.json` | 20 to 100 objects | Confirmed exoplanets with host, radius/mass/orbit when available |
| `deep_sky_references_sample.json` | 5 to 50 records | Hubble/JWST/MAST/SkyView references without huge downloads |
| `space_weather_sample.json` | 10 to 100 records | NOAA/NASA solar weather and geomagnetic samples |
| `procedural_unknown_sample.json` | 10 to 100 objects | Generated frontier objects for NPC hypothesis behavior |

`universe_manifest.json` should describe each dataset:

```json
{
  "dataset": "exoplanets_sample",
  "file": "exoplanets_sample.json",
  "source": "NASA Exoplanet Archive",
  "truth_levels": ["observed", "estimated"],
  "object_count": 25,
  "runtime_required": true,
  "external_api_required": false,
  "last_updated": "2026-07-04"
}
```

Phase 1 acceptance rules:

- Federation can boot with only local files or local database records.
- Runtime can run with network disconnected.
- Missing optional datasets degrade gracefully.
- Each cached record validates against the provenance-first schema.
- Generated objects are visually and semantically distinct from observed objects.

## Phase 2 Optional Ingestion Plan

Phase 2 adds a separate ingestion worker. It is optional and disabled by default.

Required default:

```text
UNIVERSE_INGESTION_ENABLED=false
```

The ingestion worker may later:

- Pull from JPL Horizons, NASA Exoplanet Archive, Gaia exports, MAST, NASA, and NOAA.
- Normalize source-specific records into the Federation universe schema.
- Write cache files or PostgreSQL tables.
- Produce small curated runtime datasets from larger source downloads.
- Track import timestamps, source ids, skipped records, validation failures, and counts.
- Run manually or on a controlled schedule only when explicitly enabled.

The ingestion worker must never:

- Block runtime boot.
- Run automatically during normal simulation startup.
- Write directly to active Redis mission state without a separate promotion step.
- Create live API dependencies for NPC cognition, ticks, routes, or frontend rendering.
- Import giant raw catalogs into the runtime path.

## Runtime Services

Runtime services must read local cache/database only.

| Service | Purpose |
|---|---|
| Universe loader | Loads and validates local cached datasets on boot or reload |
| Universe query service | Queries objects by type, region, truth level, confidence, and tags |
| Science context builder | Converts universe objects into short NPC-safe evidence packets |
| Anomaly selector | Selects low-confidence, estimated, or generated targets for missions |
| Mission target service | Creates bounded research/exploration targets from local universe data |
| Frontend universe endpoint | Exposes safe, paginated/bounded visualization data |
| Cache health endpoint | Reports dataset versions, object counts, and validation status |

No runtime service may call external APIs.

External API calls are allowed only in the optional ingestion layer when explicitly enabled.

## Federation And NPC Fit

The universe-data layer should become a science substrate for Federation cognition, missions, and faction behavior.

NPC science agents can:

- Compare observed data against estimated or generated frontier objects.
- Generate hypotheses from missing values and low-confidence records.
- Debate uncertainty without treating uncertainty as failure.
- Propose missions to investigate anomalies.
- Create artifacts from deep-sky references, image metadata, and research summaries.
- React to NOAA/NASA space weather as simulation events.

NPC prompt rule:

```text
Observed objects are evidence.
Estimated objects are uncertain evidence.
Generated objects are hypotheses only.
Never describe generated objects as confirmed discoveries.
```

Example mission patterns:

- Investigate a low-confidence exoplanet property.
- Compare a generated frontier anomaly against nearby observed stars.
- Monitor cached solar-weather samples for simulated infrastructure risk.
- Use a MAST/Hubble/JWST image reference as a research artifact seed.

## Storage Boundaries

Use storage by lifespan and access pattern.

| Storage | Use | Boundary |
|---|---|---|
| JSON cache files | Phase 1 curated samples and manifest | Good for small, readable, versioned starter data |
| PostgreSQL | Later normalized catalog tables and import history | Good for larger local datasets and indexed queries |
| Redis | Active missions, current anomalies, NPC focus, short-lived runtime state | Not the permanent astronomy catalog |

Suggested Redis keys for later runtime state:

```text
universe:active_anomalies
universe:mission_targets
universe:last_runtime_load
npc:{id}:science_focus
```

Redis must store active simulation state only. Catalog data belongs in JSON caches for Phase 1 and PostgreSQL for later phases.

## Frontend Visualization Rules

The frontend must make provenance visible.

| Truth Level | Visual Treatment |
|---|---|
| `observed` | Solid bright point or marker |
| `estimated` | Dashed ring, amber uncertainty halo, or confidence badge |
| `generated` | Translucent frontier marker, distinct shape, and generated badge |
| `anomaly` | Pulsing or outlined marker, with accessible label |
| `mission_target` | High-contrast marker and explicit mission label |

Visualization must be bounded:

- Render curated samples first.
- Paginate or tile larger datasets later.
- Do not push huge catalogs into browser memory.
- Do not use external image downloads as blocking UI requirements.
- Treat deep-sky imagery as references or optional tiles first.

## Accessibility Rules

Sean is partially sighted, and Federation frontend work must remain visually accessible.

Rules:

- Do not rely on color alone to distinguish observed, estimated, and generated objects.
- Use shape, label, opacity, text badges, and high-contrast outlines.
- Keep marker labels readable at large font sizes.
- Provide a text list/table view for visible universe objects and active anomalies.
- Use clear words: `OBSERVED`, `ESTIMATED`, `GENERATED`, `ANOMALY`, `MISSION`.
- Avoid tiny console-like data dumps in the UI.
- Provide summaries before raw catalog details.

## Fresh-Agent Guardrails

Fresh agents with zero chat history must preserve these boundaries.

Absolute rules:

- Runtime must be local only.
- Do not call live APIs at runtime.
- Do not import giant catalogs.
- Do not mix observed and generated records.
- Do not deploy, restart, or edit production while designing.
- Do not make Redis the permanent universe database.
- Do not build ingestion before cached samples and schema validation exist.

Required continuity file:

```text
.horizon/UNIVERSE_DATA_STATE.md
```

That file must tell future agents:

- Current phase.
- Next safe step.
- Forbidden actions.
- Allowed files.
- Runtime-local-only rule.
- Generated never equals observed.

## First Safe Implementation Phase

The first implementation phase should build only the map and local cache foundation.

Allowed first-phase deliverables:

- `universe_manifest.json`.
- Six small sample JSON datasets.
- Schema validator for cached records.
- Runtime loader that reads local files only.
- Read-only query endpoint over local cache data.
- NPC science evidence packet builder.
- Frontend proof-of-concept visualization with provenance badges.
- Handoff updates that keep fresh agents aligned.

Forbidden first-phase deliverables:

- Live API ingestion.
- Giant data imports.
- Background API crawlers.
- Runtime network dependencies.
- Production deploy by default.
- Runtime use of NASA/NOAA/MAST/Gaia/JPL keys.

First safe next step after this design:

1. Create an implementation plan for Phase 1 cached samples only.
2. Define the exact sample JSON shapes and validation rules.
3. Add the smallest local dataset set possible.
4. Verify runtime can load it without any network access.

## Final Boundary

We are not building the universe yet.

We are building the map that prevents agents from building it wrong.
