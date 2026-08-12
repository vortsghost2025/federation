#!/bin/bash
# Federation Tick Watchdog — runs every 60 seconds
# Checks: healthz, Redis connectivity, tick advancement
# Called by cron: * * * * * /docker/federation-game/monitoring/watchdog_tick.sh >> /var/log/federation/watchdog_tick.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/federation"
mkdir -p "$LOG_DIR"

echo "=== Tick Watchdog $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Run the tick check
python3 "$SCRIPT_DIR/monitor.py" --check tick
EXIT_CODE=$?

# Log exit code for downstream alerting
if [ $EXIT_CODE -eq 2 ]; then
    echo "[CRITICAL] Tick watchdog detected critical issue"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[WARNING] Tick watchdog detected warning"
else
    echo "[OK] Tick watchdog all clear"
fi

exit $EXIT_CODE
