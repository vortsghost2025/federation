# The Steward — S1 Pure Deterministic Engine

S1 of the Steward architecture (spec `docs/superpowers/specs/2026-07-18-the-steward-architecture.md`).
Pure, deterministic, **no live I/O**. Runs checks against frozen fixture JSON and
emits structured `finding.json`.

## Layout
- `steward/schema.py` — `Finding` dataclass, the single source of truth.
- `steward/checks/` — pure check functions (`semantic-loops`, `npc-heartbeats`).
  Each takes a fixture dict and returns `list[Finding]`. No I/O, no mutation.
- `steward/cli.py` — `steward check <id|all> --fixture <path|- >`.
- `tests/fixtures/` — frozen observation snapshots (pass / fail / unknown).
- `tests/unit/test_checks.py` — pure unit tests (stdlib unittest, no deps).

## Run
```
python -m unittest discover -s tests/unit -p "test_*.py"
python -m steward.cli check semantic-loops --fixture tests/fixtures/semantic_loops_loop.json
```

## Contract (spec Section 6, 7, 8, 15)
- Observe, record, flag — never mutate.
- Unknown source → `status: "unknown"`; never infer "healthy" from unreadable.
- S1 is single-shot only. `dedupe_key` is produced for every finding, but S1 does
  **NOT** persist prior occurrences or perform cross-run dedupe/occurrence counting
  (that is S2+). `first_seen == last_seen == observed_at`, `occurrence_count == 1`.
- `finding_id` is deterministic: SHA-256 over the canonical stable identity material,
  never uuid or wall-clock. Identical input → byte-identical `finding.json`.
- No `steward:` writes, no Redis/API/Docker, no cognition/pair/inbox paths.

## Out of scope (later phases)
- S2 read-only live adapters, S3 `steward:` world writes, S4 Councilor Watch,
  S5 optional model interpretation, S6 auto-infra (gated).
