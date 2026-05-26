#!/bin/sh
# GitHub Webhook Deploy Listener
# Listens on port 9101 for GitHub push events
# When a push to main is detected, pulls the latest code and restarts services

set -e

PORT="${PORT:-9101}"
GITHUB_SECRET="${GITHUB_SECRET:-changeme}"
COMPOSE_DIR="${COMPOSE_PROJECT_DIR:-/docker/federation-game}"
LOG_FILE="/tmp/webhook-deploy.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Start a simple HTTP server using netcat (available in alpine)
# This handles ONE request at a time — fine for a deploy webhook

log "Webhook deploy listener starting on port $PORT"

while true; do
    # Listen for incoming HTTP request
    REQUEST=$(nc -l -p "$PORT" -w 30 2>/dev/null) || continue

    # Extract the body (after blank line)
    BODY=$(echo "$REQUEST" | sed '1,/^$/d' | tr -d '\r')

    # Check if it's a push event to main
    REF=$(echo "$BODY" | grep -o '"ref":"refs/heads/main"' || true)

    if [ -n "$REF" ]; then
        log "Received push to main — triggering deploy..."

        # Send immediate 200 OK response
        RESPONSE="HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"deploying\",\"message\":\"Push to main detected, deploying...\"}\r\n"
        echo -e "$RESPONSE" | nc -w 1 127.0.0.1 "$PORT" 2>/dev/null || true

        # Run deploy in background
        (
            log "Starting git pull + deploy..."
            cd "$COMPOSE_DIR" || exit 1

            # Pull latest from git
            git pull origin main 2>&1 >> "$LOG_FILE" || log "WARNING: git pull failed"

            # Restart backend (bind-mounted, just needs restart)
            docker compose restart backend 2>&1 >> "$LOG_FILE" || log "WARNING: backend restart failed"

            # Rebuild worker if needed (source is baked into image)
            # docker compose build worker && docker compose up -d worker

            log "Deploy complete"
        ) &

    else
        # Not a push to main, or health check
        log "Received non-main event, ignoring"
    fi
done
