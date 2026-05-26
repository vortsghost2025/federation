# Deployment Verifier - Post-Deploy Health Checker

## Purpose
Verifies deployment health after git push or deploy events. Reports failures to Gastown dashboard only - does not redeploy or fix.

## Usage

### As Post-Hook
```bash
python federation-game/monitoring/deployment_verifier.py --hook
```

### Manual Verification
```bash
python federation-game/monitoring/deployment_verifier.py --manual [--backend-url URL]
```

### As Bead
The bead definition is in `deployment_verifier.bead.json`.

## Verifications Performed

1. **Healthz Check**: GET `/healthz` expects HTTP 200
2. **Docker Containers**: All containers must show `healthy` or `Up` status

## Exit Codes
- `0`: All checks passed
- `1`: Verification failed (alert sent to dashboard)

## Alert Format
On failure: `DEPLOYMENT VERIFICATION FAILED: [specific failure details]`

## Environment Variables
- `BACKEND_URL`: Backend URL (default: http://localhost)
- `DOCKER_COMPOSE_FILE`: Docker compose file path (default: docker-compose.yml)
- `DEPLOYMENT_ID`: Deployment identifier (auto-generated timestamp)