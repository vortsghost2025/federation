# Deployment Verifier - Post-Deploy Health Checker

## Overview

The Deployment Verifier runs post-deployment to automatically verify system health:

1. **Health Check**: Curling `/healthz` endpoint (expects 200 OK)
2. **Container Check**: Docker compose ps (all containers should show 'healthy' or 'Up')

On failure, sends alert to Gastown dashboard: `DEPLOYMENT VERIFICATION FAILED: [specific failure details]`

## Files

- `deployment_verifier.py` - Python implementation (recommended)
- `deployment-verifier.sh` - Bash implementation

## Usage

### As Post-Hook

Add to your git post-push hook or CI/CD pipeline:

```bash
# Python version
python federation-game/monitoring/deployment_verifier.py --hook

# Bash version
./federation-game/monitoring/deployment-verifier.sh --hook
```

### Manual Verification

```bash
# Check local deployment
python federation-game/monitoring/deployment_verifier.py --manual \
    --backend-url http://localhost

# Check remote deployment
python federation-game/monitoring/deployment_verifier.py --manual \
    --backend-url https://federation-game.deliberatefederation.cloud
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://localhost` | URL of the backend service |
| `DOCKER_COMPOSE_FILE` | `docker-compose.yml` | Path to docker-compose file |
| `DEPLOYMENT_ID` | timestamp | Unique deployment identifier |
| `ALERT_RECIPIENT` | `rig_dashboard` | Gastown recipient for alerts |

## Hook Integration

### Git Post-Push Hook (.git/hooks/post-push)

```bash
#!/bin/bash
# Run deployment verification after successful push
cd "$(dirname "$0")/.."
python federation-game/monitoring/deployment_verifier.py --hook
```

### CI/CD Pipeline (GitHub Actions)

```yaml
- name: Deploy
  run: |
    docker compose -f federation-game/docker-compose.yml up -d
    python federation-game/monitoring/deployment_verifier.py --hook
```

## Alert Format

On failure, the following alert is generated:

```
DEPLOYMENT VERIFICATION FAILED: [subject]
Details: [specific failure details]
```

Alerts are:
1. Printed to stdout
2. Written to `/tmp/deployment-verification.log`
3. Sent to Gastown dashboard via `gt_mail_send` (if available)

## Exit Codes

- `0` - All checks passed
- `1` - One or more checks failed

## Example Output

### Success

```
[INFO] Starting deployment verification
[INFO] Checking /healthz endpoint at http://localhost/healthz...
[INFO] Health check passed: HTTP 200
[INFO] Checking Docker container health...
[INFO] All containers are healthy
[INFO] All health checks passed successfully.
```

### Failure

```
[ERROR] Health endpoint returned HTTP 503 instead of 200
[ERROR] Found 1 unhealthy containers
==========================================
Deployment Verification Summary
==========================================
STATUS: FAILED

Failures detected:
  1. Health endpoint returned HTTP 503 instead of 200
  2. Container backend status: unhealthy (restarting)

DEPLOYMENT VERIFICATION FAILED: DEPLOYMENT VERIFICATION FAILED [20260526-025500]
```