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
- **Authentication prerequisite (corrected per prerequisite audit):** No existing
  application-layer operator guard was found in the codebase (`routes/admin.py`
  is unauthenticated; `auth_endpoints.py` is an unwired development-only authentication module; no
  `require_operator` / operator-key code exists anywhere). The approved
  authentication contract is **commit `563c7d3`**
  (`PHASE2_OPERATOR_ROUTE_AUTH_CONTRACT.md`). The Phase 2 feature branch
  **must implement the reusable `require_operator` dependency first**, and its
  isolated authentication tests **must pass before** the councilor-exchange
  router is wired into `main.py`. The route **must never exist in an
  unauthenticated intermediate state** — wiring is forbidden until the auth
  dependency and its tests are green.
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
- **Redis access (corrected per prerequisite audit):** there is **no** shared
  `redis_client.get_redis()` accessor in this codebase. Instead,
  `councilor_exchange.py` owns a **small lazy Redis accessor** (e.g. an inner
  `get_redis()` that calls `redis.from_url(REDIS_URL, decode_responses=True,
  socket_connect_timeout=3, socket_timeout=3)`). **No Redis connection or
  read occurs at module import.** The route calls the helper **only after
  `require_operator` succeeds**, so authorization always precedes any Redis
  access. The accessor must be injectable / patchable so isolated tests can
  run without a live Redis. `LRANGE` is the **only** permitted Redis command
  in Phase 2 — no writes (`rpush`/`hset`/`set`/`trim`/`expire`).

---

## 7. Expected Implementation Files (Phase 2)

| File | Change | Risk |
|------|--------|------|
| `federation-game/backend/operator_auth.py` | **NEW**, reusable `require_operator` dependency (per contract `563c7d3` §6) | low |
| `federation-game/tests/test_operator_auth.py` | **NEW**, isolated auth tests (Gate A) | low |
| `federation-game/backend/councilor_exchange.py` | NEW, read-only helper (`get_entries` only) + lazy Redis accessor | low |
| `federation-game/backend/routes/councilor_exchange.py` | NEW, route + explicit 400 validation + `Depends(require_operator)` + 503 handling | low |
| `federation-game/backend/main.py` | ADD route import + operator-gate wiring **only after Gate A passes** | low |
| `federation-game/tests/test_councilor_exchange.py` | NEW, isolated tests (see §9) | low |

> Path note: test files live in `federation-game/tests/` (not
> `backend/tests/`). All test paths above are corrected accordingly.

**Terminology correction:** Redis holds a **LIST containing JSON-encoded
entries** (each LIST element is a `json.dumps` string). This is **not** JSONL
(newline-delimited file content). The plan uses "Redis LIST of JSON-encoded
entries" throughout.

**Untouched in Phase 2:** `metrics_llm.py`, `npc_decree.py`,
`councilor_bridge.py`, `npc_autonomy.py`, `institutions.py`, and any Redis
write path.

---

## 7b. Validation and Authentication Inputs (explicit — required for 400/401)

FastAPI's automatic request validation MUST NOT produce **422** for any of the
contract inputs. The required behavior is **400** for invalid request payloads
and **401** for missing/invalid operator credentials (per
`PHASE2_OPERATOR_ROUTE_AUTH_CONTRACT.md` §7). Therefore the proposed
implementation must:

- receive the operator header as **optional** input, e.g.
  `Header(default=None)`, and **manually return 401** when the header is
  missing or malformed (never let FastAPI raise 422 for it).

**Authentication status codes (distinct):**
- missing operator header → **401**
- malformed operator header → **401**
- correctly formed header containing an **incorrect** operator key → **403**
- valid operator key → continue

(The 401 vs 403 distinction matters: 401 = no/malformed credential
present; 403 = credential present but rejected. Do not collapse both into a
single "invalid credential = 401" bucket.)
- receive `view`, `char_id`, and `limit` in a form that permits **explicit
  validation** — e.g. `view: Optional[str] = None`, `char_id: Optional[str]
  = None`, `limit: Optional[str] = None` (or typed-but-catchable) — and
  **manually parse `limit`**, returning a **sanitized 400** for non-integer
  or out-of-range values.
- **Explicit defaults during manual validation:**
  - absent `view` is manually normalized to `"shared"`.
  - absent `limit` is manually normalized to `"50"`.
  - absent `char_id` is allowed **only** for `view="shared"`.
  - `limit` is then manually parsed as an integer and checked against `1..200`.
  - FastAPI-generated 422 remains forbidden for these contract inputs.
- **authenticate before any Redis access** — `require_operator` is a
  `Depends` that runs ahead of the handler body, and the lazy Redis helper is
  invoked only inside the handler after auth succeeds.
