#!/bin/bash
# Federation Deployment Verifier — runs after each deploy
# Checks: healthz, container status, backend logs for tracebacks
# Usage: /docker/federation-game/monitoring/watchdog_deploy.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/federation"
mkdir -p "$LOG_DIR"

echo "=== Deploy Verifier $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Wait 10 seconds for containers to stabilize after restart
sleep 10

# Run the deploy check
python3 "$SCRIPT_DIR/monitor.py" --check deploy
EXIT_CODE=$?

# Log result
if [ $EXIT_CODE -eq 2 ]; then
    echo "[CRITICAL] Deploy verification FAILED — action needed"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[WARNING] Deploy verification passed with warnings"
else
    echo "[OK] Deploy verified — all systems nominal"
fi

exit $EXIT_CODE
