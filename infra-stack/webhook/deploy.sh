#!/bin/sh
# Deploy script triggered by webhook on push to main
set -e

LOG_FILE="/tmp/webhook-deploy.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Deploy triggered by GitHub push to main ==="

cd /docker/federation-game || exit 1

# Pull latest code
log "Running git pull origin main..."
git pull origin main 2>&1 >> "$LOG_FILE" || log "WARNING: git pull failed"

# Restart backend (bind-mounted, just needs restart)
log "Restarting backend..."
docker compose restart backend 2>&1 >> "$LOG_FILE" || log "WARNING: backend restart failed"

# Rebuild and restart worker (source baked into image)
log "Rebuilding worker..."
docker compose build worker 2>&1 >> "$LOG_FILE" || log "WARNING: worker build failed"
docker compose up -d worker 2>&1 >> "$LOG_FILE" || log "WARNING: worker restart failed"

# Restart frontend (HTML is bind-mounted but nginx may need reload for config changes)
log "Restarting frontend..."
docker compose restart frontend 2>&1 >> "$LOG_FILE" || log "WARNING: frontend restart failed"

log "=== Deploy complete ==="
