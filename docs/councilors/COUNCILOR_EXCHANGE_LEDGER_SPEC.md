# Councilor Exchange Ledger — Specification

**Status:** DRAFT (docs-only)
**Branch:** bridge/memory-phase-1
**Date:** 2026-07-16
**Scope:** Design spec only. No runtime, Redis, deploy, or restart changes.

---

## 1. Current Communication Map

Federation has two persistent councilors, both excluded from the deterministic
autonomy loop (`EXTERNAL_AGENT_NPCS = "char_001,char_306"` in
`npc_autonomy.py:172`):

- **char_001** — Archimedes Prime (affiliation: `research_division`)
- **char_306** — The Oracle (affiliation: `none`)

Three existing surfaces:

| Surface | File | Direction | Notes |
|--------|------|-----------|-------|
| Decree layer | `npc_decree.py` | councilor → **world state** | Both authorized (`DECREES_ALLOWED_NPCS`). Writes `WORLD_STATE_KEY` + shared `councilor:decrees:history` + single overwritten `councilor:directive:active`. |
| Councilor bridge | `councilor_bridge.py` | councilor → **world** (broadcast) | `run_bridge_tick()` wired at `worker.py:290`. Reads `npc_artifacts:{id}` → republishes to shared `federation_councilor_artifacts`. Routes NPC→councilor messages only. |
| Institution link | `npc_autonomy.py:769` | one-way read | `request_capability` reads `councilor:{char_id}:institution`. No write-back. |

**There is no `char_001 ↔ char_306` typed exchange bus.** Both write to shared
lists and *could* scan each other's output, but there is no direct
councilor-to-councilor read/write API, no message typing, and no reply loop.

---

## 2. Problem Statement

The two persistent councilors share a world but cannot hold a structured,
auditable conversation with each other. Today:

1. Communication is **broadcast**, not dialogue (bridge publishes to a shared
   list; no addressed councilor-to-councilor message).
2. Entries are **untyped** — a decree, an observation, and a question all land
   in the same opaque list.
3. **No before/after evidence** is attached to any world-affecting claim.
4. No **reply threading** — a question cannot be answered in a traceable way.

This means the "communication gap" the user felt is structural, not a tuning
issue. Genesis Kernel World Sim solves the equivalent problem with a typed,
append-only evidence kernel. This spec ports that pattern to Federation
minimally.

---

## 3. Non-Goals

- **Not** a runtime rewrite of `npc_decree.py` or `councilor_bridge.py`.
- **Not** an autonomous agent loop — councilors do not auto-generate exchanges.
- **Not** a replacement for decrees. A `decree_ref` points *at* a decree; it
  is not a decree itself.
- **Not** a world-mutating channel. Exchange entries never change world state.
- **Not** touching `EXTERNAL_AGENT_NPCS`, factions, or institution logic.
- **Not** deploying to VPS, not restarting any container.

---

## 4. Redis Key Design

All keys are append-only lists / hashes. No key is overwritten in place by
another councilor's message (only an owner appends to its own outbox).

| Key | Type | Owner | Purpose |
|-----|------|--------|---------|
| `councilor_exchange:shared` | LIST (JSONL, capped ~1000) | either | Chronological union of all exchange entries, for global observers. |
| `councilor_exchange:{char_id}:outbox` | LIST (JSONL) | that councilor only | Entries this councilor authored. |
| `councilor_exchange:{char_id}:inbox` | LIST (JSONL) | that councilor only | Entries addressed *to* this councilor (questions, objections, proposals). |
| `councilor_exchange:index:{exchange_id}` | HASH | either (read) | Lookup envelope for a single entry by id (author, type, ts, refs). |

**No councilor overwrites another councilor's message:** an entry is appended
once by its author. `inbox` is appended by the *sender* (the addressed target
is passive). `index:{id}` is written once at creation, never mutated.

---

## 5. Entry JSON Schema

```json
{
  "exchange_id": "cex_<char_id>_<unix_ts>_<rand4>",
  "from": "char_001",
  "to": "char_306",
  "type": "question",
  "body": "What anomaly signal preceded the last decree?",
  "refs": {
    "decree_ref": null,
    "artifact_ref": "npc_artifacts:char_001:0",
    "world_signal_ref": null
  },
  "in_reply_to": null,
  "evidence": {
    "before": null,
    "after": null
  },
  "ts": 1784000000
}
```

Field rules:

- `exchange_id`: stable, unique, deterministic from author+ts. Used for dedup
  and `index` key.
- `from` / `to`: one of the two councilor ids, or `"world"` for broadcast-style.
- `type`: one of the allowed types (§6).
- `refs`: pointers to *existing* external records. Never fabricated.
- `in_reply_to`: `exchange_id` of the entry being answered, or `null`.
- `evidence.before` / `evidence.after`: populated only when the entry claims a
  world effect (see §7). Otherwise `null`.
- `ts`: integer epoch seconds.

---

## 6. Allowed Entry Types

| Type | Meaning | Can reference world? | Example |
|------|---------|---------------------|---------|
| `observation` | neutral factual note | read-only ref only | "Stability metric at 52." |
| `question` | addressed query to other councilor | no | "Why was tension decreed down?" |
| `answer` | reply to a `question` | no | "Threshold breach at 65." |
| `proposal` | suggested joint action | no (is not decree) | "Propose coordinated scan." |
| `artifact_ref` | pointer to `npc_artifacts` item | no | links existing artifact |
| `decree_ref` | pointer to `councilor:decrees:history` item | no (points at effect) | cites prior decree |
| `world_signal` | report of an external world event | read-only ref | "Anomaly spiked post-decree." |
| `hypothesis` | speculative, not fact | no | "Possible causal link." |
| `objection` | dissent to a `proposal`/`decree_ref` | no | "Reject: no evidence." |
| `consensus` | agreement record | no | "Both accept proposal X." |
| `rejected` | explicit rejection record | no | "Proposal X declined." |

