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

> **CONTAINER RUNTIME QUALIFICATION COMPLETE (DR-006).** A local Docker daemon
> was made available by starting the already-installed Docker Desktop (no
> install/configure, no K8s enable, no registry sign-in). The image was built
> (`steward-dagu-runtime:qualification-8478d1f`, image id
> `sha256:6283b9337c53...`) and run in a **disposable** container with a temp
> volume. The workflow executed twice with **byte-identical** readiness output
> (SHA-256 `2929EB29...`), `READY_FOR_SHADOW_ONLY`, no `READY_FOR_LIVE`, no
> SQLite created, temp artifacts cleaned. The container + temp volume were
> removed; the image is **preserved locally for review only** — NOT pushed,
> NOT deployed, VPS untouched.
>
> Two qualification layers are now evidenced:
> 1. **SOURCE qualification** — static + in-tree self-test (DR-004) and security
>    scan (DR-007): both PASS, no Docker required.
> 2. **CONTAINER RUNTIME qualification** — real build + disposable run (DR-006
>    Q3–Q8): PASS, Docker required, now satisfied.
>
> The previous "environment-blocked" note applied only to the earlier
> Docker-less attempt and is superseded by this run.
