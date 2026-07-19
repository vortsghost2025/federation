# S3A — Steward Local-Only Federation-World Writer Core

## STATUS: LOCAL-ONLY CORE. NO LIVE BACKEND.

> **S3A DOES NOT WRITE TO LIVE FEDERATION INFRASTRUCTURE.**

> **NO LIVE REDIS, DATABASE, DOCKER, DAGU, HTTP, SSH, NPC-INBOX, OR COGNITION CONNECTOR EXISTS.**

> **A SEPARATE EXPLICIT AUTHORIZATION IS REQUIRED BEFORE IMPLEMENTING OR ENABLING A LIVE S3 BACKEND.**

This module is the governed writer core only. It produces deterministic,
redacted, replay-safe `AuditResult` objects against an injected in-memory
store. It has zero live connectors by static proof (see `s3a_static.py`
and `tests/unit/test_s3a.py::TestNoLiveConnectors`).

## Authority

Authorized under the GPT-pasted "S2.1 corrections + S3A spec" directive
(phase 1 of the Steward track). All work is local-only: no push, no fetch,
no live mutation of Federation / Redis / Docker / Dagu / VPS state.

## Module map

| Module | Responsibility |
|--------|----------------|
| `s3a_action.py` | `ProposedAction` schema, strict identity, deterministic `action_id` (SHA-256 over canonical JSON). |
| `s3a_policy.py` | Capability matrix (AUTO_PERMITTED / APPROVAL_GATED), fail-closed `ApprovalArtifact` validation. |
| `s3a_store.py` | `InMemoryStore` narrow protocol, optimistic versioning, bounded occurrence counter, idempotency ledger. |
| `s3a_audit.py` | `AuditResult`, `make_result_id`, `redact_evidence` (secrets / paths / private NPC / exceptions). |
| `s3a_councilor_watch.py` | Synthetic read-model renderer with explicit marker fields. |
| `s3a_operator.py` | Operator identity, `EXCLUDED_SUBSYSTEMS`, stable actor ID. |
| `s3a_planner.py` | Pure planner; unknown-evidence suppression; action-storm dedupe. |
| `s3a_writer.py` | `WriterCore` transactional executor; idempotent replay; clone-before-mutate. |
| `s3a_static.py` | AST scan forbidding live-connector imports. |
| `s3cli.py` | Local-only CLI; traversal/symlink protection; mandatory banner. |

## Determinism contract

- No wall-clock, UUID, or randomness in any module. All timestamps are
  supplied by the caller (`now_token`, `requested_at`).
- `action_id = "act_" + sha256(canonical_json(identity_fields))`.
- `result_id = "res_" + sha256(action_id + decision + requested_at)`.
- Two replays of the same action yield byte-identical `result_id` and are
  flagged `idempotent_replay=True`.

## Capability matrix

AUTO_PERMITTED: `steward:incident:create|update`,
`steward:work_order:create|assign_owner`,
`steward:diagnostic_snapshot:create`, `steward:occurrence:increment`,
`steward:notification:suppress_duplicate`, `steward:councilor_watch:render`.

APPROVAL_GATED (fail-closed without valid `ApprovalArtifact`):
`steward:npc_message:inject`, `steward:npc_cognition:trigger`,
`steward:redis_external:write`, `steward:docker:mutate`,
`steward:deployment:change`, `steward:schema:change`,
`steward:configuration:change`, `steward:external_notification:send`.

## Tests

`tests/unit/test_s3a.py` — 44 adversarial + regression tests (1 skipped on
platforms without symlink privilege). Run:

```
$env:PYTHONPATH="<worktree root>"
python -m unittest tests.unit.test_s3a
```

## Live backend prerequisites

Before any S3 live connector is implemented or enabled, a separate explicit
authorization must be granted covering: target subsystem, credential
handling, network egress policy, and rollback. This core deliberately ships
with none of those.
