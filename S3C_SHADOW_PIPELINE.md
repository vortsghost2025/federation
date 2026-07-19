# S3C — Steward Shadow-Mode Pipeline

`steward-s3c@0.1.0`

A shadow-mode pipeline that exercises the S3A governed-write shape against the
S3B qualification backends **without ever touching production Federation state**.
S3C proves the Steward world-writer behaves correctly (interlock, approval gate,
idempotent replay, fault injection, crash recovery) in a fully offline,
deterministic harness.

## Lineage / Base

- **True base: S3B** commit `f74e66b` (`s3b: shadow-mode qualification backends`).
  Verified by `git merge-base --is-ancestor f74e66b HEAD` → true. The 3 S3C
  commits sit directly atop S3B.
- **S3A** (`fbca26d`, branch `feature/steward-s3-writer-core`) is a **sibling
  branch**, not an ancestor. S3C is wire-compatible with the S3A `steward@0.3.0`
  shape but does **not** descend from S3A's commit graph.
- **S2** (read-only live adapters) exists locally (e.g. `bc75e36
  feat(steward): add S2 read-only live adapters`). S3C does not depend on S2 at
  runtime; S2 is the separate read-only live-adapter track.

---

## ⚠️ MANDATORY WARNINGS

### 1. NO LIVE APPLY
S3C has **no live-apply / production mode**. The only permitted modes are:

- `fixture_plan`
- `fixture_shadow_apply`
- `live_readonly_plan`
- `live_readonly_shadow_apply`

Every one of these is shadow-only. The safety interlock (`steward/s3c/interlock.py`)
fails closed: any attempt to add a `live_apply` mode, load a live writer, attach a
wildcard approval, or write outside a local safe directory is refused
(`decision="denied"`, backend untouched). S3C is **never** permitted to mutate
Federation Redis, Docker containers, the VPS, Dagu, or any protected Federation file.

### 2. NO PUSH
No push was performed during this work block according to the complete command and
audit trail. The branch has no configured upstream and no local remote-tracking ref.
These local facts do not independently prove that no similarly named remote branch
exists. Do not push this branch unless explicitly authorized by a human operator.

### 3. DAGU DRAFT IS ILLUSTRATIVE ONLY (so far)
Dagu workflow count is **UNKNOWN FROM THIS WORK BLOCK** (the local draft has not
been installed yet). The local Steward workflow draft (`steward/s3c/dagu_draft.py`)
is **not schema-validated**. It exists only as a reference illustration of how a
future fail-closed Dagu pipeline *could* wrap the S3C CLI.

> **Phase 2 authorization (this directive):** the directive authorizes installing
> exactly ONE manual-only Dagu workflow (`steward-s3c-shadow-fixture`) that runs
> only `fixture_shadow_apply` against synthetic data. As of the last edit to this
> file, that install had **not yet run**; the Dagu count remains UNKNOWN until
> Phase 2 completes. No schedule/trigger/auto-run is permitted.

---

## Architecture

```
RunManifest (S3C-002)
  -> SourceProfile (S3C-005)
  -> ShadowProposedAction (S3C shadow model, wire-compatible with S3A @0.3.0)
  -> SafetyInterlock (S3C-004, fail-closed)
  -> ShadowWriterCore (writer.py)
       -> S3B QualificationAdapter over an S3B backend (S3C-006)
  -> RunBundle (S3C-007, byte-deterministic SHA-256)
  -> ReadinessEvaluation (S3C-010, NEVER READY_FOR_LIVE)
```

For `live_readonly_*` modes, the orchestrator delegates to the read-only rehearsal
module (S3C-008), which is deterministic and has its SSH/docker transport **disabled
by default** — it replays a fixed fixture and never executes live commands or
discloses secrets.

## Safety properties (proven by tests)

- **Fail-closed interlock**: 9 independent gates; any single failure → denied.
- **No auto-approval**: a shadow action only commits when its
  `approval_state == "approved"` AND a valid, non-expired, non-wildcard
  `ShadowApprovalArtifact` is supplied and passes `validate_against`.
- **Wildcard rejection**: `*` in capability or scope is forbidden at both the
  interlock and the approval layer.
- **Shadow-only namespace**: every action/target/approval must live under
  `steward:shadow:`. A `steward:live:` namespace cannot even be constructed.
- **Determinism**: identical inputs → identical `run_id`, identical bundle
  `sha256`. Verified by the test corpus **and** by running two separate Python
  processes under `PYTHONHASHSEED=1` vs `PYTHONHASHSEED=987654` with the same
  inputs: all six artifact SHA-256 values (manifest, actions, outcomes,
  readiness, bundle, and the full 64-char `bundle_hex`) are byte-identical
  (`tests/unit/test_s3c.py::test_051/052` lock this in). Differing *input* order
  legitimately yields different `source_finding_id` → different `action_id`; that
  is semantic difference, not non-determinism.
- **No live connectors**: static scan confirms `steward/s3c/*.py` imports no
  redis / requests / urllib / socket / subprocess / docker / paramiko / psycopg /
  mysql / sqlalchemy / ssh / fabric / dagu / http.client / telnetlib.
- **Replay corpus**: 20 synthetic cases with expected decisions; all asserted by
  `tests/unit/test_s3c.py`.

## Live read-only rehearsal (performed this block)

A real read-only rehearsal against `federation-vps` (SSH `root@187.77.3.56`) was
run **twice** and was stable:

- `docker ps` (bounded), `docker inspect`/`stats` on the federation containers
  (bounded depth), `redis-cli DBSIZE` / `PING` (count + liveness only — **no
  values, no NPC bodies, no secrets read**), and one bounded HTTP `GET` to the
  backend port.
- The collected observations were fed into `_apply_to_fresh_backend` twice.
  Normalized observations were **deterministic**; the interlock allowed
  `live_readonly_shadow_apply` with `backend_qualification_only`; every decision
  came back `"denied"` — correct, because a shadow-observation pass has no
  approval artifact to commit.
- The produced bundle differed **only** by the per-run label/idempotency key
  (expected cross-run metadata, not content non-determinisn).

This rehearsal used the real `rehearsal.collect_observations(execute=True)` path
in read-only mode — it is **not** the `execute=False` placeholder fixture, and it
wrote and removed a temp bundle on disk (never committed).

## Running

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m steward.s3ccli run-fixture --findings find_a find_b --approve
python -m steward.s3ccli readiness
python -m steward.s3ccli compare-runs
python -m steward.s3ccli dagu-draft
python -m unittest tests.unit.test_s3c   # 52 adversarial cases
```

## Status

S3C is complete and locally verified. It is **held for human review** and must not
be pushed or wired into any live pipeline until explicitly authorized. Phase 2
(optional one-off manual Dagu fixture workflow) is authorized by the directive but
had not been installed as of the last edit.
