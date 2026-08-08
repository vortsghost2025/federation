# Federation Verification

## Overall Project Status

**PARTIAL — active-scope correction in progress**

The verification engine has been repaired on both local (Windows) and VPS (Linux)
surfaces. The default `syntax` check now correctly excludes test modules, fix
scripts, helper scripts, and historical candidates via a bounded active-file policy.
Documentation has been updated to match.

This is **not** a completed repair pass. The snapshot and cross-surface evidence
remain incomplete (see Remaining blockers).

## What the Engine Checks

### Default `syntax` -- active runtime scope (policy-based, not import-graph-proven)

Default `syntax` and `all` check only active runtime Python files. Files are
included if they are in `backend/`, `backend/routes/`, `backend/alembic/`, or
`npc-agent/`. Files are **excluded** from the default check if their filename
matches any of these patterns:

| Pattern | Reason |
|---------|--------|
| `*_vps.py` | non-active VPS helper |
| `fix*.py` | fix script |
| `*_fix.py` | fix script |
| `kilo*_fix*.py` | kilo fix script |
| `strip_duplicates.py` | dedup helper |
| `check_*.py` | check script |
| `smoke*.py` | smoke test |
| `manual*.py` | manual test |
| `vps_test.py` | VPS test |
| `test_*.py` | test module |
| `*_test.py` | test module |
| `_find_*.py` | find helper |
| `_fix_*.py` | fix helper |
| `_strip_*.py` | strip helper |

This is a **filename-based active-file policy**, not proof from the complete
runtime import graph. A file not matching an exclusion pattern is assumed active
even if it may be unused at runtime.

The excluded-file list with reasons is logged during every default `syntax` run.

### `syntax-broad` -- all candidates

`syntax-broad` checks every `.py` candidate found in the same directories,
**including** all excluded-by-default files: helpers, fix scripts, historical
candidates, and test modules. This is intended to catch syntax errors in files
that are not part of the active runtime.

**Known pre-existing:** `backend/main_vps.py` (VPS only) fails syntax at line 1761.
This file is excluded from default `syntax` but is caught by `syntax-broad`.

### Default `frontend` -- served `public_html`

Default `frontend` checks JavaScript files in the **served** directory
(`public_html/`) when present, falling back to `frontend/`.

### `frontend-source` -- frontend source directory

`frontend-source` explicitly checks `frontend/` source files regardless of
`public_html/` presence.

### Node.js version limitation (VPS)

The VPS runs Node.js v12.22.9, which cannot parse optional chaining (`?.`) and
nullish coalescing (`??`). Three served frontend files fail `node --check`
because of this: `spectator.js`, `spectator.v2.js`, `starmap.js`. The engine
classifies these as `UNAVAILABLE` with reason `NODE_PARSER_TOO_OLD`, not as a
JavaScript syntax failure.

## Where the Engine Lives

| Surface | Location |
|---------|----------|
| Local (Windows) | `S:\federation\scripts\verify.py` + `S:\federation\scripts/verify.ps1` + `S:\federation\docs/VERIFICATION.md` |
| VPS (Linux) | `/docker/federation-game/scripts/verify.py` + `/docker/federation-game/docs/VERIFICATION.md` |

No PowerShell wrapper is placed on the VPS. The engine runs via `python3` on
Linux. Local and VPS files are identical (SHA-256 verified).

## Quick Start

### On the VPS (Linux)

```bash
# All default-safe checks (syntax + test inventory + frontend)
cd /docker/federation-game && python3 scripts/verify.py all

# Only active-runtime syntax
cd /docker/federation-game && python3 scripts/verify.py syntax

# All-candidate syntax (includes helpers, tests, historical)
cd /docker/federation-game && python3 scripts/verify.py syntax-broad

# Static test inventory
cd /docker/federation-game && python3 scripts/verify.py discover-static
```

### On local Windows

```powershell
# All default-safe checks
python scripts\verify.py all

# Only active-runtime syntax
python scripts\verify.py syntax
```

## Commands

### `all`

Default-safe checks only:
- Python syntax (`ast.parse` + `compile`, in-memory, no bytecode files).
  Active runtime scope only (see exclusion table above).
- Static test inventory via AST only (no pytest).
- Frontend JavaScript syntax (`node --check`) on served `public_html/`
  when available.

