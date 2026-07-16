# Phase 2 — Operator Route Authentication Contract

**Status:** DRAFT (docs-only contract, not approved for implementation)
**Branch:** `bridge/memory-phase-1` (plan lives here; implementation on its own feature branch)
**Authored:** 2026-07-16
**Prerequisite:** The read-only baseline audit found **no existing application-layer
operator/admin route or demonstrated HTTP authentication** in `main.py`. The Phase 2 plan
(`PHASE2_EXCHANGE_LEDGER_PLAN.md`) therefore requires this contract to exist before any
`/simulation/operator/*` route is exposed. **No route may ship without it.**

This document defines the authentication and authorization contract for operator routes.
It is a specification only. No middleware, dependency, or endpoint is implemented here.

---

## 1. Threat Model

The operator route exposes councilor speech, hypotheses, objections, and artifact
references. The following actors must be considered:

- **Unauthenticated internet caller** — must be rejected; the route is not public.
- **Ordinary authenticated player** — has game access but must NOT reach operator routes.
- **Compromised frontend client** — a stolen player session/token must not escalate to
  operator access.
- **Internal container** — other services in the Docker network are not automatically
  trusted as operators.
- **Administrator / operator** — the intended caller, holding the operator credential or
  signed token.
- **Leaked logs or headers** — an attacker with access to logs/proxies must not recover a
  usable credential or enough to forge one.

---

## 2. Route Scope

- `GET /simulation/operator/councilor-exchange`
- **All** future `/simulation/operator/*` endpoints.
- Operator routes **must never inherit** the ordinary public-route access rules. They are
  a distinct protection class.
- If a future operator route forgets the dependency, it must fail closed (see §4 and §7).

---

## 3. Authentication Mechanism

- The initial Phase 2 mechanism is a **single server-side operator API key** (shared
  secret) supplied through a **dedicated HTTP header** (exact name is an open decision, §9).
- Comparison of the supplied value uses **constant-time** comparison to avoid timing
  side-channels.
- The route **fails closed** when the operator secret configuration is missing or malformed:
  refuse to serve the route rather than serving it unprotected.
- **No credential in URL, query parameters, path, logs, error messages, metrics, Redis, or
  HTTP responses.** It is never committed to the repository.
- **Reverse-proxy / network protection alone is insufficient.** Authentication must be
  enforced in application code, not only assumed from Traefik/VPS firewalling.
- **Signed short-lived operator tokens are a possible later upgrade**, not the initial
  mechanism. Token issuance, expiration, clock handling, signing, and verification are out
  of scope for the initial version (see §10).

---

## 4. Authorization Behavior

- **Missing credential** → `401 Unauthorized`.
- **Invalid credential** → `403 Forbidden`.
- **Valid operator credential** → continue to handler.
- Use **identical sanitized response bodies** for `401`/`403` where useful to reduce
  information leakage (do not reveal *which* failure occurred beyond what is necessary).
- **Fail closed** if auth configuration is unavailable or malformed: refuse to serve the
  route rather than serving it unprotected.

---

## 5. Configuration Rules

- The secret/token signing key comes from **runtime secret configuration** (the deployed
  `.env` / secret store), never hard-coded.
- **Never committed** to the repository.
- **Never printed** by diagnostics, `/metrics`, health checks, or error traces.
- At startup: if operator protection is not correctly configured, the application must
  **clearly fail** OR the operator router must **remain disabled** — it must not start
  exposed-and-unprotected.

---

## 6. FastAPI Integration Proposal (signatures only, no implementation)

A single reusable dependency is applied explicitly to every operator router.

```python
from fastapi import Depends, Header, HTTPException
from typing import Annotated

# Returns None on success; raises 401/403 on failure.
# Constant-time comparison; never logs the raw credential.
def require_operator(
    x_operator_token: Annotated[str | None, Header()] = None,
) -> None:
    ...

# Applied per-route, never globally by accident:
@router.get("/simulation/operator/councilor-exchange")
def get_councilor_exchange(
    _op: Annotated[None, Depends(require_operator)],
    ...
) -> ExchangeView:
    ...
```

- `require_operator` is the **only** gate; operator routers import it directly.
- No Redis read occurs before `require_operator` succeeds (see §7).

---

## 7. Tests Required Before Phase 2 Implementation Can Pass

- Missing header → `401`.
- Malformed header → `401` or `403` (sanitized).
- Incorrect credential → `403`.
- Correct credential → `200` and correct body.
- Credential value **not written to logs** (assert log capture contains no secret).
- Route **unavailable / fail-closed** when auth config is missing or malformed.
- Ordinary public routes (e.g. `/metrics`, player endpoints) **unaffected** by the operator
  dependency.
- **All** operator routes enumerate the `require_operator` dependency (static check or test
  that every `/simulation/operator/*` path is covered).
- **No Redis reads** occur before authorization succeeds (assert no Redis client call in the
  dependency path).

---

## 8. Deployment and Review Gate

- Run all local tests first; all must pass.
- Explicit diff review proving only intended files changed and no public route gained
  operator data.
- External unauthenticated probe is **rejected**.
- Authenticated probe (with the real operator credential) is **accepted**.
- **No secret exposure** at any step.
- **Stop for Sean's approval before deployment.** Do not self-deploy.

---

## 9. Open Decisions

- Exact header name (e.g. a dedicated `X-Operator-Token` vs `Authorization: Bearer …`).
- Initial choice: **one shared operator API key**.
- Later option: **signed short-lived operator tokens** (upgrade path, not initial).
- Rotation procedure for the key remains an open decision.
- Whether the **entire operator router is disabled by default** until explicitly enabled.

---

## 10. Recommended Smallest Phase 2 Choice

- One **dedicated operator API-key header** carrying a single shared operator key.
- One **server-side runtime secret** (from runtime secret configuration, never hard-coded
  or committed).
- **Constant-time comparison** of the supplied key.
- A reusable `require_operator` FastAPI dependency applied explicitly to every operator
  route.
- The operator router is **disabled or fails closed** when the secret is unavailable.

**Out of scope for the initial version:** token issuance, expiration, clock handling,
signing, and verification. Those belong to the later signed-token upgrade, not Phase 2's
first implementation.

Reuse `require_operator` on every `/simulation/operator/*` route; never apply operator
semantics to public routes.

---

## 11. Non-Goals (explicit)

- Not a general player-auth redesign.
- Not Phase 3 write path, append helper, or exchange counters.
- Not a monitoring/metrics change.
- Not a VPS, Docker, or secret-rotation task.
- **Implementation remains unauthorized** — this contract is specification only.

---

*Audit note (2026-07-16): no existing operator-route authentication pattern was found in
`backend/main.py`; `simulation_operator.py` is an internal service, not an HTTP route. This
contract exists to close that gap before any Phase 2 endpoint is exposed.*