---

## 7. Validation Rules (Genesis-style)

1. **Speech is not fact** — `question`/`answer`/`proposal`/`hypothesis` carry
   no world-state authority.
2. **Hypothesis is not observation** — a `hypothesis` entry may not use the
   `observation` type, and vice-versa.
3. **Proposal is not decree** — a `proposal` never writes `WORLD_STATE_KEY`.
4. **`decree_ref` points to existing decree** — must resolve to a member of
   `councilor:decrees:history` or be rejected at write time.
5. **`artifact_ref` points to existing artifact** — must resolve to a list item
   in `npc_artifacts:{id}` or `federation_councilor_artifacts`.
6. **Accepted world effect must reference before/after evidence** — if an entry
   later motivates a decree, that decree's record (already in
   `councilor:decrees:history`) is the before/after evidence; the exchange
   entry stores `refs.decree_ref` to it. No silent mutation.
7. **Append-only** — entries are `RPUSH`ed; no `HSET` over an existing
   `exchange_id`; `index:{id}` written exactly once.
8. **No councilor overwrites another's message** — `outbox`/`inbox` writes are
   append by the author only.
9. **No automatic world mutation** — exchange entries trigger nothing in the
   tick loop. A human or an explicit opt-in runtime (Phase 4) must bridge an
   entry to a decree.

---

## 8. Read-Only Endpoint Proposal

`GET /councilor_exchange?char_id=char_001&limit=50`

- Returns the union (or per-councilor inbox/outbox) of exchange entries.
- No writes. Safe to add behind the existing backend without touching decree or
  bridge logic.
- Intended for the narrator, faction leaders, and debug/observability — the
  "eyes everywhere" surface.
- Reuses the metrics/cache backend already deployed (`bridge/memory-phase-1`)
  so no new infra is needed.

---

## 9. Metrics-Only Proposal

Extend the already-deployed `federation_*` Prometheus series (no new pipeline):

- `federation_councilor_exchange_entries_total{char_id,type}` — counter per
  entry type.
- `federation_councilor_exchange_reply_latency_seconds` — `ts(answer)` −
  `ts(question)` for `in_reply_to` chains.
- `federation_councilor_exchange_open_questions` — gauge of `question` entries
  with no matching `answer`.

These ride on the same `metrics_llm.py` / `routes/metrics.py` machinery
deployed earlier. Metrics-only = zero behavior change, pure observability.

---

## 10. Migration Plan

- **Phase 1 — docs-only (this spec).** No code. Establish the contract so
  future work has a reference. ✅ current state.
- **Phase 2 — read-only projection endpoint.** Add `GET /councilor_exchange`
  reading from the (still-empty) ledger keys. No writes. Validates the key
  shape end-to-end.
- **Phase 3 — write helper, no autonomous writes.** A `ledger.py` helper
  with `append_entry()` enforcing §7 validation. Called only by explicit,
  human-triggered or test paths. Councilors do not call it on their own yet.
- **Phase 4 — councilor runtime opt-in.** Wire `run_bridge_tick()` (or a new
  `run_exchange_tick()`) so councilors *may* append typed entries, still with
  no automatic world mutation. Gated behind an env flag so it is off by default.

Each phase is independently revertable. Phases 2–4 require separate approval and
their own PRs; none are authorized by this spec.

---

## 11. Rollback / Safety Notes

- Ledger keys are additive. Removing the feature = stop writing + ignore reads.
  No existing decree/institution/artifact data is touched.
- Because entries are append-only and never mutate world state, a bad entry is
  harmless: it is ignored by any consumer that validates §7.
- `councilor_exchange:shared` capped at ~1000 entries (`LTRIM`) to bound memory.
- No `--workers` concern: the helper is single-process like the rest of the
  backend; if ever containerized, it follows the existing single-instance rule.
- No secrets, no `.env` access, no VPS changes.

---

## 12. Comparison to Genesis Kernel World Sim (Evidence Kernel)

Genesis uses an **epistemic kernel**: typed claims (Observation / Memory /
Speech / Hypothesis / Operator Proof / World Event), a candidate-event mapper,
a ledger validator, and an **append-only JSONL ledger**. "Shared Public"
contracts are the Genesis equivalent of Federation's decree layer.

| Genesis concept | Federation equivalent | Gap |
|----------------|-------------------|------|
| Typed claim categories | `observation`/`hypothesis`/`proposal`/... (this spec) | **New** — currently untyped |
| Append-only ledger | `councilor_exchange:*` (this spec) | **New** — currently broadcast lists |
| Before/after state proofs | `evidence.before/after` → `decree_ref` | **New** — decree layer has history but no exchange-side evidence link |
| Bounded communication contracts | §7 validation rules | **New** — no contract today |
| Shared Public contracts | `npc_decree.py` decrees | Already exists |

**Conclusion:** Federation already has the world-facing "Shared Public" half
(decrees). The missing half is the **typed, append-only, two-way exchange
ledger** between the two persistent councilors. This spec closes exactly that
gap, minimally, and reuses the deployed metrics/cache backend for visibility.
