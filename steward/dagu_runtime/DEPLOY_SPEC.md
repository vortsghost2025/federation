# Steward Dagu Python Runtime — Deployment Specification (DR-008)

> **STATUS: SPECIFICATION ONLY. NOT EXECUTED. NOT INSTALLED ON VPS. NOT PUSHED.**

This document describes how the qualification image *would* be deployed if and
when authorized. It is part of the local-only DR qualification package. No
action described here has been performed.

---

## 1. Scope & Hard Constraints

| Constraint | Status |
|---|---|
| Local-only build/qualify | ✅ Done (where Docker present) |
| No VPS modification | ✅ Enforced (read-only SSH for DR-001 only) |
| No push to any remote | ✅ Enforced (no `git push` in any artifact) |
| No live connectors | ✅ Verified (DR-004, DR-007) |
| No credentials copied | ✅ Verified (DR-007) |
| Dagu version pinned | ✅ Digest-pinned (DR-002) |
| Workflow manual-only | ✅ No schedule/trigger (DR-005) |

---

## 2. Base Image Pin

```
ghcr.io/dagucloud/dagu@sha256:5e715705e0c96e462417303f3e2fbbadc7f9cd15d153764c89fd1442e80a1d66
```

- Resolved from deployed `ghcr.io/dagucloud/dagu:latest` on VPS `187.77.3.56`
  (image id `5e715705e0c9`, Dagu v2.10.7, amd64/linux).
- **Never** rebuild from `:latest`. The digest is immutable.

---

## 3. Image Contents

- Debian-based Dagu runtime (as above) + `python3`/`python3-pip` (min).
- `steward/` package installed to `/opt/steward` (committed S1–S3C files).
- Source copy manifest: `source_manifest.txt` / `.json` (DR-003, SHA-256).
- Non-root user `steward` (uid/gid 1000) — matches deployed PUID/PGID.
- Entrypoint preserved: `tini -g -- /entrypoint.sh dagu start-all`.

**Explicitly excluded from the image:** docker CLI, git, ssh client,
compilers, redis/mysql/postgres clients, any credentials, `.git`, DBs,
`npc_agent_current.py`, federation backend, live snapshots.

---

## 4. Runtime Self-Test (DR-004)

Run inside the container after build:

```sh
python3 /opt/steward/steward/dagu_runtime/selftest.py
```

Exit 0 = shadow-only and safe. Non-zero = fail closed (do not deploy).

---

## 5. Workflow Installation (when authorized)

The Dagu workflow `steward-s3c-shadow-fixture.yaml` is **manual-only**:

- No `schedule` / `scheduler` block.
- No auto-trigger.
- Runs `python -m steward.s3ccli run-fixture --backend memory`.
- Ephemeral memory backend — nothing persisted.
- Expected result: `READY_FOR_SHADOW_ONLY`.

If ever installed on a Dagu instance, it must be triggered by an operator
action, never by a timer or watcher.

---

## 6. VPS Notes (for future authorized deployment)

- Deployed Dagu container `dagu-x4sr-dagu-1` exposes `8080/tcp` on
  **loopback only** (`127.0.0.1:32768`) — not public.
- The deployed image uses built-in Dagu auth (admin creds). **Those creds are
  NOT copied into this qualification image.**
- Any future deployment must preserve loopback-only exposure and the
  non-root user.

---

## 7. Verification Evidence (this DR run)

| Artifact | File |
|---|---|
| Source manifest (SHA-256) | `source_manifest.txt` / `source_manifest.json` |
| Runtime self-test | `selftest.py` (9 checks, all PASS) |
| Security scan | `security_report.json` (12 checks, all PASS) |
| Qualification harness | `run_qualification.py` → `qualification_report.json` |
| Dagu workflow | `steward-s3c-shadow-fixture.yaml` |
| Dockerfile | `Dockerfile` (digest-pinned) |

> Docker build/run was **environment-blocked** on the dev host (no Docker
> daemon). The local source-tree self-test + security scan substitute for the
> in-container run. In-container execution remains pending a Docker-capable
> environment. This is recorded, not hidden.
