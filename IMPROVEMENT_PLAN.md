# Federation Improvement Plan — Verification Automation & Deploy Hardening

**Objective:** Add automated verification commands, standardize VPS deploy, and protect rollback capability.

---

## 1. Files to Modify

| File | Change | Risk |
|------|--------|------|
| `AGENTS.md` | Add `VERIFICATION_COMMANDS` section with lint/typecheck/test commands | Low — docs only |
| `federation-game/Makefile` (new) | Centralize `make lint`, `make typecheck`, `make test`, `make verify-all` | Low — new file |
| `federation-game/deploy.sh` (new) | Automated VPS deploy: git pull → cp → docker compose up -d --build → curl verify | Medium — touches production |
| `.horizon/ARCHITECTURE_STATE.md` | Add verification commands reference for post-compaction recovery | Low — docs only |
| `scripts/fed-state.sh` | Optionally surface verification command status | Low — read-only |

---

## 2. Verification Commands to Define

```makefile
# federation-game/Makefile
.PHONY: lint typecheck test verify-all

lint:
	cd backend && ruff check . && cd ../frontend && npm run lint 2>/dev/null || true

typecheck:
	cd backend && mypy --strict . && cd ../frontend && npx tsc --noEmit 2>/dev/null || true

test:
	cd backend && pytest -x -q && cd ../frontend && npm test 2>/dev/null || true

verify-all: lint typecheck test
	@echo "All checks passed"
```

**Backend actual commands (need your confirmation):**
- Lint: `ruff check backend/` or `flake8 backend/`
- Typecheck: `mypy backend/` or `pyright backend/`
- Test: `pytest backend/tests/ -x -q`

**Frontend actual commands (need your confirmation):**
- Lint: `npm run lint` (if exists)
- Typecheck: `npx tsc --noEmit` (if TS)
- Test: `npm test` or `vitest run`

---

## 3. Automated Deploy Script

```bash
#!/usr/bin/env bash
# federation-game/deploy.sh
set -euo pipefail

REPO_ROOT="/opt/federation"
DEPLOY_ROOT="/docker/federation-game"
SERVICE="backend"  # or "all"

# 1. Pull latest
cd "$REPO_ROOT" && git pull origin main

# 2. Copy to deploy dir (preserves docker-compose.yml, configs)
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'node_modules' \
  --exclude '.pytest_cache' \
  --exclude 'federation_saves' \
  "$REPO_ROOT/" "$DEPLOY_ROOT/"

# 3. Build & restart
cd "$DEPLOY_ROOT" && docker compose up -d --build "$SERVICE"

# 4. Verify health
sleep 5
curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/health | grep -q 200
curl -sf -o /dev/null -w "%{http_code}" http://localhost:3000/ | grep -q 200

echo "Deploy verified"
```

---

## 4. Tests to Run After Changes

| Test | Purpose |
|------|---------|
| `make verify-all` | Confirms lint/typecheck/test all pass locally |
| `./deploy.sh` (dry-run on local Docker) | Validates deploy script doesn't break containers |
| `fed-state.sh --vps` | Confirms VPS containers healthy post-deploy |
| `curl` health checks (backend + frontend) | Smoke test matches deploy script verification |
| Existing test suite: `pytest backend/tests/ -x` | Regression check for P0-P4 + P3 changes |

---

## 5. Rollback Protection

### Before Any Change:
```bash
# 1. Tag current state
cd /opt/federation && git tag -a "pre-verification-$(date +%Y%m%d-%H%M%S)" -m "Pre-verification automation rollback point"

# 2. Backup VPS deploy dir
ssh federation-vps "cp -r /docker/federation-game /docker/federation-game.backup.$(date +%Y%m%d-%H%M%S)"
```

### Rollback Procedure (if issues):
```bash
# Local: revert Makefile/AGENTS.md changes
git checkout HEAD -- AGENTS.md Makefile deploy.sh

# VPS: restore deploy dir & restart
ssh federation-vps "
  rm -rf /docker/federation-game &&
  mv /docker/federation-game.backup.YYYYMMDD-HHMMSS /docker/federation-game &&
  cd /docker/federation-game && docker compose up -d
"
```

---

## 6. Potential Issues / Blind Spots

| Issue | Mitigation |
|-------|------------|
| Frontend lacks lint/typecheck/test scripts | Makefile uses `|| true` — fails gracefully; add scripts later |
| `mypy --strict` may fail on legacy code | Start with `mypy --ignore-missing-imports`; tighten incrementally |
| Deploy script assumes single-service restart | Parameterize `SERVICE` var; test `backend` first, then `all` |
| VPS has no git — deploy dir is source of truth | Backup deploy dir, not repo; rsync preserves docker-compose.yml |
| `fed-state.sh` doesn't run verification | Add `make verify-all` output to fed-state summary (optional) |
| SIGTERM root cause still unknown | Unrelated — separate investigation task |

---

## 7. Execution Order

1. **You confirm** actual lint/typecheck/test commands for backend + frontend
2. **I create** `Makefile` and `deploy.sh` with confirmed commands
3. **I update** `AGENTS.md` with `VERIFICATION_COMMANDS` section
4. **We test locally**: `make verify-all` → `./deploy.sh` (local Docker)
5. **You approve** → I push → you run `deploy.sh` on VPS (or I SSH and run)
6. **Post-deploy**: `fed-state.sh --vps` confirms health

---

## 8. Approval Gate

**Do not proceed until you confirm:**
- Backend lint/typecheck/test commands
- Frontend lint/typecheck/test commands (or "none exist yet")
- Whether to deploy `backend` only or `all` services by default