- **never allow FastAPI-generated 422 responses** for these contract inputs;
  all validation is performed in handler code and returns the contract's
  required status codes (400 / 401 / 403 / 503).

---

## 8. Deploy / Verify (only after separate approval + PR + feature branch)

1. `python -m py_compile federation-game/backend/operator_auth.py federation-game/backend/councilor_exchange.py federation-game/backend/routes/councilor_exchange.py`
2. scp only the new files — **explicitly including `federation-game/backend/operator_auth.py`** — plus `main.py` route wiring to VPS `/docker/federation-game/backend`.
3. Recreate the backend container using the **separately authorized** deployment
   procedure (do not use a plain `docker compose restart backend`):
   ```
   docker compose -f /docker/federation-game/docker-compose.yml \
     up -d --no-deps --force-recreate backend
   ```
   - The operator key is placed into **runtime secret configuration outside
     chat**; no credential value appears in commands, logs, reports, or
     committed files.
   - **Container recreation is required** because `docker compose restart`
     does **not** reload changed environment values — only a fresh container
     picks up the new secret.
   - **Deployment remains separately unauthorized**; this plan only
     documents the step, it does not approve it.
4. Authenticated `GET /simulation/operator/councilor-exchange` → expect `200`
   with `{"entries":[],"count":0}` (keys do not exist yet).
5. Confirm no `/metrics`-style public exposure; confirm operator gate rejects
   unauthenticated calls.

---

## 9. Tests Must Prove (test-gated order)

**Gate A — `operator_auth.py` + `federation-game/tests/test_operator_auth.py`:**
- [ ] missing operator header → `401`
- [ ] malformed operator header → `401`
- [ ] incorrect operator key → `403`
- [ ] correct operator key → request proceeds
- [ ] missing/malformed server auth configuration → fails closed (route unavailable)
- [ ] no credential appears in logs or responses
- [ ] ordinary public routes remain unaffected

**Gate B — read-only helper + `federation-game/tests/test_councilor_exchange.py` (helper slice):**
- [ ] empty LIST → `{"entries":[],"count":0}`
- [ ] newest-first ordering: `RPUSH A B C`, `limit=2` → **`C, B`**
- [ ] malformed entry inside window: `partial:true`, `invalid_count:1`, valid entries still returned newest-first; no older entries fetched
- [ ] malformed JSON entry → `partial:true`, `invalid_count:1`, valid entries still returned
- [ ] Redis outage (fake client raises) → sanitized failure surfaced to caller
- [ ] **prove `LRANGE` is the only Redis command used** (assert no `rpush`/`hset`/`set`/`trim`/`expire`)

**Gate C — router + `main.py` wiring + remaining `test_councilor_exchange.py`:**
- [ ] unauthorized request performs **zero Redis calls**
- [ ] invalid authenticated request → sanitized `400` (not 422)
- [ ] empty authenticated ledger → `200`, `entries:[],count:0`
- [ ] Redis unavailable → sanitized `503`, no raw error
- [ ] ordinary public routes remain unaffected
- [ ] **every `/simulation/operator/*` route or operator router explicitly
  applies `require_operator`**
- [ ] tests prove **no operator route is mounted without that dependency**
- [ ] ordinary public routes remain **unchanged and accessible as before**

---

## 10. Rollback

- Remove the route import + the two new backend files + the test file. No ledger
  keys were ever written in Phase 2, so nothing to clean in Redis. Single PR,
  revertable.

---

## 11. Open Questions (resolved by review)

1. Route location: dedicated `routes/councilor_exchange.py` ✅ (not buried in
   `routes/metrics.py`).
2. Auth: operator-gated `/simulation/operator/councilor-exchange`. **Corrected
   per prerequisite audit:** no application-layer operator guard exists today;
   the approved contract is commit `563c7d3`. The feature branch must
   implement `require_operator` first and pass Gate A before any route wiring.
3. Invalid `char_id`/`view`/missing `char_id`: explicit `400` ✅ (not `[]`,
   and not FastAPI's automatic 422).
4. Empty vs unavailable: `200` vs `503` ✅.
5. Metrics: deferred to Phase 3 ✅.

---

## 12. Final Prerequisite Verdict

**READY FOR FEATURE BRANCH.**

The feature branch may implement authentication (`operator_auth.py` +
`require_operator`) and the read-only endpoint (`councilor_exchange.py` +
`routes/councilor_exchange.py`), but **`main.py` route wiring is forbidden
until the `require_operator` dependency and its isolated tests (Gate A) pass.**
The route must never exist in an unauthenticated intermediate state.

*This is a plan. Nothing here is implemented or committed. Implement only after
approval on a dedicated feature branch, with its own PR.*
