# Phase 2 — Councilor Exchange Ledger: Read-Only Endpoint Plan

**Status:** DRAFT (plan-only, revised per review, not approved for implementation)
**Depends on:** Phase 1 spec (`COUNCILOR_EXCHANGE_LEDGER_SPEC.md` @ `dc54695`)
**Branch target:** `bridge/memory-phase-1` (plan lives here; implementation on its own feature branch)
**Authorizes:** No runtime writes, no Redis schema changes, no deploy, no restart — *until separately approved and PR'd*.

---

## 0. Goal

Make the (currently empty) `councilor_exchange:*` keys **observable** through a
read-only HTTP endpoint, with zero behavior change to the existing decree / bridge /
institution logic. This closes the "eyes everywhere" gap for the two persistent
councilors without any autonomous write path.

**Phase 2 separation (kept from review):** read-only projection now; all writes,
write helpers, and counters defer to Phase 3. Prometheus exchange metrics are
**deferred to Phase 3** — with no writes in Phase 2 a counter would sit at `0`
and look broken, so it is intentionally absent here.

---

## 1. Route and Exposure

```
GET /simulation/operator/councilor-exchange
  ?view=shared|inbox|outbox
  &char_id=char_001|char_306
  &limit=1..200
```

- **Not** exposed like `/metrics`. Councilor speech, hypotheses, objections, and
  artifact references must not automatically become public.
- The route **must inherit the existing operator/admin protection**. If no such
  protection exists in `main.py`, implementation **must stop and report** before
  exposing the route — do not ship an unauthenticated councilor channel.
- Default `view` = `shared`. Default `limit` = `50`. Default order = newest first.

---

## 2. Validation Rules

| Condition | Response |
|-----------|----------|
| `view=shared` | `char_id` not required → `200` |
| `view=inbox` or `outbox` | `char_id` required → if missing: **`400`** |
| unknown `char_id` (not `char_001`/`char_306`) | **`400`** |
| invalid `view` (not shared/inbox/outbox) | **`400`** |
| `limit` outside `1..200` | **`400`** (definitive; no clamping) |
| valid request, ledger empty/missing keys | **`200`** `{"entries":[],"count":0}` |
| Redis unavailable / read exception | **`503`** with sanitized message |

**Distinguish epistemic states:**
- Empty ledger (keys absent or empty) is a *valid* `200`.
- Redis down / read failure is a *different* state → `503`.
- **Never alias storage failure to an empty ledger.** Never return raw Redis
  connection details or tracebacks. Sanitized `503` only.

---

## 3. Failure Semantics

- `missing/empty Redis keys` → `200 {"entries":[],"count":0}`
- `Redis unavailable / read exception` → `503 {"error":"exchange store unavailable"}`
  (no internals)
- No path in Phase 2 writes to Redis, so there is no write-failure mode here.

---

## 4. Response Contract

```json
{
  "view": "shared",
  "char_id": null,
  "entries": [],
  "count": 0,
  "partial": false,
  "invalid_count": 0
}
```

- `partial=true` + `invalid_count>0` when one or more individual entries failed
  to parse. Malformed entries are **excluded** from `entries` but **reported**
  via `partial`/`invalid_count` — they do not silently disappear.
- `count` = number of successfully parsed entries returned (excludes invalid).

---

## 5. Ordering

Phase 1 specifies entries are appended with **`RPUSH`** (right-push) into the
LIST. `RPUSH` stores entries **oldest → newest from left to right**:

```
RPUSH key A B C
LRANGE key 0 -1        → [A, B, C]   (oldest → newest)
LRANGE key -2 -1       → [B, C]       (still oldest → newest within window)
```

**Critical:** `LRANGE key -limit -1` returns the newest `limit`-sized window,
but the order **within that window remains oldest → newest**. It is NOT
newest-first. Implementation MUST reverse in application code.

Required steps (apply identically to shared, inbox, outbox):

1. `raw_entries = redis.lrange(key, -limit, -1)`   # tail window, oldest→newest
2. `raw_entries.reverse()`                          # now newest→oldest
3. parse each element; valid → `entries`, malformed → `invalid_count++`
4. return `entries` (newest-first)

Example:

```
RPUSH key A B C
LRANGE key -2 -1  → [B, C]
reverse           → [C, B]     (newest-first ✓)
```

`limit` is applied as a **tail window** so the newest `N` are selected before
reversal.

### Malformed-entry accounting

