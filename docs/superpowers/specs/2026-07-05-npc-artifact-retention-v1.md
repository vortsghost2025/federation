# NPC Artifact Retention Policy — v1

**Date:** 2026-07-05
**Status:** Design doc (pre-implementation)
**Related:** Redis hygiene audit (2026-07-05), Stage 4C/4D

## Problem

Three `npc_artifacts:*` Redis lists are append-only with no TTL:

| Key | Size | Items | Growth | TTL |
|-----|------|-------|--------|-----|
| `npc_artifacts:global` | 21.8 MB | 4,530 | ~560 items/day | none |
| `npc_artifacts:char_001` | 14.0 MB | 2,340 | ~290 items/day | none |
| `npc_artifacts:char_306` | 10.3 MB | 2,193 | ~270 items/day | none |

At current rate: ~180 MB at 30 days, unbounded.

## Artifact Properties (from audit)

- **Immutable**: zero duplicate IDs across all entries — no overwrites, no ID reuse
- **global is strict superset**: per-NPC lists are proper subsets filtered by `char_id`
- **No crossover**: char_001 and char_306 share zero artifact IDs
- **Cross-references**: artifacts are referenced by `federation_councilor_artifacts` list (47 of the most recent 50 found there)
- **Journal references**: none — pair journal entries do not reference artifact IDs
- **Content**: avg 4 KB, max 6 KB per entry (markdown), ~17 MB raw text across all 3 lists
- **Regeneration**: impossible — each artifact is a unique NPC-authored document

## Three-Tier Storage Model

### Tier 1: Hot (Redis)

Keep a bounded window of recent artifacts in Redis for fast tick-loop access.

| Key | Retention |
|-----|-----------|
| `npc_artifacts:char_*` | last 500 per NPC |
| `npc_artifacts:global` | last 1,000 |

Trim via `LTRIM` at write time or on a periodic batch. No structural change to the list format — just bounded.

**Read path unchanged**: tick loop reads Redis as before. The window is always large enough for recent references.

### Tier 2: Warm (PostgreSQL)

Complete artifact history in a `npc_artifacts` table:

```sql
CREATE TABLE npc_artifacts (
    artifact_id UUID PRIMARY KEY,
    char_id TEXT NOT NULL,
    char_name TEXT NOT NULL,
    title TEXT NOT NULL,
    artifact_type TEXT DEFAULT 'text',
    content TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    archived_at TIMESTAMP DEFAULT NOW()
);
```

- One row per artifact. Duplicate content (not a reference) — the table is the complete historical record.
- Not read by the tick loop. Console queries, admin views, and future search only.
- Populated by a batch archiver: scans Redis for items at risk of being trimmed, inserts missing rows.

### Tier 3: Cold (filesystem archive)

- Periodic JSON snapshots of the `npc_artifacts` table (weekly, gzip-compressed).
- Stored on VPS filesystem under `/docker/federation-game/archives/`.
- Read-only historical record. Never loaded into the app.

## Decision Rule for Redis Trim

Only trim an artifact from Redis when **all** of these hold:

1. Artifact exists in warm (PostgreSQL) archive → verified by `SELECT 1 FROM npc_artifacts WHERE artifact_id = $1`
2. References in `federation_councilor_artifacts` list remain valid → that list has its own retention; artifacts referenced there stay in Redis
3. No NPC cognition currently replaying the artifact's period → only the most recent ~200 artifacts ever matter for this
4. Artifact ID remains stable → IDs are UUIDs generated at creation and never reused (confirmed immutable)
5. Recovery path tested at least once → manual verification before first trim

## Execution Shape (not implementation)

1. **Create PostgreSQL table** — migration for the `npc_artifacts` schema above
2. **Build archiver** — batch job that reads Redis artifact lists, compares against PostgreSQL, inserts missing rows
3. **Test recovery** — manually verify that archived data can be re-loaded into Redis
4. **Enable Redis trim** — add `LTRIM` at write time or periodic batch bound to retention windows
5. **Set up cold archive** — cron job or manual weekly snapshot

## Non-Goals

- No changes to artifact creation code
- No changes to tick-loop read paths
- No deletion of any data until recovery is tested
- No migration of existing data from Redis to PostgreSQL until the archiver is built and verified

## Risks

- Archiver must be idempotent: inserting an already-archived artifact should be a no-op (ON CONFLICT DO NOTHING)
- Redis trim must never outrun the archiver — trim only after archive confirmation
- `federation_councilor_artifacts` list references must be tracked — if an artifact is still referenced there, it stays in Redis regardless of age