`all` does NOT invoke pytest, execute tests, contact the VPS runtime services,
or contact Redis, PostgreSQL, providers, Ollama, or external services.

### `syntax [--paths FILE...] [--changed]`

Validates Python syntax using `ast.parse` + `compile` (in-memory, no import,
no `__pycache__`). Defaults to active backend, routes, Alembic sources, and
npc-agent modules. Excludes test modules, fix scripts, and helpers per the
policy above. The excluded file list with reasons is logged.

### `syntax-broad [--paths FILE...]`

Like `syntax`, but does NOT apply the active-scope exclusion policy. Checks all
`.py` candidates, including helpers, fix scripts, and test modules.

### `discover-static`

Builds a conservative static test inventory via AST only. No pytest. No imports
executed. Every entry starts with `review_status=PENDING`.

### `collect --ack I_UNDERSTAND_COLLECT_INVOKES_PYTEST [--timeout SECONDS]`

Runs `pytest --collect-only` with cache disabled and a bounded timeout.
Explicit opt-in only. Refuses without proper `--ack` flag.

### `tests-isolated --allowlist PATH [--inventory PATH] [--timeout SECONDS]`

Runs only exact pytest node IDs listed in an external allowlist JSON.
Requires `status="APROVED"` in the allowlist. Refuses without proper
`--allowlist` flag. Exact node IDs only; no wildcards or keyword expressions.

## Result States

| State | Meaning |
|-------|---------|
| `PASS` | Check ran and passed. |
| `FAIL` | Check ran and failed. |
| `NOT_RUN` | Check was intended but skipped did not execute. |
| `UNAVAILABLE` | Required checker unavailable (e.g. Node.js too old). |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All requested checks PASS (or NOT_RUN). |
| 1 | One or more FAIL, or required checker UNAVAILABLE. |
| 2 | Usage error (invalid command or argument). |
| 3 | Internal engine error. |

## Artifact Location

All verification output is written outside the repository.

| Surface | Path |
|---------|------|
| Windows | `%LOCALAPPDATA%\Federation\verify\<timestamp>\` (fallback: `<user-home>\.local\share\Federation\verify\<timestamp>\`) |
| Linux | `$XDG_STATE_HOME/Federation/verify/<timestamp>/` (fallback: `~/.local/state/Federation/verify/<timestamp>/`) |

Files per run: `result.json`, `test-inventory.json`, `verify.log`

No AppData path is constructed on Linux. No repository logs are created.

## Constraints

- No installation or tooling in verification.
- No VPS runtime-service, Redis, PostgreSQL, provider, or Ollama contact in
  default commands.
- No `fed-state.sh` usage.
- No automatic deletion of prior runs.
- Verification tooling lives on the VPS host, not inside running containers.
- Active scope is a filename-based policy, not an import-graph proof.

## Known Pre-Existing Issues (Not Introduced by This Repair)

1. **`backend/main_vps.py` syntax error (line 1761)** -- VPS-only file with
   `':' expected after dictionary key`. Caught by `syntax-broad` only.
2. **Frontend JS optional chaining** -- `public_html/spectator.js`,
   `public_html/spectator.v2.js`, and `public_html/starmap.js` use `??` and
   `?.` operator syntax not supported by Node.js v12.22.9 on the VPS.
   Classified as `UNAVAILABLE` with `NODE_PARSER_TOO_OLD`.
3. **Local vs VPS source divergence** -- local `deploy_vps.sh` and
   `docker-compose.yml` hashes differ from VPS. VPS is authoritative.
4. **Frontend served from `public_html`, not `frontend/`** -- the container
   serves `public_html/*`, while source files live in `frontend/`.

## Remaining Blockers

- Local workspace (`S:\federation`) diverges from VPS on `deploy_vps.sh` and
  `docker-compose.yml`. Not modified.
- Local snapshot remains **PARTIAL**: full-manifest digest design not fully
  repaired into a self-verifying chained manifest.
- Bounded VPS byte snapshot remains **NOT CAPTURED**: host files are readable
  and some were compared by SHA-256, but not every mounted file was snapshotted.
- Selected host and container files matched by SHA-256; not every mounted file
  was compared.
- Overall status remains **PARTIAL**.
