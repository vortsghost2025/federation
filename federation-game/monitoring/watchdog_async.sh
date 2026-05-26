#!/bin/bash
# Federation Async Timeout Watcher — runs every 90 seconds
# Checks: /simulation/autonomous/status for hung ticks
# Called by cron (systemd timer preferred for 90s intervals — see setup notes)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/federation"
mkdir -p "$LOG_DIR"

echo "=== Async Timeout Watcher $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Run the async check
python3 "$SCRIPT_DIR/monitor.py" --check async
EXIT_CODE=$?

# Log exit code for downstream alerting
if [ $EXIT_CODE -eq 2 ]; then
    echo "[CRITICAL] Async watchdog detected critical issue"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[WARNING] Async watchdog detected warning"
else
    echo "[OK] Async watchdog all clear"
fi

exit $EXIT_CODE
