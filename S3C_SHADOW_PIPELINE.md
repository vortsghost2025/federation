# S3C — Steward Shadow-Mode Pipeline

`steward-s3c@0.1.0`

A shadow-mode pipeline that exercises the S3A governed-write shape against the
S3B qualification backends **without ever touching production Federation state**.
S3C proves the Steward world-writer behaves correctly (interlock, approval gate,
idempotent replay, fault injection, crash recovery) in a fully offline,
deterministic harness.

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

### 3. DAGU DRAFT IS ILLUSTRATIVE ONLY
Dagu workflow count is **UNKNOWN FROM THIS WORK BLOCK**. The local Steward workflow
draft (`steward/s3c/dagu_draft.py`) was **not installed** and is **not
schema-validated**. It exists only as a reference illustration of how a future
fail-closed Dagu pipeline *could* wrap the S3C CLI. No Dagu workflow was created,
edited, enabled, or scheduled.

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
  `sha256`. Verified by `compare-runs` and by the test corpus.
- **No live connectors**: static scan confirms `steward/s3c/*.py` imports no
  redis / requests / urllib / socket / subprocess / docker / paramiko / psycopg /
  mysql / sqlalchemy / ssh / fabric / dagu / http.client / telnetlib.
- **Replay corpus**: 20 synthetic cases with expected decisions; all asserted by
  `tests/unit/test_s3c.py`.

## Running

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m steward.s3ccli run-fixture --findings find_a find_b --approve
python -m steward.s3ccli readiness
python -m steward.s3ccli compare-runs
python -m steward.s3ccli dagu-draft
python -m unittest tests.unit.test_s3c   # 50 adversarial cases
```

## Status

S3C is complete and locally verified. It is **held for human review** and must not
be pushed or wired into any live pipeline until explicitly authorized.
