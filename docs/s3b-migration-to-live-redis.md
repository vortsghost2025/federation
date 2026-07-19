# S3B → Live Federation Redis: Migration Spec (docs only)

This document describes, in specification form only, how the S3B qualification
backend contract maps onto the real Federation `steward:` world-writer that targets
Redis. **No code is written here.** S3B is the contract proof; the live backend
is a future, separately-authorized deliverable.

---

## 1. Key-namespace mapping

S3B persists under synthetic keys `world:<action_digest>`.

Live Redis mapping (proposed):

| S3B concept | Live Redis |
|-------------|-------------|
| `world:<digest>` | `steward:world:<digest>` (or the real Federation world-key scheme owned by S2/S3A) |
| `Receipt.seq` | Redis `INCR` sequence per world namespace (monotonic durability marker) |
| `value` blob | Redis `SET` / `SETEX` with TTL from `Approval.expires_at` |
| capability `granted_for` | Redis ACL user / key-prefix scope, not a free-form string |

The live key scheme is owned by S2 (read-only adapters) + S3A (writer core).
S3B does not invent live keys; it forwards the governed `action_id` digest.

## 2. Approval boundary → live enforcement

In S3B the revocation registry is an in-process dict. Live enforcement requires:

- Approval tokens issued by the Federation operator (not self-generated).
- Revocation published to a shared store (Redis key `steward:approval:<token>`
  with a `revoked` flag, or a signed revocation list) so **all writer processes**
  see the same liveness — this is what prevents the `--workers` multi-process bug
  described in FEDERATION_INDEX (single `game_state` singleton constraint).
- `is_approval_live` becomes a store lookup, not a local dict.

## 3. Fault injection → live equivalents

| S3B injected fault | Live analog |
|--------------------|-------------|
| `WRITE_FAIL` | Redis `SET` raises / returns nil (quorum loss, OOM) |
| `CONNECTION_DROP` | Mid-transaction connection reset before `EXEC` |
| `CORRUPT_READ` | CRC/tag mismatch on read (anti-tempering check) |
| `PARTIAL_WRITE` | `SET` acked but replica not converged (read-your-writes gap) |

The live backend must surface these as the same `InjectedFault`-style exceptions
(or typed `Receipt.ok=False`) so the adapter's handling is unchanged.

## 4. Crash recovery

S3B proves a committed SQLite row survives `reopen()`. Live proof requires:

- Writes are atomic (Redis `SET` is atomic; multi-key uses `MULTI/EXEC`).
- No external "publish" happens before the durable write confirms.
- On restart, the writer re-reads from Redis (source of truth), never from a local
  file — the opposite of S3B's local-only simulation.

## 5. Prerequisites before any live backend exists

1. S2 read-only adapters finalized and merged.
2. S3A writer core + A-evidence signed off (cross-process determinism proven).
3. Federation operator issues real approval tokens + revocation channel.
4. VPS Federation Redis ACL scoped to `steward:` prefix only.
5. Explicit push/authorization granted (currently: **not authorized**).

Until then, S3B remains the local-only qualification contract.