- `invalid_count` counts malformed elements **inside the selected Redis window**
  (after the tail-window slice, before/after reversal — same set).
- `count` counts valid returned entries (excludes invalid).
- Malformed entries do **not** cause older entries outside the selected window to be
  fetched as replacements. The window size is fixed by `limit`; gaps from
  invalid entries are reported via `partial`, not back-filled.

---

## 6. Helper API (read-only)

One internal reader. **No** `append`, `set`, `push`, `trim`, `expire`, or any
other Redis mutation method in Phase 2.

```python
def get_entries(view: str, char_id: Optional[str] = None, limit: int = 50) -> dict:
    """Return parsed entries + validity flags.

    Returns:
        {
          "entries": [...newest-first...],
          "count": int,
          "partial": bool,
          "invalid_count": int,
        }
    Raises a sanitized exception on Redis unavailability (caller → 503).
    """
```

- `get_entry_by_id()` is **deferred** until a route actually supports lookup by
  `exchange_id`. Do not add it in Phase 2.
- All reads go through the existing `redis_client.get_redis()` accessor.

---

## 7. Expected Implementation Files (Phase 2)

| File | Change | Risk |
|------|--------|------|
| `federation-game/backend/councilor_exchange.py` | NEW, read-only helper (`get_entries` only) | low |
| `federation-game/backend/routes/councilor_exchange.py` | NEW, route + validation + 503 handling | low |
| `federation-game/backend/main.py` | ADD route import + operator-gate wiring | low |
| `federation-game/backend/tests/test_councilor_exchange.py` | NEW, isolated tests (see §9) | low |

**Terminology correction:** Redis holds a **LIST containing JSON-encoded
entries** (each LIST element is a `json.dumps` string). This is **not** JSONL
(newline-delimited file content). The plan uses "Redis LIST of JSON-encoded
entries" throughout.

**Untouched in Phase 2:** `metrics_llm.py`, `npc_decree.py`,
`councilor_bridge.py`, `npc_autonomy.py`, `institutions.py`, and any Redis
write path.

---

## 8. Deploy / Verify (only after separate approval + PR + feature branch)

1. `python -m py_compile federation-game/backend/councilor_exchange.py federation-game/backend/routes/councilor_exchange.py`
2. scp only the new files + `main.py` route wiring to VPS `/docker/federation-game/backend`.
3. `docker compose restart backend` (backend only).
4. Authenticated `GET /simulation/operator/councilor-exchange` → expect `200`
   with `{"entries":[],"count":0}` (keys do not exist yet).
5. Confirm no `/metrics`-style public exposure; confirm operator gate rejects
   unauthenticated calls.

---

## 9. Tests Must Prove

- [ ] empty shared ledger → `200`, `entries:[],count:0`
- [ ] empty inbox (valid `char_id`) → `200`, empty
- [ ] empty outbox (valid `char_id`) → `200`, empty
- [ ] valid `char_001` and `char_306` return correctly when seeded
- [ ] invalid `char_id` → `400`
- [ ] invalid `view` → `400`
- [ ] `inbox`/`outbox` without `char_id` → `400`
- [ ] `limit` boundaries (`1`, `200`, and out-of-range → `400`)
- [ ] newest-first ordering: `RPUSH A B C`, request `limit=2` → response order **`C, B`**
- [ ] malformed entry inside window: `partial:true`, `invalid_count:1`, valid entries still returned newest-first; no older entries fetched as replacement
- [ ] malformed JSON entry in LIST → `partial:true`, `invalid_count:1`, valid entries still returned
- [ ] Redis outage (fake client raises) → sanitized `503`, no raw error
- [ ] **no Redis write method is invoked** (assert `rpush`/`hset`/`set`/etc. never called)

---

## 10. Rollback

- Remove the route import + the two new backend files + the test file. No ledger
  keys were ever written in Phase 2, so nothing to clean in Redis. Single PR,
  revertable.

---

## 11. Open Questions (resolved by review)

1. Route location: dedicated `routes/councilor_exchange.py` ✅ (not buried in
   `routes/metrics.py`).
2. Auth: operator-gated `/simulation/operator/councilor-exchange` ✅; stop and
   report if no gate exists.
3. Invalid `char_id`/`view`/missing `char_id`: `400` ✅ (not `[]`).
4. Empty vs unavailable: `200` vs `503` ✅.
5. Metrics: deferred to Phase 3 ✅.

---

*This is a plan. Nothing here is implemented or committed. Implement only after
approval on a dedicated feature branch, with its own PR.*
