# S3B — Steward Backend Qualification Harness

Local-only qualification harness for the Federation `steward:` world-writer backend.
It proves the adapter + backend contract (capability boundary, approval boundary +
revocation, fault injection, crash recovery) **without ever touching live
Federation infrastructure.**

---

## WARNINGS — READ BEFORE RUNNING

1. **LOCAL-ONLY.** This harness runs entirely on your machine. It never reaches
   the VPS, Docker, Redis, Dagu, or any live Federation service. All "writes"
   go to an in-memory dict or a throwaway local SQLite file under a temp dir.

2. **DO NOT PUSH.** S3B commits are local qualification evidence. They are NOT
   authorized for `git push` / `git fetch` against the Federation remote. Hold for
   review. Push is a separate, explicitly authorized step that has not been granted.

3. **NO LIVE-BACKEND MUTATION.** The qualification backend is a stand-in. It is
   not the production Redis writer. Under no circumstance does S3B mutate real
   Federation state, Redis keys, or world files. The approval-revocation safety
   property is proven against the local registry only.

4. **SQLITE3 IS ALLOWED ONLY INSIDE `sqlitedb.py`.** Every other module in
   `steward/s3b/` is forbidden from importing `redis`, `requests`, `urllib`,
   `socket`, `subprocess`, `docker`, `paramiko`, `psycopg`, `mysql`,
   `sqlalchemy`, `ssh`, `fabric`, `dagu`, `http.client`, or `telnetlib`. The
   static scanner (`static.py`) enforces this and is covered by tests.

---

## What is under test

`QualificationAdapter` consumes an S3A `WriteOutcome` (already governed +
deterministic + redacted) and persists the *approved mutation* to a backend.

| Property | Proof |
|----------|-------|
| Capability boundary | Backend whose `Capability` denies write/delete/cas is never asked to perform it. |
| Approval boundary | Write refused unless a live approval is attached and not revoked. |
| Revocation safety | Revoking an approval AFTER a write was accepted does NOT alter the persisted value; only *new* writes are refused. |
| Fault injection | Injected `WRITE_FAIL` / `CONNECTION_DROP` surface as failed persists, backend untouched. |
| Crash recovery | A value committed to the SQLite backend survives `reopen()` (simulated process restart). |
| No live connector | Static scan of `steward/s3b/` returns zero violations. |

## Layout

- `protocol.py` — `FaultKind`, `Receipt`, `Capability`, `Approval`,
  `InjectedFault`, and the process-global revocation registry.
- `memory.py` — in-memory backend implementing the protocol (fault injection).
- `sqlitedb.py` — SQLite persistent backend with `reopen()` crash recovery.
  **The only file permitted to import `sqlite3`.**
- `adapter.py` — `QualificationAdapter` routing S3A outcomes to a backend.
- `static.py` — `scan_path()` forbidden-connector scanner.
- `tests/unit/test_s3b.py` — 15 adversarial tests.

## Run

```powershell
cd <this-worktree>
$env:PYTHONPATH = (Get-Location)
python -m unittest tests.unit.test_s3b -v
```

## Status

All 15 S3B tests pass. Evidence is local-only; hold for review, do not push.
